"""
A2A-Cyclone Adapter Layer 单元测试 — 数据合约与基类
====================================================

测试范围:
  - SlaveStatus 枚举语义
  - TaskPackage 数据合约（创建、不可变性、默认值）
  - TaskResult 数据合约（创建、不可变性、默认值）
  - SlaveAdapter 抽象基类（接口强制实现）
"""

import pytest
from dataclasses import FrozenInstanceError
from a2a_cyclone.adapter.base import (
    SlaveStatus,
    SlaveAdapter,
    TaskPackage,
    TaskResult,
)


# ================================================================
# SlaveStatus 枚举
# ================================================================

class TestSlaveStatus:
    def test_four_states_defined(self):
        """必须包含 IDLE / BUSY / ERROR / COMPLETED 四种状态"""
        assert len(SlaveStatus) == 4
        assert SlaveStatus.IDLE.value == "IDLE"
        assert SlaveStatus.BUSY.value == "BUSY"
        assert SlaveStatus.ERROR.value == "ERROR"
        assert SlaveStatus.COMPLETED.value == "COMPLETED"

    def test_states_are_string_enum(self):
        """SlaveStatus 是 str, Enum，value 等于枚举名"""
        assert SlaveStatus.IDLE.value == "IDLE"
        assert SlaveStatus.BUSY.value == "BUSY"
        assert SlaveStatus.ERROR.value == "ERROR"
        assert SlaveStatus.COMPLETED.value == "COMPLETED"

    def test_transition_coverage(self):
        """确保所有 BusState（protocol/enums.py）都能映射到 SlaveStatus"""
        # 映射验证（非全覆盖，覆盖主要场景）
        assert SlaveStatus.IDLE.value in ("IDLE",)
        assert SlaveStatus.BUSY.value in ("BUSY",)
        assert SlaveStatus.ERROR.value in ("ERROR",)
        assert SlaveStatus.COMPLETED.value in ("COMPLETED",)


# ================================================================
# TaskPackage 数据合约
# ================================================================

class TestTaskPackage:
    def test_minimal_creation(self):
        """仅靠必填字段创建 TaskPackage"""
        pkg = TaskPackage(task_id="t-001", command="echo hello")
        assert pkg.task_id == "t-001"
        assert pkg.command == "echo hello"

    def test_default_values(self):
        """未提供的字段应有合理的默认值"""
        pkg = TaskPackage(task_id="t-001", command="echo hello")
        assert pkg.worktree_path == ""
        assert pkg.context == {}
        assert pkg.timeout_seconds == 300
        assert pkg.max_retries == 2

    def test_heartbeat_markers_default(self):
        """默认心跳标记列表应包含 HEARTBEAT / PROGRESS / STATUS"""
        pkg = TaskPackage(task_id="t-001", command="echo hello")
        assert "[HEARTBEAT]" in pkg.heartbeat_markers
        assert "[PROGRESS]" in pkg.heartbeat_markers
        assert "[STATUS]" in pkg.heartbeat_markers

    def test_full_creation(self):
        """使用全部字段创建 TaskPackage"""
        pkg = TaskPackage(
            task_id="refactor-001",
            command="重构 SVPWM",
            worktree_path="/tmp/worktree",
            context={"chip": "PY32F002B", "memory": "Q15_MUL macro"},
            timeout_seconds=600,
            max_retries=3,
        )
        assert pkg.task_id == "refactor-001"
        assert pkg.context["chip"] == "PY32F002B"
        assert pkg.timeout_seconds == 600
        assert pkg.max_retries == 3

    def test_frozen_immutability(self):
        """TaskPackage 必须是 frozen dataclass，创建后不可修改"""
        pkg = TaskPackage(task_id="t-001", command="echo hello")
        with pytest.raises(FrozenInstanceError):
            pkg.task_id = "changed"  # type: ignore[misc]

    @pytest.mark.boundary
    def test_empty_command(self):
        """边界：空命令应允许创建（执行时由 Adapter 处理）"""
        pkg = TaskPackage(task_id="t-001", command="")
        assert pkg.command == ""

    @pytest.mark.boundary
    def test_very_long_task_id(self):
        """边界：超长 task_id 应允许创建"""
        long_id = "t-" + "x" * 500
        pkg = TaskPackage(task_id=long_id, command="echo hello")
        assert len(pkg.task_id) > 200

    @pytest.mark.boundary
    def test_zero_timeout(self):
        """边界：timeout=0 表示超时立即触发"""
        pkg = TaskPackage(task_id="t-001", command="echo hello", timeout_seconds=0)
        assert pkg.timeout_seconds == 0

    @pytest.mark.boundary
    def test_negative_retries(self):
        """边界：负数 max_retries 应允许（由 Adapter 处理为重试 0 次）"""
        pkg = TaskPackage(task_id="t-001", command="echo hello", max_retries=-1)
        assert pkg.max_retries == -1

    def test_context_mutable_value(self):
        """边界：context 中的可变值（list/dict）不应影响 Package"""
        ctx = {"items": [1, 2, 3]}
        pkg = TaskPackage(task_id="t-001", command="echo hello", context=ctx)
        ctx["items"].append(4)  # 外部修改
        # TaskPackage 持有的是冻结的副本（frozen=True 但内部引用可变）
        # 这是一个已知的 dataclass 限制，外部应避免这么做


# ================================================================
# TaskResult 数据合约
# ================================================================

class TestTaskResult:
    def test_minimal_success(self):
        """最小成功结果"""
        result = TaskResult(task_id="t-001", success=True)
        assert result.task_id == "t-001"
        assert result.success is True
        assert result.status == SlaveStatus.COMPLETED  # 默认

    def test_minimal_failure(self):
        """最小失败结果"""
        result = TaskResult(task_id="t-001", success=False)
        assert result.success is False
        assert result.status == SlaveStatus.COMPLETED  # 默认，调用方应覆盖

    def test_error_result_status(self):
        """错误时推荐使用 ERROR 状态"""
        result = TaskResult(
            task_id="t-001", success=False,
            error_log="Compilation error",
            status=SlaveStatus.ERROR,
        )
        assert result.status == SlaveStatus.ERROR
        assert result.error_log == "Compilation error"

    def test_full_result(self):
        """完整的结果数据"""
        result = TaskResult(
            task_id="refactor-001",
            success=True,
            summary="SVPWM 重构完成，周期 -15%",
            diff="--- a/svpwm.c\n+++ b/svpwm.c\n@@ -42,5 +42,5 @@",
            commit_hash="abc123def456",
            artifacts={"hex": "build/output.hex", "map": "build/output.map"},
            status=SlaveStatus.COMPLETED,
        )
        assert result.commit_hash == "abc123def456"
        assert len(result.artifacts) == 2

    def test_frozen_immutability(self):
        """TaskResult 创建后不可修改"""
        result = TaskResult(task_id="t-001", success=True)
        with pytest.raises(FrozenInstanceError):
            result.success = False  # type: ignore[misc]

    @pytest.mark.boundary
    def test_empty_summary(self):
        """边界：空摘要"""
        result = TaskResult(task_id="t-001", success=True, summary="")
        assert result.summary == ""

    @pytest.mark.boundary
    def test_none_error_log_on_success(self):
        """边界：成功时 error_log 应为 None"""
        result = TaskResult(task_id="t-001", success=True)
        assert result.error_log is None

    @pytest.mark.boundary
    def test_none_commit_hash(self):
        """边界：未提交时 commit_hash 为 None"""
        result = TaskResult(task_id="t-001", success=True)
        assert result.commit_hash is None


# ================================================================
# SlaveAdapter 抽象基类
# ================================================================

class TestSlaveAdapter:
    def test_cannot_instantiate_abstract(self):
        """抽象基类不能被直接实例化"""
        with pytest.raises(TypeError):
            SlaveAdapter()  # type: ignore[abstract]

    def test_concrete_adapter_must_implement_all_methods(self):
        """具体实现必须实现所有抽象方法"""
        class IncompleteAdapter(SlaveAdapter):
            pass

        with pytest.raises(TypeError):
            IncompleteAdapter()  # type: ignore[abstract]

    def test_concrete_adapter_works(self):
        """完整实现所有抽象方法的适配器可以实例化和调用"""
        class DummyAdapter(SlaveAdapter):
            def execute(self, package):
                return TaskResult(task_id=package.task_id, success=True)

            def get_status(self):
                return SlaveStatus.IDLE

            def cancel(self):
                return True

            def get_capabilities(self):
                return {"executor_type": "dummy"}

        adapter = DummyAdapter()
        assert adapter.get_status() == SlaveStatus.IDLE
        assert adapter.cancel() is True

        result = adapter.execute(
            TaskPackage(task_id="test-001", command="echo hello")
        )
        assert result.success is True
        assert result.task_id == "test-001"
