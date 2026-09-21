"""身份种子：注册表同步与账号创建分离，可重复执行且默认值单一真相源。

设计（开发路线 P1 第 2 步）：
- `sync_registry` 只负责"字典数据"：把 38 项 Permission、5 类 Role 落库，并将
  role_permission 精确对齐 policy.DEFAULT_ROLE_PERMISSIONS。幂等——二次执行不重复写；
  移除过期的默认角色-权限关联前先输出差异日志。绝不触碰 user_permission（个人授权）。
- `ensure_admin_account` 只负责创建超级管理员账号：仅当账号不存在时创建，
  已存在则跳过，绝不重置既有口令、不改动其角色，避免覆盖运维已设置的密码。
- 演示数据（行政班/学生/绑定码）为可选联调辅助，与上述两者独立。

用法（工程根 backend/ 目录）：
    # 仅同步注册表（不需要口令，可用于任何环境）：
    uv run python -m app.modules.identity.seed --skip-admin
    # 同步注册表并创建超管（口令经环境变量注入，绝不写入仓库）：
    uv run python -m app.modules.identity.seed --admin-username admin \
        --admin-password 'ChangeMe_123'
    # 生成一次性绑定码（学生名单由导入维护，或先 --with-demo）：
    uv run python -m app.modules.identity.seed --issue-binding-token S20240001
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import session_scope, utcnow
from app.core.logging import get_logger, setup_logging
from app.core.permissions import PermissionCode, RoleCode
from app.core.security import generate_secure_token, hash_password, hash_token
from app.modules.identity.models import (
    AdministrativeClass,
    BindingTokenStatus,
    IdentityBindingToken,
    Permission,
    Role,
    Student,
    UserAccount,
    UserStatus,
)
from app.modules.identity.policy import DEFAULT_ROLE_PERMISSIONS

logger = get_logger("seed.identity")

# 角色 code -> 中文名。
ROLE_NAMES: dict[str, str] = {
    RoleCode.SUPER_ADMIN.value: "超级管理员",
    RoleCode.TEACHER_ADMIN.value: "教师管理员",
    RoleCode.STUDENT_AFFAIRS_MANAGER.value: "学生工作负责人",
    RoleCode.VOLUNTEER.value: "查课志愿者",
    RoleCode.STUDENT.value: "普通学生",
}

# 已知可选权限的中文名；其余权限以 code 作为展示名，不臆造翻译。
OPTIONAL_PERMISSION_NAMES: dict[str, str] = {
    PermissionCode.STATISTICS_READ.value: "统计查看",
    PermissionCode.OBJECTION_INITIAL_REVIEW.value: "异议初核",
    PermissionCode.REPORT_READ.value: "周报查看与下载",
}


def _permission_name(code: str) -> str:
    return OPTIONAL_PERMISSION_NAMES.get(code, code)


@dataclass
class RegistrySyncReport:
    """注册表同步结果，供日志与测试断言使用。"""

    created_permissions: list[str] = field(default_factory=list)
    created_roles: list[str] = field(default_factory=list)
    added_links: list[tuple[str, str]] = field(default_factory=list)
    removed_links: list[tuple[str, str]] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(
            self.created_permissions
            or self.created_roles
            or self.added_links
            or self.removed_links
        )


def _upsert_roles(session: Session, report: RegistrySyncReport) -> dict[str, Role]:
    roles: dict[str, Role] = {}
    for code, name in ROLE_NAMES.items():
        role = session.execute(
            select(Role).where(Role.code == code)
        ).scalar_one_or_none()
        if role is None:
            role = Role(code=code, name=name)
            session.add(role)
            session.flush()
            report.created_roles.append(code)
            logger.info("创建角色 %s", code)
        roles[code] = role
    return roles


def _upsert_permissions(session: Session, report: RegistrySyncReport) -> dict[str, Permission]:
    perms: dict[str, Permission] = {}
    for code in (p.value for p in PermissionCode):
        perm = session.execute(
            select(Permission).where(Permission.code == code)
        ).scalar_one_or_none()
        if perm is None:
            perm = Permission(code=code, name=_permission_name(code))
            session.add(perm)
            session.flush()
            report.created_permissions.append(code)
        perms[code] = perm
    return perms


def sync_registry(session: Session) -> RegistrySyncReport:
    """把注册表（角色、权限、默认角色-权限关联）同步为 DEFAULT_ROLE_PERMISSIONS。

    幂等；不删除任何 user_permission 个人授权；不重置任何账号口令。
    """
    report = RegistrySyncReport()
    roles = _upsert_roles(session, report)
    perms = _upsert_permissions(session, report)

    for role_code, desired in DEFAULT_ROLE_PERMISSIONS.items():
        role = roles[role_code]
        current = {p.code for p in role.permissions}
        to_remove = current - desired
        to_add = desired - current
        if to_remove:
            # 移除旧默认关联前输出差异（P1 第 2 步）。
            for code in sorted(to_remove):
                logger.warning("移除过期默认关联：角色=%s 权限=%s", role_code, code)
                report.removed_links.append((role_code, code))
        # 精确对齐：仅保留不在移除集内的对象，再补入新增，触发最小 delta。
        kept = [p for p in role.permissions if p.code not in to_remove]
        have = {p.code for p in kept}
        for code in sorted(to_add):
            if code not in have:
                kept.append(perms[code])
                report.added_links.append((role_code, code))
        role.permissions = kept

    session.flush()
    if report.changed:
        logger.info(
            "注册表同步：新建权限 %d、角色 %d；新增关联 %d、移除关联 %d",
            len(report.created_permissions), len(report.created_roles),
            len(report.added_links), len(report.removed_links),
        )
    else:
        logger.info("注册表同步：无变化（已是目标状态，幂等跳过）")
    return report


def ensure_admin_account(
    session: Session,
    *,
    username: str,
    password: str,
    display_name: str,
) -> bool:
    """仅在超管账号不存在时创建；已存在则原样保留（不重置口令、不改角色）。"""
    admin = session.execute(
        select(UserAccount).where(UserAccount.username == username)
    ).scalar_one_or_none()
    if admin is not None:
        logger.info("超级管理员 %s 已存在，跳过（不重置口令、不改角色）", username)
        return False

    role = session.execute(select(Role).where(Role.code == RoleCode.SUPER_ADMIN.value)).scalar_one()
    admin = UserAccount(
        username=username,
        password_hash=hash_password(password),
        display_name=display_name,
        status=UserStatus.ACTIVE.value,
    )
    admin.roles = [role]
    session.add(admin)
    session.flush()
    logger.info("创建超级管理员 %s", username)
    return True


def _ensure_demo_student(session: Session) -> None:
    """可选演示数据：一个行政班与学生，供学生绑定流程联调（真实名单由导入维护）。"""
    ac = session.execute(
        select(AdministrativeClass).where(AdministrativeClass.class_code == "DEMO-001")
    ).scalar_one_or_none()
    if ac is None:
        ac = AdministrativeClass(
            class_code="DEMO-001", class_name="演示班级", grade_year=2024, major_name="演示专业"
        )
        session.add(ac)
        session.flush()

    stu = session.execute(
        select(Student).where(Student.student_no == "S20240001")
    ).scalar_one_or_none()
    if stu is None:
        stu = Student(
            student_no="S20240001", name="演示学生", administrative_class_id=ac.id
        )
        session.add(stu)
        session.flush()


def run(
    *,
    admin_username: str | None,
    admin_password: str | None,
    admin_display_name: str,
    with_demo: bool,
) -> None:
    setup_logging()
    with session_scope() as session:
        sync_registry(session)
        if admin_username and admin_password:
            ensure_admin_account(
                session,
                username=admin_username,
                password=admin_password,
                display_name=admin_display_name,
            )
        elif admin_username or admin_password:
            logger.warning("需同时提供 --admin-username 与 --admin-password 才创建超管，已跳过建号")
        if with_demo:
            _ensure_demo_student(session)
    logger.info("种子执行完成（session_scope 提交）")


def issue_binding_token(student_no: str, valid_minutes: int) -> None:
    """为指定学生生成一次性绑定码，明文仅打印一次（库中只存摘要）。"""
    setup_logging()
    with session_scope() as session:
        stu = session.execute(
            select(Student).where(Student.student_no == student_no)
        ).scalar_one_or_none()
        if stu is None:
            raise SystemExit(f"学号 {student_no} 不存在，请先导入或初始化学生名单")
        code = generate_secure_token(24)
        session.add(
            IdentityBindingToken(
                student_id=stu.id,
                token_hash=hash_token(code),
                status=BindingTokenStatus.UNUSED.value,
                expires_at=utcnow() + timedelta(minutes=valid_minutes),
            )
        )
    print(f"绑定码（学生 {student_no}，{valid_minutes} 分钟内有效，仅此一次显示）：")
    print(f"    {code}")


def main() -> None:
    parser = argparse.ArgumentParser(description="同步身份注册表 / 创建超管 / 签发绑定码")
    parser.add_argument("--admin-username", default="admin")
    parser.add_argument(
        "--admin-password",
        default=os.environ.get("SEED_ADMIN_PASSWORD"),
        help="超管初始密码（建议经环境变量传入）；仅首次建号生效，绝不重置既有口令",
    )
    parser.add_argument("--admin-display-name", default="超级管理员")
    parser.add_argument(
        "--skip-admin",
        action="store_true",
        help="只同步注册表，不创建超级管理员账号（无需口令）",
    )
    parser.add_argument("--with-demo", action="store_true", help="附带演示行政班与学生")
    parser.add_argument(
        "--issue-binding-token",
        metavar="STUDENT_NO",
        help="仅为指定学号生成一次性绑定码（不执行完整种子）",
    )
    parser.add_argument("--token-valid-minutes", type=int, default=60)
    args = parser.parse_args()

    if args.issue_binding_token:
        issue_binding_token(args.issue_binding_token, args.token_valid_minutes)
        return

    if args.skip_admin:
        run(
            admin_username=None,
            admin_password=None,
            admin_display_name=args.admin_display_name,
            with_demo=args.with_demo,
        )
        return

    if not args.admin_password:
        raise SystemExit(
            "必须通过 --admin-password 或环境变量 SEED_ADMIN_PASSWORD 提供初始密码；"
            "若只需同步注册表请加 --skip-admin"
        )

    run(
        admin_username=args.admin_username,
        admin_password=args.admin_password,
        admin_display_name=args.admin_display_name,
        with_demo=args.with_demo,
    )


if __name__ == "__main__":
    main()
