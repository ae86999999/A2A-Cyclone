"""
A2A-Cyclone Adapter Layer: 抽象基类与数据合约
==============================================

定义所有执行器必须遵守的接口规范，包括：
  - SlaveStatus   : 从控节点的工作状态枚举
  - TaskPackage   : Master → Slave 的任务上下文数据包
  - TaskResult    : Slave → Master 的执行结果数据包
  - SlaveAdapter  : 所有执行器必须实现的抽象基类

设计原则：
  - 接口最小化 — 只定义 execute/get_status/cancel/get_capabilities
  - 数据不可变 — TaskPackage 和 TaskResult 均为 frozen dataclass
  - 错误包容 — 异常信息在 TaskResult.error_log 中传递，不抛到协议层
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any


class SlaveStatus(str, Enum):
    """从控节点在 A2A-Cyclone 总线上的工作状态

    此枚举与 protocol.enums.BusState 对应但不相同：
      BusState 描述总线的物理状态（000/001/.../103）
      SlaveStatus 描述执行器的逻辑状态（IDLE/BUSY/ERROR/COMPLETED）
    """
    IDLE = "IDLE"               # 监听挂起中，对应 BusState 000/001
    BUSY = "BUSY"               # 持有令牌执行中，对应 BusState 102/202
    ERROR = "ERROR"             # 异常终止，对应 BusState 103
    COMPLETED = "COMPLETED"     # 任务完成待回收，对应 BusState 100


@dataclass(frozen=True)
class TaskPackage:
    """Master → Slave 的任务上下文数据包

    这是 Master 编排器向执行器传递的完整任务描述。
    一旦创建不可修改，保证任务描述的一致性。

    Attributes:
        task_id:        全局唯一任务标识，格式建议 {action}-{timestamp}
        command:        人类可读的任务指令（如"把 SVPWM 改为 Q15 定点数"）
        worktree_path:  影子工作区的绝对路径，执行器在此目录内操作
        context:        附加上下文键值对（如记忆库检索结果、芯片手册片段）
        timeout_seconds:最长执行时间（秒），超时后由 Adapter 触发 cancel()
        max_retries:    失败时自动重试的最大次数
        heartbeat_markers: 期望在输出流中识别为心跳信号的前缀标记列表
    """
    task_id: str
    command: str
    worktree_path: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 300
    max_retries: int = 2
    heartbeat_markers: tuple = field(
        default=("[HEARTBEAT]", "[PROGRESS]", "[STATUS]"),
        compare=False,
    )


@dataclass(frozen=True)
class TaskResult:
    """Slave → Master 的执行结果数据包

    所有执行结果标准化为此结构，供 Master 编排器统一处理。

    Attributes:
        task_id:        对应的 TaskPackage.task_id
        success:        是否成功完成
        summary:        人类可读的执行摘要（前 500 字符）
        diff:           git diff 输出（若任务涉及代码修改）
        commit_hash:    若 auto-commit 执行，记录 commit hash
        artifacts:      附加产出物路径映射（如编译产物 .hex / .map）
        error_log:      失败时的详细错误输出（后 1000 字符）
        status:         执行完成时的从控状态
    """
    task_id: str
    success: bool
    summary: str = ""
    diff: str = ""
    commit_hash: Optional[str] = None
    artifacts: Dict[str, str] = field(default_factory=dict)
    error_log: Optional[str] = None
    status: SlaveStatus = SlaveStatus.COMPLETED


class SlaveAdapter(ABC):
    """从控适配器抽象基类

    所有具体执行器（ShellAdapter / ClaudeCodeAdapter / PythonAdapter 等）
    必须实现此接口。接口围绕单一职责设计：在受控环境中执行一个任务，
    返回标准化结果，同时提供生命周期管理和能力声明。

    使用惯例：
      execute() 可以同步或异步执行任务，但 get_status() 必须能在
      执行中的任何时刻被安全调用。
    """

    @abstractmethod
    def execute(self, package: TaskPackage) -> TaskResult:
        """接收 TaskPackage，执行任务，返回 TaskResult

        Args:
            package: Master 编排器下发的任务上下文包

        Returns:
            标准化的执行结果

        Raises:
            TimeoutError: 任务超时且 cancel() 已触发
            RuntimeError: 执行器内部不可恢复的错误
        """
        ...

    @abstractmethod
    def get_status(self) -> SlaveStatus:
        """轮询当前执行状态

        可在 execute() 执行期间随时调用，返回当前执行器状态。
        用于 Master 的 LeaseWatcher 判断是否需要续租或回收令牌。

        Returns:
            当前状态（IDLE / BUSY / ERROR / COMPLETED）
        """
        ...

    @abstractmethod
    def cancel(self) -> bool:
        """强制终止当前执行

        Master 检测到租约过期或收到用户取消指令时调用。
        执行器应在此方法中杀戮子进程、清理临时文件、释放资源。
        与 force_transition(103) 配合，构成完整的安全回收链路。

        Returns:
            True 表示成功终止，False 表示终止失败（如任务已完成）
        """
        ...

    @abstractmethod
    def get_capabilities(self) -> Dict[str, Any]:
        """声明自身能力，供 Master 编排器做任务路由决策

        返回示例:
          {
              "executor_type": "shell",
              "supported_commands": ["bash", "python", "make"],
              "max_timeout_seconds": 3600,
              "requires_network": False,
              "platform": "win32",
          }

        Returns:
            描述执行器能力的键值对
        """
        ...
