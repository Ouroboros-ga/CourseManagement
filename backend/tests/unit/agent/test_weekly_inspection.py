import importlib
from datetime import datetime

import pytest
from sqlalchemy import select
from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_group_sampling_business import arrange as business


@pytest.fixture(name="case")
def fixture(monkeypatch):
    original = campus_fixture.__wrapped__()
    campus = next(original)
    try:
        db, actor, college, semester, group, student, teaching, _ = business(campus, monkeypatch)
        from app.core.config import get_settings

        monkeypatch.setattr(get_settings(), "agent_weekly_inspection_enabled", True)
        module = importlib.import_module("app.modules.inspection.weekly_service")
        monkeypatch.setattr(module, "utcnow", lambda: datetime(2026, 9, 1))
        yield db, actor, int(college["id"]), semester, int(group["id"]), student, teaching
    finally:
        original.close()


def arrange(case):
    module = importlib.import_module("app.modules.inspection.weekly_service")
    db, actor, cid, semester, gid, student, teaching = case
    service = module.WeeklyInspectionService(db, cid, gid, semester.id, environment="dev")
    body = {
        "current_version": 0,
        "enabled": True,
        "first_week": 2,
        "last_week": 3,
        "run_weekday": 5,
        "run_time": "16:00",
        "counts": {str(student.administrative_class_id): 1},
        "course_type_ids": [str(teaching.course_type_id)],
        "require_photo": True,
    }
    return service, body


def test_weekly_plan_uses_real_owner_and_due_time_is_shanghai_previous_week(case):
    service, body = arrange(case)
    plan = service.save(case[1], body)
    assert plan["authorizer_user_id"] == str(case[1].id)
    assert plan["publication_mode"] == "DRAFT_ONLY"
    assert plan["version"] == 1
    assert service.register_due(int(plan["id"]), now=datetime(2026, 9, 4, 7, 59)) == []
    runs = service.register_due(int(plan["id"]), now=datetime(2026, 9, 4, 8))
    assert len(runs) == 1 and runs[0]["target_week"] == 2
    assert runs[0]["date_from"] == "2026-09-07" and runs[0]["date_to"] == "2026-09-13"
    assert service.register_due(int(plan["id"]), now=datetime(2026, 9, 4, 9)) == []


def test_generation_and_receipt_are_durable_replay_does_not_redraw_or_assign(case):
    from app.modules.inspection.models import InspectionAssignment, InspectionTask

    service, body = arrange(case)
    plan = service.save(case[1], body)
    run = service.register_due(int(plan["id"]), now=datetime(2026, 9, 4, 8))[0]
    generated = service.generate(int(run["id"]), now=datetime(2026, 9, 4, 8))
    assert generated["status"] == "GENERATED" and len(generated["task_ids"]) == 1
    ids = generated["task_ids"]
    assert service.generate(int(run["id"]), now=datetime(2026, 9, 4, 8))["task_ids"] == ids
    tasks = list(
        case[0].scalars(select(InspectionTask).where(InspectionTask.id.in_(map(int, ids))))
    )
    assert len(tasks) == 1 and tasks[0].group_id == case[4]
    assert case[0].query(InspectionAssignment).count() == 0
    draft = service.prepare(int(run["id"]), now=datetime(2026, 9, 4, 8))
    assert draft["status"] == "PREPARED" and draft["task_ids"] == ids
    assert draft["assignment_plan_id"]
    assert len(draft["result"]["unassigned"]) == 1
    assert case[0].query(InspectionAssignment).count() == 0


def test_pause_or_edit_fences_registered_run_without_rewriting_its_scope(case):
    from app.core.exceptions import ConflictError

    service, body = arrange(case)
    plan = service.save(case[1], body)
    run = service.register_due(int(plan["id"]), now=datetime(2026, 9, 4, 8))[0]
    service.save(case[1], {**body, "current_version": 1, "enabled": False})
    with pytest.raises(ConflictError):
        service.generate(int(run["id"]), now=datetime(2026, 9, 4, 9))
    with pytest.raises(ConflictError):
        service.save(case[1], {**body, "current_version": 1})
    assert service.register_due(int(plan["id"]), now=datetime(2026, 9, 4, 9)) == []


def test_past_target_week_is_recorded_missed_without_generating_past_tasks(case):
    service, body = arrange(case)
    plan = service.save(case[1], body)
    runs = service.register_due(int(plan["id"]), now=datetime(2026, 9, 14, 0))
    assert len(runs) == 2 and all(run["status"] == "MISSED" for run in runs)


def test_generated_tasks_survive_assignment_failure_and_retry_reuses_them(case, monkeypatch):
    from app.modules.inspection.assignment_plan_service import AssignmentPlanService

    service, body = arrange(case)
    plan = service.save(case[1], body)
    run = service.register_due(int(plan["id"]), now=datetime(2026, 9, 4, 8))[0]
    generated = service.generate(int(run["id"]), now=datetime(2026, 9, 4, 8))
    original = AssignmentPlanService.preview_in_transaction

    def failure(*args, **kwargs):
        raise RuntimeError("synthetic planner failure")

    monkeypatch.setattr(AssignmentPlanService, "preview_in_transaction", failure)
    with pytest.raises(RuntimeError):
        service.prepare(int(run["id"]), now=datetime(2026, 9, 4, 8))
    monkeypatch.setattr(AssignmentPlanService, "preview_in_transaction", original)
    assert (
        service.generate(int(run["id"]), now=datetime(2026, 9, 4, 8))["task_ids"]
        == generated["task_ids"]
    )
    assert service.prepare(int(run["id"]), now=datetime(2026, 9, 4, 8))["status"] == "PREPARED"


def test_generation_receipt_failure_rolls_back_tasks_and_original_domain_audit(case, monkeypatch):
    from app.modules.inspection.models import InspectionTask

    service, body = arrange(case)
    plan = service.save(case[1], body)
    run = service.register_due(int(plan["id"]), now=datetime(2026, 9, 4, 8))[0]
    before = case[0].query(InspectionTask).count()
    original = service._audit

    def fail_receipt(*args):
        raise RuntimeError("synthetic receipt failure")

    monkeypatch.setattr(service, "_audit", fail_receipt)
    with pytest.raises(RuntimeError):
        service.generate(int(run["id"]), now=datetime(2026, 9, 4, 8))
    assert case[0].query(InspectionTask).count() == before
    monkeypatch.setattr(service, "_audit", original)
    assert service.generate(int(run["id"]), now=datetime(2026, 9, 4, 8))["status"] == "GENERATED"


def test_disabled_owner_and_changed_group_rules_cannot_use_saved_authorization(case):
    from app.core.exceptions import ConflictError, PermissionDeniedError
    from app.modules.identity.models import UserAccount
    from app.modules.organization.service import CampusService
    from app.modules.volunteer.models import VolunteerGroup

    service, body = arrange(case)
    plan = service.save(case[1], body)
    run = service.register_due(int(plan["id"]), now=datetime(2026, 9, 4, 8))[0]
    user = case[0].get(UserAccount, case[1].id)
    user.status = "DISABLED"
    case[0].commit()
    with pytest.raises(PermissionDeniedError):
        service.generate(int(run["id"]), now=datetime(2026, 9, 4, 8))
    user.status = "ACTIVE"
    case[0].commit()
    group = case[0].get(VolunteerGroup, case[4])
    CampusService(case[0]).publish_group(
        case[1],
        case[2],
        case[4],
        {
            "lock_version": group.lock_version,
            "course_type_ids": body["course_type_ids"],
        },
    )
    with pytest.raises(ConflictError):
        service.generate(int(run["id"]), now=datetime(2026, 9, 4, 8))
    with pytest.raises(ConflictError):
        service.register_due(int(plan["id"]), now=datetime(2026, 9, 11, 8))


def test_policy_cannot_choose_owner_or_auto_publish_and_ignores_pre_authorization_weeks(
    case, monkeypatch
):
    from app.core.exceptions import AppError

    service, body = arrange(case)
    for extra in [
        {"authorizer_user_id": "2"},
        {"publication_mode": "AUTO"},
        {"counts": {"01": 1}},
        {"enabled": "true"},
    ]:
        with pytest.raises(AppError):
            service.save(case[1], {**body, **extra})
    module = importlib.import_module("app.modules.inspection.weekly_service")
    monkeypatch.setattr(module, "utcnow", lambda: datetime(2026, 9, 15))
    plan = service.save(case[1], body)
    assert service.register_due(int(plan["id"]), now=datetime(2026, 9, 16)) == []


def test_teaching_week_origin_change_invalidates_registered_execution(case):
    from datetime import timedelta

    from app.core.exceptions import ConflictError

    service, body = arrange(case)
    plan = service.save(case[1], body)
    run = service.register_due(int(plan["id"]), now=datetime(2026, 9, 4, 8))[0]
    case[3].first_monday += timedelta(weeks=1)
    case[0].commit()
    with pytest.raises(ConflictError, match="校历"):
        service.generate(int(run["id"]), now=datetime(2026, 9, 4, 8))


def test_expired_or_invalidated_draft_can_be_explicitly_rechecked_without_redrawing(case):
    from app.core.exceptions import ConflictError
    from app.modules.inspection.assignment_plan_models import AssignmentConfirmationPlan
    from app.modules.inspection.models import InspectionTask

    service, body = arrange(case)
    plan = service.save(case[1], body)
    run = service.register_due(int(plan["id"]), now=datetime(2026, 9, 4, 8))[0]
    generated = service.generate(int(run["id"]), now=datetime(2026, 9, 4, 8))
    ready = service.prepare(int(run["id"]), now=datetime(2026, 9, 4, 8))
    old = case[0].get(AssignmentConfirmationPlan, ready["assignment_plan_id"])
    old.expires_at = datetime(2026, 8, 31)
    case[0].commit()
    with pytest.raises(ConflictError, match="重新核对"):
        service.prepare(int(run["id"]), now=datetime(2026, 9, 4, 8))
    count = case[0].query(InspectionTask).count()
    rechecked = service.refresh_draft(case[1], int(run["id"]))
    assert rechecked["task_ids"] == generated["task_ids"]
    assert rechecked["assignment_plan_id"] != ready["assignment_plan_id"]
    current = case[0].get(AssignmentConfirmationPlan, rechecked["assignment_plan_id"])
    current.revision = "0" * 64
    case[0].commit()
    refreshed = service.refresh_draft(case[1], int(run["id"]))
    assert refreshed["result"]["revision"] != "0" * 64
    assert case[0].query(InspectionTask).count() == count
    assert case[0].get(AssignmentConfirmationPlan, old.id) is not None


def test_human_committed_draft_replays_publication_receipt_without_a_new_draft(case):
    from app.modules.inspection.assignment_plan_models import AssignmentConfirmationPlan
    from app.modules.inspection.assignment_plan_service import AssignmentPlanService

    service, body = arrange(case)
    plan = service.save(case[1], body)
    run = service.register_due(int(plan["id"]), now=datetime(2026, 9, 4, 8))[0]
    service.generate(int(run["id"]), now=datetime(2026, 9, 4, 8))
    ready = service.prepare(int(run["id"]), now=datetime(2026, 9, 4, 8))
    committed = AssignmentPlanService(case[0], case[1], case[2], case[4]).commit(
        ready["assignment_plan_id"], {"revision": ready["result"]["revision"], "confirmations": []}
    )
    count = case[0].query(AssignmentConfirmationPlan).count()
    replay = service.refresh_draft(case[1], int(run["id"]))
    assert replay["assignment_plan_status"] == "COMMITTED"
    assert replay["publication_result"] == committed
    assert case[0].query(AssignmentConfirmationPlan).count() == count


def test_refresh_invalidates_previous_uncommitted_draft_atomically(case):
    from app.core.exceptions import ConflictError
    from app.modules.inspection.assignment_plan_service import AssignmentPlanService

    service, body = arrange(case)
    plan = service.save(case[1], body)
    run = service.register_due(int(plan["id"]), now=datetime(2026, 9, 4, 8))[0]
    service.generate(int(run["id"]), now=datetime(2026, 9, 4, 8))
    previous = service.prepare(int(run["id"]), now=datetime(2026, 9, 4, 8))
    refreshed = service.refresh_draft(case[1], int(run["id"]))
    assert refreshed["assignment_plan_id"] != previous["assignment_plan_id"]
    with pytest.raises(ConflictError, match="过期"):
        AssignmentPlanService(case[0], case[1], case[2], case[4]).commit(
            previous["assignment_plan_id"],
            {"revision": previous["result"]["revision"], "confirmations": []},
        )


def test_failed_human_recheck_keeps_original_draft_valid_and_removes_partial_new_plan(
    case, monkeypatch
):
    from app.modules.inspection.assignment_plan_models import AssignmentConfirmationPlan
    from app.modules.inspection.assignment_plan_service import AssignmentPlanService
    from app.modules.inspection.weekly_models import WeeklyInspectionExecution

    service, body = arrange(case)
    plan = service.save(case[1], body)
    run = service.register_due(int(plan["id"]), now=datetime(2026, 9, 4, 8))[0]
    service.generate(int(run["id"]), now=datetime(2026, 9, 4, 8))
    old = service.prepare(int(run["id"]), now=datetime(2026, 9, 4, 8))
    expiry = case[0].get(AssignmentConfirmationPlan, old["assignment_plan_id"]).expires_at
    count = case[0].query(AssignmentConfirmationPlan).count()
    original = AssignmentPlanService.preview_in_transaction

    def fail_after_preparing(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic failure after new plan flush")

    monkeypatch.setattr(AssignmentPlanService, "preview_in_transaction", fail_after_preparing)
    with pytest.raises(RuntimeError):
        service.refresh_draft(case[1], int(run["id"]))
    assert case[0].query(AssignmentConfirmationPlan).count() == count
    assert case[0].get(AssignmentConfirmationPlan, old["assignment_plan_id"]).expires_at == expiry
    assert (
        case[0].get(WeeklyInspectionExecution, int(run["id"])).assignment_plan_id
        == old["assignment_plan_id"]
    )


def test_policy_change_between_initial_read_and_scope_lock_requires_retry(case, monkeypatch):
    from app.core.exceptions import ConflictError
    from sqlalchemy import text

    service, body = arrange(case)
    plan = service.save(case[1], body)
    original = service._validate

    def change_after_validation(*args):
        result = original(*args)
        case[0].execute(text("UPDATE weekly_inspection_plan SET version = version + 1"))
        case[0].commit()
        return result

    monkeypatch.setattr(service, "_validate", change_after_validation)
    with pytest.raises(ConflictError):
        service.register_due(int(plan["id"]), now=datetime(2026, 9, 4, 8))


def test_group_limited_owner_remains_limited_and_revocation_stops_background_execution(case):
    from app.core.exceptions import NotFoundError, PermissionDeniedError
    from app.modules.academic.models import AdministrativeClass
    from app.modules.identity.models import UserAccount
    from app.modules.identity.service import CurrentUser
    from app.modules.organization.models import ScopedGrant
    from app.modules.organization.service import CampusService

    service, body = arrange(case)
    user = case[0].scalar(select(UserAccount).where(UserAccount.id != case[1].id))
    reader = CurrentUser(
        user.id, user.username, user.display_name, "ACTIVE", ["SUPER_ADMIN"], ["*"]
    )
    campus = CampusService(case[0])
    grant = {
        "user_id": str(user.id),
        "actions": ["inspection.generate", "assignment.manage"],
        "resource_scope": {"kind": "GROUPS", "ids": [str(case[4])]},
    }
    campus.create_grant(
        case[1],
        case[2],
        {**grant, "preview_revision": campus.preview_grant(case[1], case[2], grant)["revision"]},
    )
    plan = service.save(reader, body)
    assert plan["authorizer_user_id"] == str(user.id)
    foreign = case[0].scalar(
        select(AdministrativeClass.id).where(AdministrativeClass.college_id != case[2])
    )
    with pytest.raises((NotFoundError, PermissionDeniedError)):
        service.save(reader, {**body, "current_version": 1, "counts": {str(foreign): 1}})
    run = service.register_due(int(plan["id"]), now=datetime(2026, 9, 4, 8))[0]
    for row in case[0].scalars(select(ScopedGrant).where(ScopedGrant.user_id == user.id)):
        row.status = "REVOKED"
    case[0].commit()
    with pytest.raises((PermissionDeniedError, NotFoundError)):
        service.generate(int(run["id"]), now=datetime(2026, 9, 4, 8))


def test_pause_remains_possible_after_group_inactivation_and_feature_gate_is_default_closed(
    case, monkeypatch
):
    from app.core.config import get_settings
    from app.core.exceptions import NotFoundError
    from app.modules.volunteer.models import VolunteerGroup

    service, body = arrange(case)
    service.save(case[1], body)
    case[0].get(VolunteerGroup, case[4]).status = "INACTIVE"
    case[0].commit()
    assert service.pause(case[1], 1)["enabled"] is False
    monkeypatch.setattr(get_settings(), "agent_weekly_inspection_enabled", False)
    with pytest.raises(NotFoundError):
        service.pause(case[1], 2)


def test_reopened_file_database_continues_weekly_stages_without_redrawing(case, tmp_path):
    import sqlite3

    from app.modules.inspection.models import InspectionAssignment
    from app.modules.inspection.weekly_service import WeeklyInspectionService
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker

    service, body = arrange(case)
    plan = service.save(case[1], body)
    run = service.register_due(int(plan["id"]), now=datetime(2026, 9, 4, 8))[0]
    path = tmp_path / "weekly.db"
    raw = case[0].bind.raw_connection()
    try:
        with sqlite3.connect(path) as target:
            raw.driver_connection.backup(target)
    finally:
        raw.close()
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    event.listen(
        engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON")
    )
    factory = sessionmaker(bind=engine)
    try:
        with factory() as db:
            reopened = WeeklyInspectionService(db, case[2], case[4], case[3].id, environment="dev")
            generated = reopened.generate(int(run["id"]), now=datetime(2026, 9, 4, 8))
        with factory() as db:
            reopened = WeeklyInspectionService(db, case[2], case[4], case[3].id, environment="dev")
            draft = reopened.prepare(int(run["id"]), now=datetime(2026, 9, 4, 8))
            assert draft["status"] == "PREPARED"
            assert (
                reopened.generate(int(run["id"]), now=datetime(2026, 9, 4, 8))["task_ids"]
                == generated["task_ids"]
            )
            assert db.query(InspectionAssignment).count() == 0
    finally:
        engine.dispose()
