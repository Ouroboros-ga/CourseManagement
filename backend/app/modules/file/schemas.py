"""文件模块请求/响应模型（Pydantic 2.x，技术方案 16）。

multipart 上传参数在路由以 File/Form 声明，不走 JSON 本体；本模块提供上传结果与
访问链接的响应外壳。BIGINT 主键对外统一字符串（复用 academic.schemas 的 IdStr）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.modules.academic.schemas import IdStr


class FileUploadResponse(BaseModel):
    """POST /files 返回：文件标识与已固化的保留/元信息（不回显对象键）。"""

    model_config = ConfigDict(from_attributes=True)

    id: IdStr
    category: str
    status: str
    original_name: str | None
    content_type: str
    size_bytes: int
    width: int
    height: int
    sha256: str
    expires_at: object


class FileAccessResponse(BaseModel):
    """GET /files/{id}/access 返回：短时签名链接与有效期（技术方案 16.2）。"""

    url: str
    method: str = "GET"
    expires_in: int
    expires_at: object


__all__ = ["FileUploadResponse", "FileAccessResponse"]
