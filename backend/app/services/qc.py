"""质量控制业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "qc"
REQUIRED_FIELDS = ["质控编号", "质控类别", "标准值"]
# 允许保存回写的字段白名单：只按字段名写回，绝不按位置对应，避免「错位」
EDITABLE_FIELDS = ["质控编号", "质控类别", "标准值", "允许偏差", "实测值", "判定结果", "检测日期", "质控状态"]
STATUS_ORDER = ["待检测", "检测中", "受控", "失控"]
ACTION_RULES = {"检测质控": "检测中", "确认受控": "受控", "标记失控": "失控"}
NEGATIVE_ACTIONS = []


def _version_of(entry: dict[str, Any]) -> int:
    return int(entry.get("version", 0))


class QcService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("质控编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return dict(entry) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        with store.lock:
            rows = store.rows(MODULE)
            entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
            entry["status"] = STATUS_ORDER[0]
            entry["pending"] = True
            entry["abnormal"] = False
            entry["version"] = 1
            rows.append(entry)
            return dict(entry), []

    def update_entry(
        self,
        entry_id: int,
        values: dict[str, Any],
        *,
        base_version: int | None,
        request_id: str | None,
    ) -> tuple[dict[str, Any] | None, str, int]:
        """保存质控样品：版本冲突检查 → 白名单字段写回，全程串行。

        返回 (记录, 提示语, HTTP 状态码)。冲突时带回当前权威记录，
        前端据此对齐列表与详情，绝不按旧版本覆盖他人修改。
        """
        idem_key = f"{MODULE}:save:{request_id}" if request_id else None
        if idem_key:
            cached = store.idempotency_get(idem_key)
            if cached is not None:
                entry, message, status = cached
                return dict(entry), message, status
        try:
            base = int(base_version) if base_version is not None else None
        except (TypeError, ValueError):
            return None, "版本号无效，请刷新后重新打开记录", 400
        with store.lock:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"质控样品 {entry_id} 不存在或已归档", 404
            current_version = _version_of(entry)
            if base is None or base != current_version:
                return dict(entry), "该记录已被他人修改，请核对最新内容后再保存", 409
            # 只写回显式提交的白名单字段；未提交的字段保持原值，避免「丢失」
            updates = {
                field: values[field]
                for field in EDITABLE_FIELDS
                if field in values and values[field] is not None
            }
            merged = {**entry, **updates}
            missing = [field for field in REQUIRED_FIELDS if not str(merged.get(field) or "").strip()]
            if missing:
                return None, f"缺少必填字段：{'、'.join(missing)}", 400
            entry.update(updates)
            entry["version"] = current_version + 1
            saved = dict(entry)
        if idem_key:
            store.idempotency_put(idem_key, (saved, "质控样品已保存", 200))
        return saved, "质控样品已保存", 200

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于质量控制可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        with store.lock:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                return None, f"质控样品 {entry_id} 不存在或已归档"
            entry["status"] = target
            entry["pending"] = target != STATUS_ORDER[-1]
            entry["abnormal"] = action in NEGATIVE_ACTIONS
            # 动作与保存改的是同一条记录，必须一起推进版本，否则并发保存发现不了
            entry["version"] = _version_of(entry) + 1
            return dict(entry), f"质控样品已{action}"
