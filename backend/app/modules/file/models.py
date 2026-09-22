"""文件域 ORM 模型（技术方案 9.4、16）。

覆盖 file_object：受限上传、对象存储 / 本地存储、状态机、短时访问签名与按类别保留期限的
落库事实。V1.0 后端接收受限文件再写存储（技术方案 16.1），存储后端可插拔（对象存储适配器
或本地文件适配器），业务权限与文件模型保持稳定。

状态机（技术方案 16.1、16.3）：
UPLOADING → READY → PURGE_PENDING → PURGED；失败可记 FAILED。仅 READY 文件可关联业务；
清理先标记 PURGE_PENDING，删除底层对象成功后置 PURGED 并记 purged_at，失败留待下次运行，
不把失败文件标记为已清理；访问已清理文件返回 FILE_EXPIRED。

约定（技术方案 8.1、9）：枚举以稳定字符串值存储并加 CHECK；object_key 由服务端随机生成，
绝不用上传原名作路径；expires_at 落库固化，不因配置变更无审计地缩短旧材料期限（16.3）；
上传者可被删除（账号注销）而材料仍需按保留期存在，故 uploader_user_id 用 SET NULL。
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import DATETIME_3, Base, TimestampMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


# --------------------------------------------------------------------------- #
# 枚举（字符串值存储）
# --------------------------------------------------------------------------- #
class FileStatus(enum.StrEnum):
    UPLOADING = "UPLOADING"  # 已建记录、底层对象尚未确认写入
    READY = "READY"  # 可被业务关联
    PURGE_PENDING = "PURGE_PENDING"  # 到期已标记待清理，底层删除进行中
    PURGED = "PURGED"  # 底层对象已删除，记录保留为审计事实
    FAILED = "FAILED"  # 上传 / 校验 / 清理失败


class FileCategory(enum.StrEnum):
    """材料类别，决定访问范围与保留策略（技术方案 16.3：按类别分别设期限）。"""

    SUBMISSION_PHOTO = "SUBMISSION_PHOTO"  # 查课提交照片
    OBJECTION_PROOF = "OBJECTION_PROOF"  # 异议证明材料（P6）
    IMPORT_FILE = "IMPORT_FILE"  # 导入原始 / 错误回执文件
    REPORT_FILE = "REPORT_FILE"  # 周报快照 / Excel（自有归档期限，不套用临时清理，16.3）
    TEMP = "TEMP"  # 临时中转（如预览期暂存），最短保留


_FILE_STATUSES = "('UPLOADING','READY','PURGE_PENDING','PURGED','FAILED')"
_FILE_CATEGORIES = (
    "('SUBMISSION_PHOTO','OBJECTION_PROOF','IMPORT_FILE','REPORT_FILE','TEMP')"
)


class FileObject(TimestampMixin, Base):
    """文件对象事实表。

    object_key 服务端随机、唯一，作为存储中的实际路径；original_name 仅展示用，可空
    （如生成件）。size_bytes / sha256 / content_type 记录校验结果。retention_policy_version
    固化命中的保留策略版本、expires_at 固化计算出的到期时刻——二者落库后不随后续配置改动
    被无审计地改写（技术方案 16.3）。
    """

    __tablename__ = "file_object"
    __table_args__ = (
        CheckConstraint(f"status IN {_FILE_STATUSES}", name="ck_file_object_status"),
        CheckConstraint(
            f"category IN {_FILE_CATEGORIES}", name="ck_file_object_category"
        ),
        CheckConstraint("size_bytes >= 0", name="ck_file_object_size"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    object_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    category: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    original_name: Mapped[str | None] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    uploader_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=FileStatus.UPLOADING.value,
        server_default=text("'UPLOADING'"),
        index=True,
    )
    # 保留策略版本与到期时刻（配置驱动计算后固化，技术方案 16.3）。
    retention_policy_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    expires_at: Mapped[datetime | None] = mapped_column(DATETIME_3)  # 未定策略时可为空
    purged_at: Mapped[datetime | None] = mapped_column(DATETIME_3)


__all__ = [
    "FileStatus",
    "FileCategory",
    "FileObject",
]
