"""质量控制接口：维护质控样品，覆盖检测质控、确认受控、标记失控等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.qc import (
    BUSINESS_CONFLICT,
    NOT_FOUND,
    VALIDATION_ERROR,
    VERSION_CONFLICT,
    QcService,
)

router = APIRouter(prefix="/api/qc", tags=["质量控制"])


@router.middleware("http")
async def no_store_qc_responses(request: Request, call_next: Any) -> Response:
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response

service = QcService()

LIST_FIELDS = ["质控编号", "质控类别", "标准值", "允许偏差", "实测值", "判定结果", "检测日期", "质控状态"]
STATUSES = ["待检测", "检测中", "受控", "失控"]
ERROR_STATUS = {
    NOT_FOUND: 404,
    VALIDATION_ERROR: 400,
    BUSINESS_CONFLICT: 409,
    VERSION_CONFLICT: 409,
}


def failure(message: str, code: str | None, entry: dict[str, Any] | None = None) -> JSONResponse:
    status_code = ERROR_STATUS.get(code, 400)
    payload = ActionResult(ok=False, message=message, code=code, entry=entry).model_dump()
    return JSONResponse(status_code=status_code, content=payload)


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按质控编号检索"),
    category: str | None = Query(default=None, description="按质控类别检索"),
    status: str | None = Query(default=None, description="待检测、检测中、受控、失控"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按质控编号与状态过滤质量控制列表；没有数据时返回空页，不报错。"""
    if page < 1:
        raise HTTPException(status_code=400, detail="页码必须从 1 开始")
    if size < 1 or size > 200:
        raise HTTPException(status_code=400, detail="每页数量必须在 1 到 200 之间")
    items, total = service.list_entries(keyword=keyword, category=category, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出质量控制清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "qc", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条质控样品明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"质控样品 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult, status_code=201)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条质控样品，缺字段时说明原因而不是静默丢弃。"""
    entry, errors = service.create_entry(payload.values, request_id=payload.request_id)
    if errors:
        return failure("；".join(errors), VALIDATION_ERROR)
    return ActionResult(ok=True, message="质控样品已登记", entry=entry)


@router.put("/{entry_id}", response_model=ActionResult)
def update_entry(entry_id: int, payload: EntryPayload) -> ActionResult | JSONResponse:
    """保存一条质控样品；携带版本号时只允许基于最新版本提交。"""
    if payload.expected_version is None:
        return failure('保存前请先读取最新记录版本', VERSION_CONFLICT)
    entry, message, code, latest = service.update_entry(
        entry_id,
        payload.values,
        expected_version=payload.expected_version,
        request_id=payload.request_id,
    )
    if entry is None:
        return failure(message, code, latest)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult | JSONResponse:
    """对单条质控样品执行检测质控、确认受控、标记失控；不允许的动作会被拦下并说明原因。"""
    action = str(payload.action or payload.values.get("action") or "").strip()
    if payload.expected_version is None:
        return failure('执行动作前请先读取最新记录版本', VERSION_CONFLICT)
    entry, message, code, latest = service.run_action(
        entry_id,
        action,
        expected_version=payload.expected_version,
        request_id=payload.request_id,
    )
    if entry is None:
        return failure(message, code, latest)
    return ActionResult(ok=True, message=message, entry=entry)
