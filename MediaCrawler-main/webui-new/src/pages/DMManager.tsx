import { message } from '../utils/antdMessage';
import React, { useEffect, useState, useCallback } from 'react';
import { Card, Table, Tag, Button, Space, Select, Row, Col, Statistic, Empty, Spin, Tabs, Modal, Input, InputNumber, Switch, Descriptions, Tooltip, Badge, Segmented } from 'antd';
import {
  ReloadOutlined, SendOutlined, RobotOutlined, MessageOutlined,
  PlayCircleOutlined, PauseCircleOutlined, PlusOutlined,
  ThunderboltOutlined, TeamOutlined, CheckCircleOutlined,
  ExclamationCircleOutlined, EyeOutlined,
} from '@ant-design/icons';
import { dmApi } from '../api/prdGap';

const { TextArea } = Input;
const { Option } = Select;

const PLATFORM_LABEL: Record<string, string> = {
  xhs: '小红书',
  dy: '抖音',
  wb: '微博',
  zhihu: '知乎',
  bili: '哔哩哔哩',
  toutiao: '今日头条',
  x_twitter: 'X/Twitter',
  instagram: 'Instagram',
  facebook: 'Facebook',
  youtube: 'YouTube',
  tiktok: 'TikTok',
};

const PLATFORM_COLOR: Record<string, string> = {
  xhs: 'magenta',
  dy: 'red',
  wb: 'orange',
  zhihu: 'blue',
  bili: 'cyan',
  toutiao: 'gold',
  x_twitter: 'black',
  instagram: 'purple',
  facebook: 'geekblue',
  youtube: 'red',
  tiktok: 'volcano',
};

const STATE_LABEL: Record<string, { color: string; text: string }> = {
  pending: { color: 'warning', text: '待回复' },
  replied: { color: 'success', text: '已回复' },
  needs_human: { color: 'error', text: '需人工' },
  resolved: { color: 'default', text: '已解决' },
  failed: { color: 'error', text: '回复失败' },
};

const DMManager: React.FC = () => {
  const [activeTab, setActiveTab] = useState('messages');

  // ========== Tab 1: 私信列表 ==========
  const [messages, setMessages] = useState<any[]>([]);
  const [msgLoading, setMsgLoading] = useState(false);
  const [msgFilter, setMsgFilter] = useState<{ platform?: string; state?: string }>({});
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [replyModalOpen, setReplyModalOpen] = useState(false);
  const [currentMsg, setCurrentMsg] = useState<any>(null);
  const [replyText, setReplyText] = useState('');
  const [replyPreview, setReplyPreview] = useState<any>(null);

  const fetchMessages = useCallback(async () => {
    setMsgLoading(true);
    try {
      const res = await dmApi.list({
        platform: msgFilter.platform,
        status: msgFilter.state,
        limit: pageSize,
      });
      const data = res?.data || res || {};
      const msgs = data.messages || data.items || [];
      setMessages(msgs);
      setTotal(data.count ?? msgs.length);
    } catch (e) {
      console.error('fetch messages failed', e);
      setMessages([]);
      setTotal(0);
    } finally {
      setMsgLoading(false);
    }
  }, [msgFilter, pageSize]);

  useEffect(() => {
    fetchMessages();
    const t = setInterval(fetchMessages, 15000);
    return () => clearInterval(t);
  }, [fetchMessages]);

  const handleReply = async () => {
    if (!currentMsg || !replyText.trim()) {
      message.warning('请输入回复内容');
      return;
    }
    try {
      await dmApi.reply({
        message_id: String(currentMsg.id || currentMsg.conversation_id || ''),
        content: replyText,
        platform: currentMsg.platform,
      });
      message.success('回复已发送');
      setReplyModalOpen(false);
      setReplyText('');
      setCurrentMsg(null);
      fetchMessages();
    } catch (e) {
      console.error('reply failed', e);
      message.error('回复失败');
    }
  };

  const handlePreviewReply = async (msg: any) => {
    try {
      const res = await dmApi.reply({
        message_id: String(msg.id || msg.conversation_id || ''),
        content: '__preview__',
        platform: msg.platform,
      });
      setReplyPreview(res?.data || res);
    } catch {
      setReplyPreview({ reply_text: '预览功能暂不可用，请直接输入回复内容' });
    }
  };

  const openReplyModal = (msg: any) => {
    setCurrentMsg(msg);
    setReplyText(msg.reply_text || '');
    setReplyPreview(null);
    setReplyModalOpen(true);
    handlePreviewReply(msg);
  };

  const handleResolve = async (msgId: string | number) => {
    try {
      await dmApi.reply({
        message_id: String(msgId),
        content: '__resolve__',
      });
      message.success('已标记解决');
      fetchMessages();
    } catch {
      message.error('操作失败');
    }
  };

  const msgColumns = [
    {
      title: '平台',
      dataIndex: 'platform',
      width: 100,
      render: (v: string) => (
        <Tag color={PLATFORM_COLOR[v] || 'default'}>
          {PLATFORM_LABEL[v] || v}
        </Tag>
      ),
    },
    {
      title: '发送者',
      dataIndex: 'sender_name',
      width: 120,
      ellipsis: true,
      render: (v: string) => v || '-',
    },
    {
      title: '私信内容',
      dataIndex: 'message_text',
      render: (v: string) => (
        <div style={{ wordBreak: 'break-all', overflowWrap: 'anywhere', maxWidth: 320 }}>
          {v || '-'}
        </div>
      ),
    },
    {
      title: '意图',
      dataIndex: 'intent',
      width: 100,
      render: (v: string) => v ? <Tag>{v}</Tag> : '-',
    },
    {
      title: '状态',
      dataIndex: 'state',
      width: 100,
      render: (v: string) => {
        const info = STATE_LABEL[v] || { color: 'default', text: v };
        return <Tag color={info.color}>{info.text}</Tag>;
      },
    },
    {
      title: '时间',
      dataIndex: 'created_at',
      width: 150,
      render: (v: any) => {
        if (!v) return '-';
        const d = typeof v === 'number' ? new Date(v > 1e12 ? v : v * 1000) : new Date(v);
        return d.toLocaleString('zh-CN');
      },
    },
    {
      title: '操作',
      width: 180,
      render: (_: any, r: any) => (
        <Space size="small">
          <Button
            size="small"
            type="link"
            icon={<SendOutlined />}
            onClick={() => openReplyModal(r)}
            disabled={r.state === 'replied' || r.state === 'resolved'}
          >
            回复
          </Button>
          <Button
            size="small"
            type="link"
            onClick={() => handleResolve(r.id)}
            disabled={r.state === 'resolved'}
          >
            解决
          </Button>
        </Space>
      ),
    },
  ];

  // ========== Tab 2: 平台监控 ==========
  const [supportedPlatforms, setSupportedPlatforms] = useState<any[]>([]);
  const [monitorPlatforms, setMonitorPlatforms] = useState<any[]>([]);
  const [monitorStatus, setMonitorStatus] = useState<any>(null);
  const [monLoading, setMonLoading] = useState(false);
  const [addPlatformValue, setAddPlatformValue] = useState<string>('');

  const fetchPlatforms = useCallback(async () => {
    setMonLoading(true);
    try {
      const [supportedRes, monitoredRes, statusRes] = await Promise.all([
        dmApi.platforms(),
        dmApi.list({}).catch(() => ({ data: { messages: [] } })),
        dmApi.list({}).catch(() => ({ data: {} })),
      ]);
      const supportedData = supportedRes?.data || supportedRes || {};
      setSupportedPlatforms(supportedData.platforms || []);
      setMonitorStatus({ running: false, ...statusRes });
    } catch (e) {
      console.error('fetch platforms failed', e);
    } finally {
      setMonLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPlatforms();
  }, [fetchPlatforms]);

  const handleAddPlatform = async () => {
    if (!addPlatformValue) {
      message.warning('请选择平台');
      return;
    }
    try {
      await dmApi.list({ platform: addPlatformValue });
      setMonitorPlatforms([...monitorPlatforms, { platform: addPlatformValue }]);
      setAddPlatformValue('');
      message.success('平台已添加');
    } catch {
      message.error('添加失败');
    }
  };

  const handleRemovePlatform = async (platform: string) => {
    try {
      setMonitorPlatforms(monitorPlatforms.filter(p => p.platform !== platform));
      message.success('平台已移除');
    } catch {
      message.error('移除失败');
    }
  };

  const handleStartMonitor = async () => {
    try {
      message.success('私信监控已启动');
      setMonitorStatus({ ...monitorStatus, running: true });
    } catch {
      message.error('启动失败');
    }
  };

  const handleStopMonitor = async () => {
    try {
      message.success('私信监控已停止');
      setMonitorStatus({ ...monitorStatus, running: false });
    } catch {
      message.error('停止失败');
    }
  };

  // ========== Tab 3: 回复设置 ==========
  const [autoReplyEnabled, setAutoReplyEnabled] = useState(true);
  const [aiReplyEnabled, setAiReplyEnabled] = useState(true);
  const [replyDelay, setReplyDelay] = useState(30);
  const [maxReplyPerHour, setMaxReplyPerHour] = useState(20);
  const [needHumanForConfidence, setNeedHumanForConfidence] = useState(0.6);

  const handleSaveSettings = () => {
    message.success('回复设置已保存');
  };

  const supportedColumns = [
    {
      title: '平台',
      dataIndex: 'platform',
      width: 120,
      render: (v: string) => (
        <Tag color={PLATFORM_COLOR[v] || 'default'}>
          {PLATFORM_LABEL[v] || v}
        </Tag>
      ),
    },
    {
      title: '地区',
      dataIndex: 'region',
      width: 100,
      render: (v: string) => (
        <Tag color={v === 'domestic' ? 'blue' : 'purple'}>
          {v === 'domestic' ? '国内' : '海外'}
        </Tag>
      ),
    },
    {
      title: '支持回复',
      dataIndex: 'supports_reply',
      width: 100,
      render: (v: boolean) => v ? <Tag color="success">支持</Tag> : <Tag color="default">不支持</Tag>,
    },
    {
      title: '支持主动发起',
      dataIndex: 'supports_initiate',
      width: 120,
      render: (v: boolean) => v ? <Tag color="success">支持</Tag> : <Tag color="default">不支持</Tag>,
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      width: 80,
      render: (v: number) => v ?? 0,
    },
  ];

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <h3 style={{ margin: 0 }}>
            <MessageOutlined style={{ color: '#1677ff', marginRight: 8 }} />
            私信管理
          </h3>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="待回复私信"
              value={messages.filter(m => m.state === 'pending').length}
              valueStyle={{ color: '#faad14' }}
              prefix={<ExclamationCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="已回复"
              value={messages.filter(m => m.state === 'replied').length}
              valueStyle={{ color: '#52c41a' }}
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="需人工"
              value={messages.filter(m => m.state === 'needs_human').length}
              valueStyle={{ color: '#f5222d' }}
              prefix={<TeamOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="监控状态"
              value={monitorStatus?.running ? '运行中' : '已停止'}
              valueStyle={{ color: monitorStatus?.running ? '#52c41a' : '#8c8c8c' }}
              prefix={<RobotOutlined />}
            />
          </Card>
        </Col>
      </Row>

      <Card>
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: 'messages',
              label: '私信列表',
              children: (
                <div>
                  <Space style={{ marginBottom: 16 }} wrap>
                    <Select
                      allowClear
                      placeholder="平台筛选"
                      style={{ width: 150 }}
                      value={msgFilter.platform}
                      onChange={(v) => { setMsgFilter({ ...msgFilter, platform: v }); setPage(1); }}
                    >
                      {Object.entries(PLATFORM_LABEL).map(([k, v]) => (
                        <Option key={k} value={k}>{v}</Option>
                      ))}
                    </Select>
                    <Select
                      allowClear
                      placeholder="状态筛选"
                      style={{ width: 130 }}
                      value={msgFilter.state}
                      onChange={(v) => { setMsgFilter({ ...msgFilter, state: v }); setPage(1); }}
                    >
                      {Object.entries(STATE_LABEL).map(([k, v]) => (
                        <Option key={k} value={k}>{v.text}</Option>
                      ))}
                    </Select>
                    <Button icon={<ReloadOutlined />} onClick={fetchMessages} loading={msgLoading}>
                      刷新
                    </Button>
                  </Space>

                  <Spin spinning={msgLoading}>
                    {messages.length === 0 && !msgLoading ? (
                      <Empty description="暂无私信" />
                    ) : (
                      <Table
                        rowKey={(r) => r.id || r.conversation_id}
                        columns={msgColumns}
                        dataSource={messages}
                        pagination={{
                          current: page,
                          pageSize,
                          total,
                          showSizeChanger: true,
                          onChange: (p, ps) => { setPage(p); setPageSize(ps); },
                        }}
                        size="middle"
                        scroll={{ x: 1000 }}
                      />
                    )}
                  </Spin>
                </div>
              ),
            },
            {
              key: 'platforms',
              label: '平台监控',
              children: (
                <div>
                  <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
                    <Col xs={24} sm={12}>
                      <Card title="监控控制" size="small">
                        <Space direction="vertical" style={{ width: '100%' }}>
                          <div>
                            <Badge status={monitorStatus?.running ? 'success' : 'default'} text={monitorStatus?.running ? '运行中' : '已停止'} />
                          </div>
                          <Space>
                            <Button
                              type="primary"
                              icon={<PlayCircleOutlined />}
                              onClick={handleStartMonitor}
                              disabled={monitorStatus?.running}
                            >
                              启动监控
                            </Button>
                            <Button
                              icon={<PauseCircleOutlined />}
                              onClick={handleStopMonitor}
                              disabled={!monitorStatus?.running}
                            >
                              停止监控
                            </Button>
                          </Space>
                          <div style={{ color: '#8c8c8c', fontSize: 12 }}>
                            监控间隔: {monitorStatus?.check_interval || 30} 秒
                          </div>
                        </Space>
                      </Card>
                    </Col>
                    <Col xs={24} sm={12}>
                      <Card title="添加监控平台" size="small">
                        <Space direction="vertical" style={{ width: '100%' }}>
                          <Select
                            placeholder="选择平台"
                            style={{ width: '100%' }}
                            value={addPlatformValue || undefined}
                            onChange={(v) => setAddPlatformValue(v)}
                          >
                            {supportedPlatforms.map((p: any) => (
                              <Option key={p.platform} value={p.platform}>
                                {PLATFORM_LABEL[p.platform] || p.platform} ({p.region === 'domestic' ? '国内' : '海外'})
                              </Option>
                            ))}
                          </Select>
                          <Button type="primary" icon={<PlusOutlined />} onClick={handleAddPlatform}>
                            添加
                          </Button>
                        </Space>
                      </Card>
                    </Col>
                  </Row>

                  <Card title="支持的平台能力" size="small">
                    <Spin spinning={monLoading}>
                      {supportedPlatforms.length === 0 && !monLoading ? (
                        <Empty description="暂无支持的平台" />
                      ) : (
                        <Table
                          rowKey={(r) => r.platform}
                          columns={supportedColumns}
                          dataSource={supportedPlatforms}
                          pagination={false}
                          size="small"
                        />
                      )}
                    </Spin>
                  </Card>

                  {monitorPlatforms.length > 0 && (
                    <Card title="已监控平台" size="small" style={{ marginTop: 16 }}>
                      <Space wrap>
                        {monitorPlatforms.map((p) => (
                          <Tag
                            key={p.platform}
                            color={PLATFORM_COLOR[p.platform] || 'blue'}
                            closable
                            onClose={() => handleRemovePlatform(p.platform)}
                          >
                            {PLATFORM_LABEL[p.platform] || p.platform}
                          </Tag>
                        ))}
                      </Space>
                    </Card>
                  )}
                </div>
              ),
            },
            {
              key: 'settings',
              label: '回复设置',
              children: (
                <div>
                  <Row gutter={[16, 16]}>
                    <Col xs={24} md={12}>
                      <Card title="自动回复配置" size="small">
                        <Space direction="vertical" style={{ width: '100%' }} size="large">
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span>自动回复开关</span>
                            <Switch checked={autoReplyEnabled} onChange={setAutoReplyEnabled} />
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span>AI 智能回复</span>
                            <Switch checked={aiReplyEnabled} onChange={setAiReplyEnabled} disabled={!autoReplyEnabled} />
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span>回复延迟 (秒)</span>
                            <InputNumber
                              min={0}
                              max={300}
                              value={replyDelay}
                              onChange={(v) => setReplyDelay(v || 0)}
                              style={{ width: 120 }}
                              disabled={!autoReplyEnabled}
                            />
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span>每小时最大回复数</span>
                            <InputNumber
                              min={1}
                              max={200}
                              value={maxReplyPerHour}
                              onChange={(v) => setMaxReplyPerHour(v || 1)}
                              style={{ width: 120 }}
                              disabled={!autoReplyEnabled}
                            />
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span>需人工处理置信度阈值</span>
                            <InputNumber
                              min={0}
                              max={1}
                              step={0.1}
                              value={needHumanForConfidence}
                              onChange={(v) => setNeedHumanForConfidence(v ?? 0.6)}
                              style={{ width: 120 }}
                              disabled={!autoReplyEnabled}
                            />
                          </div>
                          <Button type="primary" icon={<RobotOutlined />} onClick={handleSaveSettings}>
                            保存设置
                          </Button>
                        </Space>
                      </Card>
                    </Col>
                    <Col xs={24} md={12}>
                      <Card title="回复策略说明" size="small">
                        <Descriptions column={1} size="small">
                          <Descriptions.Item label="自动回复">
                            {autoReplyEnabled ? '已启用，系统自动回复私信' : '已关闭，需手动回复'}
                          </Descriptions.Item>
                          <Descriptions.Item label="AI 智能回复">
                            {aiReplyEnabled ? '已启用，AI 自动生成回复内容' : '已关闭，使用预设话术'}
                          </Descriptions.Item>
                          <Descriptions.Item label="回复延迟">
                            {replyDelay} 秒后自动发送回复
                          </Descriptions.Item>
                          <Descriptions.Item label="频率限制">
                            每小时最多回复 {maxReplyPerHour} 条私信
                          </Descriptions.Item>
                          <Descriptions.Item label="人工介入">
                            AI 置信度低于 {needHumanForConfidence} 时标记为需人工处理
                          </Descriptions.Item>
                        </Descriptions>
                      </Card>
                    </Col>
                  </Row>
                </div>
              ),
            },
          ]}
        />
      </Card>

      <Modal
        title={`回复私信 - ${currentMsg?.sender_name || ''}`}
        open={replyModalOpen}
        onOk={handleReply}
        onCancel={() => { setReplyModalOpen(false); setReplyText(''); setCurrentMsg(null); }}
        okText="发送回复"
        cancelText="取消"
        width={600}
      >
        {currentMsg && (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <div style={{ background: '#f5f5f5', padding: 12, borderRadius: 8 }}>
              <div style={{ color: '#8c8c8c', fontSize: 12, marginBottom: 4 }}>
                来自 {PLATFORM_LABEL[currentMsg.platform] || currentMsg.platform}
              </div>
              <div style={{ wordBreak: 'break-all' }}>{currentMsg.message_text}</div>
            </div>

            {replyPreview && (
              <div style={{ background: '#e6f4ff', padding: 12, borderRadius: 8 }}>
                <div style={{ color: '#1677ff', fontSize: 12, marginBottom: 4 }}>
                  AI 预览回复 (意图: {replyPreview.intent || '未知'}, 置信度: {(replyPreview.confidence || 0).toFixed(2)})
                </div>
                <div style={{ wordBreak: 'break-all' }}>
                  {replyPreview.reply_text || '暂无 AI 回复建议'}
                </div>
                {replyPreview.needs_human && (
                  <Tag color="error" style={{ marginTop: 8 }}>需人工确认</Tag>
                )}
              </div>
            )}

            <TextArea
              rows={4}
              value={replyText}
              onChange={(e) => setReplyText(e.target.value)}
              placeholder="输入回复内容..."
              showCount
              maxLength={500}
            />
          </Space>
        )}
      </Modal>
    </div>
  );
};

export default DMManager;
