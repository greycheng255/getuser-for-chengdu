import { message } from '../../utils/antdMessage';
import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Modal, Button, Space, Tag, Progress, Alert, Card, Typography, Empty } from 'antd';
import {
  ThunderboltOutlined,
  LoadingOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  SendOutlined,
  StopOutlined,
} from '@ant-design/icons';
import { autoPipelineApi, type PipelineTask } from '../../api/autoPipeline';

const { Text, Paragraph } = Typography;

// 流水线步骤定义（与后端 STEP_NAMES 对齐）
const PIPELINE_STEPS = [
  '待启动',
  '视频拆解',
  '生成解说视频',
  '生成发布文案',
  'AI选最佳文案',
  '填入视频URL',
  '发布到目标平台',
  '触发互动造势',
  '启动评论监控',
];

// 平台颜色映射（与 platformThemes 对齐，简化版）
const PLATFORM_COLORS: Record<string, string> = {
  x: '#000000',
  douyin: '#000000',
  xiaohongshu: '#FF2442',
  bilibili: '#00A1D6',
  weibo: '#E6162D',
  zhihu: '#0084FF',
};

const PLATFORM_LABELS: Record<string, string> = {
  x: 'X (Twitter)',
  douyin: '抖音',
  xiaohongshu: '小红书',
  bilibili: '哔哩哔哩',
  weibo: '微博',
  zhihu: '知乎',
};

export interface PipelineProgressModalProps {
  open: boolean;
  onClose: () => void;
  /** 多平台任务列表（每条对应一个平台的发布任务） */
  tasks: PipelineTask[];
  /** 任务状态更新回调（外部需要同步状态） */
  onTasksUpdate?: (tasks: PipelineTask[]) => void;
}

/**
 * 多平台流水线进度 Modal
 *
 * 共享给 BreakdownModal 和 TrendingPanel 使用。
 * 支持：
 * - 多任务并行展示（每个平台一行 Steps + Progress）
 * - 自动轮询任务状态（3s/次）
 * - 取消单个任务
 * - 显示 AI 选中的发布文案、发布结果链接
 */
const PipelineProgressModal: React.FC<PipelineProgressModalProps> = ({
  open,
  onClose,
  tasks,
  onTasksUpdate,
}) => {
  const [localTasks, setLocalTasks] = useState<PipelineTask[]>(tasks);
  const pollingRef = useRef<number | null>(null);

  // 同步外部 tasks
  useEffect(() => {
    setLocalTasks(tasks);
  }, [tasks]);

  // 轮询所有未完成任务的状态
  const pollAllTasks = useCallback(async () => {
    const pending = localTasks.filter(
      (t) => t.status === 'running' || t.status === 'pending'
    );
    if (pending.length === 0) return;

    const updated: PipelineTask[] = [];
    let changed = false;
    for (const t of pending) {
      try {
        const r = await autoPipelineApi.status(t.task_id);
        updated.push(r.task);
        if (r.task.update_ts !== t.update_ts || r.task.status !== t.status) {
          changed = true;
        }
      } catch {
        updated.push(t);
      }
    }
    if (changed) {
      const merged = localTasks.map((t) => {
        const u = updated.find((x) => x.task_id === t.task_id);
        return u || t;
      });
      setLocalTasks(merged);
      onTasksUpdate?.(merged);
    }
  }, [localTasks, onTasksUpdate]);

  // 启动/停止轮询
  useEffect(() => {
    if (!open) return;
    const hasRunning = localTasks.some(
      (t) => t.status === 'running' || t.status === 'pending'
    );
    if (hasRunning) {
      // 立即轮询一次
      pollAllTasks();
      pollingRef.current = window.setInterval(pollAllTasks, 3000);
    }
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [open, localTasks.length, pollAllTasks]);

  // 取消单个任务
  const handleCancel = useCallback(async (taskId: string) => {
    try {
      await autoPipelineApi.cancel(taskId);
      const updated = localTasks.map((t) =>
        t.task_id === taskId
          ? { ...t, status: 'cancelled' as const, step_detail: '用户手动取消' }
          : t
      );
      setLocalTasks(updated);
      onTasksUpdate?.(updated);
      message.warning('任务已取消');
    } catch (e: any) {
      message.error('取消失败: ' + (e?.message || ''));
    }
  }, [localTasks, onTasksUpdate]);

  const anyRunning = localTasks.some(
    (t) => t.status === 'running' || t.status === 'pending'
  );

  const completedCount = localTasks.filter((t) => t.status === 'completed').length;
  const failedCount = localTasks.filter(
    (t) => t.status === 'failed' || t.status === 'cancelled'
  ).length;

  return (
    <Modal
      title={
        <Space>
          <ThunderboltOutlined style={{ color: '#faad14' }} />
          <span>多平台一键发布进度</span>
          {localTasks.length > 0 && (
            <Tag color="blue">
              {localTasks.length} 个任务（成功 {completedCount} / 失败 {failedCount}）
            </Tag>
          )}
        </Space>
      }
      open={open}
      onCancel={onClose}
      width={760}
      footer={
        <Button onClick={onClose}>
          {anyRunning ? '后台运行' : '关闭'}
        </Button>
      }
      mask={{ closable: !anyRunning }}
    >
      {localTasks.length === 0 ? (
        <Empty description="暂无任务" />
      ) : (
        <Space direction="vertical" style={{ width: '100%' }} size={16}>
          {localTasks.map((task) => (
            <TaskCard key={task.task_id} task={task} onCancel={handleCancel} />
          ))}
        </Space>
      )}
    </Modal>
  );
};

// ==================== 单任务卡片 ====================

export interface TaskCardProps {
  task: PipelineTask;
  onCancel?: (taskId: string) => void;
}

export const TaskCard: React.FC<TaskCardProps> = ({ task, onCancel }) => {
  const color = PLATFORM_COLORS[task.platform] || '#1677ff';
  const label = PLATFORM_LABELS[task.platform] || task.platform;
  const isRunning = task.status === 'running' || task.status === 'pending';
  const isCompleted = task.status === 'completed';
  const isFailed = task.status === 'failed' || task.status === 'cancelled';

  // 总进度（8 步）
  const totalSteps = 8;
  const percent = isCompleted
    ? 100
    : Math.round((task.current_step / totalSteps) * 100);

  return (
    <Card
      size="small"
      title={
        <Space>
          <span
            style={{
              display: 'inline-block',
              width: 10,
              height: 10,
              borderRadius: '50%',
              backgroundColor: color,
            }}
          />
          <span style={{ color }}>{label}</span>
          {isCompleted && <Tag color="success" icon={<CheckCircleOutlined />}>完成</Tag>}
          {isRunning && <Tag color="processing" icon={<LoadingOutlined />}>进行中</Tag>}
          {isFailed && <Tag color="error" icon={<CloseCircleOutlined />}>{task.status === 'cancelled' ? '已取消' : '失败'}</Tag>}
        </Space>
      }
      extra={
        isRunning && onCancel && (
          <Button
            size="small"
            danger
            type="text"
            icon={<StopOutlined />}
            onClick={() => onCancel(task.task_id)}
          >
            取消
          </Button>
        )
      }
      style={{ borderColor: isCompleted ? '#52c41a' : isFailed ? '#ff4d4f' : '#d9d9d9' }}
    >
      {/* 进度条 */}
      <Progress
        percent={percent}
        status={isCompleted ? 'success' : isFailed ? 'exception' : 'active'}
        size="small"
        style={{ marginBottom: 12 }}
      />

      {/* 步骤 Tags（横向展示，自动换行） */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
        {PIPELINE_STEPS.slice(1).map((name, i) => {
          const stepNum = i + 1;
          const isDone = task.current_step > stepNum || isCompleted;
          const isCurrent = task.current_step === stepNum && isRunning;
          let tagColor: string = 'default';
          let icon: React.ReactNode = <span>{stepNum}</span>;
          if (isDone) { tagColor = 'success'; icon = '✓'; }
          else if (isCurrent) { tagColor = 'processing'; icon = <LoadingOutlined />; }
          return (
            <Tag key={stepNum} color={tagColor as any} style={{ margin: 0 }}>
              {icon} {name}
            </Tag>
          );
        })}
      </div>

      {/* 当前步骤详情 */}
      {task.step_detail && !isCompleted && (
        <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
          当前: {task.step_detail}
        </Text>
      )}

      {/* AI 选中的发布文案 */}
      {task.selected_content && (
        <Card size="small" type="inner" title="AI 选中的发布文案" style={{ marginBottom: 8 }}>
          <Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
            {task.selected_content}
          </Paragraph>
        </Card>
      )}

      {/* 错误信息 */}
      {isFailed && task.error_msg && (
        <Alert
          type="error"
          showIcon
          message={task.status === 'cancelled' ? '任务已取消' : '执行失败'}
          description={task.error_msg}
          style={{ marginBottom: 8 }}
        />
      )}

      {/* 发布结果 */}
      {task.published_post_url && isCompleted && (
        <div>
          <Text strong>发布结果:</Text>
          <div style={{ marginTop: 4, marginBottom: 4 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              帖子ID: {task.published_post_id || '(无)'}
            </Text>
          </div>
          <Button
            size="small"
            type="link"
            href={task.published_post_url}
            target="_blank"
            icon={<SendOutlined />}
          >
            查看发布内容
          </Button>
        </div>
      )}

      {/* DRY-RUN 提示（无 published_post_id 但状态 completed） */}
      {isCompleted && !task.published_post_url && (
        <Alert
          type="info"
          showIcon
          message="模拟发布完成（DRY-RUN）"
          description="该平台暂无真实发布实现，已生成完整文案但未实际发布到平台。"
        />
      )}
    </Card>
  );
};

export default PipelineProgressModal;
