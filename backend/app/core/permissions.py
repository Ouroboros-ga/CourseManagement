"""集中权限定义：角色代码与权限代码。

固定五角色见 docs/PERMISSIONS.md 第 0/1 节；38 项 Permission 注册表见第 4 节；
默认角色矩阵见第 5 节（映射在 identity/policy.py，本文件只定义稳定 code）。
可选权限（statistics.read、objection.initial_review、report.read）默认关闭，逐人开关。
具体资源归属与数据范围规则留在各模块 permissions.py，不在此集中所有业务判断。
"""

from __future__ import annotations

from enum import StrEnum


class RoleCode(StrEnum):
    SUPER_ADMIN = "SUPER_ADMIN"
    TEACHER_ADMIN = "TEACHER_ADMIN"
    STUDENT_AFFAIRS_MANAGER = "STUDENT_AFFAIRS_MANAGER"
    VOLUNTEER = "VOLUNTEER"
    STUDENT = "STUDENT"


class PermissionCode(StrEnum):
    """稳定权限 code，成员名 = code 大写、点替换为下划线。"""

    # 4.1 身份与账号
    ACCOUNT_READ = "account.read"
    ACCOUNT_MANAGE = "account.manage"
    ROLE_ASSIGN = "role.assign"
    OPTIONAL_PERMISSION_MANAGE = "optional_permission.manage"
    IDENTITY_BINDING_MANAGE = "identity.binding.manage"

    # 4.2 基础数据
    ACADEMIC_READ = "academic.read"
    ACADEMIC_MANAGE = "academic.manage"
    STUDENT_READ = "student.read"
    STUDENT_MANAGE = "student.manage"
    VOLUNTEER_READ = "volunteer.read"
    VOLUNTEER_MANAGE = "volunteer.manage"
    IMPORT_EXECUTE = "import.execute"

    # 4.3 查课任务与排班
    INSPECTION_READ = "inspection.read"
    INSPECTION_GENERATE = "inspection.generate"
    INSPECTION_CANCEL = "inspection.cancel"
    INSPECTION_ROSTER_READ = "inspection.roster.read"
    INSPECTION_ROSTER_MANAGE = "inspection.roster.manage"
    ASSIGNMENT_MANAGE = "assignment.manage"
    ASSIGNMENT_CHANGE_REQUEST = "assignment.change_request"
    ASSIGNMENT_CHANGE_REVIEW = "assignment.change_review"
    SUBMISSION_DEADLINE_READ = "submission_deadline.read"
    SUBMISSION_DEADLINE_MANAGE = "submission_deadline.manage"

    # 4.4 查课执行与审核
    SUBMISSION_CREATE = "submission.create"
    SUBMISSION_READ = "submission.read"
    SUBMISSION_REVIEW = "submission.review"
    ATTENDANCE_EXPECTED_COUNT_ADJUST = "attendance.expected_count_adjust"
    ATTENDANCE_READ = "attendance.read"
    ATTENDANCE_CORRECT = "attendance.correct"

    # 4.5 统计、周报、异议、审计与配置
    STATISTICS_READ = "statistics.read"
    REPORT_READ = "report.read"
    REPORT_GENERATE = "report.generate"
    OBJECTION_CREATE = "objection.create"
    OBJECTION_READ = "objection.read"
    OBJECTION_INITIAL_REVIEW = "objection.initial_review"
    OBJECTION_FINAL_REVIEW = "objection.final_review"
    AUDIT_READ = "audit.read"
    SYSTEM_CONFIG_READ = "system.config.read"
    SYSTEM_CONFIG_MANAGE = "system.config.manage"
