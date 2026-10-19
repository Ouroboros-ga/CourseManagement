"""Bounded security release; root only, no migrations or business-data writes.

Usage: python deploy_security_baseline.py bundle.tar.gz sha256
The bundle contains manifest.json, backend patches, edge configuration and web/.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path('/opt/course-management')
RELEASE = '20261018-security-baseline'
SITE = Path('/etc/nginx/sites-available/course-management.conf')
CONFIG = Path('/etc/course-management')
BACKEND_FILES = {
    'backend/app/api/health.py', 'backend/app/core/middleware.py',
    'backend/app/core/security.py', 'backend/app/main.py',
    'backend/app/modules/identity/service.py',
}


def run(*args):
    subprocess.run(args, check=True)


def switch(pointer, target):
    pending = pointer.with_name(pointer.name + '.security-pending')
    pending.symlink_to(target)
    os.replace(pending, pointer)


def request(url, data=None):
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        return urllib.request.urlopen(req, timeout=5)
    except urllib.error.HTTPError as exc:
        return exc


def ready(url):
    for _ in range(40):
        try:
            with request(url) as reply:
                if reply.status == 200 and json.load(reply)['status'] == 'ok':
                    return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError('Readiness failed: ' + url)


def main():
    assert os.geteuid() == 0
    archive, expected = sys.argv[1:]
    assert hashlib.sha256(Path(archive).read_bytes()).hexdigest() == expected
    stage = ROOT / 'security-staging' / RELEASE
    stage.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive) as bundle:
        bundle.extractall(stage, filter='data')
    manifest = json.loads((stage / 'manifest.json').read_text())
    assert set(manifest['backend_base_sha256']) == BACKEND_FILES
    old = (ROOT / 'current').resolve()
    old_web = (ROOT / 'admin-web/current').resolve()
    assert str(old) == manifest['expected_backend']
    assert str(old_web) == manifest['expected_web']
    for name, digest in manifest['backend_base_sha256'].items():
        contents = (old / name).read_bytes().replace(b'\r\n', b'\n')
        assert hashlib.sha256(contents).hexdigest() == digest, name
    for name, digest in manifest['files_sha256'].items():
        assert hashlib.sha256((stage / name).read_bytes()).hexdigest() == digest, name
    assert SITE.resolve() == SITE
    backup = ROOT / 'security-backups' / RELEASE
    backup.mkdir(parents=True, mode=0o700, exist_ok=False)
    targets = [SITE, CONFIG / 'security-headers.conf', CONFIG / 'course-management-proxy.conf']
    existed = {str(p): p.exists() for p in targets}
    for p in targets:
        if p.exists():
            shutil.copy2(p, backup / p.name)
    report = {'release': RELEASE, 'previous_backend': str(old), 'previous_web': str(old_web),
              'bundle_sha256': expected, 'database_migration': False,
              'business_data_writes': False, 'config_backup': str(backup)}
    (backup / 'report.json').write_text(json.dumps(report, indent=2))
    new = ROOT / 'releases' / RELEASE
    new_web = ROOT / 'admin-web/releases' / RELEASE
    assert not new.exists() and not new_web.exists()
    shutil.copytree(old, new, symlinks=True)
    for name in BACKEND_FILES:
        shutil.copyfile(stage / name, new / name)
        (new / name).chmod(0o644)
    for source in (stage / 'deploy/production').iterdir():
        shutil.copyfile(source, new / 'deploy/production' / source.name)
    shutil.copytree(stage / 'web', new_web)
    # Keep old hashed assets available to already-open SPA tabs after the switch.
    for p in (old_web / 'assets').iterdir():
        if p.is_file() and not (new_web / 'assets' / p.name).exists():
            shutil.copyfile(p, new_web / 'assets' / p.name)
    for p in [new_web, *new_web.rglob('*')]:
        p.chmod(0o755 if p.is_dir() else 0o644)
    from dotenv import dotenv_values
    env = dict(os.environ)
    env.update({k: v for k, v in dotenv_values(CONFIG / 'backend.env').items() if v is not None})
    log = (backup / 'candidate.log').open('wb')
    candidate = subprocess.Popen(
        [str(new / 'backend/.venv/bin/python'), '-m', 'uvicorn', 'app.main:app',
         '--host', '127.0.0.1', '--port', '18011', '--no-access-log'],
        cwd=new / 'backend', env=env, stdout=log, stderr=log,
        user='course-management', group='course-management',
    )
    switched = False
    config_changed = False
    try:
        ready('http://127.0.0.1:18011/health/ready')
        with request('http://127.0.0.1:18011/health/ready') as reply:
            body = json.load(reply)
            assert 'database' not in body and 'env' not in body
            assert reply.headers['X-Frame-Options'] == 'DENY'
        for path in ['/docs', '/redoc', '/openapi.json']:
            with request('http://127.0.0.1:18011' + path) as reply:
                assert reply.status == 404
        with request('http://127.0.0.1:18011/api/v1/auth/web/login',
                     b'{"username":"security-nonexistent-c57a1d8b","password":"invalid-fixture"}') as reply:
            assert reply.status == 401
        candidate.terminate()
        candidate.wait(timeout=10)
        config_changed = True
        shutil.copyfile(stage / 'deploy/production/course-management.nginx.conf', SITE)
        for name in ['security-headers.conf', 'course-management-proxy.conf']:
            shutil.copyfile(stage / 'deploy/production' / name, CONFIG / name)
            (CONFIG / name).chmod(0o644)
        run('nginx', '-t')
        switch(ROOT / 'current', new)
        switched = True
        switch(ROOT / 'admin-web/current', new_web)
        run('systemctl', 'restart', 'course-management')
        ready('http://127.0.0.1:8011/health/ready')
        run('systemctl', 'reload', 'nginx')
        # Accountless and read-only public acceptance; the gate also checks host configuration.
        run('bash', str(stage / 'deploy/production/verify_security_baseline.sh'),
            '--nginx-conf', str(SITE))
        report['status'] = 'deployed_and_verified'
        report['backend'] = str(new)
        report['web'] = str(new_web)
        report['manifest'] = manifest
        (new / 'SECURITY_RELEASE.json').write_text(json.dumps(report, indent=2))
        (backup / 'report.json').write_text(json.dumps(report, indent=2))
        print(json.dumps({k: v for k, v in report.items() if k != 'manifest'}, indent=2))
    except BaseException:
        if switched:
            switch(ROOT / 'current', old)
            switch(ROOT / 'admin-web/current', old_web)
        if config_changed:
            for p in targets:
                if existed[str(p)]:
                    shutil.copy2(backup / p.name, p)
                else:
                    p.unlink(missing_ok=True)
            run('nginx', '-t')
            run('systemctl', 'reload', 'nginx')
        if switched:
            run('systemctl', 'restart', 'course-management')
            ready('http://127.0.0.1:8011/health/ready')
        raise
    finally:
        if candidate.poll() is None:
            candidate.terminate()
            candidate.wait(timeout=10)
        log.close()


if __name__ == '__main__':
    main()
