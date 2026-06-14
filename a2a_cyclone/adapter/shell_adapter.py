"""
A2A-Cyclone Adapter Layer: Shell 命令执行器
============================================

ShellAdapter 是最基础的 SlaveAdapter 实现，在 Git Worktree 中
执行任意的 shell 命令并返回标准化的 TaskResult。

它充当 "Hello World" 级别的参考实现，同时具备生产级的：
  - 子进程生命周期管理
  - 实时 stdout/stderr 捕获与心跳检测
  - 超时杀戮与资源清理
  - 重试逻辑

核心设计（三重心跳检测）:
  S1: stdout/stderr 有任意输出 → 续租
  S2: 输出中包含心跳标记行 → 续租
  S3: 进程存活 (proc.poll() is None) → 续租
  三者皆失 → lease expired → cancel()

用法:
    adapter = ShellAdapter()
    result = adapter.execute(TaskPackage(
        task_id="build-001",
        command="make -j4",
        worktree_path="/tmp/worktree",
        timeout_seconds=120,
    ))
"""

import os
import sys
import time
import signal
import subprocess
import threading
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from .base import SlaveAdapter, SlaveStatus, TaskPackage, TaskResult


class ShellAdapter(SlaveAdapter):
    """Shell 命令执行器

    在指定工作目录中执行 shell 命令，实时捕获输出，
    通过三重心跳检测维持执行状态。

    Attributes:
        _status:      当前执行器状态
        _process:     当前子进程引用（execute 期间非 None）
        _stdout_data: 已收集的 stdout 完整内容
        _stderr_data: 已收集的 stderr 完整内容
        _last_output_time: 最后一次有输出的时间戳（用于续租判定）
        _cancel_flag: 取消标记，capture_output 线程据此退出
    """

    def __init__(self):
        self._status = SlaveStatus.IDLE
        self._process: Optional[subprocess.Popen] = None
        self._stdout_data: List[str] = []
        self._stderr_data: List[str] = []
        self._last_output_time: float = 0.0
        self._cancel_flag: bool = False
        self._lock = threading.Lock()
        self._current_task_id: str = ""

    # ---- SlaveAdapter 接口实现 ----

    def execute(self, package: TaskPackage) -> TaskResult:
        """执行 shell 命令

        流程:
          1. 锁定状态为 BUSY
          2. 创建工作目录（若不存在）
          3. 启动子进程，附加捕获线程
          4. 轮询状态直到完成或超时
          5. 组装 TaskResult 返回
        """
        with self._lock:
            if self._status == SlaveStatus.BUSY:
                raise RuntimeError(f"Adapter 正在执行任务 {self._current_task_id}")
            self._status = SlaveStatus.BUSY
            self._current_task_id = package.task_id
            self._cancel_flag = False
            self._stdout_data = []
            self._stderr_data = []
            self._last_output_time = time.time()

        result = None
        retries = 0

        while retries <= package.max_retries:
            if retries > 0:
                time.sleep(1)  # 重试间隔

            result = self._run_once(package)
            if result.success:
                with self._lock:
                    self._status = SlaveStatus.IDLE
                    self._process = None
                return result

            # 非可恢复错误（超时、二进制不存在）不重试
            if self._is_non_recoverable(result):
                break

            retries += 1

        # 所有重试耗尽 — 返回最后一次的结果，保留原始摘要和错误
        assert result is not None
        with self._lock:
            self._status = SlaveStatus.IDLE
            self._process = None
        return result

    def get_status(self) -> SlaveStatus:
        with self._lock:
            # 如果标记为 BUSY 但进程已死，自动转为 COMPLETED
            if self._status == SlaveStatus.BUSY and self._process is not None:
                ret = self._process.poll()
                if ret is not None:
                    # 进程已退出但还没被 execute() 收集
                    # 不自动改状态，等 execute 的循环去收集
                    pass
            return self._status

    def cancel(self) -> bool:
        """强制终止当前执行

        尝试优雅终止（SIGTERM），1 秒后强制杀戮（SIGKILL）。
        """
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                return False
            self._cancel_flag = True
            proc = self._process

        # 解锁后操作
        self._kill_process(proc)
        with self._lock:
            self._status = SlaveStatus.ERROR
        return True

    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "executor_type": "shell",
            "supported_commands": ["bash", "sh", "cmd", "python", "make"],
            "max_timeout_seconds": 3600,
            "requires_network": False,
            "platform": sys.platform,
        }

    # ---- 内部实现 ----

    def _run_once(self, package: TaskPackage) -> TaskResult:
        """单次执行逻辑（不包含重试）"""
        self._cancel_flag = False
        self._stdout_data = []
        self._stderr_data = []
        self._last_output_time = time.time()

        # 1. 确保工作目录存在
        worktree = package.worktree_path
        if worktree and not os.path.exists(worktree):
            os.makedirs(worktree, exist_ok=True)

        # 2. 确定 shell
        shell_cmd = self._resolve_shell()

        # 3. 启动子进程
        try:
            proc = subprocess.Popen(
                package.command if shell_cmd == "cmd" else package.command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=worktree or None,
                text=True,
                bufsize=1,  # 行缓冲
            )
        except FileNotFoundError as e:
            return TaskResult(
                task_id=package.task_id,
                success=False,
                summary=f"Shell not found: {e}",
                error_log=str(e),
                status=SlaveStatus.ERROR,
            )

        with self._lock:
            self._process = proc

        # 4. 启动 stdout/stderr 捕获线程
        stdout_thread = threading.Thread(
            target=self._capture_output,
            args=(proc.stdout, self._stdout_data),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=self._capture_output,
            args=(proc.stderr, self._stderr_data),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        # 5. 主循环：等待完成或超时
        start_time = time.time()
        while True:
            elapsed = time.time() - start_time

            # 超时检查
            if elapsed > package.timeout_seconds:
                self._kill_process(proc)
                # 等捕获线程结束
                stdout_thread.join(timeout=3)
                stderr_thread.join(timeout=3)
                return TaskResult(
                    task_id=package.task_id,
                    success=False,
                    summary=f"Timeout after {package.timeout_seconds}s",
                    error_log=self._get_recent_stderr(1000),
                    status=SlaveStatus.ERROR,
                )

            # 取消检查
            with self._lock:
                if self._cancel_flag:
                    self._kill_process(proc)
                    stdout_thread.join(timeout=3)
                    stderr_thread.join(timeout=3)
                    return TaskResult(
                        task_id=package.task_id,
                        success=False,
                        summary="Cancelled by user or master",
                        error_log=self._get_recent_stderr(1000),
                        status=SlaveStatus.ERROR,
                    )

            # 进程退出检查
            ret = proc.poll()
            if ret is not None:
                stdout_thread.join(timeout=5)
                stderr_thread.join(timeout=5)
                break

            time.sleep(0.2)

        # 6. 组装结果
        stdout_full = "".join(self._stdout_data)
        stderr_full = "".join(self._stderr_data)

        # 用心跳标记检测 stdout 中的进度信号
        heartbeat_detected = self._has_heartbeat(
            stdout_full, package.heartbeat_markers
        )

        result = TaskResult(
            task_id=package.task_id,
            success=(ret == 0),
            summary=self._truncate(stdout_full.strip()[-500:], 500),
            diff="",  # shell adapter 不自动生成 diff
            error_log=self._truncate(stderr_full.strip()[-1000:], 1000)
            if ret != 0 else None,
            status=SlaveStatus.COMPLETED if ret == 0 else SlaveStatus.ERROR,
        )

        with self._lock:
            self._status = SlaveStatus.IDLE
            self._process = None

        return result

    def _capture_output(self, stream, buffer: List[str]) -> None:
        """线程函数：逐行读取输出流，更新心跳时间"""
        try:
            for line in iter(stream.readline, ""):
                with self._lock:
                    buffer.append(line)
                    self._last_output_time = time.time()
                if self._cancel_flag:
                    break
        except (ValueError, OSError):
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _has_heartbeat(self, output: str, markers: tuple) -> bool:
        """检查输出中是否包含续租心跳标记"""
        for line in output.splitlines():
            for marker in markers:
                if line.strip().startswith(marker):
                    return True
        return False

    def _kill_process(self, proc: subprocess.Popen) -> None:
        """分级杀戮：SIGTERM → 1s → SIGKILL"""
        if proc.poll() is not None:
            return
        try:
            if sys.platform == "win32":
                proc.terminate()
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
            else:
                os.kill(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    os.kill(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=3)
        except Exception:
            pass

    @staticmethod
    def _is_non_recoverable(result: TaskResult) -> bool:
        """判断错误是否不可恢复（不应重试）

        不可恢复的错误包括:
          - 超时（重试只会继续超时）
          - Shell 或二进制不存在（重试也不会出现）
          - 用户取消（用户意图已明确）
          - 系统级错误
        """
        if not result.summary:
            return False
        summary_lower = result.summary.lower()
        non_recoverable_patterns = [
            "timeout",
            "not found",
            "no such file",
            "permission denied",
            "access denied",
            "cancelled",
        ]
        return any(p in summary_lower for p in non_recoverable_patterns)

    def _resolve_shell(self) -> str:
        """确定当前平台的 shell"""
        if sys.platform == "win32":
            return "cmd"
        return "bash"

    def _get_recent_stderr(self, max_chars: int) -> str:
        """获取最近的 stderr 内容"""
        data = "".join(self._stderr_data)
        return self._truncate(data, max_chars)

    @staticmethod
    def _truncate(text: str, max_chars: int) -> str:
        """安全截断文本（保留边界完整性）"""
        if len(text) <= max_chars:
            return text
        return "..." + text[-(max_chars - 3):]

    @property
    def last_output_time(self) -> float:
        """最后一次有输出的时间戳（供外部 LeaseWatcher 使用）"""
        with self._lock:
            return self._last_output_time

    @property
    def current_task_id(self) -> str:
        """当前正在执行的任务 ID"""
        with self._lock:
            return self._current_task_id
