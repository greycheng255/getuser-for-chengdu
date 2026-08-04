import { message } from '../utils/antdMessage';
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { Card, Table, Tag, Button, Space, Select, Row, Col, Empty, Spin, Tabs, Modal, Input, Form, DatePicker, Tooltip, Alert, Descriptions, Typography, Progress } from 'antd';
import {
  ReloadOutlined, SendOutlined, RocketOutlined, CloudUploadOutlined,
  CheckCircleOutlined, CloseCircleOutlined, EyeOutlined,
  GlobalOutlined, FileTextOutlined, ThunderboltOutlined, EditOutlined,
} from '@ant-design/icons';
import { useLocation } from 'react-router-dom';
import { publishApi, accountGroupApi } from '../api/prdGap';
import { autoPipelineApi, type PipelineTask, type PlatformCapability } from '../api/autoPipeline';
import { TaskCard } from './xworkbench/PipelineProgressModal';
import { getPlatformTheme } from '../constants/platformThemes';

// 从视频拆解 Modal / 评论撰写 Modal 跳转过来时携带的预填数据
interface PublishPrefill {
  from_breakdown?: boolean;
  source_post_id?: string;
  video_url?: string;
  content?: string;
  platform?: string;
  title?: string;
}

// 平台别名 → 后端平台标准名（用于把拆解平台的别名匹配到发布中心平台列表）
const PREFILL_PLATFORM_ALIASES: Record<string, string[]> = {
  x: ['x', 'x_twitter', 'tw', 'twitter'],
  youtube: ['youtube', 'yt'],
  douyin: ['douyin', 'dy'],
  bilibili: ['bilibili', 'bili'],
  kuaishou: ['kuaishou', 'ks'],
  xiaohongshu: ['xiaohongshu', 'xhs', 'redbook'],
  weibo: ['weibo', 'wb'],
  zhihu: ['zhihu'],
  tiktok: ['tiktok', 'tt'],
  instagram: ['instagram', 'ig'],
  facebook: ['facebook', 'fb'],
};

// 在已加载的平台列表里找到与预填平台匹配的标准名
const matchPrefillPlatform = (platforms: any[], prefillPlatform?: string): string | null => {
  if (!prefillPlatform) return null;
  // 1. 精确匹配
  const exact = platforms.find((p) => p.name === prefillPlatform);
  if (exact) return exact.name;
  // 2. 别名匹配
  const aliases = PREFILL_PLATFORM_ALIASES[prefillPlatform];
  if (aliases) {
    for (const alias of aliases) {
      const m = platforms.find((p) => p.name === alias || p.name === alias.replace('_', ''));
      if (m) return m.name;
    }
  }
  // 3. 包含匹配（如 prefill=x_twitter，平台名含 x_twitter）
  const contains = platforms.find((p) => p.name.includes(prefillPlatform) || prefillPlatform.includes(p.name));
  return contains ? contains.name : null;
};

const { Option } = Select;
const { TextArea } = Input;
const { RangePicker } = DatePicker;
const { Text } = Typography;

// 平台颜色映射 (覆盖后端 PLATFORM_METADATA 全部平台 + 常见别名)
const PLATFORM_COLOR: Record<string, string> = {
  douyin: 'red',
  xiaohongshu: 'magenta',
  xhs: 'magenta',
  bilibili: 'cyan',
  weibo: 'orange',
  zhihu: 'blue',
  x_twitter: 'black',
  x: 'black',
  x_twitter_publisher: 'black',
  kuaishou: 'volcano',
  wechat_public: 'green',
  wechat_channels: 'green',
  toutiao: 'gold',
  tiktok: 'volcano',
  instagram: 'purple',
  youtube: 'red',
  facebook: 'geekblue',
};

// 分组中文名
const GROUP_LABEL: Record<string, string> = {
  domestic_new: '国内新号',
  domestic_mature: '国内成熟号',
  overseas_us: '海外美国',
  overseas_eu: '海外欧洲',
  overseas_sea: '海外东南亚',
};

// 发布记录状态映射
const RECORD_STATUS: Record<string, { color: string; text: string }> = {
  success: { color: 'green', text: '成功' },
  failed: { color: 'red', text: '失败' },
  skipped: { color: 'orange', text: '跳过' },
  pending: { color: 'gold', text: '待发布' },
  publishing: { color: 'blue', text: '发布中' },
};

// 平台显示组件: 优先用 platformThemes 的颜色/图标, fallback 到后端 emoji
const PlatformTag: React.FC<{ platform: string; nameCn?: string; icon?: string }> = ({
  platform,
  nameCn,
  icon,
}) => {
  const theme = getPlatformTheme(platform);
  const color = PLATFORM_COLOR[platform] || 'default';
  const label = nameCn || theme.name || platform;
  return (
    <Tag color={color} icon={icon ? <span style={{ marginRight: 2 }}>{icon}</span> : undefined}>
      {label}
    </Tag>
  );
};

const PublishCenter: React.FC = () => {
  const [activeTab, setActiveTab] = useState('multi');
  const location = useLocation();
  // 从视频拆解 / 评论撰写 Modal 跳转过来时携带的预填数据（来自 location.state）
  const prefill = ((location.state || {}) as PublishPrefill) || {};
  const hasPrefill = Boolean(prefill.from_breakdown);

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <h3 style={{ margin: 0 }}>
            <CloudUploadOutlined style={{ color: '#1677ff', marginRight: 8 }} />
            发布中心
          </h3>
        </Col>
      </Row>

      {hasPrefill && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="数据已从「视频拆解」自动填充"
          description={
            <span>
              已为你预填标题、正文、视频路径与目标平台。如需账号分组、风控、定时等高级配置，请在此调整后发布。
              {prefill.source_post_id && (
                <Tag color="blue" style={{ marginLeft: 8 }}>来源帖子: {prefill.source_post_id}</Tag>
              )}
            </span>
          }
        />
      )}

      <Card>
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: 'multi',
              label: (
                <span>
                  <RocketOutlined />
                  多平台发布
                </span>
              ),
              children: <MultiPublishPanel prefill={hasPrefill ? prefill : undefined} />,
            },
            {
              key: 'single',
              label: (
                <span>
                  <SendOutlined />
                  单平台发布
                </span>
              ),
              children: <SinglePublishPanel prefill={hasPrefill ? prefill : undefined} />,
            },
            {
              key: 'pipeline-tasks',
              label: (
                <span>
                  <ThunderboltOutlined />
                  流水线任务
                </span>
              ),
              children: <PipelineTasksPanel />,
            },
            {
              key: 'records',
              label: (
                <span>
                  <FileTextOutlined />
                  发布记录
                </span>
              ),
              children: <RecordsPanel />,
            },
          ]}
        />
      </Card>
    </div>
  );
};

// ==================== 多平台发布面板 ====================
const MultiPublishPanel: React.FC<{ prefill?: PublishPrefill }> = ({ prefill }) => {
  const [platforms, setPlatforms] = useState<any[]>([]);
  const [groups, setGroups] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [form] = Form.useForm();

  const fetchInit = useCallback(async () => {
    setLoading(true);
    try {
      const [platRes, groupRes] = await Promise.all([
        publishApi.listPlatforms(),
        accountGroupApi.groups().catch(() => ({ data: { groups: [] } })),
      ]);
      const platData = platRes?.data || platRes || {};
      // 过滤掉别名平台 x_twitter_publisher
      const list = (platData.platforms || []).filter(
        (p: any) => p.name !== 'x_twitter_publisher'
      );
      setPlatforms(list);
      const groupData = groupRes?.data || groupRes || {};
      setGroups(groupData.groups || []);
    } catch (e) {
      console.error('fetch platforms failed', e);
      message.error('加载平台列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchInit();
  }, [fetchInit]);

  // 平台列表加载完成后，应用从视频拆解跳转携带的预填数据
  useEffect(() => {
    if (!prefill?.from_breakdown) return;
    if (platforms.length === 0) return; // 等平台列表加载完
    const matchedPlatform = matchPrefillPlatform(platforms, prefill.platform);
    form.setFieldsValue({
      title: prefill.title || '',
      content: prefill.content || '',
      video_path: prefill.video_url || '',
      ...(matchedPlatform ? { target_platforms: [matchedPlatform] } : {}),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill, platforms]);

  const handlePublish = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      const keywords = (values.keywords || '')
        .split(/[,，\n]/)
        .map((s: string) => s.trim())
        .filter(Boolean);
      const payload: any = {
        title: values.title,
        content: values.content,
        keywords,
        video_path: values.video_path || null,
        target_platforms: values.target_platforms,
        user_id: values.user_id || 1,
        adapt_content: values.adapt_content !== false,
        enforce_moderation: values.enforce_moderation === true,
      };
      if (values.group) {
        payload.source_post_id = values.group; // 复用字段标识分组来源，避免后端字段缺失
      }
      const res = await publishApi.multiPublish(payload);
      const data = res?.data || res || {};
      setResult(data);
      if (data.success) {
        message.success('多平台发布任务已完成');
      } else {
        message.warning(data.error_message || '发布未完全成功');
      }
    } catch (e: any) {
      if (e?.errorFields) return;
      console.error('multi publish failed', e);
      message.error('发布失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Spin spinning={loading}>
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card title="发布内容" size="small">
            <Form
              form={form}
              layout="vertical"
              initialValues={{ adapt_content: true, enforce_moderation: false, user_id: 1 }}
            >
              <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
                <Input placeholder="输入发布标题" showCount maxLength={200} />
              </Form.Item>
              <Form.Item name="content" label="正文" rules={[{ required: true, message: '请输入正文' }]}>
                <TextArea rows={5} placeholder="输入正文内容" showCount maxLength={5000} />
              </Form.Item>
              <Form.Item name="keywords" label="话题关键词（用逗号或换行分隔）">
                <TextArea rows={2} placeholder={'关键词1, 关键词2'} />
              </Form.Item>
              <Form.Item name="video_path" label="视频路径/URL（可选）">
                <Input placeholder="如 /data/videos/output.mp4 或 https://..." />
              </Form.Item>
              <Form.Item
                name="target_platforms"
                label="目标平台"
                rules={[{ required: true, message: '请选择至少一个平台' }]}
              >
                <Select
                  mode="multiple"
                  placeholder="选择目标平台（可多选）"
                  optionLabelProp="label"
                >
                  {platforms.map((p: any) => (
                    <Option key={p.name} value={p.name} label={`${p.icon || ''} ${p.name_cn}`}>
                      <Space>
                        <span>{p.icon}</span>
                        <span>{p.name_cn}</span>
                        <Text type="secondary" style={{ fontSize: 12 }}>{p.category}</Text>
                      </Space>
                    </Option>
                  ))}
                </Select>
              </Form.Item>
              <Row gutter={16}>
                <Col span={8}>
                  <Form.Item name="group" label="账号分组（可选）">
                    <Select allowClear placeholder="选择分组">
                      {groups.map((g: string) => (
                        <Option key={g} value={g}>{GROUP_LABEL[g] || g}</Option>
                      ))}
                    </Select>
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name="user_id" label="用户 ID">
                    <Input type="number" min={1} />
                  </Form.Item>
                </Col>
                <Col span={8}>
                  <Form.Item name="enforce_moderation" label="强制风控">
                    <Select>
                      <Option value={false}>关闭（命中敏感词仅警告）</Option>
                      <Option value={true}>开启（命中敏感词跳过发布）</Option>
                    </Select>
                  </Form.Item>
                </Col>
              </Row>
              <Button
                type="primary"
                icon={<RocketOutlined />}
                onClick={handlePublish}
                loading={submitting}
                size="large"
                block
              >
                立即发布
              </Button>
            </Form>
          </Card>
        </Col>

        <Col xs={24} lg={10}>
          <Card title="发布结果" size="small">
            {!result ? (
              <Empty description="尚未发起发布，请配置内容后点击立即发布" />
            ) : (
              <Spin spinning={submitting}>
                <Space direction="vertical" style={{ width: '100%' }} size="middle">
                  <div>
                    <Text strong>任务状态：</Text>
                    <Tag
                      color={
                        result.status === 'success' ? 'green' :
                        result.status === 'partial' ? 'orange' : 'red'
                      }
                    >
                      {result.status || (result.success ? 'success' : 'failed')}
                    </Tag>
                  </div>
                  {result.task_id && (
                    <div>
                      <Text strong>任务 ID：</Text>
                      <Text code style={{ wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
                        {result.task_id}
                      </Text>
                    </div>
                  )}
                  {result.error_message && (
                    <Alert
                      type={result.success ? 'info' : 'warning'}
                      message={result.error_message}
                      showIcon
                    />
                  )}
                  <Text strong>各平台结果：</Text>
                  {result.platform_results &&
                    Object.entries(result.platform_results).map(([pf, r]: [string, any]) => {
                      const meta = platforms.find((p: any) => p.name === pf);
                      return (
                        <Card
                          key={pf}
                          size="small"
                          style={{
                            borderLeft: `3px solid ${r.success ? '#52c41a' : '#f5222d'}`,
                          }}
                        >
                          <Space direction="vertical" style={{ width: '100%' }} size={4}>
                            <Space>
                              <PlatformTag
                                platform={pf}
                                nameCn={meta?.name_cn}
                                icon={meta?.icon}
                              />
                              {r.success ? (
                                <Tag color="green" icon={<CheckCircleOutlined />}>成功</Tag>
                              ) : (
                                <Tag color="red" icon={<CloseCircleOutlined />}>失败</Tag>
                              )}
                            </Space>
                            {r.url && (
                              <div style={{ wordBreak: 'break-all', overflowWrap: 'anywhere', overflowX: 'hidden' }}>
                                <Text type="secondary">链接：</Text>
                                <a href={r.url} target="_blank" rel="noreferrer">{r.url}</a>
                              </div>
                            )}
                            {r.error && (
                              <div style={{ wordBreak: 'break-all', overflowWrap: 'anywhere', overflowX: 'hidden', color: '#f5222d' }}>
                                <Text type="secondary">错误：</Text>{r.error}
                              </div>
                            )}
                            {r.message && (
                              <div style={{ wordBreak: 'break-all', overflowWrap: 'anywhere', overflowX: 'hidden', color: '#8c8c8c', fontSize: 12 }}>
                                {r.message}
                              </div>
                            )}
                          </Space>
                        </Card>
                      );
                    })}
                </Space>
              </Spin>
            )}
          </Card>
        </Col>
      </Row>
    </Spin>
  );
};

// ==================== 单平台发布面板 ====================
const SinglePublishPanel: React.FC<{ prefill?: PublishPrefill }> = ({ prefill }) => {
  const [platforms, setPlatforms] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [selectedPlatform, setSelectedPlatform] = useState<string>('');
  const [form] = Form.useForm();

  const fetchPlatforms = useCallback(async () => {
    setLoading(true);
    try {
      const res = await publishApi.listPlatforms();
      const data = res?.data || res || {};
      const list = (data.platforms || []).filter((p: any) => p.name !== 'x_twitter_publisher');
      setPlatforms(list);
      if (list.length > 0 && !selectedPlatform) {
        setSelectedPlatform(list[0].name);
      }
    } catch (e) {
      console.error('fetch platforms failed', e);
      message.error('加载平台列表失败');
    } finally {
      setLoading(false);
    }
  }, [selectedPlatform]);

  useEffect(() => {
    fetchPlatforms();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 平台列表加载完成后，应用从视频拆解跳转携带的预填数据
  useEffect(() => {
    if (!prefill?.from_breakdown) return;
    if (platforms.length === 0) return; // 等平台列表加载完
    const matchedPlatform = matchPrefillPlatform(platforms, prefill.platform);
    if (matchedPlatform) setSelectedPlatform(matchedPlatform);
    form.setFieldsValue({
      title: prefill.title || '',
      content: prefill.content || '',
      video_path: prefill.video_url || '',
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill, platforms]);

  const selectedMeta = platforms.find((p: any) => p.name === selectedPlatform);

  const handlePublish = async () => {
    if (!selectedPlatform) {
      message.warning('请选择平台');
      return;
    }
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      const keywords = (values.keywords || '')
        .split(/[,，\n]/)
        .map((s: string) => s.trim())
        .filter(Boolean);
      const res = await publishApi.singlePublish(selectedPlatform, {
        title: values.title,
        content: values.content,
        keywords,
        video_path: values.video_path || null,
        user_id: values.user_id || 1,
        adapt_content: values.adapt_content !== false,
        enforce_moderation: values.enforce_moderation === true,
      });
      const data = res?.data || res || {};
      setResult({ ...data, platform: selectedPlatform });
      if (data.success) {
        message.success(`${selectedMeta?.name_cn || selectedPlatform} 发布成功`);
      } else {
        message.error(data.error || '发布失败');
      }
    } catch (e: any) {
      if (e?.errorFields) return;
      console.error('single publish failed', e);
      message.error('发布失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Spin spinning={loading}>
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card title="发布内容" size="small">
            <Form
              form={form}
              layout="vertical"
              initialValues={{ adapt_content: true, enforce_moderation: false, user_id: 1 }}
            >
              <Form.Item label="目标平台" required>
                <Select
                  value={selectedPlatform || undefined}
                  onChange={(v) => { setSelectedPlatform(v); setResult(null); }}
                  placeholder="选择平台"
                  optionLabelProp="label"
                >
                  {platforms.map((p: any) => (
                    <Option key={p.name} value={p.name} label={`${p.icon || ''} ${p.name_cn}`}>
                      <Space>
                        <span>{p.icon}</span>
                        <span>{p.name_cn}</span>
                        <Text type="secondary" style={{ fontSize: 12 }}>{p.category}</Text>
                      </Space>
                    </Option>
                  ))}
                </Select>
              </Form.Item>
              {selectedMeta && (
                <Alert
                  type="info"
                  showIcon
                  style={{ marginBottom: 16 }}
                  message={
                    <span>
                      {selectedMeta.name_cn} 支持：
                      {selectedMeta.supports_video && <Tag color="blue" style={{ marginLeft: 4 }}>视频</Tag>}
                      {selectedMeta.supports_image && <Tag color="cyan">图片</Tag>}
                      {selectedMeta.supports_article && <Tag color="purple">文章</Tag>}
                      <span style={{ marginLeft: 8, color: '#8c8c8c' }}>
                        标题上限 {selectedMeta.max_title_length} 字 / 正文上限 {selectedMeta.max_content_length} 字
                      </span>
                    </span>
                  }
                />
              )}
              <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
                <Input placeholder="输入发布标题" showCount maxLength={selectedMeta?.max_title_length || 200} />
              </Form.Item>
              <Form.Item name="content" label="正文" rules={[{ required: true, message: '请输入正文' }]}>
                <TextArea rows={5} placeholder="输入正文内容" showCount maxLength={selectedMeta?.max_content_length || 5000} />
              </Form.Item>
              <Form.Item name="keywords" label="话题关键词（用逗号或换行分隔）">
                <TextArea rows={2} placeholder={'关键词1, 关键词2'} />
              </Form.Item>
              <Form.Item name="video_path" label="视频路径/URL（可选）">
                <Input placeholder="如 /data/videos/output.mp4 或 https://..." />
              </Form.Item>
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item name="user_id" label="用户 ID">
                    <Input type="number" min={1} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="enforce_moderation" label="强制风控">
                    <Select>
                      <Option value={false}>关闭（命中敏感词仅警告）</Option>
                      <Option value={true}>开启（命中敏感词跳过发布）</Option>
                    </Select>
                  </Form.Item>
                </Col>
              </Row>
              <Button
                type="primary"
                icon={<SendOutlined />}
                onClick={handlePublish}
                loading={submitting}
                size="large"
                block
              >
                发布到 {selectedMeta?.name_cn || selectedPlatform || '平台'}
              </Button>
            </Form>
          </Card>
        </Col>

        <Col xs={24} lg={10}>
          <Card title="发布结果" size="small">
            {!result ? (
              <Empty description="尚未发起发布" />
            ) : (
              <Spin spinning={submitting}>
                <Space direction="vertical" style={{ width: '100%' }} size="middle">
                  <div>
                    <Text strong>状态：</Text>
                    {result.success ? (
                      <Tag color="green" icon={<CheckCircleOutlined />}>成功</Tag>
                    ) : (
                      <Tag color="red" icon={<CloseCircleOutlined />}>失败</Tag>
                    )}
                  </div>
                  <PlatformTag
                    platform={result.platform}
                    nameCn={selectedMeta?.name_cn}
                    icon={selectedMeta?.icon}
                  />
                  {result.url && (
                    <div style={{ wordBreak: 'break-all', overflowWrap: 'anywhere', overflowX: 'hidden' }}>
                      <Text strong>帖子链接：</Text>
                      <a href={result.url} target="_blank" rel="noreferrer">{result.url}</a>
                    </div>
                  )}
                  {result.platform_id && (
                    <div style={{ wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
                      <Text strong>平台内容 ID：</Text>
                      <Text code>{result.platform_id}</Text>
                    </div>
                  )}
                  {result.error && (
                    <Alert
                      type="error"
                      message="错误信息"
                      description={
                        <div style={{ wordBreak: 'break-all', overflowWrap: 'anywhere', overflowX: 'hidden' }}>
                          {result.error}
                        </div>
                      }
                      showIcon
                    />
                  )}
                  {result.message && (
                    <div style={{ wordBreak: 'break-all', overflowWrap: 'anywhere', color: '#8c8c8c' }}>
                      <Text type="secondary">消息：</Text>{result.message}
                    </div>
                  )}
                  {result.debug_info && result.debug_info.length > 0 && (
                    <details>
                      <summary style={{ cursor: 'pointer', color: '#8c8c8c' }}>调试信息</summary>
                      <div style={{ wordBreak: 'break-all', overflowWrap: 'anywhere', marginTop: 8, color: '#8c8c8c', fontSize: 12 }}>
                        {result.debug_info.join('\n')}
                      </div>
                    </details>
                  )}
                </Space>
              </Spin>
            )}
          </Card>
        </Col>
      </Row>
    </Spin>
  );
};

// ==================== 流水线任务面板（视频拆解发起的发布任务） ====================

// 流水线步骤名（与后端 8 步对齐）
const PIPELINE_STEP_NAMES = [
  '待启动', '视频拆解', '生成解说视频', '生成发布文案',
  'AI选最佳文案', '填入视频URL', '发布到目标平台', '触发互动造势', '启动评论监控',
];

// 流水线任务状态 → 中文 + 颜色
const PIPELINE_STATUS_MAP: Record<string, { color: string; text: string }> = {
  pending: { color: 'gold', text: '发布中' },
  running: { color: 'processing', text: '发布中' },
  completed: { color: 'green', text: '发布成功' },
  failed: { color: 'red', text: '发布失败' },
  cancelled: { color: 'orange', text: '已取消' },
};

const PipelineTasksPanel: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [tasks, setTasks] = useState<PipelineTask[]>([]);
  const [detailTask, setDetailTask] = useState<PipelineTask | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const pollRef = useRef<number | null>(null);

  // 重试/编辑发布
  const [retryTask, setRetryTask] = useState<PipelineTask | null>(null);
  const [retryOpen, setRetryOpen] = useState(false);
  const [retrySubmitting, setRetrySubmitting] = useState(false);
  const [retryPlatforms, setRetryPlatforms] = useState<PlatformCapability[]>([]);
  const [retryForm] = Form.useForm();

  const fetchTasks = useCallback(async () => {
    try {
      const r = await autoPipelineApi.list({ limit: 100 });
      setTasks(r.tasks || []);
    } catch (e) {
      console.error('fetch pipeline tasks failed', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    fetchTasks();
  }, [fetchTasks]);

  // 有运行中任务时自动轮询（5s），全部完成后停止
  useEffect(() => {
    const hasRunning = tasks.some(
      (t) => t.status === 'running' || t.status === 'pending'
    );
    if (hasRunning) {
      pollRef.current = window.setInterval(fetchTasks, 5000);
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [tasks, fetchTasks]);

  // 详情弹窗打开时也轮询（实时更新进度）
  useEffect(() => {
    if (!detailOpen || !detailTask) return;
    const timer = window.setInterval(async () => {
      try {
        const r = await autoPipelineApi.status(detailTask.task_id);
        setDetailTask(r.task);
        // 同步到列表
        setTasks((prev) =>
          prev.map((t) => (t.task_id === r.task.task_id ? r.task : t))
        );
      } catch {
        // 忽略
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [detailOpen, detailTask]);

  const handleViewDetail = (task: PipelineTask) => {
    setDetailTask(task);
    setDetailOpen(true);
  };

  const handleCancelTask = useCallback(async (taskId: string) => {
    try {
      await autoPipelineApi.cancel(taskId);
      message.warning('任务已取消');
      fetchTasks();
      if (detailTask?.task_id === taskId) {
        setDetailTask((prev) => prev ? { ...prev, status: 'cancelled' as const, step_detail: '用户手动取消' } : null);
      }
    } catch (e: any) {
      message.error('取消失败: ' + (e?.message || ''));
    }
  }, [fetchTasks, detailTask]);

  // 加载平台列表（供重试时选择目标平台）
  useEffect(() => {
    autoPipelineApi.platforms()
      .then((r) => setRetryPlatforms(r.platforms || []))
      .catch(() => {});
  }, []);

  // 打开重试/编辑弹窗，预填任务数据
  const handleRetry = useCallback((task: PipelineTask) => {
    setRetryTask(task);
    setRetryOpen(true);
    retryForm.setFieldsValue({
      platform: task.platform,
      content: task.selected_content || task.source_post_content || '',
      video_url: task.video_url || '',
      title: (task.source_post_content || '').slice(0, 100),
    });
  }, [retryForm]);

  // 提交重试：用编辑后的内容直接发布（跳过 Step1-4）
  const doRetryPublish = useCallback(async () => {
    if (!retryTask) return;
    try {
      const values = await retryForm.validateFields();
      setRetrySubmitting(true);
      const r = await autoPipelineApi.run({
        platform: values.platform,
        hotspot_item: {
          post_id: retryTask.source_post_id || retryTask.task_id,
          post_url: retryTask.source_post_url || '',
          content: retryTask.source_post_content || values.content,
          video_url: retryTask.source_post_video || values.video_url || '',
          username: retryTask.source_post_author || '',
        },
        skip_video: true,
        auto_monitor: true,
        trigger_interaction: false,
        // 复用已有拆解+视频+编辑后文案，跳过 Step1-4，直接从 Step5 发布
        breakdown_text: retryTask.breakdown_text || undefined,
        pre_video_url: values.video_url || undefined,
        pre_selected_content: values.content || undefined,
        is_retry: true,
      });
      message.success('已重新提交发布任务');
      setRetryOpen(false);
      setRetryTask(null);
      fetchTasks();
      // 自动打开详情追踪新任务
      if (r.task_id) {
        try {
          const st = await autoPipelineApi.status(r.task_id);
          setDetailTask(st.task);
          setDetailOpen(true);
        } catch {}
      }
    } catch (e: any) {
      if (e?.errorFields) return; // 表单校验失败，不提示
      message.error('重试失败: ' + (e?.message || ''));
    } finally {
      setRetrySubmitting(false);
    }
  }, [retryTask, retryForm, fetchTasks]);

  // 统计
  const runningCount = tasks.filter((t) => t.status === 'running' || t.status === 'pending').length;
  const successCount = tasks.filter((t) => t.status === 'completed').length;
  const failedCount = tasks.filter((t) => t.status === 'failed' || t.status === 'cancelled').length;

  const columns = [
    {
      title: '平台',
      dataIndex: 'platform',
      width: 110,
      render: (v: string) => (
        <Tag color={PLATFORM_COLOR[v] || 'default'}>
          <GlobalOutlined style={{ marginRight: 4 }} />
          {v}
        </Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (v: string) => {
        const info = PIPELINE_STATUS_MAP[v] || { color: 'default', text: v };
        return <Tag color={info.color}>{info.text}</Tag>;
      },
    },
    {
      title: '进度',
      width: 200,
      render: (_: any, r: PipelineTask) => {
        const isCompleted = r.status === 'completed';
        const isFailed = r.status === 'failed' || r.status === 'cancelled';
        const percent = isCompleted ? 100 : Math.round((r.current_step / 8) * 100);
        return (
          <div>
            <Progress
              percent={percent}
              size="small"
              status={isCompleted ? 'success' : isFailed ? 'exception' : 'active'}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {PIPELINE_STEP_NAMES[r.current_step] || r.step_name || '-'}
              {r.step_detail ? `：${r.step_detail}` : ''}
            </Text>
          </div>
        );
      },
    },
    {
      title: '源内容',
      dataIndex: 'source_post_content',
      render: (v: string, r: PipelineTask) => (
        <div>
          {r.source_post_author && <Tag color="blue">@{r.source_post_author}</Tag>}
          <div
            style={{
              color: '#8c8c8c',
              fontSize: 12,
              marginTop: 4,
              wordBreak: 'break-all',
              overflowWrap: 'anywhere',
              overflowX: 'hidden',
            }}
          >
            {v ? (v.length > 60 ? v.slice(0, 60) + '...' : v) : '-'}
          </div>
        </div>
      ),
    },
    {
      title: '发布结果',
      width: 160,
      render: (_: any, r: PipelineTask) => {
        if (r.published_post_url) {
          return (
            <a href={r.published_post_url} target="_blank" rel="noreferrer" style={{ wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
              {r.published_post_url.length > 30 ? r.published_post_url.slice(0, 30) + '...' : r.published_post_url}
            </a>
          );
        }
        if (r.status === 'completed') {
          return <Text type="secondary">无链接（DRY-RUN）</Text>;
        }
        return <Text type="secondary">-</Text>;
      },
    },
    {
      title: '创建时间',
      dataIndex: 'add_ts',
      width: 160,
      render: (v: number) => {
        if (!v) return '-';
        try {
          return new Date(v * 1000).toLocaleString('zh-CN');
        } catch {
          return String(v);
        }
      },
    },
    {
      title: '操作',
      width: 170,
      render: (_: any, r: PipelineTask) => (
        <Space size={0} wrap>
          <Button size="small" type="link" icon={<EyeOutlined />} onClick={() => handleViewDetail(r)}>
            详情
          </Button>
          {(r.status === 'failed' || r.status === 'cancelled') && (
            <Button
              size="small"
              type="link"
              icon={<EditOutlined />}
              onClick={() => handleRetry(r)}
            >
              重试
            </Button>
          )}
          {(r.status === 'running' || r.status === 'pending') && (
            <Button
              size="small"
              type="link"
              danger
              onClick={() => handleCancelTask(r.task_id)}
            >
              取消
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Space style={{ marginBottom: 16 }} wrap>
        <Tag color="processing">发布中 {runningCount}</Tag>
        <Tag color="success">成功 {successCount}</Tag>
        <Tag color="error">失败 {failedCount}</Tag>
        <Tag color="blue">总计 {tasks.length}</Tag>
        <Button icon={<ReloadOutlined />} onClick={fetchTasks} loading={loading}>刷新</Button>
      </Space>

      <Spin spinning={loading}>
        {tasks.length === 0 && !loading ? (
          <Empty description="暂无流水线任务（在视频拆解中点击「一键发布」后会在此显示）" />
        ) : (
          <Table
            rowKey="task_id"
            columns={columns}
            dataSource={tasks}
            size="middle"
            pagination={{ pageSize: 15, showSizeChanger: true, total: tasks.length }}
            scroll={{ x: 1100 }}
          />
        )}
      </Spin>

      {/* 任务详情弹窗：复用 TaskCard 展示完整 8 步进度 + 打通拆解/视频/互动/监控数据 */}
      <Modal
        title={
          <Space>
            <ThunderboltOutlined style={{ color: '#faad14' }} />
            <span>流水线任务详情</span>
            {detailTask && (
              <Tag color={PLATFORM_COLOR[detailTask.platform] || 'default'}>
                {detailTask.platform}
              </Tag>
            )}
          </Space>
        }
        open={detailOpen}
        onCancel={() => { setDetailOpen(false); setDetailTask(null); }}
        footer={<Button onClick={() => { setDetailOpen(false); setDetailTask(null); }}>关闭</Button>}
        width={720}
      >
        {detailTask ? (
          <Space direction="vertical" style={{ width: '100%' }} size={12}>
            {/* 8 步进度卡片 */}
            <TaskCard task={detailTask} onCancel={handleCancelTask} />

            {/* 打通各模块数据：拆解 / 视频 / 文案 / 互动 / 监控 */}
            <Card size="small" title="完整数据（拆解·视频·互动·监控）">
              <Descriptions column={1} size="small" bordered>
                <Descriptions.Item label="任务 ID">
                  <Text copyable style={{ wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
                    {detailTask.task_id}
                  </Text>
                </Descriptions.Item>
                <Descriptions.Item label="源帖子">
                  {detailTask.source_post_url ? (
                    <a href={detailTask.source_post_url} target="_blank" rel="noreferrer" style={{ wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
                      {detailTask.source_post_url}
                    </a>
                  ) : <Text type="secondary">-</Text>}
                </Descriptions.Item>
                <Descriptions.Item label="拆解结果">
                  <div style={{ maxHeight: 120, overflowY: 'auto', wordBreak: 'break-all', overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' }}>
                    {detailTask.breakdown_text || <Text type="secondary">（无拆解文本）</Text>}
                  </div>
                </Descriptions.Item>
                <Descriptions.Item label="解说视频 URL">
                  {detailTask.video_url ? (
                    <a href={detailTask.video_url} target="_blank" rel="noreferrer" style={{ wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
                      {detailTask.video_url}
                    </a>
                  ) : <Text type="secondary">（未生成视频，纯文字发布）</Text>}
                </Descriptions.Item>
                {detailTask.candidate_contents && detailTask.candidate_contents.length > 0 && (
                  <Descriptions.Item label={`候选文案（${detailTask.candidate_contents.length} 条）`}>
                    <div style={{ maxHeight: 100, overflowY: 'auto' }}>
                      {detailTask.candidate_contents.map((c, i) => (
                        <div key={i} style={{ marginBottom: 4, wordBreak: 'break-all', overflowWrap: 'anywhere', color: c === detailTask.selected_content ? '#52c41a' : '#8c8c8c' }}>
                          {i + 1}. {c.slice(0, 80)}{c.length > 80 ? '...' : ''}
                          {c === detailTask.selected_content && <Tag color="green" style={{ marginLeft: 4 }}>已选</Tag>}
                        </div>
                      ))}
                    </div>
                  </Descriptions.Item>
                )}
                <Descriptions.Item label="发布结果">
                  {detailTask.published_post_url ? (
                    <a href={detailTask.published_post_url} target="_blank" rel="noreferrer" style={{ wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
                      {detailTask.published_post_url}
                    </a>
                  ) : <Text type="secondary">-</Text>}
                  {detailTask.published_post_id && (
                    <Tag color="blue" style={{ marginLeft: 8 }}>ID: {detailTask.published_post_id}</Tag>
                  )}
                </Descriptions.Item>
                <Descriptions.Item label="互动造势">
                  {detailTask.interaction_triggered ? (
                    <Tag color="green">已触发</Tag>
                  ) : (
                    <Tag color="default">未触发</Tag>
                  )}
                </Descriptions.Item>
                <Descriptions.Item label="评论监控">
                  {detailTask.monitor_started ? (
                    <Tag color="green">已启动</Tag>
                  ) : (
                    <Tag color="default">未启动</Tag>
                  )}
                </Descriptions.Item>
                {detailTask.error_msg && (
                  <Descriptions.Item label="错误信息">
                    <span style={{ color: '#f5222d', wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
                      {detailTask.error_msg}
                    </span>
                  </Descriptions.Item>
                )}
              </Descriptions>
            </Card>
          </Space>
        ) : (
          <Empty description="记录不存在" />
        )}
      </Modal>

      {/* 重试/编辑发布弹窗：允许用户修改文案、标题、视频URL 和目标平台后重新发布 */}
      <Modal
        title={
          <Space>
            <EditOutlined style={{ color: '#faad14' }} />
            <span>重试发布（可编辑全部内容）</span>
          </Space>
        }
        open={retryOpen}
        onCancel={() => { setRetryOpen(false); setRetryTask(null); }}
        footer={[
          <Button key="cancel" onClick={() => { setRetryOpen(false); setRetryTask(null); }}>
            取消
          </Button>,
          <Button key="submit" type="primary" loading={retrySubmitting} onClick={doRetryPublish}>
            重新发布
          </Button>,
        ]}
        width={720}
        destroyOnClose
      >
        {retryTask && (
          <Form form={retryForm} layout="vertical" initialValues={{ platform: '', content: '' }}>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message={`将基于任务 ${retryTask.task_id.slice(0, 8)}... 重新发布，复用已有拆解与视频，跳过 AI 文案生成。`}
            />
            <Form.Item
              name="platform"
              label="目标平台"
              rules={[{ required: true, message: '请选择平台' }]}
            >
              <Select placeholder="选择目标平台">
                {retryPlatforms.map((p) => (
                  <Select.Option key={p.platform} value={p.platform}>
                    <Space>
                      <Tag color={PLATFORM_COLOR[p.platform] || 'default'} style={{ marginRight: 0 }}>
                        {p.region === 'global' ? '海外' : '国内'}
                      </Tag>
                      <span>{p.name}</span>
                      {!p.real_publish && <Text type="secondary" style={{ fontSize: 12 }}>（DRY-RUN）</Text>}
                    </Space>
                  </Select.Option>
                ))}
              </Select>
            </Form.Item>
            <Form.Item
              name="title"
              label="标题"
              rules={[{ required: true, message: '请输入标题' }]}
            >
              <Input maxLength={200} placeholder="请输入发布标题" showCount />
            </Form.Item>
            <Form.Item
              name="content"
              label="发布内容"
              rules={[{ required: true, message: '请输入发布内容' }]}
            >
              <Input.TextArea
                rows={6}
                placeholder="请输入发布内容（可在此编辑后重新发布）"
                showCount
                maxLength={5000}
                style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', overflowWrap: 'anywhere' }}
              />
            </Form.Item>
            <Form.Item name="video_url" label="视频 URL（可选）">
              <Input placeholder="已有的解说视频 URL，留空则纯文字发布" />
            </Form.Item>
          </Form>
        )}
      </Modal>
    </div>
  );
};

// ==================== 发布记录面板 ====================
const RecordsPanel: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState<{
    platform?: string;
    status?: string;
    dateRange?: [any, any];
  }>({});
  const [detailOpen, setDetailOpen] = useState(false);
  const [detail, setDetail] = useState<any>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const fetchRecords = useCallback(async () => {
    setLoading(true);
    try {
      const params: any = {
        limit: 100,
        offset: 0,
      };
      if (filter.platform) params.platform = filter.platform;
      if (filter.status) params.status = filter.status;
      if (filter.dateRange && filter.dateRange.length === 2) {
        params.start_date = filter.dateRange[0].format('YYYY-MM-DD');
        params.end_date = filter.dateRange[1].format('YYYY-MM-DD');
      }
      const res = await publishApi.listRecords(params);
      const data = res?.data || res || {};
      const payload = data.data || data;
      const list = payload.items || payload.records || [];
      setItems(list);
      setTotal(payload.total ?? list.length);
    } catch (e) {
      console.error('fetch records failed', e);
      message.error('加载发布记录失败');
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    fetchRecords();
  }, [fetchRecords]);

  const handleViewDetail = async (id: number) => {
    setDetailOpen(true);
    setDetailLoading(true);
    setDetail(null);
    try {
      const res = await publishApi.getRecord(id);
      const data = res?.data || res || {};
      const payload = data.data || data;
      if (data.code && data.code !== 0) {
        message.warning(data.message || '记录不存在');
      }
      setDetail(payload);
    } catch (e) {
      console.error('fetch record detail failed', e);
      message.error('加载详情失败');
    } finally {
      setDetailLoading(false);
    }
  };

  const columns = [
    {
      title: 'ID',
      dataIndex: 'id',
      width: 70,
    },
    {
      title: '平台',
      dataIndex: 'platform',
      width: 110,
      render: (v: string) => (
        <Tag color={PLATFORM_COLOR[v] || 'default'}>
          <GlobalOutlined style={{ marginRight: 4 }} />
          {v}
        </Tag>
      ),
    },
    {
      title: '来源',
      width: 100,
      render: (_: any, r: any) => {
        const meta = r.metadata || {};
        if (meta.is_retry) {
          return <Tag color="purple">重试</Tag>;
        }
        if (meta.pipeline) {
          return <Tag color="blue">流水线</Tag>;
        }
        return <Tag color="default">直接发布</Tag>;
      },
    },
    {
      title: '账号 ID',
      dataIndex: 'account_id',
      width: 90,
      render: (v: any) => v ? String(v) : <Text type="secondary">-</Text>,
    },
    {
      title: '标题',
      dataIndex: 'title',
      render: (v: string, r: any) => (
        <div>
          <strong>{v || '-'}</strong>
          {r.content && (
            <div
              style={{
                color: '#8c8c8c',
                fontSize: 12,
                marginTop: 4,
                wordBreak: 'break-all',
                overflowWrap: 'anywhere',
                overflowX: 'hidden',
              }}
            >
              {String(r.content).slice(0, 80)}{String(r.content).length > 80 ? '...' : ''}
            </div>
          )}
        </div>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (v: string) => {
        const info = RECORD_STATUS[v] || { color: 'default', text: v };
        return <Tag color={info.color}>{info.text}</Tag>;
      },
    },
    {
      title: '发布时间',
      dataIndex: 'published_at',
      width: 170,
      render: (v: any) => {
        if (!v) return '-';
        try {
          return new Date(v).toLocaleString('zh-CN');
        } catch {
          return String(v);
        }
      },
    },
    {
      title: '帖子链接',
      dataIndex: 'post_url',
      width: 200,
      render: (v: string) => {
        if (!v) return <Text type="secondary">-</Text>;
        return (
          <Tooltip
            title={<div style={{ wordBreak: 'break-all', overflowWrap: 'anywhere', maxWidth: 400 }}>{v}</div>}
          >
            <div
              style={{
                wordBreak: 'break-all',
                overflowWrap: 'anywhere',
                overflowX: 'hidden',
                color: '#1677ff',
              }}
            >
              <a href={v} target="_blank" rel="noreferrer">{v.length > 30 ? v.slice(0, 30) + '...' : v}</a>
            </div>
          </Tooltip>
        );
      },
    },
    {
      title: '操作',
      width: 90,
      render: (_: any, r: any) => (
        <Button
          size="small"
          type="link"
          icon={<EyeOutlined />}
          onClick={() => handleViewDetail(r.id)}
        >
          详情
        </Button>
      ),
    },
  ];

  return (
    <div>
      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          allowClear
          placeholder="平台筛选"
          style={{ width: 150 }}
          value={filter.platform}
          onChange={(v) => setFilter({ ...filter, platform: v })}
        >
          {[
            'douyin', 'xiaohongshu', 'bilibili', 'weibo', 'zhihu',
            'x_twitter', 'kuaishou', 'wechat_public', 'wechat_channels',
            'toutiao', 'tiktok', 'instagram', 'youtube', 'facebook',
          ].map((p) => (
            <Option key={p} value={p}>{p}</Option>
          ))}
        </Select>
        <Select
          allowClear
          placeholder="状态筛选"
          style={{ width: 130 }}
          value={filter.status}
          onChange={(v) => setFilter({ ...filter, status: v })}
        >
          {Object.entries(RECORD_STATUS).map(([k, v]) => (
            <Option key={k} value={k}>{v.text}</Option>
          ))}
        </Select>
        <RangePicker
          value={filter.dateRange as any}
          onChange={(v) => setFilter({ ...filter, dateRange: v as [any, any] })}
        />
        <Button icon={<ReloadOutlined />} onClick={fetchRecords} loading={loading}>刷新</Button>
      </Space>

      <Spin spinning={loading}>
        {items.length === 0 && !loading ? (
          <Empty description="暂无发布记录" />
        ) : (
          <Table
            rowKey={(r) => r.id || `${r.platform}_${r.published_at}`}
            columns={columns}
            dataSource={items}
            size="middle"
            pagination={{ pageSize: 15, showSizeChanger: true, total }}
            scroll={{ x: 1100 }}
          />
        )}
      </Spin>

      <Modal
        title="发布记录详情"
        open={detailOpen}
        onCancel={() => { setDetailOpen(false); setDetail(null); }}
        footer={<Button onClick={() => { setDetailOpen(false); setDetail(null); }}>关闭</Button>}
        width={640}
      >
        <Spin spinning={detailLoading}>
          {detail ? (
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="记录 ID">{detail.id}</Descriptions.Item>
              <Descriptions.Item label="任务 ID">
                <span style={{ wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
                  {detail.task_id || '-'}
                </span>
              </Descriptions.Item>
              <Descriptions.Item label="平台">{detail.platform}</Descriptions.Item>
              <Descriptions.Item label="账号 ID">{detail.account_id || '-'}</Descriptions.Item>
              <Descriptions.Item label="标题">{detail.title || '-'}</Descriptions.Item>
              <Descriptions.Item label="状态">
                {(() => {
                  const info = RECORD_STATUS[detail.status] || { color: 'default', text: detail.status };
                  return <Tag color={info.color}>{info.text}</Tag>;
                })()}
              </Descriptions.Item>
              <Descriptions.Item label="视频路径">
                <span style={{ wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
                  {detail.video_path || '-'}
                </span>
              </Descriptions.Item>
              <Descriptions.Item label="帖子链接">
                {detail.post_url ? (
                  <a href={detail.post_url} target="_blank" rel="noreferrer" style={{ wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
                    {detail.post_url}
                  </a>
                ) : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="平台内容 ID">{detail.platform_id || '-'}</Descriptions.Item>
              <Descriptions.Item label="错误信息">
                <span style={{ wordBreak: 'break-all', overflowWrap: 'anywhere', color: detail.error_message ? '#f5222d' : undefined }}>
                  {detail.error_message || '-'}
                </span>
              </Descriptions.Item>
              <Descriptions.Item label="正文">
                <div style={{ wordBreak: 'break-all', overflowWrap: 'anywhere', overflowX: 'hidden', maxHeight: 200, overflowY: 'auto' }}>
                  {detail.content || '-'}
                </div>
              </Descriptions.Item>
              <Descriptions.Item label="发布时间">
                {detail.published_at ? new Date(detail.published_at).toLocaleString('zh-CN') : '-'}
              </Descriptions.Item>
              <Descriptions.Item label="创建时间">
                {detail.created_at ? new Date(detail.created_at).toLocaleString('zh-CN') : '-'}
              </Descriptions.Item>
            </Descriptions>
          ) : (
            !detailLoading && <Empty description="记录不存在" />
          )}
        </Spin>
      </Modal>
    </div>
  );
};

export default PublishCenter;
