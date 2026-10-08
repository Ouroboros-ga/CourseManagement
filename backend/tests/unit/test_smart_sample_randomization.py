from datetime import date
from unittest.mock import MagicMock
import pytest
from app.modules.academic.models import Semester, TeachingClass
from app.modules.inspection.course_occurrences import smart_sample_occurrences
from app.modules.inspection.schemas import SmartSampleRequest
from app.modules.inspection.service import InspectionService, PlanItem


def _make_dummy_plan_item(
    schedule_id: int,
    class_name: str,
    insp_date: date,
    start_period: int = 1,
) -> PlanItem:
    return PlanItem(
        task_key=f"task_{schedule_id}_{insp_date}",
        semester_id=1,
        inspection_date=insp_date,
        week_no=6,
        inspection_type="COURSE",
        start_period=start_period,
        end_period=start_period + 1,
        course_schedule_id=schedule_id,
        teaching_class_id=schedule_id,
        administrative_class_id=schedule_id,
        course_name_snapshot="课程",
        class_name_snapshot=class_name,
        classroom_snapshot="3-201",
        require_photo_snapshot=False,
        student_ids=[1, 2, 3],
    )


def test_smart_sample_eliminates_monday_bias_and_balances_days():
    # 模拟 30 个班级，每个班在周一 (10-05)、周三 (10-07)、周五 (10-09) 均有早八课
    d_mon = date(2026, 10, 5)
    d_wed = date(2026, 10, 7)
    d_fri = date(2026, 10, 9)

    plan_items = []
    sid = 1
    for c_idx in range(30):
        c_name = f"班级_{c_idx:02d}"
        plan_items.append(_make_dummy_plan_item(sid, c_name, d_mon, start_period=1))
        sid += 1
        plan_items.append(_make_dummy_plan_item(sid, c_name, d_wed, start_period=1))
        sid += 1
        plan_items.append(_make_dummy_plan_item(sid, c_name, d_fri, start_period=1))
        sid += 1

    mock_service = MagicMock()
    mock_service._session.execute.return_value.scalars.return_value.all.return_value = [
        TeachingClass(id=1, semester_id=1, status="ACTIVE")
    ]
    mock_service._build_course_plan_core.return_value = plan_items
    mock_service._repo.find_task_ids_by_keys.return_value = {}

    semester = Semester(id=1, name="2026秋")
    req = SmartSampleRequest(
        semester_id=1,
        week_no=6,
        morning_only=True,
        max_tasks_per_class=1,
        exclude_already_generated=False,
        random_seed=123,
    )

    res = smart_sample_occurrences(mock_service, semester, req)
    assert res["sampled_count"] == 30

    # 统计各天被选中的数量
    from collections import Counter
    day_counts = Counter(it["inspection_date"] for it in res["items"])

    # 在老算法下，周一会是 30，周三 0，周五 0。
    # 在新算法下，30 个班级应当在周一、周三、周五均匀分散，各天应各占 10 个左右（绝不能出现周一独占>20个的情况）
    assert day_counts[d_mon] > 0
    assert day_counts[d_wed] > 0
    assert day_counts[d_fri] > 0
    assert 7 <= day_counts[d_mon] <= 13
    assert 7 <= day_counts[d_wed] <= 13
    assert 7 <= day_counts[d_fri] <= 13


def test_smart_sample_multi_task_per_class_different_days():
    # 当每班上限为 2 节时，同一个班级抽选的 2 节课应当分散在不同日期
    d_mon = date(2026, 10, 5)
    d_tue = date(2026, 10, 6)
    d_wed = date(2026, 10, 7)

    plan_items = [
        _make_dummy_plan_item(1, "计算机2501", d_mon, start_period=1),
        _make_dummy_plan_item(2, "计算机2501", d_tue, start_period=1),
        _make_dummy_plan_item(3, "计算机2501", d_wed, start_period=1),
    ]

    mock_service = MagicMock()
    mock_service._session.execute.return_value.scalars.return_value.all.return_value = [
        TeachingClass(id=1, semester_id=1, status="ACTIVE")
    ]
    mock_service._build_course_plan_core.return_value = plan_items
    mock_service._repo.find_task_ids_by_keys.return_value = {}

    semester = Semester(id=1, name="2026秋")
    req = SmartSampleRequest(
        semester_id=1,
        week_no=6,
        morning_only=True,
        max_tasks_per_class=2,
        exclude_already_generated=False,
        random_seed=42,
    )

    res = smart_sample_occurrences(mock_service, semester, req)
    assert res["sampled_count"] == 2
    dates = [it["inspection_date"] for it in res["items"]]
    assert len(set(dates)) == 2, "同一班级抽选的 2 节课应当分散在不同日期"


def test_smart_sample_reroll_produces_different_recommendations():
    # 不传入 seed 时，两次运算应具备随机性，能换一批推荐
    d_mon = date(2026, 10, 5)
    d_tue = date(2026, 10, 6)
    d_wed = date(2026, 10, 7)
    d_thu = date(2026, 10, 8)
    d_fri = date(2026, 10, 9)

    plan_items = []
    sid = 1
    for c_idx in range(20):
        c_name = f"Class_{c_idx}"
        for d in [d_mon, d_tue, d_wed, d_thu, d_fri]:
            plan_items.append(_make_dummy_plan_item(sid, c_name, d, start_period=1))
            sid += 1

    mock_service = MagicMock()
    mock_service._session.execute.return_value.scalars.return_value.all.return_value = [
        TeachingClass(id=1, semester_id=1, status="ACTIVE")
    ]
    mock_service._build_course_plan_core.return_value = plan_items
    mock_service._repo.find_task_ids_by_keys.return_value = {}

    semester = Semester(id=1, name="2026秋")
    req = SmartSampleRequest(
        semester_id=1,
        week_no=6,
        morning_only=True,
        max_tasks_per_class=1,
        exclude_already_generated=False,
        random_seed=None,
    )

    run_1 = smart_sample_occurrences(mock_service, semester, req)
    run_2 = smart_sample_occurrences(mock_service, semester, req)

    keys_1 = [it["course_schedule_id"] for it in run_1["items"]]
    keys_2 = [it["course_schedule_id"] for it in run_2["items"]]
    assert keys_1 != keys_2, "不指定种子时，多次执行抽样应能随机换一批"
