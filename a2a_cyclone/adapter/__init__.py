# A2A-Cyclone Adapter Layer — 执行器适配接口
# Licensed under Apache License 2.0
#
# Adapter 层是 Protocol 层（宪法）和 Runtime 层（执行）之上的
# "适配层"，负责将具体执行器（Shell、Claude Code、Python 脚本等）
# 统一为 SlaveAdapter 接口，接入 A2A-Cyclone 总线协议。
#
# 与本层相对的 Protocol 层绝对纯净（零 I/O），而本层聚焦于：
#   1. 执行器生命周期管理（子进程启动/监控/销毁）
#   2. 任务上下文封装（TaskPackage / TaskResult 数据合约）
#   3. 输出流解析与心跳信号提取
#   4. 适配器注册与路由

from .base import SlaveStatus, TaskPackage, TaskResult, SlaveAdapter
from .registry import AdapterRegistry
from .shell_adapter import ShellAdapter
from .claude_code_adapter import ClaudeCodeAdapter

__all__ = [
    "SlaveStatus",
    "TaskPackage",
    "TaskResult",
    "SlaveAdapter",
    "AdapterRegistry",
    "ShellAdapter",
    "ClaudeCodeAdapter",
]
