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


def test_smart_sample_target_classes_only_and_custom_quotas():
    # 模拟包含 5 个班级的课表候选
    # 用户仅选定 计算机2503 (id=3), 计算机2502 (id=2), 计算机2501 (id=1)
    # 并配置: 2503 抽 2 节, 2502 抽 1 节, 2501 抽 1 节
    # 其余班级 (机械2501, 英语2501) 不应被抽查
    from app.modules.academic.models import AdministrativeClass
    from app.modules.inspection.schemas import ClassQuotaConfig

    d_mon = date(2026, 10, 5)
    d_tue = date(2026, 10, 6)
    d_wed = date(2026, 10, 7)
    d_thu = date(2026, 10, 8)

    plan_items = [
        # 计算机2503 (4门候选)
        _make_dummy_plan_item(101, "计算机2503", d_mon, start_period=1),
        _make_dummy_plan_item(102, "计算机2503", d_tue, start_period=1),
        _make_dummy_plan_item(103, "计算机2503", d_wed, start_period=1),
        _make_dummy_plan_item(104, "计算机2503", d_thu, start_period=1),
        # 计算机2502 (3门候选)
        _make_dummy_plan_item(201, "计算机2502", d_mon, start_period=1),
        _make_dummy_plan_item(202, "计算机2502", d_tue, start_period=1),
        _make_dummy_plan_item(203, "计算机2502", d_wed, start_period=1),
        # 计算机2501 (3门候选)
        _make_dummy_plan_item(301, "计算机2501", d_mon, start_period=1),
        _make_dummy_plan_item(302, "计算机2501", d_tue, start_period=1),
        _make_dummy_plan_item(303, "计算机2501", d_wed, start_period=1),
        # 其他不相关的班级 (大量课次)
        _make_dummy_plan_item(401, "机械2501", d_mon, start_period=1),
        _make_dummy_plan_item(402, "机械2501", d_tue, start_period=1),
        _make_dummy_plan_item(501, "英语2501", d_wed, start_period=1),
        _make_dummy_plan_item(502, "英语2501", d_thu, start_period=1),
    ]

    mock_service = MagicMock()
    # 模拟查询 AdministrativeClass 和 TeachingClass
    target_acs = [
        AdministrativeClass(id=3, class_code="CS2503", class_name="计算机2503"),
        AdministrativeClass(id=2, class_code="CS2502", class_name="计算机2502"),
        AdministrativeClass(id=1, class_code="CS2501", class_name="计算机2501"),
    ]
    target_tcs = [
        TeachingClass(id=10, semester_id=1, status="ACTIVE"),
        TeachingClass(id=20, semester_id=1, status="ACTIVE"),
        TeachingClass(id=30, semester_id=1, status="ACTIVE"),
    ]

    mock_service._session.execute.side_effect = [
        MagicMock(scalars=lambda: MagicMock(all=lambda: target_acs)),
        MagicMock(scalars=lambda: MagicMock(all=lambda: target_tcs)),
    ]
    mock_service._build_course_plan_core.return_value = plan_items
    mock_service._repo.find_task_ids_by_keys.return_value = {}

    semester = Semester(id=1, name="2026秋")
    req = SmartSampleRequest(
        semester_id=1,
        week_no=6,
        morning_only=True,
        max_tasks_per_class=1,  # 默认 1 节
        target_class_ids=[3, 2, 1],
        class_quotas=[
            ClassQuotaConfig(class_id=3, class_name="计算机2503", max_tasks=2),
            ClassQuotaConfig(class_id=2, class_name="计算机2502", max_tasks=1),
            ClassQuotaConfig(class_id=1, class_name="计算机2501", max_tasks=1),
        ],
        exclude_already_generated=False,
        random_seed=42,
    )

    res = smart_sample_occurrences(mock_service, semester, req)

    # 验证总推荐课次数: 2 + 1 + 1 = 4 节
    assert res["sampled_count"] == 4
    class_names = [it["class_name"] for it in res["items"]]
    from collections import Counter
    cnt = Counter(class_names)

    # 验证各班抽选数量精准匹配各自独立设定的配额
    assert cnt["计算机2503"] == 2
    assert cnt["计算机2502"] == 1
    assert cnt["计算机2501"] == 1

    # 验证绝无其他班级被选入
    assert "机械2501" not in cnt
    assert "英语2501" not in cnt

    # 验证计算机2503抽选的2节课分散在不同日期
    dates_2503 = [it["inspection_date"] for it in res["items"] if it["class_name"] == "计算机2503"]
    assert len(set(dates_2503)) == 2


def test_smart_sample_single_class_only():
    # 测试仅抽查单个指定班级（如仅计算机2503，配额 2 节）
    from app.modules.academic.models import AdministrativeClass
    from app.modules.inspection.schemas import ClassQuotaConfig

    d_mon = date(2026, 10, 5)
    d_tue = date(2026, 10, 6)
    d_wed = date(2026, 10, 7)

    plan_items = [
        _make_dummy_plan_item(101, "计算机2503", d_mon, start_period=1),
        _make_dummy_plan_item(102, "计算机2503", d_tue, start_period=1),
        _make_dummy_plan_item(103, "计算机2503", d_wed, start_period=1),
        _make_dummy_plan_item(201, "计算机2502", d_mon, start_period=1),
    ]

    mock_service = MagicMock()
    mock_service._session.execute.side_effect = [
        MagicMock(scalars=lambda: MagicMock(all=lambda: [
            AdministrativeClass(id=3, class_code="CS2503", class_name="计算机2503")
        ])),
        MagicMock(scalars=lambda: MagicMock(all=lambda: [
            TeachingClass(id=10, semester_id=1, status="ACTIVE")
        ])),
    ]
    mock_service._build_course_plan_core.return_value = plan_items
    mock_service._repo.find_task_ids_by_keys.return_value = {}

    semester = Semester(id=1, name="2026秋")
    req = SmartSampleRequest(
        semester_id=1,
        week_no=6,
        morning_only=True,
        target_class_ids=[3],
        class_quotas=[ClassQuotaConfig(class_id=3, class_name="计算机2503", max_tasks=2)],
        exclude_already_generated=False,
        random_seed=42,
    )

    res = smart_sample_occurrences(mock_service, semester, req)
    assert res["sampled_count"] == 2
    for it in res["items"]:
        assert it["class_name"] == "计算机2503"
