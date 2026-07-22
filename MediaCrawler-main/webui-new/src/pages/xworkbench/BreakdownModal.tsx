import React, { useEffect, useState, useCallback, useRef } from 'react';
import {
  Modal,
  Spin,
  Alert,
  Card,
  Row,
  Col,
  Divider,
  Input,
  Button,
  Space,
  Typography,
  Progress,
  Tag,
  message,
} from 'antd';
import {
  VideoCameraOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
  SendOutlined,
  EditOutlined,
  DownloadOutlined,
  LoadingOutlined,
} from '@ant-design/icons';
import {
  xWorkbenchApi,
  type ExplainerVideoStatusResp,
  type WorkbenchPost,
} from '../../api/xWorkbench';
import { shouldClearVideoIntent } from '../../api/videoIntentPolicy.js';

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

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
  const [loading, setLoading] = useState(false);
  const [script, setScript] = useState('');
  const [storyboards, setStoryboards] = useState<string[]>([]);
  const [keyPoints, setKeyPoints] = useState<string[]>([]);
  const [suggestedComments, setSuggestedComments] = useState<string[]>([]);
  const [editComment, setEditComment] = useState('');
  const [sending, setSending] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [videoSubmitting, setVideoSubmitting] = useState(false);
  const [videoTaskId, setVideoTaskId] = useState('');
  const [videoModelName, setVideoModelName] = useState('');
  const [videoState, setVideoState] = useState<ExplainerVideoStatusResp | null>(null);
  const videoIntentRef = useRef<{ postId: string; key: string } | null>(null);

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
      key = window.crypto.randomUUID();
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

  const doBreakdown = useCallback(async (force = false) => {
    setLoading(true);
    try {
      const r = await xWorkbenchApi.generateBreakdown(post.post_id, force);
      setScript(r.script || '');
      setStoryboards(Array.isArray(r.storyboards) ? r.storyboards : []);
      setKeyPoints(Array.isArray(r.key_points) ? r.key_points : []);
      setSuggestedComments(Array.isArray(r.suggested_comments) ? r.suggested_comments : []);
      if (r.suggested_comments && Array.isArray(r.suggested_comments) && r.suggested_comments[0]) {
        setEditComment(r.suggested_comments[0]);
      }
    } catch (e: any) {
      message.error('拆解失败: ' + (e?.message || ''));
    } finally {
      setLoading(false);
    }
  }, [post.post_id]);

  useEffect(() => {
    if (open) {
      doBreakdown(false);
    }
  }, [open, doBreakdown]);

  useEffect(() => {
    setVideoTaskId('');
    setVideoModelName('');
    setVideoState(null);
  }, [post.post_id]);

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

  const doGenComments = async () => {
    setGenerating(true);
    try {
      const r = await xWorkbenchApi.generateComments(post.post_id, 3);
      if (r.comments && r.comments.length > 0) {
        setSuggestedComments(r.comments);
        setEditComment(r.comments[0]);
        message.success(`已生成 ${r.comments.length} 条评论`);
      }
    } catch (e: any) {
      message.error('生成评论失败: ' + (e?.message || ''));
    } finally {
      setGenerating(false);
    }
  };

  const doGenerateVideo = async () => {
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

  const doSend = async (real: boolean) => {
    if (!editComment.trim()) {
      message.warning('评论内容不能为空');
      return;
    }
    setSending(true);
    try {
      const r = await xWorkbenchApi.sendComment({
        post_id: post.post_id,
        post_url: post.post_url,
        content: editComment,
        real_send: real,
      });
      if (r.success) {
        message.success(`评论已${real ? '发送' : '保存为草稿'}（ID: ${r.sent_comment_id}）`);
        onClose();
      } else {
        message.error(`发送失败: ${r.message || '未知错误'}`);
      }
    } catch (e: any) {
      message.error('发送异常: ' + (e?.message || ''));
    } finally {
      setSending(false);
    }
  };

  return (
    <Modal
      title={
        <Space>
          <VideoCameraOutlined />
          <span>视频拆解 - @{post.username}</span>
        </Space>
      }
      open={open}
      onCancel={onClose}
      width={900}
      footer={
        <Space>
          <Button onClick={onClose}>关闭</Button>
          <Button icon={<ReloadOutlined />} loading={loading} onClick={() => doBreakdown(true)}>
            重新拆解
          </Button>
        </Space>
      }
    >
      <Spin spinning={loading}>
        <Paragraph ellipsis={{ rows: 2 }} type="secondary">
          {post.content}
        </Paragraph>
        {post.video_url && (
          <Alert
            type="warning"
            message="本系统暂未接入视频转写，AI 将基于推文文本进行分析"
            style={{ marginBottom: 12 }}
            showIcon
          />
        )}

        <Card size="small" title="【脚本分析】" style={{ marginBottom: 12 }}>
          <Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>{script || '（暂无）'}</Paragraph>
        </Card>

        <Row gutter={12} style={{ marginBottom: 12 }}>
          <Col span={12}>
            <Card size="small" title="【分镜拆解】" style={{ height: '100%' }}>
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
            <Card size="small" title="【关键要点】" style={{ height: '100%' }}>
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
            message="通过 AI6700 生成 10 秒手机竖屏中文解说视频"
            description="输出规格为 9:16、720p；检测到参考图片时使用参考生模型，否则使用文生视频模型。"
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
                <Alert type="error" showIcon message="生成失败" description={videoState.error} />
              )}

              {videoState.result_url && (
                <>
                  <video
                    src={videoState.result_url}
                    controls
                    style={{ width: '100%', maxHeight: 420, borderRadius: 8, background: '#000' }}
                  />
                  <Button
                    icon={<DownloadOutlined />}
                    href={videoState.result_url}
                    target="_blank"
                  >
                    打开或下载视频
                  </Button>
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

        <Card
          size="small"
          title="【推荐评论】"
          extra={
            <Button size="small" icon={<ThunderboltOutlined />} loading={generating} onClick={doGenComments}>
              重新生成
            </Button>
          }
          style={{ marginBottom: 12 }}
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
                  onClick={() => setEditComment(c)}
                >
                  {c}
                </Button>
              ))}
            </Space>
          )}
        </Card>

        <Divider>发送评论</Divider>
        <TextArea
          rows={3}
          placeholder="编辑评论内容（最多 280 字符）"
          value={editComment}
          onChange={(e) => setEditComment(e.target.value)}
          maxLength={280}
          showCount
        />
        <Space style={{ marginTop: 12 }}>
          <Button
            type="primary"
            icon={<SendOutlined />}
            loading={sending}
            onClick={() => doSend(true)}
          >
            真实发送
          </Button>
          <Button icon={<EditOutlined />} loading={sending} onClick={() => doSend(false)}>
            保存为草稿
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>
            真实发送需要 X_TWITTER_COOKIES 已配置
          </Text>
        </Space>
      </Spin>
    </Modal>
  );
};

export default BreakdownModal;
