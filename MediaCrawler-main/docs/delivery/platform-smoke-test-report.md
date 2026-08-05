# 抖音/小红书真实平台测试记录

状态：待专用测试账号和公开测试素材准备后执行。

## 证据格式

每次执行写一行 JSON，禁止包含 Cookie、Token、手机号或真实客户数据：

```json
{"run_id":"dy-image-001","platform":"douyin","scenario":"image","success":true,"error_code":"","account_alias":"dy-test-01","started_at":"2026-08-05T10:00:00+08:00","finished_at":"2026-08-05T10:01:00+08:00","evidence_ref":"evidence/dy-image-001.png"}
```

失败记录必须填写 9 类标准 `error_code` 之一，并保留脱敏页面截图或日志引用。

## 执行要求

| 平台 | 图文最低次数 | 视频最低次数 | 每组最低成功率 |
|---|---:|---:|---:|
| 抖音 | 10 | 10 | 80% |
| 小红书 | 10 | 10 | 80% |

使用以下命令生成报告：

```powershell
python tools/platform_smoke_report.py evidence/platform-smoke.jsonl --output evidence/platform-smoke-report.json
```

只有输出中的 `valid=true` 才通过该门禁。图文与视频分别计算，不合并小样本。

## 结果

| 平台/场景 | 次数 | 成功 | 失败 | 成功率 | 结论 |
|---|---:|---:|---:|---:|---|
| 抖音图文 | 待执行 |  |  |  | 待验证 |
| 抖音视频 | 待执行 |  |  |  | 待验证 |
| 小红书图文 | 待执行 |  |  |  | 待验证 |
| 小红书视频 | 待执行 |  |  |  | 待验证 |
