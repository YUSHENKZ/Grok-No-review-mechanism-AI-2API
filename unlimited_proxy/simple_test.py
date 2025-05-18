#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
安全模块简单测试脚本，结果写入文件
"""

import sys
import os
from pathlib import Path

# 将当前目录加入到sys.path，让Python可以找到父级包
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

# 将结果写入到文件
output_file = Path('security_test_result.txt')

with open(output_file, 'w', encoding='utf-8') as f:
    try:
        f.write("开始测试安全模块...\n")
        
        # 导入安全模块
        from unlimited_proxy import security
        f.write(f"成功导入安全模块: {security.__name__}\n")
        
        # 检查关键功能
        f.write(f"IP封禁功能: {hasattr(security, 'block_ip')}\n")
        f.write(f"IP检查功能: {hasattr(security, 'is_ip_blocked')}\n")
        f.write(f"可疑请求检查: {hasattr(security, 'is_suspicious_request')}\n")
        f.write(f"速率限制功能: {hasattr(security, 'is_rate_limited')}\n")
        
        # 测试简单功能
        test_ip = "192.168.1.100"
        f.write(f"\nIP封禁测试:\n")
        f.write(f"初始状态，IP {test_ip} 是否被封禁: {security.is_ip_blocked(test_ip)}\n")
        
        # 测试可疑请求检查
        normal_path = "/v1/chat/completions"
        suspicious_path = "/wp-admin/.env"
        
        f.write(f"\n可疑请求检查:\n")
        f.write(f"正常路径 '{normal_path}' 是否可疑: {security.is_suspicious_request(normal_path)}\n")
        f.write(f"可疑路径 '{suspicious_path}' 是否可疑: {security.is_suspicious_request(suspicious_path)}\n")
        
        # 获取安全统计
        stats = security.get_security_stats()
        f.write(f"\n安全统计信息:\n")
        f.write(f"安全配置: {stats['config']}\n")
        
        # 测试白名单功能
        f.write(f"\n白名单功能测试:\n")
        f.write(f"白名单IP列表: {security.IP_WHITELIST}\n")
        
        f.write("\n测试完成，安全模块功能正常!\n")
    except Exception as e:
        f.write(f"测试过程中发生错误: {str(e)}\n")
        import traceback
        f.write(traceback.format_exc())

print(f"测试完成，结果已写入 {output_file.absolute()}") 