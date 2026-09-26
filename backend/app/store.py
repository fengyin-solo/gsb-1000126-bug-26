"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

import threading
from typing import Any

from app.seed import SEED_ROWS

# 幂等台账只保留最近若干条，避免长跑进程里无限膨胀
IDEMPOTENCY_LIMIT = 500


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        # 同一条记录的「读-改-写」必须串行，否则并发保存会互相覆盖
        self._lock = threading.RLock()
        # 保存请求的幂等台账：request_id -> 已完成的处理结果，重试时直接回放
        self._idempotency: dict[str, Any] = {}
        self._idempotency_order: list[str] = []

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def idempotency_get(self, key: str) -> Any | None:
        with self._lock:
            return self._idempotency.get(key)

    def idempotency_put(self, key: str, outcome: Any) -> None:
        with self._lock:
            if key not in self._idempotency:
                self._idempotency_order.append(key)
            self._idempotency[key] = outcome
            while len(self._idempotency_order) > IDEMPOTENCY_LIMIT:
                oldest = self._idempotency_order.pop(0)
                self._idempotency.pop(oldest, None)

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
