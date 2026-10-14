import pytest
from app.core.exceptions import NotFoundError
from app.modules.report.listing import ReportListingService
from app.modules.report.models import Report, ReportVersion
from app.modules.report.version_service import ReportService
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_scoped_file_access import setup


@pytest.fixture(name="campus")
def fixture():
    yield from campus_fixture.__wrapped__()


def create_report(db, cid, sid, week):
    report = Report(college_id=cid, semester_id=sid, week_no=week, scope="COLLEGE")
    db.add(report)
    db.flush()
    version = ReportVersion(
        report_id=report.id, version_no=1, status="PUBLISHED", college_id_snapshot=cid
    )
    db.add(version)
    db.commit()
    return report, version


def test_two_colleges_can_keep_independent_reports_for_same_week(campus, monkeypatch):
    from app.modules.academic.models import Semester

    actor, _ = setup(campus, monkeypatch)
    db = campus[1]
    semester = db.scalar(select(Semester))
    one, _ = create_report(db, int(campus[4]["id"]), semester.id, 2)
    two, _ = create_report(db, int(campus[5]["id"]), semester.id, 2)
    assert one.id != two.id


def test_explicit_report_grant_is_not_rejected_by_a_cached_role_label(campus, monkeypatch):
    from dataclasses import replace

    from app.core.config import get_settings
    from app.modules.academic.models import Semester

    from tests.unit.test_campus_configuration import grant
    from tests.unit.test_scoped_academic import records

    config, db, admin, reader, a, b = campus
    records(db, a, b)
    grant(config, admin, reader, a, ["report.read"])
    actor = replace(reader, roles=["STUDENT"])
    monkeypatch.setattr(get_settings(), "campus_business_scoped_enabled", True)
    sid = db.scalar(select(Semester.id))
    report, _ = create_report(db, int(a["id"]), sid, 2)
    result = ReportListingService(db, college_id=int(a["id"])).list_reports(
        actor, semester_id=sid, week_no=None, page=1, page_size=20
    )
    assert [row["report_id"] for row in result["items"]] == [str(report.id)]


def test_report_listing_versions_and_download_hide_foreign_owner(campus, monkeypatch):
    from app.modules.academic.models import Semester

    actor, _ = setup(campus, monkeypatch)
    db = campus[1]
    sid = db.scalar(select(Semester.id))
    own, _ = create_report(db, int(campus[4]["id"]), sid, 2)
    other, version = create_report(db, int(campus[5]["id"]), sid, 3)
    result = ReportListingService(db).list_reports(
        actor, semester_id=sid, week_no=None, page=1, page_size=20
    )
    assert result["total"] == 1 and result["items"][0]["report_id"] == str(own.id)
    with pytest.raises(NotFoundError):
        ReportService(db).list_versions(actor, other.id)
    with pytest.raises(NotFoundError):
        ReportService(db).download(actor, version.id, kind="EXCEL")


def test_unknown_legacy_owner_still_has_unique_school_report_key(campus, monkeypatch):
    from app.modules.academic.models import Semester

    _, _ = setup(campus, monkeypatch)
    db = campus[1]
    sid = db.scalar(select(Semester.id))
    create_report(db, None, sid, 2)
    with pytest.raises(IntegrityError):
        create_report(db, None, sid, 2)
    db.rollback()


def test_metadata_backfill_does_not_authorize_unverified_legacy_report_content(campus, monkeypatch):
    from app.modules.academic.models import Semester

    actor, _ = setup(campus, monkeypatch)
    db = campus[1]
    sid = db.scalar(select(Semester.id))
    report, version = create_report(db, int(campus[4]["id"]), sid, 2)
    version.college_id_snapshot = None
    db.commit()
    assert (
        ReportListingService(db).list_reports(
            actor, semester_id=sid, week_no=None, page=1, page_size=20
        )["total"]
        == 0
    )
    with pytest.raises(NotFoundError):
        ReportService(db).download(actor, version.id, kind="EXCEL")


def test_other_college_revision_does_not_mark_own_report_as_changed(campus, monkeypatch):
    from app.modules.academic.models import Semester
    from app.modules.report.models import ReportSourceRevision

    actor, _ = setup(campus, monkeypatch)
    db = campus[1]
    sid = db.scalar(select(Semester.id))
    report, version = create_report(db, int(campus[4]["id"]), sid, 2)
    version.source_revision = 1
    db.add_all(
        [
            ReportSourceRevision(
                ownership_scope_id=int(campus[4]["id"]), semester_id=sid, week_no=2, revision=1
            ),
            ReportSourceRevision(
                ownership_scope_id=int(campus[5]["id"]), semester_id=sid, week_no=2, revision=9
            ),
        ]
    )
    db.commit()
    result = ReportListingService(db).list_reports(
        actor, semester_id=sid, week_no=None, page=1, page_size=20
    )
    assert result["items"][0]["source_changed"] is False
