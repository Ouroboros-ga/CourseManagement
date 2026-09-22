"""上传文件校验（技术方案 16.1）。

V1.0 校验：扩展名白名单、声明 MIME、真实文件签名（magic bytes）三者一致，限制单文件字节
大小与图像像素上限（防解码炸弹），并计算 sha256。为遵循轻量依赖取向，图像宽高用纯解析器
读取文件头（PNG IHDR / JPEG SOF / WebP VP8·VP8X·VP8L）而非引入重型解码库——足以对
"像素总量上限"这一安全护栏作出可靠判定；真正的逐像素解码留待对象存储/预览侧按需处理。

校验失败统一抛 ValidationError→400/422 由 service 转换；本模块只做纯字节判定，不触库、
不写存储。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

# 扩展名（小写、无点）→ 规范 MIME 与真实签名探测。
_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_JPEG_SIG = b"\xff\xd8\xff"
_RIFF = b"RIFF"
_WEBP = b"WEBP"

# 声明 MIME → 归一扩展名（用于三方一致性核对）。
_MIME_TO_EXT: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/pjpeg": "jpg",
    "image/webp": "webp",
}


class FileValidationError(Exception):
    """校验失败的语义标记；service 捕获转成统一 AppError。"""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def detect_type(data: bytes) -> str | None:
    """返回真实图像类型（png/jpeg/webp）或 None（非受支持图像）。"""
    if data.startswith(_PNG_SIG):
        return "png"
    if data.startswith(_JPEG_SIG):
        return "jpg"
    if len(data) >= 12 and data[:4] == _RIFF and data[8:12] == _WEBP:
        return "webp"
    return None


def _png_dims(data: bytes) -> tuple[int, int] | None:
    # IHDR 紧跟 8 字节签名 + 4 长度 + 'IHDR'，宽高各 4 字节大端。
    if len(data) >= 24 and data[12:16] == b"IHDR":
        w = int.from_bytes(data[16:20], "big")
        h = int.from_bytes(data[20:24], "big")
        return w, h
    return None


def _webp_dims(data: bytes) -> tuple[int, int] | None:
    fmt = data[12:16]
    if fmt == b"VP8X" and len(data) >= 30:
        # VP8X：canvas 宽/高各 3 字节小端，值 = 存值 + 1（编码为 minus-one）。
        w = int.from_bytes(data[24:27], "little") + 1
        h = int.from_bytes(data[27:30], "little") + 1
        return w, h
    if fmt == b"VP8 " and len(data) >= 30:
        # 有损：帧头在 20 字节 chunk 之后，宽高各 2 字节（14 位，低位对齐）。
        w = int.from_bytes(data[26:28], "little") & 0x3FFF
        h = int.from_bytes(data[28:30], "little") & 0x3FFF
        return w, h
    if fmt == b"VP8L" and len(data) >= 25:
        # 无损：签名 0x2F 后跟 14bit-1 宽、14bit-1 高打包在 4 字节里。
        bits = int.from_bytes(data[21:25], "little")
        w = (bits & 0x3FFF) + 1
        h = ((bits >> 14) & 0x3FFF) + 1
        return w, h
    return None


def _jpeg_dims(data: bytes) -> tuple[int, int] | None:
    # 扫描 SOF0..SOF15（排除 DHT/DAC 等），marker 后第 5、7 字节为高、宽（大端）。
    i = 2
    n = len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h = int.from_bytes(data[i + 5 : i + 7], "big")
            w = int.from_bytes(data[i + 7 : i + 9], "big")
            return w, h
        seg_len = int.from_bytes(data[i + 2 : i + 4], "big")
        i += 2 + max(seg_len, 2)
    return None


def image_dimensions(kind: str, data: bytes) -> tuple[int, int] | None:
    if kind == "png":
        return _png_dims(data)
    if kind == "webp":
        return _webp_dims(data)
    if kind == "jpg":
        return _jpeg_dims(data)
    return None


@dataclass(frozen=True)
class ValidatedImage:
    kind: str  # 归一真实类型 png/jpeg/webp
    ext: str  # 与类型对应的规范扩展名
    content_type: str  # 规范 MIME
    size_bytes: int
    width: int
    height: int
    sha256: str


def validate_upload(
    *,
    data: bytes,
    declared_content_type: str | None,
    original_name: str | None,
    allowed_extensions: frozenset[str],
    max_bytes: int,
    max_pixels: int,
) -> ValidatedImage:
    """综合校验，任一不过抛 FileValidationError。通过则返回归一元数据。"""
    if not data:
        raise FileValidationError("文件内容为空")
    size = len(data)
    if size > max_bytes:
        raise FileValidationError(f"文件超过单文件大小上限 {max_bytes} 字节")

    ext = (original_name or "").rsplit(".", 1)[-1].lower() if original_name else ""
    if ext and ext not in allowed_extensions:
        raise FileValidationError(f"不支持的扩展名：{ext}")

    real = detect_type(data)
    if real is None:
        raise FileValidationError("文件真实内容不是受支持的图像类型（签名校验未通过）")

    # 扩展名、真实签名、声明 MIME 三方一致。
    if ext and ext not in {"jpg", "jpeg"} and real != ext:
        # png/webp 必须扩展名与真实类型一致
        raise FileValidationError("扩展名与文件真实类型不一致")
    if ext in {"jpg", "jpeg"} and real != "jpg":
        raise FileValidationError("扩展名与文件真实类型不一致")

    if declared_content_type:
        norm = _MIME_TO_EXT.get(declared_content_type.strip().lower())
        if norm != real:
            raise FileValidationError("声明 MIME 与文件真实类型不一致")

    dims = image_dimensions(real, data)
    if dims is None:
        raise FileValidationError("无法解析图像尺寸（文件可能损坏或被截断）")
    w, h = dims
    if w <= 0 or h <= 0:
        raise FileValidationError("图像尺寸非法")
    if w * h > max_pixels:
        raise FileValidationError(f"图像像素超过上限 {max_pixels}")

    return ValidatedImage(
        kind=real,
        ext="jpg" if real == "jpg" else real,
        content_type=f"image/{'jpeg' if real == 'jpg' else real}",
        size_bytes=size,
        width=w,
        height=h,
        sha256=hashlib.sha256(data).hexdigest(),
    )


__all__ = [
    "FileValidationError",
    "ValidatedImage",
    "detect_type",
    "image_dimensions",
    "validate_upload",
]
