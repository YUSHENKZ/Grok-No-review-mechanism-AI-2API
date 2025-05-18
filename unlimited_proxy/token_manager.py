"""
Token管理模块

负责Token的获取、缓存和验证。
"""

import os
import time
import uuid
import sqlite3
import logging
import random
import threading
import asyncio
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timedelta

import httpx

from .config import config
from .utils import get_exponential_backoff_delay

# 配置日志
logger = logging.getLogger("unlimited_proxy.token_manager")

# 硬编码的API端点
API_BASE_URL = "https://app.unlimitedai.chat"
TOKEN_ENDPOINT = f"{API_BASE_URL}/api/token"

# 添加常用User-Agent列表用于随机化
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/121.0.0.0 Safari/537.36",
]

# 替换为浏览器配置集合，包含完整的请求头信息
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
]

class TokenManager:
    """Token管理类，实现单例模式"""
    
    _instance = None
    _token = None
    _token_expiry = None
    _http_client = None
    # 添加IP与token映射字典
    _ip_tokens = {}
    # 添加token锁定机制
    _token_locks = {}
    # 添加全局互斥锁
    _global_lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TokenManager, cls).__new__(cls)
            cls._instance._init_db()
        return cls._instance
    
    def _init_db(self):
        """初始化SQLite数据库"""
        # 获取存储类型和路径
        storage_type = config.get("token.storage_type", "sqlite")
        
        if storage_type == "sqlite":
            db_path = config.get("token.db_path", "tokens.db")
            
            if not os.path.exists(os.path.dirname(db_path)) and os.path.dirname(db_path):
                os.makedirs(os.path.dirname(db_path))
            
            try:
                conn = sqlite3.connect(db_path)
                c = conn.cursor()
                
                # 创建tokens表
                c.execute('''
                CREATE TABLE IF NOT EXISTS tokens (
                    id INTEGER PRIMARY KEY,
                    token TEXT NOT NULL,
                    obtained_at TIMESTAMP NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    status TEXT DEFAULT 'active',
                    last_used TIMESTAMP,
                    use_count INTEGER DEFAULT 0,
                    error_count INTEGER DEFAULT 0,
                    using_ip TEXT,
                    lock_time TIMESTAMP
                )
                ''')
                
                conn.commit()
                conn.close()
                logger.info(f"Token数据库初始化完成, 使用SQLite: {db_path}")
            except Exception as e:
                logger.error(f"初始化Token数据库失败: {str(e)}")
        elif storage_type == "file":
            storage_path = config.get("token.storage_path", ".unlimited")
            if not os.path.exists(storage_path):
                os.makedirs(storage_path)
            logger.info(f"Token存储初始化完成, 使用文件存储: {storage_path}")
        elif storage_type == "redis":
            redis_url = config.get("token.redis_url", "redis://localhost:6379/0")
            logger.info(f"Token存储初始化完成, 使用Redis: {redis_url}")
        else:
            logger.warning(f"未知的存储类型: {storage_type}, 使用默认SQLite")
    
    def get_token(self, force_new=False, client_ip=None) -> Optional[str]:
        """
        获取有效的Token
        
        Args:
            force_new: 是否强制获取新Token
            client_ip: 客户端IP地址，用于区分不同的请求来源
            
        Returns:
            有效的Token或None
        """
        # 如果提供了客户端IP，先尝试获取该IP专用的token
        if client_ip:
            with self._global_lock:
                if client_ip in self._ip_tokens:
                    token, expires_at = self._ip_tokens[client_ip]
                    # 检查token是否仍然有效
                    if not force_new and expires_at > datetime.now():
                        logger.debug(f"使用IP {client_ip}专用的Token: {token[:10]}...")
                        return token
        
        # 优先使用内存缓存
        if not force_new and self._token and self._token_expiry and self._token_expiry > datetime.now():
            logger.debug(f"使用内存缓存的Token: {self._token[:10]}...")
            return self._token
        
        # 从数据库获取
        if not force_new:
            token = self._get_token_from_db(client_ip)
            if token:
                # 如果提供了客户端IP，将token与该IP关联
                if client_ip:
                    with self._global_lock:
                        self._ip_tokens[client_ip] = (token, datetime.now() + timedelta(hours=1))
                return token
        
        # 从服务器获取新Token
        token = self._fetch_new_token(client_ip=client_ip)
        if token:
            self._save_token_to_db(token, client_ip)
            # 如果提供了客户端IP，将token与该IP关联
            if client_ip:
                with self._global_lock:
                    self._ip_tokens[client_ip] = (token, datetime.now() + timedelta(hours=1))
        
        return token
    
    def _is_token_valid(self, token: str, expires_at_str: str) -> bool:
        """
        检查Token是否有效
        
        Args:
            token: Token字符串
            expires_at_str: 过期时间的ISO格式字符串
            
        Returns:
            Token是否有效
        """
        try:
            # 解析过期时间
            try:
                expires_at = datetime.fromisoformat(expires_at_str)
            except ValueError:
                # 尝试解析其他格式
                expires_at = datetime.strptime(expires_at_str, "%Y-%m-%d %H:%M:%S")
            
            # 设置安全边界，提前5分钟认为过期
            safety_margin = timedelta(minutes=5)
            now = datetime.now()
            
            # 检查是否有效
            is_valid = expires_at > (now + safety_margin)
            
            if is_valid:
                # 计算剩余有效时间
                remaining_time = expires_at - now
                hours = remaining_time.total_seconds() / 3600
                logger.debug(f"Token有效，剩余时间: {hours:.2f}小时")
            else:
                logger.debug(f"Token已过期或即将过期，过期时间: {expires_at}")
            
            return is_valid
            
        except Exception as e:
            logger.error(f"检查Token有效性时出错: {str(e)}")
            return False
    
    def _get_token_from_db(self, client_ip=None) -> Optional[str]:
        """
        从数据库获取有效的Token
        
        Args:
            client_ip: 客户端IP地址，用于筛选特定IP的token
            
        Returns:
            有效的Token或None
        """
        storage_type = config.get("token.storage_type", "sqlite")
        
        # 基于存储类型选择不同的获取方式
        if storage_type == "sqlite":
            return self._get_token_from_sqlite(client_ip)
        elif storage_type == "file":
            return self._get_token_from_file()
        elif storage_type == "redis":
            return self._get_token_from_redis()
        else:
            logger.warning(f"未知的存储类型: {storage_type}, 使用默认SQLite")
            return self._get_token_from_sqlite(client_ip)
    
    def _get_token_from_sqlite(self, client_ip=None) -> Optional[str]:
        """
        从SQLite获取Token
        
        Args:
            client_ip: 客户端IP地址，用于筛选特定IP的token
            
        Returns:
            有效的Token或None
        """
        try:
            db_path = config.get("token.db_path", "tokens.db")
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            
            # 查询条件
            now = datetime.now()
            safe_time = now + timedelta(minutes=5)
            
            # 如果提供了客户端IP，首先尝试获取该IP专用的token
            if client_ip:
                c.execute(
                    'SELECT token, expires_at FROM tokens WHERE status = "active" AND expires_at > ? AND using_ip = ? AND error_count < 3 LIMIT 1',
                    (safe_time.isoformat(), client_ip)
                )
                result = c.fetchone()
                if result:
                    token, expires_at_str = result
                    # 验证Token是否真的有效
                    if self._is_token_valid(token, expires_at_str):
                        # 更新使用次数和最后使用时间
                        c.execute(
                            'UPDATE tokens SET last_used = ?, use_count = use_count + 1 WHERE token = ?',
                            (now.isoformat(), token)
                        )
                        conn.commit()
                        
                        # 更新内存缓存
                        self._token = token
                        try:
                            self._token_expiry = datetime.fromisoformat(expires_at_str)
                        except:
                            self._token_expiry = now + timedelta(hours=1)
                        
                        logger.debug(f"从SQLite获取IP {client_ip}专用的Token: {token[:10]}...")
                        return token
            
            # 查询未锁定且未分配给特定IP的token，或者锁定超过10分钟的token(视为过期锁定)
            lock_expiry_time = now - timedelta(minutes=10)
            # 增加安全边界，提前5分钟认为过期
            query = '''
            SELECT token, expires_at FROM tokens 
            WHERE status = "active" AND expires_at > ? AND error_count < 3 
            AND (using_ip IS NULL OR using_ip = "" OR (lock_time IS NOT NULL AND lock_time < ?))
            ORDER BY error_count ASC, use_count ASC LIMIT 1
            '''
            c.execute(query, (safe_time.isoformat(), lock_expiry_time.isoformat()))
            
            result = c.fetchone()
            if result:
                token, expires_at_str = result
                
                # 验证Token是否真的有效
                if not self._is_token_valid(token, expires_at_str):
                    # 标记为无效并返回None
                    c.execute(
                        'UPDATE tokens SET status = "expired" WHERE token = ?',
                        (token,)
                    )
                    conn.commit()
                    conn.close()
                    return None
                
                # 锁定该token并分配给当前IP
                if client_ip:
                    c.execute(
                        'UPDATE tokens SET last_used = ?, use_count = use_count + 1, using_ip = ?, lock_time = ? WHERE token = ?',
                        (now.isoformat(), client_ip, now.isoformat(), token)
                    )
                else:
                    c.execute(
                        'UPDATE tokens SET last_used = ?, use_count = use_count + 1 WHERE token = ?',
                        (now.isoformat(), token)
                    )
                conn.commit()
                
                # 更新内存缓存
                self._token = token
                try:
                    self._token_expiry = datetime.fromisoformat(expires_at_str)
                except:
                    self._token_expiry = now + timedelta(hours=1)
                
                logger.debug(f"从SQLite获取Token: {token[:10]}...")
                return token
        
        except Exception as e:
            logger.error(f"从SQLite获取Token失败: {str(e)}")
        
        finally:
            if 'conn' in locals():
                conn.close()
        
        return None
    
    def _get_token_from_file(self) -> Optional[str]:
        """从文件存储获取Token"""
        try:
            storage_path = config.get("token.storage_path", ".unlimited")
            token_file = os.path.join(storage_path, "active_token.txt")
            
            if not os.path.exists(token_file):
                return None
            
            with open(token_file, 'r') as f:
                data = f.read().strip().split('|')
                
            if len(data) < 2:
                return None
                
            token, expires_at_str = data[0], data[1]
            
            # 验证Token是否有效
            if not self._is_token_valid(token, expires_at_str):
                # 删除无效的Token文件
                os.remove(token_file)
                return None
            
            # 更新内存缓存
            self._token = token
            try:
                self._token_expiry = datetime.fromisoformat(expires_at_str)
            except:
                self._token_expiry = datetime.now() + timedelta(hours=1)
            
            logger.debug(f"从文件获取Token: {token[:10]}...")
            return token
            
        except Exception as e:
            logger.error(f"从文件获取Token失败: {str(e)}")
            return None
    
    def _get_token_from_redis(self) -> Optional[str]:
        """从Redis获取Token"""
        # 简化实现，未实际使用Redis
        logger.warning("Redis存储尚未实现，使用默认SQLite")
        return self._get_token_from_sqlite()
    
    def _save_token_to_db(self, token: str, client_ip=None) -> bool:
        """
        保存Token到存储
        
        Args:
            token: 要保存的Token
            client_ip: 客户端IP地址，用于标记token专属的IP
            
        Returns:
            保存是否成功
        """
        storage_type = config.get("token.storage_type", "sqlite")
        
        # 基于存储类型选择不同的保存方式
        if storage_type == "sqlite":
            return self._save_token_to_sqlite(token, client_ip)
        elif storage_type == "file":
            return self._save_token_to_file(token)
        elif storage_type == "redis":
            return self._save_token_to_redis(token)
        else:
            logger.warning(f"未知的存储类型: {storage_type}, 使用默认SQLite")
            return self._save_token_to_sqlite(token, client_ip)
    
    def _save_token_to_sqlite(self, token: str, client_ip=None) -> bool:
        """
        保存Token到SQLite
        
        Args:
            token: 要保存的Token
            client_ip: 客户端IP地址，用于标记token专属的IP
            
        Returns:
            保存是否成功
        """
        try:
            db_path = config.get("token.db_path", "tokens.db")
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            
            now = datetime.now()
            expires_at = now + timedelta(hours=1)
            
            # 如果提供了客户端IP，将token标记为该IP专用
            if client_ip:
                c.execute(
                    'INSERT INTO tokens (token, obtained_at, expires_at, last_used, use_count, error_count, using_ip, lock_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                    (token, now.isoformat(), expires_at.isoformat(), now.isoformat(), 1, 0, client_ip, now.isoformat())
                )
            else:
                c.execute(
                    'INSERT INTO tokens (token, obtained_at, expires_at, last_used, use_count, error_count) VALUES (?, ?, ?, ?, ?, ?)',
                    (token, now.isoformat(), expires_at.isoformat(), now.isoformat(), 1, 0)
                )
            
            conn.commit()
            conn.close()
            
            # 更新内存缓存
            self._token = token
            self._token_expiry = expires_at
            
            logger.info(f"保存Token到SQLite: {token[:10]}..." + (f" (IP: {client_ip})" if client_ip else ""))
            return True
            
        except Exception as e:
            logger.error(f"保存Token到SQLite失败: {str(e)}")
            return False
    
    def _save_token_to_file(self, token: str) -> bool:
        """保存Token到文件"""
        try:
            storage_path = config.get("token.storage_path", ".unlimited")
            token_file = os.path.join(storage_path, "active_token.txt")
            
            now = datetime.now()
            expires_at = now + timedelta(hours=1)
            
            with open(token_file, 'w') as f:
                f.write(f"{token}|{expires_at.isoformat()}")
            
            # 更新内存缓存
            self._token = token
            self._token_expiry = expires_at
            
            logger.info(f"保存Token到文件: {token[:10]}...")
            return True
            
        except Exception as e:
            logger.error(f"保存Token到文件失败: {str(e)}")
            return False
    
    def _save_token_to_redis(self, token: str) -> bool:
        """保存Token到Redis"""
        logger.warning("Redis存储尚未实现，使用默认SQLite")
        return self._save_token_to_sqlite(token)
    
    def _get_random_user_agent(self) -> str:
        """获取随机User-Agent"""
        return random.choice(USER_AGENTS)
        
    def _get_random_browser_config(self) -> dict:
        """获取随机浏览器配置，包含完整的请求头信息"""
        return random.choice(BROWSER_CONFIGS)
    
    def _fetch_new_token(self, retry_count: int = 0, client_ip=None) -> Optional[str]:
        """
        从服务器获取新Token
        
        Args:
            retry_count: 当前重试次数
            client_ip: 客户端IP地址，用于记录token来源
            
        Returns:
            新获取的Token或None
        """
        max_retries = config.get("token.max_retries", 3)
        
        logger.info("从服务器获取新Token" + (f" (IP: {client_ip})" if client_ip else ""))
        
        # 生成随机UUID
        chat_id = str(uuid.uuid4())
        
        # 获取随机浏览器配置，包含完整的请求头信息
        browser_config = self._get_random_browser_config()
        user_agent = browser_config["user_agent"]
        
        # 准备请求头
        headers = {
            "accept": browser_config["accept"],
            "accept-language": browser_config["accept_language"],
            "priority": "u=1, i",
            "referer": f"{API_BASE_URL}/chat/{chat_id}",
            "user-agent": user_agent
        }
        
        # 添加可选的sec-ch标头（有些浏览器如Firefox和Safari不发送这些标头）
        if "sec_ch_ua" in browser_config:
            headers["sec-ch-ua"] = browser_config["sec_ch_ua"]
        if "sec_ch_ua_mobile" in browser_config:
            headers["sec-ch-ua-mobile"] = browser_config["sec_ch_ua_mobile"]
        if "sec_ch_ua_platform" in browser_config:
            headers["sec-ch-ua-platform"] = browser_config["sec_ch_ua_platform"]
            
        # 添加sec-fetch标头
        headers["sec-fetch-dest"] = browser_config["sec_fetch_dest"]
        headers["sec-fetch-mode"] = browser_config["sec_fetch_mode"]
        headers["sec-fetch-site"] = browser_config["sec_fetch_site"]
        
        logger.debug(f"使用浏览器指纹: {user_agent}")
        
        try:
            # 设置HTTP客户端
            if not self._http_client:
                client_config = {
                    "http2": config.get("performance.http2_enabled", True),
                    "limits": httpx.Limits(
                        max_connections=config.get("performance.connection_pool_size", 100),
                        max_keepalive_connections=config.get("performance.keep_alive_connections", 20),
                        keepalive_expiry=config.get("performance.keepalive_expiry", 30.0)
                    ),
                    "timeout": config.get("api.timeout", 60.0),
                    "verify": True,
                    "follow_redirects": True
                }
                
                # 添加代理配置
                proxies = config.get_proxies()
                if proxies:
                    client_config["proxies"] = proxies
                
                self._http_client = httpx.Client(**client_config)
            
            # 发送请求
            logger.info(f"HTTP请求: GET {TOKEN_ENDPOINT}")
            response = self._http_client.get(TOKEN_ENDPOINT, headers=headers)
            
            # 检查响应状态
            status_code = response.status_code
            logger.info(f"HTTP响应状态码: {status_code}")
            
            # 处理需要重试的错误状态码
            if (status_code == 429 or status_code >= 500) and retry_count < max_retries:
                # 计算退避时间
                delay = get_exponential_backoff_delay(retry_count)
                logger.warning(f"获取Token失败 (HTTP {status_code})，将在{delay}ms后重试 ({retry_count + 1}/{max_retries})")
                time.sleep(delay / 1000)  # 转换为秒
                return self._fetch_new_token(retry_count + 1, client_ip)
            
            if status_code != 200:
                logger.error(f"获取Token失败: HTTP {status_code}")
                return None
            
            # 解析响应
            try:
                data = response.json()
                token = data.get('token')
                
                if not token:
                    logger.error("响应中不包含Token")
                    return None
                
                # 更新内存缓存
                self._token = token
                self._token_expiry = datetime.now() + timedelta(hours=1)
                
                logger.info(f"成功获取新Token: {token[:10]}..." + (f" (IP: {client_ip})" if client_ip else ""))
                return token
            
            except Exception as e:
                logger.error(f"解析Token响应失败: {str(e)}")
                return None
        
        except Exception as e:
            logger.error(f"获取Token时出错: {str(e)}")
            
            # 对于网络错误等非HTTP状态错误，也进行重试
            if retry_count < max_retries:
                # 计算退避时间
                delay = get_exponential_backoff_delay(retry_count)
                logger.warning(f"获取Token时发生错误，将在{delay}ms后重试 ({retry_count + 1}/{max_retries})")
                time.sleep(delay / 1000)  # 转换为秒
                return self._fetch_new_token(retry_count + 1, client_ip)
            
            return None
    
    def invalidate_token(self, token: str) -> bool:
        """
        将Token标记为无效
        
        Args:
            token: 要标记的Token
            
        Returns:
            操作是否成功
        """
        try:
            # 检查是否为当前内存缓存的Token
            if self._token == token:
                self._token = None
                self._token_expiry = None
            
            # 从IP-token映射中移除
            with self._global_lock:
                for ip, (t, _) in list(self._ip_tokens.items()):
                    if t == token:
                        del self._ip_tokens[ip]
            
            # 基于存储类型选择不同的失效方法
            storage_type = config.get("token.storage_type", "sqlite")
            
            if storage_type == "sqlite":
                # 更新数据库
                db_path = config.get("token.db_path", "tokens.db")
                conn = sqlite3.connect(db_path)
                c = conn.cursor()
                
                # 增加error_count，如果超过3次则标记为invalid
                c.execute('UPDATE tokens SET error_count = error_count + 1, using_ip = NULL, lock_time = NULL WHERE token = ?', (token,))
                
                # 检查error_count是否>=3
                c.execute('SELECT error_count FROM tokens WHERE token = ?', (token,))
                result = c.fetchone()
                if result and result[0] >= 3:
                    c.execute('UPDATE tokens SET status = "invalid" WHERE token = ?', (token,))
                    logger.warning(f"Token错误次数达到上限，已标记为无效: {token[:10]}...")
                
                conn.commit()
                conn.close()
            elif storage_type == "file":
                # 对于文件存储，简单地删除文件
                storage_path = config.get("token.storage_path", ".unlimited")
                token_file = os.path.join(storage_path, "active_token.txt")
                if os.path.exists(token_file):
                    os.remove(token_file)
            
            logger.info(f"Token已标记为无效或增加错误计数: {token[:10]}...")
            return True
        
        except Exception as e:
            logger.error(f"标记Token为无效时出错: {str(e)}")
            return False
    
    def release_token_for_ip(self, client_ip: str) -> bool:
        """
        释放特定IP使用的Token锁定
        
        Args:
            client_ip: 客户端IP地址
            
        Returns:
            操作是否成功
        """
        try:
            # 从内存映射中移除
            with self._global_lock:
                if client_ip in self._ip_tokens:
                    del self._ip_tokens[client_ip]
            
            # 更新数据库
            storage_type = config.get("token.storage_type", "sqlite")
            if storage_type == "sqlite":
                db_path = config.get("token.db_path", "tokens.db")
                conn = sqlite3.connect(db_path)
                c = conn.cursor()
                
                c.execute(
                    'UPDATE tokens SET using_ip = NULL, lock_time = NULL WHERE using_ip = ?', 
                    (client_ip,)
                )
                
                conn.commit()
                conn.close()
                
                logger.info(f"已释放IP {client_ip}锁定的Token")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"释放IP Token锁定时出错: {str(e)}")
            return False
    
    def record_token_error(self, token: str, error_code: int) -> bool:
        """
        记录Token使用中的错误
        
        Args:
            token: 出错的Token
            error_code: HTTP错误码
            
        Returns:
            操作是否成功
        """
        try:
            # 如果是致命错误(401, 403)，直接使token无效
            if error_code in [401, 403]:
                return self.invalidate_token(token)
            
            # 对于其他错误，只增加error_count
            storage_type = config.get("token.storage_type", "sqlite")
            
            if storage_type == "sqlite":
                db_path = config.get("token.db_path", "tokens.db")
                conn = sqlite3.connect(db_path)
                c = conn.cursor()
                
                # 增加error_count，重置IP锁定，让其他客户端可以使用
                c.execute(
                    'UPDATE tokens SET error_count = error_count + 1, using_ip = NULL, lock_time = NULL WHERE token = ?', 
                    (token,)
                )
                
                # 检查是否应该标记为无效
                c.execute('SELECT error_count FROM tokens WHERE token = ?', (token,))
                result = c.fetchone()
                if result and result[0] >= 3:
                    c.execute('UPDATE tokens SET status = "invalid" WHERE token = ?', (token,))
                    logger.warning(f"Token错误次数达到上限，已标记为无效: {token[:10]}...")
                    # 清除内存缓存
                    if self._token == token:
                        self._token = None
                        self._token_expiry = None
                    
                    # 从IP-token映射中移除
                    with self._global_lock:
                        for ip, (t, _) in list(self._ip_tokens.items()):
                            if t == token:
                                del self._ip_tokens[ip]
                
                conn.commit()
                conn.close()
                
                logger.info(f"Token错误已记录: {token[:10]}..., 错误码: {error_code}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"记录Token错误时出错: {str(e)}")
            return False
    
    def cleanup(self) -> int:
        """
        清理过期的Token
        
        Returns:
            清理的Token数量
        """
        storage_type = config.get("token.storage_type", "sqlite")
        
        if storage_type == "sqlite":
            try:
                db_path = config.get("token.db_path", "tokens.db")
                conn = sqlite3.connect(db_path)
                c = conn.cursor()
                
                # 清理过期的token锁定(超过10分钟的锁定)
                now = datetime.now()
                lock_expiry_time = now - timedelta(minutes=10)
                c.execute(
                    'UPDATE tokens SET using_ip = NULL, lock_time = NULL WHERE lock_time IS NOT NULL AND lock_time < ?',
                    (lock_expiry_time.isoformat(),)
                )
                released_count = c.rowcount
                
                # 删除过期的Token
                c.execute('DELETE FROM tokens WHERE expires_at < ?', (now.isoformat(),))
                
                deleted_count = c.rowcount
                conn.commit()
                conn.close()
                
                if deleted_count > 0 or released_count > 0:
                    logger.info(f"清理了{deleted_count}个过期Token，释放了{released_count}个过期锁定")
                
                # 清理内存中的过期IP-token映射
                with self._global_lock:
                    for ip in list(self._ip_tokens.keys()):
                        _, expires_at = self._ip_tokens[ip]
                        if expires_at <= now:
                            del self._ip_tokens[ip]
                
                return deleted_count
            
            except Exception as e:
                logger.error(f"清理Token时出错: {str(e)}")
                return 0
        elif storage_type == "file":
            # 对于文件存储，检查token文件是否过期
            try:
                storage_path = config.get("token.storage_path", ".unlimited")
                token_file = os.path.join(storage_path, "active_token.txt")
                
                if not os.path.exists(token_file):
                    return 0
                
                with open(token_file, 'r') as f:
                    data = f.read().strip().split('|')
                
                if len(data) < 2:
                    os.remove(token_file)
                    return 1
                    
                try:
                    expires_at = datetime.fromisoformat(data[1])
                    if expires_at <= datetime.now():
                        os.remove(token_file)
                        logger.info("清理了过期的Token文件")
                        return 1
                except:
                    os.remove(token_file)
                    return 1
                
                return 0
            except Exception as e:
                logger.error(f"清理Token文件时出错: {str(e)}")
                return 0
        
        return 0
    
    def close(self):
        """关闭资源"""
        if self._http_client:
            self._http_client.close()
    
    async def verify_token(self, token: str) -> bool:
        """
        异步验证Token的有效性（通过发送小型测试请求）
        
        Args:
            token: Token字符串
            
        Returns:
            Token是否有效
        """
        # 获取随机浏览器配置
        browser_config = self._get_random_browser_config()
        chat_id = str(uuid.uuid4())
        
        # 准备请求头
        headers = {
            "accept": "text/event-stream",
            "content-type": "application/json",
            "x-api-token": token,
            "user-agent": browser_config["user_agent"],
            "referer": f"{API_BASE_URL}/chat/{chat_id}"
        }
        
        # 准备简单的对话请求数据
        test_message = {
            "id": chat_id,
            "messages": [
                {
                    "id": str(uuid.uuid4()),
                    "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                    "role": "user",
                    "content": "hi!",
                    "parts": [{"type": "text", "text": "hi!"}]
                }
            ],
            "selectedChatModel": "chat-model-reasoning"
        }
        
        # 使用聊天API作为验证端点
        verify_url = f"{API_BASE_URL}/api/chat"
        
        try:
            # 创建异步HTTP客户端
            async with httpx.AsyncClient(timeout=20.0) as client:
                # 发送请求
                logger.debug(f"使用对话API验证Token有效性: POST {verify_url}")
                
                # 使用流式请求，收到初始响应后立即中断，降低资源消耗
                async with client.stream("POST", verify_url, json=test_message, headers=headers) as response:
                    # 只需检查响应状态码，不需要读取完整内容
                    status_code = response.status_code
                    logger.debug(f"验证请求状态码: {status_code}, 响应头: {dict(response.headers)}")
                    
                    # 尝试读取少量内容验证流是否正常开始
                    first_chunk = await response.aread()
                    has_content = len(first_chunk) > 0
                    
                    if status_code == 200 and has_content:
                        logger.info(f"Token验证成功: {token[:10]}... (通过对话API, 接收到内容: {len(first_chunk)}字节)")
                        # 立即中断流式请求
                        await response.aclose()
                        return True
                    else:
                        details = f"状态码: {status_code}, 接收到内容: {has_content}"
                        logger.warning(f"Token验证失败: {details} (通过对话API)")
                        return False
                
        except Exception as e:
            logger.error(f"验证Token时出错: {str(e)} (通过对话API)")
            return False
    
    async def initialize(self) -> bool:
        """
        初始化并确保有可用的Token
        在应用启动时调用，确保服务开始时就有可用Token
        
        Returns:
            是否成功初始化有效的Token
        """
        # 检查是否有内存缓存的Token
        if self._token and self._token_expiry and self._token_expiry > datetime.now():
            # 验证Token实际有效性
            is_valid = await self.verify_token(self._token)
            if is_valid:
                logger.info(f"内存中的Token有效，保持使用")
                return True
            else:
                logger.warning(f"内存中的Token无效，尝试获取新Token")
                self._token = None
        
        # 从数据库获取Token
        token = self._get_token_from_db()
        if token:
            # 验证Token实际有效性
            is_valid = await self.verify_token(token)
            if is_valid:
                # 更新内存缓存
                self._token = token
                self._token_expiry = datetime.now() + timedelta(hours=1)
                logger.info(f"从数据库获取的Token有效，更新内存缓存")
                return True
            else:
                logger.warning(f"从数据库获取的Token无效，尝试获取新Token")
        
        # 从服务器获取新Token
        loop = asyncio.get_event_loop()
        token = await loop.run_in_executor(None, self._fetch_new_token)
        
        if token:
            # 验证新获取的Token
            is_valid = await self.verify_token(token)
            if is_valid:
                # 保存到数据库
                self._save_token_to_db(token)
                # 更新内存缓存
                self._token = token
                self._token_expiry = datetime.now() + timedelta(hours=1)
                logger.info(f"成功获取并验证新Token")
                return True
            else:
                logger.error(f"新获取的Token无效，初始化失败")
                return False
        else:
            logger.error(f"无法获取新Token，初始化失败")
            return False

# 创建全局TokenManager实例
token_manager = TokenManager() 