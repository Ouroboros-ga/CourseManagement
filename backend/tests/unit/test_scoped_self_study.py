import pytest
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.academic.campus_models import CourseType
from app.modules.academic.models import CourseSchedule, TeachingClass, TeachingClassStudent
from app.modules.academic.scoped_writes import ScopedAcademicWriteService
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_academic import records


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_batch_self_study_creates_courses_schedules_and_links_students(campus):
    _, db, admin, _, a, b = campus
    ac_a, ac_b, _, teaching, _, own, foreign = records(db, a, b)
    service = ScopedAcademicWriteService(db, admin, int(a["id"]))

    # 获取已内置的早自习类型
    ctype = db.scalar(
        select(CourseType).where(
            CourseType.college_id == int(a["id"]),
            CourseType.builtin_key == "morning_study",
        )
    )
    assert ctype is not None

    # 测试非法时间段
    with pytest.raises(ConflictError):
        service.batch_self_study({
            "semester_id": teaching.semester_id,
            "study_type": "EARLY",
            "class_ids": [ac_a.id],
            "weeks": [1, 2, 3],
            "weekdays": [1, 2, 3, 4, 5],
            "start_period": 2,
            "end_period": 1,
        })

    # 测试跨院班级被拒绝
    with pytest.raises(NotFoundError):
        service.batch_self_study({
            "semester_id": teaching.semester_id,
            "study_type": "EARLY",
            "class_ids": [ac_a.id, ac_b.id],
            "weeks": [1, 2, 3],
            "weekdays": [1, 2, 3, 4, 5],
            "start_period": 1,
            "end_period": 1,
        })

    # 成功批量生成
    result = service.batch_self_study({
        "semester_id": teaching.semester_id,
        "study_type": "EARLY",
        "class_ids": [ac_a.id],
        "weeks": [1, 2, 3],
        "weekdays": [1, 2, 3, 4, 5],
        "start_period": 1,
        "end_period": 1,
        "classrooms": {str(ac_a.id): "自习室101"},
    })

    assert result["status"] == "SUCCESS"
    assert result["classes_created"] == 1
    assert result["schedules_created"] == 5
    assert result["students_linked"] == 1

    # 验证数据库记录
    tc = db.scalar(
        select(TeachingClass).where(TeachingClass.class_code == f"SS_EARLY_{ac_a.class_code}")
    )
    assert tc is not None
    assert tc.course_type_id == ctype.id
    assert tc.class_name == f"{ac_a.class_name}早自习"

    # 验证学生已关联
    linked = list(
        db.scalars(
            select(TeachingClassStudent.student_id).where(
                TeachingClassStudent.teaching_class_id == tc.id
            )
        )
    )
    assert linked == [own.id]

    # 验证 5 天的排课条目
    schedules = list(
        db.scalars(select(CourseSchedule).where(CourseSchedule.teaching_class_id == tc.id))
    )
    assert len(schedules) == 5
    assert all(s.classroom == "自习室101" for s in schedules)
    assert all(s.start_period == 1 and s.end_period == 1 for s in schedules)
