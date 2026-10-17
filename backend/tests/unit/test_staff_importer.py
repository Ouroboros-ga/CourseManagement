"""教职工档案、班级责任关系与任课教师授课关系的导入单元测试（T02）。

覆盖 ACCEPTANCE.md 与 TASK.md 验收指标：
- 前导零、同名、多教师、未知工号按明确匹配规则处理
- 预览不写正式表；缺行和空责任列不结束任职
- 文件/表/行/字段和新旧差异可追溯；陈旧预览 409
- 一次确认失败全部回滚，重试不重复；无学期资料不强塞单学期集合
"""

from datetime import date
from io import BytesIO

import pytest
from app.core.exceptions import ConflictError, PermissionDeniedError
from app.modules.academic.models import (
    AdministrativeClass,
    Course,
    TeachingClass,
)
from app.modules.academic.offering_models import AcademicOffering
from app.modules.academic.staff_models import (
    ClassStaffResponsibility,
    FacultyStaff,
    TeachingStaffAssignment,
)
from app.modules.importer.confirmation_set import ImportConfirmationSet
from app.modules.importer.models import ImportBatch
from app.modules.importer.scoped_service import ScopedImporterService
from app.modules.organization.models import College
from openpyxl import Workbook
from sqlalchemy import select

from tests.unit.test_campus_configuration import campus as campus_fixture
from tests.unit.test_campus_configuration import grant
from tests.unit.test_scoped_academic import records


@pytest.fixture(name="campus")
def configured():
    yield from campus_fixture.__wrapped__()


def sheet(rows: list[list]) -> bytes:
    book = Workbook()
    ws = book.active
    for row in rows:
        ws.append(row)
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()


def setup_env(campus):
    config, db, admin, teacher, a, b = campus
    _, _, _, teaching, _, own, foreign = records(db, a, b)
    grant(
        config,
        admin,
        teacher,
        a,
        [
            "import.execute",
            "student.manage",
            "course_schedule.import",
            "academic.manage",
            "staff.manage",
        ],
    )
    service = ScopedImporterService(db, teacher, int(a["id"]))
    return service, db, teacher, int(a["id"]), int(b["id"]), teaching.semester_id


def test_faculty_staff_preview_does_not_apply_and_preserves_leading_zeros(campus):
    service, db, teacher, cid_a, _, sid = setup_env(campus)

    # 上传工号带前导零的教职工档案
    content = sheet(
        [
            ["工号", "姓名", "联系电话", "启停状态"],
            ["001001", "张老师", "13800000001", "正常"],
        ]
    )
    preview_res = service.create_preview(
        teacher,
        target="faculty_staff",
        content=content,
        semester_id=None,
        teaching_class_id=None,
        filename="staff_01.xlsx",
        replace=False,
        request_id=None,
    )

    assert preview_res.can_confirm
    assert preview_res.target == "faculty_staff"
    assert not preview_res.errors

    # 验证：预览不写正式表
    assert db.scalar(select(FacultyStaff).where(FacultyStaff.staff_no == "001001")) is None

    # 差异核对计划
    wizard = ImportConfirmationSet(service)
    batch_ids = [int(preview_res.id)]
    plan = wizard.preview(batch_ids)

    assert plan["can_confirm"]
    file_info = plan["files"][0]
    assert file_info["target"] == "faculty_staff"
    assert len(file_info["changes"]) == 1
    change = file_info["changes"][0]
    assert change["action"] == "CREATE"
    assert change["entity"] == "faculty_staff"
    assert change["key"] == "001001"
    assert change["before"] is None
    assert change["after"]["name"] == "张老师"
    assert change["after"]["phone"] == "13800000001"
    assert change["source"]["filename"] == "staff_01.xlsx"

    # 确认导入
    confirm_res = wizard.confirm(batch_ids, plan["revision"], None)
    assert confirm_res["status"] == "CONFIRMED"

    # 验证数据库正式数据：前导零保留，版本为 1
    st = db.scalar(select(FacultyStaff).where(FacultyStaff.staff_no == "001001"))
    assert st is not None
    assert st.staff_no == "001001"
    assert st.name == "张老师"
    assert st.phone == "13800000001"
    assert st.status == "ACTIVE"
    assert st.lock_version == 1

    # 再次上传更新联系电话
    update_content = sheet(
        [
            ["工号", "姓名", "联系电话", "启停状态"],
            ["001001", "张老师", "13800009999", "正常"],
        ]
    )
    p2 = service.create_preview(
        teacher,
        target="faculty_staff",
        content=update_content,
        semester_id=None,
        teaching_class_id=None,
        filename="staff_02.xlsx",
        replace=False,
        request_id=None,
    )
    plan2 = wizard.preview([int(p2.id)])
    assert plan2["can_confirm"]
    ch2 = plan2["files"][0]["changes"][0]
    assert ch2["action"] == "UPDATE"
    assert ch2["before"]["phone"] == "13800000001"
    assert ch2["after"]["phone"] == "13800009999"

    wizard.confirm([int(p2.id)], plan2["revision"], None)
    db.refresh(st)
    assert st.phone == "13800009999"
    assert st.lock_version == 2


def test_faculty_staff_duplicate_and_cross_college_conflict(campus):
    service, db, teacher, cid_a, cid_b, _ = setup_env(campus)

    # 1. 文件内重复工号阻断
    dup_content = sheet(
        [
            ["工号", "姓名"],
            ["002001", "李一"],
            ["002001", "李二"],
        ]
    )
    res_dup = service.create_preview(
        teacher,
        target="faculty_staff",
        content=dup_content,
        semester_id=None,
        teaching_class_id=None,
        filename="dup.xlsx",
        replace=False,
        request_id=None,
    )
    assert not res_dup.can_confirm
    assert any("重复工号" in e["message"] for e in res_dup.errors)

    # 2. 已在其他学院建档的工号不可覆盖
    foreign_col = db.get(College, cid_b)
    other_staff = FacultyStaff(
        school_id=foreign_col.school_id,
        college_id=cid_b,
        staff_no="FOREIGN_001",
        name="外院教师",
        status="ACTIVE",
    )
    db.add(other_staff)
    db.commit()

    cross_content = sheet(
        [
            ["工号", "姓名"],
            ["FOREIGN_001", "试图跨院建档"],
        ]
    )
    res_cross = service.create_preview(
        teacher,
        target="faculty_staff",
        content=cross_content,
        semester_id=None,
        teaching_class_id=None,
        filename="cross.xlsx",
        replace=False,
        request_id=None,
    )
    assert not res_cross.can_confirm
    assert any("已在学校其他学院建档" in e["message"] for e in res_cross.errors)


def test_class_responsibility_empty_columns_do_not_revoke_and_handover(campus):
    service, db, teacher, cid_a, _, _ = setup_env(campus)
    col = db.get(College, cid_a)

    # 准备行政班与两位教师档案
    ac = AdministrativeClass(
        class_code="SE2201",
        class_name="软工2201",
        college_id=cid_a,
        status="ACTIVE",
    )
    s1 = FacultyStaff(
        school_id=col.school_id,
        college_id=cid_a,
        staff_no="T001",
        name="原班主任",
        status="ACTIVE",
    )
    s2 = FacultyStaff(
        school_id=col.school_id,
        college_id=cid_a,
        staff_no="T002",
        name="新辅导员",
        status="ACTIVE",
    )
    s3 = FacultyStaff(
        school_id=col.school_id,
        college_id=cid_a,
        staff_no="T003",
        name="接任班主任",
        status="ACTIVE",
    )
    db.add_all([ac, s1, s2, s3])
    db.flush()

    # 原班主任已在任（从 2026-09-01 开始）
    old_duty = ClassStaffResponsibility(
        staff_id=s1.id,
        administrative_class_id=ac.id,
        duty="HEAD_TEACHER",
        effective_from=date(2026, 9, 1),
        effective_to=None,
        lock_version=1,
    )
    db.add(old_duty)
    db.commit()

    # 1. 导入只填了辅导员，班主任列为空 -> 缺行/空列不撤销
    content1 = sheet(
        [
            ["行政班", "班主任工号", "班主任姓名", "辅导员工号", "辅导员姓名", "生效日期"],
            ["软工2201", "", "", "T002", "新辅导员", "2026-09-15"],
        ]
    )
    p1 = service.create_preview(
        teacher,
        target="class_responsibility",
        content=content1,
        semester_id=None,
        teaching_class_id=None,
        filename="duty1.xlsx",
        replace=False,
        request_id=None,
    )
    assert p1.can_confirm

    wizard = ImportConfirmationSet(service)
    plan1 = wizard.preview([int(p1.id)])
    # 只有一个 change（辅导员），原班主任不出现在变更中，也不被撤销
    assert len(plan1["files"][0]["changes"]) == 1
    assert plan1["files"][0]["changes"][0]["key"] == "软工2201/COUNSELOR"

    wizard.confirm([int(p1.id)], plan1["revision"], None)

    # 检查：原班主任仍然在任，且辅导员已任命
    db.refresh(old_duty)
    assert old_duty.effective_to is None
    counselor_duty = db.scalar(
        select(ClassStaffResponsibility).where(
            ClassStaffResponsibility.administrative_class_id == ac.id,
            ClassStaffResponsibility.duty == "COUNSELOR",
        )
    )
    assert counselor_duty is not None
    assert counselor_duty.staff_id == s2.id
    assert counselor_duty.effective_from == date(2026, 9, 15)

    # 2. 交接：导入新班主任接班（从 2026-10-01 开始）
    content2 = sheet(
        [
            ["行政班", "班主任工号", "班主任姓名", "生效日期"],
            ["软工2201", "T003", "接任班主任", "2026-10-01"],
        ]
    )
    p2 = service.create_preview(
        teacher,
        target="class_responsibility",
        content=content2,
        semester_id=None,
        teaching_class_id=None,
        filename="duty2.xlsx",
        replace=False,
        request_id=None,
    )
    assert p2.can_confirm
    plan2 = wizard.preview([int(p2.id)])
    wizard.confirm([int(p2.id)], plan2["revision"], None)

    # 验证交接：旧关系在 2026-10-01 结束，新关系在 2026-10-01 开始
    db.refresh(old_duty)
    assert old_duty.effective_to == date(2026, 10, 1)

    new_head_duty = db.scalar(
        select(ClassStaffResponsibility).where(
            ClassStaffResponsibility.administrative_class_id == ac.id,
            ClassStaffResponsibility.duty == "HEAD_TEACHER",
            ClassStaffResponsibility.staff_id == s3.id,
        )
    )
    assert new_head_duty is not None
    assert new_head_duty.effective_from == date(2026, 10, 1)
    assert new_head_duty.effective_to is None


def test_class_responsibility_same_name_ambiguity_rejected(campus):
    service, db, teacher, cid_a, _, _ = setup_env(campus)
    col = db.get(College, cid_a)

    ac = AdministrativeClass(
        class_code="SE2202",
        class_name="软工2202",
        college_id=cid_a,
        status="ACTIVE",
    )
    # 同院存在两个同名为 "李四" 的教师
    s1 = FacultyStaff(
        school_id=col.school_id,
        college_id=cid_a,
        staff_no="T101",
        name="李四",
        status="ACTIVE",
    )
    s2 = FacultyStaff(
        school_id=col.school_id,
        college_id=cid_a,
        staff_no="T102",
        name="李四",
        status="ACTIVE",
    )
    db.add_all([ac, s1, s2])
    db.commit()

    # 只提供了姓名 "李四"，没有提供工号
    content = sheet(
        [
            ["行政班", "班主任姓名"],
            ["软工2202", "李四"],
        ]
    )
    preview_res = service.create_preview(
        teacher,
        target="class_responsibility",
        content=content,
        semester_id=None,
        teaching_class_id=None,
        filename="ambiguous.xlsx",
        replace=False,
        request_id=None,
    )
    # 同名教职工不能自动授权，必须报错阻断
    assert not preview_res.can_confirm
    assert any("同名" in e["message"] for e in preview_res.errors)


def test_teaching_assignment_shared_offering_covered_colleges_and_multi_teacher(campus):
    service, db, teacher, cid_a, cid_b, sid = setup_env(campus)
    col_a = db.get(College, cid_a)
    col_b = db.get(College, cid_b)

    # 1. 共享课程与两个学院的教学班
    course = Course(course_code="CS101", course_name="计算机科学导论", college_id=None)
    offering = AcademicOffering(
        id="OFFER_CS101",
        school_id=col_a.school_id,
        semester_id=sid,
        course_name="计算机科学导论",
        offering_college_id=cid_a,
    )
    db.add_all([course, offering])
    db.flush()

    tc_a = TeachingClass(
        semester_id=sid,
        course_id=course.id,
        college_id=cid_a,
        class_code="TC_CS101_A",
        class_name="计算机导论A班",
        academic_offering_id=offering.id,
        status="ACTIVE",
    )
    tc_b = TeachingClass(
        semester_id=sid,
        course_id=course.id,
        college_id=cid_b,
        class_code="TC_CS101_B",
        class_name="计算机导论B班",
        academic_offering_id=offering.id,
        status="ACTIVE",
    )
    # 两名教师
    t1 = FacultyStaff(
        school_id=col_a.school_id,
        college_id=cid_a,
        staff_no="T201",
        name="张教授",
        status="ACTIVE",
    )
    t2 = FacultyStaff(
        school_id=col_a.school_id,
        college_id=cid_a,
        staff_no="T202",
        name="王讲师",
        status="ACTIVE",
    )
    db.add_all([tc_a, tc_b, t1, t2])
    db.commit()

    # 共享授课关系导入：指定 anchor_type=SHARED
    content = sheet(
        [
            ["教学班码", "教师工号", "任课教师", "锚点类型"],
            ["TC_CS101_A", "T201", "张教授", "SHARED"],
        ]
    )
    preview_res = service.create_preview(
        teacher,
        target="teaching_assignment",
        content=content,
        semester_id=sid,
        teaching_class_id=None,
        filename="teaching.xlsx",
        replace=False,
        request_id=None,
    )
    assert preview_res.can_confirm

    wizard = ImportConfirmationSet(service)
    plan = wizard.preview([int(preview_res.id)])
    assert plan["can_confirm"]

    change = plan["files"][0]["changes"][0]
    assert change["entity"] == "teaching_assignment"
    assert change["after"]["anchor_type"] == "SHARED"
    # 共享授课预览列出覆盖的学院视图
    covered = change.get("covered_colleges") or []
    assert col_a.name in covered
    assert col_b.name in covered

    confirm_res = wizard.confirm([int(preview_res.id)], plan["revision"], None)
    assert confirm_res["status"] == "CONFIRMED"

    # 检查数据库：anchor_type 为 SHARED，academic_offering_id 有值，teaching_class_id 为 None
    assign = db.scalar(
        select(TeachingStaffAssignment).where(
            TeachingStaffAssignment.staff_id == t1.id,
            TeachingStaffAssignment.semester_id == sid,
        )
    )
    assert assign is not None
    assert assign.anchor_type == "SHARED"
    assert assign.academic_offering_id == offering.id
    assert assign.teaching_class_id is None

    # 多教师组合：在单个单元格支持拆分或多行
    # 锚点必须显式：留空一律按 LOCAL，而 T201 已以 SHARED 覆盖同一共享身份
    multi_content = sheet(
        [
            ["教学班码", "任课教师", "锚点类型"],
            ["TC_CS101_A", "张教授 / 王讲师", "SHARED"],
        ]
    )
    p_multi = service.create_preview(
        teacher,
        target="teaching_assignment",
        content=multi_content,
        semester_id=sid,
        teaching_class_id=None,
        filename="multi_teacher.xlsx",
        replace=False,
        request_id=None,
    )
    assert p_multi.can_confirm
    plan_multi = wizard.preview([int(p_multi.id)])
    # 拆分出两个教师变更
    assert len(plan_multi["files"][0]["changes"]) == 2
    keys = {c["key"] for c in plan_multi["files"][0]["changes"]}
    assert "TC_CS101_A/T201" in keys
    assert "TC_CS101_A/T202" in keys


def test_teaching_assignment_unknown_staff_no_rejected(campus):
    service, db, teacher, cid_a, _, sid = setup_env(campus)
    tc = TeachingClass(
        semester_id=sid,
        course_id=1,
        college_id=cid_a,
        class_code="TC_UNKNOWN_TEST",
        class_name="未知测试班",
        status="ACTIVE",
    )
    db.add(tc)
    db.commit()

    content = sheet(
        [
            ["教学班码", "教师工号"],
            ["TC_UNKNOWN_TEST", "NO_SUCH_TEACHER_9999"],
        ]
    )
    res = service.create_preview(
        teacher,
        target="teaching_assignment",
        content=content,
        semester_id=sid,
        teaching_class_id=None,
        filename="unknown.xlsx",
        replace=False,
        request_id=None,
    )
    assert not res.can_confirm
    assert any("未知教师工号" in e["message"] for e in res.errors)


def test_no_semester_cannot_mix_with_semester_batch(campus):
    service, db, teacher, cid_a, _, sid = setup_env(campus)

    # 1. 无学期资料：faculty_staff
    c1 = sheet([["工号", "姓名"], ["FS001", "周老师"]])
    p1 = service.create_preview(
        teacher,
        target="faculty_staff",
        content=c1,
        semester_id=None,
        teaching_class_id=None,
        filename="staff.xlsx",
        replace=False,
        request_id=None,
    )

    # 2. 有学期资料：teaching_assignment
    tc = TeachingClass(
        semester_id=sid,
        course_id=1,
        college_id=cid_a,
        class_code="TC_MIX_01",
        class_name="混合测试班",
        status="ACTIVE",
    )
    db.add(tc)
    db.commit()

    c2 = sheet([["教学班码", "教师工号"], ["TC_MIX_01", "FS001"]])
    p2 = service.create_preview(
        teacher,
        target="teaching_assignment",
        content=c2,
        semester_id=sid,
        teaching_class_id=None,
        filename="teaching.xlsx",
        replace=False,
        request_id=None,
    )

    wizard = ImportConfirmationSet(service)
    # 混合在一起确认时，必须抛出 ConflictError 拒绝
    with pytest.raises(ConflictError) as exc_info:
        wizard.preview([int(p1.id), int(p2.id)])
    assert "无学期资料与学期资料请分开确认" in exc_info.value.message


def test_stale_preview_causes_409_conflict(campus):
    service, db, teacher, cid_a, _, _ = setup_env(campus)
    col = db.get(College, cid_a)

    # 先建一个已有档案
    st = FacultyStaff(
        school_id=col.school_id,
        college_id=cid_a,
        staff_no="STALE_01",
        name="原有姓名",
        status="ACTIVE",
        lock_version=1,
    )
    db.add(st)
    db.commit()

    # 上传新预览
    c = sheet([["工号", "姓名", "联系电话"], ["STALE_01", "原有姓名", "13800001111"]])
    p = service.create_preview(
        teacher,
        target="faculty_staff",
        content=c,
        semester_id=None,
        teaching_class_id=None,
        filename="stale.xlsx",
        replace=False,
        request_id=None,
    )
    wizard = ImportConfirmationSet(service)
    plan = wizard.preview([int(p.id)])
    rev = plan["revision"]

    # 模拟其他会话/管理员在预览后修改了档案的 lock_version
    st.lock_version += 1
    db.commit()

    # 尝试确认：报 409 Conflict
    with pytest.raises(ConflictError):
        wizard.confirm([int(p.id)], rev, None)


def test_atomic_rollback_on_second_file_failure(campus, monkeypatch):
    service, db, teacher, cid_a, _, _ = setup_env(campus)

    c1 = sheet([["工号", "姓名"], ["ROLL_01", "回滚测试1"]])
    c2 = sheet([["工号", "姓名"], ["ROLL_02", "回滚测试2"]])

    p1 = service.create_preview(
        teacher,
        target="faculty_staff",
        content=c1,
        semester_id=None,
        teaching_class_id=None,
        filename="roll1.xlsx",
        replace=False,
        request_id=None,
    )
    p2 = service.create_preview(
        teacher,
        target="faculty_staff",
        content=c2,
        semester_id=None,
        teaching_class_id=None,
        filename="roll2.xlsx",
        replace=False,
        request_id=None,
    )

    wizard = ImportConfirmationSet(service)
    ids = [int(p1.id), int(p2.id)]
    plan = wizard.preview(ids)

    # 模拟第二个文件在 apply 时抛出异常
    from app.modules.importer import staff_adapter

    orig_apply = staff_adapter.apply_staff
    call_count = 0

    def mock_apply(db_session, actor, batch, payload, request_id):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise ConflictError(message="Late failure in file 2")
        return orig_apply(db_session, actor, batch, payload, request_id)

    monkeypatch.setattr(staff_adapter, "apply_staff", mock_apply)

    with pytest.raises(ConflictError):
        wizard.confirm(ids, plan["revision"], None)

    # 验证：第一个文件的记录也全部回滚，正式表没有产生任何脏数据
    assert db.scalar(select(FacultyStaff).where(FacultyStaff.staff_no == "ROLL_01")) is None
    assert db.scalar(select(FacultyStaff).where(FacultyStaff.staff_no == "ROLL_02")) is None
    assert db.get(ImportBatch, ids[0]).status == "PREVIEW"
    assert db.get(ImportBatch, ids[1]).status == "PREVIEW"


def test_idempotent_retry_does_not_duplicate(campus):
    service, db, teacher, cid_a, _, _ = setup_env(campus)

    c = sheet([["工号", "姓名"], ["IDEM_01", "幂等测试"]])
    p = service.create_preview(
        teacher,
        target="faculty_staff",
        content=c,
        semester_id=None,
        teaching_class_id=None,
        filename="idem.xlsx",
        replace=False,
        request_id=None,
    )

    wizard = ImportConfirmationSet(service)
    ids = [int(p.id)]
    plan = wizard.preview(ids)

    res1 = wizard.confirm(ids, plan["revision"], None)
    assert res1["status"] == "CONFIRMED"

    # 重试：返回相同结果，不重复插入
    res2 = wizard.confirm(ids, plan["revision"], None)
    assert res2 == res1
    count = len(list(db.scalars(select(FacultyStaff).where(FacultyStaff.staff_no == "IDEM_01"))))
    assert count == 1


def test_staff_import_requires_staff_manage_action(campus):
    """学籍/排班导入权限不等于教工资料导入权限；缺 staff.manage 即 403。"""
    config, db, admin, teacher, _a, b = campus
    setup_env(campus)
    grant(
        config,
        admin,
        teacher,
        b,
        ["import.execute", "student.manage", "course_schedule.import"],
    )

    scoped = ScopedImporterService(db, teacher, int(b["id"]))
    content = sheet([["工号", "姓名"], ["NO_STAFF_MGR", "无教工权限"]])
    with pytest.raises(PermissionDeniedError):
        scoped.create_preview(
            teacher,
            target="faculty_staff",
            content=content,
            semester_id=None,
            teaching_class_id=None,
            filename="denied.xlsx",
            replace=False,
            request_id=None,
        )
    with pytest.raises(PermissionDeniedError):
        scoped.get_template(teacher, "class_responsibility")


def test_template_contracts(campus):
    service, _, teacher, _, _, _ = setup_env(campus)

    # 1. 教职工档案
    t_staff = service.get_template(teacher, "faculty_staff")
    assert t_staff.target == "faculty_staff"
    assert t_staff.scope_fields == []
    headers = [col["header"] for col in t_staff.columns]
    assert "工号" in headers
    assert "姓名" in headers

    # 2. 班级责任关系
    t_duty = service.get_template(teacher, "class_responsibility")
    assert t_duty.target == "class_responsibility"
    assert t_duty.scope_fields == []
    headers_duty = [col["header"] for col in t_duty.columns]
    assert "行政班" in headers_duty
    assert "班主任工号" in headers_duty
    assert "辅导员工号" in headers_duty

    # 3. 任课教师授课关系
    t_teach = service.get_template(teacher, "teaching_assignment")
    assert t_teach.target == "teaching_assignment"
    assert "semester_id" in t_teach.scope_fields
    headers_teach = [col["header"] for col in t_teach.columns]
    assert "教学班码" in headers_teach
    assert "教师工号" in headers_teach


def test_import_targets_the_overlapping_appointment_not_the_latest_row(campus):
    """补录历史区间只改重叠的那条任命，正在任命的记录不能被任意覆写。"""
    service, db, teacher, cid_a, _, sid = setup_env(campus)
    col = db.get(College, cid_a)
    course = Course(course_code="HI101", course_name="历史核对课", college_id=cid_a)
    tc = TeachingClass(
        semester_id=sid,
        course_id=course.id,
        college_id=cid_a,
        class_code="TC_HI101",
        class_name="历史核对班",
        status="ACTIVE",
    )
    st = FacultyStaff(
        school_id=col.school_id,
        college_id=cid_a,
        staff_no="HIST_01",
        name="历史教师",
        status="ACTIVE",
    )
    db.add_all([course, st])
    db.flush()
    tc = TeachingClass(
        semester_id=sid,
        course_id=course.id,
        college_id=cid_a,
        class_code="TC_HI101",
        class_name="历史核对班",
        status="ACTIVE",
    )
    db.add(tc)
    db.flush()
    # 先建在任记录再建历史段：无日期条件的查询会任取一条并覆写在任记录
    current = TeachingStaffAssignment(
        staff_id=st.id,
        semester_id=sid,
        anchor_type="LOCAL",
        teaching_class_id=tc.id,
        effective_from=date(2026, 9, 1),
        effective_to=None,
        lock_version=1,
    )
    past = TeachingStaffAssignment(
        staff_id=st.id,
        semester_id=sid,
        anchor_type="LOCAL",
        teaching_class_id=tc.id,
        effective_from=date(2025, 2, 1),
        effective_to=date(2025, 6, 30),
        lock_version=1,
    )
    db.add_all([current, past])
    db.commit()

    content = sheet(
        [
            ["教学班码", "教师工号", "生效日期", "结束日期"],
            ["TC_HI101", "HIST_01", "2025-03-01", "2025-05-31"],
        ]
    )
    preview = service.create_preview(
        teacher,
        target="teaching_assignment",
        content=content,
        semester_id=sid,
        teaching_class_id=None,
        filename="history.xlsx",
        replace=False,
        request_id=None,
    )
    assert preview.can_confirm
    wizard = ImportConfirmationSet(service)
    plan = wizard.preview([int(preview.id)])
    change = plan["files"][0]["changes"][0]
    assert change["action"] == "UPDATE"
    assert change["before"]["effective_from"] == "2025-02-01"

    wizard.confirm([int(preview.id)], plan["revision"], None)
    db.refresh(past)
    db.refresh(current)
    assert (past.effective_from, past.effective_to) == (date(2025, 3, 1), date(2025, 5, 31))
    assert past.lock_version == 2
    assert (current.effective_from, current.effective_to) == (date(2026, 9, 1), None)
    assert current.lock_version == 1


def test_blank_anchor_stays_local_and_shared_conflict_is_flagged(campus):
    """留空锚点不得自动升为 SHARED；同锚点之外覆盖同一共享身份要拦下。"""
    service, db, teacher, cid_a, cid_b, sid = setup_env(campus)
    col_a = db.get(College, cid_a)
    course = Course(course_code="AN101", course_name="锚点核对课", college_id=cid_a)
    offering = AcademicOffering(
        id="OFFER_AN101",
        school_id=col_a.school_id,
        semester_id=sid,
        course_name="锚点核对课",
        offering_college_id=cid_a,
    )
    st = FacultyStaff(
        school_id=col_a.school_id,
        college_id=cid_a,
        staff_no="ANCHOR_01",
        name="锚点教师",
        status="ACTIVE",
    )
    db.add_all([course, offering, st])
    db.flush()
    tc = TeachingClass(
        semester_id=sid,
        course_id=course.id,
        college_id=cid_a,
        class_code="TC_AN101",
        class_name="锚点核对班",
        academic_offering_id=offering.id,
        status="ACTIVE",
    )
    db.add(tc)
    db.commit()

    content = sheet([["教学班码", "教师工号"], ["TC_AN101", "ANCHOR_01"]])
    preview = service.create_preview(
        teacher,
        target="teaching_assignment",
        content=content,
        semester_id=sid,
        teaching_class_id=None,
        filename="blank_anchor.xlsx",
        replace=False,
        request_id=None,
    )
    assert preview.can_confirm
    wizard = ImportConfirmationSet(service)
    plan = wizard.preview([int(preview.id)])
    assert plan["files"][0]["changes"][0]["after"]["anchor_type"] == "LOCAL"
    wizard.confirm([int(preview.id)], plan["revision"], None)

    row = db.scalar(
        select(TeachingStaffAssignment).where(
            TeachingStaffAssignment.staff_id == st.id,
            TeachingStaffAssignment.semester_id == sid,
        )
    )
    assert row.anchor_type == "LOCAL"
    assert row.teaching_class_id == tc.id
    assert row.academic_offering_id is None

    # 同一教师再以 SHARED 覆盖同一共享身份：预览必须拦下，不形成双来源
    shared_preview = service.create_preview(
        teacher,
        target="teaching_assignment",
        content=sheet([["教学班码", "教师工号", "锚点类型"], ["TC_AN101", "ANCHOR_01", "SHARED"]]),
        semester_id=sid,
        teaching_class_id=None,
        filename="shared_anchor.xlsx",
        replace=False,
        request_id=None,
    )
    assert not shared_preview.can_confirm
    assert any(i["code"] == "ANCHOR_OVERLAP" for i in shared_preview.errors)
