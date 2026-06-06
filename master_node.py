"""
A2A-CyClone Master Node — Deterministic Master Scheduler
主控调度器参考实现

v0.2.0 重构：
  - 使用 BusManager 替代直接文件 I/O
  - 集成动态 AID 分配与多主控注册
  - 集成租约看门狗 (LeaseWatcher) 与级联销毁处理器 (TeardownHandler)
  - 集成全局账本 (LedgerWriter) 审计记录
  - 支持递归子总线创建与监控
  - 支持失败传播协议的 GLOBAL_FATAL 级联击穿

用法：
  python master_node.py [--aid master-001] [--bus-file cacp_bus.json]
"""

import sys
import time
import argparse

from a2a_cyclone.protocol.enums import BusState
from a2a_cyclone.protocol.aid_pool import build_aid, AgentRole, validate_aid_format
from a2a_cyclone.protocol.bus_topology import LeaseSchedule
from a2a_cyclone.runtime.bus_manager import BusManager
from a2a_cyclone.runtime.lease_watcher import LeaseWatcher
from a2a_cyclone.runtime.teardown_handler import TeardownHandler
from a2a_cyclone.runtime.ledger_writer import LedgerWriter


def parse_args():
    parser = argparse.ArgumentParser(
        description="A2A-Cyclone Master Node (v0.2.0)"
    )
    parser.add_argument(
        "--aid", default="master-001",
        help="Agent ID for this master node (default: master-001)"
    )
    parser.add_argument(
        "--bus-file", default="cacp_bus.json",
        help="Bus file path (default: cacp_bus.json)"
    )
    parser.add_argument(
        "--target", default="slave-002",
        help="Target slave AID (default: slave-002)"
    )
    parser.add_argument(
        "--ledger-file", default="cacp_ledger.jsonl",
        help="Ledger file path (default: cacp_ledger.jsonl)"
    )
    parser.add_argument(
        "--sub-bus", action="store_true",
        help="Enable recursive sub-bus simulation"
    )
    return parser.parse_args()


def master_main():
    args = parse_args()

    MY_AID = args.aid
    BUS_FILE = args.bus_file
    TARGET_AID = args.target
    LEDGER_FILE = args.ledger_file
    ENABLE_SUB_BUS = args.sub_bus

    # ---- 启动初始化 ----
    print(f"\n{'='*60}")
    print(f"  A2A-Cyclone Master Node v0.2.0")
    print(f"  AID: {MY_AID}  |  Bus: {BUS_FILE}")
    print(f"  Target: {TARGET_AID}")
    print(f"{'='*60}\n")

    # 校验 AID 格式
    validate_aid_format(MY_AID)

    # 初始化 Runtime 组件
    bus_manager = BusManager(BUS_FILE, bus_id="root-bus-0")
    lease_watcher = LeaseWatcher(
        heartbeat_interval_ms=1000,
        max_missed_heartbeats=3,
        trunk_grace_multiplier=2.0,
    )
    teardown_handler = TeardownHandler()

    # 初始化全局账本
    ledger = LedgerWriter(LEDGER_FILE)
    bus_manager.bind_ledger(ledger)

    # 初始化总线（若已存在终端态总线，先重置为 000）
    existing = bus_manager.atomic_read()
    if existing is not None:
        current_status = existing.get("status", "000")
        if current_status in ("100", "103"):
            print(f"[{MY_AID}] 检测到上轮残留总线 (status: {current_status})，"
                  f"正在重置为 000...")
            bus_manager.force_transition(
                BusState.UNINITIALIZED, MY_AID,
                reason="Reset stale bus from previous session",
            )
    else:
        bus_manager.initialize_bus(aid=MY_AID, parent_bus_id=None)

    # ---- 阶段 1: 发起握手 (001) ----
    print(f"[{MY_AID}] 发起寻呼 (status: 001), 等待从控 ACK...")
    bus_manager.transition(
        next_state=BusState.PROBE,
        actor_aid=MY_AID,
        payload_updates={
            "Aid": MY_AID,
            "Target_Aid": TARGET_AID,
            "Request": "Connect/ctrl/",
            "content": "Handshake_Request",
            "Token_Holder": MY_AID,
        },
    )

    # ---- 阶段 2: 等待从控 ACK (002) ----
    handshake_success = False
    for _ in range(20):  # 最多等 10 秒
        time.sleep(0.5)
        bus_data = bus_manager.atomic_read()
        if bus_data is None:
            continue

        if bus_data.get("status") == "002" and bus_data.get("Target_Aid") == MY_AID:
            print(f"[{MY_AID}] 收到从控 {bus_data.get('Aid')} 的 ACK (002)...")

            # ---- 阶段 3: 锁定从控角色 (101) ----
            print(f"[{MY_AID}] 下发角色锚定指令 (101)...")
            bus_data = bus_manager.transition(
                next_state=BusState.SLAVE_PASSIVE,
                actor_aid=MY_AID,
                payload_updates={
                    "Target_Aid": bus_data.get("Aid"),
                    "Token_Holder": MY_AID,
                },
            )
            handshake_success = True
            break

    if not handshake_success:
        print(f"[{MY_AID}] 握手超时，回归 000。")
        bus_manager.force_transition(
            BusState.UNINITIALIZED, MY_AID,
            reason="Handshake timeout",
        )
        print(f"\n[{MY_AID}] 物理执行链条已闭环（握手失败）。")
        input(">>> 按 <Enter> 回车键退出主控终端... <<<")
        return

    # ---- 阶段 4: 下发业务指令 (102) ----
    time.sleep(0.5)
    print(f"[{MY_AID}] 从控角色已锁定，下发编译业务指令 (102)...")
    task_payload = "Keil_Build" if not ENABLE_SUB_BUS else "Keil_Build_SubBus"
    bus_data = bus_manager.transition(
        next_state=BusState.ACTIVE_CONTROL,
        actor_aid=MY_AID,
        payload_updates={
            "Request": "Task/exec/",
            "content": task_payload,
            "Token_Holder": MY_AID,
        },
    )

    # 注册租约监控
    lease_watcher.register(BUS_FILE)

    # ---- 阶段 5: 递归子总线模拟 (可选) ----
    sub_bus_managers = {}
    if ENABLE_SUB_BUS:
        print(f"\n[{MY_AID}] === 递归子总线模拟 (v0.2.0) ===")
        SUB_BUS_FILE = "cacp_sub_bus.json"

        # 在父总线上注册子总线
        bus_data = bus_manager.atomic_read()
        if bus_data:
            bus_data["Child_Buses"] = [SUB_BUS_FILE]
            bus_manager.atomic_write(bus_data)

        # 创建子总线的 BusManager
        sub_manager = BusManager(SUB_BUS_FILE, bus_id="sub-bus-1")
        sub_manager.bind_ledger(ledger)
        sub_manager.initialize_bus(
            aid=TARGET_AID,
            parent_bus_id=BUS_FILE,
        )
        sub_bus_managers[SUB_BUS_FILE] = sub_manager
        print(f"[{MY_AID}] 子总线已创建: {SUB_BUS_FILE} (parent: {BUS_FILE})")

        # 模拟子总线上的任务执行
        sub_manager.transition(
            next_state=BusState.PROBE,
            actor_aid=MY_AID,
            payload_updates={
                "Aid": MY_AID,
                "Target_Aid": TARGET_AID,
                "Request": "Connect/ctrl/",
                "content": "Sub_Bus_Handshake",
                "Token_Holder": MY_AID,
            },
        )
        print(f"[{MY_AID}] 子总线握手完成，模拟执行中...")

    # ---- 阶段 6: 监控执行链路 ----
    print(f"\n[{MY_AID}] 开始监控执行链路...")
    for i in range(20):
        time.sleep(1.0)
        bus_data = bus_manager.atomic_read()
        if bus_data is None:
            continue

        status = bus_data.get("status")
        lease_val = bus_data.get("Lease_Extension", 0)

        if status == "102":
            pass  # 等待从控开始执行
        elif status == "202":
            print(f"[{MY_AID}] 收到续租心跳 (202), Lease={lease_val}")
            lease_watcher.heartbeat_received(BUS_FILE, lease_val)

            # 检查租约（主干节点宽限期）
            is_trunk = ENABLE_SUB_BUS
            if not lease_watcher.check_lease(BUS_FILE, is_trunk_node=is_trunk):
                print(f"[{MY_AID}] 【Warning】从控租约超时！触发级联销毁...")
                # 执行级联销毁
                topology = {
                    BUS_FILE: {"token_holder": TARGET_AID},
                }
                if ENABLE_SUB_BUS:
                    topology["cacp_sub_bus.json"] = {"token_holder": TARGET_AID}

                results = teardown_handler.handle_agent_lost(
                    lost_agent_id=TARGET_AID,
                    parent_bus_data=bus_data,
                    child_bus_managers=sub_bus_managers,
                    bus_topology=topology,
                )
                for r in results:
                    print(f"  [Teardown] {r['bus_id']}: {r['status']}")
                break

        elif status == "100":
            print(f"[{MY_AID}] 任务圆满完成 (100)！返回结果: {bus_data.get('content')}")
            break
        elif status == "103":
            print(f"[{MY_AID}] 【Error】任务执行失败 (103): {bus_data.get('content')}")

            # v0.2.0: 失败传播 — 检查是否需要级联击穿
            from a2a_cyclone.protocol.failure_propagation import (
                FailureSignal,
                FailureCategory,
                CriticalityMask,
            )
            signal = FailureSignal(
                category=FailureCategory.TRANSIENT_TIMEOUT,
                source_bus_id=BUS_FILE,
                source_agent_id=TARGET_AID,
                error_code="103",
                error_message=bus_data.get("content", "Unknown error"),
                criticality=CriticalityMask.GLOBAL_FATAL if ENABLE_SUB_BUS
                else CriticalityMask.LOCAL_RETRYABLE,
            )

            if signal.should_escalate():
                print(f"[{MY_AID}] 【级联击穿】GLOBAL_FATAL 异常向上传播！")
                cascaded = teardown_handler.handle_cascading_failure(
                    signal=signal,
                    parent_bus_data=bus_data,
                    child_bus_managers=sub_bus_managers,
                    bus_topology={},
                )
                if cascaded:
                    print(f"  [Cascade] → {cascaded.error_message}")
            break

    # ---- 阶段 7: 清理子总线 ----
    if ENABLE_SUB_BUS:
        print(f"\n[{MY_AID}] 级联销毁子总线...")
        for bus_path, sub_mgr in sub_bus_managers.items():
            try:
                sub_mgr.force_transition(
                    BusState.UNINITIALIZED,
                    MY_AID,
                    reason="Parent bus teardown",
                )
                print(f"  [{bus_path}] → 000 (已销毁)")
            except Exception as exc:
                print(f"  [{bus_path}] 销毁失败: {exc}")

    # ---- 阶段 8: 显示审计信息 ----
    print(f"\n[{MY_AID}] === 全局账本审计 ===")
    print(f"  事件总数: {ledger.get_entry_count()}")
    last_entry = ledger.get_last_entry()
    if last_entry:
        print(f"  最后事件: [{last_entry.event_type}] {last_entry.payload}")
    print(f"  账本文件: {LEDGER_FILE}")

    print(f"\n[{MY_AID}] 当前物理执行链条已闭环。")
    input(">>> 按 <Enter> 回车键退出主控终端... <<<")


if __name__ == "__main__":
    master_main()
