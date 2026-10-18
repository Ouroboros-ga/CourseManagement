"""教职工档案与任职关系的院级查询与加锁读取。

只执行查询，不提交事务；写服务在同一事务内按账号—学院—档案—稳定父资源—关系的
顺序加锁，关系为空时仍然锁父行，避免把空结果的读取当成防重手段。
"""

from datetime import date, timedelta
from typing import Any

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session, raiseload

from app.common.pagination import PageParams
from app.core.exceptions import NotFoundError
from app.modules.academic.models import AdministrativeClass, Semester, TeachingClass
from app.modules.academic.offering_models import AcademicOffering
from app.modules.academic.repository import _paged
from app.modules.academic.staff_models import (
    ClassStaffResponsibility,
    FacultyStaff,
    TeachingStaffAssignment,
)
from app.modules.identity.models import UserAccount
from app.modules.organization.models import College


def interval_overlaps(relation, start: date, end: date | None):
    """半开区间 [effective_from, effective_to) 与 [start, end) 是否重叠。"""
    conditions = [or_(relation.effective_to.is_(None), relation.effective_to > start)]
    if end is not None:
        conditions.append(relation.effective_from < end)
    return and_(*conditions)


def active_on(relation, day: date):
    """单日命中等价于与 [day, day+1) 重叠；结束日当天不再有效。"""
    return interval_overlaps(relation, day, day + timedelta(days=1))


def _for_update(stmt: Select, *, read: bool = False) -> Select:
    stmt = stmt.with_for_update(read=read) if read else stmt.with_for_update()
    return stmt.execution_options(populate_existing=True)


class StaffRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ---- 学院与档案 ----
    def college(self, college_id: int) -> College:
        row = self.db.scalar(
            _for_update(select(College).where(College.id == college_id), read=True)
        )
        if row is None:
            raise NotFoundError("学院不存在")
        return row

    def profile_query(self, college_id: int) -> Select:
        return select(FacultyStaff).where(FacultyStaff.college_id == college_id)

    def profile(self, college_id: int, staff_id: int, *, lock: bool = False) -> FacultyStaff:
        stmt = self.profile_query(college_id).where(FacultyStaff.id == staff_id)
        row = self.db.scalar(_for_update(stmt) if lock else stmt)
        if row is None:
            raise NotFoundError("教职工档案不在本院工作区")
        return row

    def page_profiles(
        self, college_id: int, params: PageParams, *, keyword: str | None, status: str | None
    ) -> tuple[list[FacultyStaff], int]:
        stmt = self.profile_query(college_id).options(raiseload("*"))
        if keyword:
            stmt = stmt.where(
                or_(
                    FacultyStaff.staff_no.contains(keyword, autoescape=True),
                    FacultyStaff.name.contains(keyword, autoescape=True),
                )
            )
        if status:
            stmt = stmt.where(FacultyStaff.status == status)
        rows, total = _paged(self.db, stmt.order_by(FacultyStaff.staff_no, FacultyStaff.id), params)
        return list(rows), int(total)

    def staff_no_in_school(self, school_id: int, staff_no: str) -> FacultyStaff | None:
        """工号唯一性锚定学校，跨学院重复同样命中。"""
        return self.db.scalar(
            _for_update(
                select(FacultyStaff).where(
                    FacultyStaff.school_id == school_id, FacultyStaff.staff_no == staff_no
                )
            )
        )

    def profile_bound_to_account(self, user_id: int) -> FacultyStaff | None:
        return self.db.scalar(
            _for_update(select(FacultyStaff).where(FacultyStaff.user_id == user_id))
        )

    def account(self, user_id: int) -> UserAccount | None:
        return self.db.scalar(
            select(UserAccount).where(UserAccount.id == user_id).execution_options(
                populate_existing=True
            )
        )

    # ---- 稳定父资源 ----
    def semester(self, semester_id: int) -> Semester:
        row = self.db.scalar(_for_update(select(Semester).where(Semester.id == semester_id)))
        if row is None:
            raise NotFoundError("学期不存在")
        return row

    def teaching_class(self, college_id: int, teaching_class_id: int) -> TeachingClass:
        row = self.db.scalar(
            _for_update(
                select(TeachingClass).where(
                    TeachingClass.id == teaching_class_id,
                    TeachingClass.college_id == college_id,
                    TeachingClass.status == "ACTIVE",
                )
            )
        )
        if row is None:
            raise NotFoundError("教学班不在本院、已停用或不存在")
        return row

    def offering(self, school_id: int, academic_offering_id: str) -> AcademicOffering:
        row = self.db.scalar(
            _for_update(
                select(AcademicOffering).where(
                    AcademicOffering.id == academic_offering_id,
                    AcademicOffering.school_id == school_id,
                )
            )
        )
        if row is None:
            raise NotFoundError("共享课程身份不属于本学校")
        return row

    def administrative_class(self, college_id: int, class_id: int) -> AdministrativeClass:
        row = self.db.scalar(
            _for_update(
                select(AdministrativeClass).where(
                    AdministrativeClass.id == class_id,
                    AdministrativeClass.college_id == college_id,
                    AdministrativeClass.status == "ACTIVE",
                )
            )
        )
        if row is None:
            raise NotFoundError("行政班不在本院、已停用或不存在")
        return row

    def lock_administrative_class(self, class_id: int) -> None:
        """锁定行政班父行；结束任职不要求班级仍为启用状态。"""
        self.db.scalar(
            _for_update(select(AdministrativeClass.id).where(AdministrativeClass.id == class_id))
        )

    def class_offering(self, teaching_class_id: int | None) -> str | None:
        """本地教学班已确认的共享身份；未确认时不参与跨锚点重叠判定。"""
        if teaching_class_id is None:
            return None
        return self.db.scalar(
            select(TeachingClass.academic_offering_id).where(
                TeachingClass.id == teaching_class_id
            )
        )

    # ---- 关系 ----
    def _relations_in_college(self, model, college_id: int, **filters: Any) -> Select:
        stmt = select(model).join(FacultyStaff, model.staff_id == FacultyStaff.id)
        if model is TeachingStaffAssignment:
            # LOCAL 由课程学院管理，不能因教师在外院建档而隐藏/转移课程关系。
            # SHARED 仍由原有明确授权的档案学院管理，不向其他学院扩大整班授权。
            stmt = stmt.where(or_(
                and_(model.anchor_type == "LOCAL", model.teaching_class_id.in_(
                    select(TeachingClass.id).where(TeachingClass.college_id == college_id))),
                and_(model.anchor_type == "SHARED", FacultyStaff.college_id == college_id),
            ))
        else:
            stmt = stmt.where(FacultyStaff.college_id == college_id)
        for column, value in filters.items():
            if value is not None:
                stmt = stmt.where(getattr(model, column) == value)
        return stmt

    def list_teaching(
        self, college_id: int, *, staff_id: int | None = None, teaching_class_id: int | None = None
    ) -> list[TeachingStaffAssignment]:
        stmt = self._relations_in_college(
            TeachingStaffAssignment,
            college_id,
            staff_id=staff_id,
            teaching_class_id=teaching_class_id,
        ).order_by(TeachingStaffAssignment.effective_from, TeachingStaffAssignment.id)
        return list(self.db.scalars(stmt))

    def list_responsibilities(
        self,
        college_id: int,
        *,
        staff_id: int | None = None,
        administrative_class_id: int | None = None,
        as_of: date | None = None,
    ) -> list[ClassStaffResponsibility]:
        stmt = self._relations_in_college(
            ClassStaffResponsibility,
            college_id,
            staff_id=staff_id,
            administrative_class_id=administrative_class_id,
        )
        if as_of is not None:
            stmt = stmt.where(active_on(ClassStaffResponsibility, as_of))
        return list(
            self.db.scalars(stmt.order_by(ClassStaffResponsibility.effective_from,
                                           ClassStaffResponsibility.id))
        )

    def relation(
        self, model, college_id: int, relation_id: int, *, lock: bool = True
    ) -> Any:
        stmt = self._relations_in_college(model, college_id, id=relation_id)
        row = self.db.scalar(_for_update(stmt) if lock else stmt)
        if row is None:
            raise NotFoundError("任职关系不属于本院工作区或不存在")
        return row

    def overlapping_teaching(
        self,
        staff_id: int,
        semester_id: int,
        start: date,
        end: date | None,
        *,
        exclude_id: int | None = None,
    ) -> list[tuple[TeachingStaffAssignment, str | None]]:
        """返回重叠任命及其本地教学班对应的共享身份，供跨锚点重叠判定。

        不加锁：串行点由调用方锁档案父行提供（同一人的重叠才能互相看见）。
        """
        stmt = (
            select(TeachingStaffAssignment, TeachingClass.academic_offering_id)
            .outerjoin(TeachingClass, TeachingClass.id == TeachingStaffAssignment.teaching_class_id)
            .where(
                TeachingStaffAssignment.staff_id == staff_id,
                TeachingStaffAssignment.semester_id == semester_id,
                interval_overlaps(TeachingStaffAssignment, start, end),
            )
            .execution_options(populate_existing=True)
        )
        if exclude_id is not None:
            stmt = stmt.where(TeachingStaffAssignment.id != exclude_id)
        return [(row[0], row[1]) for row in self.db.execute(stmt)]

    def overlapping_responsibilities(
        self,
        administrative_class_id: int,
        duty: str,
        start: date,
        end: date | None,
        *,
        exclude_id: int | None = None,
        lock: bool = True,
    ) -> list[ClassStaffResponsibility]:
        """同班同职责且与新区间重叠的任职；起始日倒序，最新一条即在任者。"""
        stmt = (
            select(ClassStaffResponsibility)
            .where(
                ClassStaffResponsibility.administrative_class_id == administrative_class_id,
                ClassStaffResponsibility.duty == duty,
                interval_overlaps(ClassStaffResponsibility, start, end),
            )
            .order_by(
                ClassStaffResponsibility.effective_from.desc(),
                ClassStaffResponsibility.id.desc(),
            )
        )
        if exclude_id is not None:
            stmt = stmt.where(ClassStaffResponsibility.id != exclude_id)
        return list(self.db.scalars(_for_update(stmt) if lock else stmt))

    def lock_profile(self, staff_id: int) -> None:
        """按档案 id 串行同一教师的重叠写入，不限定学院。

        导入允许把共享课程的任命授给他院档案，因此不能复用带学院过滤的 `profile()`；
        只锁父行，不改变可见范围规则。
        """
        self.db.scalar(
            _for_update(select(FacultyStaff.id).where(FacultyStaff.id == staff_id))
        )

    # ---- 本人视图摘要（存在性，不返回全院 ID 列表）----
    def has_active_teaching(self, staff_id: int, day: date) -> bool:
        return (
            self.db.scalar(
                select(TeachingStaffAssignment.id)
                .where(
                    TeachingStaffAssignment.staff_id == staff_id,
                    active_on(TeachingStaffAssignment, day),
                )
                .limit(1)
            )
            is not None
        )

    def has_active_responsibility(self, staff_id: int, day: date) -> bool:
        return (
            self.db.scalar(
                select(ClassStaffResponsibility.id)
                .where(
                    ClassStaffResponsibility.staff_id == staff_id,
                    active_on(ClassStaffResponsibility, day),
                )
                .limit(1)
            )
            is not None
        )
