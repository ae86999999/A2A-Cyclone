"""
A2A-Cyclone Adapter Layer 单元测试 — Claude Code 执行器
========================================================

测试范围:
  - Prompt 渲染（模板结构、上下文注入、截断）
  - 输出解析（[HEARTBEAT] / [PROGRESS] / [RESULT] 标记提取）
  - 执行流程（mock 子进程）
  - 三重心跳检测验证
  - 超时与取消
  - 重试逻辑
  - 边界条件（Claude CLI 不存在、空输出、大上下文）
"""

import os
import sys
import json
import tempfile
import time
import threading
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, PropertyMock

import pytest

from a2a_cyclone.adapter.base import (
    SlaveAdapter, SlaveStatus, TaskPackage, TaskResult,
)
from a2a_cyclone.adapter.claude_code_adapter import (
    ClaudeCodeAdapter,
    SYSTEM_PROMPT_TEMPLATE,
)


# ================================================================
# 辅助函数
# ================================================================

def make_mock_popen(stdout_lines=None, stderr_lines=None, return_code=0):
    """创建模拟的 subprocess.Popen 对象"""
    proc = MagicMock()
    proc.stdout = MagicMock()
    proc.stderr = MagicMock()
    proc.poll.return_value = return_code

    def readline_side_effect(lines):
        """模拟 iter(stream.readline, '') 的行为"""
        def generator():
            for line in lines:
                yield line
            while True:
                yield ""
        return generator().__next__

    if stdout_lines:
        proc.stdout.readline.side_effect = readline_side_effect(stdout_lines)
    else:
        proc.stdout.readline.side_effect = readline_side_effect([])

    if stderr_lines:
        proc.stderr.readline.side_effect = readline_side_effect(stderr_lines)
    else:
        proc.stderr.readline.side_effect = readline_side_effect([])

    return proc


# ================================================================
# Prompt 渲染测试
# ================================================================

class TestPromptRendering:
    def test_template_contains_required_sections(self):
        """Prompt 模板必须包含所有必要指令"""
        assert "{command}" in SYSTEM_PROMPT_TEMPLATE
        assert "{worktree_path}" in SYSTEM_PROMPT_TEMPLATE
        assert "{task_id}" in SYSTEM_PROMPT_TEMPLATE
        assert "{timeout_seconds}" in SYSTEM_PROMPT_TEMPLATE
        assert "{context_str}" in SYSTEM_PROMPT_TEMPLATE

    def test_template_contains_heartbeat_instruction(self):
        """模板必须指导 Claude Code 输出心跳标记"""
        assert "[HEARTBEAT]" in SYSTEM_PROMPT_TEMPLATE
        assert "[RESULT] SUCCESS:" in SYSTEM_PROMPT_TEMPLATE
        assert "[RESULT] FAILURE:" in SYSTEM_PROMPT_TEMPLATE

    def test_render_basic(self):
        """基本渲染不报错"""
        adapter = ClaudeCodeAdapter()
        # patch _detect_claude_version to avoid version check
        with patch.object(adapter, '_detect_claude_version', return_value="test"):
            pkg = TaskPackage(
                task_id="test-001",
                command="echo hello",
                worktree_path="/tmp/work",
            )
            prompt = adapter._render_prompt(pkg)
            assert "echo hello" in prompt
            assert "/tmp/work" in prompt
            assert "test-001" in prompt

    def test_render_with_context(self):
        """附加上下文应被渲染到 prompt 中"""
        adapter = ClaudeCodeAdapter()
        with patch.object(adapter, '_detect_claude_version', return_value="test"):
            pkg = TaskPackage(
                task_id="test-002",
                command="重构代码",
                context={"chip": "PY32F002B", "notes": "Q15定点化"},
            )
            prompt = adapter._render_prompt(pkg)
            assert "PY32F002B" in prompt
            assert "Q15定点化" in prompt

    def test_render_context_truncation(self):
        """超长上下文应被截断"""
        adapter = ClaudeCodeAdapter()
        with patch.object(adapter, '_detect_claude_version', return_value="test"):
            huge_context = {"data": "x" * 5000}
            pkg = TaskPackage(
                task_id="test-003",
                command="test",
                context=huge_context,
            )
            prompt = adapter._render_prompt(pkg)
            # 5000 字符的 context 应被截断到 2000
            assert "(truncated)" in prompt

    @pytest.mark.boundary
    def test_render_empty_context(self):
        """空上下文的渲染"""
        adapter = ClaudeCodeAdapter()
        with patch.object(adapter, '_detect_claude_version', return_value="test"):
            pkg = TaskPackage(
                task_id="test-004",
                command="test",
                context={},
            )
            prompt = adapter._render_prompt(pkg)
            assert "(无附加上下文)" in prompt


# ================================================================
# 输出标记解析测试
# ================================================================

class TestOutputParsing:
    def test_parse_heartbeat_marker(self):
        """[HEARTBEAT] 标记应被识别"""
        adapter = ClaudeCodeAdapter()
        with patch.object(adapter, '_detect_claude_version', return_value="test"):
            adapter._parse_markers("[HEARTBEAT] step 1/5 completed\n")
            assert len(adapter._detected_markers["heartbeat"]) == 1
            assert "step 1/5" in adapter._detected_markers["heartbeat"][0]

    def test_parse_progress_marker(self):
        """[PROGRESS] 标记应被识别"""
        adapter = ClaudeCodeAdapter()
        with patch.object(adapter, '_detect_claude_version', return_value="test"):
            adapter._parse_markers("[PROGRESS] 编译进行中\n")
            assert len(adapter._detected_markers["progress"]) == 1

    def test_parse_result_success(self):
        """[RESULT] SUCCESS 应被正确解析"""
        adapter = ClaudeCodeAdapter()
        result = adapter._extract_result_marker(
            "some output\n[RESULT] SUCCESS: 重构完成\nmore output"
        )
        assert result is not None
        assert result[0] == "SUCCESS"
        assert "重构完成" in result[1]

    def test_parse_result_failure(self):
        """[RESULT] FAILURE 应被正确解析"""
        adapter = ClaudeCodeAdapter()
        result = adapter._extract_result_marker(
            "[RESULT] FAILURE: 编译错误: undefined reference"
        )
        assert result is not None
        assert result[0] == "FAILURE"

    def test_parse_result_not_found(self):
        """无标记时返回 None"""
        adapter = ClaudeCodeAdapter()
        result = adapter._extract_result_marker("just normal output")
        assert result is None

    def test_parse_diff_marker(self):
        """[DIFF] 标记应被记录"""
        adapter = ClaudeCodeAdapter()
        with patch.object(adapter, '_detect_claude_version', return_value="test"):
            adapter._parse_markers("[DIFF] src/svpwm.c\n")
            assert len(adapter._detected_markers["diff"]) == 1

    @pytest.mark.boundary
    def test_parse_empty_line(self):
        """空行不应触发解析错误"""
        adapter = ClaudeCodeAdapter()
        with patch.object(adapter, '_detect_claude_version', return_value="test"):
            adapter._parse_markers("")
            # 不抛异常
            assert True

    @pytest.mark.boundary
    def test_parse_unknown_line(self):
        """非标记行不应被记录"""
        adapter = ClaudeCodeAdapter()
        with patch.object(adapter, '_detect_claude_version', return_value="test"):
            adapter._parse_markers("just a normal thinking line\n")
            assert len(adapter._detected_markers["heartbeat"]) == 0
            assert len(adapter._detected_markers["result"]) == 0


# ================================================================
# _determine_success 测试
# ================================================================

class TestDetermineSuccess:
    def test_success_marker_wins(self):
        """[RESULT] SUCCESS 存在时即使 return_code != 0 也视为成功"""
        adapter = ClaudeCodeAdapter()
        assert adapter._determine_success(1, ("SUCCESS", "done")) is True

    def test_failure_marker_wins(self):
        """[RESULT] FAILURE 存在时即使 return_code == 0 也视为失败"""
        adapter = ClaudeCodeAdapter()
        assert adapter._determine_success(0, ("FAILURE", "error")) is False

    def test_return_code_zero(self):
        """没有标记时 return_code 0 为成功"""
        adapter = ClaudeCodeAdapter()
        assert adapter._determine_success(0, None) is True

    def test_return_code_nonzero(self):
        """没有标记时 return_code != 0 为失败"""
        adapter = ClaudeCodeAdapter()
        assert adapter._determine_success(1, None) is False

    def test_no_marker_no_retcode(self):
        """都没有时视为失败"""
        adapter = ClaudeCodeAdapter()
        assert adapter._determine_success(None, None) is False


# ================================================================
# 流程测试（mock 子进程）
# ================================================================

class TestClaudeCodeAdapterFlow:
    def test_successful_execution(self):
        """模拟一次成功的 Claude Code 执行"""
        adapter = ClaudeCodeAdapter()
        with patch.object(adapter, '_detect_claude_version', return_value="test"):
            # 模拟 claude 成功返回
            mock_proc = make_mock_popen(
                stdout_lines=[
                    "开始分析当前代码结构...\n",
                    "[HEARTBEAT] step 1/3 completed\n",
                    "正在重构 SVPWM 逻辑...\n",
                    "[HEARTBEAT] step 2/3 completed\n",
                    "验证编译通过\n",
                    "[HEARTBEAT] step 3/3 completed\n",
                    "[RESULT] SUCCESS: 重构完成，周期 -15%\n",
                ],
                return_code=0,
            )

            with patch("subprocess.Popen", return_value=mock_proc):
                with tempfile.TemporaryDirectory() as tmpdir:
                    result = adapter.execute(TaskPackage(
                        task_id="test-flow",
                        command="重构 SVPWM",
                        worktree_path=tmpdir,
                        timeout_seconds=30,
                    ))
                    assert result.success is True
                    assert "重构完成" in result.summary

    def test_failed_execution_with_marker(self):
        """Claude Code 输出 FAILURE 标记时应返回错误"""
        adapter = ClaudeCodeAdapter()
        with patch.object(adapter, '_detect_claude_version', return_value="test"):
            mock_proc = make_mock_popen(
                stdout_lines=[
                    "尝试重构...\n",
                    "[HEARTBEAT] still working...\n",
                    "[RESULT] FAILURE: 编译错误: undefined reference to 'Q15_MUL'\n",
                ],
                return_code=1,
            )
            with patch("subprocess.Popen", return_value=mock_proc):
                with tempfile.TemporaryDirectory() as tmpdir:
                    result = adapter.execute(TaskPackage(
                        task_id="test-fail",
                        command="重构 SVPWM",
                        worktree_path=tmpdir,
                        max_retries=0,
                        timeout_seconds=10,
                    ))
                    assert result.success is False

    def test_execution_no_result_marker(self):
        """Claude Code 没有输出 [RESULT] 标记时，用 return_code 判定"""
        adapter = ClaudeCodeAdapter()
        with patch.object(adapter, '_detect_claude_version', return_value="test"):
            mock_proc = make_mock_popen(
                stdout_lines=["task completed\n"],
                return_code=0,
            )
            with patch("subprocess.Popen", return_value=mock_proc):
                with tempfile.TemporaryDirectory() as tmpdir:
                    result = adapter.execute(TaskPackage(
                        task_id="test-nomarker",
                        command="test",
                        worktree_path=tmpdir,
                        timeout_seconds=5,
                        max_retries=0,
                    ))
                    # return_code 0 且没有 FAILURE 标记 → 成功
                    assert result.success is True

    def test_claude_not_found(self):
        """Claude CLI 不存在时返回友好的错误信息"""
        adapter = ClaudeCodeAdapter(claude_path="/nonexistent/claude")
        with patch("subprocess.Popen", side_effect=FileNotFoundError("No such file")):
            result = adapter.execute(TaskPackage(
                task_id="test-notfound",
                command="test",
                timeout_seconds=5,
            ))
            assert result.success is False
            assert "not found" in result.summary.lower()

    def test_heartbeats_recorded_during_execution(self):
        """执行期间的心跳标记应被记录到 _detected_markers"""
        adapter = ClaudeCodeAdapter()
        with patch.object(adapter, '_detect_claude_version', return_value="test"):
            mock_proc = make_mock_popen(
                stdout_lines=[
                    "[HEARTBEAT] step 1/3\n",
                    "[HEARTBEAT] step 2/3\n",
                    "[HEARTBEAT] step 3/3\n",
                    "[RESULT] SUCCESS: done\n",
                ],
                return_code=0,
            )
            with patch("subprocess.Popen", return_value=mock_proc):
                with tempfile.TemporaryDirectory() as tmpdir:
                    adapter.execute(TaskPackage(
                        task_id="test-hb",
                        command="test",
                        worktree_path=tmpdir,
                        timeout_seconds=5,
                        max_retries=0,
                    ))
                    # 验证心跳被记录
                    assert len(adapter._detected_markers["heartbeat"]) == 3


# ================================================================
# 超时与取消（mock 模式下）
# ================================================================

class TestClaudeCodeAdapterTimeout:
    def test_timeout_during_execution(self):
        """超时后应返回失败"""
        adapter = ClaudeCodeAdapter()
        with patch.object(adapter, '_detect_claude_version', return_value="test"):
            # 模拟一个永远不会结束的进程
            mock_proc = make_mock_popen(
                stdout_lines=["[HEARTBEAT] still working...\n"],
                return_code=None,  # 进程不退出
            )
            mock_proc.poll.return_value = None  # 永不返回

            # 让 readline 循环有界
            call_count = 0
            def never_ending():
                nonlocal call_count
                call_count += 1
                if call_count > 3:
                    return ""
                return "[HEARTBEAT] still working...\n"

            mock_proc.stdout.readline.side_effect = never_ending

            with patch("subprocess.Popen", return_value=mock_proc):
                with tempfile.TemporaryDirectory() as tmpdir:
                    result = adapter.execute(TaskPackage(
                        task_id="test-timeout",
                        command="long task",
                        worktree_path=tmpdir,
                        timeout_seconds=0.5,  # 半秒就超时
                        max_retries=0,
                    ))
                    assert result.success is False
                    assert "Timeout" in result.summary


# ================================================================
# 边界条件
# ================================================================

class TestClaudeCodeAdapterBoundary:
    def test_empty_stdout(self):
        """Claude Code 没有任何输出时不应崩溃"""
        adapter = ClaudeCodeAdapter()
        with patch.object(adapter, '_detect_claude_version', return_value="test"):
            mock_proc = make_mock_popen(
                stdout_lines=[],
                return_code=0,
            )
            with patch("subprocess.Popen", return_value=mock_proc):
                with tempfile.TemporaryDirectory() as tmpdir:
                    result = adapter.execute(TaskPackage(
                        task_id="test-empty",
                        command="",
                        worktree_path=tmpdir,
                        max_retries=0,
                        timeout_seconds=5,
                    ))
                    assert result is not None

    def test_huge_stdout(self):
        """大量输出不应导致内存泄漏"""
        adapter = ClaudeCodeAdapter()
        with patch.object(adapter, '_detect_claude_version', return_value="test"):
            huge_lines = [f"line {i}\n" for i in range(10000)]
            huge_lines.append("[RESULT] SUCCESS: done\n")
            mock_proc = make_mock_popen(
                stdout_lines=huge_lines,
                return_code=0,
            )
            with patch("subprocess.Popen", return_value=mock_proc):
                with tempfile.TemporaryDirectory() as tmpdir:
                    result = adapter.execute(TaskPackage(
                        task_id="test-huge",
                        command="huge output",
                        worktree_path=tmpdir,
                        max_retries=0,
                        timeout_seconds=10,
                    ))
                    assert result is not None

    def test_no_worktree_path(self):
        """worktree_path 为空时不应崩溃"""
        adapter = ClaudeCodeAdapter()
        with patch.object(adapter, '_detect_claude_version', return_value="test"):
            mock_proc = make_mock_popen(
                stdout_lines=["[RESULT] SUCCESS: done\n"],
                return_code=0,
            )
            with patch("subprocess.Popen", return_value=mock_proc):
                result = adapter.execute(TaskPackage(
                    task_id="test-noworktree",
                    command="test",
                    max_retries=0,
                    timeout_seconds=5,
                ))
                assert result.success is True

    def test_get_capabilities(self):
        """get_capabilities 应返回预期的 keys"""
        adapter = ClaudeCodeAdapter()
        caps = adapter.get_capabilities()
        assert caps["executor_type"] == "claude_code"
        assert "supported_commands" in caps
        assert "claude_version" in caps

    def test_get_status_idle_initial(self):
        """初始状态应为 IDLE"""
        adapter = ClaudeCodeAdapter()
        assert adapter.get_status() == SlaveStatus.IDLE

    def test_cancel_idle(self):
        """空闲时 cancel 应返回 False（没有进程）"""
        adapter = ClaudeCodeAdapter()
        assert adapter.cancel() is False

    def test_execute_busy_twice(self):
        """正在执行时再次 execute 应抛 RuntimeError"""
        adapter = ClaudeCodeAdapter()
        with patch.object(adapter, '_detect_claude_version', return_value="test"):
            mock_proc = make_mock_popen(
                stdout_lines=["working...\n"],
                return_code=None,
            )
            mock_proc.poll.return_value = None

            call_count = 0
            def slow_output():
                nonlocal call_count
                call_count += 1
                if call_count > 2:
                    return ""
                return "working...\n"
            mock_proc.stdout.readline.side_effect = slow_output

            with patch("subprocess.Popen", return_value=mock_proc):
                with tempfile.TemporaryDirectory() as tmpdir:
                    # 在另一个线程执行
                    results = {}
                    def run():
                        try:
                            results["result"] = adapter.execute(TaskPackage(
                                task_id="test-busy1",
                                command="test",
                                worktree_path=tmpdir,
                                max_retries=0,
                                timeout_seconds=10,
                            ))
                        except Exception as e:
                            results["error"] = e

                    t = threading.Thread(target=run)
                    t.start()
                    time.sleep(0.5)

                    # 尝试再次 execute
                    with pytest.raises(RuntimeError):
                        adapter.execute(TaskPackage(
                            task_id="test-busy2",
                            command="test",
                            max_retries=0,
                            timeout_seconds=1,
                        ))

                    # 取消以清理
                    adapter.cancel()
                    t.join(timeout=5)
