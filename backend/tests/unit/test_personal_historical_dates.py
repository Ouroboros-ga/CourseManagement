from datetime import date

import pytest

from app.modules.academic.enrollment_models import (
    CourseParticipation,
    StudentEnrollment,
    TeachingClassAudience,
)
from app.modules.academic.publication_service import MyAcademicSourceService
from app.modules.academic.roster_index import RosterIndex
from tests.unit.test_academic_publication import prepare, publish
from tests.unit.test_campus_configuration import campus as campus_fixture


@pytest.fixture(name='campus')
def fixture():
    yield from campus_fixture.__wrapped__()


@pytest.mark.parametrize('confirmed,origin,expected', [
    (False, 'MIGRATION_CURRENT_ONLY', 1),
    (True, 'MIGRATION_CURRENT_ONLY', 0),
    (False, 'MANUAL', 1),
    (False, None, 1),
    (True, None, 0),
])
def test_personal_projection_never_changes_formal_roster(campus, confirmed, origin, expected):
    db, teacher, a, _, teaching, _, student, user, _ = prepare(campus)
    db.add(TeachingClassAudience(teaching_class_id=teaching.id,
                                administrative_class_id=student.administrative_class_id))
    db.add(StudentEnrollment(student_id=student.id,
                             administrative_class_id=student.administrative_class_id,
                             college_id=int(a['id']), effective_from=date(2026, 10, 14),
                             status='ENROLLED', revision=0, historical_confirmed=confirmed,
                             superseded=False, snapshot={'origin': origin}))
    db.commit()
    publish(db, teacher, a['id'], teaching.semester_id)
    entries = MyAcademicSourceService(db, user.id).initialize(teaching.semester_id)['entries']
    assert sum('2026-09-07' in e['occurrence_dates'] for e in entries) == expected
    assert RosterIndex(db, [teaching.id]).at(date(2026, 9, 7))[teaching.id] == []
    assert db.query(StudentEnrollment).one().effective_from == date(2026, 10, 14)


def test_real_enrollment_changes_disable_back_projection(campus):
    db, teacher, a, _, teaching, _, student, user, _ = prepare(campus)
    for revision, start, end in [(0, date(2026, 10, 14), date(2026, 11, 1)),
                                 (1, date(2026, 11, 1), None)]:
        db.add(StudentEnrollment(student_id=student.id,
                                 administrative_class_id=student.administrative_class_id,
                                 college_id=int(a['id']), effective_from=start, effective_to=end,
                                 status='ENROLLED', revision=revision, historical_confirmed=False,
                                 superseded=False, snapshot={'origin': 'MIGRATION_CURRENT_ONLY'}))
    db.commit()
    publish(db, teacher, a['id'], teaching.semester_id)
    entries = MyAcademicSourceService(db, user.id).initialize(teaching.semester_id)['entries']
    assert not any('2026-09-07' in e['occurrence_dates'] for e in entries)


def test_initial_import_projection_does_not_backdate_explicit_course_membership(campus):
    db, teacher, a, _, teaching, _, student, user, _ = prepare(campus)
    db.add(TeachingClassAudience(
        teaching_class_id=teaching.id,
        administrative_class_id=student.administrative_class_id,
    ))
    db.add(StudentEnrollment(
        student_id=student.id,
        administrative_class_id=student.administrative_class_id,
        college_id=int(a['id']), effective_from=date(2026, 10, 14),
        status='ENROLLED', revision=0, historical_confirmed=False, snapshot={},
    ))
    db.add(CourseParticipation(
        teaching_class_id=teaching.id, student_id=student.id,
        effective_from=date(2026, 10, 14), source='EXPLICIT',
    ))
    db.commit()
    publish(db, teacher, a['id'], teaching.semester_id)
    entries = MyAcademicSourceService(db, user.id).initialize(teaching.semester_id)['entries']
    assert not any('2026-09-07' in e['occurrence_dates'] for e in entries)
