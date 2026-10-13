# OSS 接入与切换（2026-10-13）

本次代码实现后端 OSS 适配和 Web 文件客户端，未执行生产配置、上传、删除或迁移。bucket/地域/Endpoint 由用户提供；RAM 策略和角色实际绑定、桶私有设置尚需云端验收。

## 配置

在 ECS 上执行 `uv sync --locked` 安装锁定的官方 `alibabacloud-oss-v2` 和 `alibabacloud-credentials`。在受保护服务端环境文件填写：

```dotenv
FILE_STORAGE_BACKEND=object
OSS_BUCKET=oss-pai-um7e66idcat8ihfw7v-cn-shanghai
OSS_REGION=cn-shanghai
OSS_ENDPOINT=https://oss-cn-shanghai.aliyuncs.com
OSS_ROLE_NAME=tmp.course
OSS_TIMEOUT_SECONDS=15
FILE_SIGNED_URL_TTL_SECONDS=300
```

必须保留原 `SECRET_KEY`；轮换会让已有应用下载签名与其他令牌失效。ECS RAM 角色信任 ECS，权限仅限本桶对象 GetObject、PutObject、DeleteObject。SDK 从实例元数据取得并刷新临时凭据；容器部署需确认元数据可达。不要在 Web/小程序中保存长期或临时云端凭据。

默认使用外网 HTTPS endpoint。ECS 所在地域未确认；只有上海 ECS 经连通性检查后，才用 `https://oss-cn-shanghai-internal.aliyuncs.com`。该 endpoint 仅供后端使用。桶保持私有，不启用公共读、公共写，不需要给浏览器配置 OSS CORS。

## 行为与容量边界

上传经过后端图片内容、格式、大小、像素校验，OSS 写成功后才创建 READY 文件与审计事实。OSS CRC 校验采用 SDK 默认配置；上游不可用返回脱敏 503 `UPSTREAM_UNAVAILABLE`，不自动退回本地。DB 提交失败仍可能形成无引用随机对象，与原存储协议一致；不要盲目全桶删除，应以数据库引用及备份清单核对孤儿对象。

`GET /files/{id}/access` 仍经过业务授权，返回应用签名下载相对 URL，默认 300 秒。后端验签后读取 OSS，返回 private/no-store、nosniff，支持中文文件名。不依赖 STS 令牌剩余寿命生成前端 URL。相对 URL 由 Web 同源代理/小程序 API origin 补全。

上传为同步路由，数据库与 SDK 操作在线程池运行。下载仍整文件读取入内存；10 MiB 默认上传限额及低频材料场景适用，OSS 不会自动减少后端下载带宽。报表等大文件及并发下载应压测后再决定流式代理或经授权的 OSS 直链方案，不承诺未经测量的容量。

周报版本产物复用同一个 StorageBackend，Excel/Word/JSON 保存读取也随配置切换。课表、绑定码与数据库不会存入 OSS。直接导出报表与版本归档保持现有业务差异。

## 旧文件迁移、上线与回滚

存储位置是全局配置，数据库未逐文件记录 local/object。**不能直接切 object 后假定旧文件可读。** 按以下顺序执行，实际生产操作需单独授权：

1. 核对目标 ECS、数据库、服务环境文件和原文件目录；备份数据库、文件目录、旧发布与配置。
2. 保持 local，暂停上传、版本报表生成及清理作业，避免复制过程中新增/删除。
3. 只读导出 `file_object` 中未 PURGED/PURGE_PENDING 的 id/object_key/sha256/size_bytes/content_type 清单。READY 与未完成异议保留的文件都必须包含；与本地实体逐项核对，不能只迁移照片或只按未到期筛选。
4. 按原 object_key 复制至指定私有桶，保持 content_type；逐项读回校验 SHA256、字节数与清单总数。遇到同键不同内容即停止，不覆盖未知对象。保留本地原件，不清空桶。
5. 在独立验收环境先切 object，执行以下真实云端验收；随后生产在维护窗口切换配置和版本，恢复上传/清理。
6. 回滚前暂停写入与清理。如果切换后已新增 OSS 文件，先把新增对象按原键和哈希补回本地（并同步 OSS 删除事实），再回 local；仅改回 local 会丢失新文件的可读性。保留数据库事实与审计，不回滚数据库来隐藏失败。

到期删除复用现有 `deploy/scripts/cleanup_expired_files.py` 状态机；删除失败保留 PURGE_PENDING 待重试。OSS 桶不要配置与业务清理冲突的生命周期自动删除（未结束的异议证明会暂停清理）。冗余存储不代替误删恢复；版本控制、备份和恢复演练按运维策略另行配置，不在本次代码中自动开启。

## 云端验收

- 测试账号上传图片，READY 行与审计落库、桶中对应对象存在；确认正确 content_type。
- 本人和业务授权审核者可申请访问链接；无权账号统一 404。伪造签名和过期链接 403。
- 下载内容与源图片一致；中文文件名可用，Web、小程序预览成功。
- 独立测试对象可重复删除；模拟角色权限不足返回脱敏 503，不产生 READY 行。
- 在独立验收数据上生成/下载版本报表，清理失败可重跑；不得对生产学生材料试删除。
- 核对 ECS 网络、元数据访问、日志无完整签名/凭据，观察线程池、连接池、下载带宽、响应延迟和费用。

## 本地验证

后端 `tests/unit/test_oss_storage.py` 覆盖真实 SDK 方法签名、配置、读写删除、应用签名和脱敏错误；`test_oss_file_routes.py` 用 SQLite + 模拟 SDK 边界验证 multipart → READY → 授权链接 → 下载与拒绝。

Web `node --test tests/files.test.mjs` 验证 multipart、过期刷新、并发合并和上下文失效；`npm.cmd run build` 验证 TypeScript 与产物。浏览器采用模拟接口验证实际材料面板。以上不证明真实云端 IAM、MySQL 锁语义或微信真机行为。
