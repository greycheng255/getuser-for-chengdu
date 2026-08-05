# 统一账号 API

路由前缀：`/api/accounts`。所有接口使用当前登录用户作为数据权限边界。

| 方法 | 路径 | 功能 |
|---|---|---|
| GET | `/stats` | 账号状态和角色统计 |
| GET | `/` | 分页并按平台、角色、状态等筛选 |
| POST | `/` | 新增账号 |
| POST | `/batch` | 批量新增，返回逐项结果 |
| GET | `/{account_id}` | 脱敏详情 |
| PUT | `/{account_id}` | 更新角色、能力、调度和认证信息 |
| DELETE | `/{account_id}` | 逻辑停用 |
| POST | `/{account_id}/reset-cooldown` | 解除冷却 |
| POST | `/{account_id}/validate` | 校验账号配置和可用状态 |

平台输入支持 `dy→douyin`、`xhs→xiaohongshu` 等别名；非法平台返回明确参数错误。认证字段只允许写入或替换，响应和日志不得包含原文。

旧发布账号和机器人账号 API 在兼容期开启，但统一写入开关启用后只委托该服务，不允许双写旧表。
