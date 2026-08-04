# 视频拆解与发布中心职责分离重构

## Context（背景）

当前「视频拆解 Modal」的 Step2「发布互动」与「内容运营 → 发布中心」（`/publish-center`）功能重叠：两处都有「多平台发布」「单平台发布」UI，但走的 API 不同（`autoPipelineApi` 拆解流水线 vs `publishApi` 独立内容发布），用户心智混乱。同时 Step2 还混入了「生成发布文案」「发送评论」等本属于互动监控的功能，导致 BreakdownModal 职责过载。

**目标**：按单一职责切分三个模块：
- **BreakdownModal** = 拆解 + 生成视频 + 快速发布（轻量）
- **发布中心** = 所有发布的完整配置入口（重量）
- **互动监控** = 评论互动 + 文案生成（独立）

用户已确认方向：① 快速发布+跳转高级配置；② 「生成发布文案」和「发送评论」迁移到互动监控页面。

## 现状关键事实（探索结论）

- 路由：react-router-dom v6，`/x-workbench` 与 `/publish-center` 均为顶级路由，可用 `useNavigate({state})` 跨页传参（[App.tsx:71,103](file:///home/ubuntu/getuser-for-chengdu/MediaCrawler-main/webui-new/src/App.tsx)）
- `usePlatform()` 全局共享当前平台（[PlatformContext.tsx](file:///home/ubuntu/getuser-for-chengdu/MediaCrawler-main/webui-new/src/context/PlatformContext.tsx)）
- TrendingList 每条热点已有 4 个操作按钮：「一键拆解全流程」「视频拆解」「生成评论」「打开原帖」；其中「生成评论」当前也调用 `onOpenBreakdown` 打开 BreakdownModal（[TrendingList.tsx:56-62](file:///home/ubuntu/getuser-for-chengdu/MediaCrawler-main/webui-new/src/pages/xworkbench/TrendingList.tsx)）
- SentCommentsPanel（已发评论&回复）是纯列表/监控视图，无「发送评论」入口（[SentCommentsPanel.tsx](file:///home/ubuntu/getuser-for-chengdu/MediaCrawler-main/webui-new/src/pages/xworkbench/SentCommentsPanel.tsx)）
- PublishCenter 三 Tab：多平台/单平台/发布记录，Form 用 antd `form.setFieldsValue` 可预填（[PublishCenter.tsx](file:///home/ubuntu/getuser-for-chengdu/MediaCrawler-main/webui-new/src/pages/PublishCenter.tsx)）
- API 不可互换：`autoPipelineApi.run` 走拆解流水线（{platform, hotspot_item, skip_video...}），`publishApi.multiPublish` 走独立发布（{title, content, target_platforms, source_post_id...}）

## 实施步骤

### 步骤 1：新建 CommentComposeModal（互动监控页面）

**新文件**：`/webui-new/src/pages/xworkbench/CommentComposeModal.tsx`

把 BreakdownModal 里 `doSend`、`doGenComments`、`doGenXPostContent` 三个函数及对应 UI 迁过来，组织成两个 Section：

- **Section 1「发送评论」**：
  - 「重新生成」按钮 → `xWorkbenchApi.generateComments(post.post_id, 3)` → 候选评论列表（可点击选中）
  - TextArea 编辑评论（最多 280 字符）
  - 「真实发送」「保存为草稿」按钮 → `xWorkbenchApi.sendComment({post_id, post_url, content, real_send, platform})`
- **Section 2「生成发布文案」**：
  - 「生成文案」按钮 → `xWorkbenchApi.generateXPostContent(post.post_id, 3)` → 候选文案列表
  - 「复制到剪贴板」按钮 + 「跳转发布中心」按钮（携带文案+视频URL预填）

Props：`{ post: WorkbenchPost; open: boolean; onClose: () => void }`，与 BreakdownModal 一致；用 `usePlatform()` 取当前平台，复用 `PLATFORM_TO_PIPELINE` 映射（从 BreakdownModal 导出或新建共享常量文件）。

### 步骤 2：TrendingList「生成评论」按钮改触发 CommentComposeModal

**修改**：`/webui-new/src/pages/xworkbench/TrendingList.tsx`

- `PostCardProps` 新增 `onOpenComment: (post: WorkbenchPost) => void`
- 「生成评论」按钮 `onClick` 从 `onOpenBreakdown(post)` 改为 `onOpenComment(post)`
- `TrendingListProps` 同步新增 `onOpenComment` 并透传给 PostCard

**修改**：`/webui-new/src/pages/xworkbench/TrendingPanel.tsx`

- 新增 `commentModal` + `selectedPostForComment` 状态
- 新增 `openComment` 回调设置状态
- `<TrendingList onOpenComment={openComment} ... />`
- 渲染 `<CommentComposeModal post={selectedPostForComment} open={commentModal} onClose={...} />`

### 步骤 3：BreakdownModal Step2 简化

**修改**：`/webui-new/src/pages/xworkbench/BreakdownModal.tsx`

Step2 仅保留：
- **快速发布** Card：
  - 多平台 Select（默认选中当前拆解平台，已有逻辑保留）
  - 三个开关（skip_video/auto_monitor/trigger_interaction）
  - 「一键发布到所选平台」按钮（保留 `doMultiPlatformPublish`）
- **「去发布中心高级配置」按钮**：
  ```tsx
  const navigate = useNavigate();
  const goToPublishCenter = () => {
    onClose();
    navigate('/publish-center', {
      state: {
        from_breakdown: true,
        source_post_id: post.post_id,
        video_url: videoState?.result_url || customVideoUrl || uploadedVideoInfo?.file_url || '',
        content: post.content,
        platform: PLATFORM_TO_PIPELINE[platform] || platform,
        title: `@${post.username} 热点拆解`,
      },
    });
  };
  ```

**删除**（迁移到 CommentComposeModal）：
- 「生成发布文案」Card（`doGenXPostContent` + xPostContents 状态 + JSX）
- 「发送评论」Divider + TextArea + 真实发送/草稿按钮（`doSend` + editComment 状态 + JSX）
- X 平台单平台发布的复杂表单（视频上传/URL/生成视频三选一、`doPublishToX`、`handleVideoUpload`、`uploadedVideoInfo` 等）— 这些高级配置在发布中心做
- 相关未使用状态：`xPostContents`、`selectedXPostContent`、`genXPostContentLoading`、`publishingToX`、`customVideoUrl`、`uploadingVideo`、`uploadedVideoInfo`、`editComment`、`sending`、`generating`

**保留**：`publishMode` Radio 改为只读「多平台快速发布」模式（或直接删除 Radio，Step2 默认就是多平台快速发布 + 跳转按钮）。

### 步骤 4：PublishCenter 接收预填数据

**修改**：`/webui-new/src/pages/PublishCenter.tsx`

- 顶部 `const location = useLocation(); const prefilled = location.state as PrefilledData | null;`
- 顶部展示 Alert 横幅（当 `prefilled?.from_breakdown`）：「从拆解内容预填：@username 的热点拆解视频」+ 「清除预填」按钮
- 把 `prefilled` 透传给 MultiPublishPanel 和 SinglePublishPanel
- MultiPublishPanel/SinglePublishPanel 内 `useEffect` 监听 prefilled，调用 `form.setFieldsValue({
    title: prefilled.title,
    content: prefilled.content,
    video_path: prefilled.video_url,
    target_platforms: prefilled.platform ? [prefilled.platform] : undefined,
  })`
- MultiPublishPanel 的 `handlePublish` 在有 `prefilled.source_post_id` 时把它传入 `payload.source_post_id`（API 已支持此字段，见 [prdGap.ts:490](file:///home/ubuntu/getuser-for-chengdu/MediaCrawler-main/webui-new/src/api/prdGap.ts)）

## 关键文件清单

| 操作 | 文件 |
|---|---|
| 新建 | `/webui-new/src/pages/xworkbench/CommentComposeModal.tsx` |
| 修改 | `/webui-new/src/pages/xworkbench/BreakdownModal.tsx` |
| 修改 | `/webui-new/src/pages/xworkbench/TrendingList.tsx` |
| 修改 | `/webui-new/src/pages/xworkbench/TrendingPanel.tsx` |
| 修改 | `/webui-new/src/pages/PublishCenter.tsx` |

## 复用的现有函数/组件

- `xWorkbenchApi.generateComments` / `sendComment` / `generateXPostContent`（[xWorkbench.ts](file:///home/ubuntu/getuser-for-chengdu/MediaCrawler-main/webui-new/src/api/xWorkbench.ts)）— 直接搬移调用
- `autoPipelineApi.run`（[autoPipeline.ts:68](file:///home/ubuntu/getuser-for-chengdu/MediaCrawler-main/webui-new/src/api/autoPipeline.ts)）— BreakdownModal Step2 保留快速发布继续用
- `publishApi.multiPublish` 的 `source_post_id` 字段（[prdGap.ts:490](file:///home/ubuntu/getuser-for-chengdu/MediaCrawler-main/webui-new/src/api/prdGap.ts)）— 预填数据天然支持
- `usePlatform()` + `PLATFORM_TO_PIPELINE` 映射 — CommentComposeModal 复用

## 验证方式

1. **TypeScript 编译**：`./node_modules/.bin/tsc --noEmit -p .`（用 `/home/ubuntu/getuser-for-chengdu/nodejs/bin/node` 执行）无错误
2. **功能验证（手动 curl + 浏览器）**：
   - 热点中心选一条热点 → 点「生成评论」→ 弹出 CommentComposeModal（不再打开 BreakdownModal）→ 生成评论 → 编辑 → 真实发送/草稿
   - 热点中心选一条热点 → 点「视频拆解」→ Step0 拆解 → Step1 生成视频 → Step2 看到只有「一键发布」+「去发布中心」两个操作，无「生成文案」「发送评论」
   - Step2 点「去发布中心」→ 跳转 `/publish-center`，多平台 Tab 表单已预填 title/content/video_path，顶部有「从拆解内容预填」横幅
   - 切换平台（douyin/xhs/bilibili/x）重复上述流程，确认多平台兼容
3. **回归验证**：SentCommentsPanel 列表正常加载、RepliesModal 正常、发布中心三 Tab 切换正常
