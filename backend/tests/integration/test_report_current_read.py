"""分配周报版本时必须越过鉴权阶段建立的 RR 旧快照。"""

from datetime import date

import pytest
from app.modules.academic.models import Semester
from app.modules.report.models import Report, ReportVersion
from app.modules.report.repository import ReportVersionRepository
from sqlalchemy import select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


def test_latest_generating_version_visible_after_old_read_snapshot(engine, session):
    semester = Semester(code="REPORT-RR", name="Report RR", first_monday=date(2026, 9, 14),
                        start_date=date(2026, 9, 14), end_date=date(2027, 1, 24),
                        total_weeks=19, status="ACTIVE")
    session.add(semester)
    session.commit()
    semester_id = semester.id
    # 首次 SELECT 明确建立旧快照；另一个事务随后提交 GENERATING。
    assert session.scalar(select(Report.id)) is None
    with Session(engine) as writer:
        report = Report(semester_id=semester_id, week_no=1, scope="COLLEGE", latest_version_no=1)
        writer.add(report)
        writer.flush()
        writer.add(ReportVersion(report_id=report.id, version_no=1,
                                 status="GENERATING", attempt_token="other-generation"))
        writer.commit()
    repository = ReportVersionRepository(session)
    locked = repository.get_or_create_report_for_update(
        semester_id=semester_id, week_no=1, scope="COLLEGE")
    latest = repository.latest_version(locked.id)
    assert latest is not None
    assert latest.version_no == 1 and latest.status == "GENERATING"
