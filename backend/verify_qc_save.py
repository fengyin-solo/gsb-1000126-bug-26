"""质控样品保存链路验证：版本冲突、幂等重试、字段白名单、列表与详情一致性。

只依赖服务层与内存仓库（纯标准库），不启动 HTTP 服务。
运行：python3 backend/verify_qc_save.py
"""
from __future__ import annotations

import sys
import threading

sys.path.insert(0, "backend")

from app.services.qc import QcService  # noqa: E402
from app.store import store  # noqa: E402

service = QcService()
failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  -- {detail}" if not cond and detail else ""))
    if not cond:
        failures.append(name)


# 准备一条记录
entry, missing = service.create_entry({"质控编号": "QC-T001", "质控类别": "空白加标", "标准值": "10.0"})
check("登记成功", entry is not None and not missing)
eid = entry["id"]
check("登记后版本为 1", entry.get("version") == 1)

# 1. 正常保存：按字段名写回，版本推进，列表与详情读到同一份记录
saved, msg, status = service.update_entry(
    eid,
    {"质控编号": "QC-T001", "质控类别": "平行样", "标准值": "10.0", "实测值": "9.8", "判定结果": "受控"},
    base_version=1,
    request_id="req-1",
)
check("保存返回 200", status == 200, msg)
check("保存后版本推进到 2", saved.get("version") == 2)
check("质控类别写回不错位", saved.get("质控类别") == "平行样" and saved.get("质控编号") == "QC-T001")
detail = service.get_entry(eid)
list_row = next(r for r in store.rows("qc") if r["id"] == eid)
check("详情与列表是同一份记录", detail == dict(list_row) and detail.get("实测值") == "9.8")

# 2. 重复提交：同一个 request_id 重试，不重复执行、版本不再推进
replay, msg, status = service.update_entry(
    eid,
    {"质控编号": "QC-T001", "质控类别": "平行样", "标准值": "10.0", "实测值": "9.8", "判定结果": "受控"},
    base_version=1,
    request_id="req-1",
)
check("幂等重试返回原结果", status == 200 and replay.get("version") == 2, f"version={replay.get('version')}")
check("幂等重试后记录未变", service.get_entry(eid).get("version") == 2)

# 3. 保存冲突：旧版本保存返回 409，原记录不被覆盖
conflict, msg, status = service.update_entry(
    eid, {"质控编号": "QC-T001", "质控类别": "他人篡改", "标准值": "0.0"}, base_version=1, request_id="req-2",
)
check("旧版本保存返回 409", status == 409, f"status={status}")
check("冲突时带回当前权威记录", conflict.get("version") == 2 and conflict.get("质控类别") == "平行样")
check("原记录未被覆盖", service.get_entry(eid).get("质控类别") == "平行样")

# 4. 冲突后再次操作：基于最新版本显式重试才生效
saved2, msg, status = service.update_entry(
    eid, {"质控编号": "QC-T001", "质控类别": "加标回收", "标准值": "10.0"}, base_version=2, request_id="req-3",
)
check("基于新版本重试成功", status == 200 and saved2.get("version") == 3)
check("重试后详情列表一致", service.get_entry(eid).get("质控类别") == "加标回收"
      == next(r for r in store.rows("qc") if r["id"] == eid).get("质控类别"))

# 5. 丢失防护：未提交的字段保持原值；未知字段不写入
saved3, msg, status = service.update_entry(
    eid, {"实测值": "10.1", "陌生字段": "不该出现"}, base_version=3, request_id="req-4",
)
check("部分字段保存成功", status == 200, msg)
check("未提交字段不丢失", saved3.get("判定结果") == "受控" and saved3.get("质控类别") == "加标回收")
check("未知字段被忽略", "陌生字段" not in saved3)

# 6. 必填校验：清空必填字段被拒绝，记录不变
rejected, msg, status = service.update_entry(
    eid, {"质控编号": "", "质控类别": ""}, base_version=4, request_id="req-5",
)
check("必填缺失返回 400", status == 400 and "质控编号" in msg, f"status={status} msg={msg}")
check("校验失败记录未变", service.get_entry(eid).get("质控编号") == "QC-T001")

# 7. 列表动作与保存共用版本：动作后旧版本保存必须冲突
action_entry, _ = service.run_action(eid, "确认受控")
check("动作推进版本", action_entry.get("version") == 5)
stale, msg, status = service.update_entry(
    eid, {"实测值": "9.9"}, base_version=4, request_id="req-6",
)
check("动作后旧版本保存冲突", status == 409 and stale.get("version") == 5)

# 8. 并发保存：两个线程同时基于同一版本保存，只有一个能成功
e2, _ = service.create_entry({"质控编号": "QC-T002", "质控类别": "空白", "标准值": "1.0"})
results: list[int] = []
barrier = threading.Barrier(2)


def concurrent_save(tag: str) -> None:
    barrier.wait()
    _, _, code = service.update_entry(
        e2["id"], {"实测值": tag}, base_version=1, request_id=f"race-{tag}",
    )
    results.append(code)


t1 = threading.Thread(target=concurrent_save, args=("A",))
t2 = threading.Thread(target=concurrent_save, args=("B",))
t1.start(); t2.start(); t1.join(); t2.join()
check("并发保存只有一个 200，另一个 409", sorted(results) == [200, 409], f"results={results}")
check("并发后版本只推进一次", service.get_entry(e2["id"]).get("version") == 2)

# 9. 不存在的记录
ghost, msg, status = service.update_entry(999999, {"实测值": "1"}, base_version=1, request_id="req-7")
check("不存在记录返回 404", status == 404 and ghost is None)

print()
if failures:
    print(f"共 {len(failures)} 项未通过：{failures}")
    sys.exit(1)
print("全部通过：保存回写、冲突、幂等、并发、字段白名单行为符合预期")
