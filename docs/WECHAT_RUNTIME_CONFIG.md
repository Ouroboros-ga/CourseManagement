# 微信登录运行配置

2026-10-01，按用户明确授权更新服务器 `120.26.32.241`：

- 后端 AppID：`wxe056d5829b7124d3`，与项目副本及独立 wxsign 仓库当前 project.config.json 一致。
- AppSecret 保存在服务器 root 专用 `/etc/course-management/backend.env`，权限 0600，不写入仓库或本文档。
- `WECHAT_LOGIN_ENABLED=true`。后端已重启，并从实际进程环境确认开关、AppID 和凭证长度正确加载。
- 更新前配置已备份为同目录 `backend.env.before-wechat-<UTC时间>`，权限受限。
- HTTPS 健康、Web 登录、Cookie/CSRF、刷新登出冒烟通过，管理端页面 200。

本轮没有取得真实 wx.login code，因此尚未验证 code2session 的凭证有效性、真实 OpenID 登录及首次绑定闭环。客户端仍须将请求环境切换至 `https://course.zsitai.xyz`，在微信后台配置对应请求/上传/下载合法域名，并执行真机联调。

## SSH 访问变更

用户指定的 ED25519 公钥已幂等追加到 root 的 authorized_keys，保留原有密钥。指纹：`SHA256:ImkmxCKzxJJDebE9tx8jU1R+vbRhNpzzsrmfyTC3fdQ`。authorized_keys 权限 0600，sshd 配置检查通过，公钥认证启用。旧密钥列表在 `/root/.ssh/authorized_keys.before-wechat-<UTC时间>`。

没有用户配套私钥，本轮未代替其设备执行新公钥登录测试。
