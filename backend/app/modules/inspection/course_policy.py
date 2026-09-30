"""被查课程范围规则；学生课表仍保留全部课程用于忙碌时段。"""

import re
import unicodedata

_EXACT_NAMES = {
    "体育", "体育课", "体育板块", "大学体育", "公共体育", "体育与健康",
    "体育选项课", "体育专项课",
    "选项体育", "专项体育",
}
_SPORTS = "篮球|足球|排球|羽毛球|乒乓球|网球|田径|游泳|健美操|武术|瑜伽"
_SPORTS_OPTIONS = re.compile(rf"(?:{_SPORTS})(?:选项|专项)体育(?:课)?")
_COLLEGE_PE = re.compile(r"(?:大学|公共)体育(?:[1-4]|[一二三四]|IV|III|II|I|\([一二三四1-4]\))")


def is_physical_education(name: str | None) -> bool:
    if not name:
        return False
    normalized = "".join(unicodedata.normalize("NFKC", name).split())
    return bool(
        normalized in _EXACT_NAMES
        or _COLLEGE_PE.fullmatch(normalized)
        or _SPORTS_OPTIONS.fullmatch(normalized)
    )
