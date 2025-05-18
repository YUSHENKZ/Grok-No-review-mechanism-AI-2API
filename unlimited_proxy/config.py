"""
配置管理模块

处理应用程序配置、环境变量和全局设置。
"""

import os
import json
import logging
import logging.config
import random
import re
from pathlib import Path
from typing import Dict, Any, Optional, List, Union

# 强制覆盖配置 - 无论环境变量如何都使用这些值
# 设置为空字典以禁用强制配置，完全使用环境变量值
FORCE_SETTINGS = {}

# 初始化标记
loaded = False

# 设置基础日志，用于初始化阶段
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# 尝试导入dotenv，如果未安装则忽略
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        pass

# 基础路径
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

# 加载环境变量，调整参数以支持注释处理
load_dotenv(ENV_FILE, override=True, verbose=True)

# 默认配置
DEFAULT_CONFIG = {
    "api": {
        "token_endpoint": "/api/token",
        "chat_endpoint": "/api/chat",
        "timeout": 60.0,
        "connect_timeout": 10.0,
        "read_timeout": 120.0,
        "write_timeout": 20.0,
        "pool_timeout": 10.0,
        "empty_response_timeout": 5.0,
        "max_retries": 5,
        "max_token_retries": 2,
        "initial_retry_delay_ms": 100,
        "max_retry_delay_ms": 5000
    },
    "server": {
        "host": "127.0.0.1",
        "port": 8000,
        "workers": 1,
        "reload": False,
        "cors_origins": ["*"],
        "log_level": "info",
        "debug": False,
        "request_timeout": 300,
        "timeout_keep_alive": 120,
        "timeout_graceful_shutdown": 10,
        "limit_concurrency": 100,
        "backlog": 128,
        "ssl_cert": None,
        "ssl_key": None,
        "docs_enabled": True
    },
    "token": {
        "memory_cache": True,
        "cache_enabled": True,
        "cache_ttl": 3600,
        "db_path": str(BASE_DIR / "tokens.db"),
        "storage_path": ".unlimited",
        "storage_type": "sqlite",
        "redis_url": "redis://localhost:6379/0",
        "rotation_enabled": True,
        "cache_size": 5,
        "auto_refresh": True
    },
    "proxy": {
        "http": None,
        "https": None,
        "enabled": False
    },
    "models": {
        "default": "chat-model-reasoning",
        "available": [
            "chat-model-reasoning",
            "chat-model-reasoning-thinking"
        ],
        "model_config": {
            "chat-model-reasoning": {
                "description": "UnlimitedAI标准模型",
                "thinking_enabled": False
            },
            "chat-model-reasoning-thinking": {
                "description": "UnlimitedAI带推理的增强模型",
                "thinking_enabled": True
            }
        }
    },
    "performance": {
        "http2_enabled": True,
        "connection_pool_size": 100,
        "keep_alive_connections": 20,
        "keepalive_expiry": 30.0
    },
    "api_key": {
        "protection": False,
        "file": ".KEY"
    },
    # 安全配置
    "security": {
        "enable_ip_blocking": True,  # 是否启用IP封禁功能
        "block_threshold": 10,       # 可疑请求达到此阈值时封禁IP
        "block_duration": 3600,      # 封禁持续时间（秒）
        "ip_whitelist": ["127.0.0.1"],  # IP白名单
        "suspicious_patterns": [     # 自定义可疑请求模式（正则表达式）
            # 默认已包含多种常见攻击模式，此处可添加补充
        ]
    }
}

# 浏览器配置集合
BROWSER_CONFIGS = [
    # Chrome Windows
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Google Chrome\";v=\"135\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"135\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"Windows\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Chrome MacOS
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Google Chrome\";v=\"135\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"135\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"macOS\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Chrome Linux
    {
        "user_agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Google Chrome\";v=\"135\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"135\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"Linux\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Firefox Windows
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        # Firefox 不发送 sec-ch-ua 系列请求头
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Safari MacOS
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        # Safari 不发送 sec-ch-ua 系列请求头
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Edge Windows
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/121.0.0.0 Safari/537.36",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Microsoft Edge\";v=\"121\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"121\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"Windows\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # 添加原始USER_AGENTS中的浏览器配置
    # Chrome Windows 旧版本
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Google Chrome\";v=\"108\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"108\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"Windows\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Safari MacOS 旧版本
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        # Safari 不发送 sec-ch-ua 系列请求头
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Edge Windows 旧版本
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.2151.44",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Microsoft Edge\";v=\"119\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"119\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"Windows\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Chrome Windows 其他版本
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Google Chrome\";v=\"119\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"119\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"Windows\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Chrome MacOS 其他版本
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Google Chrome\";v=\"119\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"119\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"macOS\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Chrome Linux 其他版本
    {
        "user_agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Google Chrome\";v=\"119\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"119\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"Linux\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Chrome Windows 120版本
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Google Chrome\";v=\"120\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"120\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"Windows\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Chrome Windows 121版本
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Google Chrome\";v=\"121\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"121\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"Windows\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Chrome Windows 122版本
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.112 Safari/537.36",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Google Chrome\";v=\"122\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"122\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"Windows\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Chrome Windows WOW64
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Google Chrome\";v=\"120\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"120\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"Windows\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Chrome Windows 旧版操作系统
    {
        "user_agent": "Mozilla/5.0 (Windows NT 6.3; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Google Chrome\";v=\"121\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"121\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"Windows\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Chrome MacOS 10_15_8
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Google Chrome\";v=\"120\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"120\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"macOS\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Chrome MacOS 11_6_0
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 11_6_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Google Chrome\";v=\"121\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"121\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"macOS\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Chrome MacOS 12_0_1
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_0_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.112 Safari/537.36",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Google Chrome\";v=\"122\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"122\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"macOS\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Chrome Linux 120版本
    {
        "user_agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Google Chrome\";v=\"120\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"120\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"Linux\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Chrome Fedora Linux
    {
        "user_agent": "Mozilla/5.0 (X11; Fedora; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Google Chrome\";v=\"121\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"121\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"Linux\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Chrome Ubuntu Linux
    {
        "user_agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.6261.112 Safari/537.36",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Google Chrome\";v=\"122\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"122\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"Linux\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Firefox Windows 110版本
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:110.0) Gecko/20100101 Firefox/110.0",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        # Firefox 不发送 sec-ch-ua 系列请求头
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Firefox Windows 111版本
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:111.0) Gecko/20100101 Firefox/111.0",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        # Firefox 不发送 sec-ch-ua 系列请求头
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Firefox Windows 112版本
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:112.0) Gecko/20100101 Firefox/112.0",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        # Firefox 不发送 sec-ch-ua 系列请求头
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Firefox Windows 老版本系统
    {
        "user_agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:109.0) Gecko/20100101 Firefox/110.0",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        # Firefox 不发送 sec-ch-ua 系列请求头
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Firefox MacOS 110版本
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:110.0) Gecko/20100101 Firefox/110.0",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        # Firefox 不发送 sec-ch-ua 系列请求头
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Firefox MacOS 111版本
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 11.6; rv:111.0) Gecko/20100101 Firefox/111.0",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        # Firefox 不发送 sec-ch-ua 系列请求头
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Firefox MacOS 112版本
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 12.0; rv:112.0) Gecko/20100101 Firefox/112.0",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        # Firefox 不发送 sec-ch-ua 系列请求头
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Firefox Linux i686
    {
        "user_agent": "Mozilla/5.0 (X11; Linux i686; rv:110.0) Gecko/20100101 Firefox/110.0",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        # Firefox 不发送 sec-ch-ua 系列请求头
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Firefox Fedora Linux
    {
        "user_agent": "Mozilla/5.0 (X11; Fedora; Linux x86_64; rv:111.0) Gecko/20100101 Firefox/111.0",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        # Firefox 不发送 sec-ch-ua 系列请求头
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Firefox Ubuntu Linux i686
    {
        "user_agent": "Mozilla/5.0 (X11; Ubuntu; Linux i686; rv:112.0) Gecko/20100101 Firefox/112.0",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        # Firefox 不发送 sec-ch-ua 系列请求头
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Edge Windows 120版本
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Microsoft Edge\";v=\"120\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"120\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"Windows\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Edge Windows 121版本
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Microsoft Edge\";v=\"121\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"121\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"Windows\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Edge Windows 122版本
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Microsoft Edge\";v=\"122\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"122\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"Windows\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Edge MacOS 120版本
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Microsoft Edge\";v=\"120\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"120\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"macOS\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Edge MacOS 121版本
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 11_6_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        "sec_ch_ua": "\"Microsoft Edge\";v=\"121\", \"Not-A.Brand\";v=\"8\", \"Chromium\";v=\"121\"",
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": "\"macOS\"",
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Safari MacOS 15_0版本
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        # Safari 不发送 sec-ch-ua 系列请求头
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Safari MacOS 15_4版本
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.4 Safari/605.1.15",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        # Safari 不发送 sec-ch-ua 系列请求头
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Safari MacOS 16_0版本
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 11_6_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        # Safari 不发送 sec-ch-ua 系列请求头
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Safari iPad版本
    {
        "user_agent": "Mozilla/5.0 (iPad; CPU OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        # Safari 不发送 sec-ch-ua 系列请求头
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    },
    # Safari iPhone版本
    {
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.4 Mobile/15E148 Safari/604.1",
        "accept": "*/*",
        "accept_language": "zh-CN,zh;q=0.9,en;q=0.8",
        # Safari 不发送 sec-ch-ua 系列请求头
        "sec_fetch_dest": "empty",
        "sec_fetch_mode": "cors",
        "sec_fetch_site": "same-origin"
    }
]

# 为了向后兼容，保留get_random_user_agent函数
def get_random_user_agent():
    """获取随机用户代理"""
    return random.choice([config["user_agent"] for config in BROWSER_CONFIGS])

def get_random_browser_config():
    """获取随机浏览器配置，包含完整的请求头信息"""
    return random.choice(BROWSER_CONFIGS)

class Config:
    """配置管理类，实现单例模式"""
    
    _instance = None
    _config = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            cls._instance._load_config()
        return cls._instance
    
    def _load_config(self):
        """加载配置"""
        # 加载默认配置
        self._config = DEFAULT_CONFIG.copy()
        
        # 从环境变量加载
        self._load_from_env()
    
    def _load_from_env(self):
        """从环境变量加载配置"""
        env_prefix = "UNLIMITED_"
        
        # 存储临时日志配置，以便后面统一处理优先级
        logging_config = {}
        server_logging_configs = {}

        # 直接加载关键配置项
        # 服务器配置
        self._config["server"] = self._config.get("server", {})
        self._config["server"]["host"] = os.getenv("UNLIMITED_SERVER_HOST", "0.0.0.0")
        self._config["server"]["port"] = int(os.getenv("UNLIMITED_SERVER_PORT", "8000"))
        self._config["server"]["workers"] = int(os.getenv("UNLIMITED_SERVER_WORKERS", "1"))
        self._config["server"]["reload"] = os.getenv("UNLIMITED_SERVER_RELOAD", "FALSE").upper() in ["TRUE", "YES", "1"]
        self._config["server"]["cors_origins"] = os.getenv("UNLIMITED_SERVER_CORS_ORIGINS", "*").split(",")
        self._config["server"]["log_level"] = os.getenv("UNLIMITED_SERVER_LOG_LEVEL", "info").lower()
        self._config["server"]["docs_enabled"] = os.getenv("UNLIMITED_SERVER_DOCS_ENABLED", "TRUE").upper() in ["TRUE", "YES", "1"]
        
        # API配置
        self._config["api"] = self._config.get("api", {})
        self._config["api"]["enable_rate_limit"] = os.getenv("UNLIMITED_RATE_LIMIT_ENABLED", "TRUE").upper() in ["TRUE", "YES", "1"]
        self._config["api"]["max_request_rate"] = int(os.getenv("UNLIMITED_RATE_LIMIT_IP", "20"))
        self._config["api"]["time_window"] = int(os.getenv("UNLIMITED_RATE_LIMIT_WINDOW", "60"))
        self._config["api"]["key_protection"] = os.getenv("UNLIMITED_API_KEY_PROTECTION", "FALSE").upper() in ["TRUE", "YES", "1"]
        self._config["api"]["key_file"] = os.getenv("UNLIMITED_API_KEY_FILE", ".KEY")
        
        # 处理其他环境变量
        for key in os.environ:
            if key.startswith(env_prefix):
                config_key = key[len(env_prefix):].lower()
                value = os.environ[key]
                
                # 跳过已直接处理的配置项
                if config_key in ["server_host", "server_port", "server_workers", "server_reload", 
                                 "server_cors_origins", "server_log_level", "server_docs_enabled",
                                 "rate_limit_enabled", "rate_limit_ip", "rate_limit_window", 
                                 "api_key_protection", "api_key_file"]:
                    continue
                
                # 尝试转换为适当的类型
                try:
                    if value.lower() in ("true", "yes", "1"):
                        value = True
                    elif value.lower() in ("false", "no", "0"):
                        value = False
                    elif value.isdigit():
                        value = int(value)
                    elif value.replace(".", "", 1).isdigit() and value.count(".") == 1:
                        value = float(value)
                    elif value.startswith('"') and value.endswith('"'):
                        # 处理引号包裹的字符串
                        value = value[1:-1]
                except Exception:
                    pass
                
                # 按照不同前缀映射到配置结构中
                if config_key.startswith("server_"):
                    section = "server"
                    option = config_key[len("server_"):]
                    
                    # 专门处理服务器日志相关配置，保存到临时变量
                    if option in ["log_level", "debug"]:
                        server_logging_configs[option] = value
                        continue  # 暂不保存到配置中，稍后根据优先级处理
                        
                elif config_key.startswith("api_"):
                    # 特殊处理API_KEY前缀，它属于api_key部分
                    if config_key.startswith("api_key_"):
                        section = "api_key"
                        option = config_key[len("api_key_"):]
                    else:
                        section = "api"
                        option = config_key[len("api_"):]
                elif config_key.startswith("token_"):
                    section = "token"
                    option = config_key[len("token_"):]
                elif config_key.startswith("proxy_"):
                    section = "proxy"
                    option = config_key[len("proxy_"):]
                elif config_key.startswith("performance_"):
                    section = "performance"
                    option = config_key[len("performance_"):]
                    
                    # 特殊处理：避免将冗余的请求速率和时间窗口配置存入性能配置
                    if option in ["max_request_rate", "time_window"]:
                        continue
                        
                elif config_key.startswith("logging_"):
                    section = "logging"
                    option = config_key[len("logging_"):]
                    
                    # 保存日志配置到临时变量
                    logging_config[option] = value
                else:
                    # 尝试使用点分隔符解析
                    parts = config_key.split("_", 1)
                    if len(parts) > 1:
                        section = parts[0]
                        option = parts[1]
                    else:
                        # 没有分隔符，放在根级别
                        self._config[config_key] = value
                        continue
                
                # 确保section在配置中存在
                if section not in self._config:
                    self._config[section] = {}
                
                # 设置配置项
                self._config[section][option] = value
        
        # 处理日志配置的优先级：logging_* 配置 > server_log_level/server_debug
        # 如果没有设置logging.level，但设置了server.log_level，则使用server.log_level
        if "logging" not in self._config:
            self._config["logging"] = {}
            
        # 优先使用logging_level，如果不存在再考虑server_log_level
        if "level" not in self._config["logging"] and "log_level" in server_logging_configs:
            self._config["logging"]["level"] = server_logging_configs["log_level"]
            logging.warning("使用server.log_level配置作为日志级别。建议迁移到专用的logging.level配置。")
            
        # 如果server.debug为true但logging.level不是DEBUG，发出警告
        if "debug" in server_logging_configs and server_logging_configs["debug"] and \
           self._config.get("logging", {}).get("level", "").upper() != "DEBUG":
            logging.warning("服务器调试模式已启用(server.debug=true)，但日志级别不是DEBUG。建议使用专用的logging.level=DEBUG配置。")
    
    def get(self, key, default=None):
        """获取配置值
        
        Args:
            key: 配置键，使用点号分隔，如 "server.host"
            default: 默认值，如果配置不存在则返回此值
        
        Returns:
            配置值或默认值
        """
        keys = key.split(".")
        value = self._config
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def set(self, key, value):
        """设置配置值
        
        Args:
            key: 配置键，使用点号分隔，如 "server.host"
            value: 要设置的值
        """
        keys = key.split(".")
        config = self._config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value
    
    def update(self, config_dict):
        """更新配置
        
        Args:
            config_dict: 包含新配置的字典
        """
        self._config = self._update_nested_dict(self._config, config_dict)
    
    def _update_nested_dict(self, d, u):
        """递归更新嵌套字典
        
        Args:
            d: 目标字典
            u: 更新源字典
        """
        for k, v in u.items():
            if isinstance(v, dict):
                d[k] = self._update_nested_dict(d.get(k, {}), v)
            else:
                d[k] = v
        return d
    
    def get_proxies(self):
        """获取代理配置
        
        Returns:
            代理配置字典，格式为 {"http": "...", "https": "..."}
        """
        if not self.get("proxy.enabled", False):
            return None
        
        proxies = {}
        if self.get("proxy.http"):
            proxies["http"] = self.get("proxy.http")
        if self.get("proxy.https"):
            proxies["https"] = self.get("proxy.https")
        
        return proxies if proxies else None

    def get_model_config(self, model_name: str) -> Dict[str, Any]:
        """
        获取指定模型的配置
        
        Args:
            model_name: 模型名称
            
        Returns:
            模型配置字典
        """
        model_configs = self.get("models.model_config", {})
        return model_configs.get(model_name, {"description": f"Unknown model: {model_name}", "thinking_enabled": False})
    
    def get_available_models(self) -> List[Dict[str, Any]]:
        """
        获取所有可用模型的信息
        
        Returns:
            模型信息列表，每个模型包含id和配置信息
        """
        available_models = self.get("models.available", [])
        default_model = self.get("models.default", available_models[0] if available_models else None)
        
        models = []
        for model_id in available_models:
            model_config = self.get_model_config(model_id)
            models.append({
                "id": model_id,
                "description": model_config.get("description", ""),
                "is_default": model_id == default_model,
                "thinking_enabled": model_config.get("thinking_enabled", False)
            })
        
        return models
    
    def get_token_storage_path(self) -> str:
        """
        获取令牌存储路径
        
        根据存储类型返回适当的路径，对于文件存储返回目录路径，对于SQLite返回数据库文件路径
        
        Returns:
            存储路径字符串
        """
        storage_type = self.get("token.storage_type", "sqlite")
        
        if storage_type == "file":
            return self.get("token.storage_path", ".unlimited")
        else:  # sqlite
            return self.get("token.db_path", "tokens.db")
    
    def get_token_redis_url(self) -> str:
        """
        获取Redis连接URL
        
        Returns:
            Redis连接URL
        """
        return self.get("token.redis_url", "redis://localhost:6379/0")
    
    def get_rate_limit_config(self) -> Dict[str, Any]:
        """
        获取请求速率限制配置
        Returns:
            速率限制配置字典，包含max_rate和time_window
        """
        # 获取日志实例
        logger = logging.getLogger("unlimited_proxy.config")
        
        try:
            # 直接从_config字典获取当前值，这些值应该已经在_load_security_config_from_env中设置
            max_rate = self._config.get("api", {}).get("max_request_rate")
            time_window = self._config.get("api", {}).get("time_window")
            
            # 如果从_config中获取不到值，尝试从环境变量直接获取
            if max_rate is None:
                env_value = os.getenv('UNLIMITED_RATE_LIMIT_IP')
                if env_value and env_value.isdigit():
                    max_rate = int(env_value)
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"从环境变量UNLIMITED_RATE_LIMIT_IP直接获取max_rate: {max_rate}")
            
            if time_window is None:
                env_value = os.getenv('UNLIMITED_RATE_LIMIT_WINDOW')
                if env_value and env_value.isdigit():
                    time_window = int(env_value)
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(f"从环境变量UNLIMITED_RATE_LIMIT_WINDOW直接获取time_window: {time_window}")
            
            # 如果仍然获取不到，使用默认值
            if max_rate is None:
                max_rate = 10
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"未找到max_rate配置，使用默认值: {max_rate}")
            
            if time_window is None:
                time_window = 10
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(f"未找到time_window配置，使用默认值: {time_window}")
            
            # 返回配置
            return {
                "max_rate": max_rate,
                "time_window": time_window
            }
        except Exception as e:
            logger.error(f"获取速率限制配置时出错: {e}")
            # 发生错误时返回默认值
            return {
                "max_rate": 10,
                "time_window": 10
            }
    
    def get_log_config(self) -> Dict[str, Any]:
        """
        获取日志配置
        
        Returns:
            日志配置字典
        """
        # 从配置构建完整的日志配置，不依赖预定义的LOG_CONFIG
        
        # 获取日志级别，默认为INFO
        log_level_str = self.get("logging.level", "INFO").upper()
        
        # 处理多级别日志配置或特殊值
        if log_level_str == "ALL":
            log_level = "DEBUG"  # 所有级别等同于DEBUG
        elif log_level_str == "NONE":
            log_level = "CRITICAL"
        elif "," in log_level_str:
            # 对于多个级别，找出最低级别，因为logging配置使用最低级别
            levels = [l.strip().upper() for l in log_level_str.split(",")]
            valid_levels = []
            # 日志级别从低到高的顺序
            level_order = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
            
            for level in levels:
                if level in level_order:
                    valid_levels.append(level)
            
            if valid_levels:
                # 找出最低级别（在level_order中索引最小的）
                log_level = min(valid_levels, key=lambda x: level_order.index(x))
            else:
                # 如果没有有效级别，默认使用INFO
                log_level = "INFO"
        else:
            # 单个级别
            log_level = log_level_str
            
            # 验证日志级别是否有效
            valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
            if log_level not in valid_levels:
                logging.warning(f"无效的日志级别: {log_level}，使用默认级别INFO")
                log_level = "INFO"
        
        # 获取日志格式，默认为DETAILED
        log_format = self.get("logging.format", "DETAILED").upper()
        
        # 获取日志输出目标，默认为BOTH
        log_output = self.get("logging.output", "BOTH").upper()
        
        # 获取日志目录，默认为logs
        log_dir = self.get("logging.dir", "logs")
        os.makedirs(log_dir, exist_ok=True)
        
        # 获取日志文件大小和备份数量
        max_size = self.get("logging.file_max_size", 10485760)  # 默认10MB
        backup_count = self.get("logging.file_backup_count", 3)
        
        # 是否隐藏HTTP请求日志
        hide_http = self.get("logging.hide_http", True)
        
        # 构建格式化器配置
        formatters = {
            "standard": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
            },
            "detailed": {
                "format": "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s"
            },
            "simple": {
                "format": "%(levelname)s: %(message)s"
            },
            "sophnet": {
                "format": "%(asctime)s - [%(filename)s:%(lineno)d] - %(levelname)s - %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S"
            }
        }
        
        # 根据配置选择格式化器
        if log_format == "SIMPLE":
            formatter = "simple"
        elif log_format == "DETAILED":
            formatter = "detailed"
        elif log_format == "SOPHNET":
            formatter = "sophnet"
        else:
            formatter = "standard"
        
        # 构建处理器配置
        handlers = {
            "console": {
                "class": "logging.StreamHandler",
                "level": log_level,
                "formatter": formatter,
                "stream": "ext://sys.stdout"
            }
        }
        
        # 添加文件处理器
        handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": log_level,
            "formatter": formatter,
            "filename": os.path.join(log_dir, "unlimited_proxy.log"),
            "maxBytes": max_size,
            "backupCount": backup_count,
            "encoding": "utf8"
        }
        
        # 添加错误文件处理器
        handlers["error_file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "ERROR",
            "formatter": formatter,
            "filename": os.path.join(log_dir, "error.log"),
            "maxBytes": max_size,
            "backupCount": backup_count,
            "encoding": "utf8"
        }
        
        # 根据log_output配置确定使用哪些处理器
        log_handlers = []
        if log_output in ["CONSOLE", "BOTH"]:
            log_handlers.append("console")
        if log_output in ["FILE", "BOTH"]:
            log_handlers.append("file")
            log_handlers.append("error_file")
        
        # 构建完整的日志配置
        log_config = {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": formatters,
            "handlers": handlers,
            "loggers": {
                "unlimited_proxy": {
                    "level": log_level,
                    "handlers": log_handlers,
                    "propagate": False
                }
            },
            "root": {
                "level": log_level,
                "handlers": ["console"] if "console" in log_handlers else []
            }
        }
        
        return log_config

def load_config(config_file=None):
    """加载配置"""
    global loaded
    
    if loaded:
        return
    
    # 加载环境变量
    _load_env_vars()
    
    # 加载日志配置
    _configure_logging()

    # 加载默认配置
    _load_default_config()

    # 加载环境变量覆盖的配置
    _load_from_env()

    # 加载安全模块配置
    _load_security_config_from_env()
    
    # 加载模型配置
    _load_models_config()
    
    loaded = True
    
    if DEBUG_LEVEL >= 3:
        print("\n最终配置:")
        for key in sorted(config.keys()):
            if "password" in key or "secret" in key or "key" in key:
                print(f"  {key}: ******")
            else:
                print(f"  {key}: {config[key]}")
        print("")

config = Config()

# 从环境变量加载安全模块设置
def _load_security_config_from_env():
    """从环境变量加载安全模块配置"""
    # 使用logging而不是print
    logger = logging.getLogger("unlimited_proxy.config")
    
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("\n======= 加载环境变量安全配置 =======")
    
    # 获取环境变量值
    rate_limit_ip = os.getenv('UNLIMITED_RATE_LIMIT_IP')
    rate_limit_window = os.getenv('UNLIMITED_RATE_LIMIT_WINDOW')
    rate_limit_by_key = os.getenv('UNLIMITED_RATE_LIMIT_BY_KEY')
    rate_limit_key_default = os.getenv('UNLIMITED_RATE_LIMIT_KEY_DEFAULT')
    
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(f"[环境变量]UNLIMITED_RATE_LIMIT_IP = {rate_limit_ip}")
        logger.debug(f"[环境变量]UNLIMITED_RATE_LIMIT_WINDOW = {rate_limit_window}")
        logger.debug(f"[环境变量]UNLIMITED_RATE_LIMIT_BY_KEY = {rate_limit_by_key}")
        logger.debug(f"[环境变量]UNLIMITED_RATE_LIMIT_KEY_DEFAULT = {rate_limit_key_default}")
        logger.debug(f"[强制设置] = {FORCE_SETTINGS}")
    
    # 转换环境变量值为合适的类型
    ip_limit = int(rate_limit_ip) if rate_limit_ip and rate_limit_ip.isdigit() else None
    time_window = int(rate_limit_window) if rate_limit_window and rate_limit_window.isdigit() else None
    key_limit = rate_limit_by_key.upper() in ["TRUE", "YES", "1"] if rate_limit_by_key else None
    key_default = int(rate_limit_key_default) if rate_limit_key_default and rate_limit_key_default.isdigit() else None
    
    # 设置配置值 - 无论如何都要设置，避免None值
    config._config["api"]["max_request_rate"] = ip_limit if ip_limit is not None else 60
    config._config["api"]["time_window"] = time_window if time_window is not None else 60
    config._config["api"]["key_rate_limit"] = key_limit if key_limit is not None else False
    config._config["api"]["default_key_rate"] = key_default if key_default is not None else 20
    
    # 应用强制设置 - 如果强制设置存在，则覆盖环境变量设置
    if "api.max_request_rate" in FORCE_SETTINGS:
        config._config["api"]["max_request_rate"] = FORCE_SETTINGS["api.max_request_rate"]
    if "api.time_window" in FORCE_SETTINGS:
        config._config["api"]["time_window"] = FORCE_SETTINGS["api.time_window"]
    if "api.key_rate_limit" in FORCE_SETTINGS:
        config._config["api"]["key_rate_limit"] = FORCE_SETTINGS["api.key_rate_limit"]
    if "api.default_key_rate" in FORCE_SETTINGS:
        config._config["api"]["default_key_rate"] = FORCE_SETTINGS["api.default_key_rate"]
    
    # 打印最终的配置值（仅在DEBUG级别）
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("\n[最终配置]:")
        logger.debug(f"api.max_request_rate = {config._config['api']['max_request_rate']}")
        logger.debug(f"api.time_window = {config._config['api']['time_window']}")
        logger.debug(f"api.key_rate_limit = {config._config['api']['key_rate_limit']}")
        logger.debug(f"api.default_key_rate = {config._config['api']['default_key_rate']}")
        logger.debug("====================================\n")

# 解析环境变量的辅助函数
def _parse_bool_env(env_name, default=False):
    """解析布尔类型的环境变量
    
    Args:
        env_name: 环境变量名称
        default: 默认值
        
    Returns:
        解析后的布尔值
    """
    value = os.getenv(env_name)
    if value is None:
        return default
    return value.lower() in ('true', '1', 'yes', 'y', 'on')

def _parse_int_env(env_name, default=0):
    """解析整数类型的环境变量
    
    Args:
        env_name: 环境变量名称
        default: 默认值
        
    Returns:
        解析后的整数值
    """
    value = os.getenv(env_name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning(f"环境变量 {env_name} 的值 '{value}' 不是有效的整数，使用默认值 {default}")
        return default