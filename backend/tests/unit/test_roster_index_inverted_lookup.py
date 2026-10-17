"""`RosterIndex.at()` 反向索引化的差分回归。

原实现对每个学生扫描全部教学班，整周查询退化成 `学生 × 教学班 × 天数`。改为反向索引
后判定必须逐学生、逐顺序完全一致，否则正式名单、课次人数和任务快照都会漂移。
"""

import random
from datetime import date, timedelta

import pytest
from app.models import Base
from app.modules.academic.enrollment_models import (
    CourseParticipation,
    StudentEnrollment,
    TeachingClassAudience,
)
from app.modules.academic.models import (
    AdministrativeClass,
    Course,
    Semester,
    Student,
    TeachingClass,
    TeachingClassStudent,
)
from app.modules.academic.roster_index import RosterIndex
from app.modules.organization.models import College, School
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

START = date(2026, 9, 7)
TEACHING_CLASSES = 14
ADMIN_CLASSES = 6
STUDENTS = 60
PROBE_DATES = [START + timedelta(days=n) for n in (0, 20, 41, 55, 70, 90)]


def _reference_at(index: RosterIndex, on_date: date) -> dict[int, list[int]]:
    """修复前的判定原文：三路条件按全部教学班逐一取并集。"""
    result: dict[int, list[int]] = {tid: [] for tid in index.ids}
    explicit = {
        tid: {
            m.student_id
            for m in members
            if m.effective_from <= on_date and (m.effective_to is None or on_date < m.effective_to)
        }
        for tid, members in index.dated.items()
    }
    for student in index.students:
        timeline = index.enrollments[student.id]
        enrollment = next(
            (
                e
                for e in timeline
                if not e.superseded
                and e.effective_from <= on_date
                and (e.effective_to is None or on_date < e.effective_to)
            ),
            None,
        )
        if enrollment is not None:
            if enrollment.status != "ENROLLED":
                continue
            class_id = enrollment.administrative_class_id
        else:
            if timeline or student.status != "ACTIVE":
                continue
            class_id = student.administrative_class_id
        for tid in index.ids:
            if (
                student.id in explicit.get(tid, set())
                or student.id in index.legacy[tid]
                or class_id in index.audiences[tid]
            ):
                result[tid].append(student.id)
    return result


def _seed(db: Session, rng: random.Random) -> list[int]:
    db.add_all(
        [
            School(id=1, code="S", name="学校"),
            College(id=1, school_id=1, code="A", name="学院A"),
            Semester(
                id=1, code="2026FA", name="2026秋", start_date=START,
                end_date=START + timedelta(days=140), first_monday=START,
                total_weeks=20, status="ACTIVE",
            ),
        ]
    )
    db.flush()
    for k in range(1, ADMIN_CLASSES + 1):
        db.add(
            AdministrativeClass(
                id=k, class_code=f"AC{k}", class_name=f"行政班{k}", grade_year=2026,
                major_name="软件工程", college="学院A", college_id=1, status="ACTIVE",
            )
        )
    db.add(Course(id=1, course_code="C1", course_name="高等数学", status="ACTIVE", college_id=1))
    db.flush()
    for t in range(1, TEACHING_CLASSES + 1):
        db.add(
            TeachingClass(
                id=t, semester_id=1, course_id=1, class_name=f"教学班{t}",
                status="ACTIVE", college_id=1,
            )
        )
    for s in range(1, STUDENTS + 1):
        db.add(
            Student(
                id=s, student_no=f"ST{s:04d}", name=f"学生{s}",
                administrative_class_id=rng.randint(1, ADMIN_CLASSES),
                status="ACTIVE" if rng.random() > 0.12 else "SUSPENDED",
            )
        )
    db.flush()

    # 整班受众：部分教学班按行政班招生
    for t in range(1, TEACHING_CLASSES + 1):
        for cid in rng.sample(range(1, ADMIN_CLASSES + 1), rng.randint(0, 2)):
            db.add(TeachingClassAudience(teaching_class_id=t, administrative_class_id=cid))

    # 带日期的显式参与
    for pid, _ in enumerate(range(300), start=1):
        start = START + timedelta(days=rng.randint(0, 80))
        end = start + timedelta(days=rng.choice([5, 10, 40])) if rng.random() > 0.4 else None
        db.add(
            CourseParticipation(
                id=pid, teaching_class_id=rng.randint(1, TEACHING_CLASSES),
                student_id=rng.randint(1, STUDENTS), effective_from=start, effective_to=end,
            )
        )
    db.flush()

    # 旧名单（无显式参与且该班无整班受众时才生效，见 RosterIndex 构造）
    links = {(rng.randint(1, TEACHING_CLASSES), rng.randint(1, STUDENTS)) for _ in range(200)}
    for tid, sid in sorted(links):
        db.add(TeachingClassStudent(teaching_class_id=tid, student_id=sid))

    # 学籍时间线：基线、转班双区间、被取代、非在读
    eid = 0
    for s in range(1, STUDENTS + 1):
        roll = rng.random()
        if roll < 0.15:
            continue
        eid += 1
        db.add(
            StudentEnrollment(
                id=eid, student_id=s,
                administrative_class_id=rng.randint(1, ADMIN_CLASSES), college_id=1,
                effective_from=START, status=rng.choice(["ENROLLED", "ENROLLED", "SUSPENDED"]),
                revision=0, snapshot={},
            )
        )
        if roll > 0.85:
            eid += 1
            db.add(
                StudentEnrollment(
                    id=eid, student_id=s,
                    administrative_class_id=rng.randint(1, ADMIN_CLASSES), college_id=1,
                    effective_from=START + timedelta(days=rng.randint(10, 60)),
                    status="ENROLLED", revision=1, snapshot={},
                )
            )
        if 0.5 < roll <= 0.6:
            eid += 1
            db.add(
                StudentEnrollment(
                    id=eid, student_id=s,
                    administrative_class_id=rng.randint(1, ADMIN_CLASSES), college_id=1,
                    effective_from=START, status="ENROLLED", revision=2,
                    superseded=True, snapshot={},
                )
            )
    db.commit()
    return list(range(1, TEACHING_CLASSES + 1))


@pytest.fixture(name="session_and_ids")
def fixture_session_and_ids():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    rng = random.Random(20261017)
    with Session(engine) as session:
        ids = _seed(session, rng)
        yield session, ids


def test_inverted_index_matches_the_original_three_way_test(session_and_ids):
    """随机数据下每个日期、每个教学班的名单与学生顺序都必须完全相同。"""
    session, ids = session_and_ids
    index = RosterIndex(session, ids)

    for probe in PROBE_DATES:
        got = {tid: [s.id for s in rows] for tid, rows in index.at(probe).items()}
        assert got == _reference_at(index, probe), f"mismatch on {probe}"
        assert any(rows for rows in got.values()), f"{probe} produced an entirely empty roster"


def test_every_teaching_class_key_is_preserved(session_and_ids):
    """结果必须为范围内每个教学班保留键，包括空名单。"""
    session, ids = session_and_ids
    index = RosterIndex(session, ids)
    result = index.at(START + timedelta(days=41))

    assert set(result) == set(ids)
    assert all(isinstance(rows, list) for rows in result.values())


def test_enrollment_status_still_gates_membership(session_and_ids):
    """非在读学籍的学生不得进入任何名单，反向索引不得放宽这条判定。"""
    session, ids = session_and_ids
    index = RosterIndex(session, ids)
    probe = START + timedelta(days=41)
    result = index.at(probe)
    suspended = [
        student
        for student in index.students
        if (enrollment := index.enrollment_at(student.id, probe)) is not None
        and enrollment.status != "ENROLLED"
    ]
    assert suspended, "随机数据应覆盖到非在读学籍"
    for student in suspended:
        assert all(student.id not in [s.id for s in rows] for rows in result.values())
