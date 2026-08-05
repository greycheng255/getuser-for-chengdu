# Apollo 配置接入与验证手册

## 地址职责

- Apollo Portal：供人员登录、编辑和发布配置，不能作为应用运行时读取地址。
- Meta Server：按 AppId 发现当前环境的 Config Service。
- Config Service：应用读取已发布配置的接口。

应用必须配置 `APOLLO_META_SERVER_URL` 或 `APOLLO_CONFIG_SERVER_URL`。经 Portal 只读核对，本项目的应用为 `getuser-for-chengdu`，`LOCAL/dev/application` 分别表示环境、集群和命名空间。因此客户端参数为 `APOLLO_APP_ID=getuser-for-chengdu`、`APOLLO_ENV=LOCAL`、`APOLLO_CLUSTER=dev`、`APOLLO_NAMESPACE=application`。

## 启动配置

```dotenv
APOLLO_ENABLED=true
APOLLO_META_SERVER_URL=
APOLLO_CONFIG_SERVER_URL=http://122.51.51.177:8071
APOLLO_APP_ID=getuser-for-chengdu
APOLLO_ENV=LOCAL
APOLLO_CLUSTER=dev
APOLLO_NAMESPACE=application
APOLLO_TIMEOUT_SECONDS=3
APOLLO_OVERRIDE_ENV=true
APOLLO_REQUIRED=true
```

只配置 Config Service 时可留空 `APOLLO_META_SERVER_URL`。开发机允许 `APOLLO_REQUIRED=false` 降级；dev/staging/production 推荐为 `true`，避免错误配置被静默使用。

## 新能力初始值

```dotenv
UNIFIED_ACCOUNT_READ_ENABLED=false
UNIFIED_ACCOUNT_WRITE_ENABLED=false
LEGACY_ACCOUNT_API_ENABLED=true
UNIFIED_SCRIPT_LIBRARY_ENABLED=false
DOUYIN_VIDEO_PUBLISH_ENABLED=false
XIAOHONGSHU_VIDEO_PUBLISH_ENABLED=false
```

## 验证

1. 在 Portal 发布 `LOCAL/dev/application`。
2. 重启 API 进程；当前实现为启动加载，不依赖 Portal 登录账号。
3. 使用已登录管理员 Token 请求 `GET /api/config/apollo-status`。
4. 确认 `enabled=true`、`loaded=true`、`keys_loaded>0`、`last_error` 为空。
5. 将脱敏响应保存为 `apollo-status.json`，供 `tools/verify_acceptance_evidence.py` 验收。

当前 Portal 公网地址仅用于管理配置，不能填入 Meta/Config Service 地址。Config Service 已确认为 `http://122.51.51.177:8071`：本地和应用服务器请求标准配置接口均返回 200，本地加载器状态为 `enabled=true`、`loaded=true`、`keys_loaded=39`。应用服务器 `.env` 已写入引导参数，但服务器当前代码版本尚无 `config/runtime_config.py`，需先部署本阶段代码再重启并验证状态接口。

状态接口不会返回服务地址、配置键名或配置值。

## 回滚

1. 先关闭对应业务开关并发布 Apollo 配置。
2. 重启应用，确认状态接口加载成功。
3. 若 Apollo 本身故障，设置 `APOLLO_ENABLED=false` 并使用受控的本地环境变量启动；所有新能力在缺少配置时默认关闭。
