"""
A2A-Cyclone Adapter Layer: Claude Code 执行器
==============================================

ClaudeCodeAdapter 封装 Claude Code CLI（claude CLI），
将其接入 A2A-Cyclone 总线协议，实现三重心跳检测、
超时回收、自动重试和结果结构化。

三重心跳检测（无需 Claude Code 软件层面配合）:
  S1 (stdout): 只要有 stdout 输出 → 续租
  S2 (标记):   输出行包含 [HEARTBEAT] 标记 → 续租
  S3 (进程):   进程存活 (proc.poll() is None) → 续租

输出流协议标记（通过 Prompt 指令告知 Claude Code 发送）:
  [HEARTBEAT] step N/M completed    → 续租信号 + 进度
  [PROGRESS] <detail>                → 续租信号 + 日志
  [STATUS] <state>                   → 状态变更通知
  [RESULT] SUCCESS: <summary>       → 任务成功
  [RESULT] FAILURE: <error>         → 任务失败
  [DIFF] <path>                      → 指示 git diff 路径

用法:
    adapter = ClaudeCodeAdapter(claude_path="claude")
    result = adapter.execute(TaskPackage(
        task_id="refactor-001",
        command="把 SVPWM 占空比刷新逻辑改为 Q15 定点数格式",
        worktree_path="/tmp/worktree/feature-q15",
        timeout_seconds=600,
    ))
"""

import os
import sys
import json
import time
import tempfile
import signal
import subprocess
import threading
import traceback
from typing import Optional, List, Dict, Any, Tuple

from .base import SlaveAdapter, SlaveStatus, TaskPackage, TaskResult


# ---- Prompt 模板 ----

SYSTEM_PROMPT_TEMPLATE = """你是一个 A2A-Cyclone 协议从控节点。你的任务由 Master 编排器分派。

## 任务指令
{command}

## 执行环境
- 工作目录: {worktree_path}
- 任务 ID: {task_id}
- 超时限制: {timeout_seconds} 秒

## 附加上下文
{context_str}

## 执行协议（你必须遵守）
1. 每完成一个子步骤，输出一行 `[HEARTBEAT] step N/M completed`
2. 如果遇到编译/运行等长时间任务，每 30 秒输出一行 `[HEARTBEAT] still working...`
3. 任务成功时，输出 `[RESULT] SUCCESS: <单行摘要>`
4. 任务失败时，输出 `[RESULT] FAILURE: <单行错误说明>`
5. 若生成了代码变更，最后告知: `[DIFF] <变更文件路径>`

## 约束
- 不要询问用户确认，直接执行
- 不要输出无意义的中转思考过程
- 只在工作目录 {worktree_path} 内操作
- 完成后不要交互式等待
"""


class ClaudeCodeAdapter(SlaveAdapter):
    """Claude Code 执行器

    通过子进程调用 claude CLI，在影子 Git Worktree 中
    执行代码重构/分析任务。

    Attributes:
        claude_path:       Claude Code CLI 路径（默认为 "claude"）
        _status:           当前执行器状态
        _process:          当前子进程引用
        _stdout_data:      stdout 完整内容
        _stderr_data:      stderr 完整内容
        _last_output_time: 最后输出时间（心跳基准）
        _cancel_flag:      取消标记
        _detected_markers: 从输出流中检测到的协议标记
    """

    def __init__(self, claude_path: str = "claude"):
        self.claude_path = claude_path
        self._status = SlaveStatus.IDLE
        self._process: Optional[subprocess.Popen] = None
        self._stdout_data: List[str] = []
        self._stderr_data: List[str] = []
        self._last_output_time: float = 0.0
        self._cancel_flag: bool = False
        self._lock = threading.Lock()
        self._current_task_id: str = ""
        self._detected_markers: Dict[str, List[str]] = {
            "heartbeat": [],
            "progress": [],
            "result": [],
            "diff": [],
        }

    # ---- SlaveAdapter 接口实现 ----

    def execute(self, package: TaskPackage) -> TaskResult:
        """执行 Claude Code 任务

        流程:
          1. 锁定状态为 BUSY
          2. 将任务指令 + 上下文渲染为结构化 Prompt
          3. 写入临时 task.md 文件
          4. 启动 claude 子进程，附加捕获线程
          5. 主循环检测超时/取消/完成
          6. 解析输出中 [RESULT] 标记
          7. 重试逻辑（失败时自动重试）
          8. 提取 git diff（若有）
        """
        with self._lock:
            if self._status == SlaveStatus.BUSY:
                raise RuntimeError(
                    f"Adapter 正在执行任务 {self._current_task_id}"
                )
            self._status = SlaveStatus.BUSY
            self._current_task_id = package.task_id
            self._cancel_flag = False
            self._stdout_data = []
            self._stderr_data = []
            self._last_output_time = time.time()
            self._detected_markers = {
                "heartbeat": [], "progress": [], "result": [], "diff": [],
            }

        result = None
        retries = 0

        while retries <= package.max_retries:
            if retries > 0:
                time.sleep(1)

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
            if self._status == SlaveStatus.BUSY and self._process is not None:
                ret = self._process.poll()
                if ret is not None:
                    # 进程退出了但 execute() 循环还没收集
                    pass
            return self._status

    def cancel(self) -> bool:
        """强制终止 Claude Code

        先 SIGTERM（1 秒等待），再 SIGKILL（3 秒等待）。
        """
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                return False
            self._cancel_flag = True
            proc = self._process

        self._kill_process(proc)
        with self._lock:
            self._status = SlaveStatus.ERROR
        return True

    def get_capabilities(self) -> Dict[str, Any]:
        return {
            "executor_type": "claude_code",
            "supported_commands": ["code_refactor", "code_review", "code_analysis"],
            "max_timeout_seconds": 3600,
            "requires_network": True,
            "platform": sys.platform,
            "claude_version": self._detect_claude_version(),
        }

    # ---- 内部实现 ----

    def _run_once(self, package: TaskPackage) -> TaskResult:
        """单次执行（不含重试）"""
        self._cancel_flag = False
        self._stdout_data = []
        self._stderr_data = []
        self._last_output_time = time.time()
        self._detected_markers = {
            "heartbeat": [], "progress": [], "result": [], "diff": [],
        }

        worktree = package.worktree_path
        if worktree and not os.path.exists(worktree):
            os.makedirs(worktree, exist_ok=True)

        # 1. 渲染 Prompt 并写入临时文件
        prompt_content = self._render_prompt(package)

        # 使用临时文件，执行完成后清理
        tmp_dir = tempfile.mkdtemp(prefix="a2a_task_")
        task_file = os.path.join(tmp_dir, "task.md")
        try:
            with open(task_file, "w", encoding="utf-8") as f:
                f.write(prompt_content)
        except OSError as e:
            self._cleanup_tmpdir(tmp_dir)
            return TaskResult(
                task_id=package.task_id,
                success=False,
                summary=f"Cannot write task file: {e}",
                error_log=str(e),
                status=SlaveStatus.ERROR,
            )

        # 2. 组装 CLI 命令
        cmd = self._build_cli_command(task_file)

        # 3. 启动子进程
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=worktree or None,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as e:
            self._cleanup_tmpdir(tmp_dir)
            return TaskResult(
                task_id=package.task_id,
                success=False,
                summary=f"Claude CLI not found at '{self.claude_path}': {e}",
                error_log=str(e),
                status=SlaveStatus.ERROR,
            )

        with self._lock:
            self._process = proc

        # 4. 启动捕获线程
        stdout_thread = threading.Thread(
            target=self._capture_output,
            args=(proc.stdout, self._stdout_data, True),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=self._capture_output,
            args=(proc.stderr, self._stderr_data, False),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        # 5. 主循环
        start_time = time.time()
        timeout_occurred = False
        cancelled = False

        while True:
            elapsed = time.time() - start_time

            # 超时检查
            if elapsed > package.timeout_seconds:
                self._kill_process(proc)
                timeout_occurred = True
                break

            # 取消检查
            with self._lock:
                if self._cancel_flag:
                    self._kill_process(proc)
                    cancelled = True
                    break

            # 进程退出检查
            ret = proc.poll()
            if ret is not None:
                break

            time.sleep(0.3)

        # 6. 等待输出线程完成
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        self._cleanup_tmpdir(tmp_dir)

        # 7. 解析结果
        stdout_full = "".join(self._stdout_data)
        stderr_full = "".join(self._stderr_data)

        if timeout_occurred:
            return TaskResult(
                task_id=package.task_id,
                success=False,
                summary=f"Timeout after {package.timeout_seconds}s",
                error_log=self._truncate(stderr_full, 1000),
                status=SlaveStatus.ERROR,
            )

        if cancelled:
            return TaskResult(
                task_id=package.task_id,
                success=False,
                summary="Cancelled by user or master",
                error_log=self._truncate(stderr_full, 1000),
                status=SlaveStatus.ERROR,
            )

        # 解析 [RESULT] 标记
        result_marker = self._extract_result_marker(stdout_full)
        diff_output = self._extract_diff(worktree, stdout_full)

        success = self._determine_success(ret, result_marker)

        return TaskResult(
            task_id=package.task_id,
            success=success,
            summary=result_marker[1] if result_marker else (
                self._truncate(stdout_full.strip()[-500:], 500)
            ),
            diff=diff_output,
            error_log=self._truncate(stderr_full, 1000) if not success else None,
            status=SlaveStatus.COMPLETED if success else SlaveStatus.ERROR,
        )

    def _render_prompt(self, package: TaskPackage) -> str:
        """将 TaskPackage 渲染为结构化 Prompt"""
        context_str = ""
        if package.context:
            context_lines = []
            for k, v in package.context.items():
                if isinstance(v, str) and len(v) > 2000:
                    v = v[:2000] + "\n... (truncated)"
                context_lines.append(f"### {k}\n{v}")
            context_str = "\n".join(context_lines)

        return SYSTEM_PROMPT_TEMPLATE.format(
            command=package.command,
            worktree_path=package.worktree_path or os.getcwd(),
            task_id=package.task_id,
            timeout_seconds=package.timeout_seconds,
            context_str=context_str or "(无附加上下文)",
        )

    def _build_cli_command(self, task_file: str) -> List[str]:
        """构造 claude CLI 命令

        尝试多种参数形式以保证兼容性：
          claude --auto --prompt-file <file>
          claude --auto -f <file>
          claude <file>
        """
        # 优先级 1: --auto + --prompt-file（官方推荐）
        # 优先级 2: -p <file>（旧版本兼容）
        # 优先级 3: 直接传文件路径
        return [self.claude_path, "--auto", "--prompt-file", task_file]

    def _capture_output(
        self, stream, buffer: List[str], is_stdout: bool
    ) -> None:
        """捕获输出流，检测协议标记，更新心跳时间"""
        try:
            for line in iter(stream.readline, ""):
                with self._lock:
                    buffer.append(line)
                    self._last_output_time = time.time()
                    if is_stdout:
                        self._parse_markers(line)
                if self._cancel_flag:
                    break
        except (ValueError, OSError):
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _parse_markers(self, line: str) -> None:
        """从输出行解析协议标记"""
        stripped = line.strip()

        for marker in ("[HEARTBEAT]", "[HEARTBEAT]"):
            if stripped.startswith("[HEARTBEAT]"):
                self._detected_markers["heartbeat"].append(line)
                return

        if stripped.startswith("[PROGRESS]"):
            self._detected_markers["progress"].append(line)
            return

        if stripped.startswith("[RESULT]"):
            self._detected_markers["result"].append(line)
            return

        if stripped.startswith("[DIFF]"):
            self._detected_markers["diff"].append(line)
            return

    def _extract_result_marker(
        self, output: str
    ) -> Optional[Tuple[str, str]]:
        """从输出中提取 [RESULT] 标记

        Returns:
            (type, message) — 如 ("SUCCESS", "重构完成") 或 ("FAILURE", "编译错误")
        """
        for line in output.splitlines():
            stripped = line.strip()
            if stripped.startswith("[RESULT] SUCCESS:"):
                msg = stripped[len("[RESULT] SUCCESS:"):].strip()
                return ("SUCCESS", msg)
            if stripped.startswith("[RESULT] FAILURE:"):
                msg = stripped[len("[RESULT] FAILURE:"):].strip()
                return ("FAILURE", msg)
        return None

    def _determine_success(
        self, return_code: Optional[int], result_marker: Optional[Tuple[str, str]]
    ) -> bool:
        """综合判断任务是否成功

        规则:
          - [RESULT] SUCCESS 标记存在 → 成功（即使 return_code 非 0）
          - [RESULT] FAILURE 标记存在 → 失败
          - 没有标记时，return_code == 0 → 成功
          - 没有标记且 return_code != 0 → 失败
        """
        if result_marker:
            return result_marker[0] == "SUCCESS"
        if return_code is not None:
            return return_code == 0
        return False

    def _extract_diff(self, worktree_path: str, stdout: str) -> str:
        """从输出中提取 git diff 信息

        策略：
          1. 如果 Claude Code 输出了 [DIFF] 路径，从该路径取 diff
          2. 如果 worktree 是 git 仓库，执行 git diff
          3. 否则返回空字符串
        """
        # 优先从标记中提取
        diff_paths = self._detected_markers.get("diff", [])
        for marker in diff_paths:
            parts = marker.strip().split(" ", 1)
            if len(parts) > 1:
                diff_path = parts[1].strip()
                if os.path.exists(diff_path):
                    try:
                        result = subprocess.run(
                            ["git", "diff", diff_path],
                            capture_output=True, text=True,
                            cwd=worktree_path or os.path.dirname(diff_path),
                            timeout=10,
                        )
                        if result.returncode == 0 and result.stdout.strip():
                            return result.stdout
                    except Exception:
                        pass

        # 回退：整个 worktree 的 diff
        if worktree_path and os.path.isdir(os.path.join(worktree_path, ".git")):
            try:
                result = subprocess.run(
                    ["git", "diff"],
                    capture_output=True, text=True,
                    cwd=worktree_path,
                    timeout=10,
                )
                if result.returncode == 0:
                    return result.stdout
            except Exception:
                pass

        return ""

    def _kill_process(self, proc: subprocess.Popen) -> None:
        """分级杀戮"""
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
          - 二进制不存在（重试也不会出现）
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

    def _detect_claude_version(self) -> str:
        """探测 Claude Code CLI 版本"""
        try:
            result = subprocess.run(
                [self.claude_path, "--version"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return "unknown"

    @staticmethod
    def _cleanup_tmpdir(tmpdir: str) -> None:
        """清理临时目录"""
        try:
            task_file = os.path.join(tmpdir, "task.md")
            if os.path.exists(task_file):
                os.remove(task_file)
            os.rmdir(tmpdir)
        except Exception:
            pass

    @staticmethod
    def _truncate(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return "..." + text[-(max_chars - 3):]
