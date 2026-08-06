import { message } from '../../utils/antdMessage';
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { Modal, Spin, Alert, Card, Row, Col, Divider, Input, Button, Space, Typography, Progress, Tag, Select, Checkbox, Steps, Radio, Empty, List } from 'antd';
import {
  VideoCameraOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
  SendOutlined,
  EditOutlined,
  DownloadOutlined,
  LoadingOutlined,
  RocketOutlined,
  CheckCircleOutlined,
  WarningOutlined,
  GiftOutlined,
  PlusOutlined,
  CloudUploadOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import {
  xWorkbenchApi,
  type ExplainerVideoStatusResp,
  type WorkbenchPost,
} from '../../api/xWorkbench';
import { usePlatform } from '../../context/PlatformContext';
import { autoPipelineApi, type PlatformCapability, type PipelineTask } from '../../api/autoPipeline';
import { marketingApi } from '../../api/prdGap';
import PipelineProgressModal from './PipelineProgressModal';
import { shouldClearVideoIntent } from '../../api/videoIntentPolicy.js';

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

// 平台别名映射：usePlatform() 的值 → autoPipeline 后端期望的值
const PLATFORM_TO_PIPELINE: Record<string, string> = {
  x: 'x', x_twitter: 'x', tw: 'x',
  youtube: 'youtube', yt: 'youtube',
  douyin: 'douyin', dy: 'douyin',
  bilibili: 'bilibili', bili: 'bilibili',
  kuaishou: 'kuaishou', ks: 'kuaishou',
  xiaohongshu: 'xiaohongshu', xhs: 'xiaohongshu',
  weibo: 'weibo', wb: 'weibo',
  zhihu: 'zhihu',
};

// 素材类型标签配色
const MATERIAL_TYPE_COLORS: Record<string, string> = {
  slogan: 'blue', logo: 'green', qr_code: 'orange',
  link: 'cyan', event: 'purple', contact: 'default',
};
const MATERIAL_TYPE_LABELS: Record<string, string> = {
  slogan: '品牌口号', logo: 'Logo水印', qr_code: '二维码',
  link: '链接', event: '活动', contact: '联系方式',
};

const apiErrorMessage = (error: any, fallback: string) =>
  error?.response?.data?.message || error?.response?.data?.detail || error?.message || fallback;

export interface BreakdownModalProps {
  post: WorkbenchPost;
  open: boolean;
  onClose: () => void;
}

/**
 * 视频拆解 Modal
 * 展示 AI 拆解的脚本/分镜/关键要点/推荐评论，并支持发送评论
 */
const BreakdownModal: React.FC<BreakdownModalProps> = ({ post, open, onClose }) => {
  const { platform } = usePlatform();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [script, setScript] = useState('');
  const [storyboards, setStoryboards] = useState<string[]>([]);
  const [keyPoints, setKeyPoints] = useState<string[]>([]);
  const [suggestedComments, setSuggestedComments] = useState<string[]>([]);
  const [videoSubmitting, setVideoSubmitting] = useState(false);
  const [videoTaskId, setVideoTaskId] = useState('');
  const [videoModelName, setVideoModelName] = useState('');
  const [videoState, setVideoState] = useState<ExplainerVideoStatusResp | null>(null);
  const videoIntentRef = useRef<{ postId: string; key: string } | null>(null);

  // ===== 多平台一键发布（platform-agnostic pipeline） =====
  const [platforms, setPlatforms] = useState<PlatformCapability[]>([]);
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>([]);
  const [multiPublishOptions, setMultiPublishOptions] = useState({
    skip_video: true,           // 多平台发布默认跳过视频生成（避免 20 分钟等待）
    auto_monitor: true,        // X 平台自动启动评论监控
    trigger_interaction: false, // 默认不触发互动（避免账号风险）
  });
  const [multiPublishLoading, setMultiPublishLoading] = useState(false);
  const [pipelineTasks, setPipelineTasks] = useState<PipelineTask[]>([]);
  const [pipelineModalOpen, setPipelineModalOpen] = useState(false);

  // ===== 三步向导 + 素材集成 =====
  const [currentStep, setCurrentStep] = useState(0);
  const [materials, setMaterials] = useState<any[]>([]);
  const [materialsLoading, setMaterialsLoading] = useState(false);
  const [selectedMaterialIds, setSelectedMaterialIds] = useState<number[]>([]);
  const [customVideoPrompt, setCustomVideoPrompt] = useState('');
  const [newMaterialModalOpen, setNewMaterialModalOpen] = useState(false);
  const [newMaterialForm, setNewMaterialForm] = useState({ name: '', material_type: 'slogan', content: '', position: 'bottom-right' });
  const [applyingMaterials, setApplyingMaterials] = useState(false);

  const videoIntentStorageKey = (postId: string) =>
    `x-workbench:explainer-video:intent:${postId}`;

  const getOrCreateVideoIntent = (postId: string) => {
    if (videoIntentRef.current?.postId === postId) {
      return videoIntentRef.current.key;
    }

    const storageKey = videoIntentStorageKey(postId);
    let key = '';
    try {
      key = window.sessionStorage.getItem(storageKey) || '';
    } catch {
      // Some privacy modes disable storage; the in-memory ref still preserves
      // the key for retries during this modal lifetime.
    }
    if (!key) {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      key = window.crypto.randomUUID();
    } else {
      key = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
      });
    }
    try {
      window.sessionStorage.setItem(storageKey, key);
    } catch {
      // See above: keep using the ref when storage is unavailable.
    }
  }
    videoIntentRef.current = { postId, key };
    return key;
  };

  const clearVideoIntent = (postId: string) => {
    if (videoIntentRef.current?.postId === postId) {
      videoIntentRef.current = null;
    }
    try {
      window.sessionStorage.removeItem(videoIntentStorageKey(postId));
    } catch {
      // Storage can be unavailable in hardened/private browser contexts.
    }
  };

  const [loadingScript, setLoadingScript] = useState(false);
  const [loadingStoryboards, setLoadingStoryboards] = useState(false);
  const [loadingKeyPoints, setLoadingKeyPoints] = useState(false);

  const doBreakdown = useCallback(async (force = false) => {
    setLoading(true);
    try {
      const r = await xWorkbenchApi.generateBreakdown({
        post_id: post.post_id,
        force_refresh: force,
        platform,
        post_url: post.post_url,
        content: post.content,
        username: post.username,
        video_url: post.video_url || '',
      });
      setScript(r.script || '');
      setStoryboards(Array.isArray(r.storyboards) ? r.storyboards : []);
      setKeyPoints(Array.isArray(r.key_points) ? r.key_points : []);
      setSuggestedComments(Array.isArray(r.suggested_comments) ? r.suggested_comments : []);
    } catch (e: any) {
      message.error('拆解失败: ' + (e?.message || ''));
    } finally {
      setLoading(false);
    }
  }, [post.post_id, platform, post.post_url, post.content, post.username, post.video_url]);

  const doRegenScript = async () => {
    setLoadingScript(true);
    try {
      const r = await xWorkbenchApi.generateBreakdown({
        post_id: post.post_id, force_refresh: true, platform,
        post_url: post.post_url, content: post.content, username: post.username, video_url: post.video_url || '',
      });
      setScript(r.script || '');
      message.success('脚本分析已重新生成');
    } catch (e: any) {
      message.error('脚本分析重新生成失败: ' + (e?.message || ''));
    } finally {
      setLoadingScript(false);
    }
  };

  const doRegenStoryboards = async () => {
    setLoadingStoryboards(true);
    try {
      const r = await xWorkbenchApi.generateBreakdown({
        post_id: post.post_id, force_refresh: true, platform,
        post_url: post.post_url, content: post.content, username: post.username, video_url: post.video_url || '',
      });
      setStoryboards(Array.isArray(r.storyboards) ? r.storyboards : []);
      message.success('分镜拆解已重新生成');
    } catch (e: any) {
      message.error('分镜拆解重新生成失败: ' + (e?.message || ''));
    } finally {
      setLoadingStoryboards(false);
    }
  };

  const doRegenKeyPoints = async () => {
    setLoadingKeyPoints(true);
    try {
      const r = await xWorkbenchApi.generateBreakdown({
        post_id: post.post_id, force_refresh: true, platform,
        post_url: post.post_url, content: post.content, username: post.username, video_url: post.video_url || '',
      });
      setKeyPoints(Array.isArray(r.key_points) ? r.key_points : []);
      message.success('关键要点已重新生成');
    } catch (e: any) {
      message.error('关键要点重新生成失败: ' + (e?.message || ''));
    } finally {
      setLoadingKeyPoints(false);
    }
  };

  useEffect(() => {
    if (open) {
      doBreakdown(false);
    }
  }, [open, doBreakdown]);

  // 打开/切换内容时,先查询该 post 的历史视频任务,恢复展示或继续轮询,避免重复生成
  useEffect(() => {
    let active = true;
    setVideoTaskId('');
    setVideoModelName('');
    setVideoState(null);
    if (!post.post_id) return;

    (async () => {
      try {
        const history = await xWorkbenchApi.getExplainerVideoByPost(post.post_id);
        if (!active) return;
        setVideoModelName(history.model_name || '');
        setVideoState({
          task_id: history.task_id,
          status: history.status,
          is_final: history.is_final,
          progress: history.progress,
          current_step: history.current_step,
          result_url: history.result_url,
          result_reference: history.result_reference,
          error: history.error,
          cost: history.cost,
        });
        // 非终态任务恢复轮询(触发下方 videoTaskId 的 useEffect)
        if (!history.is_final && history.task_id) {
          setVideoTaskId(history.task_id);
        }
      } catch {
        // 404 = 无历史任务,保持空白等用户点击生成
      }
    })();

    return () => { active = false; };
  }, [post.post_id]);

  // 加载多平台能力列表 + 默认选中当前平台
  useEffect(() => {
    if (!open) return;
    let active = true;
    (async () => {
      try {
        const r = await autoPipelineApi.platforms();
        if (!active) return;
        setPlatforms(r.platforms || []);
        // 默认选中当前平台（含别名映射）
        const pipelinePlatform = PLATFORM_TO_PIPELINE[platform] || platform;
        const exists = (r.platforms || []).some((p: PlatformCapability) => p.platform === pipelinePlatform);
        if (exists) {
          setSelectedPlatforms([pipelinePlatform]);
        }
      } catch (e) {
        console.warn('加载多平台能力列表失败', e);
      }
    })();
    return () => { active = false; };
  }, [open, platform]);

  // 跳转发布中心高级配置（携带拆解视频/内容预填数据）
  const goToPublishCenter = useCallback(() => {
    onClose();
    navigate('/publish-center', {
      state: {
        from_breakdown: true,
        source_post_id: post.post_id,
        video_url: videoState?.result_url || '',
        content: post.content,
        platform: PLATFORM_TO_PIPELINE[platform] || platform,
        title: `@${post.username} 热点拆解`,
      },
    });
  }, [onClose, navigate, post.post_id, post.content, post.username, platform, videoState]);

  // 多平台一键发布：对每个选中平台并发启动流水线
  const doMultiPlatformPublish = useCallback(async () => {
    if (selectedPlatforms.length === 0) {
      message.warning('请至少选择一个目标平台');
      return;
    }
    setMultiPublishLoading(true);
    setPipelineTasks([]);
    setPipelineModalOpen(true);

    // 构造热点项（统一字段名）
    const hotspotItem = {
      post_id: post.post_id,
      post_url: post.post_url,
      content: post.content,
      video_url: post.video_url || '',
      username: post.username,
    };

    // 复用已有拆解结果：把结构化数据重建为后端 parse_breakdown 可识别的格式
    // （【脚本分析】【分镜拆解】【关键要点】），避免流水线重复执行 Step1 AI 拆解
    const reuseBreakdownText = [
      script.trim() ? `【脚本分析】\n${script.trim()}` : '',
      storyboards.length > 0
        ? `【分镜拆解】\n${storyboards.map((s) => `- ${s}`).join('\n')}`
        : '',
      keyPoints.length > 0
        ? `【关键要点】\n${keyPoints.map((k) => `- ${k}`).join('\n')}`
        : '',
    ].filter(Boolean).join('\n\n');

    // 复用已生成的解说视频 URL（若有），避免流水线重新生成视频（省 20 分钟）
    const reuseVideoUrl = videoState?.result_url || '';

    // 对每个平台并发启动流水线
    const newTasks: PipelineTask[] = [];
    const settled = await Promise.allSettled(
      selectedPlatforms.map(async (platform) => {
        const r = await autoPipelineApi.run({
          platform,
          hotspot_item: hotspotItem,
          // 已有视频则跳过生成；否则沿用用户勾选的 skip_video
          skip_video: reuseVideoUrl ? true : multiPublishOptions.skip_video,
          auto_monitor: multiPublishOptions.auto_monitor,
          trigger_interaction: multiPublishOptions.trigger_interaction,
          // 传递已有拆解文本和视频 URL，让后端复用（跳过 Step1/Step2）
          breakdown_text: reuseBreakdownText || undefined,
          pre_video_url: reuseVideoUrl || undefined,
        });
        // 立即查询一次任务状态，构造初始 PipelineTask
        try {
          const st = await autoPipelineApi.status(r.task_id);
          return st.task;
        } catch {
          return {
            task_id: r.task_id,
            platform,
            source_post_id: hotspotItem.post_id,
            source_post_url: hotspotItem.post_url,
            source_post_content: hotspotItem.content,
            source_post_video: hotspotItem.video_url,
            source_post_author: hotspotItem.username,
            status: 'pending' as const,
            current_step: 0,
            step_name: '待启动',
            step_detail: '任务已创建,等待执行',
            breakdown_text: '',
            video_url: '',
            candidate_contents: [],
            selected_content: '',
            published_post_id: '',
            published_post_url: '',
            account_id: null,
            interaction_triggered: 0,
            monitor_started: 0,
            error_msg: '',
            options: {},
            owner_user_id: null,
            add_ts: Math.floor(Date.now() / 1000),
            update_ts: Math.floor(Date.now() / 1000),
          } as PipelineTask;
        }
      })
    );

    for (const s of settled) {
      if (s.status === 'fulfilled') {
        newTasks.push(s.value);
      } else {
        message.error(`启动失败: ${(s.reason as any)?.message || '未知错误'}`);
      }
    }

    setPipelineTasks(newTasks);
    setMultiPublishLoading(false);
    if (newTasks.length > 0) {
      message.success(`已启动 ${newTasks.length} 个平台的发布流水线`);
    }
  }, [selectedPlatforms, post, multiPublishOptions, script, storyboards, keyPoints, videoState]);

  useEffect(() => {
    if (!videoTaskId) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let consecutiveFailures = 0;

    const poll = async () => {
      try {
        const status = await xWorkbenchApi.getExplainerVideoStatus(videoTaskId);
        if (!active) return;
        consecutiveFailures = 0;
        setVideoState(status);
        if (status.is_final) {
          setVideoTaskId('');
          const failed = Boolean(status.error) || ['error', 'failed', 'canceled', 'cancelled'].includes(status.status);
          if (failed) {
            message.error(`解说视频生成失败: ${status.error || status.status}`);
          } else if (!status.result_url && !status.result_reference) {
            message.warning('解说视频任务已完成，但 AI6700 未返回可用结果');
          } else {
            message.success('解说视频生成完成');
          }
          return;
        }
      } catch (e: any) {
        if (!active) return;
        consecutiveFailures += 1;
        if (consecutiveFailures >= 3) {
          setVideoState((previous) => previous ? {
            ...previous,
            status: 'error',
            is_final: true,
            error: e?.message || '状态查询失败',
          } : null);
          setVideoTaskId('');
          message.error('解说视频状态查询失败: ' + (e?.message || ''));
          return;
        }
      }
      if (active) timer = setTimeout(poll, 5000);
    };

    timer = setTimeout(poll, 1000);
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [videoTaskId]);

  const doGenerateVideo = async () => {
    console.log('[doGenerateVideo] clicked');
    console.log('[doGenerateVideo] script:', script?.length, script?.substring(0, 50));
    console.log('[doGenerateVideo] storyboards:', storyboards.length, storyboards);
    console.log('[doGenerateVideo] keyPoints:', keyPoints.length, keyPoints);
    if (!script.trim() && storyboards.length === 0 && keyPoints.length === 0) {
      message.warning('请先完成视频拆解');
      return;
    }
    setVideoSubmitting(true);
    setVideoState(null);
    const idempotencyKey = getOrCreateVideoIntent(post.post_id);
    try {
      const result = await xWorkbenchApi.generateExplainerVideo(
        post.post_id,
        idempotencyKey,
        {
          platform,
          post_url: post.post_url,
          content: post.content,
          video_url: post.video_url || '',
          username: post.username,
          custom_prompt: customVideoPrompt,
        },
      );
      // A successful submit/replay means the intent now has a stable local
      // task.  A later deliberate click must start a new paid intent.
      clearVideoIntent(post.post_id);
      setVideoModelName(result.model_name);
      setVideoState({
        task_id: result.task_id,
        status: result.status,
        is_final: false,
        progress: 5,
        current_step: 'init',
        result_url: '',
        error: '',
        cost: 0,
      });
      setVideoTaskId(result.task_id);
      message.success(`视频任务已提交：${result.model_name}`);
    } catch (e: any) {
      const reason = e?.response?.data?.data?.reason;
      const status = e?.response?.status;
      if (shouldClearVideoIntent({ status, reason })) {
        // Billing rejection and an explicit request/destination conflict are
        // terminal for this intent; a later click is a new paid attempt.
        clearVideoIntent(post.post_id);
      }
      message.error('解说视频提交失败: ' + apiErrorMessage(e, '未知错误'));
    } finally {
      setVideoSubmitting(false);
    }
  };

  // ===== 素材库加载 =====
  useEffect(() => {
    if (!open || currentStep !== 1) return;
    let active = true;
    (async () => {
      setMaterialsLoading(true);
      try {
        const r = await marketingApi.listMaterials({ only_active: true });
        if (!active) return;
        setMaterials(r.materials || []);
      } catch (e) {
        console.warn('加载素材库失败', e);
      } finally {
        if (active) setMaterialsLoading(false);
      }
    })();
    return () => { active = false; };
  }, [open, currentStep]);

  // ===== 植入素材到视频 =====
  const applyMaterialsToVideo = async () => {
    if (!videoState?.result_url) {
      message.warning('请先生成视频');
      return;
    }
    if (selectedMaterialIds.length === 0) {
      message.warning('请选择至少一个素材');
      return;
    }
    setApplyingMaterials(true);
    try {
      let lastOutput = videoState.result_url;
      for (const id of selectedMaterialIds) {
        const m = materials.find((x: any) => x.id === id);
        if (!m) continue;
        const outPath = `${lastOutput}_proc_${id}.mp4`;
        if (m.material_type === 'logo' && m.file_path) {
          const r = await marketingApi.addWatermark({
            video_path: lastOutput, logo_path: m.file_path,
            output_path: outPath, position: m.position || 'bottom-right',
          });
          if (r.output_path) lastOutput = r.output_path;
        } else if (m.material_type === 'qr_code' && m.file_path) {
          const r = await marketingApi.addQrCode({
            video_path: lastOutput, qr_image_path: m.file_path,
            output_path: outPath, position: m.position || 'bottom-right',
          });
          if (r.output_path) lastOutput = r.output_path;
        } else if (m.material_type === 'slogan' && m.content) {
          const r = await marketingApi.addTextWatermark({
            video_path: lastOutput, text: m.content,
            output_path: outPath, position: m.position || 'bottom-right',
          });
          if (r.output_path) lastOutput = r.output_path;
        }
      }
      message.success(`已植入 ${selectedMaterialIds.length} 个素材到视频`);
      // 更新预览（如果后端返回可访问的路径）
      setVideoState(prev => prev ? { ...prev, result_url: lastOutput } : prev);
    } catch (e: any) {
      message.error('素材植入失败: ' + apiErrorMessage(e, ''));
    } finally {
      setApplyingMaterials(false);
    }
  };

  // ===== 新建素材 =====
  const doCreateMaterial = async () => {
    if (!newMaterialForm.name.trim()) {
      message.warning('请输入素材名称');
      return;
    }
    try {
      await marketingApi.createMaterial(newMaterialForm);
      message.success('素材已创建');
      setNewMaterialModalOpen(false);
      setNewMaterialForm({ name: '', material_type: 'slogan', content: '', position: 'bottom-right' });
      const r = await marketingApi.listMaterials({ only_active: true });
      setMaterials(r.materials || []);
    } catch (e: any) {
      message.error('创建素材失败: ' + apiErrorMessage(e, ''));
    }
  };

  return (
    <>
    <Modal
      title={
        <Space>
          <VideoCameraOutlined />
          <span>视频拆解 - @{post.username}</span>
        </Space>
      }
      open={open}
      onCancel={onClose}
      width={960}
      footer={
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Space>
            {currentStep > 0 && (
              <Button onClick={() => setCurrentStep(s => s - 1)}>上一步</Button>
            )}
            {currentStep === 0 && (
              <Button icon={<ReloadOutlined />} loading={loading} onClick={() => doBreakdown(true)}>
                重新拆解
              </Button>
            )}
          </Space>
          <Space>
            <Button onClick={onClose}>关闭</Button>
            {currentStep < 2 && (
              <Button type="primary" onClick={() => setCurrentStep(s => s + 1)}>
                下一步
              </Button>
            )}
          </Space>
        </Space>
      }
    >
      <Spin spinning={loading}>
        <Paragraph ellipsis={{ rows: 2 }} type="secondary">
          {post.content}
        </Paragraph>

        <Steps
          current={currentStep}
          size="small"
          style={{ marginBottom: 20 }}
          items={[
            { title: 'AI 拆解' },
            { title: '视频生成' },
            { title: '发布互动' },
          ]}
        />

        {/* ===== Step 0: AI 拆解 ===== */}
        {currentStep === 0 && (
          <>
            {post.video_url && (
              <Alert
                type="warning"
                message="本系统暂未接入视频转写，AI 将基于文本进行分析"
                style={{ marginBottom: 12 }}
                showIcon
              />
            )}

            <Card
              size="small"
              title="【脚本分析】"
              style={{ marginBottom: 12 }}
              extra={
                <Button size="small" icon={<ReloadOutlined />} loading={loadingScript} onClick={doRegenScript}>
                  重试
                </Button>
              }
            >
              <Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>{script || '（暂无）'}</Paragraph>
            </Card>

            <Row gutter={12} style={{ marginBottom: 12 }}>
              <Col span={12}>
                <Card
                  size="small"
                  title="【分镜拆解】"
                  style={{ height: '100%' }}
                  extra={
                    <Button size="small" icon={<ReloadOutlined />} loading={loadingStoryboards} onClick={doRegenStoryboards}>
                      重试
                    </Button>
                  }
                >
                  {storyboards.length === 0 ? (
                    <Text type="secondary">暂无</Text>
                  ) : (
                    <ol style={{ paddingLeft: 20, marginBottom: 0 }}>
                      {storyboards.map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ol>
                  )}
                </Card>
              </Col>
              <Col span={12}>
                <Card
                  size="small"
                  title="【关键要点】"
                  style={{ height: '100%' }}
                  extra={
                    <Button size="small" icon={<ReloadOutlined />} loading={loadingKeyPoints} onClick={doRegenKeyPoints}>
                      重试
                    </Button>
                  }
                >
                  {keyPoints.length === 0 ? (
                    <Text type="secondary">暂无</Text>
                  ) : (
                    <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
                      {keyPoints.map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                  )}
                </Card>
              </Col>
            </Row>

            <Card
              size="small"
              title={
                <Space>
                  <span>【推荐评论】</span>
                  <Tag color="blue" style={{ fontSize: 11 }}>点击复制</Tag>
                </Space>
              }
            >
              {suggestedComments.length === 0 ? (
                <Text type="secondary">暂无</Text>
              ) : (
                <Space direction="vertical" style={{ width: '100%' }}>
                  {suggestedComments.map((c, i) => (
                    <Button
                      key={i}
                      block
                      style={{ textAlign: 'left', height: 'auto', whiteSpace: 'normal', padding: '8px 12px' }}
                      onClick={() => {
                        // 评论发送已迁移到独立的「生成评论」Modal（热点卡片入口）
                        // 这里仅复制到剪贴板，引导用户使用热点卡片的「生成评论」按钮发送
                        navigator.clipboard?.writeText(c).then(
                          () => message.success('评论已复制，请关闭弹窗后点击热点卡片的「生成评论」按钮发送'),
                          () => message.info('请手动复制评论，关闭弹窗后点击热点卡片的「生成评论」按钮发送'),
                        );
                      }}
                    >
                      {c}
                    </Button>
                  ))}
                </Space>
              )}
            </Card>
          </>
        )}

        {/* ===== Step 1: 视频生成 ===== */}
        {currentStep === 1 && (
          <>
            {/* 自定义视频内容/参考 */}
            <Card size="small" title="【自定义视频内容】（可选）" style={{ marginBottom: 12 }}>
              <TextArea
                rows={3}
                placeholder="输入自定义视频内容或参考描述，留空则使用 AI 拆解的脚本/分镜自动生成 prompt"
                value={customVideoPrompt}
                onChange={(e) => setCustomVideoPrompt(e.target.value)}
              />
              <Text type="secondary" style={{ fontSize: 12, marginTop: 4, display: 'block' }}>
                填写后将覆盖拆解上下文，直接作为 AI6700 视频生成的 prompt
              </Text>
            </Card>

            {/* 营销素材选择 */}
            <Card
              size="small"
              title={
                <Space>
                  <GiftOutlined />
                  <span>【营销素材】</span>
                  <Tag color="blue" style={{ fontSize: 11 }}>选中后可植入视频</Tag>
                </Space>
              }
              style={{ marginBottom: 12 }}
              extra={
                <Button size="small" icon={<PlusOutlined />} onClick={() => setNewMaterialModalOpen(true)}>
                  新增素材
                </Button>
              }
            >
              <Spin spinning={materialsLoading}>
                {materials.length === 0 ? (
                  <Empty description="暂无启用的素材" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                ) : (
                  <List
                    size="small"
                    dataSource={materials}
                    renderItem={(m: any) => (
                      <List.Item
                        actions={[
                          <Checkbox
                            key="sel"
                            checked={selectedMaterialIds.includes(m.id)}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setSelectedMaterialIds(prev => [...prev, m.id]);
                              } else {
                                setSelectedMaterialIds(prev => prev.filter(id => id !== m.id));
                              }
                            }}
                          >
                            植入
                          </Checkbox>,
                        ]}
                      >
                        <List.Item.Meta
                          title={
                            <Space size={4}>
                              <Tag color={MATERIAL_TYPE_COLORS[m.material_type] || 'default'} style={{ fontSize: 11 }}>
                                {MATERIAL_TYPE_LABELS[m.material_type] || m.material_type}
                              </Tag>
                              <span style={{ fontSize: 13 }}>{m.name}</span>
                            </Space>
                          }
                          description={
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              {m.content || m.file_path || m.link_url || '—'} · 位置: {m.position || 'bottom-right'}
                            </Text>
                          }
                        />
                      </List.Item>
                    )}
                  />
                )}
              </Spin>
            </Card>

            {/* AI6700 视频生成 */}
            <Card
              size="small"
              title="【生成解说视频】"
              extra={
                <Button
                  type="primary"
                  size="small"
                  icon={videoSubmitting || videoTaskId ? <LoadingOutlined /> : <VideoCameraOutlined />}
                  loading={videoSubmitting}
                  disabled={Boolean(videoTaskId)}
                  onClick={doGenerateVideo}
                >
                  {videoTaskId ? '生成中' : '生成视频'}
                </Button>
              }
              style={{ marginBottom: 12 }}
            >
              <Alert
                type="info"
                showIcon
                message="通过 AI6700 生成 5 秒手机竖屏中文解说视频"
                description="输出规格为 9:16、480p；检测到参考图片时使用参考生模型，否则使用文生视频模型。"
                style={{ marginBottom: videoState ? 12 : 0 }}
              />

              {videoState && (
                <Space direction="vertical" style={{ width: '100%' }} size={10}>
                  <Space wrap>
                    <Tag color="purple">{videoModelName || 'Seedance 2.0'}</Tag>
                    <Text type="secondary">任务：{videoState.task_id}</Text>
                  </Space>

                  {!videoState.is_final && (
                    <Progress
                      percent={videoState.progress}
                      status="active"
                      format={(percent) => `${percent}% · ${videoState.current_step || '生成中'}`}
                    />
                  )}

                  {videoState.error && (
                    <Alert type="error" showIcon title="生成失败" description={videoState.error} />
                  )}

                  {videoState.result_url && (
                    <>
                      <video
                        src={videoState.result_url}
                        controls
                        style={{ width: '100%', maxHeight: 360, borderRadius: 8, background: '#000' }}
                      />
                      <Space wrap>
                        <Button icon={<DownloadOutlined />} href={videoState.result_url} target="_blank">
                          打开或下载视频
                        </Button>
                        {selectedMaterialIds.length > 0 && (
                          <Button
                            type="primary"
                            icon={<GiftOutlined />}
                            loading={applyingMaterials}
                            onClick={applyMaterialsToVideo}
                          >
                            植入 {selectedMaterialIds.length} 个素材到视频
                          </Button>
                        )}
                      </Space>
                    </>
                  )}

                  {!videoState.result_url && videoState.result_reference && (
                    <Alert
                      type="success"
                      showIcon
                      message="视频已生成"
                      description={`AI6700 结果引用：${videoState.result_reference}`}
                    />
                  )}
                </Space>
              )}
            </Card>
          </>
        )}

        {/* ===== Step 2: 快速发布（高级配置请去发布中心） ===== */}
        {currentStep === 2 && (
          <>
            <Alert
              type="info"
              showIcon
              message="快速发布 / 高级配置二选一"
              description={
                <span>
                  本页只做「一键快速发布到当前拆解平台」。如需账号分组、视频上传、风控、定时等高级配置，请点击下方「去发布中心高级配置」按钮，将自动预填拆解视频与内容。
                </span>
              }
              style={{ marginBottom: 12 }}
            />

            {/* 复用已有结果提示：让用户清楚流水线不会重复拆解/生成视频 */}
            {(script.trim() || storyboards.length > 0 || videoState?.result_url) && (
              <Alert
                type="success"
                showIcon
                style={{ marginBottom: 12 }}
                message="本次发布将复用已有结果（不会重复执行）"
                description={
                  <Space size={4} wrap>
                    {script.trim() && <Tag color="green">✓ 复用 AI 拆解（跳过 Step1）</Tag>}
                    {videoState?.result_url ? (
                      <Tag color="green">✓ 复用已生成视频（跳过 Step2，省 ~20 分钟）</Tag>
                    ) : (
                      <Tag color="orange">未生成视频，将按勾选项决定是否生成</Tag>
                    )}
                  </Space>
                }
              />
            )}

            <Card
              size="small"
              title={
                <Space>
                  <RocketOutlined style={{ color: '#722ed1' }} />
                  <span>【快速发布】</span>
                </Space>
              }
              style={{ marginBottom: 12, borderColor: '#722ed1', background: '#faf5ff' }}
            >
              <div style={{ marginBottom: 12 }}>
                <Text strong style={{ display: 'block', marginBottom: 6 }}>选择目标平台（默认已选中当前拆解平台）：</Text>
                <Select
                  mode="multiple"
                  placeholder="选择要发布的平台（可多选）"
                  value={selectedPlatforms}
                  onChange={setSelectedPlatforms}
                  style={{ width: '100%' }}
                  optionLabelProp="label"
                  options={platforms.map((p) => ({
                    value: p.platform,
                    label: (
                      <Space size={4}>
                        <span>{p.name}</span>
                        {p.real_publish ? (
                          <Tag color="success" style={{ fontSize: 10, margin: 0, padding: '0 4px' }}>
                            <CheckCircleOutlined /> 真实发布
                          </Tag>
                        ) : (
                          <Tag color="warning" style={{ fontSize: 10, margin: 0, padding: '0 4px' }}>
                            <WarningOutlined /> DRY-RUN
                          </Tag>
                        )}
                      </Space>
                    ),
                  }))}
                />
              </div>

              <div style={{ marginBottom: 12 }}>
                <Space wrap>
                  <Checkbox
                    checked={multiPublishOptions.skip_video}
                    onChange={(e) => setMultiPublishOptions((s) => ({ ...s, skip_video: e.target.checked }))}
                  >
                    跳过解说视频生成（推荐）
                  </Checkbox>
                  <Checkbox
                    checked={multiPublishOptions.auto_monitor}
                    onChange={(e) => setMultiPublishOptions((s) => ({ ...s, auto_monitor: e.target.checked }))}
                  >
                    自动启动评论监控（仅 X）
                  </Checkbox>
                  <Checkbox
                    checked={multiPublishOptions.trigger_interaction}
                    onChange={(e) => setMultiPublishOptions((s) => ({ ...s, trigger_interaction: e.target.checked }))}
                  >
                    触发同平台点赞造势
                  </Checkbox>
                </Space>
              </div>

              <Space wrap>
                <Button
                  type="primary"
                  icon={<RocketOutlined />}
                  loading={multiPublishLoading}
                  disabled={selectedPlatforms.length === 0}
                  onClick={doMultiPlatformPublish}
                  style={{ background: '#722ed1', borderColor: '#722ed1' }}
                >
                  一键发布到所选平台（{selectedPlatforms.length}）
                </Button>
                <Button
                  icon={<CloudUploadOutlined />}
                  onClick={goToPublishCenter}
                >
                  去发布中心高级配置
                </Button>
              </Space>
            </Card>

            <Card size="small" title="【已迁移功能】" style={{ marginBottom: 12, background: '#f6ffed', borderColor: '#b7eb8f' }}>
              <Space direction="vertical" style={{ width: '100%' }} size={6}>
                <Text>
                  <Tag color="green">迁移</Tag>「生成发布文案」「发送评论」已迁移到独立的「生成评论」Modal。
                </Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  关闭本弹窗后，点击热点卡片上的「生成评论」按钮即可打开评论撰写界面（生成评论 / 真实发送 / 草稿 / 生成发布文案 / 跳转发布中心）。
                </Text>
              </Space>
            </Card>
          </>
        )}
      </Spin>
    </Modal>

    {/* 多平台流水线进度 Modal */}
    <PipelineProgressModal
      open={pipelineModalOpen}
      onClose={() => setPipelineModalOpen(false)}
      tasks={pipelineTasks}
      onTasksUpdate={setPipelineTasks}
    />

    {/* 新建素材子 Modal */}
    <Modal
      title="新增营销素材"
      open={newMaterialModalOpen}
      onCancel={() => setNewMaterialModalOpen(false)}
      onOk={doCreateMaterial}
      width={480}
      getContainer={false}
    >
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        <div>
          <Text strong style={{ display: 'block', marginBottom: 4 }}>素材名称</Text>
          <Input
            placeholder="如：品牌口号-夏季促销"
            value={newMaterialForm.name}
            onChange={(e) => setNewMaterialForm(s => ({ ...s, name: e.target.value }))}
          />
        </div>
        <div>
          <Text strong style={{ display: 'block', marginBottom: 4 }}>素材类型</Text>
          <Select
            value={newMaterialForm.material_type}
            onChange={(v) => setNewMaterialForm(s => ({ ...s, material_type: v }))}
            style={{ width: '100%' }}
            options={[
              { value: 'slogan', label: '品牌口号（文字水印）' },
              { value: 'logo', label: 'Logo（图片水印）' },
              { value: 'qr_code', label: '二维码贴片' },
              { value: 'link', label: '链接' },
              { value: 'event', label: '活动信息' },
              { value: 'contact', label: '联系方式' },
            ]}
          />
        </div>
        <div>
          <Text strong style={{ display: 'block', marginBottom: 4 }}>内容（品牌口号文字/链接URL等）</Text>
          <TextArea
            rows={2}
            placeholder="如：AI赋能高效获客"
            value={newMaterialForm.content}
            onChange={(e) => setNewMaterialForm(s => ({ ...s, content: e.target.value }))}
          />
        </div>
        <div>
          <Text strong style={{ display: 'block', marginBottom: 4 }}>位置</Text>
          <Select
            value={newMaterialForm.position}
            onChange={(v) => setNewMaterialForm(s => ({ ...s, position: v }))}
            style={{ width: '100%' }}
            options={[
              { value: 'bottom-right', label: '右下角' },
              { value: 'bottom-left', label: '左下角' },
              { value: 'top-right', label: '右上角' },
              { value: 'top-left', label: '左上角' },
              { value: 'center', label: '居中' },
            ]}
          />
        </div>
      </Space>
    </Modal>
    </>
  );
};

export default BreakdownModal;
