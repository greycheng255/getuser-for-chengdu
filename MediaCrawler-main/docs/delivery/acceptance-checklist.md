# 业务验收清单

## 自动化证据

- [x] 后端全量测试无失败。
- [x] TypeScript 编译和生产构建通过。
- [x] 前端专项重试测试通过。
- [x] 本轮改动未增加 ESLint 错误。
- [x] 当前跟踪文件高置信凭据扫描为 0。

## 外部环境证据

- [x] dev PostgreSQL 只读连通性及脱敏结构快照完成。
- [x] dev 账号迁移 dry-run：3 个候选、0 冲突、0 失败，且目标表未被创建。
- [x] Apollo `LOCAL/dev/application` 已发布 6 个安全默认开关。
- [x] Config Service 标准接口与本地运行时加载验证通过，`keys_loaded=39`。
- [ ] dev/staging 迁移 `apply` 完整演练至少两次。
- [ ] 第二次迁移 `created_count=0`。
- [ ] 迁移校验 `coverage_rate=1.0`。
- [ ] 数据库或迁移批次回滚演练通过。
- [ ] 部署本阶段代码到应用服务器，重启并验证 Apollo 状态 `enabled=true`、`loaded=true`。
- [ ] 抖音图文、视频分别至少 10 次且成功率不低于 80%。
- [ ] 小红书图文、视频分别至少 10 次且成功率不低于 80%。
- [ ] 历史 Git 凭据已在平台侧轮换。
- [ ] 业务验收人确认。

## 签字文件格式

保存为不含敏感信息的 JSON：

```json
{"approved":true,"approver":"姓名或工号","approved_at":"2026-08-05T18:00:00+08:00","notes":"验收范围说明"}
```

收集全部 JSON 证据后执行：

```powershell
python tools/verify_acceptance_evidence.py `
  --migration-apply evidence/apply-01.json `
  --migration-apply evidence/apply-02.json `
  --migration-validate evidence/validate.json `
  --migration-rollback evidence/rollback.json `
  --platform-smoke evidence/platform-smoke-report.json `
  --apollo-status evidence/apollo-status.json `
  --signoff evidence/signoff.json `
  --output evidence/final-acceptance.json
```

只有 `final-acceptance.json` 中 `valid=true` 才能标记生产上线验收完成。
