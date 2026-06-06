"""
A2A-CyClone Runtime Layer: 账本写入器 (Ledger Writer)
负责将 Protocol 层定义的 LedgerEntry 以 append-only JSONL 格式持久化。

采用 JSONL（每行一个 JSON 对象）格式：
  - 追加写入，绝不修改已有记录
  - 每行独立可解析（支持流式审计）
  - 原子性：每行写入后立即 fsync
"""

import json
import os
from typing import List, Optional

from ..protocol.ledger import LedgerEntry, assert_ledger_invariants


class LedgerWriter:
    """全局账本写入器

    以 append-only JSONL 格式持久化所有系统事件。
    每条事件为一行完整 JSON，永不修改或删除。
    """

    def __init__(self, ledger_file_path: str):
        self.ledger_file_path = ledger_file_path
        self._entries: List[LedgerEntry] = []
        self._sequence_number = 0

    def append(self, entry: LedgerEntry) -> None:
        """追加一条事件到账本

        操作顺序：
          1. 内存中记录（用于不变量校验）
          2. 追加写入 JSONL 文件
          3. 序列号递增
        """
        # 写入内存
        self._entries.append(entry)
        self._sequence_number += 1

        # 追加写入文件
        line = json.dumps(
            {
                "event_id": entry.event_id,
                "event_type": entry.event_type.value,
                "bus_id": entry.bus_id,
                "agent_id": entry.agent_id,
                "timestamp_iso": entry.timestamp_iso,
                "vector_clock": entry.vector_clock,
                "payload": entry.payload,
                "parent_event_id": entry.parent_event_id,
                "correlation_id": entry.correlation_id,
                "sequence": self._sequence_number,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with open(self.ledger_file_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())

    def read_all(self) -> List[LedgerEntry]:
        """读取账本中的全部事件

        从 JSONL 文件逐行解析，用于崩溃恢复后的状态重建。
        """
        entries = []
        if not os.path.exists(self.ledger_file_path):
            return entries

        with open(self.ledger_file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                    entry = LedgerEntry(
                        event_id=raw["event_id"],
                        event_type=raw["event_type"],
                        bus_id=raw["bus_id"],
                        agent_id=raw["agent_id"],
                        timestamp_iso=raw["timestamp_iso"],
                        vector_clock=raw["vector_clock"],
                        payload=raw.get("payload", {}),
                        parent_event_id=raw.get("parent_event_id"),
                        correlation_id=raw.get("correlation_id"),
                    )
                    entries.append(entry)
                except (json.JSONDecodeError, KeyError):
                    continue  # 跳过损坏的行

        self._entries = entries
        self._sequence_number = len(entries)
        return entries

    def validate(self) -> bool:
        """校验当前账本是否符合所有不变量"""
        return assert_ledger_invariants(self._entries)

    def get_entry_count(self) -> int:
        """返回已记录事件数"""
        return len(self._entries)

    def get_last_entry(self) -> Optional[LedgerEntry]:
        """返回最近一条事件"""
        if not self._entries:
            return None
        return self._entries[-1]

    def clear(self) -> None:
        """清除账本（仅用于测试环境重置）"""
        self._entries.clear()
        self._sequence_number = 0
        if os.path.exists(self.ledger_file_path):
            os.remove(self.ledger_file_path)
