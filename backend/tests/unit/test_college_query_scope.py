"""旧管理路径查询、计数、缓存和写入都不能跨固定学院。"""

import pytest
from app.core.exceptions import PermissionDeniedError
from app.modules.academic.models import AdministrativeClass, Student
from app.modules.identity.query_scope import ScopedSession, activate_query_scope
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

pytest_plugins = ["tests.unit.test_enrollment_lifecycle"]


def test_list_count_and_identity_cache_are_scoped(school):
    school.add(Student(id=2, student_no="B", name="另一学院", administrative_class_id=3))
    school.commit()
    with ScopedSession(school.get_bind()) as db:
        foreign = db.get(Student, 2)
        assert foreign is not None
        activate_query_scope(db, 2)
        assert db.scalar(select(func.count()).select_from(Student)) == 1
        assert [s.id for s in db.scalars(select(Student))] == [1]
        assert db.get(Student, 2) is None
        assert db.get(AdministrativeClass, 3) is None
        other = aliased(Student)
        assert [s.id for s in db.scalars(select(other))] == [1]


def test_cached_foreign_write_cannot_bypass_scope(school):
    with ScopedSession(school.get_bind()) as db:
        foreign = db.get(AdministrativeClass, 3)
        activate_query_scope(db, 2)
        foreign.class_name = "非法修改"
        with pytest.raises(PermissionDeniedError):
            db.flush()
        db.rollback()
        db.info.clear()
        assert db.get(AdministrativeClass, 3).class_name == "B1"


def test_teacher_cannot_change_own_class_college(school):
    with ScopedSession(school.get_bind()) as db:
        activate_query_scope(db, 2)
        own = db.get(AdministrativeClass, 1)
        own.college_id = 2
        with pytest.raises(PermissionDeniedError):
            db.flush()


def test_school_admin_and_personal_paths_remain_distinct(school):
    with ScopedSession(school.get_bind()) as db:
        activate_query_scope(db, 1)
        assert len(list(db.scalars(select(AdministrativeClass)))) == 3
        activate_query_scope(db, 2, personal=True)
        assert "college_query_scope" not in db.info
