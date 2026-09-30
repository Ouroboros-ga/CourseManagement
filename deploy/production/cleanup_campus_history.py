"""已验证最终备份后，清理明确属于校园应用的旧发布目录。"""
import json
import re
import shutil
import subprocess
from pathlib import Path

backup = Path('/var/backups/campus-innovation-hub-final-20260930')
subprocess.run(['sha256sum', '-c', 'SHA256SUMS'], cwd=backup, check=True,
               stdout=subprocess.DEVNULL)
assert (backup / 'actual-business.dump').stat().st_size > 1000
assert (backup / 'restore-verification.log').exists()
latest = Path('/opt/campus-innovation-hub/releases/0b9a6eb6bda5d609211eaea4327f4d73d5b2b9d5')
assert Path('/opt/campus-innovation-hub/current').resolve() == latest
targets = []
for path in latest.parent.iterdir():
    if path != latest:
        assert re.fullmatch(r'[a-f0-9]{40}', path.name), path.name
        targets.append(path)
for path in Path('/opt').iterdir():
    if path.name == 'campus-innovation-hub-dev' or re.match(r'^campus-innovation-hub-be\d{3}-', path.name):
        targets.append(path)
legacy = Path('/opt/backups/campus-innovation-hub')
if legacy.exists():
    targets.append(legacy)
# 删除前一次性检查所有目标；不跟随符号链接或越出指定校园应用目录。
for path in targets:
    assert not path.is_symlink(), str(path)
    resolved = path.resolve(strict=True)
    assert resolved == path and resolved != latest
    assert resolved.parent in (Path('/opt'), latest.parent, Path('/opt/backups'))
    assert resolved.is_dir()
(backup / 'removed-history.json').write_text(json.dumps([str(p) for p in targets], indent=2))
for path in targets:
    shutil.rmtree(path)
assert list(latest.parent.iterdir()) == [latest]
print(f'Removed {len(targets)} campus history directories; current release retained')
