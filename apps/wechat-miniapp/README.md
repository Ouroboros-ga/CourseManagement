# 查课管理系统微信小程序

本目录从用户提供的 [Mo-Qiong/wxsign](https://github.com/Mo-Qiong/wxsign) 引入原生 WXML/JS/WXSS 页面，并接入本仓库 FastAPI `/api/v1` 契约。提交号、许可声明和复核边界见 [上游来源记录](./UPSTREAM_PROVENANCE.md)；原始说明见 `UPSTREAM_README.md`。

## 本地启动

1. 按 [后端启动说明](../../backend/README.md) 启动 MySQL、运行 Alembic 迁移及角色权限种子，再启动 FastAPI。小程序默认请求开发者自己电脑上的 `http://127.0.0.1:18080`；在仓库的 `backend/` 目录执行 `uv run uvicorn app.main:app --host 127.0.0.1 --port 18080`。如果使用别的端口，修改 `miniprogram/utils/env.js` 中的本地地址。此地址指向**运行微信开发者工具的电脑**，不会指向原开发者的电脑。
2. 在本目录执行 `Copy-Item project.private.config.example.json project.private.config.json`（PowerShell），仅供开发者工具本地模拟器关闭请求域名校验；私有文件被 Git 忽略。然后进入 `miniprogram/` 执行 `npm ci`、`npm test`，用微信开发者工具导入本目录并执行“工具 → 构建 npm”。提交的 `project.config.json` 仍保持 `urlCheck=true`。
3. 核对 `project.config.json` 的 AppID 是否是开发者有权限使用的小程序。真实登录需在**后端私有配置**中提供相同的 `WECHAT_APPID`、对应 `WECHAT_SECRET` 并设置 `WECHAT_LOGIN_ENABLED=true`，随后重启 API；不要把 AppSecret 写入小程序或 Git。没有这些配置时，登录接口按设计返回 403，页面流程只能用测试中的微信 API 替身验证。
4. 后台先导入学生并发放一次性绑定码。小程序首次登录后用“学号＋绑定码”绑定；本人受派任务可读取，但只有具备本学期有效志愿者资格的当前受派人能提交。

可运行 `cd miniprogram && npm test` 验证 API 封装、令牌轮换、上传和页面流程。测试使用模拟 `wx`；不能代替真实 `wx.login → code2session`、域名校验、微信开发者工具编译及真机联调。

原开发电脑（2026-09-27）另有 Git 忽略的独立 MySQL 数据目录和管理员凭证；它们**不随仓库推送**。收到仓库的开发者应按上述步骤建立自己的后端环境。

## 已接通的范围

- 微信登录、本人信息、首次学生绑定、后端登出；refresh 通过 JSON 传递，401 串行刷新后至多重试一次。
- 本人查课任务分页、详情、任务名单、异常学生选择、照片上传以及结果提交。所有学生与文件关联使用后端 ID，避免用学号或本地文件路径代替。
- 逾期任务仍可补交；截止时的“逾期未执行”考核事实由后端保留。
- 本人考勤分页查询、本人异议提交；期望认定必填，理由选填，证明照片作为 `OBJECTION_PROOF` 上传，提交只传文件 ID。重复未完成异议与超出窗口由后端拒绝。
- 异议审核入口依据 `/me` 返回的有效权限显示：学生工作负责人仅在被授予可选初核权限后可初核；终审需 `objection.final_review`，可选择最终认定类型，改判还需 `attendance.correct`。终审读取当前考勤版本，版本冲突后刷新列表；证明材料由后端签发短时访问链接后预览，未结案异议的材料到期后仍可读至结案。

本次合入了上游新增的考勤、异议和审核页面，但排班管理仍引导至 Web 后台。真机和发布环境必须使用可访问的 HTTPS API，并在微信后台配置 request、uploadFile 合法域名；本地关闭域名校验的私有设置不能替代这一要求。真实微信链路还需要私有 AppSecret、匹配的 AppID 与开发者工具/设备验证。
