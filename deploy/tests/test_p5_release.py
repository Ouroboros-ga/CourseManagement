import runpy
from pathlib import Path


def test_copied_console_launchers_use_release_python(tmp_path):
    module = runpy.run_path(str(Path(__file__).parents[1] / "production/deploy_campus_p5_20261015.py"))
    source, target = tmp_path / "private-runtime/.venv", tmp_path / "release/.venv"
    (target / "bin").mkdir(parents=True)
    command = target / "bin/uvicorn"
    command.write_text(f"#!{source}/bin/python\nprint('launch')\n")
    command.chmod(0o755)
    module["relocate_launchers"](source, target)
    assert command.read_text().splitlines()[0] == f"#!{target}/bin/python"
