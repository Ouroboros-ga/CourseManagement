"""名单快照冻结的批量读取回归。

`_attach_rosters` 早期实现对每个「计划条目 × 学生」调用一次 `EnrollmentService.at()`，
一次课次查询会产生上万条 SQL。改为批量读时间线后，输出必须与逐条查询逐字段一致，
否则 `selection_revision` 漂移会让精确下发的乐观并发失效。
"""

from datetime import date

import pytest
from app.models import Base
from app.modules.academic.enrollment_models import StudentEnrollment
from app.modules.academic.enrollment_service import EnrollmentService
from app.modules.academic.models import AdministrativeClass, Student
from app.modules.inspection.service import InspectionService, PlanItem
from app.modules.organization.models import College, School
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

START = date(2026, 9, 7)
TRANSFER = date(2026, 10, 15)
BEFORE = date(2026, 10, 13)
AFTER = date(2026, 10, 16)
FUTURE = date(2026, 11, 2)


def _enrollment(
    eid: int,
    student_id: int,
    ac_id: int,
    college_id: int,
    effective_from: date,
    effective_to: date | None = None,
    *,
    status: str = "ENROLLED",
    revision: int = 0,
    superseded: bool = False,
    major: str = "未填写",
) -> StudentEnrollment:
    return StudentEnrollment(
        id=eid,
        student_id=student_id,
        administrative_class_id=ac_id,
        college_id=college_id,
        effective_from=effective_from,
        effective_to=effective_to,
        status=status,
        revision=revision,
        superseded=superseded,
        snapshot={"major_name": major},
    )


def _admin_class(
    aid: int, code: str, name: str, college_id: int, major: str
) -> AdministrativeClass:
    return AdministrativeClass(
        id=aid,
        class_code=code,
        class_name=name,
        grade_year=2023,
        major_name=major,
        college=f"学院{college_id}",
        college_id=college_id,
        status="ACTIVE",
    )


def _item(student_ids: list[int], on_date: date, key: str) -> PlanItem:
    return PlanItem(
        task_key=key,
        semester_id=1,
        inspection_date=on_date,
        week_no=6,
        inspection_type="COURSE",
        start_period=1,
        end_period=2,
        course_schedule_id=1,
        teaching_class_id=1,
        administrative_class_id=None,
        course_name_snapshot="高等数学",
        class_name_snapshot="软件2301",
        classroom_snapshot="A101",
        require_photo_snapshot=False,
        student_ids=student_ids,
    )


def _snapshot(roster) -> list[tuple]:
    return [
        (
            m.student_id,
            m.class_name_snapshot,
            m.grade_year_snapshot,
            m.administrative_class_id_snapshot,
            m.college_id_snapshot,
            m.major_name_snapshot,
        )
        for m in roster
    ]


def _reference_roster(db: Session, item: PlanItem) -> list[tuple]:
    """修复前的逐条语义：以 `EnrollmentService.at()` 为基准装配同一组快照字段。"""
    students = {
        s.id: s
        for s in db.execute(select(Student).where(Student.id.in_(item.student_ids))).scalars().all()
    }
    enrollment_service = EnrollmentService(db)
    rows = []
    for sid in item.student_ids:
        s = students.get(sid)
        if s is None:
            continue
        current = s.administrative_class_id
        ac = db.get(AdministrativeClass, current) if current else None
        enrollment = enrollment_service.at(s.id, item.inspection_date)
        if enrollment is not None and enrollment.administrative_class_id != current:
            ac = db.get(AdministrativeClass, enrollment.administrative_class_id)
        rows.append(
            (
                s.id,
                ac.class_name if ac else None,
                ac.grade_year if ac else None,
                ac.id if ac else None,
                enrollment.college_id if enrollment else ac.college_id if ac else None,
                enrollment.snapshot.get("major_name")
                if enrollment
                else ac.major_name
                if ac
                else None,
            )
        )
    return rows


# 1 单一基线；2 期中转班；3 被取代的迁移基线；4 学籍状态非 ENROLLED；5 无学籍记录；
# 6 生效日晚于查课日；7/8 同一 effective_from 并列，按 revision 取新
STUDENTS = [1, 2, 3, 4, 5, 6, 7, 8]
# 学生 7 的两条区间同日生效，旧实现 `ORDER BY effective_from DESC LIMIT 1` 没有次级排序键，
# 取到哪条由存储引擎决定，无法作为差分基准；它由并列用例单独断言。
NON_TIE_STUDENTS = [1, 2, 3, 4, 5, 6, 8]


@pytest.fixture(name="db")
def fixture_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                School(id=1, code="S", name="学校"),
                College(id=1, school_id=1, code="A", name="学院A"),
                College(id=2, school_id=1, code="B", name="学院B"),
                _admin_class(1, "A1", "软工2301", 1, "软件工程"),
                _admin_class(2, "A2", "软工2302", 1, "软件工程"),
                _admin_class(3, "B1", "智能2301", 2, "人工智能"),
            ]
        )
        session.flush()
        session.add_all(
            [
                Student(id=1, student_no="S1", name="学生一", administrative_class_id=1),
                Student(id=2, student_no="S2", name="学生二", administrative_class_id=1),
                Student(id=3, student_no="S3", name="学生三", administrative_class_id=1),
                Student(id=4, student_no="S4", name="学生四", administrative_class_id=2),
                Student(id=5, student_no="S5", name="学生五", administrative_class_id=3),
                Student(id=6, student_no="S6", name="学生六", administrative_class_id=1),
                Student(id=7, student_no="S7", name="学生七", administrative_class_id=1),
                Student(id=8, student_no="S8", name="学生八", administrative_class_id=1),
            ]
        )
        session.add_all(
            [
                _enrollment(1, 1, 1, 1, START, major="软件工程"),
                _enrollment(2, 2, 1, 1, START, TRANSFER, major="软件工程"),
                _enrollment(3, 2, 3, 2, TRANSFER, revision=1, major="人工智能"),
                _enrollment(4, 3, 1, 1, START, superseded=True, major="旧专业"),
                _enrollment(5, 3, 2, 1, START, revision=1, major="软件工程"),
                _enrollment(6, 4, 2, 1, START, status="SUSPENDED", major="软件工程"),
                _enrollment(7, 6, 3, 2, FUTURE, major="人工智能"),
                _enrollment(8, 7, 1, 1, START, major="并列旧"),
                _enrollment(9, 7, 2, 1, START, revision=1, major="并列新"),
                _enrollment(10, 8, 1, 1, START, major="软件工程"),
            ]
        )
        session.commit()
        yield session


@pytest.mark.parametrize("on_date", [BEFORE, AFTER])
def test_batched_roster_matches_row_by_row_semantics(db, on_date):
    """转班、被取代、休学、无学籍、未生效各区间都必须与 `at()` 结果逐字段相同。"""
    item = _item(NON_TIE_STUDENTS, on_date, "k1")
    expected = _reference_roster(db, item)

    [filled] = InspectionService(db)._attach_rosters([item])

    assert _snapshot(filled.roster) == expected
    assert len(expected) == len(NON_TIE_STUDENTS)


def test_transfer_moves_the_frozen_class_snapshot(db):
    """转班前后同一学生落在不同行政班快照上，且学院随学籍走。"""
    service = InspectionService(db)
    before, after = _item([2], BEFORE, "b"), _item([2], AFTER, "a")
    service._attach_rosters([before, after])

    assert _snapshot(before.roster) == [(2, "软工2301", 2023, 1, 1, "软件工程")]
    assert _snapshot(after.roster) == [(2, "智能2301", 2023, 3, 2, "人工智能")]


def test_suspended_and_missing_enrollment_still_project_a_snapshot(db):
    """`at()` 不按 status 过滤；无学籍记录时回落到 student 表当前班级。"""
    [filled] = InspectionService(db)._attach_rosters([_item([4, 5], BEFORE, "s")])

    assert _snapshot(filled.roster) == [
        (4, "软工2302", 2023, 2, 1, "软件工程"),
        (5, "智能2301", 2023, 3, 2, "人工智能"),
    ]


def test_same_day_tie_resolves_to_the_higher_revision(db):
    """同日并列区间在 MySQL 下原本不确定，批量实现固定取较大 revision。"""
    [filled] = InspectionService(db)._attach_rosters([_item([7], BEFORE, "t")])

    assert _snapshot(filled.roster) == [(7, "软工2302", 2023, 2, 1, "并列新")]


def test_statement_count_does_not_grow_with_roster_size(db):
    """SQL 次数不随「课次 × 学生数」增长，这是本次修复的目的。"""
    counter = {"n": 0}

    @event.listens_for(db.get_bind(), "before_cursor_execute")
    def _count(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    service = InspectionService(db)
    counter["n"] = 0
    service._attach_rosters([_item(STUDENTS, BEFORE, f"x{i}") for i in range(3)])
    small = counter["n"]

    counter["n"] = 0
    service._attach_rosters([_item(STUDENTS, BEFORE, f"x{i}") for i in range(40)])
    large = counter["n"]

    assert small == large == 3
