"""导入模块的请求/响应模型（Pydantic 2.x）。

multipart 上传的参数在路由以 Form/File 声明，不走本体的 JSON 模型；本模块主要
提供确认/预览/错误/模板的响应外壳。BIGINT 主键对外统一字符串（复用 academic.schemas
的 IdStr 约定）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

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


class ImportConfirmResponse(BaseModel):
    id: IdStr
    target: str
    status: str
    summary: dict


class ImportTemplateResponse(BaseModel):
    target: str
    scope_fields: list[str]
    columns: list[dict]
    example_rows: list[dict]


__all__ = [
    "ImportPreviewResponse",
    "ImportConfirmResponse",
    "ImportTemplateResponse",
    "BaseModel",
]
