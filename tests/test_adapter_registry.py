"""
A2A-Cyclone Adapter Layer 单元测试 — 适配器注册表
==================================================

测试范围:
  - register / unregister 功能
  - 容量上限
  - list_idle / list_by_capability 查询
  - 并发安全
  - 边界条件（重复注册、不存在的注销、清空）
"""

import pytest
import threading
from a2a_cyclone.adapter.base import SlaveAdapter, SlaveStatus, TaskPackage, TaskResult
from a2a_cyclone.adapter.registry import AdapterRegistry


# 辅助：一个简单的 DummyAdapter
class DummyAdapter(SlaveAdapter):
    def __init__(self, status=SlaveStatus.IDLE, capabilities=None):
        self._status = status
        self._caps = capabilities or {"executor_type": "dummy"}

    def execute(self, package):
        return TaskResult(task_id=package.task_id, success=True)

    def get_status(self):
        return self._status

    def cancel(self):
        self._status = SlaveStatus.IDLE
        return True

    def get_capabilities(self):
        return self._caps


# ================================================================
# 注册与注销
# ================================================================

class TestRegistryRegister:
    def test_register_adapter(self):
        registry = AdapterRegistry()
        adapter = DummyAdapter()
        assert registry.register("bus-001", adapter) is True
        assert registry.get("bus-001") is adapter

    def test_register_duplicate_bus_id(self):
        """重复注册同一 bus_id 应返回 False"""
        registry = AdapterRegistry()
        assert registry.register("bus-001", DummyAdapter()) is True
        assert registry.register("bus-001", DummyAdapter()) is False

    def test_register_exceeds_capacity(self):
        """超过容量上限应返回 False"""
        registry = AdapterRegistry(max_adapters=2)
        assert registry.register("bus-001", DummyAdapter()) is True
        assert registry.register("bus-002", DummyAdapter()) is True
        assert registry.register("bus-003", DummyAdapter()) is False

    def test_unregister_existing(self):
        registry = AdapterRegistry()
        adapter = DummyAdapter()
        registry.register("bus-001", adapter)
        assert registry.unregister("bus-001") is True
        assert registry.get("bus-001") is None

    def test_unregister_nonexistent(self):
        """注销不存在的 bus_id 应返回 False"""
        registry = AdapterRegistry()
        assert registry.unregister("bus-999") is False

    def test_unregister_cancels_busy_adapter(self):
        """注销 BUSY 状态的适配器应先 cancel"""
        cancelled = False
        class BusyAdapter(DummyAdapter):
            def cancel(self):
                nonlocal cancelled
                cancelled = True
                return super().cancel()
            def get_status(self):
                return SlaveStatus.BUSY

        registry = AdapterRegistry()
        registry.register("bus-001", BusyAdapter(status=SlaveStatus.BUSY))
        registry.unregister("bus-001")
        assert cancelled is True

    def test_count(self):
        registry = AdapterRegistry()
        assert registry.count() == 0
        registry.register("bus-001", DummyAdapter())
        assert registry.count() == 1
        registry.register("bus-002", DummyAdapter())
        assert registry.count() == 2
        registry.unregister("bus-001")
        assert registry.count() == 1


# ================================================================
# 查询功能
# ================================================================

class TestRegistryQuery:
    def test_list_adapters(self):
        registry = AdapterRegistry()
        a1 = DummyAdapter()
        a2 = DummyAdapter()
        registry.register("bus-001", a1)
        registry.register("bus-002", a2)

        adapters = registry.list_adapters()
        assert len(adapters) == 2
        assert adapters["bus-001"] is a1
        assert adapters["bus-002"] is a2

    def test_list_adapters_is_copy(self):
        """list_adapters 返回的是副本，外部修改不影响注册表"""
        registry = AdapterRegistry()
        registry.register("bus-001", DummyAdapter())
        adapters = registry.list_adapters()
        adapters.clear()
        assert registry.count() == 1

    def test_list_idle(self):
        registry = AdapterRegistry()
        registry.register("bus-idle", DummyAdapter(status=SlaveStatus.IDLE))
        registry.register("bus-busy", DummyAdapter(status=SlaveStatus.BUSY))
        registry.register("bus-idle2", DummyAdapter(status=SlaveStatus.IDLE))

        idle_list = registry.list_idle()
        assert "bus-idle" in idle_list
        assert "bus-busy" not in idle_list
        assert "bus-idle2" in idle_list
        assert len(idle_list) == 2

    def test_list_by_capability(self):
        registry = AdapterRegistry()
        registry.register(
            "bus-make",
            DummyAdapter(capabilities={"executor_type": "shell", "supported_commands": ["make"]}),
        )
        registry.register(
            "bus-python",
            DummyAdapter(capabilities={"executor_type": "shell", "supported_commands": ["python"]}),
        )

        make_adapters = registry.list_by_capability(
            lambda cap: "make" in cap.get("supported_commands", [])
        )
        assert make_adapters == ["bus-make"]

    def test_list_by_capability_skip_error(self):
        """能力查询抛异常的适配器应被跳过"""
        registry = AdapterRegistry()
        registry.register("bus-good", DummyAdapter())

        class BrokenAdapter(SlaveAdapter):
            def execute(self, pkg): ...
            def get_status(self): return SlaveStatus.IDLE
            def cancel(self): return True
            def get_capabilities(self): raise RuntimeError("broken")

        registry.register("bus-broken", BrokenAdapter())

        result = registry.list_by_capability(lambda cap: True)
        assert "bus-good" in result
        assert "bus-broken" not in result


# ================================================================
# 并发安全
# ================================================================

class TestRegistryConcurrency:
    def test_concurrent_registration(self):
        """多线程并发注册不应数据丢失"""
        registry = AdapterRegistry(max_adapters=100)

        def register_thread(bus_id):
            return registry.register(bus_id, DummyAdapter())

        threads = []
        for i in range(50):
            t = threading.Thread(target=register_thread, args=(f"bus-{i:03d}",))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert registry.count() == 50

    def test_concurrent_read_write(self):
        """同时读写不应死锁"""
        registry = AdapterRegistry(max_adapters=100)

        writer = threading.Thread(
            target=lambda: [registry.register(f"bus-{i}", DummyAdapter()) for i in range(30)]
        )
        reader = threading.Thread(
            target=lambda: [registry.list_adapters() for _ in range(100)]
        )

        writer.start()
        reader.start()
        writer.join()
        reader.join()

        # 至少写入了部分
        assert registry.count() > 0


# ================================================================
# 清空操作
# ================================================================

class TestRegistryClear:
    def test_clear_empty(self):
        registry = AdapterRegistry()
        registry.clear()
        assert registry.count() == 0

    def test_clear_with_adapters(self):
        registry = AdapterRegistry()
        registry.register("bus-001", DummyAdapter())
        registry.register("bus-002", DummyAdapter())
        registry.clear()
        assert registry.count() == 0

    def test_clear_cancels_busy(self):
        """clear 时应 cancel 所有 BUSY 适配器"""
        cancelled = []
        class TrackCancel(DummyAdapter):
            def cancel(self):
                cancelled.append(self)
                return True

        registry = AdapterRegistry()
        a1 = TrackCancel(status=SlaveStatus.BUSY)
        a2 = TrackCancel(status=SlaveStatus.IDLE)
        registry.register("bus-busy", a1)
        registry.register("bus-idle", a2)
        registry.clear()

        assert a1 in cancelled  # BUSY 的被 cancel
        assert a2 not in cancelled  # IDLE 的不需要 cancel
        assert registry.count() == 0
