"""
A2A-Cyclone Adapter Layer: 适配器注册表
=======================================

AdapterRegistry 是 Master 编排器管理多个执行器实例的核心设施。
它维护 bus_id → SlaveAdapter 的映射，支持注册、注销、按能力查询。

设计特性：
  - 线程安全（使用 threading.Lock），支持并行调度场景
  - 按能力筛选（list_by_capability），Master 可根据任务类型自动路由
  - 容量上限校验（max_adapters），防止资源耗尽
"""

import threading
from typing import Dict, List, Optional, Callable
from .base import SlaveAdapter


class AdapterRegistry:
    """适配器注册表 — 管理多个 SlaveAdapter 实例

    Master 编排器通过注册表查询可用的执行器，
    并根据任务需求和执行器能力做路由决策。
    """

    def __init__(self, max_adapters: int = 64):
        self._adapters: Dict[str, SlaveAdapter] = {}
        self._lock = threading.Lock()
        self._max_adapters = max_adapters

    # ---- 注册 / 注销 ----

    def register(self, bus_id: str, adapter: SlaveAdapter) -> bool:
        """注册一个适配器实例

        Args:
            bus_id: 该适配器在总线树中对应的总线标识
            adapter: 适配器实例

        Returns:
            True 注册成功，False 已达容量上限或 bus_id 已存在
        """
        with self._lock:
            if len(self._adapters) >= self._max_adapters:
                return False
            if bus_id in self._adapters:
                return False
            self._adapters[bus_id] = adapter
            return True

    def unregister(self, bus_id: str) -> bool:
        """注销一个适配器实例

        Args:
            bus_id: 要注销的总线标识

        Returns:
            True 注销成功，False bus_id 不存在
        """
        with self._lock:
            if bus_id not in self._adapters:
                return False
            # 如果适配器正在执行任务，先终止
            adapter = self._adapters[bus_id]
            if adapter.get_status() not in ("IDLE", "COMPLETED"):
                adapter.cancel()
            del self._adapters[bus_id]
            return True

    def get(self, bus_id: str) -> Optional[SlaveAdapter]:
        """按 bus_id 获取适配器实例"""
        with self._lock:
            return self._adapters.get(bus_id)

    # ---- 查询 ----

    def list_adapters(self) -> Dict[str, SlaveAdapter]:
        """返回当前所有注册的适配器快照

        Returns:
            {bus_id: SlaveAdapter} 的拷贝，外部修改不影响注册表
        """
        with self._lock:
            return dict(self._adapters)

    def list_idle(self) -> List[str]:
        """返回所有空闲适配器的 bus_id 列表

        用于 Master 调度器快速选择可用的执行器。
        """
        with self._lock:
            return [
                bid for bid, ada in self._adapters.items()
                if ada.get_status().value == "IDLE"
            ]

    def list_by_capability(
        self,
        capability_filter: Callable[[Dict], bool],
    ) -> List[str]:
        """按能力筛选适配器

        Args:
            capability_filter: 回调函数，接收 get_capabilities() 的结果，
                               返回 True 表示符合要求

        Returns:
            符合条件的适配器 bus_id 列表

        示例:
            # 找到所有支持 make 编译的适配器
            registry.list_by_capability(
                lambda cap: "make" in cap.get("supported_commands", [])
            )
        """
        with self._lock:
            results = []
            for bid, ada in self._adapters.items():
                try:
                    caps = ada.get_capabilities()
                    if capability_filter(caps):
                        results.append(bid)
                except Exception:
                    # 能力查询失败跳过该适配器
                    continue
            return results

    def count(self) -> int:
        """返回当前注册的适配器数量"""
        with self._lock:
            return len(self._adapters)

    def clear(self) -> None:
        """清空所有注册的适配器（用于测试和系统重置）"""
        with self._lock:
            for ada in self._adapters.values():
                try:
                    if ada.get_status() not in ("IDLE", "COMPLETED"):
                        ada.cancel()
                except Exception:
                    pass
            self._adapters.clear()
