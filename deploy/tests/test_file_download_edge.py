"""签名下载跨源例外必须被站点加载，并保留其他接口的安全基线。"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "production"


def test_site_loads_download_exception_before_generic_api():
    text = (ROOT / "course-management.nginx.conf").read_text(encoding="utf-8")
    assert text.index(
        "include /etc/course-management/file-download.conf;"
    ) < text.index("location /api/")


def test_download_exception_preserves_baseline_and_has_single_corp():
    text = (ROOT / "file-download.conf").read_text(encoding="utf-8")
    baseline = (ROOT / "security-headers.conf").read_text(encoding="utf-8")
    headers = re.findall(r"^add_header (.+);$", baseline, re.MULTILINE)
    for header in headers:
        if not header.startswith("Cross-Origin-Resource-Policy"):
            assert f"add_header {header};" in text
    assert text.count("add_header Cross-Origin-Resource-Policy") == 1
    assert 'Cross-Origin-Resource-Policy "cross-origin" always' in text
    assert 'Cross-Origin-Resource-Policy "same-origin" always' in baseline


def test_download_preflight_and_no_credentialed_cors():
    text = (ROOT / "file-download.conf").read_text(encoding="utf-8")
    assert "if ($request_method = OPTIONS)" in text and "return 204;" in text
    assert 'Access-Control-Allow-Methods "GET, OPTIONS"' in text
    assert "add_header Access-Control-Allow-Credentials" not in text
    assert "proxy_hide_header Access-Control-Allow-Origin;" in text
    assert "proxy_hide_header Access-Control-Allow-Credentials;" in text
    assert 'Cache-Control "private, no-store" always' in text
    assert re.search(r"location ~ \^/api/v1/files/\[0-9\]\+/download\$", text)
