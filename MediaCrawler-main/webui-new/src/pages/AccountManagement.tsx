import { useCallback, useEffect, useState } from 'react';
import {
  App,
  Button,
  Card,
  Checkbox,
  Col,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Progress,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  type TableColumnsType,
} from 'antd';
import {
  CheckCircleOutlined,
  CloudUploadOutlined,
  EditOutlined,
  PlusOutlined,
  ReloadOutlined,
  StopOutlined,
  UnlockOutlined,
} from '@ant-design/icons';
import { isAxiosError } from 'axios';
import {
  batchCreateAccounts,
  createAccount,
  disableAccount,
  listAccounts,
  resetAccountCooldown,
  updateAccount,
  validateAccount,
  type AccountFilters,
  type AccountInput,
  type AccountRole,
  type AccountStatus,
  type UnifiedAccount,
} from '../api/accounts';

const { Title, Text } = Typography;

const platformOptions = [
  ['douyin', '抖音'], ['xiaohongshu', '小红书'], ['bilibili', '哔哩哔哩'],
  ['weibo', '微博'], ['zhihu', '知乎'], ['kuaishou', '快手'],
  ['x_twitter', 'X / Twitter'], ['wechat_public', '微信公众号'],
  ['wechat_channels', '微信视频号'], ['toutiao', '头条'], ['tiktok', 'TikTok'],
  ['instagram', 'Instagram'], ['youtube', 'YouTube'], ['facebook', 'Facebook'],
].map(([value, label]) => ({ value, label }));

const roleLabels: Record<AccountRole, string> = {
  publisher: '发布账号',
  interactor: '互动账号',
  both: '发布 + 互动',
};

const statusMeta: Record<AccountStatus, { label: string; color: string }> = {
  active: { label: '正常', color: 'green' },
  expired: { label: '已过期', color: 'orange' },
  invalid: { label: '无效', color: 'red' },
  needs_relogin: { label: '需重新登录', color: 'gold' },
  cooldown: { label: '冷却中', color: 'blue' },
  disabled: { label: '已停用', color: 'default' },
};

const capabilityOptions = [
  { label: '图文', value: 'image' },
  { label: '视频', value: 'video' },
  { label: '文章', value: 'article' },
  { label: '评论', value: 'comment' },
  { label: '私信', value: 'dm' },
];

interface AccountFormValues extends Omit<AccountInput, 'auth_data'> {
  auth_secret?: string;
}

function errorMessage(error: unknown): string {
  if (!isAxiosError(error)) return '操作失败，请稍后重试';
  if (!error.response) return '网络连接失败，请检查服务是否启动';
  if (error.response.status === 403) return '当前账号没有操作权限';
  const data = error.response.data as { detail?: string; message?: string } | undefined;
  return data?.detail || data?.message || `请求失败（${error.response.status}）`;
}

export default function AccountManagement() {
  const { message } = App.useApp();
  const [form] = Form.useForm<AccountFormValues>();
  const [items, setItems] = useState<UnifiedAccount[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [filters, setFilters] = useState<AccountFilters>({ page: 1, page_size: 20 });
  const [editorOpen, setEditorOpen] = useState(false);
  const [editing, setEditing] = useState<UnifiedAccount | null>(null);
  const [batchOpen, setBatchOpen] = useState(false);
  const [batchText, setBatchText] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await listAccounts(filters);
      setItems(result.items);
      setTotal(result.total);
    } catch (error) {
      message.error(errorMessage(error));
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [filters, message]);

  useEffect(() => {
    // Initial and filter-driven data synchronisation.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ role: 'publisher', status: 'active', health_score: 100, weight: 100, daily_limit: 0 });
    setEditorOpen(true);
  };

  const openEdit = (account: UnifiedAccount) => {
    setEditing(account);
    form.resetFields();
    form.setFieldsValue({
      platform: account.platform,
      account_name: account.account_name,
      role: account.role,
      status: account.status,
      capabilities: account.capabilities,
      group_name: account.group_name,
      region: account.region,
      priority: account.priority,
      weight: account.weight,
      health_score: account.health_score,
      daily_limit: account.daily_limit,
      auth_secret: undefined,
    });
    setEditorOpen(true);
  };

  const closeEditor = () => {
    form.resetFields();
    setEditing(null);
    setEditorOpen(false);
  };

  const save = async () => {
    try {
      const values = await form.validateFields();
      const { auth_secret: authSecret, ...base } = values;
      const payload: AccountInput = { ...base };
      if (authSecret) payload.auth_data = { cookies: authSecret };
      setSaving(true);
      if (editing) {
        await updateAccount(editing.account_id, payload);
        message.success('账号已更新');
      } else {
        if (!authSecret) {
          form.setFields([{ name: 'auth_secret', errors: ['请输入认证 Cookie / Token'] }]);
          return;
        }
        await createAccount(payload);
        message.success('账号已创建');
      }
      closeEditor();
      await load();
    } catch (error) {
      if (isAxiosError(error)) message.error(errorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const importBatch = async () => {
    setSaving(true);
    try {
      const parsed = JSON.parse(batchText) as AccountInput[];
      if (!Array.isArray(parsed) || parsed.length === 0) throw new Error('批量数据必须是非空 JSON 数组');
      const result = await batchCreateAccounts(parsed);
      if (result.failed.length) {
        message.warning(`成功 ${result.created.length} 条，失败 ${result.failed.length} 条`);
      } else {
        message.success(`已导入 ${result.created.length} 个账号`);
      }
      setBatchText('');
      setBatchOpen(false);
      await load();
    } catch (error) {
      message.error(error instanceof SyntaxError || error instanceof Error && !isAxiosError(error) ? error.message : errorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const columns: TableColumnsType<UnifiedAccount> = [
    {
      title: '账号',
      key: 'account',
      fixed: 'left',
      width: 190,
      render: (_, record) => (
        <Space direction="vertical" size={0}>
          <Text strong>{record.account_name || record.account_id}</Text>
          <Text type="secondary" copyable={{ text: record.account_id }}>{record.account_id}</Text>
        </Space>
      ),
    },
    { title: '平台', dataIndex: 'platform', width: 120, render: value => platformOptions.find(item => item.value === value)?.label || value },
    { title: '角色', dataIndex: 'role', width: 120, render: (value: AccountRole) => <Tag color={value === 'both' ? 'purple' : value === 'publisher' ? 'blue' : 'cyan'}>{roleLabels[value]}</Tag> },
    { title: '状态', dataIndex: 'status', width: 110, render: (value: AccountStatus) => <Tag color={statusMeta[value].color}>{statusMeta[value].label}</Tag> },
    {
      title: '认证',
      dataIndex: 'auth_configured',
      width: 100,
      render: (configured: boolean, record) => configured
        ? <Tooltip title={`已配置字段：${Object.keys(record.auth_preview).join('、') || '认证信息'}`}><Tag color="green">已配置</Tag></Tooltip>
        : <Tag>未配置</Tag>,
    },
    { title: '分组 / 地域', width: 130, render: (_, record) => `${record.group_name || '-'} / ${record.region || '-'}` },
    { title: '健康度', dataIndex: 'health_score', width: 120, render: (value: number) => <Progress percent={value} size="small" status={value < 40 ? 'exception' : 'normal'} /> },
    { title: '今日配额', width: 110, render: (_, record) => `${record.today_count} / ${record.daily_limit || '∞'}` },
    {
      title: '操作',
      key: 'actions',
      fixed: 'right',
      width: 285,
      render: (_, record) => (
        <Space wrap size={4}>
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>编辑</Button>
          <Button size="small" icon={<CheckCircleOutlined />} onClick={async () => {
            try {
              const result = await validateAccount(record.account_id);
              if (result.valid) message.success(result.message);
              else message.warning(result.message);
            } catch (error) { message.error(errorMessage(error)); }
          }}>校验</Button>
          {record.in_cooldown && <Button size="small" icon={<UnlockOutlined />} onClick={async () => {
            try { await resetAccountCooldown(record.account_id); message.success('冷却已解除'); await load(); }
            catch (error) { message.error(errorMessage(error)); }
          }}>解除冷却</Button>}
          {record.status !== 'disabled' && <Popconfirm title="确认停用此账号？" description="账号将不再参与发布和互动调度。" onConfirm={async () => {
            try { await disableAccount(record.account_id); message.success('账号已停用'); await load(); }
            catch (error) { message.error(errorMessage(error)); }
          }}><Button size="small" danger icon={<StopOutlined />}>停用</Button></Popconfirm>}
        </Space>
      ),
    },
  ];

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div>
        <Title level={3} style={{ marginBottom: 4 }}>统一账号管理</Title>
        <Text type="secondary">统一管理发布账号、互动账号和共用账号；认证值只允许录入或替换，不会回显。</Text>
      </div>

      <Card>
        <Row gutter={[12, 12]} align="middle">
          <Col xs={24} sm={12} md={5}><Select allowClear placeholder="全部平台" options={platformOptions} style={{ width: '100%' }} value={filters.platform} onChange={platform => setFilters(current => ({ ...current, platform, page: 1 }))} /></Col>
          <Col xs={24} sm={12} md={4}><Select allowClear placeholder="全部角色" style={{ width: '100%' }} value={filters.role} options={Object.entries(roleLabels).map(([value, label]) => ({ value, label }))} onChange={role => setFilters(current => ({ ...current, role, page: 1 }))} /></Col>
          <Col xs={24} sm={12} md={4}><Select allowClear placeholder="全部状态" style={{ width: '100%' }} value={filters.status} options={Object.entries(statusMeta).map(([value, meta]) => ({ value, label: meta.label }))} onChange={status => setFilters(current => ({ ...current, status, page: 1 }))} /></Col>
          <Col xs={24} sm={12} md={5}><Input allowClear placeholder="分组名称" value={filters.group_name} onChange={event => setFilters(current => ({ ...current, group_name: event.target.value || undefined, page: 1 }))} /></Col>
          <Col flex="auto"><Space wrap><Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button><Button icon={<CloudUploadOutlined />} onClick={() => setBatchOpen(true)}>批量导入</Button><Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增账号</Button></Space></Col>
        </Row>
      </Card>

      <Table<UnifiedAccount>
        rowKey="account_id"
        loading={loading}
        columns={columns}
        dataSource={items}
        scroll={{ x: 1450 }}
        locale={{ emptyText: <Empty description="暂无账号，可点击“新增账号”开始配置" /> }}
        pagination={{
          current: filters.page,
          pageSize: filters.page_size,
          total,
          showSizeChanger: true,
          showTotal: value => `共 ${value} 个账号`,
          onChange: (page, pageSize) => setFilters(current => ({ ...current, page, page_size: pageSize })),
        }}
      />

      <Modal title={editing ? '编辑统一账号' : '新增统一账号'} open={editorOpen} onCancel={closeEditor} onOk={() => void save()} confirmLoading={saving} width={760} destroyOnHidden>
        <Form form={form} layout="vertical" autoComplete="off">
          <Row gutter={16}>
            <Col span={12}><Form.Item name="platform" label="平台" rules={[{ required: true, message: '请选择平台' }]}><Select options={platformOptions} /></Form.Item></Col>
            <Col span={12}><Form.Item name="account_name" label="账号名称" rules={[{ required: true, message: '请输入账号名称' }]}><Input maxLength={128} /></Form.Item></Col>
            <Col span={12}><Form.Item name="role" label="业务角色" rules={[{ required: true }]}><Select options={Object.entries(roleLabels).map(([value, label]) => ({ value, label }))} /></Form.Item></Col>
            <Col span={12}><Form.Item name="status" label="状态" rules={[{ required: true }]}><Select options={Object.entries(statusMeta).map(([value, meta]) => ({ value, label: meta.label }))} /></Form.Item></Col>
            <Col span={24}><Form.Item name="auth_secret" label={editing ? '替换认证 Cookie / Token（留空则保持不变）' : '认证 Cookie / Token'}><Input.Password visibilityToggle={false} autoComplete="new-password" placeholder="认证值不会回显或写入浏览器存储" /></Form.Item></Col>
            <Col span={24}><Form.Item name="capabilities" label="能力"><Checkbox.Group options={capabilityOptions} /></Form.Item></Col>
            <Col span={8}><Form.Item name="group_name" label="分组"><Input maxLength={64} /></Form.Item></Col>
            <Col span={8}><Form.Item name="region" label="地域"><Input maxLength={16} placeholder="cn / us / eu" /></Form.Item></Col>
            <Col span={8}><Form.Item name="daily_limit" label="每日配额（0 为不限）"><InputNumber min={0} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={8}><Form.Item name="priority" label="优先级"><InputNumber min={0} max={10000} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={8}><Form.Item name="weight" label="权重"><InputNumber min={0} max={10000} style={{ width: '100%' }} /></Form.Item></Col>
            <Col span={8}><Form.Item name="health_score" label="健康度"><InputNumber min={0} max={100} style={{ width: '100%' }} /></Form.Item></Col>
          </Row>
        </Form>
      </Modal>

      <Modal title="批量导入统一账号" open={batchOpen} onCancel={() => { setBatchText(''); setBatchOpen(false); }} onOk={() => void importBatch()} confirmLoading={saving} width={720} destroyOnHidden>
        <Text type="secondary">请输入 JSON 数组，每项字段与新增账号一致；关闭窗口后输入内容会立即清空。</Text>
        <Input.TextArea value={batchText} onChange={event => setBatchText(event.target.value)} rows={12} autoComplete="off" placeholder={'[{"platform":"douyin","account_name":"运营号1","role":"both","auth_data":{"cookies":"..."}}]'} style={{ marginTop: 12, fontFamily: 'monospace' }} />
      </Modal>
    </Space>
  );
}
