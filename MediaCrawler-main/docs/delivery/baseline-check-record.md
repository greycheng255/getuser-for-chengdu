# 基线与本地回归记录

| 项目 | 记录 |
|---|---|
| 分支 | `feature-20260804-project-integration` |
| 开发基线 | `e091ba2384452bb315963d2e283167f2a3e7f998` |
| 初始后端门禁 | `242 passed, 1 skipped` |
| 阶段 3 后端 | `247 passed, 1 skipped` |
| 阶段 5 后端 | `250 passed, 1 skipped` |
| 阶段 6 首轮后端 | `267 passed, 1 skipped` |
| 前端基线债务 | 全量 ESLint 存在历史错误；本轮按增量不增加错误控制 |
| 前端构建 | TypeScript 和 Vite 生产构建通过 |

阶段 0 未取得 dev PostgreSQL 备份、真实平台账号和素材，因此这些项目不能用本地模拟证据替代，已保留在业务验收清单中。

开发前工作树已存在虚拟环境链接删除和上级 `nodejs/bin` 修改，本轮未恢复、删除或声称拥有这些改动。
