"""服务器上执行真实 HTTPS 验证；不输出密码、访问令牌或 Cookie 值。"""
import json
from pathlib import Path
import httpx

base = 'https://course.zsitai.xyz'
password = Path('/etc/course-management/initial-admin.env').read_text().strip().split('=', 1)[1]
results = {}
with httpx.Client(base_url=base, timeout=30, trust_env=False) as client:
    for probe in ('live', 'ready'):
        reply = client.get('/health/' + probe)
        assert reply.status_code == 200, (probe, reply.status_code)
        results[probe] = reply.json()['status']
    assert client.get('/api/v1/me').status_code == 401
    results['unauthenticated'] = 401
    reply = client.post('/api/v1/auth/web/login', json={'username': 'admin', 'password': password})
    assert reply.status_code == 200, reply.status_code
    data = reply.json()['data']
    assert 'refresh_token' not in data
    cookie = reply.headers['set-cookie'].lower()
    for attribute in ('httponly', 'secure', 'samesite=lax', 'path=/api/v1/auth'):
        assert attribute in cookie, attribute
    results['secure_cookie'] = True
    access = data['access_token']
    headers = {'Authorization': 'Bearer ' + access}
    assert client.get('/api/v1/me', headers=headers).status_code == 200
    assert client.get('/api/v1/academic/semesters', headers=headers).status_code == 200
    results['authenticated_reads'] = True
    rejected = client.post('/api/v1/auth/refresh', headers={'Origin': 'https://invalid.example'})
    assert rejected.status_code == 403
    results['csrf_rejected'] = 403
    refreshed = client.post('/api/v1/auth/refresh', headers={'Origin': base})
    assert refreshed.status_code == 200, refreshed.status_code
    assert 'refresh_token' not in refreshed.json()['data']
    headers = {'Authorization': 'Bearer ' + refreshed.json()['data']['access_token']}
    logged_out = client.post('/api/v1/auth/logout', headers=headers)
    assert logged_out.status_code in (200, 204), logged_out.status_code
    assert client.get('/api/v1/me', headers=headers).status_code == 401
    results['refresh_and_logout'] = True
    assert client.get('/docs').status_code == 404
    assert client.get('/openapi.json').status_code == 404
    results['private_docs'] = True
print(json.dumps(results))
