"""审计日志 ORM 模型（技术方案 9.4、第 23 节；权限策略第 16 节）。

审计记录为不可变追加事实：只提供 INSERT 与必要 SELECT，应用账号不授予
UPDATE/DELETE（数据库授权由部署阶段落实，见技术方案 23）。因此本表只用
CreateTimeMixin（仅 created_at），不随业务记录更新。

字段与权限策略第 16 节的逻辑模型一一对应：
    actor_id / action / resource_type / resource_id
    / before_json / after_json / reason / request_id / created_at

`actor_user_id` 为逻辑 `actor_id` 的物理落地（外键指向 user_account）。
为在账号注销后仍保留审计事实，外键采用 SET NULL 且列可空；系统触发的
操作（如后续清理脚本）可无操作者。`resource_id` 以字符串保存，兼容跨表
的 BIGINT 主键而不强行绑定单一外键目标。before/after 仅记录必要差异，
不复制证明材料全文（技术方案 23 第 7 点）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, CreateTimeMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


class AuditLog(CreateTimeMixin, Base):
    """关键业务变更的追加型审计事实。"""

    __tablename__ = "audit_log"
    __table_args__ = (MYSQL_TABLE_ARGS,)

    id: Mapped[int] = pk_column()
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(64))
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(String(512))
    request_id: Mapped[str | None] = mapped_column(String(64))
