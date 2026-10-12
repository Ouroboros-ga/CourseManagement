"""考勤统计返回明细与班级置顶数据结构测试。"""

from app.modules.report.aggregation import build_classes
from app.modules.report.schemas import AbnormalDetailItem, AttendanceStatsResponse, ClassStatsItem, OverallStats


def test_class_stats_item_includes_class_id() -> None:
    item = ClassStatsItem(
        class_id=101,
        class_name="数科2401",
        head_teacher="陈芙佳",
        counselor="陈芙佳",
        expected_count=39,
        abnormal_count=4,
        normal_count=35,
        leave_count=0,
        late_count=0,
        absent_count=4,
        abnormal_rate=0.103,
        attendance_rate=0.897,
        class_ratio_available=True,
        excluded_task_count=0,
    )
    assert item.class_id == "101"
    assert item.class_name == "数科2401"


def test_build_classes_extracts_class_id() -> None:
    expected = {1: (39, 39)}
    roster_by_tc = {(1, "数科2401"): 39}
    att_by_tc = {(1, "数科2401"): {"NORMAL": 35, "LEAVE": 0, "LATE": 0, "ABSENT": 4}}
    class_duties = {"数科2401": ("陈芙佳", "陈芙佳", 202)}

    classes = build_classes(expected, roster_by_tc, att_by_tc, class_duties=class_duties)
    assert len(classes) == 1
    c = classes[0]
    assert c.class_id == "202"
    assert c.class_name == "数科2401"
    assert c.absent_count == 4


def test_attendance_stats_response_includes_details() -> None:
    detail = AbnormalDetailItem(
        task_id=88,
        attendance_type="ABSENT",
        student_no="2024001",
        name="张三",
        class_name_snapshot="数科2401",
        inspection_date="2026-10-12",
        date_display="10.12",
        course_name="高等数学",
        inspection_type="COURSE",
        start_period=1,
        end_period=2,
        classroom="1-201",
        teacher_name="李老师",
    )
    resp = AttendanceStatsResponse(
        semester_id=1,
        week_no=7,
        date_from=None,
        date_to=None,
        eligible_task_count=1,
        overall=OverallStats(
            statistics_available=True,
            expected_count=39,
            abnormal_count=4,
            normal_count=35,
            leave_count=0,
            late_count=0,
            absent_count=4,
            abnormal_rate=0.103,
            attendance_rate=0.897,
        ),
        classes=[],
        details=[detail],
    )
    assert resp.details is not None
    assert len(resp.details) == 1
    assert resp.details[0].student_no == "2024001"
    assert resp.details[0].course_name == "高等数学"
    assert resp.details[0].start_period == 1
