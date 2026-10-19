"""后台提取、核对建档、绑定凭证导出和真实工号补充。

在 backend 工作目录运行 python -m app.cli.staff_onboarding --help。
配置沿用应用 DATABASE_URL，所有操作都复核指定操作者的学院 staff.manage 权限。
"""

import argparse
import csv
import json
import os
from pathlib import Path

from sqlalchemy import select

from app.core.database import get_session_factory, iso_utc
from app.core.exceptions import AppError, ConflictError
from app.modules.academic.staff_models import FacultyStaff
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.service import CurrentUser
from app.modules.identity.staff_binding import StaffBindingService
from app.modules.importer.scoped_service import ScopedImporterService
from app.modules.importer.staff_onboarding import StaffOnboarding
from app.modules.importer.staff_onboarding_source import responsibility_payload
from app.modules.organization.models import College


def write_json(path, value):
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)


def safe_cell(value):
    text = str(value or "")
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def export_credentials(tool, staff_ids, path):
    """先独占创建私有文件，整批签发并落盘后提交；失败移除本次未完成文件。"""
    if not staff_ids or len(staff_ids) != len(set(staff_ids)):
        raise ConflictError(message="请选择不重复的教职工档案 ID")
    # O_EXCL 不覆盖已发放凭证文件；POSIX 0600，Windows 继承目录 ACL。
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with (
            os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="") as output,
            tool.service.operation("staff.manage"),
        ):
            college = tool.db.get(College, tool.service.cid)
            binder = StaffBindingService(tool.db, college_id=tool.service.cid)
            writer = csv.writer(output)
            writer.writerow(["学院", "姓名", "档案ID", "工号", "临时工号", "绑定码", "有效期UTC"])
            for staff_id in sorted(staff_ids):
                staff = tool.db.scalar(
                    select(FacultyStaff)
                    .where(
                        FacultyStaff.id == staff_id,
                        FacultyStaff.college_id == tool.service.cid,
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if staff is None or staff.status != "ACTIVE" or staff.user_id is not None:
                    raise ConflictError(message="档案不存在、不属于本院、已停用或已绑定")
                _, code, expires = binder.issue_token_in_transaction(
                    actor=tool.service.actor, staff_id=staff.id, reason="后台初始化导出"
                )
                writer.writerow(
                    [
                        safe_cell(college.name),
                        safe_cell(staff.name),
                        str(staff.id),
                        safe_cell(staff.staff_no),
                        safe_cell(staff.temporary_staff_no),
                        code,
                        iso_utc(expires),
                    ]
                )
            output.flush()
            os.fsync(output.fileno())
            tool.db.commit()
    except BaseException:
        tool.db.rollback()
        path.unlink(missing_ok=True)
        raise


def responsibility_source(service, path):
    if path is None:
        return None
    with service.operation("staff.manage"):
        return responsibility_payload(service._session, service.cid, path.read_bytes(), path.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor-id", required=True, type=int)
    parser.add_argument("--college-id", required=True, type=int)
    commands = parser.add_subparsers(dest="command", required=True)
    preview = commands.add_parser("preview", help="只提取候选，不写正式资料")
    preview.add_argument("--semester-id", type=int)
    preview.add_argument("--responsibility-file", type=Path)
    preview.add_argument("--output", required=True, type=Path)
    confirm = commands.add_parser("confirm", help="按逐条核对结果建档并建立任职")
    confirm.add_argument("--plan", required=True, type=Path)
    confirm.add_argument("--review", required=True, type=Path)
    confirm.add_argument("--responsibility-file", type=Path)
    confirm.add_argument("--output", required=True, type=Path)
    export = commands.add_parser("export", help="为指定未绑定档案签发并导出一次性绑定码")
    export.add_argument("--staff-id", required=True, type=int, action="append")
    export.add_argument("--output", required=True, type=Path)
    real = commands.add_parser("set-real-number", help="明确按原档案 ID 和版本补充真实工号")
    real.add_argument("--staff-id", required=True, type=int)
    real.add_argument("--lock-version", required=True, type=int)
    real.add_argument("--real-number", required=True)
    args = parser.parse_args()
    from app import models  # noqa: F401

    with get_session_factory()() as db:
        repo = IdentityRepository(db)
        account = repo.get_user_by_id(args.actor_id)
        if account is None or not account.is_active:
            parser.error("操作者账号不存在或已停用")
        actor = CurrentUser(
            account.id,
            account.username,
            account.display_name,
            account.status,
            repo.list_role_codes(account.id),
            repo.list_effective_permissions(account.id),
        )
        service = ScopedImporterService(db, actor, args.college_id)
        tool = StaffOnboarding(service)
        try:
            if args.command == "preview":
                value = tool.preview(
                    args.semester_id, responsibility_source(service, args.responsibility_file)
                )
                value["review_template"] = [
                    {
                        "key": row["key"],
                        "action": "REVIEW_REQUIRED",
                        "person_key": "",
                        "staff_id": "",
                        "home_college_id": "",
                        "distinct_from_staff_ids": [],
                    }
                    for row in value["candidates"]
                ]
                # 模板为单独文件，确认仅接收原始指纹计划。
                template = value.pop("review_template")
                write_json(args.output, value)
                write_json(args.output.with_name(args.output.stem + "-review.json"), template)
            elif args.command == "confirm":
                if args.output.exists():
                    raise FileExistsError(args.output)
                value = tool.confirm(
                    json.loads(args.plan.read_text(encoding="utf-8")),
                    json.loads(args.review.read_text(encoding="utf-8")),
                    responsibility_source(service, args.responsibility_file),
                )
                write_json(args.output, value)
            elif args.command == "export":
                export_credentials(tool, args.staff_id, args.output)
            else:
                tool.set_real_number(args.staff_id, args.real_number, args.lock_version)
            print("操作完成。导出文件如含绑定码，请按有效期发放。")
        except (AppError, ValueError, KeyError, OSError) as exc:
            db.rollback()
            parser.exit(1, f"操作失败：{exc}\n")


if __name__ == "__main__":
    main()
