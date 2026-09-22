"""版本化周报产物构建（W7c，技术方案 18）。

纯计算、无数据库、无事务：把服务侧算好的聚合 payload 渲染为两份字节产物——
明细 JSON 快照（含个人异常明细，是"可复核事实"的归档形态）与 Excel 工作簿（界面/线下分发）。

克制原则（技术方案 §非目标）：真实学院 Excel 模板样例尚未提供，V1.0 以"后端算好写死数值 +
通用工作簿"交付，模板往返兼容待拿到真实样例后验收；此处不猜模板版式、不引入模板文件依赖。
每次调用 new 一个 Workbook 实例（不复用共享实例），杜绝并发/跨请求下的状态串写。
"""

from __future__ import annotations

import io
import json
from typing import Any

from openpyxl import Workbook

# Excel 产物的 MIME（openpyxl 输出 .xlsx）。
XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
JSON_CONTENT_TYPE = "application/json"

# 明细快照里个人异常的中文标签，仅用于报表可读性；不改写存储的枚举值。
_TYPE_LABEL = {"LEAVE": "请假", "LATE": "迟到", "ABSENT": "旷课", "NORMAL": "正常"}


def _to_serializable(obj: Any) -> Any:
    """兜底把 date/datetime 等转成 ISO 字符串，保证 JSON 可序列化。"""
    import datetime as _dt

    if isinstance(obj, (_dt.datetime, _dt.date)):
        return obj.isoformat()
    return str(obj)


def build_snapshot_json(payload: dict[str, Any]) -> bytes:
    """渲染明细 JSON 快照（稳定排序、UTF-8、缩进 2，便于归档与复核 diff）。"""
    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=False,
        default=_to_serializable,
    ).encode("utf-8")


def build_excel(payload: dict[str, Any]) -> bytes:
    """把聚合结果写成通用 .xlsx（汇总 + 班级 + 任务 + 个人明细 四表），写死数值。"""
    meta = payload.get("meta", {})
    overall = payload.get("overall", {})
    classes: list[dict[str, Any]] = payload.get("classes", [])
    tasks: list[dict[str, Any]] = payload.get("tasks", [])
    details: list[dict[str, Any]] = payload.get("details", [])

    wb = Workbook()

    # Sheet 1：汇总
    ws = wb.active
    ws.title = "汇总"
    ws.append(["学期ID", "周次", "范围", "符合条件任务数", "生成时源修订号"])
    ws.append(
        [
            str(meta.get("semester_id", "")),
            meta.get("week_no", ""),
            meta.get("scope", ""),
            meta.get("eligible_task_count", 0),
            meta.get("source_revision", 0),
        ]
    )
    ws.append([])
    ws.append(["统计可用", "有效应到", "异常合计", "请假", "迟到", "旷课", "出勤缺失率"])
    available = bool(overall.get("statistics_available"))
    rate = overall.get("abnormal_rate")
    ws.append(
        [
            "是" if available else "否（分母≤0，不显示比率）",
            overall.get("expected_count", 0),
            overall.get("abnormal_count", 0),
            overall.get("leave_count", 0),
            overall.get("late_count", 0),
            overall.get("absent_count", 0),
            ("" if rate is None else rate),
        ]
    )

    # Sheet 2：班级
    ws_cls = wb.create_sheet("班级")
    ws_cls.append(
        [
            "班级",
            "有效应到",
            "异常合计",
            "请假",
            "迟到",
            "旷课",
            "缺失率",
            "班级比率可用",
            "剔除任务数",
        ]
    )
    for c in classes:
        ws_cls.append(
            [
                c.get("class_name", ""),
                c.get("expected_count", 0),
                c.get("abnormal_count", 0),
                c.get("leave_count", 0),
                c.get("late_count", 0),
                c.get("absent_count", 0),
                c.get("abnormal_rate") if c.get("abnormal_rate") is not None else "",
                "是" if c.get("class_ratio_available") else "否",
                c.get("excluded_task_count", 0),
            ]
        )

    # Sheet 3：任务
    ws_task = wb.create_sheet("任务")
    ws_task.append(["任务ID", "应到", "异常", "应到已人工调整", "班级比率可用"])
    for t in tasks:
        ws_task.append(
            [
                str(t.get("task_id", "")),
                t.get("expected_count", 0),
                t.get("abnormal_count", 0),
                "是" if t.get("expected_count_adjusted") else "否",
                "是" if t.get("class_ratio_available") else "否",
            ]
        )

    # Sheet 4：个人明细
    ws_det = wb.create_sheet("异常明细")
    ws_det.append(["任务ID", "学号", "姓名", "班级", "认定"])
    for d in details:
        ws_det.append(
            [
                str(d.get("task_id", "")),
                d.get("student_no", ""),
                d.get("name", ""),
                d.get("class_name_snapshot") or "",
                _TYPE_LABEL.get(str(d.get("attendance_type", "")), d.get("attendance_type", "")),
            ]
        )

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


__all__ = ["build_snapshot_json", "build_excel", "XLSX_CONTENT_TYPE", "JSON_CONTENT_TYPE"]
