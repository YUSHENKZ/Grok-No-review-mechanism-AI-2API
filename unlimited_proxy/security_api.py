"""
安全管理API扩展模块

提供API限速统计信息查询功能。
"""

import logging
import time
from typing import Dict, Any
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import JSONResponse

# 导入安全模块函数
from .security import get_security_stats

# 配置日志
logger = logging.getLogger("unlimited_proxy.security_api")

# 创建路由器
security_router = APIRouter(prefix="/security/api", tags=["security"])

# 辅助函数：验证管理员访问权限
async def verify_admin_access(request: Request):
    """验证管理员访问权限的依赖函数
    
    Args:
        request: FastAPI请求对象
        
    Returns:
        客户端IP和管理密钥
    """
    # 获取客户端IP
    client_ip = request.client.host if request.client else "unknown"
    
    # 这里由于移除了之前的安全验证功能，我们暂时允许所有请求访问
    # 在实际项目中，您应该实现适当的管理员访问控制
    
    return {"client_ip": client_ip}

@security_router.get("/status")
async def api_status(admin_data: Dict = Depends(verify_admin_access)):
    """检查安全管理API状态
    
    Returns:
        API状态信息
    """
    client_ip = admin_data["client_ip"]
    
    # 记录管理API访问日志
    logger.info(f"管理API访问成功: [IP:{client_ip}] [端点:status]")
    
    return {
        "status": "ok",
        "timestamp": int(time.time()),
        "message": "API限速管理API运行正常",
        "api_version": "1.0"
    }

@security_router.get("/stats")
async def get_security_stats_route(admin_data: Dict = Depends(verify_admin_access)):
    """获取API限速统计信息
    
    Returns:
        安全统计信息
    """
    client_ip = admin_data["client_ip"]
    
    # 获取安全统计信息
    stats = get_security_stats()
    
    # 记录管理API访问日志
    logger.info(f"管理API访问成功: [IP:{client_ip}] [端点:stats]")
    
    return {
        "status": "ok",
        "timestamp": int(time.time()),
        **stats  # 展开统计信息到响应中
    } 