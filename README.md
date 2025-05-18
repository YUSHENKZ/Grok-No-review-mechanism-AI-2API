## Grok-No-review-mechanism-AI-2API UnlimitedAI代理服务
<p align="center">
  <b>代理服务 · 完全支持OpenAI API格式</b>
</p>


- **特点**: 支持OpenAI标准API格式，可无缝替换现有应用

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
git clone [https://github.com/yourusername/unlimited-ai-proxy.git](https://github.com/YUSHENKZ/Grok-No-review-mechanism-AI-2API.git)

cd Grok-No-review-mechanism-AI-2API-main

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

配置可通过环境变量、`.env`文件或命令行参数提供：

```
# 环境配置

# ==================== 服务配置 ====================
# 服务器主机地址，可以是IP地址或域名
# 默认值: 127.0.0.1 (本地)，设置为0.0.0.0可接受所有外部连接
UNLIMITED_SERVER_HOST=127.0.0.1

# 服务器端口，范围1024-65535，常用值3000/8000/8080等
UNLIMITED_SERVER_PORT=8000

# 工作进程数量，注意：当前系统设计不完全支持多进程
# 多进程模式下Token管理和SQLite可能出现问题，保持1除非您修改了存储机制
# 如需开启多进程，建议将TOKEN_STORAGE_TYPE设为redis，并修改SQLite连接方式
UNLIMITED_SERVER_WORKERS=1

# 是否启用自动重载，开发环境设为true，生产环境设为false
UNLIMITED_SERVER_RELOAD=false

# 是否启用API文档页面，true启用，false禁用
UNLIMITED_SERVER_DOCS_ENABLED=false

# 请求超时时间(秒)，建议设置较大值，避免长时间对话被中断
UNLIMITED_SERVER_REQUEST_TIMEOUT=300

# 允许的跨域源，*表示允许所有，也可以指定具体域名，多个用逗号分隔
UNLIMITED_SERVER_CORS_ORIGINS=*

# ==================== 并发与连接管理 ====================
# --- 服务器连接设置 ---
# 并发连接数上限，设置为0表示不限制，推荐根据服务器性能设置50-500
UNLIMITED_SERVER_LIMIT_CONCURRENCY=100

# 保持空闲连接的最长时间(秒)，设置过小可能导致频繁断开连接，推荐60-300
UNLIMITED_SERVER_TIMEOUT_KEEP_ALIVE=120

# 优雅关闭服务的等待时间(秒)，服务将等待该时间后强制关闭，推荐5-30
UNLIMITED_SERVER_TIMEOUT_GRACEFUL_SHUTDOWN=6

# TCP连接队列大小，表示等待处理的连接队列长度，推荐100-500
UNLIMITED_SERVER_BACKLOG=128

# --- API客户端连接设置（可选，留空则自动计算） ---
# 以下设置为高级选项，通常不需要手动设置
# 系统会根据服务器连接设置自动计算合适的值：
# - 连接池大小：默认为UNLIMITED_SERVER_LIMIT_CONCURRENCY的1.2倍
# - 活跃连接数：默认为连接池大小的20%
# - 连接保持时间：默认为UNLIMITED_SERVER_TIMEOUT_KEEP_ALIVE的1/3
# 仅当需要特别调优时才设置这些值

# API客户端连接池大小 - 可选，不设置则自动计算
# UNLIMITED_PERFORMANCE_CONNECTION_POOL_SIZE=100

# API客户端保持活跃的连接数 - 可选，不设置则自动计算
# UNLIMITED_PERFORMANCE_KEEP_ALIVE_CONNECTIONS=20

# API连接保持时间(秒) - 可选，不设置则自动计算
# UNLIMITED_PERFORMANCE_KEEPALIVE_EXPIRY=30.0

# ==================== 接口端点配置 ====================
# --- 超时和重试设置 ---
# 请求超时时间(秒)
UNLIMITED_API_TIMEOUT=60.0

# 连接超时时间(秒)
UNLIMITED_API_CONNECT_TIMEOUT=10.0

# 读取超时时间(秒)
UNLIMITED_API_READ_TIMEOUT=120.0

# 写入超时时间(秒)
UNLIMITED_API_WRITE_TIMEOUT=20.0

# 连接池超时时间(秒)
UNLIMITED_API_POOL_TIMEOUT=10.0

# 请求失败时的最大重试次数，推荐3-10
UNLIMITED_API_MAX_RETRIES=5

# Token获取失败时的最大重试次数
UNLIMITED_API_MAX_TOKEN_RETRIES=3

# 首次重试的延迟时间(毫秒)，建议50-200
UNLIMITED_API_INITIAL_RETRY_DELAY_MS=100

# 重试的最大延迟时间(毫秒)，避免无限增长，建议2000-10000
UNLIMITED_API_MAX_RETRY_DELAY_MS=5000

# 空响应超时时间(秒)，等待多久后认为是空响应
UNLIMITED_API_EMPTY_RESPONSE_TIMEOUT=5.0

# ==================== 令牌管理配置 ====================
# 是否使用内存缓存令牌
UNLIMITED_TOKEN_MEMORY_CACHE=true

# 是否启用令牌缓存
UNLIMITED_TOKEN_CACHE_ENABLED=true

# 令牌缓存有效期(秒)
UNLIMITED_TOKEN_CACHE_TTL=3600

# 令牌存储类型，可选值：file(文件存储)、sqlite(SQLite数据库)、redis(Redis数据库)
# 注意：在多工作进程模式下，建议使用redis存储类型
UNLIMITED_TOKEN_STORAGE_TYPE=sqlite

# 令牌数据库路径(SQLite模式下使用)
UNLIMITED_TOKEN_DB_PATH=tokens.db

# 令牌存储目录(文件模式下使用)
UNLIMITED_TOKEN_STORAGE_PATH=.unlimited

# Redis连接URL(Redis模式下使用)，格式为redis://username:password@host:port/db
UNLIMITED_TOKEN_REDIS_URL=redis://localhost:6379/0

# 是否启用令牌轮换
UNLIMITED_TOKEN_ROTATION_ENABLED=true

# 令牌缓存大小
UNLIMITED_TOKEN_CACHE_SIZE=5

# 是否自动刷新令牌
UNLIMITED_TOKEN_AUTO_REFRESH=true

# ==================== 代理配置 ====================
# 是否启用代理
UNLIMITED_PROXY_ENABLED=false

# HTTP代理地址，启用代理后使用
# UNLIMITED_PROXY_HTTP=http://127.0.0.1:7890

# HTTPS代理地址，启用代理后使用
# UNLIMITED_PROXY_HTTPS=http://127.0.0.1:7890

# ==================== 日志配置 ====================
# 日志级别: 
# - DEBUG: 最详细级别，显示所有API请求和响应的详细内容、Token处理、格式化过程等，适用于开发调试
# - INFO: 显示基本操作信息和API请求概要，不包含详细的请求/响应内容，适用于常规监控
# - WARNING: 只显示警告和错误信息，适用于生产环境
# - ERROR: 只显示错误信息
# - CRITICAL: 只显示严重错误信息
# 也可以设置多个级别组合，用逗号分隔，如"DEBUG,INFO,ERROR"表示只显示这三种级别的日志
# 或使用"ALL"显示所有级别日志，"NONE"关闭日志
UNLIMITED_LOGGING_LEVEL=INFO,WARNING

# 日志目录
UNLIMITED_LOGGING_DIR=logs

# 日志格式，可选值：SIMPLE(简单格式)、DETAILED(详细格式，包含文件名和行号)、SOPHNET(时间戳-[文件名:行号]-级别-消息)
UNLIMITED_LOGGING_FORMAT=SOPHNET

# 日志输出目标，可选值：CONSOLE(控制台)、FILE(文件)、BOTH(同时输出到控制台和文件)
UNLIMITED_LOGGING_OUTPUT=BOTH

# 是否隐藏HTTP请求日志，可选值：TRUE(隐藏)、FALSE(显示)
UNLIMITED_LOGGING_HIDE_HTTP=TRUE

# 日志文件最大大小(字节)，默认10MB
UNLIMITED_LOGGING_FILE_MAX_SIZE=10485760

# 日志文件备份数量
UNLIMITED_LOGGING_FILE_BACKUP_COUNT=3

# ==================== API访问控制 ====================
# --- API密钥保护 ---
# 是否启用API密钥保护，TRUE(启用)表示API请求必须提供有效密钥，FALSE(禁用)表示允许无密钥访问
UNLIMITED_API_KEY_PROTECTION=TRUE

# API密钥配置文件路径
UNLIMITED_API_KEY_FILE=.key

# --- 请求速率限制 ---
# 是否启用请求速率限制，TRUE启用，FALSE禁用
UNLIMITED_RATE_LIMIT_ENABLED=TRUE

# IP级别限制：每个时间窗口内允许的最大请求数
UNLIMITED_RATE_LIMIT_IP=50

# 时间窗口大小（秒）
UNLIMITED_RATE_LIMIT_WINDOW=60

# --- API密钥限速 ---
# 是否对API密钥应用限速，设为TRUE则根据密钥单独限速
UNLIMITED_RATE_LIMIT_BY_KEY=TRUE

# API密钥默认限速（每个时间窗口内允许的最大请求数）
# 当UNLIMITED_RATE_LIMIT_BY_KEY=TRUE时生效
UNLIMITED_RATE_LIMIT_KEY_DEFAULT=30
```


## 安全模块

随便搞了个安全模块：

### 主要安全特性

1. **请求频率限制**: 基于滑动窗口算法的精确请求限制，IP级和密钥级
2. **API密钥验证**: 支持多API密钥管理和不同的限制策略

## KEY配置项

配置可通过`.key`文件提供：
```
# API密钥配置文件
# 格式: API_KEY_序号=密钥值=过期时间[=限速设置[:限速值]]
# 过期时间: permanent(永久有效) 或 YYYY-MM-DD
# 限速设置: 
#  - rate_limit: 启用限速，可以带上冒号和数字指定限速值，如 rate_limit:50
#  - no_limit: 禁用限速
#  - 不填则使用全局设置

# 生产环境请替换为安全的密钥
API_KEY_1=sk-unlimited-dev-key=permanent=no_limit
API_KEY_2=sk-unlimited-test-key=2025-12-31=no_limit
API_KEY_3=sk-unlimited-high-freq-key=permanent=rate_limit:3
API_KEY_4=sk-unlimited-normal-key=permanent=rate_limit
# API_KEY_5=sk-unlimited-demo-key=2023-12-31=rate_limit:10
```


## 许可证

本项目采用MIT许可证 - 详情请查看[LICENSE](LICENSE)文件。

