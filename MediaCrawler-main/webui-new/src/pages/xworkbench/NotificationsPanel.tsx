import { message } from '../../utils/antdMessage';
import { useEffect, useState, useCallback, useMemo } from 'react';
import { Card, Table, Button, Space, Modal, Form, Input, Select, Switch, InputNumber, Tag, Tooltip, Typography, Popconfirm, Empty } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  ReloadOutlined,
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  ThunderboltOutlined,
  BellOutlined,
  MailOutlined,
  MessageOutlined,
  ApiOutlined,
} from '@ant-design/icons';
import {
  xWorkbenchApi,
  type NotificationChannel,
  type ChannelTypeOption,
} from '../../api/xWorkbench';

const { Text, Paragraph } = Typography;

/**
 * 通知渠道管理面板
 *
 * 支持邮件、钉钉、企业微信、自定义 webhook 等多种渠道,
 * 在收到新回复、AI 回复失败等事件时自动推送通知。
 */
const NotificationsPanel: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [list, setList] = useState<NotificationChannel[]>([]);
  const [channelTypes, setChannelTypes] = useState<ChannelTypeOption[]>([]);
  const [eventTypes, setEventTypes] = useState<ChannelTypeOption[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<NotificationChannel | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [testingId, setTestingId] = useState<number | null>(null);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await xWorkbenchApi.listNotificationChannels();
      setList(r.items || []);
    } catch (e: any) {
      message.error('加载失败: ' + (e?.message || ''));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadMeta = useCallback(async () => {
    try {
      const r = await xWorkbenchApi.notificationMeta();
      setChannelTypes(r.channels || []);
      setEventTypes(r.events || []);
    } catch {}
  }, []);

  useEffect(() => {
    load();
    loadMeta();
  }, [load, loadMeta]);

  // 打开新建/编辑 Modal
  const openModal = useCallback((ch: NotificationChannel | null) => {
    setEditing(ch);
    if (ch) {
      form.setFieldsValue({
        name: ch.name,
        channel_type: ch.channel_type,
        events: ch.events,
        is_active: ch.is_active === 1,
        min_interval_seconds: ch.min_interval_seconds,
        note: ch.note,
        // 展开 config 到表单字段
        email_to: ch.config?.email_to || '',
        webhook_url: ch.config?.webhook_url || '',
        secret: ch.config?.secret || '',
        at_mobiles: ch.config?.at_mobiles || '',
        is_at_all: ch.config?.is_at_all || false,
        mentioned_list: ch.config?.mentioned_list || '',
        headers: ch.config?.headers ? JSON.stringify(ch.config.headers, null, 2) : '',
      });
    } else {
      form.resetFields();
      form.setFieldsValue({
        channel_type: 'email',
        events: ['new_reply'],
        is_active: true,
        min_interval_seconds: 60,
      });
    }
    setModalOpen(true);
  }, [form]);

  // 提交表单
  const handleSubmit = useCallback(async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);

      // 根据渠道类型组装 config
      const config: Record<string, any> = {};
      if (values.channel_type === 'email') {
        config.email_to = values.email_to?.trim() || '';
      } else if (values.channel_type === 'dingtalk') {
        config.webhook_url = values.webhook_url?.trim() || '';
        config.secret = values.secret?.trim() || '';
        config.at_mobiles = values.at_mobiles?.trim() || '';
        config.is_at_all = !!values.is_at_all;
      } else if (values.channel_type === 'wechat_work') {
        config.webhook_url = values.webhook_url?.trim() || '';
        config.mentioned_list = values.mentioned_list?.trim() || '';
      } else if (values.channel_type === 'custom_webhook') {
        config.webhook_url = values.webhook_url?.trim() || '';
        config.secret = values.secret?.trim() || '';
        if (values.headers?.trim()) {
          try {
            config.headers = JSON.parse(values.headers);
          } catch {
            message.error('自定义请求头必须是合法 JSON');
            setSubmitting(false);
            return;
          }
        }
      }

      const payload = {
        name: values.name.trim(),
        channel_type: values.channel_type,
        config,
        events: values.events || [],
        is_active: !!values.is_active,
        min_interval_seconds: values.min_interval_seconds || 60,
        note: values.note || '',
      };

      if (editing) {
        await xWorkbenchApi.updateNotificationChannel(editing.id, payload);
        message.success('已更新');
      } else {
        await xWorkbenchApi.createNotificationChannel(payload);
        message.success('已创建');
      }
      setModalOpen(false);
      load();
    } catch (e: any) {
      if (e?.errorFields) return; // 表单校验错误,Form 已提示
      message.error('保存失败: ' + (e?.message || ''));
    } finally {
      setSubmitting(false);
    }
  }, [form, editing, load]);

  // 切换启用状态
  const toggleActive = useCallback(async (ch: NotificationChannel, checked: boolean) => {
    try {
      await xWorkbenchApi.updateNotificationChannel(ch.id, { is_active: checked });
      message.success(checked ? '已启用' : '已禁用');
      load();
    } catch (e: any) {
      message.error('操作失败: ' + (e?.message || ''));
    }
  }, [load]);

  // 删除(软删除)
  const handleDelete = useCallback(async (ch: NotificationChannel) => {
    try {
      await xWorkbenchApi.deleteNotificationChannel(ch.id);
      message.success('已删除');
      load();
    } catch (e: any) {
      message.error('删除失败: ' + (e?.message || ''));
    }
  }, [load]);

  // 测试推送
  const handleTest = useCallback(async (ch: NotificationChannel) => {
    setTestingId(ch.id);
    try {
      const r = await xWorkbenchApi.testNotificationChannel(ch.id);
      message.success(r.message || '推送成功');
      load();
    } catch (e: any) {
      message.error('测试失败: ' + (e?.message || ''));
    } finally {
      setTestingId(null);
    }
  }, [load]);

  // 当前表单选中的渠道类型(用于动态显示配置字段)
  const watchChannelType = Form.useWatch('channel_type', form);
  const watchEvents = Form.useWatch('events', form);

  // 渠道类型图标/标签映射
  const channelTypeMeta = useMemo(() => ({
    email: { icon: <MailOutlined />, color: 'blue', label: '邮件' },
    dingtalk: { icon: <MessageOutlined />, color: 'blue', label: '钉钉' },
    wechat_work: { icon: <MessageOutlined />, color: 'green', label: '企业微信' },
    custom_webhook: { icon: <ApiOutlined />, color: 'purple', label: '自定义' },
  }) as Record<string, { icon: React.ReactNode; color: string; label: string }>, []);

  // 事件标签映射
  const eventLabelMap = useMemo(() => {
    const m: Record<string, string> = {};
    eventTypes.forEach(e => { m[e.value] = e.label; });
    return m;
  }, [eventTypes]);

  const columns: ColumnsType<NotificationChannel> = useMemo(() => [
    {
      title: '名称',
      dataIndex: 'name',
      render: (name, r) => {
        const meta = channelTypeMeta[r.channel_type] || channelTypeMeta.custom_webhook;
        return (
          <Space>
            <Tag color={meta.color} icon={meta.icon}>{meta.label}</Tag>
            <Text strong>{name}</Text>
          </Space>
        );
      },
    },
    {
      title: '订阅事件',
      dataIndex: 'events',
      render: (events: string[]) => (
        <Space size={[4, 4]} wrap>
          {events && events.length > 0 ? events.map(e => (
            <Tag key={e} color="processing">{eventLabelMap[e] || e}</Tag>
          )) : <Text type="secondary">未订阅</Text>}
        </Space>
      ),
    },
    {
      title: '推送统计',
      width: 140,
      render: (_, r) => (
        <Space direction="vertical" size={0}>
          <Text type="success">成功 {r.success_count || 0}</Text>
          <Text type="danger">失败 {r.fail_count || 0}</Text>
        </Space>
      ),
    },
    {
      title: '限频',
      dataIndex: 'min_interval_seconds',
      width: 90,
      render: (s) => <Text type="secondary">{s}s</Text>,
    },
    {
      title: '启用',
      dataIndex: 'is_active',
      width: 70,
      render: (active, r) => (
        <Switch checked={active === 1} size="small" onChange={(c) => toggleActive(r, c)} />
      ),
    },
    {
      title: '上次触发',
      dataIndex: 'last_trigger_ts',
      width: 160,
      render: (t) => t ? new Date(t * 1000).toLocaleString('zh-CN') : <Text type="secondary">从未触发</Text>,
    },
    {
      title: '操作',
      width: 220,
      render: (_, r) => (
        <Space size="small">
          <Button
            size="small"
            icon={<ThunderboltOutlined />}
            loading={testingId === r.id}
            onClick={() => handleTest(r)}
          >
            测试
          </Button>
          <Button size="small" icon={<EditOutlined />} onClick={() => openModal(r)}>
            编辑
          </Button>
          <Popconfirm
            title="确定删除该通知渠道?"
            description="删除后将停止该渠道的通知推送"
            onConfirm={() => handleDelete(r)}
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ], [channelTypeMeta, eventLabelMap, testingId, handleTest, openModal, handleDelete, toggleActive]);

  return (
    <div>
      <Card
        size="small"
        title={
          <Space>
            <BellOutlined />
            <span>通知渠道管理</span>
          </Space>
        }
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => openModal(null)}>
              新建渠道
            </Button>
          </Space>
        }
      >
        <Paragraph type="secondary" style={{ marginBottom: 12 }}>
          配置邮件、钉钉、企业微信等通知渠道,在收到新回复、AI 回复失败等事件时自动推送通知。
          每个渠道可独立订阅事件类型,并设置最小触发间隔避免频繁打扰。
        </Paragraph>
        <Table
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={list}
          size="middle"
          pagination={{ pageSize: 10, size: 'small' }}
          locale={{
            emptyText: <Empty description="暂无通知渠道,点击「新建渠道」开始配置" />,
          }}
        />
      </Card>

      <Modal
        title={editing ? '编辑通知渠道' : '新建通知渠道'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleSubmit}
        confirmLoading={submitting}
        width={640}
        destroyOnClose
        okText={editing ? '保存' : '创建'}
        cancelText="取消"
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="name"
            label="渠道名称"
            rules={[{ required: true, message: '请输入渠道名称' }]}
          >
            <Input placeholder="如:管理员邮箱、产品反馈钉钉群" maxLength={64} />
          </Form.Item>

          <Form.Item
            name="channel_type"
            label="渠道类型"
            rules={[{ required: true, message: '请选择渠道类型' }]}
          >
            <Select
              options={channelTypes}
              disabled={!!editing}
              placeholder="选择渠道类型"
            />
          </Form.Item>

          {/* 动态显示渠道配置字段 */}
          {watchChannelType === 'email' && (
            <Form.Item
              name="email_to"
              label="收件邮箱"
              rules={[{ required: true, message: '请输入收件邮箱' }, { type: 'email', message: '邮箱格式不正确' }]}
            >
              <Input placeholder="admin@example.com" />
            </Form.Item>
          )}

          {(watchChannelType === 'dingtalk' || watchChannelType === 'wechat_work' || watchChannelType === 'custom_webhook') && (
            <Form.Item
              name="webhook_url"
              label="Webhook URL"
              rules={[{ required: true, message: '请输入 webhook URL' }]}
            >
              <Input placeholder="https://oapi.dingtalk.com/robot/send?access_token=..." />
            </Form.Item>
          )}

          {watchChannelType === 'dingtalk' && (
            <>
              <Form.Item name="secret" label="加签密钥(可选)">
                <Input.Password placeholder="SEC... (机器人安全设置中的加签密钥)" />
              </Form.Item>
              <Form.Item name="at_mobiles" label="@ 手机号(可选,逗号分隔)">
                <Input placeholder="13800138000,13900139000" />
              </Form.Item>
              <Form.Item name="is_at_all" label="@ 所有人" valuePropName="checked">
                <Switch />
              </Form.Item>
            </>
          )}

          {watchChannelType === 'wechat_work' && (
            <Form.Item name="mentioned_list" label="@ 用户ID(可选,逗号分隔,@all 表示所有人)">
              <Input placeholder="zhangsan,@all" />
            </Form.Item>
          )}

          {watchChannelType === 'custom_webhook' && (
            <>
              <Form.Item name="secret" label="签名密钥(可选,放在 X-Webhook-Secret 头中)">
                <Input.Password placeholder="whsec_xxx" />
              </Form.Item>
              <Form.Item name="headers" label="自定义请求头(JSON 格式,可选)">
                <Input.TextArea
                  rows={3}
                  placeholder='{"X-Custom-Header": "value"}'
                  style={{ fontFamily: 'monospace' }}
                />
              </Form.Item>
            </>
          )}

          <Form.Item
            name="events"
            label="订阅事件"
            rules={[{ required: true, message: '请至少选择一个事件' }]}
          >
            <Select
              mode="multiple"
              options={eventTypes}
              placeholder="选择要订阅的事件类型"
            />
          </Form.Item>

          {watchEvents && watchEvents.length > 0 && (
            <Paragraph type="secondary" style={{ fontSize: 12, marginTop: -8, marginBottom: 12 }}>
              <Tooltip title="事件说明">
                <Text type="secondary">
                  将订阅 {watchEvents.length} 个事件,触发后会按所选渠道推送通知。
                </Text>
              </Tooltip>
            </Paragraph>
          )}

          <Form.Item name="min_interval_seconds" label="最小触发间隔(秒)">
            <InputNumber min={0} max={86400} style={{ width: '100%' }} placeholder="60" />
          </Form.Item>

          <Form.Item name="is_active" label="启用" valuePropName="checked">
            <Switch />
          </Form.Item>

          <Form.Item name="note" label="备注">
            <Input.TextArea rows={2} placeholder="可选,渠道用途说明" maxLength={200} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default NotificationsPanel;
