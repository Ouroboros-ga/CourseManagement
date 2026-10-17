"""导入模块的请求/响应模型（Pydantic 2.x）。

multipart 上传的参数在路由以 Form/File 声明，不走本体的 JSON 模型；本模块主要
提供确认/预览/错误/模板的响应外壳。BIGINT 主键对外统一字符串（复用 academic.schemas
的 IdStr 约定）。
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, model_validator

from app.modules.academic.schemas import IdStr, OptIdStr


class ImportPreviewResponse(BaseModel):
    """POST /imports 返回的预览结果：批次标识 + 统计概要 + 错误/告警。"""

    model_config = ConfigDict(from_attributes=True)

    id: IdStr
    target: str
    status: str
    semester_id: OptIdStr
    teaching_class_id: OptIdStr
    summary: dict
    errors: list[dict] = []
    warnings: list[dict] = []
    expires_at: object
    can_confirm: bool

    @model_validator(mode="before")
    @classmethod
    def _resolve_target(cls, data: Any) -> Any:
        if hasattr(data, "payload_json") and data.payload_json:
            it = data.payload_json.get("import_type")
            if it:
                if isinstance(data, dict):
                    data["target"] = it
                else:
                    return {
                        "id": str(data.id),
                        "target": it,
                        "status": data.status,
                        "semester_id": data.semester_id,
                        "teaching_class_id": data.teaching_class_id,
                        "summary": data.summary_json or {},
                        "errors": [
                            i for i in (data.error_json or []) if i.get("severity") == "error"
                        ],
                        "warnings": [
                            i for i in (data.error_json or []) if i.get("severity") != "error"
                        ],
                        "expires_at": data.expires_at,
                        "can_confirm": (
                            data.status == "PREVIEW"
                            and not any(
                                i.get("severity") == "error"
                                for i in (data.error_json or [])
                            )
                        ),
                    }
        elif isinstance(data, dict):
            pj = data.get("payload_json")
            if isinstance(pj, dict) and pj.get("import_type"):
                data["target"] = pj["import_type"]
        return data


class ImportConfirmResponse(BaseModel):
    id: IdStr
    target: str
    status: str
    summary: dict

    @model_validator(mode="before")
    @classmethod
    def _resolve_target(cls, data: Any) -> Any:
        if hasattr(data, "payload_json") and data.payload_json:
            it = data.payload_json.get("import_type")
            if it:
                return {
                    "id": str(data.id),
                    "target": it,
                    "status": data.status,
                    "summary": data.summary_json or {},
                }
        elif isinstance(data, dict):
            pj = data.get("payload_json")
            if isinstance(pj, dict) and pj.get("import_type"):
                data["target"] = pj["import_type"]
        return data


class ImportTemplateResponse(BaseModel):
    target: str
    scope_fields: list[str]
    columns: list[dict]
    example_rows: list[dict]


class ImportBatchListItem(BaseModel):
    """GET /imports 列表项：学院最近导入批次的可读概要（按 id 倒序）。"""

    model_config = ConfigDict(from_attributes=True)

    id: IdStr
    target: str
    status: str
    filename: str | None
    semester_id: OptIdStr
    summary: dict
    created_at: object
    expires_at: object

    @model_validator(mode="before")
    @classmethod
    def _resolve_target(cls, data: Any) -> Any:
        if hasattr(data, "payload_json") and data.payload_json:
            it = data.payload_json.get("import_type")
            if it:
                return {
                    "id": str(data.id),
                    "target": it,
                    "status": data.status,
                    "filename": data.filename,
                    "semester_id": data.semester_id,
                    "summary": data.summary_json or {},
                    "created_at": data.created_at,
                    "expires_at": data.expires_at,
                }
        elif isinstance(data, dict):
            pj = data.get("payload_json")
            if isinstance(pj, dict) and pj.get("import_type"):
                data["target"] = pj["import_type"]
        return data


__all__ = [
    "ImportPreviewResponse",
    "ImportConfirmResponse",
    "ImportTemplateResponse",
    "ImportBatchListItem",
    "BaseModel",
]
