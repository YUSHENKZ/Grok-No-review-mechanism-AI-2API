"""
安全模块

提供API请求限速和API密钥验证功能。
集成在API配置中，不需要单独配置。
"""

import os
import time
import json
import logging
import re
import traceback
from typing import Dict, List, Set, Tuple, Optional
from datetime import datetime
import threading
from collections import defaultdict, Counter

# 配置导入
try:
    from .config import config
except (ImportError, ValueError):
    try:
        # 直接导入，用于单元测试
        from config import config
    except ImportError:
        # 创建一个空的配置对象用于测试
        class MockConfig:
            def get(self, key, default=None):
                return default
            def __getitem__(self, key):
                return None
        config = MockConfig()

# 其他导入
try:
    from .api_key import APIKeyManager, RATE_LIMIT_ENABLED, RATE_LIMIT_DISABLED, get_api_key_manager
except (ImportError, ValueError):
    # 创建模拟对象用于测试
    APIKeyManager = None
    RATE_LIMIT_ENABLED = "enabled"
    RATE_LIMIT_DISABLED = "disabled"
    get_api_key_manager = lambda: None

logger = logging.getLogger("security")

# 全局变量
RATE_LIMIT_COUNTERS: Dict[str, List[float]] = defaultdict(list)  # IP速率限制计数器
API_RATE_LIMIT_COUNTERS: Dict[str, List[float]] = defaultdict(list)  # API密钥速率限制计数器

# API密钥速率限制
SECURITY_API_RATE_LIMIT = False
SECURITY_DEFAULT_API_RATE = 20
SECURITY_API_RATE_CONFIG = {}  # 格式: {api_key: rate_limit}

# 默认配置值
GLOBAL_RATE_LIMIT_ENABLED = True  # 是否启用全局速率限制
GLOBAL_RATE_LIMIT_MAX = 30  # 全局最大请求速率
GLOBAL_RATE_LIMIT_WINDOW = 70  # 全局时间窗口（秒）

# 线程锁
security_lock = threading.Lock()

def load_security_config(force_refresh=True) -> None:
    """
    加载安全配置参数
    
    Args:
        force_refresh: 是否强制刷新配置，如果为True，则忽略缓存
    """
    global GLOBAL_RATE_LIMIT_ENABLED, GLOBAL_RATE_LIMIT_MAX, GLOBAL_RATE_LIMIT_WINDOW
    global SECURITY_API_RATE_LIMIT, SECURITY_DEFAULT_API_RATE, SECURITY_API_RATE_CONFIG
    
    if force_refresh:
        # 调用配置模块重新加载环境变量
        try:
            from dotenv import load_dotenv
            load_dotenv(".env", override=True, verbose=True)
            
            # 重新加载安全配置 - 如果可能的话
            try:
                from .config import _load_security_config_from_env
                _load_security_config_from_env()
                logger.info("[SECURITY] 强制刷新配置完成")
            except ImportError:
                logger.warning("[SECURITY] 无法导入_load_security_config_from_env函数，跳过强制刷新")
        except ImportError:
            logger.warning("[SECURITY] 未安装python-dotenv，无法刷新环境变量")
    
    # 直接从配置对象读取值，不提供默认值
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("[SECURITY] 安全模块从config读取配置")
    
    # 读取并设置IP限制配置
    ip_limit_enabled = config.get("api.enable_rate_limit")
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"读取 api.enable_rate_limit: {ip_limit_enabled}")
    GLOBAL_RATE_LIMIT_ENABLED = ip_limit_enabled if ip_limit_enabled is not None else True
    
    ip_max_rate = config.get("api.max_request_rate")
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"读取 api.max_request_rate: {ip_max_rate}")
    GLOBAL_RATE_LIMIT_MAX = ip_max_rate if ip_max_rate is not None else 10
    
    ip_time_window = config.get("api.time_window")
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"读取 api.time_window: {ip_time_window}")
    GLOBAL_RATE_LIMIT_WINDOW = ip_time_window if ip_time_window is not None else 10
    
    # 读取并设置API密钥限制配置
    key_limit_enabled = config.get("api.key_rate_limit")
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"读取 api.key_rate_limit: {key_limit_enabled}")
    SECURITY_API_RATE_LIMIT = key_limit_enabled if key_limit_enabled is not None else True
    
    key_default_rate = config.get("api.default_key_rate")
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"读取 api.default_key_rate: {key_default_rate}")
    SECURITY_DEFAULT_API_RATE = key_default_rate if key_default_rate is not None else 10
    
    # 配置已加载完成，显示最终值
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("[SECURITY] 安全模块最终配置值")
        logger.debug(f"IP限速: {'启用' if GLOBAL_RATE_LIMIT_ENABLED else '禁用'}, {GLOBAL_RATE_LIMIT_MAX}次/{GLOBAL_RATE_LIMIT_WINDOW}秒")
        logger.debug(f"密钥限速: {'启用' if SECURITY_API_RATE_LIMIT else '禁用'}, 默认{SECURITY_DEFAULT_API_RATE}次/{GLOBAL_RATE_LIMIT_WINDOW}秒")
    
    # 清空并重新加载API速率配置
    SECURITY_API_RATE_CONFIG.clear()
    
    # 1. 首先加载配置文件中的速率配置
    api_rate_config_str = config.get("api.key_rate_config", "")
    if api_rate_config_str:
        configs = api_rate_config_str.split(";")
        for config_item in configs:
            if "=" in config_item:
                key, rate_str = config_item.split("=", 1)
                try:
                    SECURITY_API_RATE_CONFIG[key.strip()] = int(rate_str.strip())
                except ValueError:
                    logger.warning(f"无效的API密钥限速配置: {config_item}，将被忽略")
    
    # 2. 从API密钥管理器获取自定义限速设置
    try:
        from .api_key import get_api_key_manager
        api_key_manager = get_api_key_manager()
        if api_key_manager:
            custom_rate_limits = 0
            # 获取key_rate_limits字典中的自定义限速
            for api_key, rate_value in api_key_manager.key_rate_limits.items():
                if rate_value is not None and rate_value > 0:
                    SECURITY_API_RATE_CONFIG[api_key] = rate_value
                    custom_rate_limits += 1
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"从API密钥管理器获取自定义限速: 密钥={api_key[:8]}..., 值={rate_value}")
            
            if logger.isEnabledFor(logging.DEBUG) and custom_rate_limits > 0:
                logger.debug(f"成功加载 {custom_rate_limits} 个自定义限速规则")
    except Exception as e:
        logger.warning(f"获取API密钥自定义限速配置时出错: {e}", exc_info=True)
    
    # 无论是否强制刷新，都始终输出详细配置信息
    logger.info("==================== API访问控制配置 ====================")
    logger.info(f"  - IP请求限速: {'已启用' if GLOBAL_RATE_LIMIT_ENABLED else '已禁用'}")
    logger.info(f"  - IP限速配置: {GLOBAL_RATE_LIMIT_MAX}次/{GLOBAL_RATE_LIMIT_WINDOW}秒")
    logger.info(f"  - API密钥限速: {'已启用' if SECURITY_API_RATE_LIMIT else '已禁用'}")
    logger.info(f"  - 密钥默认限速: {SECURITY_DEFAULT_API_RATE}次/{GLOBAL_RATE_LIMIT_WINDOW}秒")
    logger.info(f"  - 自定义限速规则: {len(SECURITY_API_RATE_CONFIG)}个")
    logger.info("=======================================================")

def is_rate_limited(ip: str, api_key: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """检查请求是否超过速率限制
    
    Args:
        ip: 客户端IP地址
        api_key: API密钥（如果有）
        
    Returns:
        Tuple[bool, Optional[str]]: (是否超过限制, 错误信息)
    """
    # 1. 检查API密钥速率限制
    if api_key and SECURITY_API_RATE_LIMIT:
        # 获取API密钥的速率限制
        api_manager = get_api_key_manager()
        if api_manager:
            key_info = api_manager.get_key_info(api_key)
            if key_info:
                # 如果API密钥设置为不限速
                if key_info.get('rate_limit') == RATE_LIMIT_DISABLED:
                    return False, None
                # 如果API密钥设置为必须限速
                elif key_info.get('rate_limit') == RATE_LIMIT_ENABLED:
                    # 获取特定API密钥的限制
                    # 首先检查密钥中是否有自定义限速值
                    if 'rate_limit_value' in key_info:
                        rate_limit = key_info['rate_limit_value']
                        logger.debug(f"使用密钥内自定义限速值: {rate_limit}次/{GLOBAL_RATE_LIMIT_WINDOW}秒")
                    else:
                        # 然后检查全局自定义限速配置
                        rate_limit = SECURITY_API_RATE_CONFIG.get(api_key, SECURITY_DEFAULT_API_RATE)
                        
                    # 检查API密钥的速率限制
                    is_limited = _check_rate_limit(api_key, API_RATE_LIMIT_COUNTERS, rate_limit, GLOBAL_RATE_LIMIT_WINDOW)
                    if is_limited:
                        logger.info(f"API密钥 {api_key[:8]}... 超出请求限制: {rate_limit}次/{GLOBAL_RATE_LIMIT_WINDOW}秒")
                        return True, f"API密钥请求频率超出限制 ({rate_limit}次/{GLOBAL_RATE_LIMIT_WINDOW}秒)，请稍后再试"
    
    # 2. 检查全局请求限速
    if GLOBAL_RATE_LIMIT_ENABLED:
        limited = _check_rate_limit(ip, RATE_LIMIT_COUNTERS, GLOBAL_RATE_LIMIT_MAX, GLOBAL_RATE_LIMIT_WINDOW)
        if limited:
            logger.info(f"IP {ip} 超出请求限制: {GLOBAL_RATE_LIMIT_MAX}次/{GLOBAL_RATE_LIMIT_WINDOW}秒")
            return True, f"请求频率超出限制 ({GLOBAL_RATE_LIMIT_MAX}次/{GLOBAL_RATE_LIMIT_WINDOW}秒)，请稍后再试"
    
    # 未超出限制
    return False, None

def _check_rate_limit(key: str, counter_dict: Dict[str, List[float]], limit: int, window: int) -> bool:
    """内部函数：检查是否超过速率限制
    
    使用滑动窗口算法检查请求速率
    
    Args:
        key: 限速键（IP或API密钥）
        counter_dict: 计数器字典
        limit: 请求数限制
        window: 时间窗口（秒）
        
    Returns:
        bool: 如果超过限制返回True，否则返回False
    """
    current_time = time.time()
    
    # 添加当前请求时间戳
    counter_dict[key].append(current_time)
    
    # 清理过期的请求记录
    counter_dict[key] = [t for t in counter_dict[key] 
                       if current_time - t < window]
    
    # 检查请求数是否超过限制
    return len(counter_dict[key]) > limit

def get_security_stats() -> Dict:
    """获取API限速统计信息
    
    Returns:
        Dict: 包含API限速统计信息的字典
    """
    return {
        "API访问控制": {
            "IP请求限速": "已启用" if GLOBAL_RATE_LIMIT_ENABLED else "已禁用",
            "IP限速配置": f"{GLOBAL_RATE_LIMIT_MAX}次/{GLOBAL_RATE_LIMIT_WINDOW}秒",
            "API密钥限速": "已启用" if SECURITY_API_RATE_LIMIT else "已禁用",
            "密钥默认限速": f"{SECURITY_DEFAULT_API_RATE}次/{GLOBAL_RATE_LIMIT_WINDOW}秒",
            "自定义限速规则": len(SECURITY_API_RATE_CONFIG),
            "当前限速IP数": len(RATE_LIMIT_COUNTERS),
            "当前限速密钥数": len(API_RATE_LIMIT_COUNTERS)
        }
    } 