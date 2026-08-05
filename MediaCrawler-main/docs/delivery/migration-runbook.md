# 统一账号迁移与回滚手册

所有命令均在 `MediaCrawler-main` 目录执行，报告不得包含 Cookie、Token 或密码原文。

## 迁移前

1. 停止自动发布和互动任务。
2. 记录 PostgreSQL 地址、数据库名、时区和当前代码提交。
3. 使用运维批准的方式备份 `publisher_accounts`、`bot_accounts`、`unified_accounts` 和 `interaction_scripts`。
4. 记录备份文件校验和及恢复验证结果，不把备份文件提交 Git。

## 第一次演练

```powershell
python tools/migrate_to_unified_accounts.py dry-run --batch-id dev-rehearsal-01
python tools/migrate_to_unified_accounts.py apply --batch-id dev-rehearsal-01
python tools/migrate_to_unified_accounts.py validate --batch-id dev-rehearsal-01
python tools/migrate_to_unified_accounts.py rollback-plan --batch-id dev-rehearsal-01
python tools/migrate_to_unified_accounts.py rollback --batch-id dev-rehearsal-01 --confirm-rollback
```

`rollback` 只删除该批次创建且具有旧表来源标记的统一账号，不修改旧表，也不会删除迁移前已存在的统一账号。

## 第二次演练与幂等验证

从备份恢复非生产数据库，再执行：

```powershell
python tools/migrate_to_unified_accounts.py apply --batch-id staging-rehearsal-02a
python tools/migrate_to_unified_accounts.py apply --batch-id staging-rehearsal-02b
python tools/migrate_to_unified_accounts.py validate --batch-id staging-rehearsal-02b
```

第二次 `apply` 的 `created_count` 必须为 0，`validate` 的 `coverage_rate` 必须为 1.0，失败和冲突项必须逐条复核。

## 切换顺序

1. `UNIFIED_ACCOUNT_WRITE_ENABLED=true`。
2. 确认旧 API 只委托统一服务，不写旧表。
3. `UNIFIED_ACCOUNT_READ_ENABLED=true`。
4. 保持 `LEGACY_ACCOUNT_API_ENABLED=true` 一个观察周期。

## 业务回滚

1. 停止自动任务。
2. 设置 `UNIFIED_ACCOUNT_READ_ENABLED=false`，恢复旧表读取。
3. 保持旧 API 开启。
4. 数据错误时优先恢复备份；按批次删除仅用于已确认没有迁移后业务更新的数据。
5. 不删除旧表或现场数据。
