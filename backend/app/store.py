"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
仓库对单条记录的读取和提交提供同一把模块锁，避免并发保存/动作互相覆盖。
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from threading import RLock
from time import monotonic
from typing import Any, Iterator
from uuid import uuid4

from app.seed import SEED_ROWS


class VersionConflictError(Exception):
    """前端持有的版本已过期，不能覆盖更新后的记录。"""


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [self._with_version(dict(row)) for row in rows]
            for name, rows in SEED_ROWS.items()
        }
        self._normalize_qc_rows()
        self._locks = {name: RLock() for name in self._tables}
        self._mutation_locks: dict[tuple[str, str], RLock] = {}
        self._request_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}

    @staticmethod
    def _with_version(row: dict[str, Any]) -> dict[str, Any]:
        row.setdefault("version", 1)
        return row

    def _lock(self, module: str) -> RLock:
        lock = self._locks.get(module)
        if lock is None:
            lock = RLock()
            self._locks[module] = lock
        return lock

    @staticmethod
    def snapshot(row: dict[str, Any] | None) -> dict[str, Any] | None:
        """返回深拷贝，避免调用方拿到响应对象后在锁外改动仓库数据。"""
        return deepcopy(row) if row is not None else None

    @contextmanager
    def transaction(self, module: str) -> Iterator[None]:
        with self._lock(module):
            yield

    def _normalize_qc_rows(self) -> None:
        """统一通用 status 与业务列表展示用的「质控状态」，避免两列读到不同来源。"""
        for row in self._tables.get("qc", []):
            status = row.get("status")
            if status:
                row["质控状态"] = status

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        with self._lock(module):
            for row in self.rows(module):
                if int(row.get("id", 0)) == entry_id:
                    return self.snapshot(row)
        return None

    def find_index(self, module: str, entry_id: int) -> int:
        for index, row in enumerate(self.rows(module)):
            if int(row.get("id", 0)) == entry_id:
                return index
        return -1

    def cached_request(self, module: str, request_id: str) -> dict[str, Any] | None:
        with self._lock(module):
            now = monotonic()
            self._request_cache = {
                key: value for key, value in self._request_cache.items() if now - value[0] < 300
            }
            cached = self._request_cache.get((module, request_id))
            return deepcopy(cached[1]) if cached is not None else None

    def remember_request(self, module: str, request_id: str, result: dict[str, Any]) -> None:
        with self._lock(module):
            self._request_cache[(module, request_id)] = (monotonic(), deepcopy(result))

    def request_lock(self, module: str, request_id: str) -> RLock:
        with self._lock(module):
            now = monotonic()
            self._request_cache = {
                key: value for key, value in self._request_cache.items() if now - value[0] < 300
            }
            key = (module, request_id)
            lock = self._mutation_locks.get(key)
            if lock is None:
                lock = RLock()
                self._mutation_locks[key] = lock
            return lock

    def commit(
        self,
        module: str,
        entry_id: int,
        changes: dict[str, Any],
        *,
        expected_version: int | None = None,
        replace: bool = False,
    ) -> dict[str, Any]:
        """按版本提交单条记录；版本不匹配时不写入任何字段。"""
        with self._lock(module):
            index = self.find_index(module, entry_id)
            if index < 0:
                raise KeyError(entry_id)

            current = self.rows(module)[index]
            current_version = int(current.get("version", 1))
            if expected_version is not None and current_version != expected_version:
                raise VersionConflictError(
                    f"记录已由其他操作更新（当前版本 {current_version}，提交版本 {expected_version}）"
                )

            next_row = deepcopy(changes)
            if not replace:
                next_id = next_row.get("id", current.get("id"))
                next_version = current_version + 1
                current.update(next_row)
                current["id"] = int(next_id)
                current["version"] = next_version
            else:
                next_row["id"] = int(next_row.get("id", current.get("id", entry_id)))
                next_row["version"] = current_version + 1
                self.rows(module)[index] = next_row
                current = next_row
            return self.snapshot(current)  # type: ignore[return-value]

    def append(self, module: str, row: dict[str, Any]) -> dict[str, Any]:
        with self._lock(module):
            rows = self.rows(module)
            entry = deepcopy(row)
            next_id = entry.get("id")
            entry["id"] = int(next_id) if next_id is not None else max((int(r.get("id", 0)) for r in rows), default=0) + 1
            entry["version"] = int(entry.get("version", 1))
            entry.setdefault("revision", str(uuid4()))
            rows.append(entry)
            return self.snapshot(entry)  # type: ignore[return-value]

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
