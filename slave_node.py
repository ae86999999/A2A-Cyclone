import os
import time
import json

BUS_FILE = "cacp_bus.json"
MY_AID = "ai-slave-002"

def atomic_write(data):
    """基于第一性原理的原子级重命名写入，彻底干掉文件脏读"""
    temp_file = "temp_slave_bus.json"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_file, BUS_FILE)

def run_slave_loop():
    print(f"[{MY_AID}] A2A-Cyclone 物理状态机拉起，等待主控寻呼...")
    
    while True:
        time.sleep(0.5) 
        
        if not os.path.exists(BUS_FILE):
            continue
            
        try:
            with open(BUS_FILE, "r", encoding="utf-8") as f:
                bus = json.load(f)
        except (json.JSONDecodeError, PermissionError):
            continue 
            
        if bus.get("Target_Aid") != MY_AID and bus.get("Target_Aid") != "*":
            continue
            
        current_status = bus.get("status")
        
        # 判定 1：收到寻呼 (001) -> 回复确认 (002)
        if current_status == "001" and bus.get("Request") == "Connect/ctrl/":
            print(f"[{MY_AID}] 收到主控 {bus.get('Aid')} 探针，发出确认 ACK (002)...")
            bus["status"] = "002"
            bus["Target_Aid"] = bus.get("Aid")
            bus["Aid"] = MY_AID
            bus["Vector_Clock"] += 1
            atomic_write(bus)
            
        # 判定 2：主控锁定角色 (101) -> 保持监听，暂无文件写动作
        elif current_status == "101":
            print(f"[{MY_AID}] 主控已确认角色锁定 (101)，等待业务指令下发...")
            # 101 是单纯被控态，从控只需等待 102 出现，无需修改总线
            
        # 判定 3：收到执行指令 (102) -> 续租执行 (202) -> 完成释放 (100)
        elif current_status == "102" and bus.get("Request") == "Task/exec/":
            print(f"[{MY_AID}] 接收到业务指令: {bus.get('content')}，锁死总线启动执行...")
            
            # 模拟物理耗时与续租
            for i in range(3):
                time.sleep(1.5)
                bus["status"] = "202"
                bus["Lease_Extension"] = bus.get("Lease_Extension", 0) + 1
                bus["Vector_Clock"] += 1
                print(f"[{MY_AID}] 任务执行中，发送续租心跳 (202)...")
                atomic_write(bus)
                
            print(f"[{MY_AID}] 物理动作完成，释放状态机至 100")
            bus["status"] = "100"
            bus["Lease_Extension"] = 0
            bus["content"] = "Success: 0 Error(s)"
            bus["Vector_Clock"] += 1
            atomic_write(bus)

if __name__ == "__main__":
    run_slave_loop()