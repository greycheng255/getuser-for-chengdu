import request from './request';

// ==================== 类型定义 ====================

export interface PlatformCapability {
  platform: string;
  name: string;
  region: string;
  real_publish: boolean;
  publisher: string;
  interactor: string;
  monitor: string | null;
  max_content: number;
}

export interface HotspotItem {
  post_id: string;
  post_url: string;
  content: string;
  video_url: string;
  username: string;
}

export interface RunPipelineParams {
  platform: string;
  hotspot_item: HotspotItem;
  skip_video?: boolean;
  auto_monitor?: boolean;
  trigger_interaction?: boolean;
  /** 已有的拆解文本（来自视频拆解 Modal），提供则跳过 Step1 AI 拆解 */
  breakdown_text?: string;
  /** 已生成的解说视频 URL（来自视频拆解 Modal），提供则跳过 Step2 视频生成并复用 */
  pre_video_url?: string;
  /** 已编辑的发布文案（来自重试/编辑），提供则跳过 Step3-4 文案生成与 AI 选文案 */
  pre_selected_content?: string;
  /** 是否为重试发布（来自发布中心重试按钮），写入 publish_records.metadata.is_retry 供前端区分 */
  is_retry?: boolean;
}

export interface PipelineTask {
  task_id: string;
  platform: string;
  source_post_id: string;
  source_post_url: string;
  source_post_content: string;
  source_post_video: string;
  source_post_author: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  current_step: number;
  step_name: string;
  step_detail: string;
  breakdown_text: string;
  video_url: string;
  candidate_contents: string[];
  selected_content: string;
  published_post_id: string;
  published_post_url: string;
  account_id: number | null;
  interaction_triggered: number;
  monitor_started: number;
  error_msg: string;
  options: Record<string, unknown>;
  owner_user_id: number | null;
  add_ts: number;
  update_ts: number;
}

// ==================== API ====================

export const autoPipelineApi = {
  /** 列出支持全流程的平台（含能力标注） */
  platforms: () =>
    request.get<any, { success: boolean; platforms: PlatformCapability[]; total: number }>('/auto_pipeline/platforms'),

  /** 启动多平台一键拆解流水线 */
  run: (data: RunPipelineParams) =>
    request.post<any, { success: boolean; task_id: string; platform: string; message: string }>('/auto_pipeline/run', data),

  /** 查询任务列表 */
  list: (params?: { platform?: string; status?: string; limit?: number }) =>
    request.get<any, { success: boolean; total: number; tasks: PipelineTask[] }>('/auto_pipeline', { params }),

  /** 查询单个任务状态 */
  status: (taskId: string) =>
    request.get<any, { success: boolean; task: PipelineTask }>(`/auto_pipeline/${taskId}`),

  /** 取消任务 */
  cancel: (taskId: string) =>
    request.post<any, { success: boolean; message: string }>(`/auto_pipeline/${taskId}/cancel`),
};
