"""体育课程只占用志愿者上课时间，不成为被查目标。"""

import pytest
from app.modules.inspection.course_policy import is_physical_education


@pytest.mark.parametrize("name", [
    "体育", " 体育 课 ", "体育板块", "大学体育1", "大学体育（一）", "大学体育Ⅰ",
    "大学体育", "公共体育", "公共体育1", "公共体育（一）", "体育与健康",
    "篮球专项体育", "羽毛球选项体育", "大 学 体 育 １",
])
def test_explicit_physical_education_names_are_excluded(name: str) -> None:
    assert is_physical_education(name)


@pytest.mark.parametrize("name", [
    None, "", "高等数学", "体育经济学", "体育管理学", "体育社会学", "体育教学论",
    "大学体育经济学", "大学体育文化", "体育与健康教育研究",
])
def test_theory_and_other_courses_remain_inspectable(name: str | None) -> None:
    assert not is_physical_education(name)
