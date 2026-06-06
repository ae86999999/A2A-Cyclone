"""
A2A-CyClone Slave Node — Agent Watchdog & Lease Emulator
从控执行节点参考实现

v0.2.0 重构：
  - 使用 BusManager 替代直接文件 I/O
  - 集成动态 AID 分配
  - 支持主干节点（Trunk Node）角色识别与宽限期
  - 支持子总线感知与失败信号生成
  - 模拟租约竞争条件缓解（Trunk Node Grace Period）

用法：
  python slave_node.py [--aid slave-002] [--bus-file cacp_bus.json]
                       [--sub-bus-file cacp_sub_bus.json]
"""

import sys
import time
import argparse

from a2a_cyclone.protocol.enums import BusState
from a2a_cyclone.protocol.aid_pool import validate_aid_format
from a2a_cyclone.runtime.bus_manager import BusManager


def parse_args():
    parser = argparse.ArgumentParser(
        description="A2A-Cyclone Slave Node (v0.2.0)"
    )
    parser.add_argument(
        "--aid", default="slave-002",
        help="Agent ID for this slave node (default: slave-002)"
    )
    parser.add_argument(
        "--bus-file", default="cacp_bus.json",
        help="Bus file path (default: cacp_bus.json)"
    )
    parser.add_argument(
        "--sub-bus-file", default="",
        help="Optional sub-bus file path for trunk node simulation"
    )
    return parser.parse_args()


def slave_main():
    args = parse_args()

    MY_AID = args.aid
    BUS_FILE = args.bus_file
    SUB_BUS_FILE = args.sub_bus_file

    # 判断是否为主干节点（同时管理子总线）
    IS_TRUNK_NODE = bool(SUB_BUS_FILE)

    print(f"\n{'='*60}")
    print(f"  A2A-Cyclone Slave Node v0.2.0")
    print(f"  AID: {MY_AID}  |  Bus: {BUS_FILE}")
    if IS_TRUNK_NODE:
        print(f"  Role: TRUNK NODE (子总线: {SUB_BUS_FILE})")
    print(f"{'='*60}\n")

    # 校验 AID 格式
    validate_aid_format(MY_AID)

    # 初始化 Runtime 组件
    bus_manager = BusManager(BUS_FILE, bus_id="root-bus-0")

    # 若为主干节点，初始化子总线管理器
    sub_bus_manager = None
    if IS_TRUNK_NODE:
        sub_bus_manager = BusManager(SUB_BUS_FILE, bus_id="sub-bus-1")

    print(f"[{MY_AID}] A2A-Cyclone 物理状态机拉起，等待主控寻呼...")

    # 执行状态标记
    task_in_progress = False
    heartbeat_count = 0

    while True:
        time.sleep(0.5)

        # ---- 检查父总线 ----
        bus_data = bus_manager.atomic_read()
        if bus_data is None:
            continue

        # 过滤非目标消息
        target = bus_data.get("Target_Aid", "")
        if target != MY_AID and target != "*":
            continue

        current_status = bus_data.get("status")
        request = bus_data.get("Request", "")

        # ============ 判定 1: 收到寻呼 (001) -> 回复 ACK (002) ============
        if current_status == "001" and request == "Connect/ctrl/":
            print(f"[{MY_AID}] 收到主控 {bus_data.get('Aid')} 探针，发出确认 ACK (002)...")

            bus_data["status"] = "002"
            bus_data["Target_Aid"] = bus_data.get("Aid")
            bus_data["Aid"] = MY_AID
            bus_data["Token_Holder"] = ""  # 握手阶段暂不设令牌持有者
            bus_data["Vector_Clock"] = bus_data.get("Vector_Clock", 0) + 1
            bus_manager.atomic_write(bus_data)

        # ============ 判定 2: 角色被锁定 (101) -> 等待指令 ============
        elif current_status == "101":
            if not task_in_progress:
                print(f"[{MY_AID}] 主控已确认角色锁定 (101)，等待业务指令下发...")

        # ============ 判定 3: 收到执行指令 (102) -> 续租 + 执行 ============
        elif current_status == "102" and request == "Task/exec/":
            task_content = bus_data.get("content", "")
            print(f"[{MY_AID}] 接收到业务指令: {task_content}，锁死总线启动执行...")

            token_holder = bus_data.get("Token_Holder", "")
            if token_holder != MY_AID and token_holder != bus_data.get("Aid", ""):
                print(f"[{MY_AID}] 【Warning】Token_Holder 不匹配"
                      f"(expected {MY_AID}, got {token_holder})")

            task_in_progress = True
            heartbeat_count = 0

            # ---- 子总线感知：若为主干节点，同步管理子总线 ----
            if IS_TRUNK_NODE and sub_bus_manager:
                print(f"[{MY_AID}] [Trunk] 初始化子总线 {SUB_BUS_FILE}...")
                sub_bus_manager.initialize_bus(
                    aid=MY_AID,
                    parent_bus_id=BUS_FILE,
                )

            # ---- 模拟物理耗时与续租 ----
            for i in range(3):
                time.sleep(1.5)

                # v0.2.0: 主干节点在执行续租前，先处理子总线心跳
                if IS_TRUNK_NODE and sub_bus_manager:
                    sub_data = sub_bus_manager.atomic_read()
                    if sub_data:
                        print(f"[{MY_AID}] [Trunk] 子总线状态: {sub_data.get('status')}")
                        # 模拟子总线收集——这期间父总线的心跳间隔被拉长
                        # 父总线由于 trunk_grace_multiplier=2.0 获得额外宽限
                        time.sleep(0.2)  # 模拟子总线 I/O 延迟

                # 向父总线发送续租心跳 (202)
                bus_data = bus_manager.atomic_read()
                if bus_data is None:
                    continue

                bus_data["status"] = "202"
                bus_data["Lease_Extension"] = bus_data.get("Lease_Extension", 0) + 1
                bus_data["Vector_Clock"] = bus_data.get("Vector_Clock", 0) + 1
                bus_data["Token_Holder"] = MY_AID
                bus_manager.atomic_write(bus_data)

                heartbeat_count += 1
                trunk_tag = "[Trunk] " if IS_TRUNK_NODE else ""
                print(f"[{MY_AID}] {trunk_tag}任务执行中，发送续租心跳"
                      f"(202) #{heartbeat_count}...")

            # ---- 任务完成，释放 (100) ----
            bus_data = bus_manager.atomic_read()
            if bus_data is None:
                continue

            print(f"[{MY_AID}] 物理动作完成，释放状态机至 100")
            bus_data["status"] = "100"
            bus_data["Lease_Extension"] = 0
            bus_data["content"] = "Success: 0 Error(s)"
            bus_data["Vector_Clock"] = bus_data.get("Vector_Clock", 0) + 1
            bus_data["Token_Holder"] = ""
            bus_manager.atomic_write(bus_data)

            # ---- 清理子总线 ----
            if IS_TRUNK_NODE and sub_bus_manager:
                print(f"[{MY_AID}] [Trunk] 级联释放子总线...")
                try:
                    sub_bus_manager.force_transition(
                        BusState.UNINITIALIZED,
                        MY_AID,
                        reason="Task completed, parent bus released",
                    )
                    print(f"[{MY_AID}] [Trunk] 子总线已回归 000")
                except Exception as exc:
                    print(f"[{MY_AID}] [Trunk] 子总线释放异常: {exc}")

            task_in_progress = False

        # ============ 判定 4: 任务被强制终止 (级联销毁) ============
        elif current_status == "103" and task_in_progress:
            force_reset = bus_data.get("force_reset", False)
            if force_reset:
                print(f"[{MY_AID}] 【级联销毁】被 {bus_data.get('force_reset_by')}"
                      f" 强制终止: {bus_data.get('force_reset_reason')}")
                task_in_progress = False


if __name__ == "__main__":
    slave_main()
