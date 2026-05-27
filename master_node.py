import json
import time
import os

BUS_FILE = "cacp_bus.json"
MY_AID = "ai-master-001"
TARGET_AID = "ai-slave-002"

def atomic_write(data):
    """主控端同样强制执行原子级写入，杜绝总线脏读"""
    temp_file = "temp_master_bus.json"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_file, BUS_FILE)

def master_test():
    # 1. 状态 001: 发起探针握手
    handshake = {
        "status": "001",
        "Aid": MY_AID,
        "Target_Aid": TARGET_AID,
        "Vector_Clock": 1,
        "Request": "Connect/ctrl/",
        "content": "Handshake_Request",
        "Lease_Extension": 0
    }

    print(f"[{MY_AID}] 发起寻呼 (status: 001), 等待从控 ACK...")
    atomic_write(handshake)

    # 阶段一：等待从控 002 确认
    handshake_success = False
    while True:
        time.sleep(0.5)
        if not os.path.exists(BUS_FILE):
            continue
        try:
            with open(BUS_FILE, "r", encoding="utf-8") as f:
                bus = json.load(f)
        except Exception:
            continue
            
        # 2. 检测到 002: 握手确认
        if bus.get("status") == "002" and bus.get("Target_Aid") == MY_AID:
            print(f"[{MY_AID}] 收到从控 {bus.get('Aid')} 的 ACK (002)...")
            
            # 3. 状态 101: 锁定从控角色
            print(f"[{MY_AID}] 下发角色锚定指令 (101)...")
            bus["status"] = "101"
            bus["Target_Aid"] = bus.get("Aid") # 指向具体从控
            bus["Vector_Clock"] += 1
            atomic_write(bus)
            handshake_success = True
            break
            
    if not handshake_success:
        return

    # 阶段二：下发任务指令
    time.sleep(0.5) # 留出物理间隔让从控感知 101
    print(f"[{MY_AID}] 从控角色已锁定，下发编译业务指令 (102)...")
    bus["status"] = "102"
    bus["Request"] = "Task/exec/"
    bus["content"] = "Keil_Build"
    bus["Vector_Clock"] += 1
    atomic_write(bus)

    # 阶段三：监控物理层状态流转 (202 / 100 / 103)
    print(f"[{MY_AID}] 开始监控执行链路...")
    for _ in range(20):
        time.sleep(1.0)
        try:
            with open(BUS_FILE, "r", encoding="utf-8") as f:
                bus = json.load(f)
        except Exception:
            continue
            
        status = bus.get("status")
        if status == "102":
            pass
        elif status == "202":
            print(f"[{MY_AID}] 收到续租心跳 (202), Lease={bus.get('Lease_Extension')}")
        elif status == "100":
            print(f"[{MY_AID}] 任务圆满完成 (100)！返回结果: {bus.get('content')}")
            break
        elif status == "103":
            print(f"[{MY_AID}] 【Error】任务执行失败 (103): {bus.get('content')}")
            break
            
    # ==========================================
    # 核心修改点：注入 IO 中断阻塞，防止命令行闪退
    # ==========================================
    print(f"\n[{MY_AID}] 当前物理执行链条已闭环。")
    input(">>> 按 <Enter> 回车键退出主控终端... <<<")

if __name__ == "__main__":
    master_test()