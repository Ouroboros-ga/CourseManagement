"""首次部署专用：在服务器生成凭证；拒绝覆盖已有配置或数据库容器。"""
from pathlib import Path
import secrets
import subprocess

ROOT = Path('/etc/course-management')
if (ROOT / 'backend.env').exists():
    raise SystemExit('Existing backend.env: refusing to overwrite credentials')
if subprocess.run(['docker', 'container', 'inspect', 'course-management-mysql'],
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
    raise SystemExit('Existing database container: inspect before continuing')

ROOT.mkdir(mode=0o700, exist_ok=True)

def private_file(name: str, content: str) -> None:
    path = ROOT / name
    with path.open('x') as handle:
        handle.write(content)
    path.chmod(0o600)

root_password = secrets.token_hex(32)
migration_password = secrets.token_hex(32)
runtime_password = secrets.token_hex(32)
private_file('mysql.env', f'MYSQL_ROOT_PASSWORD={root_password}\nMYSQL_DATABASE=course_management\nMYSQL_USER=cm_migrate\nMYSQL_PASSWORD={migration_password}\n')
private_file('mysql-root.cnf', f'[client]\nuser=root\npassword={root_password}\n')
private_file('migration.env', f'DATABASE_URL=mysql+pymysql://cm_migrate:{migration_password}@127.0.0.1:13308/course_management?charset=utf8mb4\n')
private_file('runtime-user.sql', f"CREATE USER 'cm_runtime'@'%' IDENTIFIED BY '{runtime_password}';\nGRANT SELECT, INSERT, UPDATE, DELETE ON course_management.* TO 'cm_runtime'@'%';\n")
private_file('initial-admin.env', f'SEED_ADMIN_PASSWORD={secrets.token_urlsafe(24)}\n')
template = Path('/opt/course-management/releases/20260930-02/deploy/production/backend.env.example').read_text()
private_file('backend.env', template.replace('GENERATED_PASSWORD', runtime_password)
             .replace('GENERATE_ON_SERVER', secrets.token_hex(48))
             .replace('API_DOMAIN', 'course.zsitai.xyz'))
print('Credentials generated in /etc/course-management; values withheld')
