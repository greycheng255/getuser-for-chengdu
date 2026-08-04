import { message } from '../utils/antdMessage';
import React, { useEffect, useState, useCallback } from 'react';
import { Card, Table, Tag, Button, Space, Modal, Form, Input, Select, Row, Col, Statistic, Empty, Spin, Descriptions, Tooltip, Typography } from 'antd';
import {
  ReloadOutlined, PlusOutlined, SearchOutlined, ThunderboltOutlined,
  ExperimentOutlined, FileTextOutlined, CopyOutlined, RocketOutlined,
} from '@ant-design/icons';
import { promptLibraryApi, pipelineApi, unifiedPipelineApi } from '../api/prdGap';

const { TextArea } = Input;
const { Option } = Select;
const { Text } = Typography;

const PromptLibrary: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<any[]>([]);
  const [search, setSearch] = useState<{ keyword?: string; category?: string }>({});
  const [detail, setDetail] = useState<any>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [pipelineOpen, setPipelineOpen] = useState(false);
  const [pipelineResult, setPipelineResult] = useState<any>(null);
  const [pipelineLoading, setPipelineLoading] = useState(false);
  const [form] = Form.useForm();
  const [pipelineForm] = Form.useForm();

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await promptLibraryApi.search({ ...search, limit: 100 });
      const data = res?.data || res || [];
      setItems(Array.isArray(data) ? data : data.items || []);
    } catch (e) {
      console.error('fetch prompts failed', e);
    } finally {
      setLoading(false);
    }
  }, [search]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      const tags = values.tags ? (Array.isArray(values.tags) ? values.tags : values.tags.split(/[,，]/).map((s: string) => s.trim()).filter(Boolean)) : [];
      const styleKeywords = values.style_keywords ? (Array.isArray(values.style_keywords) ? values.style_keywords : values.style_keywords.split(/[,，]/).map((s: string) => s.trim()).filter(Boolean)) : [];
      const res = await promptLibraryApi.create({ ...values, tags, style_keywords: styleKeywords });
      message.success('创建成功');
      setCreateOpen(false);
      form.resetFields();
      fetchData();
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error('创建失败');
    }
  };

  const handleVariant = async (promptId: string) => {
    try {
      const res = await promptLibraryApi.variant(promptId);
      const v = res?.data?.variant_prompt || res?.variant_prompt;
      if (v) {
        Modal.info({
          title: '提示词变体',
          width: 600,
          content: <div style={{ wordBreak: 'break-all', overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' }}>{v}</div>,
        });
      } else {
        message.warning('生成失败');
      }
    } catch {
      message.error('生成失败');
    }
  };

  const handlePipeline = async () => {
    try {
      const values = await pipelineForm.validateFields();
      setPipelineLoading(true);
      setPipelineResult(null);
      const res = await pipelineApi.full(values);
      setPipelineResult(res?.data || res || null);
      message.success('完整链路执行完成');
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error('执行失败');
    } finally {
      setPipelineLoading(false);
    }
  };

  const columns = [
    {
      title: '标题', dataIndex: 'title',
      render: (v: string, r: any) => (
        <a onClick={() => setDetail(r)} style={{ wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
          {v || r.prompt_id?.slice(0, 12)}
        </a>
      ),
    },
    {
      title: '分类', dataIndex: 'category', width: 110,
      render: (v: string) => v ? <Tag color="blue">{v}</Tag> : '-',
    },
    {
      title: '风格关键词', dataIndex: 'style_keywords', width: 200,
      render: (v: string[]) => (
        <span style={{ wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
          {v?.length ? v.join('、') : '-'}
        </span>
      ),
    },
    {
      title: '标签', dataIndex: 'tags', width: 160,
      render: (v: string[]) => v?.length ? v.map((t) => <Tag key={t}>{t}</Tag>) : '-',
    },
    {
      title: '创建时间', dataIndex: 'created_at', width: 160,
      render: (v: any) => {
        if (!v) return '-';
        const d = typeof v === 'number' ? new Date(v > 1e12 ? v : v * 1000) : new Date(v);
        return d.toLocaleString('zh-CN');
      },
    },
    {
      title: '操作', width: 200,
      render: (_: any, r: any) => (
        <Space size="small">
          <Tooltip title="生成变体">
            <Button size="small" type="text" icon={<ExperimentOutlined />} onClick={() => handleVariant(r.prompt_id)} />
          </Tooltip>
          <Button
            size="small"
            type="text"
            icon={<CopyOutlined />}
            onClick={() => { navigator.clipboard?.writeText(r.prompt_text); message.success('已复制'); }}
          />
          <Tooltip title="启动完整流水线（提示词→视频生成→人工复核→发布调度→话术互动）">
            <Button
              size="small"
              type="primary"
              ghost
              icon={<RocketOutlined />}
              onClick={() => handleRunUnifiedPipeline(r.prompt_id, r.title)}
            >
              流水线
            </Button>
          </Tooltip>
        </Space>
      ),
    },
  ];

  const handleRunUnifiedPipeline = async (promptId: string, title: string) => {
    try {
      const res = await unifiedPipelineApi.run({
        source_type: 'prompt_id',
        source_value: promptId,
        publish_platforms: ['douyin'],
      });
      const data = res?.data || res;
      if (data?.pipeline_id) {
        message.success(`流水线已启动，视频生成后将进入人工复核队列`);
        Modal.info({
          title: '流水线已启动',
          width: 520,
          content: (
            <div style={{ wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
              <p>提示词「{title}」已进入完整自动化流水线。</p>
              <p>流水线ID：<Text code copyable>{data.pipeline_id}</Text></p>
              <p>下一步：视频生成完成后，请前往「人工复核」队列审核。</p>
              <p>审核通过后将自动创建定时发布任务，发布完成后自动触发话术库互动。</p>
            </div>
          ),
        });
      } else {
        message.error(data?.error || res?.message || '启动失败');
      }
    } catch (e: any) {
      message.error(e?.message || '启动流水线失败');
    }
  };

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <h3 style={{ margin: 0 }}>
            <FileTextOutlined style={{ color: '#1677ff', marginRight: 8 }} />
            提示词库
          </h3>
        </Col>
        <Col>
          <Space>
            <Button type="primary" icon={<ThunderboltOutlined />} onClick={() => { setPipelineOpen(true); setPipelineResult(null); pipelineForm.resetFields(); }}>
              一键完整链路
            </Button>
            <Button icon={<PlusOutlined />} onClick={() => { setCreateOpen(true); form.resetFields(); }}>新增提示词</Button>
            <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>刷新</Button>
          </Space>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={8}>
          <Card size="small"><Statistic title="提示词总数" value={items.length} prefix={<FileTextOutlined />} /></Card>
        </Col>
        <Col xs={12} sm={8}>
          <Card size="small"><Statistic title="分类数" value={new Set(items.map((i) => i.category).filter(Boolean)).size} /></Card>
        </Col>
        <Col xs={12} sm={8}>
          <Card size="small"><Statistic title="来源视频数" value={new Set(items.map((i) => i.source_video_url).filter(Boolean)).size} /></Card>
        </Col>
      </Row>

      <Card>
        <Space style={{ marginBottom: 16 }} wrap>
          <Input.Search
            allowClear
            placeholder="搜索关键词"
            style={{ width: 240 }}
            onSearch={(v) => setSearch({ ...search, keyword: v })}
          />
          <Input
            allowClear
            placeholder="分类"
            style={{ width: 150 }}
            onPressEnter={(e) => setSearch({ ...search, category: (e.target as HTMLInputElement).value })}
          />
        </Space>

        <Spin spinning={loading}>
          {items.length === 0 && !loading ? (
            <Empty description="暂无提示词">
              <Button type="primary" icon={<PlusOutlined />} onClick={() => { setCreateOpen(true); form.resetFields(); }}>新增提示词</Button>
            </Empty>
          ) : (
            <Table rowKey="prompt_id" columns={columns} dataSource={items} size="middle" pagination={{ pageSize: 15 }} scroll={{ x: 1000 }} />
          )}
        </Spin>
      </Card>

      <Modal
        title="提示词详情"
        open={!!detail}
        onCancel={() => setDetail(null)}
        footer={null}
        width={680}
      >
        {detail && (
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="标题">{detail.title}</Descriptions.Item>
            <Descriptions.Item label="分类">{detail.category || '-'}</Descriptions.Item>
            <Descriptions.Item label="提示词文本">
              <div style={{ wordBreak: 'break-all', overflowWrap: 'anywhere', whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto' }}>
                {detail.prompt_text}
              </div>
            </Descriptions.Item>
            <Descriptions.Item label="风格关键词">{detail.style_keywords?.join('、') || '-'}</Descriptions.Item>
            <Descriptions.Item label="标签">{detail.tags?.join('、') || '-'}</Descriptions.Item>
            <Descriptions.Item label="来源视频">
              <span style={{ wordBreak: 'break-all', overflowWrap: 'anywhere' }}>{detail.source_video_url || '-'}</span>
            </Descriptions.Item>
            <Descriptions.Item label="关联分镜">{detail.storyboard_id || '-'}</Descriptions.Item>
          </Descriptions>
        )}
      </Modal>

      <Modal
        title="新增提示词"
        open={createOpen}
        onOk={handleCreate}
        onCancel={() => setCreateOpen(false)}
        okText="保存"
        cancelText="取消"
        width={640}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="title" label="标题" rules={[{ required: true }]}>
            <Input placeholder="如：科技解说-极简风格" />
          </Form.Item>
          <Form.Item name="category" label="分类">
            <Input placeholder="如：科技、生活、职场" />
          </Form.Item>
          <Form.Item name="prompt_text" label="提示词文本" rules={[{ required: true }]}>
            <TextArea rows={6} placeholder="完整的提示词内容..." />
          </Form.Item>
          <Form.Item name="style_keywords" label="风格关键词（逗号分隔）">
            <Input placeholder="如：极简,科技感,快节奏" />
          </Form.Item>
          <Form.Item name="tags" label="标签（逗号分隔）">
            <Input placeholder="如：竖屏,30秒,解说" />
          </Form.Item>
          <Form.Item name="source_video_url" label="来源视频URL">
            <Input placeholder="https://..." />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="一键完整链路（热点视频 → 提示词/分镜 → 视频生成 → 审核 → 分发）"
        open={pipelineOpen}
        onCancel={() => setPipelineOpen(false)}
        footer={null}
        width={680}
      >
        <Form form={pipelineForm} layout="vertical">
          <Form.Item name="hotspot_video_url" label="热点视频URL" rules={[{ required: true }]}>
            <Input placeholder="https://..." />
          </Form.Item>
          <Form.Item name="hotspot_id" label="热点ID（可选）">
            <Input placeholder="关联热点库ID" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="video_config_id" label="视频参数配置ID（可选）">
                <Input placeholder="如：preset_vertical_30s" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="publish_platforms" label="发布平台（逗号分隔）">
                <Input placeholder="如：x,douyin" />
              </Form.Item>
            </Col>
          </Row>
          <Button type="primary" icon={<ThunderboltOutlined />} loading={pipelineLoading} onClick={handlePipeline} block>
            执行完整链路
          </Button>
        </Form>
        {pipelineResult && (
          <Card size="small" title="执行结果" style={{ marginTop: 16 }}>
            <Descriptions column={1} size="small">
              <Descriptions.Item label="成功">{String(pipelineResult.success)}</Descriptions.Item>
              {pipelineResult.prompt_id && <Descriptions.Item label="提示词ID">{pipelineResult.prompt_id}</Descriptions.Item>}
              {pipelineResult.storyboard_id && <Descriptions.Item label="分镜ID">{pipelineResult.storyboard_id}</Descriptions.Item>}
              {pipelineResult.video_url && (
                <Descriptions.Item label="视频URL">
                  <span style={{ wordBreak: 'break-all', overflowWrap: 'anywhere' }}>{pipelineResult.video_url}</span>
                </Descriptions.Item>
              )}
              {pipelineResult.message && (
                <Descriptions.Item label="消息">
                  <span style={{ wordBreak: 'break-all', overflowWrap: 'anywhere' }}>{pipelineResult.message}</span>
                </Descriptions.Item>
              )}
            </Descriptions>
          </Card>
        )}
      </Modal>
    </div>
  );
};

export default PromptLibrary;
