"""CI 发布门禁：把"历史红测"与"本次必须通过"分开，同时禁止静默跳过。

用法：
    python scripts/ci_gate.py reports/junit.xml \
        --baseline tests/ci_baseline_unit.txt \
        --require-ran 800 \
        --require-pass tests/unit/test_submission_correction_window.py \
        --require-pass tests/unit/test_parsing_budgets.py

判定规则（任一不满足即退出码 1）：
1. 真正执行的用例数（收集数减跳过数）< --require-ran → 失败。集成测试因缺库被整体跳过时
   收集数照常计入，只有减去 skipped 才能看出"一行都没跑"，这一条就会红。
2. 跳过数 > --allow-skip-max → 失败。
3. 失败用例不在 --baseline 清单里 → 失败。历史债务单独记账，新增回归不被掩盖。
4. baseline 里的用例这次通过了 → 失败（棘轮）：要求把它从清单删除，避免基线只增不减、
   慢慢变成第二套"默认通过"。只要这次真的跑够了数量就强制检查，不因为基线里还有其它红
   而免检。
5. 每个 --require-pass 前缀（可以是文件，也可以是单个用例节点 ID）必须全部通过 → 否则失败。
   新功能测试不受基线豁免。
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _node_ids(suite: ET.Element, wanted: str) -> set[str]:
    found: set[str] = set()
    for case in suite.iter("testcase"):
        status = case.find(wanted)
        if status is not None:
            classname = case.get("classname", "").replace(".", "/")
            # classname 形如 tests.unit.test_x，用例名可能带参数化后缀。
            found.add(f"{classname}.py::{case.get('name')}")
    return found


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("junit")
    parser.add_argument("--baseline", default=None)
    parser.add_argument("--require-ran", type=int, default=0)
    parser.add_argument("--allow-skip-max", type=int, default=sys.maxsize)
    parser.add_argument("--require-pass", action="append", default=[])
    args = parser.parse_args(argv)

    root = ET.parse(args.junit).getroot()
    suites = root.iter("testsuite") if root.tag == "testsuites" else iter([root])

    ran = failures = skipped = 0
    failed_ids: set[str] = set()
    for suite in suites:
        ran += int(suite.get("tests", 0))
        failures += int(suite.get("failures", 0)) + int(suite.get("errors", 0))
        skipped += int(suite.get("skipped", 0))
        failed_ids |= _node_ids(suite, "failure") | _node_ids(suite, "error")

    baseline: set[str] = set()
    if args.baseline:
        path = Path(args.baseline)
        if path.is_file():
            baseline = {
                line.strip()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")
            }

    problems: list[str] = []

    # "执行数"必须是真跑过的用例数。pytest 的 junit 把 skipped 也计入 tests 属性，所以直接拿
    # tests 比较会让"整体跳过"的运行蒙混过关——那正是这条检查要防的情形。
    executed = ran - skipped
    if executed < args.require_ran:
        problems.append(
            f"实际执行 {executed} 个用例（收集 {ran}、跳过 {skipped}），"
            f"低于要求的 {args.require_ran}：疑似整体跳过或未收集。"
        )
    if skipped > args.allow_skip_max:
        problems.append(f"跳过 {skipped} 个用例，超过允许上限 {args.allow_skip_max}。")

    new_failures = sorted(failed_ids - baseline)
    newly_green = sorted(baseline - failed_ids)
    if new_failures:
        problems.append(f"不在基线内的失败 {len(new_failures)} 项：")
        problems.extend(f"  - {name}" for name in new_failures[:40])
    for pattern in args.require_pass:
        offenders = sorted(name for name in failed_ids if name.startswith(pattern))
        if offenders:
            problems.append(f"必须通过的 {pattern} 出现失败：")
            problems.extend(f"  - {name}" for name in offenders[:20])

    # 棘轮只在显式提供基线时生效；CI 里基线文件随仓库走。
    # 原来附带 `and not failures`，于是只要基线里还剩任何一项红，"基线项已经变绿"就永远不被
    # 检查——基线因此可以只增不减。改为只要这次真的跑够了数量就强制检查；跑得不完整时由
    # require-ran 那条单独定性，避免把两种问题混成一片噪音。
    if args.baseline and newly_green and executed >= args.require_ran:
        problems.append(
            f"基线里 {len(newly_green)} 项已经通过，请从 {args.baseline} 删除："
        )
        problems.extend(f"  - {name}" for name in newly_green[:20])

    print(f"ran={ran} failed={failures} skipped={skipped} baseline={len(baseline)}")
    if problems:
        print("\n".join(problems))
        return 1
    print("GATE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
