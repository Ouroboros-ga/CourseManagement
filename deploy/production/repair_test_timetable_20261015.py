"""Explicitly authorized semester-2 TEST data repair. Preview unless --apply is given.

Run with the release backend on PYTHONPATH and migration credentials in the environment.
Never disable foreign keys; retain accounts, enrollment, configuration and other semesters.
"""

import argparse
import json
from collections import Counter

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.academic.publication_service import AcademicPublicationService
from app.modules.audit.models import AuditLog
from app.modules.identity.models import Role, UserAccount, UserRole
from app.modules.identity.service import CurrentUser


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    url = get_settings().database_url
    assert make_url(url).database == "course_management"
    engine = create_engine(url, pool_pre_ping=True)
    with Session(engine) as db:
        def scalar(sql):
            return db.scalar(text(sql))

        batches = list(db.execute(text(
            "SELECT DATE(created_at) AS day,filename,payload_json FROM import_batch "
            "WHERE semester_id=2 AND target='grid_timetable' AND status='CONFIRMED' "
            "AND DATE(created_at) IN ('2026-10-07','2026-10-11')"
        )).mappings())
        datasets = {"2026-10-07": {}, "2026-10-11": {}}
        for batch in batches:
            payload = batch["payload_json"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            rows = Counter(json.dumps(
                {k: v for k, v in row.items() if k not in {"start_period", "end_period"}},
                sort_keys=True, ensure_ascii=False,
            ) for row in payload["courses"])
            day = str(batch["day"])
            assert batch["filename"] not in datasets[day], "Ambiguous batch file"
            datasets[day][batch["filename"]] = rows
        assert len(datasets["2026-10-07"]) == 32
        assert datasets["2026-10-07"] == datasets["2026-10-11"], "Non-time changes need review"
        before = {
            "schedules": scalar("SELECT COUNT(*) FROM course_schedule WHERE semester_id=2"),
            "old": scalar("SELECT COUNT(*) FROM course_schedule WHERE semester_id=2 AND DATE(created_at)='2026-10-07' AND status='ACTIVE'"),
            "duplicate": scalar("SELECT COUNT(*) FROM course_schedule WHERE semester_id=2 AND DATE(created_at)='2026-10-11' AND status='ACTIVE'"),
            "tasks": scalar("SELECT COUNT(*) FROM inspection_task WHERE semester_id=2"),
            "personal": scalar("SELECT COUNT(*) FROM personal_timetable WHERE semester_id=2"),
        }
        assert before["old"] == before["duplicate"] == 471
        assert before["personal"] == 2
        user = db.scalar(select(UserAccount).join(UserRole, UserRole.user_id == UserAccount.id)
                         .join(Role, Role.id == UserRole.role_id)
                         .where(Role.code == "SUPER_ADMIN", UserAccount.status == "ACTIVE")
                         .order_by(UserAccount.id).limit(1))
        assert user is not None
        actor = CurrentUser(user.id, None, user.display_name, "ACTIVE", ["SUPER_ADMIN"], [])
        report = {"semester_id": "2", "matched_source_files": 32, "before": before,
                  "status": "preview", "historical_enrollment_changed": False}
        if not args.apply:
            print(json.dumps(report))
            return
        # The application must be stopped by the caller before this locked transaction.
        db.execute(text("SELECT id FROM semester WHERE id=2 FOR UPDATE"))
        for statement in (
            "DELETE FROM personal_timetable WHERE semester_id=2",
            "DELETE s FROM published_schedule_student s JOIN published_schedule p ON p.id=s.published_schedule_id JOIN academic_publication a ON a.id=p.publication_id WHERE a.semester_id=2",
            "DELETE p FROM published_schedule p JOIN academic_publication a ON a.id=p.publication_id WHERE a.semester_id=2",
            "DELETE p FROM publication_audience p JOIN academic_publication a ON a.id=p.publication_id WHERE a.semester_id=2",
            "DELETE FROM academic_publication WHERE semester_id=2",
            "DELETE FROM assignment_confirmation_plan WHERE semester_id=2",
            "DELETE i FROM configuration_impact_item i JOIN inspection_task t ON t.id=i.task_id WHERE t.semester_id=2",
            "DELETE a FROM inspection_assignment a JOIN inspection_task t ON t.id=a.task_id WHERE t.semester_id=2",
            "DELETE FROM inspection_task WHERE semester_id=2",
            "DELETE FROM course_schedule WHERE semester_id=2 AND DATE(created_at)='2026-10-11'",
        ):
            db.execute(text(statement))
        assert scalar("SELECT COUNT(*) FROM course_schedule WHERE semester_id=2") == before["schedules"] - 471
        assert scalar("SELECT COUNT(*) FROM inspection_task WHERE semester_id=2") == 0
        assert scalar("SELECT COUNT(*) FROM personal_timetable WHERE semester_id=2") == 0
        report["publications"] = []
        colleges = list(db.scalars(text(
            "SELECT DISTINCT college_id FROM course_schedule WHERE semester_id=2 "
            "AND status='ACTIVE' AND college_id IS NOT NULL ORDER BY college_id"
        )))
        # Validate EVERY source before the single commit, then publish in the same transaction.
        assert colleges == [1], "Unexpected publication scope"
        service = AcademicPublicationService(db, actor, 1)
        preview = service.preview(2)
        assert preview["schedule_count"] == 399
        db.add(AuditLog(actor_user_id=user.id, action="academic.test_timetable.repair",
                        resource_type="semester", resource_id="2", before_json=before,
                        after_json={"source_batch_day": "2026-10-07", "removed_duplicate": 471,
                                    "test_tasks_cleared": before["tasks"],
                                    "personal_copies_reset": before["personal"]}))
        # publish() commits cleanup, audit and new immutable publication together.
        result = service.publish(2, preview["source_revision"])
        report["publications"].append(result)
        report.update(status="applied", remaining_schedules=before["schedules"]-471,
                      published_schedules=preview["schedule_count"])
        print(json.dumps(report))


if __name__ == "__main__":
    main()
