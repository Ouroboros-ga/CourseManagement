# 遗留解析代码暂存区（legacy_parser_reference）

> 本目录是从旧原型项目 `D:\My project\course`（Streamlit + SQLite 单体）
> 拷贝过来的**原始参考副本**，用于「查课管理系统」新后端的 Excel/课表文件
> 解析能力复用。此处文件保持原型原样，**不参与新后端构建、不被 app/ 导入**，
> 仅作为移植蓝本。适配时逐个搬进 `backend/app/` 并对齐新项目约定，改完后
> 回到这里在下方清单勾选进度。

## 来源与拷贝时间

- 源项目：`D:\My project\course`
- 拷贝日期：2026-09-20
- 技术栈差异：原型 = 顶层平铺模块 + SQLite + Streamlit；新后端 = FastAPI +
  SQLAlchemy 2.x（连真实 MySQL）+ 模块化单体 + Pydantic schemas。

## 为什么值得复用

原型里这套解析逻辑已经过测试验证，恰好命中新方案里「课程表/名单导入」的硬骨头：

1. `normalize.py` —— 中文时间标准化纯函数，零外部依赖。
   - `parse_weeks`：`1-16`、`1-15单周`、`2-16双周`、`1,3,5,8`、`第1-8周` 及组合
   - `parse_weekday`：`1~7` / `周一..周日` / `星期一..星期日`
   - `parse_period`：小节→标准大节折算、`大1`/`第1大节` 直接大节模式
   - 全角→半角、多种波浪线/破折号归一、拒绝公式残留、拒绝倒置区间/越界
2. `school_grid.py` —— 学校「方格课表」(xls/xlsx) 转标准长表。
   - 格子内 `课程◇X-Y周(单/双)(N-M节)◇地点◇教师◇选课人数` 的正则解析
   - 表头提取班级号、星期列定位、xls/xlsx 同版式复用
3. `excel_io.py`（仅**读取半区**有价值）—— 标准四表工作簿导入。
   - 表头**别名映射**（学号/学生学号/student_no → 同一字段）
   - **公式单元格防御**（`=+-@` 一律按文本、拒绝公式执行）
   - 逐行**结构化错误报告**（Issue: code/sheet/row/field）+ 跨表引用校验
   - 注：`export_workbook` 是排班结果专用导出，本阶段用不到，移植时可舍弃
4. `models.py` —— 原型领域 DTO（dataclass）。移植时用作新解析层 DTO 的**参照**，
   新项目最终会以 Pydantic schema / ORM 模型替换，不直接沿用。

## 移植时的三处关键适配（不要原样搬进 app/）

1. **导入方式**：原型是 `from models import ...` / `from normalize import ...`
   顶层平铺导入；搬进 `backend/app/` 后必须改成包内绝对导入（如
   `from app.common.parsing.time_slots import parse_weeks`），否则
   `uv run mypy app` / `ruff` / 打包只认 app 包内代码。
2. **输出契约**：解析层现在吐原型 dataclass；新后端 `academic` 模块尚无课表/
   任务 ORM。需先为解析结果定义轻量 DTO，Service 再做 DTO→ORM 落库。
3. **错误模型**：解析错误现在返回 `Issue` 列表；新后端有统一
   `AppError + ErrorCode + fieldErrors`（见 `backend/app/core/exceptions.py`）。
   适配层把 `Issue` 映射成 `AppError` 的 fieldErrors 即可。

## 建议落点结构（后续适配目标，本目录不是）

```
backend/app/common/parsing/
  __init__.py
  time_slots.py     # ← normalize.py（原文搬运，最高优先，几乎零改动）
  grid.py           # ← school_grid.py 解析部分（BLOCK_RE 等纯字符串）
  excel_roster.py   # ← excel_io.py 读取半区 + 模板生成
backend/tests/unit/parsing/
  test_time_slots.py   # ← tests/test_normalize.py
  test_grid.py         # ← tests/test_school_grid.py
  test_excel_roster.py # ← tests/test_excel_io.py
```

## 依赖注意

- 新后端已装 `openpyxl` + `defusedxml`（见 pyproject.toml），xlsx 解析可直接用。
- 原型 xls 老格式依赖 `xlrd`，新后端**未安装**。若后续确认要支持 .xls，再单独
  引入；.xlsx 版式无需 xlrd。

## 移植进度清单

- [ ] `normalize.py` → `app/common/parsing/time_slots.py` + 测试跑通
- [ ] `school_grid.py` 解析 → `app/common/parsing/grid.py` + 测试跑通
- [ ] `excel_io.py` 读取半区 → `app/common/parsing/excel_roster.py` + 测试跑通
- [ ] 定义解析结果 DTO（Pydantic）替换原型 dataclass 输出
- [ ] `Issue` → `AppError/fieldErrors` 适配层
- [ ] academic 模块 ORM（课表/行政班扩展）落地后接 Service 落库
- [ ] 全部搬完且 app/ 内测试绿后，删除本暂存目录（或保留为归档）
