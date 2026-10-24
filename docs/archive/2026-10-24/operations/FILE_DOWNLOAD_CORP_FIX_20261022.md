> 归档说明（2026-10-24）：原路径 `docs/development/FILE_DOWNLOAD_CORP_FIX_20261022.md`。本文保留当时的修复、验证与发布记录；历史版本和待验收项按当时语义理解，当前进度见[实施状态](../../../development/IMPLEMENTATION_STATUS.md)。

# 微信图片签名下载跨源策略修复

## 审查与修复范围

原报告主因成立：线上 `/api/v1/files/{id}/download` 默认返回CORP same-origin，微信来源的预检返回405。签名下载不依赖登录Cookie，适合独立的无凭据跨源策略，但原建议只声明允许OPTIONS而未处理，不能直接采用。问题来自Nginx安全基线，后端签名算法与权限无需修改。

仅给数字文件ID下载路由增加独立location片段；CORP改为cross-origin，ACAO为*，允许GET/OPTIONS并实际处理204预检。不宣称HEAD支持，不允许跨源登录凭据；隐藏上游同名CORS和缓存头，网关只输出一份。保留完整其余安全头及API限流，成功/错误响应均private/no-store。获取签名的 `/access`、上传与普通API保持原策略，GET继续验证HMAC、时效和文件状态。

## 验证

3项配置回归先失败后通过。服务器回环隔离Nginx和临时合成PNG上游通过：有效签名图片200且内容一致，无效与过期签名403，微信来源OPTIONS204，普通API及签名申请路由同源策略不变。模拟上游额外CORS头后，网关仍只输出一份ACAO/CORP，没有Allow-Credentials。使用应用SignedDownload算法、随机临时密钥，不读业务库和真实照片。

隔离实例初次启动因宝塔OpenResty的Lua路径缺失失败，补齐同一服务器已存在的模块路径后通过；未将失败记录算通过。Python验证脚本和测试Ruff通过。本次不改后端、Web、小程序包或数据库。

## 发布与回退

已提交推送并完成网关部署：功能提交 `a10238f`，整合远端后的配置来源 `930aeefa0121a9afd069b721c55c504c139fcf8e`，网关发布记录名 `20261022-file-download-corp-930aeef`。北京时间2026-10-22 10:50重载完成。站点仍使用原内容，仅插入下载片段include，未覆盖域名、TLS、端口或其他配置。

- 公网已确认：无效探测文件GET404仍带唯一CORP cross-origin、ACAO *、GET/OPTIONS和private/no-store；微信来源预检204。首页/健康200、me及文件access匿名401，CORP仍same-origin且没有CORS放开。有效及过期HMAC的合成图片测试在隔离实例完成；未用真实照片执行公网200下载。
- 后端保持 `20261021-wechat-rebind-6f4299bd78`，Web保持 `20261021-staff-binding-export-145dfe8fc1`，运行环境配置摘要保持 `e906579ee8e72a4d3f98007c11f87d3530a98e5c4e7beb37fde5efd50bf53163`。未执行数据库写入、迁移或后端重启。
- 原站点SHA-256：`20a8839d07907182a5a4ad37970d295954c95e7545787132b831b91c2056746c`；更新后：`f1c438205fabe283df4ac50e4de97f4b8f8060e653df0f29c283ef74bd49b50b`。下载片段SHA-256：`8d24d261927f69b2d96a16e90cc827e393e7b8f75065be8b69cbfd2045efe804`。
- 备份与验证报告：`/var/backups/course-management/20261022-file-download-corp-930aeef/`，含原站点、片段、before/report.json和rollback.py。需回退时执行 `python3 /var/backups/course-management/20261022-file-download-corp-930aeef/rollback.py --apply`，校验当前摘要后恢复原站点、删除本次新片段、测试并reload。命令仅记录，本轮未执行回退。

远端图片上传格式修复 `7f78f31` 已在Git整合保留，但本次未重发后端，不将其记为本轮上线能力。微信开发者工具及真机复测尚待进行。
