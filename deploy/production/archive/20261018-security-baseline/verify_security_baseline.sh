#!/usr/bin/env bash
# 生产安全基线验证：迁移服务器、重装、改配置之后跑一次，确认安全措施没有丢。
#
# 用法：
#   在目标服务器上（含本机配置与权限检查）：
#       sudo ./verify_security_baseline.sh
#   只做 HTTP 层检查（可在任意机器跑，只发 GET/HEAD，不修改任何数据）：
#       ./verify_security_baseline.sh --http-only --host https://course.zsitai.xyz
#
# 退出码 = 失败项数量。CI 或迁移脚本可直接据此判定是否放行。
set -uo pipefail

HOST="https://course.zsitai.xyz"
HTTP_ONLY=0
CONF_DIR="/etc/course-management"
UNIT="course-management.service"
NGINX_CONF=""

while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST="${2:-}"; shift 2 ;;
    --http-only) HTTP_ONLY=1; shift ;;
    --conf-dir) CONF_DIR="${2:-}"; shift 2 ;;
    --nginx-conf) NGINX_CONF="${2:-}"; shift 2 ;;
    *) echo "未知参数: $1"; exit 64 ;;
  esac
done

HOSTNAME_ONLY=$(echo "$HOST" | sed -E 's#https?://([^/:]+).*#\1#')
PASS=0
FAIL=0

ok()   { PASS=$((PASS+1)); printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  \033[31mFAIL\033[0m  %s\n' "$1"; [ -n "${2:-}" ] && printf '        → %s\n' "$2"; }
head_of() { curl -sS -o /dev/null -D - --max-time 10 "$1" 2>/dev/null | tr -d '\r'; }

banner() { printf '\n\033[1m%s\033[0m\n' "$1"; }

# ---------------------------------------------------------------- HTTP 层
banner "1. 安全响应头"
HEADERS=$(head_of "$HOST/")
for h in strict-transport-security x-frame-options x-content-type-options \
         referrer-policy permissions-policy cross-origin-opener-policy \
         cross-origin-resource-policy; do
  if echo "$HEADERS" | grep -qi "^$h:"; then ok "$h"; else bad "$h 缺失" "检查 /etc/course-management/security-headers.conf 是否被 server 块 include"; fi
done
if echo "$HEADERS" | grep -qi "^content-security-policy:"; then
  ok "content-security-policy"
else
  bad "content-security-policy 缺失" "检查 location / 与 location = /index.html 的 CSP add_header"
fi

banner "2. 版本号隐藏"
for scheme in http https; do
  srv=$(curl -sS -o /dev/null -D - --max-time 10 "$scheme://$HOSTNAME_ONLY/" 2>/dev/null | tr -d '\r' | grep -i '^server:')
  if echo "$srv" | grep -qE '[0-9]+\.[0-9]+'; then
    bad "$scheme 端口泄漏版本：$srv" "server_tokens off 必须写在 nginx http 级，不能只写在 443 server 块"
  else
    ok "$scheme 端口无版本号"
  fi
done

banner "3. 接口定义与敏感路径"
for p in /openapi.json /docs /redoc; do
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$HOST$p")
  [ "$code" = "404" ] && ok "$p → 404" || bad "$p → $code（应 404）" "检查应用 openapi_url/docs_url 与 nginx 精确匹配"
done
for p in /.env /.git/config /backup.zip; do
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$HOST$p")
  [ "$code" = "404" ] && ok "$p → 404" || bad "$p → $code（应 404）" "SPA 兜底把未知路径回成 200；检查敏感前缀 location"
done

banner "4. 健康检查信息收敛"
body=$(curl -sS --max-time 10 "$HOST/health/live")
if echo "$body" | grep -q '"env"'; then
  bad "health/live 回显 env" "APP_ENV 非 prod 或 health 路由未按 is_prod 分级"
else
  ok "health/live 不回显 env"
fi
if curl -sS --max-time 10 "$HOST/health/ready" | grep -q '"database"'; then
  bad "health/ready 回显 database" "同上"
else
  ok "health/ready 不回显 database"
fi

banner "5. 传输层"
code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "http://$HOSTNAME_ONLY/")
[ "$code" = "301" ] && ok "HTTP → HTTPS 301" || bad "HTTP 返回 $code（应 301）"

if command -v openssl >/dev/null 2>&1; then
  # 注意：握手失败时 openssl 返回非零，而本脚本开了 pipefail，
  # 直接 `openssl | grep` 会因左端退出码被判假。先落变量再匹配。
  tls1_out=$(openssl s_client -connect "$HOSTNAME_ONLY:443" -servername "$HOSTNAME_ONLY" -tls1 </dev/null 2>&1 || true)
  if echo "$tls1_out" | grep -q "Cipher is (NONE)"; then
    ok "TLS 1.0 已拒绝"
  else
    bad "TLS 1.0 可能仍可用" "检查 ssl_protocols 只保留 TLSv1.2 TLSv1.3"
  fi

  cert_out=$(openssl s_client -connect "$HOSTNAME_ONLY:443" -servername "$HOSTNAME_ONLY" </dev/null 2>/dev/null || true)
  if echo "$cert_out" | openssl x509 -noout -checkend $((30 * 86400)) >/dev/null 2>&1; then
    ok "证书剩余 > 30 天"
  else
    bad "证书 30 天内到期或不可读" "确认 acme/certbot 定时任务"
  fi
else
  echo "  SKIP  openssl 不可用，跳过 TLS 检查"
fi

# ---------------------------------------------------------------- 本机层
if [ "$HTTP_ONLY" -eq 0 ]; then
  banner "6. nginx 配置完整性"
  main_conf="${NGINX_CONF:-$CONF_DIR/course-management.nginx.conf}"
  frag="$CONF_DIR/security-headers.conf"
  if [ -f "$frag" ]; then ok "security-headers.conf 已安装"; else bad "security-headers.conf 缺失" "从仓库 deploy/production/ 复制，否则 include 直接报错"; fi
  if [ -f "$main_conf" ]; then
    ok "主配置存在"
    # server_tokens 必须在第一个 server 块之前，否则只对 443 生效
    # 只匹配指令行，不能匹配注释——注释里也会出现 "server_tokens" 这个词，
    # 曾导致"把指令挪回 443 块"后仍被判为 PASS。
    first_server=$(grep -nE '^[[:space:]]*server[[:space:]]*\{' "$main_conf" | head -1 | cut -d: -f1)
    st_line=$(grep -nE '^[[:space:]]*server_tokens[[:space:]]+off;' "$main_conf" | head -1 | cut -d: -f1)
    if [ -n "$st_line" ] && [ -n "$first_server" ] && [ "$st_line" -lt "$first_server" ]; then
      ok "server_tokens 位于 http 级"
    else
      bad "server_tokens 不在 http 级（或缺失）" "写在 443 块内不会作用于 80 端口"
    fi
    grep -qE '^[[:space:]]*include[[:space:]]+.*security-headers\.conf' "$main_conf" \
      && ok "主配置 include 安全头片段" || bad "主配置未 include 安全头片段"
    grep -qE '^[[:space:]]*limit_req_zone[[:space:]].*cm_api_rate' "$main_conf" \
      && ok "API 限流 zone 已配置" || bad "缺少 cm_api_rate 限流" "匿名扫描可打满单 worker"
  else
    bad "主配置不存在：$main_conf"
  fi

  banner "7. 服务加固"
  unit_path=$(systemctl show -p FragmentPath "$UNIT" 2>/dev/null | cut -d= -f2)
  if [ -n "$unit_path" ] && [ -f "$unit_path" ]; then
    for kv in "User=" "NoNewPrivileges=true" "PrivateTmp=true" "ProtectSystem=" "MemoryMax="; do
      grep -q "$kv" "$unit_path" && ok "systemd 含 $kv" || bad "systemd 缺少 $kv" "从仓库 deploy/production/$UNIT 取，勿手工改歪"
    done
    if grep -q '^User=root' "$unit_path"; then bad "服务以 root 运行" "改回 User=course-management"; fi
  else
    echo "  SKIP  未找到 $UNIT 单元文件"
  fi

  banner "8. 运行期配置基线"
  env_file="$CONF_DIR/backend.env"
  if [ -f "$env_file" ]; then
    perm=$(stat -c '%a %U' "$env_file" 2>/dev/null)
    [ "$perm" = "600 root" ] && ok "backend.env 权限 600 root" || bad "backend.env 权限异常：$perm" "chmod 600; chown root:root"
    grep -q '^APP_ENV=prod' "$env_file" && ok "APP_ENV=prod" || bad "APP_ENV 不是 prod" "非 prod 会开放 /docs 且 health 回显环境"
    grep -q '^DEBUG=false' "$env_file" && ok "DEBUG=false" || bad "DEBUG 不为 false"
    grep -q '^COOKIE_SECURE=true' "$env_file" && ok "COOKIE_SECURE=true" || bad "COOKIE_SECURE 不为 true" "HTTPS 下 refresh Cookie 必须 Secure"
    if grep -q '^SECRET_KEY=change_me_to_a_long_random_string' "$env_file"; then
      bad "SECRET_KEY 仍是默认值" "必须换成随机值；更换会使全部现有 token 失效"
    else
      ok "SECRET_KEY 非默认值"
    fi
    if grep -E '^CORS_ORIGINS=.+' "$env_file" >/dev/null; then
      echo "  INFO  CORS_ORIGINS 已开启：$(grep '^CORS_ORIGINS=' "$env_file" | cut -d= -f2)，确认是精确域名而非 *"
    else
      ok "CORS 未开放（同源部署）"
    fi
  else
    echo "  SKIP  未找到 $env_file"
  fi

  banner "9. 数据目录权限"
  for d in /var/lib/course-management/files "$CONF_DIR"; do
    if [ -d "$d" ]; then
      owner=$(stat -c '%U:%a' "$d")
      case "$owner" in
        root:700|course-management:*) ok "$d 权限 $owner" ;;
        *) bad "$d 权限 $owner" "配置目录应 root:700，文件目录应属服务账号且不可全局可读" ;;
      esac
    else
      echo "  SKIP  $d 不存在"
    fi
  done
fi

printf '\n\033[1m汇总：%s passed / %s failed\033[0m\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] && echo "基线完整。" || echo "存在缺失项，按上面提示修复后重跑。"
exit "$FAIL"
