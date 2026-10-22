"""隔离Nginx及合成PNG验证；不读业务库、不用生产签名密钥。

Linux服务器：python verify_file_download_edge.py --config-dir <候选配置目录>
使用当前后端的SignedDownload校验算法，临时密钥只在进程内。
"""

from __future__ import annotations

import argparse
import base64
import json
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", type=Path, required=True)
    parser.add_argument(
        "--backend-root",
        type=Path,
        default=Path("/opt/course-management/current/backend"),
    )
    args = parser.parse_args()
    sys.path.insert(0, str(args.backend_root))
    from app.modules.file.storage import SignedDownload

    signer = SignedDownload(secrets.token_hex(32))
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII="
    )

    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # 不记录带签名的URL。

        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(url.query)
            download = url.path.startswith("/api/v1/files/") and url.path.endswith(
                "/download"
            )
            valid = download and signer.verify_download(
                "synthetic.png",
                int(query.get("expires", ["0"])[0]),
                query.get("sig", [""])[0],
            )
            self.send_response(200 if valid else 403 if download else 401)
            self.send_header(
                "Content-Type", "image/png" if valid else "application/json"
            )
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            if download:
                # 模拟上游已启用CORS，断言网关隐藏后只返回一份正确策略。
                self.send_header(
                    "Access-Control-Allow-Origin", "https://upstream.invalid"
                )
                self.send_header("Access-Control-Allow-Credentials", "true")
                self.send_header("Access-Control-Allow-Methods", "PUT")
                self.send_header("Cache-Control", "private, no-store")
            self.end_headers()
            self.wfile.write(png if valid else b"{}")

    fixture = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    thread.start()
    with tempfile.TemporaryDirectory(prefix="cm-download-edge-") as directory:
        stage = Path(directory)
        (stage / "logs").mkdir()
        # 宝塔/OpenResty的resty.core通过主配置的Lua搜索路径加载，隔离实例需复用路径。
        lua = (
            'lua_package_path "/www/server/nginx/lib/lua/?.lua;;";'
            if Path("/www/server/nginx/lib/lua/resty/core.lua").is_file()
            else ""
        )
        fragment = (args.config_dir / "file-download.conf").read_text()
        fragment = fragment.replace(
            "http://127.0.0.1:8011", f"http://127.0.0.1:{fixture.server_port}"
        )
        fragment = fragment.replace(
            "/etc/course-management/", str(args.config_dir.resolve()) + "/"
        )
        (stage / "download.conf").write_text(fragment)
        config = f"""pid {stage}/nginx.pid;
error_log {stage}/error.log;
events {{}}
http {{
    {lua}
    access_log off;
    limit_req_zone $binary_remote_addr zone=cm_api_rate:1m rate=30r/s;
    server {{
        listen 127.0.0.1:18441;
        include {args.config_dir.resolve()}/security-headers.conf;
        include {stage}/download.conf;
        location /api/ {{
            proxy_pass http://127.0.0.1:{fixture.server_port};
            include {args.config_dir.resolve()}/course-management-proxy.conf;
        }}
    }}
}}
"""
        path = stage / "nginx.conf"
        path.write_text(config)
        command = ["nginx", "-p", str(stage), "-c", str(path)]
        subprocess.run([*command, "-t"], check=True, capture_output=True)
        started = subprocess.run(command, capture_output=True, text=True)
        if started.returncode:
            raise RuntimeError(started.stderr)
        results = {}
        try:

            def request(url, method="GET", headers=None):
                req = urllib.request.Request(
                    "http://127.0.0.1:18441" + url, method=method, headers=headers or {}
                )
                try:
                    return urllib.request.urlopen(req, timeout=5)
                except urllib.error.HTTPError as error:
                    return error

            url = signer.presign_get(1, "synthetic.png", 60)
            cases = [
                ("valid-image", url, 200, png),
                (
                    "invalid-signature",
                    "/api/v1/files/1/download?expires=9999999999&sig=invalid",
                    403,
                    b"{}",
                ),
                (
                    "expired-signature",
                    f"/api/v1/files/1/download?expires=1&sig={signer._sign('synthetic.png', 1)}",
                    403,
                    b"{}",
                ),
            ]
            for label, target, status, body in cases:
                with request(
                    target, headers={"Origin": "https://servicewechat.com"}
                ) as response:
                    assert response.status == status, (label, response.status)
                    assert response.read() == body, label
                    for key, expected in {
                        "Cross-Origin-Resource-Policy": "cross-origin",
                        "Access-Control-Allow-Origin": "*",
                        "Access-Control-Allow-Methods": "GET, OPTIONS",
                        "Cache-Control": "private, no-store",
                        "X-Content-Type-Options": "nosniff",
                    }.items():
                        assert response.headers.get_all(key) == [expected], (label, key)
                    assert not response.headers.get_all(
                        "Access-Control-Allow-Credentials"
                    )
                    results[label] = status
            with request(
                "/api/v1/files/1/download",
                "OPTIONS",
                {
                    "Origin": "https://servicewechat.com",
                    "Access-Control-Request-Method": "GET",
                },
            ) as response:
                assert response.status == 204 and response.read() == b""
                assert response.headers.get_all("Access-Control-Allow-Origin") == ["*"]
                results["preflight"] = 204
            for target in ["/api/v1/me", "/api/v1/files/1/access"]:
                with request(target) as response:
                    assert response.status == 401
                    assert response.headers.get_all("Cross-Origin-Resource-Policy") == [
                        "same-origin"
                    ]
                    assert not response.headers.get_all("Access-Control-Allow-Origin")
            results["other-api-baseline"] = "unchanged"
            print(json.dumps(results))
        finally:
            subprocess.run([*command, "-s", "quit"], check=True, capture_output=True)
            for _ in range(30):
                if not (stage / "nginx.pid").exists():
                    break
                time.sleep(0.1)
            fixture.shutdown()
            fixture.server_close()


if __name__ == "__main__":
    main()
