"""CI 门禁脚本自身的回归：它负责判断"别人是否真的通过"，所以它不能被悄悄掏空。

用合成的 junit XML 直接驱动 ci_gate.main，覆盖三条会被写成装饰性检查的规则：
基线棘轮、执行数下限、必须通过清单。
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "ci_gate", Path(__file__).resolve().parents[2] / "scripts" / "ci_gate.py"
)
ci_gate = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules["ci_gate"] = ci_gate
_SPEC.loader.exec_module(ci_gate)

_HEAD = '<testsuites><testsuite name="p" tests="{tests}" failures="{failures}" ' \
         'errors="0" skipped="{skipped}">'
_CASE = '<testcase classname="tests.unit.test_x" name="{name}">{body}</testcase>'


def _xml(cases, *, skipped=0):
    failed = sum(1 for _n, b in cases if b)
    body = "".join(_CASE.format(name=n, body='<failure msg="x"/>' if b else "") for n, b in cases)
    return _HEAD.format(tests=len(cases) + skipped, failures=failed, skipped=skipped) + body + \
        "</testsuite></testsuites>"


def _write(tmp_path, xml, baseline=None):
    report = tmp_path / "r.xml"
    report.write_text(xml, encoding="utf-8")
    args = [str(report)]
    if baseline is not None:
        bl = tmp_path / "baseline.txt"
        bl.write_text("".join(f"{n}\n" for n in baseline), encoding="utf-8")
        args += ["--baseline", str(bl)]
    return args


def _run(args):
    return ci_gate.main(args)


def test_ratchet_fires_even_while_other_baseline_items_are_still_red(tmp_path, capsys):
    """旧实现在"基线里还有红"时完全不检查棘轮，基线因此可以只增不减。"""
    xml = _xml([("test_kept_red", True), ("test_now_green", False)])
    args = _write(tmp_path, xml, baseline=[
        "tests/unit/test_x.py::test_kept_red",
        "tests/unit/test_x.py::test_now_green",
    ]) + ["--require-ran", "1"]
    assert _run(args) == 1
    out = capsys.readouterr().out
    assert "已经通过" in out and "test_now_green" in out
    assert "不在基线内" not in out  # 已知红项不该被算成新回归


def test_short_run_is_reported_as_incomplete_not_as_massive_ratchet(tmp_path, capsys):
    """整体跳过/未收集时只报"没跑够"，不刷屏要求删基线。"""
    xml = _xml([], skipped=300)
    args = _write(tmp_path, xml, baseline=["tests/unit/test_x.py::test_a"]) + [
        "--require-ran", "100"
    ]
    assert _run(args) == 1
    out = capsys.readouterr().out
    assert "疑似整体跳过" in out
    assert "已经通过" not in out


def test_skip_over_limit_fails(tmp_path, capsys):
    xml = _xml([("test_ok", False)], skipped=11)
    args = _write(tmp_path, xml) + ["--require-ran", "1", "--allow-skip-max", "10"]
    assert _run(args) == 1
    assert "超过允许上限" in capsys.readouterr().out


def test_new_failure_outside_baseline_fails(tmp_path, capsys):
    xml = _xml([("test_regressed", True)])
    args = _write(tmp_path, xml, baseline=["tests/unit/test_x.py::test_old"]) + [
        "--require-ran", "1"
    ]
    assert _run(args) == 1
    assert "不在基线内的失败 1 项" in capsys.readouterr().out


def test_require_pass_accepts_a_single_node_id(tmp_path, capsys):
    """新功能可以按用例名点名要求通过，而不必把整个历史文件都拉进必须通过范围。"""
    xml = _xml([("test_new_rule", True), ("test_legacy_red", True)])
    args = _write(tmp_path, xml, baseline=[
        "tests/unit/test_x.py::test_legacy_red",
        "tests/unit/test_x.py::test_new_rule",
    ]) + ["--require-ran", "1", "--require-pass", "tests/unit/test_x.py::test_new_rule"]
    assert _run(args) == 1
    assert "必须通过的" in capsys.readouterr().out


def test_clean_run_passes(tmp_path):
    xml = _xml([("test_a", False), ("test_b", False)])
    args = _write(tmp_path, xml) + ["--require-ran", "2"]
    assert _run(args) == 0


def test_baseline_shrinking_only_needs_deletion(tmp_path):
    """基线项全绿且没有其它红：仍然要求把它从清单删掉。"""
    xml = _xml([("test_now_green", False)])
    args = _write(tmp_path, xml, baseline=["tests/unit/test_x.py::test_now_green"]) + \
        ["--require-ran", "1"]
    assert _run(args) == 1


@pytest.mark.parametrize("flag", ["--require-ran", "--allow-skip-max"])
def test_gate_thresholds_are_enforceable(flag, tmp_path):
    """阈值必须真的能拦：把要求抬到超过实际执行数/允许跳过数，门禁就要红。"""
    if flag == "--require-ran":
        xml, value = _xml([("test_a", False)]), "5"
    else:
        xml, value = _xml([("test_a", False)], skipped=6), "5"
    args = _write(tmp_path, xml) + [flag, value]
    assert ci_gate.main(args) == 1
