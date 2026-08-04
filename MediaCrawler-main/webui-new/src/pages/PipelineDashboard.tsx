import { message } from '../utils/antdMessage';
import React, { useEffect, useState, useCallback, useRef } from 'react';
import {
  Card, Table, Tag, Button, Space, Select, Row, Col, Statistic, Empty, Spin,
  Form, Input, Typography, Divider, Steps, Alert,
} from 'antd';
import {
  ReloadOutlined, ThunderboltOutlined, PlayCircleOutlined,
  ExperimentOutlined, VideoCameraOutlined, AuditOutlined,
  CloudUploadOutlined, MessageOutlined, CheckCircleOutlined,
} from '@ant-design/icons';
import { unifiedPipelineApi, videoConfigApi } from '../api/prdGap';

const { TextArea } = Input;
const { Text } = Typography;

// 流水线状态 → Steps 当前步索引映射
const STATUS_TO_STEP: Record<string, number> = {
  pending: 0,
  extracting: 1,
  generating: 2,
  reviewing: 2,       // 仍在生成阶段后，等待复核
  scheduling: 4,
  published: 4,       // 已发布，互动进行中
  interacting: 5,
  completed: 5,
  failed: -1,
};

const STATUS_LABEL: Record<string, { text: string; color: string }> = {
  pending: { text: '待启动', color: 'default' },
  extracting: { text: '提示词处理', color: 'processing' },
  generating: { text: '视频生成', color: 'processing' },
  reviewing: { text: '人工复核', color: 'warning' },
  scheduling: { text: '发布调度', color: 'processing' },
  published: { text: '已发布', color: 'success' },
  interacting: { text: '互动中', color: 'processing' },
  completed: { text: '已完成', color: 'success' },
  failed: { text: '失败', color: 'error' },
};

const SOURCE_LABEL: Record<string, string> = {
  hotspot_url: '热点视频URL',
  prompt_id: '提示词库',
  manual_text: '手动文案',
};

const PLATFORM_OPTIONS = ['douyin', 'xiaohongshu', 'bilibili', 'weibo', 'zhihu', 'kuaishou'];

const PipelineDashboard: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [items, setItems] = useState<any[]>([]);
  const [videoConfigs, setVideoConfigs] = useState<any[]>([]);
  const [currentPipeline, setCurrentPipeline] = useState<any>(null);
  const [form] = Form.useForm();
  const pollRef = useRef<any>(null);

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const res = await unifiedPipelineApi.list(20);
      const data = res?.data || res || {};
      setItems(data.items || []);
    } catch (e) {
      console.error('fetch pipelines failed', e);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchVideoConfigs = useCallback(async () => {
    try {
      const res = await videoConfigApi.list(undefined, true);
      const data = res?.data || res || {};
      setVideoConfigs(data.items || []);
    } catch (e) {
      console.error('fetch video configs failed', e);
    }
  }, []);

  useEffect(() => {
    fetchList();
    fetchVideoConfigs();
  }, [fetchList, fetchVideoConfigs]);

  // 轮询当前流水线状态
  const startPolling = useCallback((pipelineId: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const res = await unifiedPipelineApi.get(pipelineId);
        const data = res?.data || res;
        if (data) {
          setCurrentPipeline(data);
          // 终态停止轮询
          if (['completed', 'failed'].includes(data.status)) {
            if (pollRef.current) {
              clearInterval(pollRef.current);
              pollRef.current = null;
            }
            fetchList();
          }
        }
      } catch (e) {
        console.error('poll pipeline status failed', e);
      }
    }, 3000);
  }, [fetchList]);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const handleRun = async () => {
    try {
      const values = await form.validateFields();
      setRunning(true);
      setCurrentPipeline(null);
      const res = await unifiedPipelineApi.run({
        source_type: values.source_type,
        source_value: values.source_value,
        video_config_id: values.video_config_id || '',
        publish_platforms: values.publish_platforms || ['douyin'],
      });
      const data = res?.data || res;
      if (data?.pipeline_id) {
        message.success(`流水线已启动，进入人工复核环节`);
        startPolling(data.pipeline_id);
        fetchList();
      } else {
        message.error(data?.error || res?.message || '启动失败');
      }
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error(e?.message || '启动失败');
    } finally {
      setRunning(false);
    }
  };

  const columns = [
    {
      title: '流水线ID', dataIndex: 'pipeline_id', width: 180, ellipsis: true,
      render: (v: string) => <Text copyable={{ text: v }} style={{ fontSize: 12 }}>{v?.slice(0, 16)}...</Text>,
    },
    {
      title: '状态', dataIndex: 'status', width: 110,
      render: (v: string) => {
        const cfg = STATUS_LABEL[v] || { text: v, color: 'default' };
        return <Tag color={cfg.color}>{cfg.text}</Tag>;
      },
    },
    {
      title: '输入源', dataIndex: 'source_type', width: 110,
      render: (v: string) => SOURCE_LABEL[v] || v,
    },
    {
      title: '输入内容', dataIndex: 'source_value', ellipsis: true, width: 200,
      render: (v: string) => v?.slice(0, 40) || '-',
    },
    {
      title: '复核', dataIndex: 'review_id', width: 100,
      render: (v: string) => v ? <Tag color="warning">待复核</Tag> : '-',
    },
    {
      title: '发布任务', dataIndex: 'schedule_task_id', width: 100,
      render: (v: string) => v ? <Tag color="processing">{v}</Tag> : '-',
    },
    {
      title: '互动', dataIndex: 'interaction_task_id', width: 100,
      render: (v: string) => v ? <Tag color="success">已触发</Tag> : '-',
    },
    {
      title: '创建时间', dataIndex: 'created_at', width: 160,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作', width: 100, fixed: 'right' as const,
      render: (_: any, record: any) => (
        <Button size="small" onClick={() => { setCurrentPipeline(record); startPolling(record.pipeline_id); }}>
          查看进度
        </Button>
      ),
    },
  ];

  // 当前流水线的步骤进度
  const renderSteps = () => {
    if (!currentPipeline) return null;
    const status = currentPipeline.status;
    const current = STATUS_TO_STEP[status] ?? 0;
    const isError = status === 'failed';

    const steps = [
      { title: '提示词库', icon: <ExperimentOutlined />, desc: currentPipeline.prompt_id ? `已沉淀 ${currentPipeline.prompt_id.slice(0, 12)}` : '手动文案' },
      { title: '视频参数', icon: <VideoCameraOutlined />, desc: currentPipeline.video_config_id ? '已加载配置' : '默认配置' },
      { title: '视频生成', icon: <PlayCircleOutlined />, desc: currentPipeline.video_url ? '已生成' : '待生成' },
      { title: '人工复核', icon: <AuditOutlined />, desc: currentPipeline.review_id ? `复核 ${currentPipeline.review_id.slice(0, 12)}` : '待复核' },
      { title: '发布调度', icon: <CloudUploadOutlined />, desc: currentPipeline.schedule_task_id ? `任务#${currentPipeline.schedule_task_id}` : '待调度' },
      { title: '话术互动', icon: <MessageOutlined />, desc: currentPipeline.interaction_task_id ? '已触发' : '待触发' },
    ];

    return (
      <Card title="流水线进度" size="small" style={{ marginBottom: 16 }}
        extra={isError ? <Tag color="error">失败</Tag> : status === 'completed' ? <Tag color="success"><CheckCircleOutlined /> 已完成</Tag> : <Spin size="small" />}>
        <Steps
          current={current}
          status={isError ? 'error' : 'process'}
          size="small"
          items={steps.map(s => ({ title: s.title, description: s.desc, icon: s.icon }))}
        />
        {isError && currentPipeline.error_message && (
          <Alert style={{ marginTop: 12 }} type="error" showIcon
            message="流水线执行失败" description={currentPipeline.error_message} />
        )}
        {currentPipeline.video_url && (
          <div style={{ marginTop: 12 }}>
            <Text type="secondary">生成视频：</Text>
            <Text copyable style={{ fontSize: 12, wordBreak: 'break-all' }}>{currentPipeline.video_url}</Text>
          </div>
        )}
      </Card>
    );
  };

  return (
    <div style={{ padding: 24 }}>
      <Card
        title={
          <Space>
            <ThunderboltOutlined />
            <span>五功能自动化流水线</span>
          </Space>
        }
        extra={<Button icon={<ReloadOutlined />} onClick={fetchList} size="small">刷新</Button>}
      >
        <Alert
          style={{ marginBottom: 16 }}
          type="info" showIcon
          message="完整流水线：提示词库 → 视频参数配置 → 数字人视频生成 → 人工复核 → 发布调度管理 → 话术库互动"
          description="视频生成后将自动进入人工复核队列，复核通过后自动创建定时发布任务，发布完成后自动从话术库选取话术触发互动。"
        />

        <Row gutter={16}>
          {/* 左侧：启动表单 */}
          <Col span={10}>
            <Card title="启动流水线" size="small">
              <Form form={form} layout="vertical" initialValues={{
                source_type: 'manual_text',
                publish_platforms: ['douyin'],
              }}>
                <Form.Item label="输入源类型" name="source_type" rules={[{ required: true }]}>
                  <Select>
                    <Select.Option value="manual_text">手动文案</Select.Option>
                    <Select.Option value="hotspot_url">热点视频URL</Select.Option>
                    <Select.Option value="prompt_id">提示词库ID</Select.Option>
                  </Select>
                </Form.Item>
                <Form.Item label="输入内容（文案/URL/提示词ID）" name="source_value" rules={[{ required: true, message: '请输入内容' }]}>
                  <TextArea rows={3} placeholder="输入口播文案 / 热点视频URL / 提示词库ID" />
                </Form.Item>
                <Form.Item label="视频参数配置" name="video_config_id">
                  <Select allowClear placeholder="不选则用默认配置">
                    {videoConfigs.map(c => (
                      <Select.Option key={c.config_id} value={c.config_id}>
                        {c.name} ({c.resolution}/{c.aspect_ratio})
                      </Select.Option>
                    ))}
                  </Select>
                </Form.Item>
                <Form.Item label="目标发布平台" name="publish_platforms" rules={[{ required: true }]}>
                  <Select mode="multiple" placeholder="选择发布平台">
                    {PLATFORM_OPTIONS.map(p => (
                      <Select.Option key={p} value={p}>{p}</Select.Option>
                    ))}
                  </Select>
                </Form.Item>
                <Button type="primary" icon={<ThunderboltOutlined />} loading={running} onClick={handleRun} block>
                  启动完整流水线
                </Button>
              </Form>
            </Card>
          </Col>

          {/* 右侧：进度看板 */}
          <Col span={14}>
            {currentPipeline ? renderSteps() : (
              <Card size="small" style={{ marginBottom: 16 }}>
                <Empty description="启动流水线或点击列表「查看进度」查看实时状态" />
              </Card>
            )}
            <Row gutter={8}>
              <Col span={6}>
                <Card size="small"><Statistic title="总流水线" value={items.length} /></Card>
              </Col>
              <Col span={6}>
                <Card size="small"><Statistic title="待复核" value={items.filter(i => i.status === 'reviewing').length} valueStyle={{ color: '#faad14' }} /></Card>
              </Col>
              <Col span={6}>
                <Card size="small"><Statistic title="发布中" value={items.filter(i => ['scheduling', 'published'].includes(i.status)).length} valueStyle={{ color: '#1677ff' }} /></Card>
              </Col>
              <Col span={6}>
                <Card size="small"><Statistic title="已完成" value={items.filter(i => i.status === 'completed').length} valueStyle={{ color: '#52c41a' }} /></Card>
              </Col>
            </Row>
          </Col>
        </Row>

        <Divider />

        <Table
          columns={columns}
          dataSource={items}
          rowKey="pipeline_id"
          loading={loading}
          size="small"
          scroll={{ x: 1200 }}
          pagination={{ pageSize: 10, showSizeChanger: false }}
        />
      </Card>
    </div>
  );
};

export default PipelineDashboard;
