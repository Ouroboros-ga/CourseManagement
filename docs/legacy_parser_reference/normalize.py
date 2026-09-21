"""时间标准化：周次 / 星期 / 节次解析（M1a）。

- parse_weeks(text, total_weeks) -> list[int]
- parse_weekday(value) -> int
- parse_period(value, slot_mapping=None) -> list[int]（标准大节）

设计依据见规划第 4.2 节：
- 去除空格并统一全角标点后解析；
- 拒绝倒置区间、空结果和超出学期范围的值；
- 星期为 1~7 或固定中文映射，不做模糊识别；
- 默认大节映射 1-2->1、3-4->2、5-6->3、7-8->4、9-10->5。
"""

from __future__ import annotations


# 小节 -> 标准大节。配置变化必须记录在方案规则快照中。
DEFAULT_SLOT_MAPPING: dict[int, int] = {
    1: 1,
    2: 1,
    3: 2,
    4: 2,
    5: 3,
    6: 3,
    7: 4,
    8: 4,
    9: 5,
    10: 5,
}

MAX_SLOT = max(DEFAULT_SLOT_MAPPING.values())

# 全角数字 -> 半角
_FW_DIGITS = {chr(ord("０") + i): str(i) for i in range(10)}
_FW_DIGITS["　"] = ""  # 全角空格直接删除（空格统一在别处处理）

# 全角/易混标点 -> 标准分隔符
_PUNCT_MAP = {
    "，": ",",
    "、": ",",
    "；": ",",
    ";": ",",
    "〜": "-",  # U+301C WAVE DASH，常见于中文输入法
    "～": "-",  # U+FF5E FULLWIDTH TILDE
    "–": "-",  # EN DASH
    "—": "-",  # EM DASH
    "－": "-",  # FULLWIDTH HYPHEN-MINUS
    "﹣": "-",
    "﹑": ",",
}


def _to_half_width(text: str) -> str:
    out: list[str] = []
    for ch in text:
        if ch in _FW_DIGITS:
            out.append(_FW_DIGITS[ch])
            continue
        if ch in _PUNCT_MAP:
            out.append(_PUNCT_MAP[ch])
            continue
        o = ord(ch)
        # 全角数字已处理；全角大写/小写字母不用于时间，保留原样以便报错。
        if 0xFF01 <= o <= 0xFF5E:
            out.append(chr(o - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def _strip_spaces(text: str) -> str:
    # 去除所有空白（含全角空格、制表、换行）
    return "".join(ch for ch in text if not ch.isspace() and ch != "　")


def _normalize_weeks_text(text: str) -> str:
    s = _strip_spaces(text)
    s = _to_half_width(s)
    return s


_WEEKDAY_MAP: dict[str, int] = {
    "周一": 1,
    "周二": 2,
    "周三": 3,
    "周四": 4,
    "周五": 5,
    "周六": 6,
    "周日": 7,
    "周天": 7,
    "星期一": 1,
    "星期二": 2,
    "星期三": 3,
    "星期四": 4,
    "星期五": 5,
    "星期六": 6,
    "星期日": 7,
    "星期天": 7,
    "周1": 1,
    "周2": 2,
    "周3": 3,
    "周4": 4,
    "周5": 5,
    "周6": 6,
    "周7": 7,
    "星期1": 1,
    "星期2": 2,
    "星期3": 3,
    "星期4": 4,
    "星期5": 5,
    "星期6": 6,
    "星期7": 7,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "日": 7,
    "天": 7,
}


def parse_weeks(text: str | int, total_weeks: int) -> list[int]:
    """解析周次为排序去重后的周列表。

    支持 ``1-16``、``1-15单周``、``2-16双周``、``1,3,5,8``、``第1-8周`` 及其组合
    （如 ``1-4,6,8-10双周``）。单/双可写成 ``单``/``单周``/``双``/``双周``。

    非法输入（倒置区间、空结果、超出 ``1..total_weeks``、无法识别文本）抛 ValueError。
    """
    if isinstance(text, bool):
        raise ValueError(f"非法周次：{text!r}")
    if isinstance(text, int):
        if not isinstance(total_weeks, int) or total_weeks < 1:
            raise ValueError(f"非法学期总周数：{total_weeks!r}")
        if 1 <= text <= total_weeks:
            return [text]
        raise ValueError(f"周次 {text} 超出范围 1..{total_weeks}")
    if not isinstance(text, str):
        raise ValueError(f"非法周次：{text!r}")
    if not isinstance(total_weeks, int) or total_weeks < 1:
        raise ValueError(f"非法学期总周数：{total_weeks!r}")

    s = _normalize_weeks_text(text)
    if not s:
        raise ValueError(f"非法周次：{text!r}（空）")
    # 拒绝显式公式输入（Excel 公式残留）
    if s.startswith("="):
        raise ValueError(f"非法周次：{text!r}（疑似公式）")

    parts = s.split(",")
    result: list[int] = []
    for part in parts:
        if not part:
            raise ValueError(f"非法周次：{text!r}（存在空段）")
        weeks = _parse_single_week_part(part, total_weeks, original=text)
        result.extend(weeks)
    if not result:
        raise ValueError(f"非法周次：{text!r}（空结果）")
    for w in result:
        if w < 1 or w > total_weeks:
            raise ValueError(f"周次 {w} 超出范围 1..{total_weeks}：{text!r}")
    return sorted(set(result))


def _parse_single_week_part(part: str, total_weeks: int, original: object) -> list[int]:
    parity: str | None = None
    core = part
    if core.endswith("单周"):
        parity = "odd"
        core = core[:-2]
    elif core.endswith("双周"):
        parity = "even"
        core = core[:-2]
    elif core.endswith("单"):
        parity = "odd"
        core = core[:-1]
    elif core.endswith("双"):
        parity = "even"
        core = core[:-1]

    if core.startswith("第"):
        core = core[1:]
    if core.endswith("周"):
        core = core[:-1]

    if not core or "第" in core or "周" in core or "单" in core or "双" in core:
        raise ValueError(f"非法周次：{original!r}（段 {part!r} 无法识别）")

    if "-" in core:
        if core.count("-") != 1:
            raise ValueError(f"非法周次：{original!r}（段 {part!r} 区间格式错误）")
        a_str, b_str = core.split("-", 1)
        if not a_str or not b_str or not a_str.isdigit() or not b_str.isdigit():
            raise ValueError(f"非法周次：{original!r}（段 {part!r} 区间数字错误）")
        a, b = int(a_str), int(b_str)
        if a > b:
            raise ValueError(f"非法周次：{original!r}（段 {part!r} 倒置区间）")
        if a < 1 or b > total_weeks:
            raise ValueError(f"非法周次：{original!r}（段 {part!r} 超出 1..{total_weeks}）")
        weeks = list(range(a, b + 1))
        if parity == "odd":
            weeks = [w for w in weeks if w % 2 == 1]
        elif parity == "even":
            weeks = [w for w in weeks if w % 2 == 0]
        if not weeks:
            raise ValueError(f"非法周次：{original!r}（段 {part!r} 过滤后为空）")
        return weeks

    if not core.isdigit():
        raise ValueError(f"非法周次：{original!r}（段 {part!r} 无法识别）")
    w = int(core)
    if w < 1 or w > total_weeks:
        raise ValueError(f"非法周次：{original!r}（{w} 超出 1..{total_weeks}）")
    if parity == "odd" and w % 2 != 1:
        raise ValueError(f"非法周次：{original!r}（段 {part!r} 与单周矛盾）")
    if parity == "even" and w % 2 != 0:
        raise ValueError(f"非法周次：{original!r}（段 {part!r} 与双周矛盾）")
    return [w]


def parse_weekday(value: str | int) -> int:
    """解析星期为 1..7（1=周一，7=周日）。"""
    if isinstance(value, bool):
        raise ValueError(f"非法星期：{value!r}")
    if isinstance(value, int):
        if 1 <= value <= 7:
            return value
        raise ValueError(f"非法星期：{value!r}（超出 1..7）")
    if isinstance(value, float):
        # Excel 可能给出 3.0；仅接受整数值浮点。
        if value.is_integer() and 1 <= int(value) <= 7:
            return int(value)
        raise ValueError(f"非法星期：{value!r}")
    if not isinstance(value, str):
        raise ValueError(f"非法星期：{value!r}")
    s = _to_half_width(_strip_spaces(value))
    if not s:
        raise ValueError(f"非法星期：{value!r}（空）")
    if s.startswith("="):
        raise ValueError(f"非法星期：{value!r}（疑似公式）")
    if s.isdigit():
        w = int(s)
        if 1 <= w <= 7:
            return w
        raise ValueError(f"非法星期：{value!r}（超出 1..7）")
    if s in _WEEKDAY_MAP:
        return _WEEKDAY_MAP[s]
    raise ValueError(f"非法星期：{value!r}（仅支持 1~7 或周一..周日/星期一..星期日）")


def parse_period(
    value: str | int,
    slot_mapping: dict[int, int] | None = None,
) -> list[int]:
    """解析节次为排序去重后的标准大节列表。

    输入为**小节**编号（默认 1..10），按 ``slot_mapping`` 折算为大节。
    例如默认映射下 ``"1-2" -> [1]``，``"1-6" -> [1, 2, 3]``。

    若字符串包含 ``大``（如 ``大1``/``大节2``/``第1大节``），则直接按大节解析，
    取值范围为 ``1..max(slot_mapping.values())``（默认 1..5）。

    支持 ``1``、``1-2``、``1,2``、``第1-2节``、``1-2节``、``1-2,5-6`` 等组合。
    非法（倒置、越界、空结果）抛 ValueError。
    """
    mapping = slot_mapping if slot_mapping is not None else DEFAULT_SLOT_MAPPING
    if not mapping:
        raise ValueError("节次映射为空")
    max_raw = max(mapping.keys())
    min_raw = min(mapping.keys())
    max_slot = max(mapping.values())

    if isinstance(value, bool):
        raise ValueError(f"非法节次：{value!r}")
    if isinstance(value, int):
        if min_raw <= value <= max_raw and value in mapping:
            return [mapping[value]]
        raise ValueError(f"非法节次：{value!r}（超出小节 {min_raw}..{max_raw}）")
    if isinstance(value, float):
        if value.is_integer() and int(value) in mapping:
            return [mapping[int(value)]]
        raise ValueError(f"非法节次：{value!r}")
    if not isinstance(value, str):
        raise ValueError(f"非法节次：{value!r}")

    s = _to_half_width(_strip_spaces(value))
    if not s:
        raise ValueError(f"非法节次：{value!r}（空）")
    if s.startswith("="):
        raise ValueError(f"非法节次：{value!r}（疑似公式）")

    # 直接大节模式：包含“大”字
    if "大" in s:
        return _parse_big_slots(s, max_slot, original=value)

    # 小节模式：去掉装饰字 第 / 节 / 小
    t = s.replace("第", "").replace("节", "").replace("小", "")
    if not t or any(c in t for c in ("第", "节", "大", "小", "周", "单", "双")):
        raise ValueError(f"非法节次：{value!r}（无法识别）")
    parts = t.split(",")
    raw: list[int] = []
    for part in parts:
        if not part:
            raise ValueError(f"非法节次：{value!r}（存在空段）")
        raw.extend(_parse_int_range(part, min_raw, max_raw, original=value, label="节次"))
    if not raw:
        raise ValueError(f"非法节次：{value!r}（空结果）")
    slots: list[int] = []
    for r in raw:
        if r not in mapping:
            raise ValueError(f"非法节次：{value!r}（小节 {r} 无映射）")
        slots.append(mapping[r])
    return sorted(set(slots))


def _parse_big_slots(s: str, max_slot: int, original: object) -> list[int]:
    t = s.replace("第", "").replace("大", "").replace("节", "")
    if not t or any(c in t for c in ("第", "大", "节", "小", "周", "单", "双")):
        raise ValueError(f"非法节次：{original!r}（无法识别）")
    parts = t.split(",")
    out: list[int] = []
    for part in parts:
        if not part:
            raise ValueError(f"非法节次：{original!r}（存在空段）")
        out.extend(_parse_int_range(part, 1, max_slot, original=original, label="大节"))
    if not out:
        raise ValueError(f"非法节次：{original!r}（空结果）")
    return sorted(set(out))


def _parse_int_range(
    part: str, lo: int, hi: int, original: object, label: str
) -> list[int]:
    if "-" in part:
        if part.count("-") != 1:
            raise ValueError(f"非法{label}：{original!r}（段 {part!r} 格式错误）")
        a_str, b_str = part.split("-", 1)
        if not a_str or not b_str or not a_str.isdigit() or not b_str.isdigit():
            raise ValueError(f"非法{label}：{original!r}（段 {part!r} 数字错误）")
        a, b = int(a_str), int(b_str)
        if a > b:
            raise ValueError(f"非法{label}：{original!r}（段 {part!r} 倒置区间）")
        if a < lo or b > hi:
            raise ValueError(f"非法{label}：{original!r}（段 {part!r} 超出 {lo}..{hi}）")
        return list(range(a, b + 1))
    if not part.isdigit():
        raise ValueError(f"非法{label}：{original!r}（段 {part!r} 无法识别）")
    v = int(part)
    if v < lo or v > hi:
        raise ValueError(f"非法{label}：{original!r}（{v} 超出 {lo}..{hi}）")
    return [v]
