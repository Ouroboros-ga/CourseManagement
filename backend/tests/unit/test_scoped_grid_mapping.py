from datetime import time

import pytest
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.modules.academic.models import PeriodDefinition
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_importer import prepare


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def school_periods(db, sid):
    existing = set(
        db.scalars(select(PeriodDefinition.period_no).where(PeriodDefinition.semester_id == sid))
    )
    for number in range(1, 13):
        if number not in existing:
            db.add(
                PeriodDefinition(
                    semester_id=sid, period_no=number, start_time=time(10), end_time=time(10, 45)
                )
            )
    db.commit()


def test_school_mode_import_preserves_raw_periods_without_college_version(campus, monkeypatch):
    service, db, _, _, sid = prepare(campus)
    school_periods(db, sid)
    monkeypatch.setattr(get_settings(), "campus_scheduling_enabled", False)
    monkeypatch.setattr(
        "app.modules.importer.service.load_grid",
        lambda _: (
            "示例班",
            [
                {
                    "course_name": "示例课",
                    "weekday": "周一",
                    "weeks": "1-2",
                    "period": "10-11",
                    "location": "示例教室",
                }
            ],
        ),
    )
    payload, issues, _ = service._parse_grid_timetable(b"fixture", sid, "示例班课表.xls")
    assert not issues
    assert payload["courses"][0]["start_period"] == 10
    assert payload["courses"][0]["end_period"] == 11


def test_college_mode_still_requires_explicit_mapping(campus, monkeypatch):
    service, db, _, _, sid = prepare(campus)
    school_periods(db, sid)
    monkeypatch.setattr(get_settings(), "campus_scheduling_enabled", True)
    with pytest.raises(AppError):
        service.grid_slot_mapping(sid)
