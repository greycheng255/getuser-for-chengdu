# dev 外部环境预检记录

预检日期：2026-08-05。所有数据库动作均为只读，没有读取或导出认证字段值。

## dev PostgreSQL

- 使用当前 `.env` 成功执行 `SELECT current_database(), current_user, version()`。
- 数据库与账号均和本地连接配置匹配，服务端为 PostgreSQL 18.3。
- 脱敏结构快照发现旧表 `publisher_accounts`、`bot_accounts`、`interaction_scripts`，尚无 `unified_accounts`。
- 账号迁移 dry-run 识别 3 个候选（发布账号 2、互动账号 1），0 冲突、0 失败，结果有效。
- 迁移前 validate 的覆盖率为 0，原因是目标表尚未创建，符合未执行 apply 的实际状态。
- dry-run 前后结构快照一致，证明预演没有创建目标表。

本轮同时修复迁移工具：`dry-run`、`validate`、`rollback-plan` 不再调用建表；明确执行 `apply` 时也只允许创建 `unified_accounts`，不会顺带创建其他业务表。

证据文件：

- `evidence/dev-data-profile.json`
- `evidence/migration-dry-run.json`
- `evidence/migration-validate-preapply.json`
- `evidence/dev-data-profile-after-dry-run.json`

## Apollo

- Portal 登录及只读 API 正常。
- 实际坐标为 `getuser-for-chengdu / LOCAL / dev / application`。
- 原命名空间包含 33 项配置；已新增并发布 6 个安全默认功能开关，发布后共 39 项。
- 发布 ID 为 3，发布名称为 `feature-20260804-stage7-safe-defaults-20260805`，未废弃。
- Config Service 已确认为 `http://122.51.51.177:8071`，标准接口返回 39 项配置。
- 本地运行时加载状态为 `enabled=true`、`loaded=true`、`keys_loaded=39`，6 个业务开关值符合安全默认策略。
- 应用服务器访问 Config Service 返回 200，`.env` 已原子写入 10 个 Apollo 引导参数，并保留 `.env.before-apollo-20260805` 备份。
- 应用服务器当前代码提交尚未包含 `config/runtime_config.py`，且工作树存在大量既有改动，因此没有直接覆盖或重启远端代码。

证据文件：`evidence/apollo-portal-release.json`。

## 尚需外部条件

1. 将本阶段代码安全部署到应用服务器，重启后验证 `/api/config/apollo-status`。
2. 数据库负责人确认备份方案后，执行两次 apply、validate 和按批次 rollback 演练。
3. 提供抖音、小红书专用测试账号及图文/视频素材，执行四组各 10 次真实发布测试。
4. 业务验收人完成签字，历史 Git 凭据完成平台侧轮换。

上述条件完成前，统一账号读写、统一话术和两个视频发布开关继续保持关闭，旧账号 API 保持开启。
