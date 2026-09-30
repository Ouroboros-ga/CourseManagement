# 管理端开发

```powershell
cd "D:/My project/CourseManagement/apps/admin-web"
npm.cmd run dev
```

打开 `http://127.0.0.1:3000`。Vite 将 `/api` 请求代理到正式云后端 `https://course.zsitai.xyz`，包括上传和下载请求。使用云端账号登录；页面上的新增、修改、删除会实际作用于正式数据库。

开发代理验证云端 TLS 证书，并将 localhost 的合法 Origin 转为云端同源；非法 Origin 与 Sec-Fetch-Site 继续交由后端拒绝。本地 HTTP Cookie 仅移除 Secure，保留 HttpOnly、SameSite 和 auth 路径。上述配置仅存在于开发服务器，不改变正式后端配置或静态构建中的 Cookie 安全策略。

3000 端口被占用时启动直接报错，避免端口变化导致来源校验不一致。开发服务器仅监听 IPv4 回环地址，不开放局域网访问。正式部署应由 Nginx 同源代理 `/api`，`vite preview` 不使用此开发代理。
