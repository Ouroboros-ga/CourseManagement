"""新业务功能单元测试：
1. 6 位友好学生绑定码生成与 Excel 导出
2. 相同“教室+时段+课程”查课合流与去重
3. 智能抽查规则推荐 (Smart Sampling)
4. 任务现场编辑 (方式 A: PATCH /inspection-tasks/{task_id})
5. 学籍异动 (转专业/换班) 自动识别
"""

import io
from datetime import date, datetime
import openpyxl
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.security import generate_friendly_binding_code, hash_token
from app.modules.academic.models import (
    AdministrativeClass,
    Course,
    CourseSchedule,
    CourseScheduleWeek,
    PeriodDefinition,
    Semester,
    Student,
    TeachingClass,
    TeachingClassStudent,
)
from app.modules.identity.models import IdentityBindingToken, Role, UserAccount
from app.modules.identity.service import IdentityService
from app.modules.inspection.course_policy import is_course_exempt
from app.modules.inspection.models import InspectionTask
from app.modules.inspection.schemas import InspectionTaskUpdateRequest, SmartSampleRequest
from app.modules.inspection.service import InspectionService, PlanItem


def test_friendly_binding_code_format():
    for _ in range(50):
        code = generate_friendly_binding_code(6)
        assert len(code) == 6
        assert code.isupper() or code.isdigit()
        # 确保无易混淆字符
        for bad_char in ["0", "O", "1", "I"]:
            assert bad_char not in code


def test_course_exempt_policy():
    assert is_course_exempt("大学体育1") is True
    assert is_course_exempt("篮球专项体育") is True
    assert is_course_exempt("金工实习") is True
    assert is_course_exempt("大学计算机机房上机") is True
    assert is_course_exempt("网络慕课") is True
    assert is_course_exempt("高等数学", classroom="操场") is True
    assert is_course_exempt("高等数学", classroom="3-203") is False
    assert is_course_exempt("大学英语", classroom="5-102") is False


def test_hash_token_case_insensitivity():
    code = "A8K9MN"
    h1 = hash_token("a8k9mn")
    h2 = hash_token("A8K9MN ")
    h3 = hash_token("  A8k9Mn  ")
    assert h1 == h2 == h3
