import React, { useEffect, useState, useCallback } from 'react';
import {
  Row,
  Col,
  Card,
  Statistic,
  Spin,
  Collapse,
  Empty,
  List,
  Tag,
  Avatar,
  Tooltip,
  Badge,
  Button,
  Space,
  Progress,
  Alert,
  Typography,
  message,
} from 'antd';
import {
  MessageOutlined,
  CheckCircleTwoTone,
  ThunderboltOutlined,
  ReloadOutlined,
  DownOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined,
  RobotOutlined,
} from '@ant-design/icons';
import {
  xWorkbenchApi,
  type WorkbenchStats,
  type MonitorStatus,
  type SentComment,
  type ReplyRecord,
  type AutoModeStatus,
} from '../../api/xWorkbench';

const { Text } = Typography;

/**
 * 监控设置面板
 * 展示工作台统计 + 评论回复列表 + 监控服务状态 + AI 健康检查
 */
const MonitorPanel: React.FC = () => {
  const [stats, setStats] = useState<WorkbenchStats | null>(null);
  const [status, setStatus] = useState<MonitorStatus | null>(null);
  const [aiHealth, setAiHealth] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [comments, setComments] = useState<SentComment[]>([]);
  const [expandedCommentId, setExpandedCommentId] = useState<number | null>(null);
  const [repliesMap, setRepliesMap] = useState<Map<number, ReplyRecord[]>>(new Map());
  const [commentsLoading, setCommentsLoading] = useState(false);
  const [autoMode, setAutoMode] = useState<AutoModeStatus | null>(null);
  const [autoModeLoading, setAutoModeLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, st, h, am] = await Promise.all([
        xWorkbenchApi.getStats(),
        xWorkbenchApi.getMonitorStatus(),
        xWorkbenchApi.aiHealth().catch(() => ({ ok: false, error: '请求失败' })),
        xWorkbenchApi.getAutoModeStatus().catch(() => null),
      ]);
      setStats(s);
      setStatus(st);
      setAiHealth(h);
      setAutoMode(am);
    } catch (e: any) {
      message.error('加载失败: ' + (e?.message || ''));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadComments = async () => {
    setCommentsLoading(true);
    try {
      const resp = await xWorkbenchApi.listComments({ page: 1, page_size: 50 });
      setComments(resp.items || []);
    } catch (e: any) {
      message.error('加载评论失败: ' + (e?.message || ''));
    } finally {
      setCommentsLoading(false);
    }
  };

  const loadReplies = async (sent_comment_id: number) => {
    if (repliesMap.has(sent_comment_id)) {
      setExpandedCommentId(expandedCommentId === sent_comment_id ? null : sent_comment_id);
      return;
    }
    try {
      const resp = await xWorkbenchApi.listReplies(sent_comment_id);
      setRepliesMap(prev => new Map(prev).set(sent_comment_id, resp.items || []));
      setExpandedCommentId(sent_comment_id);
    } catch (e: any) {
      message.error('加载回复失败: ' + (e?.message || ''));
    }
  };

  useEffect(() => {
    load();
  }, [load]);

  const toggleMonitor = async (start: boolean) => {
    try {
      if (start) {
        await xWorkbenchApi.startMonitor();
        message.success('监控已启动');
      } else {
        await xWorkbenchApi.stopMonitor();
        message.success('监控已停止');
      }
      load();
    } catch (e: any) {
      message.error('操作失败: ' + (e?.message || ''));
    }
  };

  const checkNow = async () => {
    try {
      await xWorkbenchApi.checkNow();
      message.success('已触发一次检查');
      load();
    } catch (e: any) {
      message.error('触发失败: ' + (e?.message || ''));
    }
  };

  // ===== 全自动模式 =====
  const toggleAutoMode = async (start: boolean) => {
    setAutoModeLoading(true);
    try {
      if (start) {
        const r = await xWorkbenchApi.startAutoMode();
        if (r.success) {
          message.success('全自动模式已启动');
        } else {
          message.error(r.message || '启动失败');
        }
      } else {
        const r = await xWorkbenchApi.stopAutoMode();
        if (r.success) {
          message.success('全自动模式已停止');
        } else {
          message.error(r.message || '停止失败');
        }
      }
      load();
    } catch (e: any) {
      message.error('操作失败: ' + (e?.message || ''));
    } finally {
      setAutoModeLoading(false);
    }
  };

  // auto mode 状态自动刷新(运行中时每 15s 刷新一次)
  useEffect(() => {
    if (!autoMode?.running) return;
    const t = setInterval(() => {
      xWorkbenchApi.getAutoModeStatus().then(setAutoMode).catch(() => {});
    }, 15000);
    return () => clearInterval(t);
  }, [autoMode?.running]);

  // 阶段中文映射
  const phaseText: Record<string, string> = {
    idle: '空闲',
    starting: '启动中',
    crawling: '爬取热点',
    selecting: '选取帖子',
    commenting: '发送评论',
    monitoring: '监控回复',
    waiting: '等待下一轮',
  };

  const formatTime = (ts: number) => {
    return new Date(ts * 1000).toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  return (
    <Spin spinning={loading}>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic title="已发评论总数" value={stats?.total_sent_comments || 0} prefix={<MessageOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="成功发送" value={stats?.success_sent || 0} prefix={<CheckCircleTwoTone twoToneColor="#52c41a" />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic title="收到回复" value={stats?.total_replies || 0} prefix={<MessageOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="待处理回复"
              value={stats?.pending_replies || 0}
              prefix={<ThunderboltOutlined />}
              valueStyle={{ color: (stats?.pending_replies || 0) > 0 ? '#fa8c16' : undefined }}
            />
          </Card>
        </Col>
      </Row>

      <Collapse defaultActiveKey={['stats']} style={{ marginBottom: 16 }}>
        <Collapse.Panel header="📊 统计明细" key="stats">
          <Row gutter={16}>
            <Col span={12}>
              <Card title="已发评论明细" size="small">
                <List
                  dataSource={[
                    { label: '总数', value: stats?.total_sent_comments || 0, color: '#1DA1F2' },
                    { label: '成功发送', value: stats?.success_sent || 0, color: '#52c41a' },
                    { label: '草稿/失败', value: stats?.draft_or_failed || 0, color: '#ff4d4f' },
                  ]}
                  renderItem={(item) => (
                    <List.Item key={item.label}>
                      <Space>
                        <Badge status="processing" style={{ backgroundColor: item.color }} />
                        <Text style={{ width: 80, display: 'inline-block' }}>{item.label}:</Text>
                        <Text strong style={{ color: item.color }}>{item.value}</Text>
                      </Space>
                    </List.Item>
                  )}
                />
                {stats?.total_sent_comments && stats?.success_sent && (
                  <Progress
                    percent={Math.round((stats.success_sent / stats.total_sent_comments) * 100)}
                    strokeColor="#52c41a"
                    size="small"
                    style={{ marginTop: 12 }}
                  />
                )}
              </Card>
            </Col>
            <Col span={12}>
              <Card title="回复明细" size="small">
                <List
                  dataSource={[
                    { label: '收到回复', value: stats?.total_replies || 0, color: '#1DA1F2' },
                    { label: 'AI 已回复', value: stats?.auto_replied || 0, color: '#722ED1' },
                    { label: '待处理回复', value: stats?.pending_replies || 0, color: '#fa8c16' },
                  ]}
                  renderItem={(item) => (
                    <List.Item key={item.label}>
                      <Space>
                        <Badge status="processing" style={{ backgroundColor: item.color }} />
                        <Text style={{ width: 80, display: 'inline-block' }}>{item.label}:</Text>
                        <Text strong style={{ color: item.color }}>{item.value}</Text>
                      </Space>
                    </List.Item>
                  )}
                />
                {stats?.total_replies && stats?.auto_replied && (
                  <Progress
                    percent={Math.round((stats.auto_replied / stats.total_replies) * 100)}
                    strokeColor="#722ED1"
                    size="small"
                    style={{ marginTop: 12 }}
                  />
                )}
              </Card>
            </Col>
          </Row>
        </Collapse.Panel>

        <Collapse.Panel header={`💬 评论列表 (${comments.length}条)`} key="comments">
          <Space direction="vertical" style={{ width: '100%' }}>
            <Button type="primary" icon={<ReloadOutlined />} onClick={loadComments} loading={commentsLoading}>
              刷新评论列表
            </Button>
            {comments.length === 0 ? (
              <Empty description="暂无评论数据" />
            ) : (
              <List
                dataSource={comments}
                renderItem={(comment) => (
                  <Card
                    size="small"
                    extra={
                      <Button
                        type="link"
                        icon={<DownOutlined />}
                        onClick={() => loadReplies(comment.id)}
                      >
                        {expandedCommentId === comment.id ? '收起' : `查看回复(${comment.reply_count})`}
                      </Button>
                    }
                    style={{ marginBottom: 8 }}
                  >
                    <Space direction="vertical" style={{ width: '100%' }}>
                      <Row>
                        <Col span={20}>
                          <Text strong>{comment.comment_content}</Text>
                        </Col>
                        <Col span={4} style={{ textAlign: 'right' }}>
                          <Tag color={comment.sent_status === 'success' ? 'green' : 'red'}>
                            {comment.sent_status === 'success' ? '成功' : comment.sent_status === 'draft' ? '草稿' : '失败'}
                          </Tag>
                        </Col>
                      </Row>
                      <Row style={{ fontSize: 12, color: '#999' }}>
                        <Col span={8}>@ {comment.post_username}</Col>
                        <Col span={8}>{formatTime(comment.sent_at)}</Col>
                        <Col span={8} style={{ textAlign: 'right' }}>
                          <Text>AI 回复: {comment.auto_replied_count} / {comment.reply_count}</Text>
                        </Col>
                      </Row>

                      {expandedCommentId === comment.id && (
                        <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px dashed #e8e8e8' }}>
                          {repliesMap.get(comment.id)?.length === 0 ? (
                            <Empty description="暂无回复" />
                          ) : (
                            <List
                              dataSource={repliesMap.get(comment.id)}
                              renderItem={(reply) => (
                                <List.Item key={reply.id} style={{ padding: '8px 0' }}>
                                  <Space direction="vertical" style={{ width: '100%' }}>
                                    <Row>
                                      <Col span={4}>
                                        <Avatar size="small">
                                          {reply.replier_username?.charAt(0).toUpperCase()}
                                        </Avatar>
                                      </Col>
                                      <Col span={20}>
                                        <Text strong>@{reply.replier_username}</Text>
                                        <Text style={{ marginLeft: 8, color: '#666' }}>{reply.reply_content}</Text>
                                      </Col>
                                    </Row>
                                    <Row style={{ fontSize: 12, color: '#999', paddingLeft: 44 }}>
                                      <Col span={12}>
                                        <Tag color={reply.auto_reply_status === 'sent' ? 'purple' : reply.auto_reply_status === 'failed' ? 'red' : 'orange'}>
                                          {reply.auto_reply_status === 'sent' ? 'AI 已回复' : reply.auto_reply_status === 'failed' ? '回复失败' : '待处理'}
                                        </Tag>
                                      </Col>
                                      <Col span={12} style={{ textAlign: 'right' }}>
                                        {reply.auto_reply_content && (
                                          <Tooltip title={reply.auto_reply_content}>
                                            <Text>AI: {reply.auto_reply_content.slice(0, 30)}...</Text>
                                          </Tooltip>
                                        )}
                                      </Col>
                                    </Row>
                                  </Space>
                                </List.Item>
                              )}
                            />
                          )}
                        </div>
                      )}
                    </Space>
                  </Card>
                )}
              />
            )}
          </Space>
        </Collapse.Panel>
      </Collapse>

      <Card
        title={
          <Space>
            <RobotOutlined style={{ color: '#722ED1' }} />
            <span>全自动模式</span>
            {autoMode?.running ? (
              <Badge status="processing" text="运行中" />
            ) : (
              <Badge status="default" text="已停止" />
            )}
          </Space>
        }
        style={{ marginBottom: 16, borderColor: autoMode?.running ? '#722ED1' : undefined }}
        extra={
          <Space>
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              loading={autoModeLoading}
              disabled={autoMode?.running}
              onClick={() => toggleAutoMode(true)}
            >
              启动
            </Button>
            <Button
              danger
              icon={<PauseCircleOutlined />}
              loading={autoModeLoading}
              disabled={!autoMode?.running}
              onClick={() => toggleAutoMode(false)}
            >
              停止
            </Button>
            <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
          </Space>
        }
      >
        <Alert
          type={autoMode?.running ? 'success' : 'info'}
          showIcon
          message={
            autoMode?.running
              ? `全自动模式运行中,当前阶段: ${phaseText[autoMode.current_phase] || autoMode.current_phase}`
              : '一键启动:自动爬热点 → AI 生成评论 → 真实发送 → 监控回复 → AI 自动回复'
          }
          description={
            <Space direction="vertical" size={4} style={{ width: '100%' }}>
              {autoMode?.last_cycle_summary && (
                <Text type="secondary">上一轮: {autoMode.last_cycle_summary}</Text>
              )}
              {autoMode?.running && (
                <Text type="secondary">
                  已运行 {autoMode.total_cycles} 轮 · 成功 {autoMode.total_comments_sent} 条 · 失败 {autoMode.total_comments_failed} 条
                  · 每轮间隔 {autoMode.cycle_interval_seconds}s · 单轮上限 {autoMode.max_posts_per_cycle} 条
                </Text>
              )}
              {autoMode?.error && <Text type="danger">错误: {autoMode.error}</Text>}
              {autoMode && autoMode.last_cycle_at > 0 && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  上轮时间: {formatTime(autoMode.last_cycle_at)}
                  {autoMode.started_at > 0 && ` · 启动于: ${formatTime(autoMode.started_at)}`}
                </Text>
              )}
            </Space>
          }
          style={{ marginBottom: 0 }}
        />
      </Card>

      <Card title="监控服务" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Row>
            <Col span={8}>
              <Text>运行状态: </Text>
              {status?.running ? (
                <Badge status="processing" text="运行中" />
              ) : (
                <Badge status="default" text="已停止" />
              )}
            </Col>
            <Col span={8}>
              <Text>检查间隔: {status?.check_interval || 0} 秒</Text>
            </Col>
            <Col span={8}>
              <Text>每日 AI 回复上限: {status?.daily_limit || 0}</Text>
            </Col>
          </Row>
          <Alert
            type="info"
            showIcon
            message="监控服务持续运行"
            description="为保证评论回复能及时被处理,监控服务会在应用启动时自动启动,异常退出时 watchdog 自动重启。如需手动触发,可点击「立即检查一次」。"
            style={{ marginBottom: 12 }}
          />
          <Space>
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              disabled={status?.running}
              onClick={() => toggleMonitor(true)}
            >
              {status?.running ? '监控运行中' : '启动监控'}
            </Button>
            <Button icon={<ReloadOutlined />} onClick={checkNow} disabled={!status?.running}>
              立即检查一次
            </Button>
            <Button icon={<ReloadOutlined />} onClick={load}>
              刷新状态
            </Button>
          </Space>
        </Space>
      </Card>

      <Card title="AI Agent 健康">
        {aiHealth?.ok ? (
          <Alert
            type="success"
            showIcon
            message={`AI 服务正常 (${aiHealth.model})`}
            description={`Base URL: ${aiHealth.base_url}`}
          />
        ) : (
          <Alert
            type="error"
            showIcon
            message="AI 服务不可用"
            description={aiHealth?.error || '请检查 .env 中 X_TWITTER_AI_API_KEY 和 X_TWITTER_AI_BASE_URL'}
          />
        )}
      </Card>
    </Spin>
  );
};

export default MonitorPanel;
