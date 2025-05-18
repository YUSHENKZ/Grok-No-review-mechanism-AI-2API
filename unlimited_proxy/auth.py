"""认证模块

提供API密钥验证和请求限速功能
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List, Callable
from fastapi import Request, HTTPException, Depends, Header, status
from fastapi.security import APIKeyHeader

from .api_key import get_api_key_manager, mask_api_key, RATE_LIMIT_ENABLED, RATE_LIMIT_DISABLED
from .config import config

# 设置日志
logger = logging.getLogger("unlimited_proxy.auth")

# 定义警告符号
WARNING_SYMBOL = "[!]"

# API密钥头部名称
API_KEY_HEADER = "Authorization"
API_KEY_QUERY = "api-key"

# API密钥统计
api_key_stats: Dict[str, Dict] = {}

# 请求计数
request_count = {
    "total": 0,
    "success": 0,
    "failed": 0,
    "auth_failed": 0,  # 认证失败的请求
    "rate_limited": 0,  # 超出速率限制的请求
    "expired_keys": 0,  # 使用过期密钥的请求
    "invalid_keys": 0,  # 使用无效密钥的请求
    "missing_keys": 0,  # 缺少密钥的请求
    "last_report": datetime.now().replace(minute=0, second=0, microsecond=0)
}

# 速率限制器
class RateLimiter:
    """基于滑动窗口的请求速率限制器"""
    
    def __init__(self, max_rate: int = 20, time_window: int = 60):
        """初始化速率限制器
        
        Args:
            max_rate: 时间窗口内允许的最大请求数
            time_window: 时间窗口大小(秒)
        """
        self.max_rate = max_rate
        self.time_window = time_window
        # 按"密钥+IP"组合进行限速，格式: {"密钥:IP": [时间戳列表]}
        self.request_history: Dict[str, List[float]] = {}
        # 使用INFO级别记录初始化信息，确保在标准日志级别下可见
        logger.info(f"初始化请求速率限制器 [最大速率:{max_rate}次/{time_window}秒]")
        
    def is_allowed(self, key: str, ip: str) -> bool:
        """检查请求是否被允许
        
        Args:
            key: 用于标识请求来源的键(API密钥)
            ip: 客户端IP地址
            
        Returns:
            bool: 请求是否被允许
        """
        # 组合键，格式为"密钥:IP"
        combined_key = f"{key}:{ip}"
        
        if combined_key not in self.request_history:
            self.request_history[combined_key] = []
            
        # 获取当前时间
        current_time = time.time()
        
        # 清理超过时间窗口的请求记录
        cutoff_time = current_time - self.time_window
        self.request_history[combined_key] = [t for t in self.request_history[combined_key] if t > cutoff_time]
        
        # 检查是否超过速率限制
        if len(self.request_history[combined_key]) >= self.max_rate:
            return False
            
        # 记录本次请求
        self.request_history[combined_key].append(current_time)
        return True
        
    def get_remaining(self, key: str, ip: str) -> int:
        """获取剩余的请求配额
        
        Args:
            key: 用于标识请求来源的键(API密钥)
            ip: 客户端IP地址
            
        Returns:
            int: 剩余的请求配额
        """
        # 组合键，格式为"密钥:IP"
        combined_key = f"{key}:{ip}"
        
        if combined_key not in self.request_history:
            return self.max_rate
            
        # 获取当前时间
        current_time = time.time()
        
        # 清理超过时间窗口的请求记录
        cutoff_time = current_time - self.time_window
        self.request_history[combined_key] = [t for t in self.request_history[combined_key] if t > cutoff_time]
        
        return max(0, self.max_rate - len(self.request_history[combined_key]))
        
    def get_retry_after(self, key: str, ip: str) -> int:
        """获取下一次请求可以尝试的时间(秒)
        
        Args:
            key: 用于标识请求来源的键(API密钥)
            ip: 客户端IP地址
            
        Returns:
            int: 建议的重试等待时间(秒)
        """
        # 组合键，格式为"密钥:IP"
        combined_key = f"{key}:{ip}"
        
        if combined_key not in self.request_history or not self.request_history[combined_key]:
            return 0
            
        # 获取最早的请求时间
        oldest_request = min(self.request_history[combined_key])
        current_time = time.time()
        
        # 计算需要等待的时间
        wait_time = max(0, self.time_window - (current_time - oldest_request))
        return int(wait_time) + 1  # 额外加1秒作为缓冲

# 速率限制器定义为None，使用时再通过函数动态初始化
rate_limiter = None  # 不在顶层代码初始化，避免配置还未加载完成的问题

def _get_rate_limiter():
    """获取速率限制器，如果未初始化则创建新实例"""
    global rate_limiter
    
    # 获取最新配置
    rate_limit_config = config.get_rate_limit_config()
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"当前速率限制配置: {rate_limit_config}")
    
    # 提取配置值
    max_rate = rate_limit_config.get("max_rate")
    time_window = rate_limit_config.get("time_window")
    
    # 备选逻辑：如果配置中没有值，尝试直接从config读取
    if max_rate is None:
        max_rate = config.get("api.max_request_rate")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"使用api.max_request_rate: {max_rate}")
    
    if time_window is None:
        time_window = config.get("api.time_window")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"使用api.time_window: {time_window}")
    
    # 确保有默认值
    if max_rate is None:
        max_rate = 10
        logger.warning(f"无法获取速率限制配置，使用默认值 max_rate={max_rate}")
    
    if time_window is None:
        time_window = 10
        logger.warning(f"无法获取速率限制配置，使用默认值 time_window={time_window}")
    
    # 初始化或更新速率限制器
    if rate_limiter is None:
        # 首次创建，始终输出INFO级别日志
        rate_limiter = RateLimiter(max_rate=max_rate, time_window=time_window)
        logger.info(f"创建速率限制器: max_rate={rate_limiter.max_rate}次/{rate_limiter.time_window}秒")
    elif rate_limiter.max_rate != max_rate or rate_limiter.time_window != time_window:
        # 配置已改变，重新创建并记录变化
        old_max_rate = rate_limiter.max_rate
        old_time_window = rate_limiter.time_window
        rate_limiter = RateLimiter(max_rate=max_rate, time_window=time_window)
        logger.info(f"更新速率限制器配置: {old_max_rate}次/{old_time_window}秒 -> {rate_limiter.max_rate}次/{rate_limiter.time_window}秒")
    else:
        # 配置未变化，但仍然输出DEBUG级别日志
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"使用现有速率限制器: max_rate={rate_limiter.max_rate}次/{rate_limiter.time_window}秒")
    
    return rate_limiter

# 定义API密钥验证器
api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)

async def verify_api_key(
    request: Request,
    api_key_header: Optional[str] = Depends(api_key_header),
) -> str:
    """验证API密钥
    
    检查请求头中的Authorization或查询参数中的api-key
    
    Args:
        request: FastAPI请求对象
        api_key_header: 从请求头中提取的API密钥
        
    Returns:
        str: 验证通过的API密钥
        
    Raises:
        HTTPException: 当API密钥无效、过期或请求超出速率限制时
    """
    # 确保使用最新的速率限制配置
    global rate_limiter
    rate_limit_config = config.get_rate_limit_config()
    # 如果配置发生变化，重新创建限速器
    if rate_limit_config["max_rate"] != rate_limiter.max_rate or rate_limit_config["time_window"] != rate_limiter.time_window:
        rate_limiter = RateLimiter(
            max_rate=rate_limit_config["max_rate"],
            time_window=rate_limit_config["time_window"]
        )
        logger.info(f"速率限制配置已更新 [最大速率:{rate_limiter.max_rate}次/{rate_limiter.time_window}秒]")
    
    # 获取客户端IP地址
    client_ip = request.client.host if request.client else "未知IP"
    
    # 判断是否启用API密钥保护
    api_key_protection = config.get("api.key_protection", False)
    if not api_key_protection:
        # 如果未启用API密钥保护，跳过验证
        # 但仍然进行限速检查，使用IP地址作为标识
        
        # 仅检查是否启用了全局速率限制
        enable_rate_limit = config.get("api.enable_rate_limit", True)
        if enable_rate_limit:
            path = request.url.path
            method = request.method
            
            # 对于未使用API密钥的情况，使用IP地址作为限速键，并使用一个特殊前缀
            ip_key = f"ip:{client_ip}"
            
            # 检查速率限制
            if not rate_limiter.is_allowed(ip_key, client_ip):
                request_count["failed"] += 1
                request_count["rate_limited"] += 1
                
                # 计算剩余的等待时间
                retry_after = rate_limiter.get_retry_after(ip_key, client_ip)
                
                # 记录超出限制的请求
                logger.warning(f"{WARNING_SYMBOL} 请求频率超限 [IP:{client_ip}] [路径:{path}] [等待:{retry_after}秒]")
                
                # 返回429状态码和重试信息
                headers = {"Retry-After": str(retry_after)}
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"请求频率超出限制，请等待{retry_after}秒后重试",
                    headers=headers
                )
                
            # 获取剩余配额
            remaining = rate_limiter.get_remaining(ip_key, client_ip)
            
            # 如果剩余配额较少，记录警告
            if remaining <= 3:
                logger.warning(f"{WARNING_SYMBOL} 请求配额即将用完 [IP:{client_ip}] [剩余:{remaining}]")
        
        return client_ip  # 返回IP地址作为标识
    
    start_time = time.time()
    request_count["total"] += 1
    
    # 获取请求信息
    path = request.url.path
    method = request.method
    
    # 使用INFO级别记录API请求基本信息
    logger.info(f"API请求 [{method}] [路径:{path}] [IP:{client_ip}]")
    
    api_key = None
    key_source = None
    
    # 从请求头中获取API密钥
    if api_key_header:
        # 检查Bearer前缀
        if api_key_header.startswith("Bearer "):
            api_key = api_key_header[7:]
            key_source = "Bearer头部"
        else:
            api_key = api_key_header
            key_source = "Authorization头部"
    
    # 从查询参数中获取API密钥
    if not api_key:
        api_key = request.query_params.get(API_KEY_QUERY)
        if api_key:
            key_source = "查询参数"
    
    # 如果没有找到API密钥
    if not api_key:
        request_count["failed"] += 1
        request_count["missing_keys"] += 1
        logger.warning(f"{WARNING_SYMBOL} 缺少API密钥 [方法:{method}] [路径:{path}] [IP:{client_ip}]")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证失败: 缺少API密钥",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 验证API密钥
    api_key_manager = get_api_key_manager()
    masked_key = mask_api_key(api_key)
    is_valid, error_message = api_key_manager.validate_key(api_key)
    
    if not is_valid:
        request_count["failed"] += 1
        request_count["auth_failed"] += 1
        
        # 判断是密钥过期还是无效密钥
        if "过期" in error_message:
            request_count["expired_keys"] += 1
            logger.warning(f"{WARNING_SYMBOL} 密钥已过期 [密钥:{masked_key}] [来源:{key_source}] [IP:{client_ip}]")
        else:
            request_count["invalid_keys"] += 1
            logger.warning(f"{WARNING_SYMBOL} 无效密钥 [密钥:{masked_key}] [来源:{key_source}] [IP:{client_ip}]")
        
        # 更新统计信息 - 失败次数
        if masked_key not in api_key_stats:
            api_key_stats[masked_key] = {"success": 0, "failed": 0, "last_failed": None, "last_success": None, "paths": {}}
        api_key_stats[masked_key]["failed"] += 1
        api_key_stats[masked_key]["last_failed"] = datetime.now()
        
        # 更新路径统计
        path_key = f"{method} {path}"
        if path_key not in api_key_stats[masked_key]["paths"]:
            api_key_stats[masked_key]["paths"][path_key] = {"success": 0, "failed": 0}
        api_key_stats[masked_key]["paths"][path_key]["failed"] += 1
        
        # 定期输出统计信息
        _check_and_output_stats()
            
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_message,
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # API密钥验证通过后，检查请求速率限制
    await _check_rate_limit(request, api_key)
    
    # 记录成功的API密钥使用
    request_count["success"] += 1
    key_name, expiry, _, _ = api_key_manager.api_keys[api_key]
    
    # 检查密钥是否即将过期
    if expiry:
        days_remaining = (expiry - datetime.now()).days
        if days_remaining <= 7:
            logger.warning(f"{WARNING_SYMBOL} 使用即将过期的密钥 [名称:{key_name}] [剩余:{days_remaining}天] [IP:{client_ip}]")
    
    # 更新统计信息 - 成功次数
    if masked_key not in api_key_stats:
        api_key_stats[masked_key] = {"success": 0, "failed": 0, "last_failed": None, "last_success": None, "paths": {}}
    api_key_stats[masked_key]["success"] += 1
    api_key_stats[masked_key]["last_success"] = datetime.now()
    
    # 更新路径统计
    path_key = f"{method} {path}"
    if path_key not in api_key_stats[masked_key]["paths"]:
        api_key_stats[masked_key]["paths"][path_key] = {"success": 0, "failed": 0}
    api_key_stats[masked_key]["paths"][path_key]["success"] += 1
    
    # 计算处理时间
    elapsed_ms = (time.time() - start_time) * 1000
    
    # 记录详细结果
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"密钥验证成功 [密钥:{masked_key}] [名称:{key_name}] [来源:{key_source}] [路径:{path}] [耗时:{elapsed_ms:.2f}ms]")
    else:
        # INFO级别只输出关键信息
        logger.info(f"API密钥有效 [名称:{key_name}] [耗时:{elapsed_ms:.2f}ms]")
    
    # 定期输出统计信息
    _check_and_output_stats()
    
    return api_key

async def _check_rate_limit(request: Request, key: str) -> str:
    """检查请求速率限制
    
    Args:
        request: FastAPI请求对象
        key: 用于标识请求来源的键(API密钥或IP地址)
        
    Returns:
        str: 传入的键
        
    Raises:
        HTTPException: 当请求超出速率限制时
    """
    # 获取客户端IP地址
    client_ip = request.client.host if request.client else "未知IP"
    
    # 检查是否启用全局请求速率限制
    enable_rate_limit = config.get("api.enable_rate_limit", True)
    
    # 检查该密钥是否有自定义限速设置
    api_key_manager = get_api_key_manager()
    key_rate_limit = api_key_manager.get_key_rate_limit_setting(key)
    
    # 确定是否对此密钥进行限速
    # 如果密钥设置为不限速，则跳过限速检查
    if key_rate_limit == RATE_LIMIT_DISABLED:
        return key
    
    # 如果密钥设置为限速，或全局设置为限速且密钥未指定，则进行限速
    if key_rate_limit == RATE_LIMIT_ENABLED or (enable_rate_limit and key_rate_limit is None):
        path = request.url.path
        method = request.method
        
        # 检查速率限制 - 使用"密钥+IP"组合
        if not rate_limiter.is_allowed(key, client_ip):
            request_count["failed"] += 1
            request_count["rate_limited"] += 1
            
            # 计算剩余的等待时间
            retry_after = rate_limiter.get_retry_after(key, client_ip)
            
            # 记录超出限制的请求
            logger.warning(f"{WARNING_SYMBOL} 请求频率超限 [密钥:{mask_api_key(key)}] [IP:{client_ip}] [路径:{path}] [等待:{retry_after}秒]")
            
            # 返回429状态码和重试信息
            headers = {"Retry-After": str(retry_after)}
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"请求频率超出限制，请等待{retry_after}秒后重试",
                headers=headers
            )
        
        # 获取剩余配额
        remaining = rate_limiter.get_remaining(key, client_ip)
        
        # 如果剩余配额较少，记录警告
        if remaining <= 3:
            logger.warning(f"{WARNING_SYMBOL} 请求配额即将用完 [密钥:{mask_api_key(key)}] [IP:{client_ip}] [剩余:{remaining}]")
    
    return key

def _check_and_output_stats():
    """检查并输出统计信息，每小时一次"""
    current_hour = datetime.now().replace(minute=0, second=0, microsecond=0)
    if current_hour > request_count["last_report"]:
        request_count["last_report"] = current_hour
        
        # 构建统计摘要
        stats_summary = [
            "-" * 50,
            "API请求统计:",
            f"总请求: {request_count['total']} | 成功: {request_count['success']} | 失败: {request_count['failed']}",
            f"认证失败: {request_count['auth_failed']} | 速率限制: {request_count['rate_limited']} | 过期密钥: {request_count['expired_keys']} | 无效密钥: {request_count['invalid_keys']} | 缺少密钥: {request_count['missing_keys']}",
            "-" * 30
        ]
        
        # 添加每个密钥的统计信息
        for key, stats in api_key_stats.items():
            # 基本统计
            summary_line = f"密钥 {key}: 成功 {stats['success']}次, 失败 {stats['failed']}次"
            
            # 最后成功/失败时间
            if stats["last_success"]:
                summary_line += f", 最后成功: {stats['last_success'].strftime('%m-%d %H:%M')}"
            if stats["last_failed"]:
                summary_line += f", 最后失败: {stats['last_failed'].strftime('%m-%d %H:%M')}"
                
            stats_summary.append(summary_line)
            
            # 详细的路径访问统计 - 仅输出前3个最常用路径
            if stats["paths"]:
                path_stats = []
                for path, path_count in stats["paths"].items():
                    path_stats.append((path, path_count["success"], path_count["failed"]))
                
                # 按照成功次数排序，取前3个
                top_paths = sorted(path_stats, key=lambda x: x[1] + x[2], reverse=True)[:3]
                for path, successes, failures in top_paths:
                    stats_summary.append(f"  - {path}: 成功 {successes}次, 失败 {failures}次")
        
        stats_summary.append("-" * 50)
        logger.info("\n".join(stats_summary))

def get_api_key_dependency():
    """获取API密钥依赖项
    
    根据配置决定是否启用API密钥验证
    
    Returns:
        Callable: 依赖项函数
    """
    # 查看配置是否启用API密钥保护
    api_key_protection = config.get("api.key_protection", False)
    
    if api_key_protection:
        return Depends(verify_api_key)
    return None 