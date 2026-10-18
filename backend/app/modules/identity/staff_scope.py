"""教职工只读 SQL 授权谓词，供后续列表/详情/统计共用并在分页前过滤。

user_id 必须来自已验证会话；as_of 必须由服务端 business_today() 提供。
本模块不颁发写入授权：写服务仍须锁定账号、档案、关系并复核版本/归档。
责任班级参数使用任务名单快照中的班级，不能替换为学生当前班级。
"""

from datetime import date

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import aliased

from app.modules.academic.models import AdministrativeClass, TeachingClass
from app.modules.academic.offering_models import AcademicOffering
from app.modules.academic.staff_models import (
    ClassStaffResponsibility,
    FacultyStaff,
    TeachingStaffAssignment,
)
from app.modules.identity.models import UserAccount
from app.modules.organization.models import College


def _active_interval(relation, day):
    return and_(
        relation.effective_from <= day,
        or_(relation.effective_to.is_(None), relation.effective_to > day),
    )


def _staff_query(user_id: int):
    return (
        select(FacultyStaff.id)
        .join(UserAccount, UserAccount.id == FacultyStaff.user_id)
        .join(College, College.id == FacultyStaff.college_id)
        .where(
            UserAccount.id == user_id,
            UserAccount.status == "ACTIVE",
            FacultyStaff.status == "ACTIVE",
            College.status == "ACTIVE",
            College.school_id == FacultyStaff.school_id,
        )
    )


def teaching_class_condition(user_id: int, *, occurrence_on, as_of: date):
    """针对外层 TeachingClass；关系同时覆盖当前日期与真实授课日期。

    LOCAL 不经共享 ID 扩权；SHARED 只匹配已确认的映射，且学校/学期一致。
    历史只读的另行授权不由本谓词隐含提供。
    """
    return _teaching_condition(
        user_id, as_of, _active_interval(TeachingStaffAssignment, occurrence_on)
    )


def teaching_class_covers_range(user_id: int, *, date_from: date, date_to: date, as_of: date):
    """关系在 ``[date_from, date_to]`` 内至少一个日期有效——本人正式课次日历用。

    与 ``teaching_class_condition`` 共用同一套锚点、学院与学期判定，只把“覆盖某一天”
    换成“区间相交”，避免出现第二套算法；已在区间前结束的任命不会因为当前在任而被列出。
    """
    return _teaching_condition(
        user_id,
        as_of,
        and_(
            TeachingStaffAssignment.effective_from <= date_to,
            or_(
                TeachingStaffAssignment.effective_to.is_(None),
                TeachingStaffAssignment.effective_to > date_from,
            ),
        ),
    )


def _teaching_condition(user_id: int, as_of: date, occurrence_predicate):
    relation = TeachingStaffAssignment
    target_college = aliased(College)
    shared = (
        select(AcademicOffering.id)
        .where(
            AcademicOffering.id == relation.academic_offering_id,
            AcademicOffering.id == TeachingClass.academic_offering_id,
            AcademicOffering.school_id == FacultyStaff.school_id,
            AcademicOffering.semester_id == relation.semester_id,
        )
        .correlate(relation, TeachingClass, FacultyStaff)
        .exists()
    )
    return (
        _staff_query(user_id)
        .join(relation, relation.staff_id == FacultyStaff.id)
        .join(target_college, target_college.id == TeachingClass.college_id)
        .where(
            target_college.school_id == FacultyStaff.school_id,
            target_college.status == "ACTIVE",
            TeachingClass.status == "ACTIVE",
            relation.semester_id == TeachingClass.semester_id,
            _active_interval(relation, as_of),
            occurrence_predicate,
            or_(
                and_(
                    relation.anchor_type == "LOCAL", relation.teaching_class_id == TeachingClass.id
                ),
                and_(relation.anchor_type == "SHARED", shared),
            ),
        )
        .correlate(TeachingClass)
        .exists()
    )


def responsible_class_condition(
    user_id: int, *, administrative_class_id, as_of: date, review_college_id=None
):
    """本人当前责任班级；review_college_id 为审核任务归属，传入时追加本院交集。

    只读命中不授予材料或改判权限。调用审核入口时必须传任务真实学院，
    学院全局/跨院授权继续走原管理服务，不并入这里的本人职责。
    """
    responsibility_class = aliased(AdministrativeClass)
    relation = ClassStaffResponsibility
    query = (
        _staff_query(user_id)
        .join(relation, relation.staff_id == FacultyStaff.id)
        .join(responsibility_class, responsibility_class.id == relation.administrative_class_id)
        .where(
            responsibility_class.id == administrative_class_id,
            responsibility_class.college_id == FacultyStaff.college_id,
            responsibility_class.status == "ACTIVE",
            _active_interval(relation, as_of),
        )
    )
    if review_college_id is not None:
        query = query.where(FacultyStaff.college_id == review_college_id)
    # 只关联调用方表达式；内部别名始终留在子查询中。
    return query.correlate_except(
        FacultyStaff, UserAccount, College, relation, responsibility_class
    ).exists()
