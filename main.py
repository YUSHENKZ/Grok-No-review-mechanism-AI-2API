#!/usr/bin/env python3
"""
UnlimitedAI代理服务主程序

提供命令行接口，处理配置参数，并启动API服务。
"""

import os
import sys
import argparse
import logging
import logging.handlers
import logging.config
import uvicorn
import time
import multiprocessing

# 初始化基本日志配置，确保早期的日志警告能够显示
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

from unlimited_proxy import __version__
from unlimited_proxy.config import config, BASE_DIR
from unlimited_proxy.server import app

def parse_log_level(log_level_str):
    """解析日志级别字符串，支持单个级别或多个级别（逗号分隔）
    
    Args:
        log_level_str: 日志级别字符串，如"INFO"或"INFO,WARNING"
        
    Returns:
        解析后的日志级别（logging模块常量）
    """
    # 处理特殊值
    if log_level_str.upper() == "ALL":
        return logging.DEBUG  # 显示所有级别
    if log_level_str.upper() == "NONE":
        return logging.CRITICAL + 10  # 不显示任何日志
    
    # 分割逗号分隔的多个级别
    if "," in log_level_str:
        # 对于多个级别，使用最低的级别（允许显示更多日志）
        levels = log_level_str.split(",")
        min_level = logging.CRITICAL + 10  # 初始值设置为比CRITICAL还高
        
        for level in levels:
            level = level.strip().upper()
            try:
                level_value = getattr(logging, level)
                min_level = min(min_level, level_value)
            except AttributeError:
                logging.warning(f"无效的日志级别: {level}，将被忽略")
        
        if min_level == logging.CRITICAL + 10:
            # 如果所有级别都无效，使用默认级别
            logging.warning(f"所有指定的日志级别都无效: {log_level_str}，使用默认级别INFO")
            return logging.INFO
        
        return min_level
    else:
        # 单个级别的情况
        try:
            return getattr(logging, log_level_str.upper())
        except AttributeError:
            logging.warning(f"无效的日志级别: {log_level_str}，使用默认级别INFO")
            return logging.INFO

def setup_logging(log_level=None):
    """设置日志系统"""
    # 确保日志目录存在
    log_dir = os.path.join(BASE_DIR, config.get("logging.dir", "logs"))
    os.makedirs(log_dir, exist_ok=True)
    
    # 获取当前时间作为日志文件名的一部分
    current_time = time.strftime("%Y%m%d_%H%M%S")
    
    # 获取配置的日志级别
    if log_level is None:
        log_level_str = config.get("logging.level", "INFO")
        log_level = parse_log_level(log_level_str)
    
    # 获取日志配置
    log_config = config.get_log_config()
    
    # 更新文件名中的时间戳
    log_config["handlers"]["file"]["filename"] = os.path.join(log_dir, f"unlimited_proxy_{current_time}.log")
    api_log_file = os.path.join(log_dir, f"api_debug_{current_time}.log")
    
    # 清理现有日志配置，防止重复日志
    # 移除根日志记录器的所有处理器
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # 清理可能已配置的unlimited_proxy日志记录器
    unlimited_logger = logging.getLogger("unlimited_proxy")
    for handler in unlimited_logger.handlers[:]:
        unlimited_logger.removeHandler(handler)
    
    # 应用日志配置
    logging.config.dictConfig(log_config)
    logging.info(f"日志系统初始化完成，级别: {logging.getLevelName(log_level)}, 日志目录: {log_dir}")
    
    # 配置API调试日志
    api_logger = logging.getLogger("unlimited_proxy.api_debug")
    
    # 清除API日志记录器的现有处理器
    for handler in api_logger.handlers[:]:
        api_logger.removeHandler(handler)
    
    # 禁止日志传播到父记录器，防止日志重复
    api_logger.propagate = False
    
    # 根据配置的日志级别来设置API调试日志的级别
    # DEBUG：显示所有API请求和响应的详细信息，适用于开发调试
    # INFO：只显示主要的API请求和响应概要，适用于基本监控
    # WARNING及以上：只显示错误或异常信息，适用于生产环境
    if log_level <= logging.DEBUG:
        api_logger.setLevel(logging.DEBUG)
    elif log_level <= logging.INFO:
        api_logger.setLevel(logging.INFO)
    else:
        api_logger.setLevel(logging.WARNING)
    
    # 设置文件处理器，添加编码参数确保正确处理中文和特殊字符
    file_handler = logging.FileHandler(api_log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    
    # 根据配置选择格式化器
    log_format = config.get("logging.format", "DETAILED").upper()
    if log_format == "SIMPLE":
        formatter = logging.Formatter('%(levelname)s: %(message)s')
    elif log_format == "DETAILED":
        formatter = logging.Formatter('%(asctime)s - [API DEBUG] %(filename)s:%(lineno)d - %(message)s')
    elif log_format == "SOPHNET":
        formatter = logging.Formatter('%(asctime)s - [%(filename)s:%(lineno)d] - %(levelname)s - %(message)s', datefmt="%Y-%m-%d %H:%M:%S")
    else:
        formatter = logging.Formatter('%(asctime)s - [API DEBUG] %(message)s')
    
    file_handler.setFormatter(formatter)
    
    # 根据输出目标配置处理器
    log_output = config.get("logging.output", "BOTH").upper()
    if log_output in ["CONSOLE", "BOTH"]:
        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)
        api_logger.addHandler(console_handler)
    
    if log_output in ["FILE", "BOTH"]:
        # 添加文件处理器
        api_logger.addHandler(file_handler)
    
    # 设置其他模块的日志级别
    hide_http = config.get("logging.hide_http", True)
    if hide_http:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("uvicorn").setLevel(logging.WARNING)
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        
    # 确保chat模块日志不重复
    chat_logger = logging.getLogger("unlimited_proxy.chat")
    chat_logger.propagate = False

def parse_args():
    """解析命令行参数"""
    # 获取CPU核心数用于工作进程建议
    cpu_count = multiprocessing.cpu_count()
    recommended_workers = max(1, cpu_count)
    
    # 获取服务器配置中的工作进程数，确保是整数
    default_workers = config.get('server.workers', 1)
    if not isinstance(default_workers, int):
        logging.warning(f"配置文件中的工作进程数类型错误: {type(default_workers)}，使用默认值1")
        default_workers = 1
    
    # 从日志配置获取日志级别，而不是服务器配置
    default_log_level = config.get('logging.level', 'info').lower()
    
    # 从日志配置获取调试模式
    log_level_str = config.get('logging.level', 'INFO')
    default_debug = 'DEBUG' in log_level_str.upper() or log_level_str.upper() == 'ALL'
    
    parser = argparse.ArgumentParser(description='UnlimitedAI代理服务')
    parser.add_argument('--host', type=str, default=config.get('server.host', '127.0.0.1'), help='监听地址')
    parser.add_argument('--port', type=int, default=config.get('server.port', 8000), help='监听端口')
    parser.add_argument('--reload', action='store_true', default=config.get('server.reload', False), help='是否启用热重载 (开发模式)')
    parser.add_argument('--env-file', type=str, default='.env', help='环境变量配置文件路径')
    parser.add_argument('--log-level', type=str, default=default_log_level, 
                        choices=['debug', 'info', 'warning', 'error', 'critical', 'all', 'none'],
                        help='日志级别 (覆盖配置文件)')
    parser.add_argument('--log-dir', type=str, default=config.get('logging.dir', 'logs'), help='日志目录')
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    parser.add_argument('--debug', action='store_true', default=default_debug, help='启用调试模式 (覆盖配置文件)')
    parser.add_argument('--workers', type=int, default=default_workers, 
                       help=f'工作进程数量 (推荐: {recommended_workers})')
    return parser.parse_args()

def main():
    """主函数"""
    # 解析命令行参数
    args = parse_args()
    
    # 更新配置中的日志目录（如果在命令行中指定）
    if args.log_dir != config.get('logging.dir', 'logs'):
        config.set('logging.dir', args.log_dir)
    
    # 配置日志级别 - 使用命令行参数覆盖配置文件
    # 如果提供了命令行参数，则更新配置
    if args.log_level:
        config.set('logging.level', args.log_level.upper())
    
    # 配置调试模式 - 使用命令行参数覆盖配置文件
    if args.debug:
        config.set('logging.level', 'DEBUG')
    
    # 配置日志 - 使用parse_log_level函数解析日志级别
    log_level_str = config.get('logging.level', 'INFO')
    log_level = parse_log_level(log_level_str)
    setup_logging(log_level=log_level)
    
    logging.info(f"使用环境变量配置，配置文件: .env，日志级别: {config.get('logging.level')}")
    
    # 特别处理API调试日志
    if args.debug or 'DEBUG' in config.get('logging.level', 'INFO').upper() or config.get('logging.level', 'INFO').upper() == 'ALL':
        api_logger = logging.getLogger("unlimited_proxy.api_debug")
        api_logger.setLevel(logging.DEBUG)
        logging.info("启用API调试模式 - 将输出所有API请求和响应细节")
        # 调试模式同时影响服务器配置
        config.set('server.debug', True)
    
    # 获取服务器相关配置
    timeout_keep_alive = config.get('server.timeout_keep_alive', 120)
    timeout_graceful_shutdown = config.get('server.timeout_graceful_shutdown', 10)
    limit_concurrency = config.get('server.limit_concurrency', 100)
    backlog = config.get('server.backlog', 128)
    
    # 检查多进程模式
    workers = args.workers
    # 确保workers是整数类型
    if not isinstance(workers, int):
        logging.warning(f"工作进程参数类型错误：{type(workers)}，将使用默认值1")
        workers = 1
    
    storage_type = config.get('token.storage_type', 'sqlite')
    if workers > 1 and storage_type != 'redis':
        logging.warning(f"警告: 您设置了 {workers} 个工作进程，但Token存储类型为 {storage_type}")
        logging.warning("多进程模式下建议使用redis存储类型，否则可能出现Token管理问题")
        logging.warning("如需使用多进程，请设置 UNLIMITED_TOKEN_STORAGE_TYPE=redis")
    
    # 打印欢迎信息
    print(f"""
╔══════════════════════════════════════════════════╗
                                                   
    UnlimitedAI代理服务 v{__version__:<23}          
                                                   
    服务地址: http://{args.host}:{args.port:<19}   
    测试页面: http://{args.host}:{args.port}/test  
    API文档:  http://{args.host}:{args.port}/docs  
                                                   
    使用 Ctrl+C 停止服务                            
                                                   
╚══════════════════════════════════════════════════╝
    """)
    
    # 日志显示配置信息
    logging.info(f"服务配置: 主机={args.host}, 端口={args.port}, 工作进程={workers}, 调试模式={args.debug}")
    logging.info(f"高级配置: 连接保持={timeout_keep_alive}秒, 优雅关闭={timeout_graceful_shutdown}秒")
    
    if workers > 1:
        logging.info(f"多进程模式: 使用 {workers} 个工作进程, 存储类型={storage_type}")
        if storage_type != 'redis':
            logging.warning("警告: 多进程模式下，各进程的Token缓存不共享，可能导致过多的Token请求")
    
    # 启动服务器
    try:
        # 构建Uvicorn配置
        uvicorn_config = {
            "app": app,
            "host": args.host,
            "port": args.port,
            "timeout_keep_alive": timeout_keep_alive,
            "limit_concurrency": limit_concurrency if limit_concurrency > 0 else None,
            "backlog": backlog,
            "workers": workers,
            # 直接使用简单的日志级别设置
            "log_level": "info"
        }
        
        # 处理reload参数
        if args.reload:
            uvicorn_config["reload"] = True
            # 热重载模式下不支持多工作进程
            if workers > 1:
                logging.warning("热重载模式下不支持多工作进程，已忽略workers设置")
                uvicorn_config.pop("workers", None)
        
        # 打印Uvicorn配置以便调试
        print("Uvicorn配置:", uvicorn_config)
        print(f"workers类型: {type(workers)}, 值: {workers}")
        
        uvicorn.run(**uvicorn_config)
    except KeyboardInterrupt:
        logging.info("接收到停止信号，服务正在关闭")
        print("\n服务已停止")
    except Exception as e:
        logging.error(f"服务异常退出: {e}", exc_info=True)
        print(f"服务异常退出: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main() 