"""
聊天处理模块

实现聊天请求处理、转发和响应处理。
"""

import json
import time
import uuid
import logging
import asyncio
import re
from typing import Dict, Any, List, Optional, AsyncGenerator, Tuple

import httpx

from .config import config, get_random_user_agent, get_random_browser_config
from .token_manager import token_manager
from .utils import ChatFormatter, RequestUtils, PerformanceUtils

# 配置日志
logger = logging.getLogger("unlimited_proxy.chat")

# 增加API调试日志记录器
api_logger = logging.getLogger("unlimited_proxy.api_debug")
api_logger.setLevel(logging.DEBUG)

# 硬编码的API端点
API_BASE_URL = "https://app.unlimitedai.chat"
TOKEN_ENDPOINT = f"{API_BASE_URL}/api/token"
CHAT_ENDPOINT = f"{API_BASE_URL}/api/chat"

# 辅助函数
def create_default_response(model="chat-model-reasoning", content="Model is available."):
    """创建默认响应，用于模型检查或错误恢复"""
    return {
        "id": f"chatcmpl-{str(uuid.uuid4())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": content
            },
            "finish_reason": "stop"
        }],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }
    }

def format_markdown_titles(content):
    """格式化Markdown标题，确保标题格式正确"""
    
    # 记录处理前内容
    api_logger.debug("格式化前内容: " + content.replace("\n", "\\n"))
    
    # 处理空内容
    if not content or not content.strip():
        return content
    
    # 如果内容只是标题标记，直接返回
    if re.match(r'^#+\s*$', content.strip()):
        return content
    
    processed_content = content
    
    # 使用更精确的正则表达式确保正确处理标题格式
    # 确保 ### Title 格式正确，而不是变成 ## # Title
    # 匹配行首或换行后的连续#号，确保它们后面没有空格，然后添加一个空格
    processed_content = re.sub(r'(^|\n)(#+)(?=[^#\s])', r'\1\2 ', processed_content)
    
    # 检测内容是否是一个完整标题行(以#开头的行)
    is_complete_title_line = re.match(r'^#+\s+.+$', processed_content.strip())
    
    # 只有在内容中确实包含换行符或者是完整标题行时才处理标题前后的空行
    if '\n' in processed_content or is_complete_title_line:
        # 如果是完整标题行且没有以换行符结束，添加两个换行符
        if is_complete_title_line and not processed_content.endswith('\n'):
            processed_content += '\n\n'
        else:
            # 处理标题之前的换行确保标题前有一个空行(除非是文档的第一行)
            processed_content = re.sub(r'(?<!^)(?<!\n)\n(#+) ', r'\n\n\1 ', processed_content)
            
            # 处理标题之后的内容，确保标题后有一个空行
            processed_content = re.sub(r'(#+) ([^\n]*)\n(?!\n)', r'\1 \2\n\n', processed_content)
            
            # 标准化多个连续换行符为最多两个
            processed_content = re.sub(r'\n{3,}', r'\n\n', processed_content)
    
    # 记录处理后内容
    api_logger.debug("格式化后内容: " + processed_content.replace("\n", "\\n"))
    
    return processed_content

# 请求统计
class RequestStats:
    """请求统计类"""
    
    total_requests = 0
    successful_requests = 0
    token_retries = 0
    token_failures = 0
    
    @classmethod
    def log_request(cls, success=True, token_retry=False, token_failure=False):
        """记录请求统计"""
        cls.total_requests += 1
        if success:
            cls.successful_requests += 1
        if token_retry:
            cls.token_retries += 1
        if token_failure:
            cls.token_failures += 1
    
    @classmethod
    def get_stats(cls):
        """获取统计信息"""
        success_rate = 0
        if cls.total_requests > 0:
            success_rate = (cls.successful_requests / cls.total_requests) * 100
        
        return {
            "total_requests": cls.total_requests,
            "successful_requests": cls.successful_requests,
            "success_rate": f"{success_rate:.2f}%",
            "token_retries": cls.token_retries,
            "token_failures": cls.token_failures
        }

class ChatClient:
    """聊天客户端，处理与UnlimitedAI的通信"""
    
    def __init__(self):
        """初始化聊天客户端"""
        self._http_client = None
        self._init_http_client()
    
    def _init_http_client(self):
        """初始化HTTP客户端"""
        if not self._http_client:
            client_config = {
                "http2": config.get("performance.http2_enabled", True),
                "limits": httpx.Limits(
                    max_connections=config.get("performance.connection_pool_size", 100),
                    max_keepalive_connections=config.get("performance.keep_alive_connections", 30),
                    keepalive_expiry=config.get("performance.keepalive_expiry", 120.0)
                ),
                "timeout": httpx.Timeout(
                    connect=config.get("api.connect_timeout", 10.0),
                    read=config.get("api.read_timeout", 180.0),
                    write=config.get("api.write_timeout", 30.0),
                    pool=config.get("api.pool_timeout", 20.0)
                ),
                "follow_redirects": True,
                # 注意：AsyncClient不支持直接传入retry_backend和max_retries参数
                # 重试逻辑将在请求方法中单独实现
            }
            
            # 设置代理
            proxies = config.get_proxies()
            if proxies:
                client_config["proxies"] = proxies
            
            self._http_client = httpx.AsyncClient(**client_config)
            logger.info("HTTP客户端已初始化，配置参数：连接超时=%s秒，读取超时=%s秒，写入超时=%s秒，池超时=%s秒，连接保持超时=%s秒，连接池大小=%s，保持连接数=%s，最大重试次数=%s",
                       config.get("api.connect_timeout", 10.0),
                       config.get("api.read_timeout", 180.0),
                       config.get("api.write_timeout", 30.0),
                       config.get("api.pool_timeout", 20.0),
                       config.get("performance.keepalive_expiry", 120.0),
                       config.get("performance.connection_pool_size", 100),
                       config.get("performance.keep_alive_connections", 30),
                       config.get("api.max_retries", 3))
    
    async def close(self):
        """关闭客户端资源"""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
    
    async def reconnect(self):
        """强制重新连接HTTP客户端"""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._init_http_client()
        return self._http_client is not None
    
    def _is_model_check_request(self, payload: Dict[str, Any]) -> bool:
        """
        检测是否为模型检查请求
        
        Args:
            payload: 请求数据
            
        Returns:
            是否为模型检查请求
        """
        # 检查消息长度和内容
        messages = payload.get("messages", [])
        
        # 模型检查请求通常消息数量较少
        if len(messages) <= 2:
            # 检查最后一条消息内容
            if messages and "content" in messages[-1]:
                content = messages[-1]["content"].lower()
                
                # 模型检查常见关键词
                check_keywords = [
                    "are you available", 
                    "test", 
                    "check", 
                    "available", 
                    "可用", 
                    "测试", 
                    "检查",
                    "模型是否可用"
                ]
                
                # 检查是否包含关键词
                if any(keyword in content for keyword in check_keywords):
                    return True
                    
                # 检查是否为短请求（通常模型检查请求内容较短）
                if len(content) < 20:
                    return True
        
        return False
    
    async def handle_chat_request(self, payload: Dict[str, Any], debug: bool = False, client_ip: str = None) -> Dict[str, Any]:
        """
        处理非流式聊天请求
        
        Args:
            payload: OpenAI格式的请求数据
            debug: 是否启用调试模式
            client_ip: 客户端IP地址，用于Token管理
            
        Returns:
            OpenAI格式的响应数据
        """
        # 记录请求开始时间
        start_time = time.time()
        
        # 验证模型名称
        available_models = config.get_available_models()
        available_model_ids = [model["id"] for model in available_models]
        
        requested_model = payload.get("model", "chat-model-reasoning")
        if requested_model not in available_model_ids:
            logger.warning(f"请求了无效的模型: {requested_model}")
            return {"error": f"模型 '{requested_model}' 不可用，支持的模型: {', '.join(available_model_ids)}", "code": "INVALID_MODEL", "status": 400}
        
        # 使用字典存储日志状态，防止重复日志
        _request_log_state = {
            "request_logged": False,
            "response_logged": False
        }
        
        # 检查流式模式，非流式处理
        if payload.get("stream", False):
            logger.warning("非流式API收到了流式请求，自动切换到流式处理")
            full_response = {"content": "", "thinking": ""}
            
            async for chunk in self.handle_chat_stream(payload, debug=debug, client_ip=client_ip):
                if "error" in chunk:
                    # 如果已经是标准错误格式，直接传递
                    if "status" in chunk:
                        return {"error": chunk["error"], "status": chunk["status"]}
                    # 否则使用默认状态码500
                    return {"error": chunk["error"], "status": 500}
                
                if "choices" in chunk and chunk["choices"] and "delta" in chunk["choices"][0]:
                    delta = chunk["choices"][0]["delta"]
                    if "content" in delta:
                        full_response["content"] += delta["content"]
                
                # 处理思考内容
                if "thinking" in chunk:
                    full_response["thinking"] += chunk["thinking"] + "\n"
            
            # 创建完整的非流式响应
            return {
                "id": f"chatcmpl-{str(uuid.uuid4())}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": payload.get("model", "chat-model-reasoning"),
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": full_response["content"]
                    },
                    "finish_reason": "stop"
                }],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                },
                "thinking": full_response["thinking"]
            }
        
        # 模型检查请求特殊处理
        is_model_check = self._is_model_check_request(payload)
        if is_model_check:
            logger.info("检测到模型检查请求，直接返回模型可用响应")
            return create_default_response(model=payload.get("model", "chat-model-reasoning"))
        
        # 转换为UnlimitedAI格式
        unlimited_payload = ChatFormatter.openai_to_unlimited(payload)
        
        # 调试日志
        if debug:
            logger.debug(f"转换后的请求数据: {json.dumps(unlimited_payload, ensure_ascii=False)}")
        
        # 获取Token - 使用客户端IP
        token = token_manager.get_token(client_ip=client_ip)
        if not token:
            logger.error("无法获取有效Token")
            return {"error": "无法获取有效Token", "code": "INVALID_TOKEN", "status": 401}
        
        # 生成新的聊天ID
        chat_id = str(uuid.uuid4())
        
        # 获取随机浏览器配置，包含完整的请求头信息
        browser_config = get_random_browser_config()
        user_agent = browser_config["user_agent"]
        
        # 准备请求头
        headers = {
            "accept": "text/event-stream",  # 流式响应需要使用固定的accept头
            "accept-language": browser_config["accept_language"],
            "content-type": "application/json",
            "priority": "u=1, i",  # 保留流式响应的优先级设置
            "x-api-token": token,
            "origin": API_BASE_URL,
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
        
        # 准备消息
        messages = unlimited_payload.get("messages", [])
        formatted_messages = []
        
        for msg in messages:
            formatted_messages.append({
                "id": str(uuid.uuid4()),
                "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                "role": msg.get("role"),
                "content": msg.get("content", ""),
                "parts": [{"type": "text", "text": msg.get("content", "")}]
            })
        
        # 构建最终请求体
        request_body = {
            "id": chat_id,
            "messages": formatted_messages,
            "selectedChatModel": unlimited_payload.get("model", "chat-model-reasoning")
        }
        
        # 如果启用思考模式
        if unlimited_payload.get("thinking", False):
            budget_tokens = unlimited_payload.get("budget_tokens", 7999)
            request_body["thinking"] = {
                "type": "enabled",
                "budget_tokens": budget_tokens
            }
            
            # 处理系统消息中的思考提示
            sys_message_idx = next((i for i, m in enumerate(formatted_messages) if m["role"] == "system"), -1)
            
            if sys_message_idx >= 0:
                current_content = formatted_messages[sys_message_idx]["content"]
                if "深度思考" not in current_content and "思考分析" not in current_content:
                    formatted_messages[sys_message_idx]["content"] += "\n请在回答前进行深度思考分析，展示你的推理过程。"
                    formatted_messages[sys_message_idx]["parts"][0]["text"] = formatted_messages[sys_message_idx]["content"]
            else:
                # 添加系统消息
                formatted_messages.insert(0, {
                    "id": str(uuid.uuid4()),
                    "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                    "role": "system",
                    "content": "你是一个AI助手，请在回答前进行深度思考分析，展示你的推理过程。",
                    "parts": [
                        {
                            "type": "text", 
                            "text": "你是一个AI助手，请在回答前进行深度思考分析，展示你的推理过程。"
                        }
                    ]
                })
            
            request_body["messages"] = formatted_messages
        
        # 添加其他参数
        if "temperature" in unlimited_payload:
            request_body["temperature"] = unlimited_payload["temperature"]
        
        if "max_tokens" in unlimited_payload:
            request_body["maxOutputTokens"] = unlimited_payload["max_tokens"]
        
        # 调试日志 - 根据日志级别记录不同详细程度的请求信息
        if not _request_log_state["request_logged"]:
            api_logger.info("===== API请求开始 =====")
            api_logger.info(f"请求URL: {CHAT_ENDPOINT}")
            # 将详细的请求信息移至DEBUG级别
            api_logger.debug(f"请求方法: POST")
            api_logger.debug(f"请求头: {json.dumps(dict(headers), ensure_ascii=False)}")
            api_logger.debug(f"请求体: {json.dumps(request_body, ensure_ascii=False)}")
            _request_log_state["request_logged"] = True
        
        try:
            # 发送请求
            logger.info(f"发送非流式请求到: {CHAT_ENDPOINT}")
            
            response = await self._http_client.post(
                CHAT_ENDPOINT,
                headers=headers,
                json=request_body
            )
            
            # 记录响应详情
            if not _request_log_state["response_logged"]:
                api_logger.info("===== API响应开始 =====")
                api_logger.info(f"响应状态码: {response.status_code}")
                # 将详细的响应信息移至DEBUG级别
                api_logger.debug(f"响应头: {json.dumps(dict(response.headers), ensure_ascii=False)}")
                api_logger.debug(f"原始响应内容: {response.text}")
                api_logger.info("===== API响应结束 =====")
                _request_log_state["response_logged"] = True
            
            # 检查响应状态
            status_code = response.status_code
            
            # 处理Token失效
            if status_code in [401, 403]:
                logger.warning(f"Token可能已失效 [HTTP {status_code}]，尝试获取新Token")
                token_manager.record_token_error(token, status_code)
                new_token = token_manager.get_token(force_new=True, client_ip=client_ip)
                
                if new_token:
                    logger.info("使用新Token重试请求")
                    headers["x-api-token"] = new_token
                    
                    # 重置日志状态，为重试请求记录新的日志
                    _request_log_state["response_logged"] = False
                    
                    # 重试请求
                    response = await self._http_client.post(
                        CHAT_ENDPOINT,
                        headers=headers,
                        json=request_body
                    )
                    
                    # 记录重试响应详情
                    if not _request_log_state["response_logged"]:
                        api_logger.info("===== API重试响应开始 =====")
                        api_logger.info(f"响应状态码: {response.status_code}")
                        api_logger.debug(f"响应头: {json.dumps(dict(response.headers), ensure_ascii=False)}")
                        api_logger.debug(f"原始响应内容: {response.text}")
                        api_logger.info("===== API重试响应结束 =====")
                        _request_log_state["response_logged"] = True
                    
                    # 检查重试响应状态
                    new_status_code = response.status_code
                    if new_status_code != 200:
                        logger.error(f"使用新Token重试请求失败: HTTP {new_status_code}")
                        RequestStats.log_request(success=False, token_retry=True, token_failure=True)
                        
                        # 为429错误返回特殊格式
                        if new_status_code == 429:
                            # 从配置获取限速参数
                            max_rate = config.get("api.max_request_rate", 10)
                            time_window = config.get("api.time_window", 10)
                            
                            # 创建标准格式的错误对象
                            error_message = f"IP请求频率超出限制 ({max_rate}次/{time_window}秒)，请于{time_window}秒后重新请求"
                            logger.warning(f"IP限速触发: {error_message}")
                            return {"error": error_message, "code": "TOO_MANY_REQUESTS", "status": 429}
                        
                        # 其他错误使用统一格式
                        error_message = {"error":"API请求失败","code":f"HTTP_{new_status_code}"}
                        return {"error": error_message, "status": new_status_code}
                    
                    # 如果重试成功，继续处理正常响应
                    logger.info("使用新Token重试请求成功")
                    RequestStats.log_request(success=True, token_retry=True)
                    status_code = 200
                else:
                    logger.error("无法获取新的有效Token")
                    RequestStats.log_request(success=False, token_failure=True)
                    return {"error": "无法获取有效Token", "code": "INVALID_TOKEN", "status": 401}
            
            # 处理限速错误
            if status_code == 429:
                # 从配置获取限速参数
                max_rate = config.get("api.max_request_rate", 10)
                time_window = config.get("api.time_window", 10)
                
                # 创建标准格式的错误对象
                error_message = f"IP请求频率超出限制 ({max_rate}次/{time_window}秒)，请于{time_window}秒后重新请求"
                logger.warning(f"IP限速触发: {error_message}")
                RequestStats.log_request(success=False)
                return {"error": error_message, "code": "TOO_MANY_REQUESTS", "status": 429}
            
            if status_code != 200:
                logger.error(f"请求失败: HTTP {status_code}")
                RequestStats.log_request(success=False)
                return {"error": f"API请求失败: HTTP {status_code}", "code": f"HTTP_{status_code}", "status": status_code}
            
            # 解析响应
            try:
                # 先检查响应内容，避免空响应导致解析失败
                response_text = response.text.strip()
                
                if not response_text:
                    logger.error("收到空响应")
                    if is_model_check:
                        # 对于模型检查请求，返回一个简单的成功响应
                        logger.info("这是模型检查请求，返回默认成功响应")
                        return create_default_response(model=payload.get("model", "chat-model-reasoning"))
                    else:
                        error_message = {"error":"API返回空响应","code":"EMPTY_RESPONSE"}
                        return {"error": "API返回空响应", "code": "EMPTY_RESPONSE", "status": 500}
                
                # 检查响应格式是否为UnlimitedAI的特殊流式格式
                if response_text.startswith('f:') or response_text.startswith('0:'):
                    logger.info(f"收到特殊格式响应，尝试解析: {response_text[:100]}...")
                    
                    # 尝试提取内容
                    content = ""
                    thinking_content = ""
                    lines = response_text.split('\n')
                    
                    for line in lines:
                        # 提取标准内容行
                        if line.startswith('0:"'):
                            # 处理类似 0:"How " 格式的行
                            content_part = line[3:-1] if line.endswith('"') else line[3:]
                            content += content_part
                        
                        # 提取messageId (可能包含在f:中)
                        elif line.startswith('f:') and '{' in line and '}' in line:
                            try:
                                # 尝试提取JSON部分
                                json_part = line[line.index('{'):line.rindex('}')+1]
                                json_data = json.loads(json_part)
                                if "messageId" in json_data:
                                    logger.info(f"提取到消息ID: {json_data['messageId']}")
                            except:
                                pass
                        
                        # 提取思考内容行
                        elif line.startswith('g:"'):
                            thinking_part = line[3:-1] if line.endswith('"') else line[3:]
                            thinking_content += thinking_part + "\n"
                    
                    # 对于模型检查请求或内容提取成功
                    if is_model_check or content:
                        if content:
                            logger.info(f"成功从特殊格式提取内容，长度: {len(content)}字符")
                            response = create_default_response(model=payload.get("model", "chat-model-reasoning"), content=content)
                            
                            # 如果有思考内容，添加到响应中
                            if thinking_content and unlimited_payload.get("thinking", False):
                                response["thinking"] = thinking_content
                            
                            return response
                        else:
                            logger.info("这是模型检查请求，返回默认成功响应")
                            return create_default_response(model=payload.get("model", "chat-model-reasoning"))
                
                # 尝试解析为JSON
                try:
                    response_data = response.json()
                except json.JSONDecodeError as e:
                    # 仍然记录错误，但级别降为WARNING
                    logger.warning(f"JSON解析错误: {e}, 响应内容前100字符: '{response_text[:100]}'")
                    
                    # 对于模型检查请求的特殊处理
                    if is_model_check:
                        logger.info("这是模型检查请求，返回默认成功响应")
                        return create_default_response(model=payload.get("model", "chat-model-reasoning"))
                    
                    # 提供更详细的错误上下文
                    try:
                        error_context = f"响应状态码: {response.status_code}, 内容类型: {response.headers.get('content-type', '未知')}"
                        if hasattr(response, 'text') and response.text:
                            error_context += f", 响应前100字符: '{response.text[:100]}'"
                    except:
                        error_context = "无法获取错误上下文"
                    
                    return {"error": f"API返回非JSON格式响应: {e}", "code": "INVALID_JSON", "details": error_context, "status": 500}
                
                # 调试日志
                if debug:
                    logger.debug(f"响应数据: {json.dumps(response_data, ensure_ascii=False)[:500]}...")
                else:
                    # 将原始响应数据移至DEBUG级别
                    logger.debug(f"原始API响应数据(格式调试): {json.dumps(response_data, ensure_ascii=False)[:1000]}")
                
                # 提取消息内容
                if "result" in response_data:
                    message_content = response_data["result"]
                    # 将原始内容移至DEBUG级别
                    logger.debug(f"原始未格式化内容(格式调试): {message_content[:1000]}")
                    
                    # 使用专用函数格式化Markdown标题
                    message_content = format_markdown_titles(message_content)
                    
                    # 将格式化后内容移至DEBUG级别
                    logger.debug(f"格式化后内容(格式调试): {message_content[:1000]}")
                else:
                    message_content = ""
                
                # 提取思考内容
                thinking_content = ""
                if "thinking" in response_data:
                    thinking_content = response_data["thinking"]
                    # 使用专用函数格式化Markdown标题
                    thinking_content = format_markdown_titles(thinking_content)
                
                # 构建OpenAI格式响应
                openai_response = {
                    "id": f"chatcmpl-{str(uuid.uuid4())}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": payload.get("model", "chat-model-reasoning"),
                    "choices": [{
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": message_content
                        },
                        "finish_reason": "stop"
                    }],
                    "usage": {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0
                    }
                }
                
                # 添加思考内容
                if thinking_content:
                    openai_response["thinking"] = thinking_content
                
                # 记录请求耗时
                elapsed = time.time() - start_time
                logger.info(f"请求处理完成，耗时: {elapsed:.2f}秒，内容长度: {len(message_content)}字符")
                RequestStats.log_request(success=True)
                
                return openai_response
            
            except Exception as e:
                logger.error(f"解析响应失败: {str(e)}")
                # 对于模型检查请求的特殊处理
                if is_model_check:
                    logger.info("这是模型检查请求，尽管发生错误，仍返回默认成功响应")
                    return create_default_response(model=payload.get("model", "chat-model-reasoning"))
                
                RequestStats.log_request(success=False)
                try:
                    error_context = f"响应状态码: {response.status_code}, 内容类型: {response.headers.get('content-type', '未知')}"
                    if hasattr(response, 'text') and response.text:
                        error_context += f", 响应前100字符: '{response.text[:100]}'"
                except:
                    error_context = "无法获取错误上下文"
                
                return {"error": f"解析响应失败: {str(e)}", "code": "PARSE_ERROR", "details": error_context, "status": 500}
        
        except httpx.TimeoutException:
            logger.error("请求超时")
            RequestStats.log_request(success=False)
            return {"error": "请求超时，请稍后重试", "code": "REQUEST_TIMEOUT", "status": 504}
        
        except Exception as e:
            logger.error(f"请求处理出错: {str(e)}")
            RequestStats.log_request(success=False)
            return {"error": f"处理请求时出错: {str(e)}", "code": "REQUEST_ERROR", "status": 500}
    
    async def handle_chat_stream(self, payload: Dict[str, Any], debug: bool = False, client_ip: str = None) -> AsyncGenerator[Dict[str, Any], None]:
        """
        处理流式聊天请求
        
        Args:
            payload: OpenAI格式的请求数据
            debug: 是否启用调试模式
            client_ip: 客户端IP地址，用于Token管理
            
        Yields:
            OpenAI格式的响应数据块
        """
        # 记录请求开始时间
        start_time = time.time()
        response_id = f"chatcmpl-{uuid.uuid4()}"
        
        # 验证模型名称
        available_models = config.get_available_models()
        available_model_ids = [model["id"] for model in available_models]
        
        requested_model = payload.get("model", "chat-model-reasoning")
        if requested_model not in available_model_ids:
            logger.warning(f"请求了无效的模型: {requested_model}")
            yield {"error": f"模型 '{requested_model}' 不可用，支持的模型: {', '.join(available_model_ids)}", "code": "INVALID_MODEL", "status": 400}
            return
        
        # 使用类级别变量来防止重复日志
        # 注意：这不是线程安全的，但在异步环境下对于单一请求是可接受的
        _chat_stream_log_state = {
            "request_logged": False,
            "response_logged": False,
            "response_end_logged": False
        }
        
        # 准备UnlimitedAI格式的请求
        unlimited_payload = ChatFormatter.openai_to_unlimited(payload)
        unlimited_payload["stream"] = True
        
        # 调试日志
        if debug:
            logger.debug(f"转换后的请求数据: {json.dumps(unlimited_payload, ensure_ascii=False)}")
        
        # 获取Token - 使用客户端IP
        token = token_manager.get_token(client_ip=client_ip)
        if not token:
            logger.error("无法获取有效Token")
            yield {"error": "无法获取有效Token", "code": "INVALID_TOKEN", "status": 401}
            return
        
        # 生成新的聊天ID
        chat_id = str(uuid.uuid4())
        
        # 获取随机浏览器配置，包含完整的请求头信息
        browser_config = get_random_browser_config()
        user_agent = browser_config["user_agent"]
        
        # 准备请求头
        headers = {
            "accept": "text/event-stream",  # 流式响应需要使用固定的accept头
            "accept-language": browser_config["accept_language"],
            "content-type": "application/json",
            "priority": "u=1, i",  # 保留流式响应的优先级设置
            "x-api-token": token,
            "origin": API_BASE_URL,
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
        
        # 准备消息
        messages = unlimited_payload.get("messages", [])
        formatted_messages = []
        
        for msg in messages:
            formatted_messages.append({
                "id": str(uuid.uuid4()),
                "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                "role": msg.get("role"),
                "content": msg.get("content", ""),
                "parts": [{"type": "text", "text": msg.get("content", "")}]
            })
        
        # 构建最终请求体
        request_body = {
            "id": chat_id,  # 使用新生成的UUID作为chat_id
            "messages": formatted_messages,
            "selectedChatModel": unlimited_payload.get("model", "chat-model-reasoning")
        }
        
        # 如果启用思考模式
        if unlimited_payload.get("thinking", False):
            budget_tokens = unlimited_payload.get("budget_tokens", 7999)
            request_body["thinking"] = {
                "type": "enabled",
                "budget_tokens": budget_tokens
            }
            
            # 处理系统消息中的思考提示
            sys_message_idx = next((i for i, m in enumerate(formatted_messages) if m["role"] == "system"), -1)
            
            if sys_message_idx >= 0:
                current_content = formatted_messages[sys_message_idx]["content"]
                if "深度思考" not in current_content and "思考分析" not in current_content:
                    formatted_messages[sys_message_idx]["content"] += "\n请在回答前进行深度思考分析，展示你的推理过程。"
                    formatted_messages[sys_message_idx]["parts"][0]["text"] = formatted_messages[sys_message_idx]["content"]
            else:
                # 添加系统消息
                formatted_messages.insert(0, {
                    "id": str(uuid.uuid4()),
                    "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                    "role": "system",
                    "content": "你是一个AI助手。请在回答前进行深度思考分析，展示你的推理过程。",
                    "parts": [
                        {
                            "type": "text", 
                            "text": "你是一个AI助手。请在回答前进行深度思考分析，展示你的推理过程。"
                        }
                    ]
                })
            
            request_body["messages"] = formatted_messages
        
        # 添加其他参数
        if "temperature" in unlimited_payload:
            request_body["temperature"] = unlimited_payload["temperature"]
        
        if "max_tokens" in unlimited_payload:
            request_body["maxOutputTokens"] = unlimited_payload["max_tokens"]
        
        # 记录流式请求的详细信息（使用统一的日志状态控制）
        if not _chat_stream_log_state["request_logged"]:
            api_logger.info("===== 流式API请求开始 =====")
            api_logger.info(f"请求URL: {CHAT_ENDPOINT}")
            # 将详细的请求信息移至DEBUG级别
            api_logger.debug(f"请求方法: POST (流式)")
            api_logger.debug(f"请求头: {json.dumps(dict(headers), ensure_ascii=False)}")
            api_logger.debug(f"请求体: {json.dumps(request_body, ensure_ascii=False)}")
            _chat_stream_log_state["request_logged"] = True
        
        try:
            # 首先发送角色信息
            yield {
                "id": f"chatcmpl-{uuid.uuid4()}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": payload.get("model", "chat-model-reasoning"),
                "choices": [{
                    "index": 0,
                    "delta": {"role": "assistant"}
                }]
            }
            
            # 发送流式请求并处理响应
            token_retry = False
            max_retries = config.get("api.max_retries", 3)
            
            for retry_count in range(max_retries + 1):
                if retry_count > 0:
                    logger.info(f"使用新Token进行第{retry_count}次重试")
                    # 重置响应日志状态，允许为新的重试请求记录新的响应日志
                    _chat_stream_log_state["response_logged"] = False
                
                try:
                    async with self._http_client.stream(
                        "POST",
                        CHAT_ENDPOINT,
                        headers=headers,
                        json=request_body,
                        timeout=config.get("api.read_timeout", 120.0)
                    ) as response:
                        # 检查响应状态
                        status_code = response.status_code
                        
                        # 记录响应状态（使用统一的日志状态控制）
                        if not _chat_stream_log_state["response_logged"]:
                            api_logger.info("===== 流式API响应开始 =====")
                            api_logger.info(f"响应状态码: {status_code}")
                            # 将详细的响应信息移至DEBUG级别
                            api_logger.debug(f"响应头: {json.dumps(dict(response.headers), ensure_ascii=False)}")
                            _chat_stream_log_state["response_logged"] = True
                        
                        # 处理错误状态
                        if status_code != 200:
                            logger.error(f"流式请求失败: HTTP {status_code}")
                            
                            # 处理Token失效
                            if status_code in [401, 403] and not token_retry:
                                logger.warning(f"Token可能已失效 [HTTP {status_code}]，尝试获取新Token")
                                token_manager.record_token_error(token, status_code)
                                new_token = token_manager.get_token(force_new=True, client_ip=client_ip)
                                
                                if new_token:
                                    logger.info("使用新Token重试请求")
                                    headers["x-api-token"] = new_token
                                    token_retry = True
                                    # 继续外部循环进行重试
                                    continue
                            
                            # 如果是429状态码，返回友好的限速错误消息
                            if status_code == 429:
                                # 从配置获取限速参数
                                max_rate = config.get("api.max_request_rate", 10)
                                time_window = config.get("api.time_window", 10)
                                
                                # 创建标准格式的错误对象
                                error_message = f"IP请求频率超出限制 ({max_rate}次/{time_window}秒)，请于{time_window}秒后重新请求"
                                logger.warning(f"IP限速触发: {error_message}")
                                yield {"error": error_message, "code": "TOO_MANY_REQUESTS", "status": 429}
                                return
                            
                            # 如果不能重试或者重试也失败了，则返回标准格式的错误
                            yield {"error": f"API请求失败: HTTP {status_code}", "code": f"HTTP_{status_code}", "status": status_code}
                            return
                        
                        # 处理流式响应
                        buffer = b""
                        thinking_buffer = ""
                        full_response_log = ""
                        
                        # 新增累积缓冲区相关变量
                        MAX_BUFFER_SIZE = 3  # 最大缓冲区大小，超过此大小将刷新缓冲区
                        FLUSH_INTERVAL = 0.03  # 刷新间隔（秒）
                        accumulated_content = ""  # 累积的常规内容
                        accumulated_thinking = ""  # 累积的thinking内容
                        last_flush_time = time.time()  # 上次刷新时间
                        # 标题处理相关变量
                        awaiting_title_content = False  # 是否正在等待标题后续内容
                        potential_title = ""  # 潜在的标题内容
                        
                        # 添加内容检查变量
                        received_any_content = False  # 是否接收到任何内容
                        last_chunk_time = time.time()  # 上次接收到数据的时间
                        start_streaming_time = time.time()  # 开始流式响应的时间
                        empty_response_timeout = config.get("api.empty_response_timeout", 5.0)  # 允许空响应的最大时间（秒）
                        
                        async for chunk in response.aiter_bytes():
                            if not chunk:
                                # 检查是否超过空响应超时时间
                                if not received_any_content and (time.time() - start_streaming_time) > empty_response_timeout:
                                    logger.warning(f"流式响应超时未接收到任何内容，已等待{time.time() - start_streaming_time:.2f}秒")
                                    break
                                continue
                            
                            # 记录已接收到内容
                            received_any_content = True
                            last_chunk_time = time.time()
                            
                            # 更新缓冲区
                            buffer += chunk
                            
                            # 处理完整行
                            while b'\n' in buffer:
                                line_bytes, buffer = buffer.split(b'\n', 1)
                                
                                if not line_bytes:
                                    continue
                                
                                try:
                                    line = line_bytes.decode('utf-8').strip()
                                    
                                    # 记录流式响应原始行内容
                                    api_logger.debug(f"流式响应原始行: {line}")
                                    full_response_log += line + "\n"  # 记录完整响应
                                    
                                    if not line:
                                        continue
                                    
                                    # 处理数据行
                                    if line.startswith('data:'):
                                        data = line[5:].strip()
                                        
                                        if data == '[DONE]':
                                            continue
                                        
                                        # 尝试解析JSON
                                        try:
                                            json_data = json.loads(data)
                                            
                                            # 记录JSON解析结果
                                            api_logger.debug(f"JSON数据: {json.dumps(json_data, ensure_ascii=False)}")
                                            
                                            # 处理内容
                                            if "content" in json_data and json_data["content"]:
                                                content = json_data["content"]
                                                # 检查是否是标题开始
                                                if not awaiting_title_content and content.strip().startswith('#'):
                                                    # 判断是否只包含标题标记且没有实际标题内容，或者是不完整的标题行
                                                    is_title_marker = re.match(r'^#+\s*$', content.strip())
                                                    is_partial_title = re.match(r'^#+\s+.+$', content.strip()) and not content.strip().endswith('\n')
                                                    
                                                    if is_title_marker or is_partial_title:
                                                        # 标记为等待标题内容的状态
                                                        potential_title = content
                                                        awaiting_title_content = True
                                                        # 不立即累积，等待标题的实际内容
                                                        api_logger.debug(f"发现标题标记或不完整标题: {content}")
                                                        continue
                                                # 如果正在等待标题内容并收到了内容
                                                elif awaiting_title_content:
                                                    # 检查内容不是另一个标题标记
                                                    if not content.strip().startswith('#'):
                                                        # 拼接完整标题
                                                        full_title = potential_title.rstrip() + content
                                                        api_logger.debug(f"拼接完整标题: {full_title}")
                                                        
                                                        # 确保标题后有换行
                                                        if not full_title.endswith('\n'):
                                                            full_title += '\n\n'
                                                        elif not full_title.endswith('\n\n'):
                                                            full_title += '\n'
                                                            
                                                        # 将完整标题添加到累积内容
                                                        accumulated_content += full_title
                                                        # 使用字符串连接代替replace方法，避免f-string中的反斜杠问题
                                                        api_logger.debug("添加标题到累积内容后: " + accumulated_content)
                                                        
                                                        # 重置标题等待状态
                                                        potential_title = ""
                                                        awaiting_title_content = False
                                                    else:
                                                        # 如果收到了新的标题标记，先处理之前的标题标记
                                                        if potential_title.strip():
                                                            # 确保前一个标题标记结束有换行
                                                            if not potential_title.endswith('\n'):
                                                                potential_title += '\n\n'
                                                            accumulated_content += potential_title
                                                        potential_title = content
                                                        api_logger.debug(f"发现新标题标记，替换等待状态: {content}")
                                                        continue
                                                else:
                                                    # 正常累积内容
                                                    accumulated_content += content
                                                
                                                # 检查是否应该刷新缓冲区
                                                current_time = time.time()
                                                should_flush = len(accumulated_content) >= MAX_BUFFER_SIZE or (current_time - last_flush_time) >= FLUSH_INTERVAL
                                                
                                                if should_flush and accumulated_content:
                                                    # 格式化和输出累积的内容
                                                    formatted_content = format_markdown_titles(accumulated_content)
                                                    api_logger.debug(f"刷新内容到客户端，长度: {len(formatted_content)}")
                                                    yield {
                                                        "id": f"chatcmpl-{uuid.uuid4()}",
                                                        "object": "chat.completion.chunk",
                                                        "created": int(time.time()),
                                                        "model": payload.get("model", "chat-model-reasoning"),
                                                        "choices": [{
                                                            "index": 0,
                                                            "delta": {"content": formatted_content}
                                                        }]
                                                    }
                                                    # 重置累积和更新刷新时间
                                                    accumulated_content = ""
                                                    last_flush_time = current_time
                                            
                                            # 处理思考内容
                                            if "thinking" in json_data and unlimited_payload.get("thinking", False):
                                                thinking = json_data["thinking"]
                                                # 将思考内容添加到累积缓冲区
                                                accumulated_thinking += thinking
                                                
                                                # 评估是否足够大或足够时间
                                                current_time = time.time()
                                                should_flush_thinking = len(accumulated_thinking) >= MAX_BUFFER_SIZE or (current_time - last_flush_time) >= FLUSH_INTERVAL
                                                
                                                if should_flush_thinking and accumulated_thinking:
                                                    # 格式化累积的思考内容
                                                    formatted_thinking = format_markdown_titles(accumulated_thinking)
                                                    api_logger.debug(f"刷新思考内容到客户端，长度: {len(formatted_thinking)}")
                                                    yield {
                                                        "id": f"chatcmpl-{uuid.uuid4()}",
                                                        "object": "chat.completion.chunk",
                                                        "created": int(time.time()),
                                                        "model": payload.get("model", "chat-model-reasoning"),
                                                        "choices": [{
                                                            "index": 0,
                                                            "delta": {"thinking": formatted_thinking}
                                                        }]
                                                    }
                                                    # 重置累积和更新刷新时间
                                                    accumulated_thinking = ""
                                                    last_flush_time = current_time
                                        
                                        except json.JSONDecodeError:
                                            # 非JSON格式，可能是特殊格式文本
                                            if data and data != '[DONE]':
                                                # 处理内容中的转义字符
                                                content = data.replace('\\n', '\n')
                                                
                                                # 使用专用函数格式化Markdown标题
                                                content = format_markdown_titles(content)
                                                
                                                api_logger.debug(f"非JSON格式数据直接传递: {content[:100]}...")
                                                yield {
                                                    "id": f"chatcmpl-{uuid.uuid4()}",
                                                    "object": "chat.completion.chunk",
                                                    "created": int(time.time()),
                                                    "model": payload.get("model", "chat-model-reasoning"),
                                                    "choices": [{
                                                        "index": 0,
                                                        "delta": {"content": content}
                                                    }]
                                                }
                                    
                                    # 处理特殊格式（g:思考内容，0:普通内容）
                                    elif line.startswith('0:') or (len(line) > 1 and line[0] == '0' and line[1] == ':'):
                                        # 提取内容
                                        content = line[2:].strip()
                                        # 去除引号
                                        if content.startswith('"') and content.endswith('"'):
                                            content = content[1:-1]
                                        
                                        # 处理可能的转义字符
                                        try:
                                            content = json.loads(f'"{content}"')
                                        except json.JSONDecodeError:
                                            # 如果JSON解析失败，回退到简单替换
                                            content = content.replace('\\n', '\n')
                                        
                                        # 累积内容
                                        accumulated_content += content
                                        
                                        # 检查是否应该刷新缓冲区
                                        current_time = time.time()
                                        should_flush = len(accumulated_content) >= MAX_BUFFER_SIZE or (current_time - last_flush_time) >= FLUSH_INTERVAL
                                        
                                        if should_flush and accumulated_content:
                                            # 格式化和输出累积的内容
                                            formatted_content = format_markdown_titles(accumulated_content)
                                            api_logger.debug(f"刷新0:格式内容到客户端，长度: {len(formatted_content)}")
                                            yield {
                                                "id": f"chatcmpl-{uuid.uuid4()}",
                                                "object": "chat.completion.chunk",
                                                "created": int(time.time()),
                                                "model": payload.get("model", "chat-model-reasoning"),
                                                "choices": [{
                                                    "index": 0,
                                                    "delta": {"content": formatted_content}
                                                }]
                                            }
                                            # 重置累积和更新刷新时间
                                            accumulated_content = ""
                                            last_flush_time = current_time
                                    
                                    # 处理思考内容格式
                                    elif line.startswith('g:') or (len(line) > 1 and line[0] == 'g' and line[1] == ':'):
                                        if unlimited_payload.get("thinking", False):
                                            # 提取内容
                                            content = line[2:].strip()
                                            # 去除引号
                                            if content.startswith('"') and content.endswith('"'):
                                                content = content[1:-1]
                                            
                                            # 处理可能的转义字符
                                            try:
                                                content = json.loads(f'"{content}"')
                                            except json.JSONDecodeError:
                                                # 如果JSON解析失败，回退到简单替换
                                                content = content.replace('\\n', '\n')
                                            
                                            # 累积思考内容
                                            accumulated_thinking += content + "\n"
                                            
                                            # 检查是否应该刷新缓冲区
                                            current_time = time.time()
                                            should_flush = len(accumulated_thinking) >= MAX_BUFFER_SIZE or (current_time - last_flush_time) >= FLUSH_INTERVAL
                                            
                                            if should_flush and accumulated_thinking:
                                                # 格式化和输出累积的思考内容
                                                formatted_thinking = format_markdown_titles(accumulated_thinking)
                                                api_logger.debug(f"刷新g:格式思考内容到客户端，长度: {len(formatted_thinking)}")
                                                yield {
                                                    "id": f"chatcmpl-{uuid.uuid4()}",
                                                    "object": "chat.completion.chunk",
                                                    "created": int(time.time()),
                                                    "model": payload.get("model", "chat-model-reasoning"),
                                                    "choices": [{
                                                        "index": 0,
                                                        "delta": {"thinking": formatted_thinking}
                                                    }]
                                                }
                                                # 重置累积和更新刷新时间
                                                accumulated_thinking = ""
                                                last_flush_time = current_time
                                
                                except UnicodeDecodeError:
                                    # 忽略解码错误
                                    continue
                        
                        # 流式请求完成（使用统一的日志状态控制）
                        if not _chat_stream_log_state["response_end_logged"]:
                            api_logger.info("===== 流式API响应结束 =====")
                            _chat_stream_log_state["response_end_logged"] = True
                        
                        # 检查是否接收到了任何内容
                        if not received_any_content:
                            logger.warning("流式响应没有接收到任何内容，可能是连接过早关闭")
                            
                            # 重置响应日志状态以便重试请求时重新记录日志
                            _chat_stream_log_state["response_logged"] = False
                            _chat_stream_log_state["response_end_logged"] = False
                            
                            # 尝试重新连接HTTP客户端
                            try:
                                logger.info("尝试重新连接HTTP客户端...")
                                reconnected = await self.reconnect()
                                if reconnected:
                                    logger.info("HTTP客户端重新连接成功")
                                else:
                                    logger.warning("HTTP客户端重新连接失败")
                            except Exception as e:
                                logger.error(f"重新连接HTTP客户端时出错: {str(e)}")
                            
                            # 如果尚未重试过，则尝试获取新Token并重试
                            if retry_count < max_retries:
                                logger.info("尝试获取新Token并重试请求")
                                token = token_manager.get_token(force_new=True, client_ip=client_ip)
                                if token:
                                    headers["x-api-token"] = token
                                    logger.info("获取到新Token，准备重试请求")
                                else:
                                    logger.error("无法获取新Token，放弃重试")
                                    yield {"error": "请求超时，无法获取新Token重试", "code": "TOKEN_TIMEOUT", "status": 504}
                                    return
                                # 继续到下一次重试
                                continue
                            else:
                                logger.error("流式响应为空，达到最大重试次数")
                                yield {"error": "请求超时，请稍后重试", "code": "REQUEST_TIMEOUT", "status": 504}
                                return
                        
                        # 将完整响应内容移至DEBUG级别
                        api_logger.debug("完整流式响应内容:\n" + full_response_log)
                        
                        # 处理可能存在的未输出的内容
                        if accumulated_content:
                            # 格式化最后的累积内容
                            final_formatted_content = format_markdown_titles(accumulated_content)
                            
                            # 记录最后的累积内容
                            api_logger.debug(f"最后的累积内容格式化前\n---\n{accumulated_content}\n---")
                            api_logger.debug(f"最后的累积内容格式化后\n---\n{final_formatted_content}\n---")
                            
                            # 输出最后的格式化内容
                            if final_formatted_content.strip():
                                api_logger.debug(f"输出最终累积内容到客户端，长度: {len(final_formatted_content)}")
                                yield {
                                    "id": f"chatcmpl-{uuid.uuid4()}",
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": payload.get("model", "chat-model-reasoning"),
                                    "choices": [{
                                        "index": 0,
                                        "delta": {"content": final_formatted_content}
                                    }]
                                }
                        
                        # 处理最后的思考内容
                        if accumulated_thinking:
                            final_formatted_thinking = format_markdown_titles(accumulated_thinking)
                            if final_formatted_thinking.strip():
                                api_logger.debug(f"输出最终累积思考内容到客户端，长度: {len(final_formatted_thinking)}")
                                yield {
                                    "id": f"chatcmpl-{uuid.uuid4()}",
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": payload.get("model", "chat-model-reasoning"),
                                    "choices": [{
                                        "index": 0,
                                        "delta": {"thinking": final_formatted_thinking}
                                    }]
                                }
                        
                        # 发送完成标记
                        api_logger.debug("发送完成标记到客户端")
                        yield {
                            "id": f"chatcmpl-{uuid.uuid4()}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": payload.get("model", "chat-model-reasoning"),
                            "choices": [{
                                "index": 0,
                                "delta": {},
                                "finish_reason": "stop"
                            }]
                        }
                        
                        # 记录请求耗时
                        elapsed = time.time() - start_time
                        logger.info(f"流式请求处理完成，耗时: {elapsed:.2f}秒")
                        # 记录请求成功
                        RequestStats.log_request(success=True, token_retry=(retry_count > 0))
                        # 成功完成处理，跳出重试循环
                        break
                
                except httpx.TimeoutException:
                    if retry_count < max_retries:
                        logger.warning("请求超时，尝试重新获取Token并重试")
                        token = token_manager.get_token(force_new=True, client_ip=client_ip)
                        if token:
                            headers["x-api-token"] = token
                        else:
                            logger.error("无法获取新Token，放弃重试")
                            yield {"error": "请求超时，无法获取新Token重试", "code": "TOKEN_TIMEOUT", "status": 504}
                            return
                    else:
                        logger.error("请求超时，达到最大重试次数")
                        yield {"error": "请求超时，请稍后重试", "code": "REQUEST_TIMEOUT", "status": 504}
                        return
        
        except httpx.TimeoutException:
            logger.error("流式请求超时")
            yield {"error": "请求超时，请稍后重试", "code": "REQUEST_TIMEOUT", "status": 504}
            RequestStats.log_request(success=False)
        
        except Exception as e:
            logger.error(f"流式请求处理出错: {str(e)}")
            yield {"error": f"处理请求时出错: {str(e)}", "code": "REQUEST_ERROR", "status": 500}
            RequestStats.log_request(success=False)

# 创建全局ChatClient实例
chat_client = ChatClient() 