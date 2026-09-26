"""质量控制业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable

from app.store import VersionConflictError, store

MODULE = "qc"
REQUIRED_FIELDS = ["质控编号", "质控类别", "标准值"]
EDITABLE_FIELDS = [
    "质控编号",
    "质控类别",
    "标准值",
    "允许偏差",
    "实测值",
    "判定结果",
    "检测日期",
]
DISPLAY_STATUS_FIELD = "质控状态"
STATUS_ORDER = ["待检测", "检测中", "受控", "失控"]
ACTION_RULES = {"检测质控": "检测中", "确认受控": "受控", "标记失控": "失控"}
JUDGEMENT_BY_STATUS = {"待检测": "待判定", "检测中": "检测中", "受控": "合格", "失控": "失控"}
NEGATIVE_ACTIONS = ["标记失控"]
BUSINESS_CONFLICT = "business_conflict"
VERSION_CONFLICT = "version_conflict"
NOT_FOUND = "not_found"
VALIDATION_ERROR = "validation_error"


class QcService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        category: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        with store.transaction(MODULE):
            rows = [store.snapshot(row) for row in store.rows(MODULE)]
            if keyword:
                rows = [row for row in rows if keyword in str(row.get("质控编号", ""))]
            if category:
                rows = [row for row in rows if category in str(row.get("质控类别", ""))]
            if status:
                rows = [row for row in rows if row.get("status") == status]
            total = len(rows)
            start = max(page - 1, 0) * size
            return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(
        self,
        values: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        cleaned, errors = self._clean_values(values, required=True)
        if errors:
            return None, errors

        if request_id:
            cache_key = f"create:{request_id}"
            cached = store.cached_request(MODULE, cache_key)
            if cached is not None:
                return cached, []
            request_lock = store.request_lock(MODULE, cache_key)
            with request_lock:
                cached = store.cached_request(MODULE, cache_key)
                if cached is not None:
                    return cached, []
                created, create_errors = self._create_entry(cleaned)
                if created is not None and not create_errors:
                    store.remember_request(MODULE, cache_key, created)
                return created, create_errors
        return self._create_entry(cleaned)

    def _create_entry(self, cleaned: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        with store.transaction(MODULE):
            rows = store.rows(MODULE)
            duplicate = next((row for row in rows if row.get("质控编号") == cleaned["质控编号"]), None)
            if duplicate is not None:
                return None, [f"质控编号已存在：{cleaned['质控编号']}"]

            now = self._now()
            entry: dict[str, Any] = {
                **{field: None for field in EDITABLE_FIELDS},
                **cleaned,
                "status": STATUS_ORDER[0],
                DISPLAY_STATUS_FIELD: STATUS_ORDER[0],
                "pending": True,
                "abnormal": False,
                "created_at": now,
                "updated_at": now,
            }
            return store.append(MODULE, entry), []

    def update_entry(
        self,
        entry_id: int,
        values: dict[str, Any],
        *,
        expected_version: int,
        request_id: str | None = None,
    ) -> tuple[dict[str, Any] | None, str, str | None, dict[str, Any] | None]:
        cleaned, errors = self._clean_values(values, required=True)
        if errors:
            return None, "；".join(errors), VALIDATION_ERROR, None

        def commit() -> tuple[dict[str, Any] | None, str, str | None, dict[str, Any] | None]:
            with store.transaction(MODULE):
                current = store.find(MODULE, entry_id)
                if current is None:
                    return None, f"质控样品 {entry_id} 不存在或已归档", NOT_FOUND, None

                duplicate = next(
                    (
                        row
                        for row in store.rows(MODULE)
                        if int(row.get("id", 0)) != entry_id and row.get("质控编号") == cleaned["质控编号"]
                    ),
                    None,
                )
                if duplicate is not None:
                    return None, f"质控编号已存在：{cleaned['质控编号']}", BUSINESS_CONFLICT, current

                next_entry = deepcopy(current)
                next_entry.update(cleaned)
                next_entry["updated_at"] = self._now()
                try:
                    return store.commit(MODULE, entry_id, next_entry, expected_version=expected_version, replace=True), "质控样品已保存", None, current
                except VersionConflictError as exc:
                    latest = store.find(MODULE, entry_id)
                    return None, str(exc), VERSION_CONFLICT, latest

        return self._with_idempotency(f"update:{entry_id}", request_id, commit)

    def run_action(
        self,
        entry_id: int,
        action: str,
        *,
        expected_version: int,
        request_id: str | None = None,
    ) -> tuple[dict[str, Any] | None, str, str | None, dict[str, Any] | None]:
        def commit() -> tuple[dict[str, Any] | None, str, str | None, dict[str, Any] | None]:
            with store.transaction(MODULE):
                current = store.find(MODULE, entry_id)
                if current is None:
                    return None, f"质控样品 {entry_id} 不存在或已归档", NOT_FOUND, None
                if action not in ACTION_RULES:
                    return None, f"动作「{action}」不属于质量控制可执行范围", VALIDATION_ERROR, current

                target = ACTION_RULES[action]
                if target not in STATUS_ORDER:
                    return None, f"目标状态「{target}」不在允许的状态序列里", VALIDATION_ERROR, current

                next_entry = deepcopy(current)
                next_entry["status"] = target
                next_entry[DISPLAY_STATUS_FIELD] = target
                next_entry["pending"] = target != STATUS_ORDER[-1]
                next_entry["abnormal"] = action in NEGATIVE_ACTIONS
                next_entry["判定结果"] = JUDGEMENT_BY_STATUS[target]
                next_entry["updated_at"] = self._now()
                try:
                    saved = store.commit(
                        MODULE,
                        entry_id,
                        next_entry,
                        expected_version=expected_version,
                        replace=True,
                    )
                    return saved, f"质控样品已{action}", None, current
                except VersionConflictError as exc:
                    latest = store.find(MODULE, entry_id)
                    return None, str(exc), VERSION_CONFLICT, latest

        return self._with_idempotency(f"action:{entry_id}", request_id, commit)

    @staticmethod
    def _with_idempotency(
        key: str,
        request_id: str | None,
        commit: Callable[[], tuple[dict[str, Any] | None, str, str | None, dict[str, Any] | None]],
    ) -> tuple[dict[str, Any] | None, str, str | None, dict[str, Any] | None]:
        if not request_id:
            return commit()

        cache_key = f"{key}:{request_id}"
        cached = store.cached_request(MODULE, cache_key)
        if cached is not None:
            return cached, "重复提交已忽略，使用首次保存结果", None, None
        with store.request_lock(MODULE, cache_key):
            cached = store.cached_request(MODULE, cache_key)
            if cached is not None:
                return cached, "重复提交已忽略，使用首次保存结果", None, None
            result = commit()
            entry, _, code, _ = result
            if entry is not None and code is None:
                store.remember_request(MODULE, cache_key, entry)
            return result

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _clean_values(
        raw: dict[str, Any],
        *,
        required: bool,
    ) -> tuple[dict[str, Any], list[str]]:
        cleaned: dict[str, Any] = {}
        unknown = [key for key in raw if key not in EDITABLE_FIELDS]
        for field in EDITABLE_FIELDS:
            if field not in raw:
                continue
            value = raw.get(field)
            if value is None:
                cleaned[field] = None
                continue
            text = str(value).strip()
            cleaned[field] = text or None

        errors: list[str] = []
        if required:
            missing = [field for field in REQUIRED_FIELDS if not cleaned.get(field)]
            if missing:
                errors.append(f"缺少必填字段：{'、'.join(missing)}")
        if unknown:
            errors.append(f"不允许提交字段：{'、'.join(unknown)}")
        return cleaned, errors
