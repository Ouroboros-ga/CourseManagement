"""基础数据导入的解析层（时间标准化 + 方格课表）。

纯函数、不触库：Service 负责把 :mod:`app.common.parsing.dto` 里的解析结果
映射为 ORM。自遗留参考 ``docs/legacy_parser_reference/`` 移植并裁剪到
基础数据所需范围；参考目录仅作历史留档，运行时代码不导入它。
"""

from __future__ import annotations
