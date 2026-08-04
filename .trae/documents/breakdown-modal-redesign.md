# 视频拆解 Modal 三步向导重构计划

## Context

当前 BreakdownModal（1012 行）将 8+ 个 Card 垂直堆叠在 1000px Modal 中，信息密度过高、功能混乱。用户提出三个需求：
1. **素材集成**：生成视频时可选/上传营销素材（品牌口号、水印等），或自定义视频内容参考
2. **默认平台**：发布时默认选中当前拆解的平台，支持单平台/多平台发布
3. **UI/UX 重构**：整体布局重新规划，消除混乱

同时发现视频生成端点 `generate_explainer_video` 只支持 X 平台（`_get_post_by_id` 只查 X 专属表），非 X 平台会 404，需一并修复。

## 方案：三步向导 + 素材集成 + 多平台视频生成

### 整体布局：Ant Design Steps 三步向导

| 步骤 | 标题 | 内容 | 主操作 |
|------|------|------|--------|
| 0 | AI 拆解 | 脚本分析 + 分镜/要点（双列）+ 推荐评论 | 重新拆解 / 下一步 |
| 1 | 视频生成 | 自定义脚本输入 + 素材库选择 + AI6700 生成 + 预览 | 上一步 / 生成 / 植入素材 / 下一步 |
| 2 | 发布互动 | 单/多平台切换（默认当前平台）+ 发布选项 + 文案 + 评论 | 上一步 / 发布 / 发送评论 |

---

## 实施步骤

### Step 1: 后端 — 视频生成多平台支持

**文件**: [x_twitter_workbench.py](file:///home/ubuntu/getuser-for-chengdu/MediaCrawler-main/api/routers/x_twitter_workbench.py)

1. **扩展 `ExplainerVideoRequest`**（第 62 行）：新增 `platform`、`post_url`、`content`、`video_url`、`username`、`custom_prompt` 字段（均有默认值，向后兼容）

2. **修改 `generate_explainer_video`**（第 724 行）：按平台分支取 post 数据
   - X 平台：保持原逻辑 `_get_post_by_id`
   - 非 X 平台：用请求中的 `post_url`/`content`/`video_url`/`username` 构造 post-like 对象

3. **支持 `custom_prompt`**（第 759 行）：用户自定义内容优先于拆解上下文

4. **更新 `_explainer_request_hash`**：将 `platform` 和 `custom_prompt` 纳入 hash，避免不同平台的 idempotency_key 误命中

### Step 2: 前端 API — 扩展 generateExplainerVideo 签名

**文件**: [xWorkbench.ts](file:///home/ubuntu/getuser-for-chengdu/MediaCrawler-main/webui-new/src/api/xWorkbench.ts)（第 487 行）

```ts
generateExplainerVideo: (post_id, idempotency_key, options?: {
  platform?: string; post_url?: string; content?: string;
  video_url?: string; username?: string; custom_prompt?: string;
}) => request.post('/x-workbench/explainer-video', { post_id, idempotency_key, ...options })
```

### Step 3: BreakdownModal 重构 — 三步向导

**文件**: [BreakdownModal.tsx](file:///home/ubuntu/getuser-for-chengdu/MediaCrawler-main/webui-new/src/pages/xworkbench/BreakdownModal.tsx)

#### 3a. 新增导入与状态

```ts
import { Steps, Radio, Empty, List } from 'antd';
import { marketingApi } from '../../api/prdGap';  // 素材 API 已就绪

// 新增状态
const [currentStep, setCurrentStep] = useState(0);
const [materials, setMaterials] = useState<any[]>([]);
const [selectedMaterialIds, setSelectedMaterialIds] = useState<number[]>([]);
const [customVideoPrompt, setCustomVideoPrompt] = useState('');
const [publishMode, setPublishMode] = useState<'single'|'multi'>('multi');
const [newMaterialModalOpen, setNewMaterialModalOpen] = useState(false);
```

#### 3b. 平台默认选中

`useEffect` 在 modal 打开时加载平台列表，并默认选中当前平台（含别名映射 `xhs`→`xiaohongshu` 等）：
```ts
const PLATFORM_TO_PIPELINE = { x:'x', xhs:'xiaohongshu', dy:'douyin', bili:'bilibili', wb:'weibo', ks:'kuaishou' };
useEffect(() => {
  if (!open) return;
  // 加载平台列表 → 默认选中当前平台
}, [open, platform]);
```

#### 3c. 素材库加载

`useEffect` 在进入 Step 1 时加载启用的素材列表：
```ts
useEffect(() => {
  if (open && currentStep === 1) {
    marketingApi.listMaterials({ only_active: true }).then(r => setMaterials(r.materials || []));
  }
}, [open, currentStep]);
```

#### 3d. 素材植入视频

生成视频后，用户可点击「植入素材」按钮，将选中的素材依次应用到视频：
- `slogan` 类型 → `marketingApi.addTextWatermark`（文字水印）
- `logo` 类型 → `marketingApi.addWatermark`（图片水印）
- `qr_code` 类型 → `marketingApi.addQrCode`（二维码贴片）

#### 3e. 新建素材子 Modal

在 BreakdownModal 内嵌一个素材创建表单（复用 `MarketingMaterials.tsx` 的字段约定），支持快速添加品牌口号等素材。

#### 3f. doGenerateVideo 改造

调用新签名，传递平台和帖子数据：
```ts
await xWorkbenchApi.generateExplainerVideo(post.post_id, idempotencyKey, {
  platform, post_url: post.post_url, content: post.content,
  video_url: post.video_url, username: post.username,
  custom_prompt: customVideoPrompt,
});
```

#### 3g. JSX 重构

将原 `return` 中的 8 个 Card 替换为 `<Steps>` + 三段条件渲染：

**Step 0（拆解）**: 脚本分析 Card + 分镜/要点双列 + 推荐评论 Card（点击评论 → 填入 editComment + 跳到 Step 2）

**Step 1（视频生成）**: 
- 自定义脚本/参考 TextArea（可选）
- 素材库 List（checkbox 多选，`Tag` 标注类型）+ 新增素材按钮
- 生成视频按钮 + 进度条 + 视频预览
- 植入素材按钮（生成后显示）

**Step 2（发布互动）**:
- `Radio.Group` 切换单/多平台
- 多平台：`Select[multiple]`（默认选中当前平台）
- 单平台：`Select`（默认当前平台，X 平台走 `doPublishToX`，其他走 `autoPipelineApi.run`）
- 发布选项（跳过视频/自动监控/触发互动）
- 发布文案（TextArea + 生成文案按钮）
- 发送评论（TextArea + 真实/草稿按钮）

**Footer**: 关闭 / 上一步(step>0) / 下一步(step<2) / 完成(step==2)

---

## 关键文件清单

| 文件 | 修改内容 |
|------|----------|
| [BreakdownModal.tsx](file:///home/ubuntu/getuser-for-chengdu/MediaCrawler-main/webui-new/src/pages/xworkbench/BreakdownModal.tsx) | 三步向导重构 + 素材集成 + 默认平台 |
| [x_twitter_workbench.py](file:///home/ubuntu/getuser-for-chengdu/MediaCrawler-main/api/routers/x_twitter_workbench.py) | ExplainerVideoRequest 扩展 + 多平台支持 |
| [xWorkbench.ts](file:///home/ubuntu/getuser-for-chengdu/MediaCrawler-main/webui-new/src/api/xWorkbench.ts) | generateExplainerVideo 签名扩展 |
| [prdGap.ts](file:///home/ubuntu/getuser-for-chengdu/MediaCrawler-main/webui-new/src/api/prdGap.ts) | marketingApi（已就绪，仅引用） |

## 复用的已有资产

- `marketingApi`（prdGap.ts:417-469）：素材 CRUD + 视频水印/文字水印/二维码 + 文案植入
- `autoPipelineApi`（autoPipeline.ts）：多平台发布流水线
- `usePlatform()`（PlatformContext.tsx）：当前平台上下文
- `MATERIAL_TYPE_OPTIONS`（MarketingMaterials.tsx）：素材类型标签配色

## 验证方法

1. **非 X 平台拆解+生成**：切到抖音/小红书 → 选择热点 → 点击拆解 → 生成视频 → 不再 404
2. **素材集成**：Step 1 中选择品牌口号素材 → 生成视频 → 点击植入 → 确认水印/文字应用
3. **默认平台**：打开 Modal → Step 2 默认选中当前平台
4. **单/多平台发布**：切换单平台模式 → 发布到当前平台；切换多平台 → 发布到多个平台
5. **UI 清晰度**：三步向导导航清晰，不再有 8 个 Card 堆叠
