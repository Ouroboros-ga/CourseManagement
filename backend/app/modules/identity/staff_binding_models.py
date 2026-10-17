"""教职工一次性绑定凭证；与学生绑定凭证分表，只保存不可逆摘要。

原码只在签发响应中出现一次。核销的单次性由服务端对凭证行的 FOR UPDATE 串行化，
状态与使用时刻同事务写入，不依赖前端隐藏入口。
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import DATETIME_3, Base, CreateTimeMixin, pk_column
from app.core.db import MYSQL_TABLE_ARGS


class StaffBindingToken(CreateTimeMixin, Base):
    __tablename__ = "staff_binding_token"
    __table_args__ = (
        CheckConstraint("status IN ('UNUSED','USED','EXPIRED')", name="staff_binding_status"),
        MYSQL_TABLE_ARGS,
    )

    id: Mapped[int] = pk_column()
    staff_id: Mapped[int] = mapped_column(
        ForeignKey("faculty_staff.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="UNUSED", server_default=text("'UNUSED'")
    )
    expires_at: Mapped[datetime] = mapped_column(DATETIME_3, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DATETIME_3)
    failed_attempts: Mapped[int] = mapped_column(
        default=0, server_default=text("0"), nullable=False
    )
