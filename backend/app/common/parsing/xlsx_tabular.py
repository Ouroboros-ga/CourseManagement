"""表格式 xlsx 读取：把首个工作表按表头行读成 list[dict[str,str]]（技术方案 19）。

导入模板统一冻结为**表格式**（每行一条记录、首行为表头），与"方格课表"
(:mod:`app.common.parsing.grid`) 互补：方格用于贴合学校原始周课表导出，表格式
用于名单 / 志愿者资格 / 规范化课行长表这类结构化清单。

- 所有单元格按字符串取值并 strip，保留前导零（学号/班号不丢位，技术方案 8.1）；
- 表头到字段名的映射由 :data:`ALIASES` 归一（支持中英文/别名列头）；
- 只支持 .xlsx（openpyxl）。xls 需另行确认依赖，见 DEVELOPMENT_PLAN §6。
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 仅在类型检查期引入，运行时按需延迟导入 openpyxl
    from collections.abc import Iterable


def _clean(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        # Excel 数值单元格 2024.0 → "2024"，避免学号被写成浮点。
        return str(int(value))
    return str(value).strip()


def normalize_header(cell: str) -> str:
    return _clean(cell).replace(" ", "").lower()


class TableTooLarge(ValueError):
    """表格规模超出解析预算。

    与普通 ValueError 分开，是为了让解析失败**不会**再走一遍兜底链（改名 .xls、
    CSV 嗅探等）——那会把一次已经超限的解析重复成两三次。调用方仍按 ValueError
    捕获并映射为 422，语义不变。
    """


# 默认预算：单 worker 生产进程 MemoryMax=384M，全量载入工作表会直接 OOM 打死整个 API。
# 与 importer/limits.py 的字节预算分层：这里约束解析出的行列规模。
DEFAULT_MAX_ROWS = 20_000
DEFAULT_MAX_COLUMNS = 300


def _guard_columns(headers: list[str], max_columns: int) -> None:
    if len(headers) > max_columns:
        raise TableTooLarge(
            f"表格列数 {len(headers)} 超出解析上限 {max_columns}，请确认上传的是名单/课表模板而非汇总表"
        )


def _guard_row_count(count: int, max_rows: int) -> None:
    if count > max_rows:
        raise TableTooLarge(f"表格行数 {count} 超出解析上限 {max_rows}")


def _read_xls_tabular_rows(
    data: bytes,
    *,
    sheet_index: int = 0,
    header_row: int = 1,
    required_headers: Iterable[str] | None = None,
    include_source: bool = False,
    max_rows: int = DEFAULT_MAX_ROWS,
    max_columns: int = DEFAULT_MAX_COLUMNS,
) -> list[dict[str, str]]:
    import xlrd

    # on_demand 让工作表按需载入，避免一次物化整个 .xls 到内存。
    wb = xlrd.open_workbook(file_contents=data, on_demand=True)
    ws = wb.sheet_by_index(sheet_index)
    h_idx = header_row - 1
    if h_idx >= ws.nrows:
        raise ValueError("表头行超出工作表行数")
    headers = [_clean(ws.cell_value(h_idx, c)) for c in range(ws.ncols)]
    _guard_columns(headers, max_columns)
    if not any(headers):
        raise ValueError("表头行为空")
    normalized = [normalize_header(h) for h in headers]
    if required_headers is not None:
        missing = [
            req
            for req in required_headers
            if normalize_header(req) not in normalized
        ]
        if missing:
            raise ValueError(f"缺少必需列：{', '.join(missing)}")
    rows: list[dict[str, str]] = []
    for r in range(h_idx + 1, ws.nrows):
        record: dict[str, str] = {}
        non_empty = False
        for c, h in enumerate(headers):
            if not h:
                continue
            v = _clean(ws.cell_value(r, c))
            record[h] = v
            if v:
                non_empty = True
        if non_empty:
            if include_source:
                record["_source_row"] = str(r + 1)
                record["_source_sheet"] = ws.name
            rows.append(record)
            _guard_row_count(len(rows), max_rows)
    return rows


def read_any_matrix(
    data: bytes,
    *,
    max_rows: int = DEFAULT_MAX_ROWS,
    max_columns: int = DEFAULT_MAX_COLUMNS,
) -> list[list[str]]:
    """将 xlsx / xls / csv / 文本格式数据统一读取为行二维字符串矩阵 list[list[str]]。

    支持自动探测编码（utf-8-sig, utf-8, gb18030, gbk）与分隔符。
    规模超 `max_rows`/`max_columns` 抛 :class:`TableTooLarge`，并在越界处早停，
    不先把超限表全部物化再报错。
    """
    if not data:
        return []

    def _collect(rows) -> list[list[str]]:
        out: list[list[str]] = []
        for row in rows:
            cells = [_clean(c) for c in row]
            if len(cells) > max_columns:
                raise TableTooLarge(
                    f"表格列数 {len(cells)} 超出解析上限 {max_columns}"
                )
            out.append(cells)
            _guard_row_count(len(out), max_rows)
        return out

    # 1. xls 复合文档
    if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        import xlrd

        wb = xlrd.open_workbook(file_contents=data, on_demand=True)
        ws = wb.sheet_by_index(0)
        return _collect(
            (ws.row_values(r) for r in range(min(ws.nrows, max_rows + 1)))
        )

    # 2. xlsx (PK zip)
    if data.startswith(b"PK\x03\x04"):
        from openpyxl import load_workbook

        wb = load_workbook(
            filename=io.BytesIO(bytes(data)), data_only=True, read_only=True
        )
        try:
            ws = wb.worksheets[0]
            return _collect(ws.iter_rows(values_only=True))
        finally:
            wb.close()

    # 3. 文本 / CSV 格式探测与解析
    import csv

    for enc in ("utf-8-sig", "gb18030", "gbk", "utf-8"):
        try:
            text = data.decode(enc)
            sample = text[:4096]
            dialect: type[csv.Dialect] | csv.Dialect = csv.excel
            try:
                sniffer = csv.Sniffer()
                dialect = sniffer.sniff(sample, delimiters=",\t;")
            except Exception:
                pass
            reader = csv.reader(io.StringIO(text), dialect=dialect)
            return _collect(reader)
        except TableTooLarge:
            raise
        except Exception:
            continue

    # 4. 兜底尝试 openpyxl
    try:
        from openpyxl import load_workbook

        wb = load_workbook(
            filename=io.BytesIO(bytes(data)), data_only=True, read_only=True
        )
        try:
            ws = wb.worksheets[0]
            return _collect(ws.iter_rows(values_only=True))
        finally:
            wb.close()
    except TableTooLarge:
        raise
    except Exception:
        pass

    raise ValueError("无法识别的表格文件格式，请上传 .xlsx、.xls 或 .csv 文件")


def read_tabular_rows(
    data: bytes,
    *,
    sheet_index: int = 0,
    header_row: int = 1,
    required_headers: Iterable[str] | None = None,
    include_source: bool = False,
    max_rows: int = DEFAULT_MAX_ROWS,
    max_columns: int = DEFAULT_MAX_COLUMNS,
) -> list[dict[str, str]]:
    """读取 xlsx/xls 指定工作表，返回以**原始表头文本**为键的行字典列表。

    跳过全空行；数值型单元格整数值去尾零。找不到表头行或表头为空抛 ValueError，
    由上层导入服务捕获为 error 级 Issue。行列超出 `max_rows`/`max_columns` 抛
    :class:`TableTooLarge`，且不再进入兜底解析链。
    """
    # 检查是否为老旧的 .xls 复合文档格式 (OLE2 标识符)
    if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return _read_xls_tabular_rows(
            data,
            sheet_index=sheet_index,
            header_row=header_row,
            required_headers=required_headers,
            include_source=include_source,
            max_rows=max_rows,
            max_columns=max_columns,
        )

    try:
        from openpyxl import load_workbook

        # read_only=True 让 openpyxl 流式读取而不是物化整张工作表；
        # 代价是只能顺序 iter_rows，不能 ws.cell(row, column) 随机访问。
        wb = load_workbook(
            filename=io.BytesIO(bytes(data)), data_only=True, read_only=True
        )
        try:
            ws = wb.worksheets[sheet_index]
            stream = ws.iter_rows(values_only=True)
            headers: list[str] = []
            for index, raw in enumerate(stream, start=1):
                if index < header_row:
                    continue
                headers = [_clean(v) for v in raw]
                break
            if not headers:
                raise ValueError("表头行为空")
            _guard_columns(headers, max_columns)
            if not any(headers):
                raise ValueError("表头行为空")
            normalized = [normalize_header(h) for h in headers]
            if required_headers is not None:
                missing = [
                    req
                    for req in required_headers
                    if normalize_header(req) not in normalized
                ]
                if missing:
                    raise ValueError(f"缺少必需列：{', '.join(missing)}")
            rows: list[dict[str, str]] = []
            for offset, raw in enumerate(stream, start=header_row + 1):
                padded = list(raw) + [""] * (len(headers) - len(raw))
                record: dict[str, str] = {}
                non_empty = False
                for c, h in enumerate(headers, start=1):
                    if not h:
                        continue
                    v = _clean(padded[c - 1])
                    record[h] = v
                    if v:
                        non_empty = True
                if non_empty:
                    if include_source:
                        record["_source_row"] = str(offset)
                        record["_source_sheet"] = ws.title
                    rows.append(record)
                    # 早停：超限即抛，不把整张超限表读完再交给上层判断。
                    _guard_row_count(len(rows), max_rows)
            return rows
        finally:
            wb.close()
    except TableTooLarge:
        raise
    except Exception:
        # 若 openpyxl 无法解析（例如文件为改名的 .xls 或 csv），兜底尝试 xlrd 或文本矩阵
        try:
            return _read_xls_tabular_rows(
                data,
                sheet_index=sheet_index,
                header_row=header_row,
                required_headers=required_headers,
                include_source=include_source,
                max_rows=max_rows,
                max_columns=max_columns,
            )
        except TableTooLarge:
            raise
        except Exception:
            pass

        try:
            matrix = read_any_matrix(data)
            h_idx = header_row - 1
            if h_idx >= len(matrix):
                raise ValueError("表头行超出数据行数")
            headers = matrix[h_idx]
            _guard_columns(headers, max_columns)
            if not any(headers):
                raise ValueError("表头行为空")
            normalized = [normalize_header(h) for h in headers]
            if required_headers is not None:
                missing = [
                    req
                    for req in required_headers
                    if normalize_header(req) not in normalized
                ]
                if missing:
                    raise ValueError(f"缺少必需列：{', '.join(missing)}")
            rows = []
            for source_row, r_row in enumerate(matrix[h_idx + 1:], start=h_idx + 2):
                record = {}
                non_empty = False
                for c, h in enumerate(headers):
                    if not h:
                        continue
                    v = r_row[c] if c < len(r_row) else ""
                    record[h] = v
                    if v:
                        non_empty = True
                if non_empty:
                    rows.append(record)
                    _guard_row_count(len(rows), max_rows)
            return rows
        except TableTooLarge:
            raise
        except Exception:
            raise


def pick(row: dict[str, str], *names: str) -> str:
    """按候选列名（忽略大小写/空格）取第一个命中的非规范化键值。"""
    normalized = {normalize_header(k): v for k, v in row.items()}
    for n in names:
        v = normalized.get(normalize_header(n))
        if v is not None:
            return v
    return ""
