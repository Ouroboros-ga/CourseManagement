import pytest
from app.modules.academic.models import Semester
from app.modules.file.service import FileService
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_file_access import setup
from tests.unit.test_scoped_reports import create_report


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def test_report_file_links_require_verified_version_and_matching_college(campus, monkeypatch):
    actor, (own, foreign) = setup(campus, monkeypatch)
    db = campus[1]
    sid = db.scalar(select(Semester.id))
    versions = []
    for file, college in [(own, campus[4]), (foreign, campus[5])]:
        file.category = "REPORT_FILE"
        file.uploader_user_id = None
        _, version = create_report(db, int(college["id"]), sid, 2)
        version.excel_file_id = file.id
        versions.append(version)
    db.commit()
    service = FileService(db)
    assert service.can_access(actor, own)
    assert not service.can_access(actor, foreign)
    versions[0].college_id_snapshot = None
    db.commit()
    assert not service.can_access(actor, own)
