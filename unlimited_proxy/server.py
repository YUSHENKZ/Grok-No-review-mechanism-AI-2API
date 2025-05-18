"""
FastAPI服务器模块

实现API路由和请求处理，支持OpenAI API格式的调用。
"""

import json
import logging
import asyncio
import time
from typing import Dict, Any, Optional, List, Awaitable
from fastapi import FastAPI, Request, Response, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from pathlib import Path
import traceback

from . import __version__
from .config import config
from .chat import chat_client, RequestStats
from .token_manager import token_manager
from .utils import ChatFormatter, RequestUtils
from .auth import get_api_key_dependency, verify_api_key
from .security import is_rate_limited, get_security_stats, load_security_config
# 导入安全管理API路由器
from .security_api import security_router

# 配置日志
logger = logging.getLogger("unlimited_proxy.server")

# 检查是否启用API文档
docs_enabled = config.get("server.docs_enabled", True)
docs_url = "/docs" if docs_enabled else None
redoc_url = "/redoc" if docs_enabled else None

app = FastAPI(
    title="UnlimitedAI Proxy API",
    description="高性能UnlimitedAI代理服务，支持OpenAI API格式的调用",
    version=__version__,
    docs_url=docs_url,
    redoc_url=redoc_url,
)

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.get("server.cors_origins", ["*"]),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 安全中间件
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """安全中间件，检查API请求速率限制"""
    # 获取客户端IP
    client_ip = request.client.host
    path = request.url.path
    method = request.method
    
    # 提取API密钥（如果有）
    api_key = None
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        api_key = auth_header[7:]
    
    # 检查是否超过速率限制
    is_limited, limit_message = is_rate_limited(client_ip, api_key)
    if is_limited:
        logger.warning(f"请求因速率限制被拒绝: [IP:{client_ip}] [方法:{method}] [路径:{path}]")
        return JSONResponse(
            status_code=429,
            content={"error": limit_message or "请求过于频繁，请稍后再试", "code": "TOO_MANY_REQUESTS"}
        )
    
    # 继续处理正常请求
    response = await call_next(request)
    return response

# 文档访问中间件
@app.middleware("http")
async def docs_access_middleware(request: Request, call_next):
    """文档访问中间件，当文档被禁用时阻止访问文档页面"""
    path = request.url.path
    docs_paths = ["/docs", "/docs/", "/redoc", "/redoc/", "/openapi.json"]
    
    # 检查是否访问文档页面且文档已禁用
    if path in docs_paths and not config.get("server.docs_enabled", True):
        logger.warning(f"尝试访问已禁用的文档页面: {path}")
        return JSONResponse(
            status_code=404,
            content={"error": "页面不存在", "code": "NOT_FOUND"}
        )
    
    # 继续处理正常请求
    response = await call_next(request)
    return response

# 挂载静态文件
static_dir = Path("static")
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
else:
    logger.warning("静态文件目录 'static' 不存在，跳过挂载")

# 获取API密钥验证依赖项
api_key_dependency = get_api_key_dependency()

# 启动时检查API密钥保护配置
api_key_protection = config.get("api.key_protection", False)
if api_key_protection:
    logger.info(f"API密钥保护已启用，API请求将需要有效的密钥")
else:
    logger.warning(f"API密钥保护已禁用，所有API端点将公开访问")

# 启动时检查速率限制配置
rate_limit_config = config.get_rate_limit_config()
rate_limit_enabled = config.get("api.enable_rate_limit", True)
# 注释掉模块级别的日志，避免与startup_event中的日志重复
# if rate_limit_enabled:
#     logger.info(f"请求速率限制已启用 [最大速率:{rate_limit_config['max_rate']}请求/{rate_limit_config['time_window']}秒]")
# else:
#     logger.warning(f"请求速率限制已禁用，可能导致API被滥用")

# 启动时加载安全配置
load_security_config()

# 挂载安全管理API路由器
app.include_router(security_router)

async def validate_request(request: Request) -> Dict[str, Any]:
    """
    验证并解析请求数据
    
    Args:
        request: FastAPI请求对象
        
    Returns:
        解析后的请求数据
    """
    content_type = request.headers.get("content-type", "")
    
    if "application/json" not in content_type:
        raise HTTPException(status_code=400, detail="Content-Type must be application/json")
    
    try:
        payload = await request.json()
        return payload
    except Exception as e:
        logger.error(f"解析请求数据时出错: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")

@app.get("/")
async def root():
    """API根路径，返回基本信息"""
    return {
        "name": "UnlimitedAI Proxy API@YSKZ",
        "version": __version__,
        "status": "ok"
    }

@app.get("/v1")
async def api_info():
    """API信息路径，返回版本信息"""
    return {
        "version": __version__,
        "status": "ok"
    }

@app.get("/stats")
async def get_stats():
    """获取API使用统计信息"""
    stats = RequestStats.get_stats()
    token_state = "有效" if token_manager.get_token() else "无效"
    
    return {
        "status": "ok",
        "timestamp": int(time.time()),
        "token_state": token_state,
        "request_stats": stats
    }

@app.get("/health")
async def health_check():
    """健康检查端点"""
    # 获取当前状态
    token_status = "ok" if token_manager.get_token() else "error"
    
    return {
        "status": "ok" if token_status == "ok" else "error",
        "version": __version__,
        "components": {
            "token_manager": token_status
        }
    }

@app.get("/admin/security/stats")
async def security_status(request: Request):
    """查看安全统计信息的管理员接口
    
    Args:
        request: FastAPI请求对象
        
    Returns:
        安全统计信息
    """
    # 获取客户端IP
    client_ip = request.client.host if request.client else "unknown"
    
    # 获取安全统计信息
    stats = get_security_stats()
    
    # 记录管理API访问日志
    logger.info(f"管理API访问成功: [IP:{client_ip}] [端点:security_stats]")
    
    return {
        "status": "ok",
        "timestamp": int(time.time()),
        "security": stats
    }

@app.post("/v1/chat/completions", dependencies=[api_key_dependency] if api_key_protection else [])
async def chat_completions(request: Request, background_tasks: BackgroundTasks):
    """
    聊天补全API，兼容OpenAI API
    
    Args:
        request: FastAPI请求对象
        background_tasks: 后台任务管理器
        
    Returns:
        JSON响应或流式响应
    """
    # 解析请求
    try:
        payload = await validate_request(request)
    except HTTPException as e:
        logger.error(f"请求验证失败: {e.detail}")
        return JSONResponse(
            status_code=e.status_code,
            content={"error": e.detail}
        )
    except Exception as e:
        logger.error(f"请求处理出错: {str(e)}")
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid request: {str(e)}"}
        )
    
    # 获取调试状态
    debug_mode = payload.pop("debug", False)
    
    # 获取流式状态
    stream_mode = payload.get("stream", False)
    
    # 获取客户端IP地址
    client_ip = request.client.host if request.client else None
    logger.debug(f"处理来自 {client_ip} 的请求")
    
    if debug_mode:
        logger.debug(f"接收到聊天请求: {json.dumps(payload, ensure_ascii=False)}")
    
    # 处理请求
    if stream_mode:
        # 流式请求处理
        async def generate():
            try:
                response_id = None
                
                async for chunk in chat_client.handle_chat_stream(payload, debug=debug_mode, client_ip=client_ip):
                    if "error" in chunk:
                        # 错误处理
                        error_json = json.dumps({"error": chunk["error"]})
                        yield f"data: {error_json}\n\n"
                        break
                    
                    # 保存一致的响应ID
                    if "id" in chunk and not response_id:
                        response_id = chunk["id"]
                    elif "id" not in chunk and response_id:
                        chunk["id"] = response_id
                    
                    # 仅处理思考内容和delta内容
                    if "thinking" in chunk:
                        # 思考内容单独发送
                        thinking_json = json.dumps({"thinking": chunk["thinking"]})
                        yield f"data: {thinking_json}\n\n"
                    elif "choices" in chunk and chunk["choices"] and "delta" in chunk["choices"][0]:
                        # 常规的delta内容
                        try:
                            # 移除可能导致问题的换行符
                            if "content" in chunk["choices"][0]["delta"]:
                                content = chunk["choices"][0]["delta"]["content"]
                                if "\n\n" in content:
                                    chunk["choices"][0]["delta"]["content"] = content.replace("\n\n", "\n")
                                
                                # 内容处理后重新获取
                                content = chunk["choices"][0]["delta"]["content"]
                                
                                # 字符级别的流式输出，每个字符之间有固定延迟
                                # 保存原始chunk属性
                                chunk_id = chunk.get("id", "")
                                chunk_created = chunk.get("created", int(time.time()))
                                chunk_model = chunk.get("model", "chat-model-reasoning")
                                
                                # 对所有内容都进行字符级拆分
                                chars = list(content)
                                
                                # 逐个发送字符，模拟真人打字效果
                                for char in chars:
                                    small_chunk = {
                                        "id": chunk_id,
                                        "object": "chat.completion.chunk",
                                        "created": chunk_created,
                                        "model": chunk_model,
                                        "choices": [{
                                            "index": 0,
                                            "delta": {"content": char}
                                        }]
                                    }
                                    small_chunk_json = json.dumps(small_chunk)
                                    yield f"data: {small_chunk_json}\n\n"
                                
                                # 固定的字符间延迟
                                await asyncio.sleep(0.16)  
                            else:
                                # 非内容delta直接发送（如角色信息或结束标记）
                                chunk_json = json.dumps(chunk)
                                yield f"data: {chunk_json}\n\n"
                        except Exception as e:
                            logger.error(f"序列化响应块失败: {e}")
                            # 尝试移除可能导致问题的内容
                            if "content" in chunk["choices"][0]["delta"]:
                                content = chunk["choices"][0]["delta"]["content"]
                                chunk["choices"][0]["delta"]["content"] = content[:100]  # 截断长内容
                                try:
                                    chunk_json = json.dumps(chunk)
                                    yield f"data: {chunk_json}\n\n"
                                except:
                                    # 如果仍失败，发送错误
                                    error_json = json.dumps({"error": "序列化响应失败"})
                                    yield f"data: {error_json}\n\n"
                
                # 流式结束
                yield "data: [DONE]\n\n"
            except Exception as e:
                logger.error(f"流式响应生成出错: {str(e)}", exc_info=True)
                error_json = json.dumps({"error": str(e)})
                yield f"data: {error_json}\n\n"
                yield "data: [DONE]\n\n"
        
        # 返回流式响应
        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Content-Type": "text/event-stream",
                "X-Accel-Buffering": "no"
            }
        )
    else:
        # 非流式请求处理
        try:
            result = await chat_client.handle_chat_request(payload, debug=debug_mode, client_ip=client_ip)
            
            if "error" in result:
                if "status" in result:
                    status_code = result.pop("status")
                else:
                    status_code = 500
                
                error_response = {"error": result["error"]}
                
                # 如果有原始响应预览，添加到错误信息中
                if "raw_response_preview" in result:
                    error_response["raw_response"] = result["raw_response_preview"]
                
                return JSONResponse(
                    status_code=status_code,
                    content=error_response
                )
            
            # 处理文本中可能存在的多余换行符
            if "choices" in result and result["choices"] and "message" in result["choices"][0]:
                if "content" in result["choices"][0]["message"]:
                    content = result["choices"][0]["message"]["content"]
                    if "\n\n" in content:
                        result["choices"][0]["message"]["content"] = content.replace("\n\n", "\n")
            
            # 处理思考内容中的多余换行符
            if "thinking" in result:
                thinking = result["thinking"]
                if "\n\n" in thinking:
                    result["thinking"] = thinking.replace("\n\n", "\n")
            
            return JSONResponse(content=result)
        except Exception as e:
            logger.error(f"处理聊天请求时出错: {str(e)}", exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"error": f"Server error: {str(e)}"}
            )

@app.get("/v1/models", dependencies=[api_key_dependency] if api_key_protection else [])
async def list_models():
    """
    列出可用模型
    """
    # 获取配置中的可用模型列表
    available_models = config.get_available_models()
    
    # 转换为OpenAI格式的模型列表
    models = []
    for model_config in available_models:
        model_id = model_config["id"]
        model_desc = model_config.get("description", "UnlimitedAI模型")
        
        models.append({
            "id": model_id,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "unlimited-ai",
            "permission": [],
            "root": model_id,
            "parent": None,
            "description": model_desc
        })
    
    return {
        "object": "list",
        "data": models
    }

@app.get("/test")
async def test_client():
    """测试客户端页面 - 重定向"""
    return RedirectResponse(url="/static/client.html")

@app.get("/docs/thinking")
async def thinking_docs():
    """思考模式文档"""
    html_content = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>思考模式文档 - UnlimitedAI Proxy API</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
        }
        
        h1, h2, h3 {
            color: #2c3e50;
        }
        
        h1 {
            border-bottom: 1px solid #eee;
            padding-bottom: 10px;
        }
        
        pre {
            background: #f5f5f5;
            padding: 15px;
            border-radius: 4px;
            overflow-x: auto;
        }
        
        code {
            font-family: Consolas, Monaco, 'Andale Mono', monospace;
            background: #f8f9fa;
            padding: 2px 4px;
            border-radius: 3px;
        }
        
        .info-box {
            background: #e7f4ff;
            border-left: 4px solid #0275d8;
            padding: 15px;
            margin: 20px 0;
            border-radius: 4px;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }
        
        th, td {
            border: 1px solid #ddd;
            padding: 10px;
            text-align: left;
        }
        
        th {
            background: #f8f9fa;
        }
    </style>
</head>
<body>
    <h1>思考模式文档</h1>
    
    <div class="info-box">
        此文档介绍如何在UnlimitedAI Proxy API中使用思考模式功能。
    </div>
    
    <h2>什么是思考模式？</h2>
    <p>
        思考模式是一个允许AI模型在生成最终回答之前，先展示其思考过程的功能。
        这对于以下场景特别有用：
    </p>
    <ul>
        <li>需要跟踪AI的推理过程</li>
        <li>验证AI的知识和逻辑</li>
        <li>教育目的，展示问题解决的步骤</li>
        <li>增强用户对AI决策的信任</li>
    </ul>
    
    <h2>如何启用思考模式</h2>
    <p>
        要启用思考模式，只需在请求中添加相关参数即可。有两种方式：
    </p>
    
    <h3>方法一：基本使用</h3>
    <p>
        在API请求中添加<code>thinking: true</code>参数：
    </p>
    
    <pre><code>{
  "model": "chat-model-reasoning",
  "messages": [
    {"role": "user", "content": "请给我解释一下电子计算机是如何工作的?"}
  ],
  "thinking": true
}</code></pre>
    
    <h3>方法二：高级配置</h3>
    <p>
        可以设置思考模式的令牌预算，控制思考过程的长度：
    </p>
    
    <pre><code>{
  "model": "chat-model-reasoning",
  "messages": [
    {"role": "user", "content": "请分析这段代码的复杂度并提出优化建议：for(int i=0; i<n; i++) { for(int j=0; j<n; j++) { sum += i*j; } }"}
  ],
  "thinking": true,
  "budget_tokens": 5000
}</code></pre>
    
    <h2>API响应格式</h2>
    
    <h3>流式响应</h3>
    <p>
        当使用<code>stream: true</code>时，思考内容会通过特殊的事件流式传输：
    </p>
    
    <pre><code>data: {"thinking": "首先，我需要理解这段代码..."}
data: {"thinking": "这是一个嵌套循环结构，分析其时间复杂度..."}
data: {"id": "chatcmpl-123", "object": "chat.completion.chunk", "choices": [{"delta": {"role": "assistant"}}]}
data: {"id": "chatcmpl-124", "object": "chat.completion.chunk", "choices": [{"delta": {"content": "这段代码的时间复杂度是"}}]}
data: {"id": "chatcmpl-125", "object": "chat.completion.chunk", "choices": [{"delta": {"content": " O(n²)"}}]}
data: [DONE]</code></pre>
    
    <h3>非流式响应</h3>
    <p>
        对于<code>stream: false</code>的请求，思考内容会包含在最终响应中：
    </p>
    
    <pre><code>{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1698604094,
  "model": "chat-model-reasoning",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "这段代码的时间复杂度是 O(n²)，因为它有两个嵌套循环，每个循环都执行n次迭代..."
      },
      "finish_reason": "stop"
    }
  ],
  "thinking": "首先，我需要理解这段代码...\n这是一个嵌套循环结构，分析其时间复杂度...\n两个循环分别迭代n次，所以总的操作次数是n*n=n²..."
}</code></pre>
    
    <h2>最佳实践</h2>
    <ul>
        <li>对于需要复杂推理的问题，建议设置较高的<code>budget_tokens</code></li>
        <li>思考模式与流式响应结合使用效果最佳</li>
        <li>在UI中，可以将思考内容显示为不同样式，如斜体或不同颜色</li>
        <li>可以在系统提示中强化"深度思考"的指令，以获得更详细的思考过程</li>
    </ul>
    
    <h2>示例应用</h2>
    <p>
        我们提供了一个简单的测试客户端，集成了思考模式功能：<a href="/test">/test</a>
    </p>
    
    <h2>常见问题</h2>
    <table>
        <tr>
            <th>问题</th>
            <th>解决方案</th>
        </tr>
        <tr>
            <td>思考内容没有显示</td>
            <td>确保<code>thinking: true</code>已设置，并检查客户端是否正确处理思考相关的事件</td>
        </tr>
        <tr>
            <td>思考内容过短</td>
            <td>尝试增加<code>budget_tokens</code>值，或在系统提示中明确要求详细思考</td>
        </tr>
        <tr>
            <td>流式响应格式问题</td>
            <td>确保客户端能够处理混合的思考内容和正常内容事件</td>
        </tr>
    </table>
    
    <div class="info-box">
        <p><strong>注意：</strong> 思考模式可能会增加API响应时间和token消耗。</p>
    </div>
</body>
</html>
"""
    return HTMLResponse(content=html_content)

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP异常处理"""
    error_type = "api_error"
    error_code = None
    
    # 根据状态码确定错误类型
    if exc.status_code == 401:
        error_type = "authentication_error"
        if "API密钥" in exc.detail or "api key" in exc.detail.lower():
            error_code = "invalid_api_key"
    elif exc.status_code == 403:
        error_type = "permission_error"
    elif exc.status_code == 404:
        error_type = "not_found_error"
    elif exc.status_code == 429:
        error_type = "rate_limit_error"
    elif exc.status_code >= 500:
        error_type = "server_error"
    elif exc.status_code == 400:
        error_type = "invalid_request_error"
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "message": exc.detail,
                "type": error_type,
                "param": None,
                "code": error_code
            }
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """一般异常处理"""
    logger.error(f"未处理的异常: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "message": f"内部服务器错误: {str(exc)}",
                "type": "server_error",
                "param": None,
                "code": "internal_server_error"
            }
        }
    )

@app.on_event("startup")
async def startup_event():
    """应用启动时执行的操作"""
    logger.info("服务启动中...")

    # 初始化HTTP客户端
    await chat_client.reconnect()
    
    # 初始化配置
    try:
        from .security import load_security_config, get_security_stats
        # 加载安全配置（只保留安全配置加载，移除重复的日志输出）
        load_security_config(force_refresh=True)
        
        # 记录API文档状态 - 保留这个独特的信息
        docs_status = "已启用" if config.get("server.docs_enabled", True) else "已禁用"
        logger.info(f"[SERVER] API文档页面: {docs_status}")
    except Exception as e:
        logger.error(f"加载配置时出错: {str(e)}", exc_info=True)
    
    # 主动初始化和验证Token，确保有可用Token
    logger.info("[SERVER] 开始初始化Token管理器...")
    token_initialized = False
    try:
        token_initialized = await token_manager.initialize()
    except Exception as e:
        logger.error(f"[SERVER] Token初始化出错: {str(e)}", exc_info=True)
    
    if token_initialized:
        logger.info("[SERVER] Token初始化成功，有效Token已准备就绪")
    else:
        logger.warning("[SERVER] Token初始化失败，服务可能在首次请求时需要获取Token")
    
    # 获取并输出服务令牌状态
    logger.info("[SERVER] 获取服务令牌状态...")  
    token_ok = token_manager.get_token() is not None
    if token_ok:
        logger.info("[SERVER] 服务令牌有效")
    else:
        logger.warning("[SERVER] 警告: 服务令牌无效或不存在")
    
    # 初始化速率限制器 - 只记录初始化动作，不再重复输出配置
    try:
        from .auth import _get_rate_limiter
        _get_rate_limiter()  # 只初始化限速器，但不重复输出配置信息
    except Exception as e:
        logger.error(f"[SERVER] 警告: 速率限制器初始化失败: {str(e)}")

@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时执行的操作"""
    logger.info("服务正在关闭")
    
    # 关闭HTTP客户端
    await chat_client.close()

def create_app() -> FastAPI:
    """
    创建FastAPI应用
    
    Returns:
        FastAPI应用实例
    """
    return app

def run_server():
    """启动服务器"""
    host = config.get("server.host", "0.0.0.0")
    port = config.get("server.port", 8000)
    
    uvicorn.run(
        "unlimited_proxy.server:app",
        host=host,
        port=port,
        reload=config.get("server.reload", False),
        workers=config.get("server.workers", 1),
        log_level=config.get("server.log_level", "info").lower()
    ) 