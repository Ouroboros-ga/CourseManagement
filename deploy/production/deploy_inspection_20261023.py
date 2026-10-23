"""Paired inspection release with guarded additive migration and protected database backup."""
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/opt/course-management')
INPUT = Path(__file__).resolve().parent
M = json.loads((INPUT / 'manifest.json').read_text())
NAME = M['release']
assert re.fullmatch(r'20261023-inspection-[0-9a-f]{10}', NAME)
BACK = ROOT / 'releases' / NAME
WEB = ROOT / 'admin-web/releases' / NAME
OLD = (ROOT / 'current').resolve()
OLDWEB = (ROOT / 'admin-web/current').resolve()
BACKUP = Path('/var/backups/course-management') / NAME
UNIT = 'cm-inspection-candidate'
ENV = Path('/etc/course-management/backend.env')

def run(*args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, **kwargs)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def verify(base, files):
    for name, sha in files.items():
        path = (base / name).resolve()
        assert path.is_relative_to(base.resolve()) and path.is_file(), name
        assert digest(path) == sha, 'File drift: ' + name

def schema():
    return subprocess.check_output(['docker', 'exec', '-i', 'course-management-mysql', 'mysql',
        '--defaults-extra-file=/run/cm-root.cnf', '-N', '-e',
        'SELECT version_num FROM course_management.alembic_version'], text=True).strip()

def request(url, method='GET'):
    req = urllib.request.Request(url, data=b'{}' if method == 'POST' else None,
                                 headers={'Content-Type': 'application/json'}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()

def probe(port):
    base = 'http://127.0.0.1:' + str(port)
    for _ in range(80):
        try:
            code, data = request(base + '/health/ready')
            if code == 200 and json.loads(data).get('status') == 'ok':
                break
        except Exception:
            pass
        time.sleep(.5)
    else:
        raise RuntimeError('Candidate not ready')
    checked = {}
    for method, path in [('GET', '/api/v1/me'), ('GET', '/api/v1/files/1/access?delivery=direct'),
        ('GET', '/api/v1/colleges/1/academic/master-timetable?semester_id=1'),
        ('POST', '/api/v1/inspection-tasks/1/exception'),
        ('POST', '/api/v1/colleges/1/inspection-tasks/1/exception/clear'),
        ('GET', '/api/v1/colleges/1/assignment-change-requests?semester_id=1&page_size=50')]:
        code, _ = request(base + path, method)
        assert code == 401, (method, path, code)
        checked[method + ' ' + path] = code
    return checked

def switch(pointer, target):
    pending = pointer.with_name(pointer.name + '.inspection-pending')
    assert not pending.exists() and not pending.is_symlink()
    pending.symlink_to(target)
    os.replace(pending, pointer)

def mysql_acceptance():
    result = run(BACK/'backend/.venv/bin/python',
        BACK/'deploy/production/verify_inspection_20261023.py', BACKUP,
        cwd=BACK/'backend', env={**os.environ, 'PYTHONPATH':str(BACK/'backend')},
        capture_output=True, text=True)
    return json.loads(result.stdout.strip())


def sql(statement):
    return subprocess.check_output(['docker','exec','-i','course-management-mysql','mysql',
        '--defaults-extra-file=/run/cm-root.cnf','-N','-e',statement],text=True).strip()


def row_counts():
    tables=sql("SELECT table_name FROM information_schema.tables WHERE table_schema='course_management' AND table_type='BASE TABLE'").splitlines()
    assert tables and all(re.fullmatch(r'[a-z0-9_]+',t) for t in tables)
    return {table:int(sql(f"SELECT COUNT(*) FROM course_management.`{table}`")) for table in tables}


def migrate(state):
    # Never print credentials. DDL uses the separately provisioned migration account.
    code = """
import os, subprocess, sys
from pathlib import Path
from dotenv import dotenv_values
from sqlalchemy.engine import make_url
runtime={**os.environ,**{k:v for k,v in dotenv_values('/etc/course-management/backend.env').items() if v is not None}}
env={**runtime,**{k:v for k,v in dotenv_values('/etc/course-management/migration.env').items() if v is not None}}
a,b=make_url(runtime['DATABASE_URL']),make_url(env['DATABASE_URL'])
assert a.database==b.database=='course_management' and a.host==b.host and a.port==b.port
env['PYTHONPATH']=str(Path.cwd())
p=subprocess.run([sys.executable,'-m','alembic','upgrade','f26a1023x001'],env=env,capture_output=True,text=True)
Path(os.environ['MIGRATION_LOG']).write_text(p.stdout+p.stderr)
if p.returncode: raise RuntimeError('Production migration failed; inspect protected log')
"""
    run('systemctl','stop','course-management')
    try:
        output=subprocess.check_output(['bash',ROOT/'backup.sh'],text=True)
        match=re.search(r'Backup completed: (/var/backups/course-management/[^\s]+)',output)
        assert match, 'Backup did not complete'
        backup=Path(match.group(1)).resolve()
        assert backup.parent == BACKUP.parent
        run('sha256sum','--check','SHA256SUMS',cwd=backup,stdout=subprocess.DEVNULL)
        state['database_backup']=str(backup)
        before=row_counts()
        (BACKUP/'business-counts-before.json').write_text(json.dumps(before,indent=2))
        run(BACK/'backend/.venv/bin/python','-c',code,cwd=BACK/'backend',
            env={**os.environ,'MIGRATION_LOG':str(BACKUP/'production-migration.log')},
            capture_output=True,text=True)
        assert schema()==M['migration_head']
        after=row_counts()
        assert before==after, 'Production row counts changed'
        assert sql("SELECT COUNT(*) FROM course_management.inspection_task WHERE exception_reported_at IS NOT NULL")=="0"
        state.update(migration_executed=True,migration_head=schema(),business_row_counts_preserved=True)
        (BACKUP/'business-counts-after.json').write_text(json.dumps(after,indent=2))
        (BACKUP/'before.json').write_text(json.dumps(state,indent=2))
    finally:
        # Previous application accepts the additive schema; it stays live during candidate probes.
        run('systemctl','start','course-management')


def main():
    lock = open('/var/backups/course-management/deploy.lock', 'a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert OLD.name == M['expected_backend'] and OLDWEB.name == M['expected_web'], 'Pointers changed'
    assert schema() == M['previous_migration_head'], 'Schema drift'
    assert not BACK.exists() and not WEB.exists() and not BACKUP.exists()
    prior = json.loads((OLD/'RELEASE.json').read_text())
    prior_files = prior.get('files_sha256') or prior.get('runtime_files') or prior.get('source_files')
    assert prior_files and prior['source_commit'] == M['expected_source']
    verify(OLD, {k:v for k,v in prior_files.items() if k.startswith('backend/')})
    config = digest(ENV)
    for name, key in [('backend.tar.gz', 'backend_sha256'), ('web.tar.gz', 'web_sha256')]:
        assert digest(INPUT/name) == M[key]
    BACKUP.mkdir(mode=0o700)
    shutil.copyfile(ENV, BACKUP/'backend.env'); (BACKUP/'backend.env').chmod(0o600)
    shutil.copyfile(OLD/'RELEASE.json', BACKUP/'previous-backend-RELEASE.json')
    state = {'release':NAME,'source_commit':M['source_commit'],'old_backend':str(OLD),
        'old_web':str(OLDWEB),'backup':str(BACKUP),'migration_head':schema(),
        'configuration_sha256':config,'migration_executed':False,'production_business_data_written':False,
        'status':'preparing'}
    (BACKUP/'before.json').write_text(json.dumps(state,indent=2))
    rollback = '''import json,os,subprocess,sys,time,urllib.request
from pathlib import Path
d=json.loads(Path(__file__).with_name('before.json').read_text())
if sys.argv[1:]!=['--apply']: print(json.dumps(d));raise SystemExit(0)
root=Path('/opt/course-management')
def sql(statement):
 return subprocess.check_output(['docker','exec','-i','course-management-mysql','mysql','--defaults-extra-file=/run/cm-root.cnf','-N','-e',statement],text=True).strip()
columns=sql("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='course_management' AND table_name='inspection_task' AND column_name='exception_reported_at'")
if columns!='0':
 facts=int(sql("SELECT COUNT(*) FROM course_management.inspection_task WHERE exception_reported_at IS NOT NULL"))+int(sql("SELECT COUNT(*) FROM course_management.task_deadline_assessment WHERE result='EXCEPTION'"))
 if facts:raise RuntimeError('Exception facts already exist: retain compatible new application and repair forward; old code cannot represent these facts')
# Keep additive schema. Do not downgrade or restore a live database automatically.
for p,t in [(root/'current',d['old_backend']),(root/'admin-web/current',d['old_web'])]:
 assert p.resolve().name in [d['release'],Path(t).name]
 q=p.with_name(p.name+'.clock-rollback');assert not q.exists() and not q.is_symlink();q.symlink_to(t);os.replace(q,p)
subprocess.run(['systemctl','restart','course-management'],check=True)
for _ in range(80):
 try:
  with urllib.request.urlopen('http://127.0.0.1:8011/health/ready',timeout=3) as r:assert r.status==200
  print('Rollback healthy');break
 except Exception:time.sleep(.5)
else:raise RuntimeError('Rollback health failed')
'''
    (BACKUP/'rollback.py').write_text(rollback)
    for name in ['manifest.json','deploy.py']:
        shutil.copyfile(INPUT/name, BACKUP/name)
    switched = False
    try:
        for name, dest in [('backend.tar.gz',BACK),('web.tar.gz',WEB)]:
            dest.mkdir(mode=0o755)
            with tarfile.open(INPUT/name) as bundle:
                bundle.extractall(dest, filter='data')
        verify(BACK,M['source_files']); verify(WEB,M['web_files'])
        assert (BACK/'backend/uv.lock').read_bytes().replace(b'\r\n',b'\n') == (OLD/'backend/uv.lock').read_bytes().replace(b'\r\n',b'\n')
        for dest in [BACK,WEB]:
            for path in dest.rglob('*'):
                path.chmod(0o755 if path.is_dir() else 0o644)
        run('cp','-a',OLD/'backend/.venv',BACK/'backend/.venv')
        run('python3',BACK/'deploy/production/selfcontain_release_venv.py','--apply','--release',NAME)
        for asset in (OLDWEB/'assets').iterdir():
            target = WEB/'assets'/asset.name
            if asset.is_file() and not target.exists(): shutil.copyfile(asset,target);target.chmod(0o644)
        state['mysql_acceptance'] = mysql_acceptance()
        run('nginx','-t')
        migrate(state)
        run('systemd-run','--unit='+UNIT,'--property=User=course-management',
            '--property=Group=course-management','--property=WorkingDirectory='+str(BACK/'backend'),
            '--property=EnvironmentFile='+str(ENV),'--property=MemoryMax=384M',
            BACK/'backend/.venv/bin/python','-m','uvicorn','app.main:app',
            '--host','127.0.0.1','--port','18043','--no-access-log')
        state['candidate'] = probe(18043)
        assert digest(ENV) == config and schema() == M['migration_head']
        assert (ROOT/'current').resolve() == OLD and (ROOT/'admin-web/current').resolve() == OLDWEB
        switched = True
        switch(ROOT/'current',BACK);switch(ROOT/'admin-web/current',WEB)
        run('systemctl','restart','course-management')
        state['live'] = probe(8011)
        assert digest(ENV) == config and schema() == M['migration_head']
        verify(BACK,M['source_files']); verify(WEB,M['web_files'])
        run('systemctl','is-active','course-management')
        state.update(status='deployed',deployed_at=datetime.now(timezone.utc).isoformat(),
                     files_verified=len(M['source_files']),web_files_verified=len(M['web_files']))
        for dest in [BACK,WEB]:
            (dest/'RELEASE.json').write_text(json.dumps({**M,**state},indent=2))
        (BACKUP/'report.json').write_text(json.dumps(state,indent=2))
        print(json.dumps(state))
    except BaseException:
        if switched:
            try:
                run('python3',BACKUP/'rollback.py','--apply')
                state['status']='rolled-back-schema-retained'
            except Exception:
                state['status']='rollback-blocked-repair-forward'
                (BACKUP/'report.json').write_text(json.dumps(state,indent=2))
                raise
        else: state['status']='candidate-failed'
        (BACKUP/'report.json').write_text(json.dumps(state,indent=2))
        raise
    finally:
        subprocess.run(['systemctl','stop',UNIT],check=False,capture_output=True)

if __name__ == '__main__': main()
