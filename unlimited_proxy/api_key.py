"""API密钥管理模块

负责加载、验证和管理API密钥
"""

import os
import logging
from datetime import datetime
from typing import Dict, Optional, Tuple, List, Any
from pathlib import Path

# 设置日志
logger = logging.getLogger("unlimited_proxy.api_key")

# 定义警告符号
WARNING_SYMBOL = "[!]"

# 限速设置枚举
RATE_LIMIT_ENABLED = "rate_limit"  # 启用限速
RATE_LIMIT_DISABLED = "no_limit"   # 禁用限速
RATE_LIMIT_GLOBAL = None           # 使用全局设置

class APIKeyManager:
    """API密钥管理器

    负责加载和验证API密钥
    """
    
    def __init__(self, key_file: str = ".KEY"):
        """初始化API密钥管理器
        
        Args:
            key_file: API密钥配置文件路径
        """
        self.key_file = key_file
        # 存储格式: {密钥: (名称, 过期时间, 限速设置, 限速值)}
        self.api_keys: Dict[str, Tuple[str, Optional[datetime], Optional[str], Optional[int]]] = {}
        self.key_rate_limits: Dict[str, int] = {}  # 用于存储密钥的自定义限速值
        logger.info(f"初始化API密钥管理器 [配置文件:{key_file}]")
        self.load_api_keys()
        
    def load_api_keys(self) -> None:
        """从配置文件加载API密钥"""
        try:
            key_path = Path(self.key_file)
            if not key_path.exists():
                logger.warning(f"{WARNING_SYMBOL} API密钥配置文件不存在 [路径:{self.key_file}]")
                return
                
            logger.debug(f"开始加载API密钥 [路径:{key_path.absolute()}]")
            with open(key_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            # 统计信息
            valid_keys = 0
            invalid_keys = 0
            expired_keys = 0
            permanent_keys = 0
            near_expiry_keys = 0
            rate_limited_keys = 0
            unlimited_keys = 0
            custom_rate_limit_keys = 0
            
            # 收集详细信息用于后续汇总输出
            valid_key_infos: List[str] = []
            expired_key_infos: List[str] = []
            warning_key_infos: List[str] = []
            
            for line_number, line in enumerate(lines, 1):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                    
                try:
                    # 解析密钥行: 密钥名=密钥值=过期时间[=限速设置[:限速值]]
                    parts = line.split('=')
                    if len(parts) < 2:
                        logger.warning(f"格式错误的API密钥配置 [行:{line_number}]")
                        invalid_keys += 1
                        continue
                        
                    # 密钥名和值是必须的
                    key_name = parts[0].strip()
                    key_value = parts[1].strip()
                    
                    # 解析过期时间（第3部分，如果存在）
                    expiry_str = parts[2].strip() if len(parts) > 2 else "permanent"
                    expiry = None
                    is_permanent = False
                    
                    # 解析限速设置（第4部分，如果存在）
                    rate_limit_setting = None
                    rate_limit_value = None
                    if len(parts) > 3:
                        rate_limit_part = parts[3].strip().lower()
                        
                        # 检查是否包含限速值（格式如：rate_limit:30）
                        if ":" in rate_limit_part:
                            rate_setting, rate_value = rate_limit_part.split(":", 1)
                            rate_setting = rate_setting.strip()
                            
                            if rate_setting == "rate_limit":
                                rate_limit_setting = RATE_LIMIT_ENABLED
                                rate_limited_keys += 1
                                try:
                                    rate_limit_value = int(rate_value.strip())
                                    custom_rate_limit_keys += 1
                                    # 保存自定义限速值
                                    self.key_rate_limits[key_value] = rate_limit_value
                                    logger.debug(f"密钥 {mask_api_key(key_value)} 设置自定义限速: {rate_limit_value}次/窗口")
                                except ValueError:
                                    logger.warning(f"无效的限速值 [行:{line_number}, 值:{rate_value}]，将使用默认值")
                            elif rate_setting == "no_limit":
                                rate_limit_setting = RATE_LIMIT_DISABLED
                                unlimited_keys += 1
                        else:
                            # 传统格式，没有限速值
                            if rate_limit_part == "rate_limit":
                                rate_limit_setting = RATE_LIMIT_ENABLED
                                rate_limited_keys += 1
                            elif rate_limit_part == "no_limit":
                                rate_limit_setting = RATE_LIMIT_DISABLED
                                unlimited_keys += 1
                    
                    if expiry_str.lower() == 'permanent':
                        is_permanent = True
                        permanent_keys += 1
                        valid_key_infos.append(format_api_key_info(key_value, key_name, None, rate_limit_setting, rate_limit_value))
                    else:
                        try:
                            expiry = datetime.strptime(expiry_str, '%Y-%m-%d')
                            # 检查是否已过期
                            if datetime.now() > expiry:
                                expired_keys += 1
                                expired_key_infos.append(format_api_key_info(key_value, key_name, expiry, rate_limit_setting, rate_limit_value))
                            else:
                                days_remaining = (expiry - datetime.now()).days
                                valid_keys += 1
                                
                                # 记录即将过期的密钥
                                if days_remaining <= 30:
                                    near_expiry_keys += 1
                                    if days_remaining <= 7:
                                        warning_key_infos.append(format_api_key_info(key_value, key_name, expiry, rate_limit_setting, rate_limit_value))
                                    
                                valid_key_infos.append(format_api_key_info(key_value, key_name, expiry, rate_limit_setting, rate_limit_value))
                        except ValueError:
                            logger.warning(f"无效的过期时间格式 [行:{line_number}, 值:{expiry_str}]")
                            invalid_keys += 1
                            continue
                            
                    # 存储密钥信息（名称、过期时间、限速设置、限速值）
                    self.api_keys[key_value] = (key_name, expiry, rate_limit_setting, rate_limit_value)
                    
                except Exception as e:
                    logger.error(f"处理API密钥时出错 [行:{line_number}, 错误:{str(e)}]")
                    invalid_keys += 1
            
            # 汇总输出日志
            total_keys = valid_keys + permanent_keys
            
            if total_keys > 0:
                logger.info(f"API密钥加载完成 [有效:{total_keys}, 永久:{permanent_keys}, 限期:{valid_keys}, 过期:{expired_keys}, 无效:{invalid_keys}]")
                logger.info(f"限速设置 [启用限速:{rate_limited_keys}, 禁用限速:{unlimited_keys}, 使用全局设置:{total_keys-(rate_limited_keys+unlimited_keys)}]")
                if custom_rate_limit_keys > 0:
                    logger.info(f"自定义限速 [密钥数:{custom_rate_limit_keys}]")
                
                # 如果负载有限的密钥很少，发出警告
                if total_keys == 1:
                    logger.warning(f"{WARNING_SYMBOL} 警告: 只加载了1个有效API密钥，建议添加更多密钥提高可用性")
            else:
                logger.warning(f"{WARNING_SYMBOL} 警告: 未加载任何有效的API密钥，所有API请求将被拒绝")
            
            # 如果有即将过期的密钥，输出警告
            if near_expiry_keys > 0:
                logger.warning(f"{WARNING_SYMBOL} 检测到 {near_expiry_keys} 个API密钥将在30天内过期")
                
            # 如果有7天内即将过期的密钥，单独输出警告
            for warning_info in warning_key_infos:
                logger.warning(f"{WARNING_SYMBOL} API密钥即将过期: {warning_info}")
                
            # 如果配置了DEBUG级别，输出所有有效密钥信息
            if logger.isEnabledFor(logging.DEBUG):
                for key_info in valid_key_infos:
                    logger.debug(f"有效API密钥: {key_info}")
                    
            # 如果配置了DEBUG级别，输出所有过期密钥信息
            if logger.isEnabledFor(logging.DEBUG) and expired_key_infos:
                for key_info in expired_key_infos:
                    logger.debug(f"过期API密钥: {key_info}")
            
        except Exception as e:
            logger.error(f"加载API密钥配置文件时出错 [错误:{str(e)}]")
    
    def get_key_info(self, api_key: str) -> Dict[str, Any]:
        """获取API密钥的详细信息
        
        Args:
            api_key: API密钥
            
        Returns:
            Dict: 包含密钥信息的字典，如果密钥不存在则返回空字典
        """
        if api_key not in self.api_keys:
            return {}
            
        key_name, expiry, rate_limit_setting, rate_limit_value = self.api_keys[api_key]
        info = {
            'name': key_name,
            'expiry': expiry,
            'rate_limit': rate_limit_setting
        }
        
        # 如果有自定义限速值，添加到结果中
        if rate_limit_value is not None:
            info['rate_limit_value'] = rate_limit_value
            
        return info
        
    def get_key_rate_limit(self, api_key: str) -> Optional[int]:
        """获取API密钥的自定义限速值
        
        Args:
            api_key: API密钥
            
        Returns:
            Optional[int]: 密钥的自定义限速值，如果没有设置则返回None
        """
        return self.key_rate_limits.get(api_key)

    def validate_key(self, api_key: str) -> Tuple[bool, Optional[str]]:
        """验证API密钥
        
        Args:
            api_key: 要验证的API密钥
            
        Returns:
            Tuple[bool, Optional[str]]: (是否有效, 错误消息)
        """
        # 检查密钥是否存在
        if api_key not in self.api_keys:
            masked_key = mask_api_key(api_key)
            logger.warning(f"{WARNING_SYMBOL} API密钥验证失败: 未找到密钥 [{masked_key}]")
            return False, "认证失败: 无效的API密钥"
            
        # 检查密钥是否过期
        key_name, expiry, _, _ = self.api_keys[api_key]
        if expiry and datetime.now() > expiry:
            days_expired = (datetime.now() - expiry).days
            masked_key = mask_api_key(api_key)
            logger.warning(f"{WARNING_SYMBOL} API密钥验证失败: 密钥已过期 [名称:{key_name}, 过期天数:{days_expired}]")
            return False, f"认证失败: API密钥 {key_name} 已过期"
            
        # 密钥有效
        masked_key = mask_api_key(api_key)
        if expiry:
            days_remaining = (expiry - datetime.now()).days
            expiry_str = f", 剩余:{days_remaining}天"
            
            # 使用INFO级别警告即将过期的密钥
            if days_remaining <= 7:
                logger.info(f"API密钥即将过期 [名称:{key_name}, 剩余天数:{days_remaining}]")
        else:
            expiry_str = ", 永久有效"
        
        logger.debug(f"API密钥验证成功 [名称:{key_name}, 密钥:{masked_key}{expiry_str}]")
        return True, None
    
    def get_key_rate_limit_setting(self, api_key: str) -> Optional[str]:
        """获取API密钥的限速设置
        
        Args:
            api_key: API密钥
            
        Returns:
            Optional[str]: 限速设置，可能的值:
                - "rate_limit": 启用限速
                - "no_limit": 禁用限速
                - None: 使用全局设置
        """
        if api_key not in self.api_keys:
            return None
            
        _, _, rate_limit_setting, _ = self.api_keys[api_key]
        return rate_limit_setting
        
    def reload_keys(self) -> bool:
        """重新加载API密钥
        
        Returns:
            bool: 重载是否成功
        """
        logger.info(f"开始重新加载API密钥 [文件:{self.key_file}]")
        old_keys_count = len(self.api_keys)
        old_keys = set(self.api_keys.keys())
        
        try:
            self.api_keys.clear()
            self.key_rate_limits.clear()
            self.load_api_keys()
            
            new_keys_count = len(self.api_keys)
            new_keys = set(self.api_keys.keys())
            
            # 计算变化
            added_keys = new_keys - old_keys
            removed_keys = old_keys - new_keys
            
            # 记录变更详情
            if added_keys:
                logger.info(f"新增API密钥: {len(added_keys)}个")
                
            if removed_keys:
                logger.info(f"移除API密钥: {len(removed_keys)}个")
                
            # 比较前后变化
            if new_keys_count > old_keys_count:
                change_text = f"增加{new_keys_count - old_keys_count}个"
            elif new_keys_count < old_keys_count:
                change_text = f"减少{old_keys_count - new_keys_count}个"
            else:
                change_text = "数量不变"
                
            logger.info(f"API密钥重新加载完成 [原有:{old_keys_count}, 现有:{new_keys_count}, {change_text}]")
            return True
        except Exception as e:
            logger.error(f"重新加载API密钥失败 [错误:{str(e)}]")
            return False

def mask_api_key(api_key: str) -> str:
    """掩码API密钥，只显示前4位和后4位
    
    Args:
        api_key: 完整的API密钥
        
    Returns:
        str: 掩码后的API密钥
    """
    if not api_key:
        return "无效密钥"
        
    if len(api_key) <= 8:
        return api_key[:2] + "***" + (api_key[-2:] if len(api_key) > 3 else "")
        
    return api_key[:4] + "***" + api_key[-4:]

def format_api_key_info(api_key: str, key_name: str, expiry: Optional[datetime], rate_limit: Optional[str] = None, rate_limit_value: Optional[int] = None) -> str:
    """格式化API密钥信息用于日志输出
    
    Args:
        api_key: API密钥
        key_name: 密钥名称
        expiry: 过期时间
        rate_limit: 限速设置
        rate_limit_value: 限速值
        
    Returns:
        str: 格式化的密钥信息
    """
    masked_key = mask_api_key(api_key)
    expiry_str = "永久有效" if expiry is None else expiry.strftime("%Y-%m-%d")
    
    # 如果有过期时间，计算剩余天数
    days_str = ""
    if expiry:
        days = (expiry - datetime.now()).days
        if days > 0:
            days_str = f", 剩余{days}天"
        elif days == 0:
            days_str = ", 今日过期"
        else:
            days_str = f", 已过期{-days}天"
    
    # 添加限速设置信息
    rate_limit_str = ""
    if rate_limit == RATE_LIMIT_ENABLED:
        rate_limit_str = ", 启用限速"
    elif rate_limit == RATE_LIMIT_DISABLED:
        rate_limit_str = ", 禁用限速"
    
    # 添加限速值信息
    rate_value_str = ""
    if rate_limit_value is not None:
        rate_value_str = f", 限速值:{rate_limit_value}"
    
    return f"{key_name} [{masked_key}] ({expiry_str}{days_str}{rate_limit_str}{rate_value_str})"

# 创建单例实例
api_key_manager = None

def get_api_key_manager() -> APIKeyManager:
    """获取API密钥管理器实例"""
    global api_key_manager
    if api_key_manager is None:
        from .config import config
        api_key_manager = APIKeyManager(config.get("api.key_file", ".KEY"))
    return api_key_manager 