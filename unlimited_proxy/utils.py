"""
实用工具模块

包含请求处理、格式转换和其他辅助功能。
"""

import json
import time
import uuid
import logging
import random
import re
import os
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional, Union, List, Tuple

from .config import config, get_random_browser_config  # 添加缺少的config导入

# 配置日志
logger = logging.getLogger("unlimited_proxy.utils")

def get_exponential_backoff_delay(retry_count: int) -> int:
    """
    计算指数退避延迟时间（毫秒）
    
    Args:
        retry_count: 当前重试次数
        
    Returns:
        退避延迟时间（毫秒）
    """
    # 从配置中读取初始延迟和最大延迟
    initial_delay = config.get("api.initial_retry_delay_ms", 100)  # 默认初始延迟100毫秒
    max_delay = config.get("api.max_retry_delay_ms", 5000)  # 默认最大延迟5000毫秒
    
    # 计算指数退避延迟，但不超过最大延迟
    delay = min(initial_delay * (2 ** retry_count), max_delay)
    
    # 加入随机抖动，避免多个客户端同时重试
    jitter = random.uniform(0.8, 1.2)
    final_delay = int(delay * jitter)
    
    return final_delay

async def async_sleep(ms: int) -> None:
    """
    异步等待指定的毫秒数
    
    Args:
        ms: 等待的毫秒数
    """
    await asyncio.sleep(ms / 1000)

class ChatFormatter:
    """聊天格式化工具，处理不同格式之间的转换"""
    
    @staticmethod
    def openai_to_unlimited(payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        将OpenAI格式数据转换为UnlimitedAI格式
        
        Args:
            payload: OpenAI格式数据
            
        Returns:
            UnlimitedAI格式数据
        """
        unlimited_payload = {}
        
        # 设置模型
        model = payload.get("model", "chat-model-reasoning")
        # 从模型名中提取基础模型名
        base_model = "chat-model-reasoning"
        if model and model.startswith("chat-model-reasoning"):
            base_model = "chat-model-reasoning"
        
        # 始终使用基础模型名
        unlimited_payload["model"] = base_model
        
        # 获取模型配置
        model_config = config.get_model_config(model)
        
        # 根据模型配置和请求参数设置thinking参数
        if model == "chat-model-reasoning-thinking" or model_config.get("thinking_enabled", False) or payload.get("thinking", False):
            unlimited_payload["thinking"] = True
            unlimited_payload["budget_tokens"] = payload.get("budget_tokens", 7999)  # 默认预算token数
        else:
            # 如果模型不支持thinking，确保thinking参数为False
            unlimited_payload["thinking"] = False
        
        # 处理消息
        messages = payload.get("messages", [])
        unlimited_payload["messages"] = messages
        
        # 确保存在系统消息
        has_system_message = any(m.get("role") == "system" for m in messages)
        if not has_system_message:
            # 添加默认系统消息
            if unlimited_payload["thinking"]:
                # 带推理的模型使用鼓励思考的系统提示
                system_message = {"role": "system", "content": "你是一个AI助手。请在回答前进行深度思考分析，展示你的推理过程。"}
            else:
                # 标准模型使用普通系统提示
                system_message = {"role": "system", "content": "你是一个有用的AI助手。"}
            
            unlimited_payload["messages"] = [system_message] + messages
        
        # 复制其他参数
        if "temperature" in payload:
            unlimited_payload["temperature"] = payload["temperature"]
        
        if "max_tokens" in payload:
            unlimited_payload["max_tokens"] = payload["max_tokens"]
        
        if "stream" in payload:
            unlimited_payload["stream"] = payload["stream"]
        
        logger.debug(f"转换后的请求数据: {json.dumps(unlimited_payload, ensure_ascii=False)}")
        return unlimited_payload
    
    @staticmethod
    def unlimited_to_openai(response_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        将UnlimitedAI格式的响应转换为OpenAI格式
        
        Args:
            response_data: UnlimitedAI格式的响应数据
            
        Returns:
            OpenAI格式的响应数据
        """
        openai_response = {
            "id": response_data.get("id", f"chatcmpl-{str(uuid.uuid4())}"),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": response_data.get("model", "gpt-3.5-turbo"),
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": response_data.get("message", "")
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": response_data.get("usage", {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            })
        }
        
        # 处理思考内容
        if "thinking" in response_data and response_data["thinking"]:
            openai_response["thinking"] = response_data["thinking"]
        
        return openai_response
    
    @staticmethod
    def format_stream_chunk(content: str, role: str = "assistant", finish_reason: Optional[str] = None) -> Dict[str, Any]:
        """
        格式化流式响应块为OpenAI格式
        
        Args:
            content: 响应内容
            role: 角色，默认为'assistant'
            finish_reason: 完成原因，默认为None
            
        Returns:
            OpenAI格式的流式响应块
        """
        chunk = {
            "id": f"chatcmpl-{str(uuid.uuid4())}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": "gpt-3.5-turbo",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "role": role,
                        "content": content
                    }
                }
            ]
        }
        
        # 如果提供了完成原因
        if finish_reason:
            chunk["choices"][0]["finish_reason"] = finish_reason
        
        return chunk
    
    @staticmethod
    def extract_thinking_content(data: str) -> Tuple[bool, str, str]:
        """
        从响应中提取思考内容
        
        Args:
            data: 响应数据
            
        Returns:
            (是否为思考内容, 提取的思考内容, 剩余的响应内容)
        """
        # 处理特殊格式的思考内容标记
        thinking_pattern = r'^g:\s*(.+)$'
        match = re.match(thinking_pattern, data)
        
        if match:
            return True, match.group(1), ""
        
        # 处理<think>...</think>格式
        think_pattern = r'<think>(.*?)</think>'
        match = re.search(think_pattern, data, re.DOTALL)
        
        if match:
            thinking_content = match.group(1).strip()
            remaining_content = re.sub(think_pattern, '', data, flags=re.DOTALL).strip()
            return True, thinking_content, remaining_content
        
        return False, "", data

class RequestUtils:
    """请求处理工具"""
    
    @staticmethod
    def prepare_headers(chat_id: str, referer_url: str) -> Dict[str, str]:
        """
        准备请求头
        
        Args:
            chat_id: 会话ID
            referer_url: 来源URL
            
        Returns:
            请求头字典
        """
        # 获取随机浏览器配置
        browser_config = get_random_browser_config()
        user_agent = browser_config["user_agent"]
        
        # 基本请求头
        headers = {
            "accept": "text/event-stream",  # 覆盖为流式响应需要的格式
            "accept-language": browser_config["accept_language"],
            "content-type": "application/json",
            "priority": "u=1, i",
            "referer": referer_url,
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
        
        return headers
    
    @staticmethod
    def generate_chat_id() -> str:
        """
        生成会话ID
        
        Returns:
            会话ID
        """
        return str(uuid.uuid4())
    
    @staticmethod
    def parse_sse_line(line: str) -> Tuple[Optional[str], Optional[str]]:
        """
        解析SSE行数据
        
        Args:
            line: SSE行数据
            
        Returns:
            (事件名, 事件数据)
        """
        if not line or line.strip() == "":
            return None, None
        
        if line.startswith("data:"):
            return "data", line[5:].strip()
        
        if line.startswith("event:"):
            return "event", line[6:].strip()
        
        return None, None
    
    @staticmethod
    def is_json(text: str) -> bool:
        """
        检查文本是否为有效的JSON
        
        Args:
            text: 要检查的文本
            
        Returns:
            是否为有效的JSON
        """
        try:
            json.loads(text)
            return True
        except (ValueError, TypeError):
            return False

    @staticmethod
    def sanitize_headers(headers: Dict[str, str]) -> Dict[str, str]:
        """
        清洗请求头，去除敏感信息
        
        Args:
            headers: 原始请求头
        
        Returns:
            清洗后的请求头
        """
        sanitized = {}
        sensitive_keys = ['authorization', 'cookie', 'x-api-token', 'api-key']
        
        for key, value in headers.items():
            key_lower = key.lower()
            if any(s in key_lower for s in sensitive_keys):
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = value
                
        return sanitized
    
    @staticmethod
    def format_request_debug(method: str, url: str, headers: Dict[str, str], data: Any = None) -> str:
        """
        格式化请求调试信息
        
        Args:
            method: 请求方法
            url: 请求URL
            headers: 请求头
            data: 请求数据
            
        Returns:
            格式化的调试信息
        """
        safe_headers = RequestUtils.sanitize_headers(headers)
        debug_parts = [
            f"HTTP Request: {method} {url}",
            f"Headers: {json.dumps(safe_headers, indent=2, ensure_ascii=False)}"
        ]
        
        if data:
            if isinstance(data, dict) or isinstance(data, list):
                debug_parts.append(f"Data: {json.dumps(data, indent=2, ensure_ascii=False)}")
            else:
                debug_parts.append(f"Data: {data}")
                
        return "\n".join(debug_parts)

class PerformanceUtils:
    """性能优化工具"""
    
    @staticmethod
    def calculate_backoff(attempt: int, base_delay: float = 0.5, max_delay: float = 10.0) -> float:
        """
        计算退避时间
        
        Args:
            attempt: 尝试次数
            base_delay: 基础延迟
            max_delay: 最大延迟
            
        Returns:
            延迟时间（秒）
        """
        delay = min(base_delay * (2 ** attempt), max_delay)
        jitter = random.uniform(0, 0.1 * delay)
        return delay + jitter
    
    @staticmethod
    def should_retry(status_code: int, retry_codes: List[int] = None) -> bool:
        """
        判断是否应该重试请求
        
        Args:
            status_code: HTTP状态码
            retry_codes: 可重试的状态码列表
            
        Returns:
            是否应该重试
        """
        if retry_codes is None:
            retry_codes = [429, 500, 502, 503, 504]
        
        return status_code in retry_codes
    
    @staticmethod
    def timeit(func):
        """
        函数执行时间装饰器
        
        Args:
            func: 要测量的函数
            
        Returns:
            装饰后的函数
        """
        def wrapper(*args, **kwargs):
            start_time = time.time()
            result = func(*args, **kwargs)
            end_time = time.time()
            elapsed = end_time - start_time
            logger.debug(f"函数 {func.__name__} 执行时间: {elapsed:.4f}秒")
            return result
            
        return wrapper
    
    @staticmethod
    def async_timeit(func):
        """
        异步函数执行时间装饰器
        
        Args:
            func: 要测量的异步函数
            
        Returns:
            装饰后的函数
        """
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            result = await func(*args, **kwargs)
            end_time = time.time()
            elapsed = end_time - start_time
            logger.debug(f"异步函数 {func.__name__} 执行时间: {elapsed:.4f}秒")
            return result
            
        return wrapper 