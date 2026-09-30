"""只解释显式楼号；无法辨认的地点保持未知，不能猜房间号或拒绝任务。"""

import re
from collections.abc import Sequence

_CHINESE = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
            "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12,
            "十三": 13, "十四": 14, "十五": 15}


def building_cluster(location: str | None, groups: Sequence[Sequence[int]]) -> str | None:
    if not location:
        return None
    matches = re.findall(r"(?<!\d)(\d{1,2}|[一二三四五六七八九十]+)\s*(?:号楼|幢|栋)", location)
    if not matches:
        short = re.fullmatch(
            r"\s*(?:教学楼)?(\d{1,2})\s*[-－]\s*(?:\d{3,4}|阶\d+)\s*", location)
        matches = [short[1]] if short else []
    numbers = {int(s) if s.isdigit() else _CHINESE.get(s) for s in matches}
    if len(numbers) != 1 or None in numbers:
        return None
    building = next(iter(numbers))
    return next((",".join(map(str, sorted(group))) for group in groups if building in group), None)
