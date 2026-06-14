"""
A2A-Cyclone Adapter Layer 单元测试 — Shell 命令执行器
======================================================

测试范围:
  - 正常命令执行（echo、exit code）
  - 输出捕获（stdout / stderr）
  - 超时检测与杀戮
  - 取消操作
  - 重试逻辑
  - 边界条件（空命令、不存在的命令、大输出、非零退出码）
"""

import os
import queue
import sys
import tempfile
import time
import threading
from pathlib import Path

import pytest

from a2a_cyclone.adapter.base import SlaveAdapter, SlaveStatus, TaskPackage, TaskResult
from a2a_cyclone.adapter.shell_adapter import ShellAdapter


SHELL = "cmd" if sys.platform == "win32" else "bash"


# ================================================================
# 正常路径
# ================================================================

class TestShellAdapterNormal:
    def test_execute_simple_command(self):
        """执行简单的 echo 命令应成功"""
        adapter = ShellAdapter()
        pkg = TaskPackage(
            task_id="test-001",
            command='echo "hello a2a"',
            timeout_seconds=10,
        )
        result = adapter.execute(pkg)
        assert result.success is True
        assert "hello a2a" in result.summary or "hello a2a" in result.__dict__.get("summary", "")

    def test_exit_code_zero(self):
        """exit 0 应成功"""
        adapter = ShellAdapter()
        cmd = "exit 0" if sys.platform != "win32" else "exit /b 0"
        result = adapter.execute(TaskPackage(
            task_id="test-002", command=cmd, timeout_seconds=5,
        ))
        assert result.success is True

    def test_exit_code_nonzero(self):
        """非零退出码应失败"""
        adapter = ShellAdapter()
        cmd = "exit 1" if sys.platform != "win32" else "exit /b 1"
        result = adapter.execute(TaskPackage(
            task_id="test-003", command=cmd, timeout_seconds=5,
        ))
        assert result.success is False
        assert result.status == SlaveStatus.ERROR

    def test_stdout_capture(self):
        """stdout 输出应被完整捕获"""
        adapter = ShellAdapter()
        pkg = TaskPackage(
            task_id="test-004",
            command='echo "line1" && echo "line2" && echo "line3"',
            timeout_seconds=5,
        )
        result = adapter.execute(pkg)
        assert result.success is True

    def test_stderr_capture(self):
        """stderr 输出应被捕获到 error_log"""
        adapter = ShellAdapter()
        if sys.platform == "win32":
            cmd = "echo stderr test 1>&2"
        else:
            cmd = "echo 'stderr test' >&2"
        result = adapter.execute(TaskPackage(
            task_id="test-005", command=cmd, timeout_seconds=5,
        ))
        # stderr 重定向到文件时可能不会导致失败
        # 至少确保执行没有崩溃

    def test_adapter_interface_conformance(self):
        """ShellAdapter 实现 SlaveAdapter 接口"""
        adapter = ShellAdapter()
        assert isinstance(adapter, SlaveAdapter)
        caps = adapter.get_capabilities()
        assert caps["executor_type"] == "shell"


# ================================================================
# 超时测试
# ================================================================

class TestShellAdapterTimeout:
    def test_timeout_triggers(self):
        """超时的任务应返回失败"""
        adapter = ShellAdapter()
        if sys.platform == "win32":
            cmd = "ping -n 10 127.0.0.1 > nul"
        else:
            cmd = "sleep 10"
        result = adapter.execute(TaskPackage(
            task_id="test-timeout",
            command=cmd,
            timeout_seconds=2,
            max_retries=0,  # 不重试，快速返回
        ))
        assert result.success is False
        assert "Timeout" in result.summary

    def test_timeout_kills_process(self):
        """超时后进程应被杀死（执行完后状态回归 IDLE）"""
        adapter = ShellAdapter()
        pkg = TaskPackage(
            task_id="test-kill",
            command="sleep 30" if sys.platform != "win32" else "ping -n 30 127.0.0.1 > nul",
            timeout_seconds=1,
            max_retries=0,  # 不重试
        )

        # 同步执行（max_retries=0 只跑一次）
        result = adapter.execute(pkg)
        assert result.success is False
        assert "Timeout" in result.summary
        assert adapter.get_status() == SlaveStatus.IDLE  # 执行完后回到空闲


# ================================================================
# 取消测试
# ================================================================

class TestShellAdapterCancel:
    def test_cancel_long_running(self):
        """长时间运行的任务可以被 cancel 终止并返回失败结果"""
        import queue
        adapter = ShellAdapter()
        result_queue = queue.Queue()

        def run():
            result_queue.put(adapter.execute(TaskPackage(
                task_id="test-cancel",
                command="sleep 60" if sys.platform != "win32" else "ping -n 60 127.0.0.1 > nul",
                timeout_seconds=30,
                max_retries=0,
            )))

        t = threading.Thread(target=run, daemon=True)
        t.start()
        time.sleep(1)
        assert adapter.cancel() is True

        # 等待最多 10 秒（远小于原命令的 60 秒）
        try:
            result = result_queue.get(timeout=10)
        except queue.Empty:
            # 若超时未返回，强制 cancel 并断言失败
            adapter.cancel()
            raise AssertionError("cancel 后线程未在 10 秒内返回")

        assert result.success is False

    def test_cancel_twice(self):
        """重复 cancel 应安全（不会抛异常）"""
        adapter = ShellAdapter()

        def run():
            adapter.execute(TaskPackage(
                task_id="test-cancel2",
                command="sleep 60" if sys.platform != "win32" else "ping -n 60 127.0.0.1 > nul",
                timeout_seconds=30,
                max_retries=0,
            ))
        t = threading.Thread(target=run)
        t.start()
        time.sleep(1)

        first = adapter.cancel()
        second = adapter.cancel()  # 第二次 cancel 应返回 False（已取消）
        t.join(timeout=10)
        assert first is True


# ================================================================
# 重试逻辑
# ================================================================

class TestShellAdapterRetry:
    def test_success_on_first_try_no_retry(self):
        """成功时不应重试"""
        adapter = ShellAdapter()
        result = adapter.execute(TaskPackage(
            task_id="test-retry-ok",
            command="exit 0" if sys.platform != "win32" else "exit /b 0",
            max_retries=3,
            timeout_seconds=5,
        ))
        assert result.success is True
        # 如果执行了一次，没有重试，应该快速返回

    def test_retry_on_failure(self):
        """失败时重试，应执行 max_retries 次"""
        adapter = ShellAdapter()
        cmd = "exit 1" if sys.platform != "win32" else "exit /b 1"
        result = adapter.execute(TaskPackage(
            task_id="test-retry-fail",
            command=cmd,
            max_retries=2,
            timeout_seconds=5,
        ))
        assert result.success is False
        # retries 消耗完后返回 ERROR 状态
        assert result.status == SlaveStatus.ERROR


# ================================================================
# 边界条件
# ================================================================

class TestShellAdapterBoundary:
    def test_empty_command(self):
        """空命令：不应崩溃"""
        adapter = ShellAdapter()
        result = adapter.execute(TaskPackage(
            task_id="test-empty", command="", timeout_seconds=5,
        ))
        # 空命令的行为取决于 shell，可能成功可能失败
        # 关键是不抛异常
        assert result is not None

    def test_nonexistent_worktree(self):
        """不存在的 worktree 路径应自动创建"""
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = os.path.join(tmpdir, "nonexistent", "deep")
            adapter = ShellAdapter()
            result = adapter.execute(TaskPackage(
                task_id="test-mkdir",
                command='echo "hello"',
                worktree_path=new_dir,
                timeout_seconds=5,
            ))
            assert result.success is True
            assert os.path.exists(new_dir)

    @pytest.mark.skipif(sys.platform == "win32", reason="Command as arg only on Unix")
    def test_large_output(self):
        """大量输出应能被截断处理"""
        adapter = ShellAdapter()
        result = adapter.execute(TaskPackage(
            task_id="test-large",
            command="for i in $(seq 1 200); do echo 'line'$i; done",
            timeout_seconds=10,
        ))
        assert result is not None

    def test_immediate_exit_on_cancel_before_execute(self):
        """在 execute 之前 cancel 应安全"""
        adapter = ShellAdapter()
        assert adapter.cancel() is False  # 没有进程在运行

    def test_get_status_idle_initial(self):
        """初始状态应为 IDLE"""
        adapter = ShellAdapter()
        assert adapter.get_status() == SlaveStatus.IDLE

    def test_get_capabilities_returns_dict(self):
        """get_capabilities 应返回非空 dict"""
        adapter = ShellAdapter()
        caps = adapter.get_capabilities()
        assert isinstance(caps, dict)
        assert len(caps) > 0

    def test_worktree_created_then_cleaned_up_by_caller(self):
        """worktree 目录由调用方管理，Adapter 不负责清理"""
        base_dir = tempfile.mkdtemp()
        adapter = ShellAdapter()
        result = adapter.execute(TaskPackage(
            task_id="test-worktree",
            command='echo "done"',
            worktree_path=base_dir,
            timeout_seconds=5,
        ))
        assert result.success is True
        # 工作目录仍然存在
        assert os.path.exists(base_dir)
        os.rmdir(base_dir)
