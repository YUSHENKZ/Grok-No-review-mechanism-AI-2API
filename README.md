# UnlimitedAI代理服务

<p align="center">
  <img src="https://github.com/yourusername/unlimited-ai-proxy/raw/main/docs/logo.png" alt="UnlimitedAI Logo" width="200" />
</p>

<p align="center">
  <b>代理服务 · 完全支持OpenAI API格式</b>
</p>


- **完全兼容**: 支持OpenAI标准API格式，可无缝替换现有应用

### 架构概览

```
/
├── main.py             # 应用入口点，处理命令行参数和启动服务
├── unlimited_proxy/    # 核心包
│   ├── __init__.py     # 包初始化
│   ├── server.py       # FastAPI服务器和路由
│   ├── config.py       # 配置管理
│   ├── chat.py         # 聊天补全核心逻辑
│   ├── token_manager.py# 令牌管理
│   ├── auth.py         # 认证相关
│   ├── api_key.py      # API密钥管理
│   ├── security.py     # 安全功能
│   ├── security_api.py # 安全管理API
│   └── utils.py        # 工具函数
├── static/             # 静态资源
├── logs/               # 日志目录
├── .KEY                # API密钥设置
└── .env                # 环境变量配置
```

### 数据流程

1. 客户端发送请求 → FastAPI服务器(server.py)
2. 请求通过安全中间件(security.py)过滤可疑请求和进行速率限制
3. 认证中间件(auth.py)验证API密钥
4. 请求被转发至相应处理器(chat.py等)
5. 处理器使用token_manager获取所需令牌
6. 处理完成后，响应通过FastAPI返回给客户端


## 快速开始

### 前置要求

- Python 3.8+
- 兼容Linux、macOS和Windows系统

### 安装与启动

```bash
# 克隆仓库
git clone https://github.com/yourusername/unlimited-ai-proxy.git
cd unlimited-ai-proxy

# 安装依赖
pip install -r requirements.txt

# 使用默认配置启动服务
python main.py
```

服务将在 http://127.0.0.1:8000 上启动

### 自定义启动

```bash
# 自定义监听地址和端口
python main.py --host 0.0.0.0 --port 8080

# 使用调试模式
python main.py --log-level debug

# 启用多进程模式
python main.py --workers 4
```

### 命令行选项

| 选项 | 说明 |
|------|------|
| `--host HOST` | 服务监听地址，默认为127.0.0.1 |
| `--port PORT` | 服务监听端口，默认为8000 |
| `--log-level LEVEL` | 日志级别(debug/info/warning/error/critical/all/none) |
| `--log-dir LOG_DIR` | 日志目录 |
| `--workers N` | 工作进程数量，默认为1 |
| `--reload` | 启用自动重载，用于开发环境 |
| `--debug` | 启用调试模式 (覆盖配置文件) |
| `--env-file ENV_FILE` | 环境变量配置文件路径 |
| `--version` | 显示版本信息 |
| `--help` | 显示帮助信息 |

## API使用

### 聊天补全API

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "chat-model-reasoning",
    "messages": [{"role": "user", "content": "你好，请介绍一下自己"}],
    "temperature": 1.0,
    "max_tokens": 2000,
    "stream": false
  }'
```


## 配置项

配置可通过环境变量、`.env`文件或命令行参数提供。主要配置项包括：

### API配置

```
# API基础配置
UNLIMITED_API_TIMEOUT=60
UNLIMITED_MAX_RETRIES=3
UNLIMITED_CONNECT_TIMEOUT=10

# 令牌管理
UNLIMITED_TOKEN_CACHE_ENABLED=true
UNLIMITED_TOKEN_CACHE_TTL=3600
```

### 服务器配置

```
# 服务器配置
UNLIMITED_SERVER_HOST=0.0.0.0
UNLIMITED_SERVER_PORT=8000
UNLIMITED_SERVER_WORKERS=4
UNLIMITED_SERVER_CORS_ORIGINS=*
UNLIMITED_SERVER_DOCS_ENABLED=false  # 禁用API文档页面，提高安全性

# 性能配置
UNLIMITED_HTTP2_ENABLED=true
UNLIMITED_CONNECTION_POOL_SIZE=100
```

### 日志配置

```
# 日志配置
UNLIMITED_LOG_LEVEL=INFO
UNLIMITED_LOG_DIR=logs
UNLIMITED_LOG_FORMAT=DETAILED
```

## 安全模块

随便搞了个安全模块，提供多层次防护：

### 主要安全特性

1. **IP封禁**: 自动识别和封禁发送可疑请求的IP地址
2. **请求频率限制**: 基于滑动窗口算法的精确请求限制
3. **可疑请求过滤**: 检测并拦截常见的扫描和攻击请求[有人扫站于是就搞了一个]
4. **API密钥验证**: 支持多API密钥管理和不同的限制策略
5. **管理API**: 专用的安全管理接口，支持实时监控和封禁管理

### 安全配置示例

```
# 基本安全配置
UNLIMITED_SECURITY_ENABLED=true
UNLIMITED_SECURITY_IP_BLOCKING=true
UNLIMITED_SECURITY_BLOCK_THRESHOLD=10
UNLIMITED_SECURITY_BLOCK_DURATION=3600

# IP白名单配置
UNLIMITED_SECURITY_IP_WHITELIST=127.0.0.1,192.168.1.1

# 频率限制配置
UNLIMITED_ENABLE_RATE_LIMIT=true
UNLIMITED_MAX_REQUEST_RATE=60
UNLIMITED_TIME_WINDOW=60
```

### 完整配置示例

详细配置示例可在项目根目录的`.env`文件中查看。

## 许可证

本项目采用MIT许可证 - 详情请查看[LICENSE](LICENSE)文件。

