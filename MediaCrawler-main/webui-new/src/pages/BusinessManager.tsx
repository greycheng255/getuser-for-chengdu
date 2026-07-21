import React, { useEffect, useState, useCallback } from 'react';
import {
  Card, Tabs, Table, Button, Space, Modal, Form, Input, Select, InputNumber,
  message, Tag, Row, Col, Statistic, Tooltip, Popconfirm, Switch, Descriptions, Divider
} from 'antd';
import {
  UserOutlined, TeamOutlined, AppstoreOutlined, ApiOutlined, DollarOutlined,
  PlusOutlined, ReloadOutlined, KeyOutlined, SendOutlined, ShopOutlined, PhoneOutlined
} from '@ant-design/icons';
import dayjs from 'dayjs';
import type {
  BusinessUser, LeadPackage, ApiClient, BusinessStats, AssignedLead, FollowUpRecord,
} from '../api/business';
import {
  getBusinessUsers, createBusinessUser, updateBusinessUser, rechargeUserBalance, resetUserApiKey,
  getLeadPackages, createLeadPackage, updateLeadPackage, publishLeadPackage, discontinueLeadPackage, deleteLeadPackage,
  purchaseLeadPackage, getAssignedLeads, getFollowUps, createFollowUp,
  getApiClients, createApiClient, updateApiClient, toggleApiClientStatus, triggerPushToClient,
  getBusinessStats
} from '../api/business';
import { getTasks } from '../api/tasks';

const { Option } = Select;
const { TextArea } = Input;

// 格式化金额(分转元)
const formatMoney = (cents: number) => `¥${(cents / 100).toFixed(2)}`;
// 格式化时间戳
const formatTs = (ts: number) => ts ? dayjs(ts).format('YYYY-MM-DD HH:mm') : '-';

const BusinessManager: React.FC = () => {
  // 统计
  const [stats, setStats] = useState<BusinessStats | null>(null);
  // 业务用户
  const [users, setUsers] = useState<BusinessUser[]>([]);
  const [usersTotal, setUsersTotal] = useState(0);
  const [usersPage, setUsersPage] = useState(1);
  const [usersLoading, setUsersLoading] = useState(false);
  // 线索包
  const [packages, setPackages] = useState<LeadPackage[]>([]);
  const [packagesTotal, setPackagesTotal] = useState(0);
  const [packagesPage, setPackagesPage] = useState(1);
  const [packagesLoading, setPackagesLoading] = useState(false);
  // API客户端
  const [apiClients, setApiClients] = useState<ApiClient[]>([]);
  const [apiClientsTotal, setApiClientsTotal] = useState(0);
  const [apiClientsLoading, setApiClientsLoading] = useState(false);
  // 已分配线索
  const [assignedLeads, setAssignedLeads] = useState<AssignedLead[]>([]);
  const [assignedTotal, setAssignedTotal] = useState(0);
  const [assignedLoading, setAssignedLoading] = useState(false);
  // 跟进记录
  const [followUps, setFollowUps] = useState<FollowUpRecord[]>([]);
  const [followUpsTotal, setFollowUpsTotal] = useState(0);
  const [followUpsLoading, setFollowUpsLoading] = useState(false);
  // 任务列表(用于筛选)
  const [tasks, setTasks] = useState<any[]>([]);
  // 弹窗
  const [createUserModal, setCreateUserModal] = useState(false);
  const [createPackageModal, setCreatePackageModal] = useState(false);
  const [editPackageModal, setEditPackageModal] = useState(false);
  const [createApiClientModal, setCreateApiClientModal] = useState(false);
  const [editApiClientModal, setEditApiClientModal] = useState(false);
  const [selectedApiClient, setSelectedApiClient] = useState<ApiClient | null>(null);
  const [rechargeModal, setRechargeModal] = useState(false);
  const [purchaseModal, setPurchaseModal] = useState(false);
  const [selectedUser, setSelectedUser] = useState<BusinessUser | null>(null);
  const [selectedPackage, setSelectedPackage] = useState<LeadPackage | null>(null);
  // 表单
  const [userForm] = Form.useForm();
  const [packageForm] = Form.useForm();
  const [apiClientForm] = Form.useForm();
  const [rechargeForm] = Form.useForm();
  const [purchaseForm] = Form.useForm();

  // 加载统计
  const fetchStats = useCallback(async () => {
    try {
      const res = await getBusinessStats();
      setStats(res);
    } catch (e) {
      console.error('Failed to fetch stats:', e);
    }
  }, []);

  // 加载业务用户
  const fetchUsers = useCallback(async (page = 1) => {
    setUsersLoading(true);
    try {
      const res = await getBusinessUsers({ page, page_size: 20 });
      setUsers(res.items);
      setUsersTotal(res.total);
      setUsersPage(page);
    } catch (e) {
      message.error('获取用户列表失败');
    } finally {
      setUsersLoading(false);
    }
  }, []);

  // 加载线索包
  const fetchPackages = useCallback(async (page = 1) => {
    setPackagesLoading(true);
    try {
      const res = await getLeadPackages({ page, page_size: 20 });
      setPackages(res.items);
      setPackagesTotal(res.total);
      setPackagesPage(page);
    } catch (e) {
      message.error('获取线索包列表失败');
    } finally {
      setPackagesLoading(false);
    }
  }, []);

  // 加载API客户端
  const fetchApiClients = useCallback(async () => {
    setApiClientsLoading(true);
    try {
      const res = await getApiClients({ page: 1, page_size: 50 });
      setApiClients(res.items);
      setApiClientsTotal(res.total);
    } catch (e) {
      message.error('获取API客户端列表失败');
    } finally {
      setApiClientsLoading(false);
    }
  }, []);

  // 加载已分配线索
  const fetchAssignedLeads = useCallback(async (page = 1) => {
    setAssignedLoading(true);
    try {
      const res = await getAssignedLeads({ page, page_size: 20 });
      setAssignedLeads(res.items);
      setAssignedTotal(res.total);
    } catch (e) {
      message.error('获取已分配线索失败');
    } finally {
      setAssignedLoading(false);
    }
  }, []);

  // 加载任务列表
  const fetchTasks = useCallback(async () => {
    try {
      const res = await getTasks();
      setTasks(res || []);
    } catch (e) {
      // ignore
    }
  }, []);

  // 初始化
  useEffect(() => {
    fetchStats();
    fetchUsers();
    fetchPackages();
    fetchApiClients();
    fetchAssignedLeads();
    fetchTasks();
  }, [fetchStats, fetchUsers, fetchPackages, fetchApiClients, fetchAssignedLeads, fetchTasks]);

  // 创建业务用户
  const handleCreateUser = async (values: any) => {
    try {
      await createBusinessUser(values);
      message.success('创建成功');
      setCreateUserModal(false);
      userForm.resetFields();
      fetchUsers();
      fetchStats();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '创建失败');
    }
  };

  // 充值
  const handleRecharge = async (values: any) => {
    if (!selectedUser) return;
    try {
      const res = await rechargeUserBalance(selectedUser.id, values.amount * 100); // 元转分
      message.success(`充值成功，当前余额: ${formatMoney(res.balance)}`);
      setRechargeModal(false);
      rechargeForm.resetFields();
      fetchUsers();
      fetchStats();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '充值失败');
    }
  };

  // 重置API密钥
  const handleResetApiKey = async (userId: string) => {
    try {
      const res = await resetUserApiKey(userId);
      message.success(`新API密钥: ${res.api_key}`);
      fetchUsers();
    } catch (e: any) {
      message.error('重置失败');
    }
  };

  // 创建线索包
  const handleCreatePackage = async (values: any) => {
    try {
      const data = {
        ...values,
        price_per_lead: values.price_per_lead * 100, // 元转分
      };
      await createLeadPackage(data);
      message.success('创建成功，请发布后客户方可购买');
      setCreatePackageModal(false);
      packageForm.resetFields();
      fetchPackages();
      fetchStats();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '创建失败');
    }
  };

  // 编辑线索包
  const handleEditPackage = (pkg: LeadPackage) => {
    setSelectedPackage(pkg);
    packageForm.setFieldsValue({
      name: pkg.name,
      description: pkg.description,
      price_per_lead: pkg.price_per_lead / 100, // 分转元
      expire_days: pkg.expire_days,
    });
    setEditPackageModal(true);
  };

  // 保存编辑线索包
  const handleSavePackage = async (values: any) => {
    try {
      if (!selectedPackage) return;
      const data: any = {};
      if (values.name !== undefined) data.name = values.name;
      if (values.description !== undefined) data.description = values.description;
      if (values.price_per_lead !== undefined) data.price_per_lead = values.price_per_lead * 100;
      if (values.expire_days !== undefined) data.expire_days = values.expire_days;
      await updateLeadPackage(selectedPackage.id, data);
      message.success('更新成功');
      setEditPackageModal(false);
      packageForm.resetFields();
      setSelectedPackage(null);
      fetchPackages();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '更新失败');
    }
  };

  // 发布线索包
  const handlePublishPackage = async (packageId: string) => {
    try {
      await publishLeadPackage(packageId);
      message.success('发布成功');
      fetchPackages();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '发布失败');
    }
  };

  // 下架线索包
  const handleDiscontinuePackage = async (packageId: string) => {
    try {
      await discontinueLeadPackage(packageId);
      message.success('已下架');
      fetchPackages();
    } catch (e: any) {
      message.error('下架失败');
    }
  };

  // 删除线索包
  const handleDeletePackage = async (packageId: string) => {
    try {
      await deleteLeadPackage(packageId);
      message.success('已删除');
      fetchPackages();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '删除失败');
    }
  };

  // 购买线索包
  const handlePurchase = async (values: any) => {
    if (!selectedPackage) return;
    try {
      const res = await purchaseLeadPackage({
        package_id: selectedPackage.id,
        lead_count: values.lead_count,
        payment_method: 'balance',
      });
      message.success(`购买成功，分配了 ${res.assigned_count} 条线索`);
      setPurchaseModal(false);
      purchaseForm.resetFields();
      fetchPackages();
      fetchAssignedLeads();
      fetchStats();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '购买失败');
    }
  };

  // 创建API客户端
  const handleCreateApiClient = async (values: any) => {
    try {
      await createApiClient(values);
      message.success('创建成功');
      setCreateApiClientModal(false);
      apiClientForm.resetFields();
      fetchApiClients();
    } catch (e: any) {
      message.error('创建失败');
    }
  };

  // 触发推送
  const handleTriggerPush = async (clientId: string) => {
    try {
      const res = await triggerPushToClient(clientId, 50);
      message.success(res.message || `推送了 ${res.pushed_count} 条线索`);
      fetchApiClients();
    } catch (e: any) {
      message.error('推送失败');
    }
  };

  // 编辑API客户端
  const handleEditApiClient = (client: ApiClient) => {
    setSelectedApiClient(client);
    apiClientForm.setFieldsValue({
      name: client.name,
      webhook_url: client.webhook_url,
      callback_url: client.callback_url,
      push_mode: client.push_mode,
      push_interval: client.push_interval,
    });
    setEditApiClientModal(true);
  };

  // 保存编辑API客户端
  const handleSaveApiClient = async (values: any) => {
    try {
      if (!selectedApiClient) return;
      await updateApiClient(selectedApiClient.id, values);
      message.success('更新成功');
      setEditApiClientModal(false);
      apiClientForm.resetFields();
      setSelectedApiClient(null);
      fetchApiClients();
    } catch (e: any) {
      message.error('更新失败');
    }
  };

  // 切换API客户端状态
  const handleToggleApiClient = async (clientId: string) => {
    try {
      const res = await toggleApiClientStatus(clientId);
      message.success(res.status === 'active' ? '已启用' : '已禁用');
      fetchApiClients();
    } catch (e: any) {
      message.error('操作失败');
    }
  };

  // 用户表格列
  const userColumns = [
    { title: '用户名', dataIndex: 'username', width: 120 },
    { title: '昵称', dataIndex: 'nickname', width: 120 },
    { title: '角色', dataIndex: 'role', width: 80, render: (v: string) => (
      <Tag color={v === 'customer' ? 'blue' : v === 'sales' ? 'green' : 'red'}>
        {v === 'customer' ? '客户' : v === 'sales' ? '销售' : '管理员'}
      </Tag>
    )},
    { title: '公司', dataIndex: 'company_name', width: 150, ellipsis: true },
    { title: '余额', dataIndex: 'balance', width: 100, render: (v: number) => formatMoney(v) },
    { title: '已分配', dataIndex: 'assigned_leads_count', width: 80 },
    { title: '已转化', dataIndex: 'converted_leads_count', width: 80 },
    { title: '状态', dataIndex: 'status', width: 80, render: (v: string) => (
      <Tag color={v === 'active' ? 'success' : 'error'}>{v === 'active' ? '正常' : '禁用'}</Tag>
    )},
    { title: '创建时间', dataIndex: 'created_ts', width: 120, render: (v: number) => formatTs(v) },
    { title: '操作', width: 180, render: (_: any, record: BusinessUser) => (
      <Space size="small">
        <Button size="small" icon={<DollarOutlined />} onClick={() => { setSelectedUser(record); setRechargeModal(true); }}>充值</Button>
        <Tooltip title="重置API密钥">
          <Button size="small" icon={<KeyOutlined />} onClick={() => handleResetApiKey(record.id)} />
        </Tooltip>
      </Space>
    )},
  ];

  // 线索包表格列
  const packageColumns = [
    { title: '包名', dataIndex: 'name', width: 150, ellipsis: true },
    { title: '平台', dataIndex: 'platform', width: 80, render: (v: string) => v || '全部' },
    { title: '意向等级', dataIndex: 'level', width: 80, render: (v: string) => (
      <Tag color={v === 'high' ? 'red' : v === 'medium' ? 'orange' : v === 'low' ? 'default' : 'blue'}>
        {v === 'high' ? '高意向' : v === 'medium' ? '中意向' : v === 'low' ? '低意向' : '全部'}
      </Tag>
    )},
    { title: '地域', dataIndex: 'ip_location', width: 100, ellipsis: true },
    { title: '总数', dataIndex: 'total_count', width: 80 },
    { title: '可售', dataIndex: 'available_count', width: 80, render: (v: number) => v > 0 ? <Tag color="green">{v}</Tag> : <Tag color="red">0</Tag> },
    { title: '单价', dataIndex: 'price_per_lead', width: 80, render: (v: number) => formatMoney(v) },
    { title: '状态', dataIndex: 'status', width: 80, render: (v: string) => (
      <Tag color={v === 'active' ? 'success' : v === 'draft' ? 'default' : 'error'}>
        {v === 'active' ? '上架' : v === 'draft' ? '草稿' : v === 'sold_out' ? '售罄' : '下架'}
      </Tag>
    )},
    { title: '操作', width: 240, render: (_: any, record: LeadPackage) => (
      <Space size="small">
        <Button size="small" onClick={() => handleEditPackage(record)}>编辑</Button>
        {record.status === 'draft' && (
          <>
            <Button size="small" type="primary" onClick={() => handlePublishPackage(record.id)}>发布</Button>
            <Popconfirm title="确定删除?" onConfirm={() => handleDeletePackage(record.id)}>
              <Button size="small" danger>删除</Button>
            </Popconfirm>
          </>
        )}
        {record.status === 'active' && (
          <>
            <Button size="small" type="primary" onClick={() => { setSelectedPackage(record); setPurchaseModal(true); }}>购买</Button>
            <Popconfirm title="确定下架?" onConfirm={() => handleDiscontinuePackage(record.id)}>
              <Button size="small" danger>下架</Button>
            </Popconfirm>
          </>
        )}
      </Space>
    )},
  ];

  // API客户端表格列
  const apiClientColumns = [
    { title: '名称', dataIndex: 'name', width: 150 },
    { title: 'API密钥', dataIndex: 'api_key', width: 200, ellipsis: true },
    { title: 'Webhook地址', dataIndex: 'webhook_url', width: 200, ellipsis: true },
    { title: '推送模式', dataIndex: 'push_mode', width: 80, render: (v: string) => v === 'batch' ? '批量' : '实时' },
    { title: '已推送', dataIndex: 'total_pushed', width: 80 },
    { title: '状态', dataIndex: 'status', width: 80, render: (v: string) => (
      <Tag color={v === 'active' ? 'success' : 'error'}>{v === 'active' ? '正常' : '禁用'}</Tag>
    )},
    { title: '操作', width: 180, render: (_: any, record: ApiClient) => (
      <Space>
        <Button size="small" onClick={() => handleEditApiClient(record)}>编辑</Button>
        <Button size="small" type="primary" icon={<SendOutlined />} onClick={() => handleTriggerPush(record.id)}>推送</Button>
        <Button size="small" danger={record.status === 'active'} onClick={() => handleToggleApiClient(record.id)}>
          {record.status === 'active' ? '禁用' : '启用'}
        </Button>
      </Space>
    )},
  ];

  // 已分配线索表格列
  const assignedLeadColumns = [
    { title: '线索ID', dataIndex: 'lead_id', width: 80 },
    { title: '用户昵称', dataIndex: 'nickname', width: 120, ellipsis: true },
    { title: '内容摘要', dataIndex: 'content', width: 200, ellipsis: true },
    { title: '意向分', dataIndex: 'lead_score', width: 80, render: (v: number) => (
      <Tag color={v >= 50 ? 'red' : v >= 25 ? 'orange' : 'default'}>{v}</Tag>
    )},
    { title: '地域', dataIndex: 'ip_location', width: 80 },
    { title: '状态', dataIndex: 'status', width: 80, render: (v: string) => (
      <Tag color={v === 'assigned' ? 'processing' : v === 'used' ? 'success' : v === 'pulled' ? 'blue' : 'error'}>
        {v === 'assigned' ? '已分配' : v === 'used' ? '已使用' : v === 'pulled' ? '已拉取' : '已过期'}
      </Tag>
    )},
    { title: '分配时间', dataIndex: 'assigned_ts', width: 120, render: (v: number) => formatTs(v) },
    { title: '过期时间', dataIndex: 'expire_ts', width: 120, render: (v: number) => formatTs(v) },
  ];

  return (
    <div style={{ padding: 24 }}>
      {/* 统计概览 */}
      <Card style={{ marginBottom: 24 }}>
        <Row gutter={24}>
          <Col span={4}>
            <Statistic title="客户数" value={stats?.total_customers || 0} prefix={<ShopOutlined />} />
          </Col>
          <Col span={4}>
            <Statistic title="销售数" value={stats?.total_sales || 0} prefix={<TeamOutlined />} />
          </Col>
          <Col span={4}>
            <Statistic title="线索包" value={stats?.total_packages || 0} prefix={<AppstoreOutlined />} />
          </Col>
          <Col span={4}>
            <Statistic title="已分配线索" value={stats?.total_leads_assigned || 0} prefix={<UserOutlined />} />
          </Col>
          <Col span={4}>
            <Statistic title="总收入" value={formatMoney(stats?.total_revenue || 0)} prefix={<DollarOutlined />} />
          </Col>
          <Col span={4}>
            <Statistic title="成交订单" value={stats?.total_orders || 0} prefix={<ApiOutlined />} />
          </Col>
        </Row>
      </Card>

      {/* Tab页 */}
      <Tabs defaultActiveKey="users">
        {/* 客户管理 */}
        <Tabs.TabPane tab="客户管理" key="users">
          <Card>
            <Space style={{ marginBottom: 16 }}>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateUserModal(true)}>创建客户/销售</Button>
              <Button icon={<ReloadOutlined />} onClick={() => fetchUsers(usersPage)}>刷新</Button>
            </Space>
            <Table
              columns={userColumns}
              dataSource={users}
              rowKey="id"
              loading={usersLoading}
              pagination={{
                current: usersPage,
                total: usersTotal,
                pageSize: 20,
                onChange: (page) => fetchUsers(page),
              }}
              scroll={{ x: 1200 }}
            />
          </Card>
        </Tabs.TabPane>

        {/* 线索包管理 */}
        <Tabs.TabPane tab="线索包管理" key="packages">
          <Card>
            <Space style={{ marginBottom: 16 }}>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreatePackageModal(true)}>创建线索包</Button>
              <Button icon={<ReloadOutlined />} onClick={() => fetchPackages(packagesPage)}>刷新</Button>
            </Space>
            <Table
              columns={packageColumns}
              dataSource={packages}
              rowKey="id"
              loading={packagesLoading}
              pagination={{
                current: packagesPage,
                total: packagesTotal,
                pageSize: 20,
                onChange: (page) => fetchPackages(page),
              }}
              scroll={{ x: 1000 }}
            />
          </Card>
        </Tabs.TabPane>

        {/* API对接 */}
        <Tabs.TabPane tab="API对接" key="api">
          <Card>
            <Space style={{ marginBottom: 16 }}>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateApiClientModal(true)}>创建API客户端</Button>
              <Button icon={<ReloadOutlined />} onClick={() => fetchApiClients()}>刷新</Button>
            </Space>
            <Table
              columns={apiClientColumns}
              dataSource={apiClients}
              rowKey="id"
              loading={apiClientsLoading}
              pagination={false}
              scroll={{ x: 900 }}
            />
          </Card>
        </Tabs.TabPane>

        {/* 已分配线索 */}
        <Tabs.TabPane tab="已分配线索" key="assigned">
          <Card>
            <Space style={{ marginBottom: 16 }}>
              <Button icon={<ReloadOutlined />} onClick={() => fetchAssignedLeads()}>刷新</Button>
            </Space>
            <Table
              columns={assignedLeadColumns}
              dataSource={assignedLeads}
              rowKey="assignment_id"
              loading={assignedLoading}
              pagination={{
                current: 1,
                total: assignedTotal,
                pageSize: 20,
                onChange: (page) => fetchAssignedLeads(page),
              }}
              scroll={{ x: 1000 }}
            />
          </Card>
        </Tabs.TabPane>
      </Tabs>

      {/* 创建用户弹窗 */}
      <Modal
        title="创建客户/销售"
        open={createUserModal}
        onCancel={() => { setCreateUserModal(false); userForm.resetFields(); }}
        onOk={() => userForm.submit()}
      >
        <Form form={userForm} onFinish={handleCreateUser} layout="vertical">
          <Form.Item name="username" label="登录账号" rules={[{ required: true }]}>
            <Input placeholder="用于登录的账号名" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, min: 6 }]}>
            <Input.Password placeholder="至少6位" />
          </Form.Item>
          <Form.Item name="nickname" label="显示名称" rules={[{ required: true }]}>
            <Input placeholder="公司名或销售姓名" />
          </Form.Item>
          <Form.Item name="role" label="角色" initialValue="customer" rules={[{ required: true }]}>
            <Select>
              <Option value="customer">客户(家具公司/装修公司)</Option>
              <Option value="sales">销售人员</Option>
            </Select>
          </Form.Item>
          <Form.Item name="company_name" label="公司名称">
            <Input placeholder="公司全称" />
          </Form.Item>
          <Form.Item name="contact_phone" label="联系电话">
            <Input placeholder="手机号" />
          </Form.Item>
          <Form.Item name="contact_email" label="联系邮箱">
            <Input placeholder="邮箱地址" />
          </Form.Item>
          <Form.Item name="sales_region" label="负责地域(销售用)">
            <Input placeholder="如: 广东,四川" />
          </Form.Item>
          <Form.Item name="webhook_url" label="Webhook推送地址(客户用)">
            <Input placeholder="接收线索推送的URL" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 充值弹窗 */}
      <Modal
        title={`为 ${selectedUser?.nickname} 充值`}
        open={rechargeModal}
        onCancel={() => { setRechargeModal(false); rechargeForm.resetFields(); }}
        onOk={() => rechargeForm.submit()}
      >
        <Descriptions column={1} style={{ marginBottom: 16 }}>
          <Descriptions.Item label="当前余额">{selectedUser && formatMoney(selectedUser.balance)}</Descriptions.Item>
        </Descriptions>
        <Form form={rechargeForm} onFinish={handleRecharge} layout="vertical">
          <Form.Item name="amount" label="充值金额(元)" rules={[{ required: true, min: 1 }]}>
            <InputNumber min={1} precision={2} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 创建线索包弹窗 */}
      <Modal
        title="创建线索包"
        open={createPackageModal}
        onCancel={() => { setCreatePackageModal(false); packageForm.resetFields(); }}
        onOk={() => packageForm.submit()}
        width={600}
      >
        <Form form={packageForm} onFinish={handleCreatePackage} layout="vertical">
          <Form.Item name="name" label="包名" rules={[{ required: true }]}>
            <Input placeholder="如: 广东高意向家具线索100条" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <TextArea rows={2} placeholder="详细描述" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="platform" label="平台筛选">
                <Select allowClear placeholder="全部">
                  <Option value="douyin">dy</Option>
                  <Option value="xhs">xhs</Option>
                  <Option value="kuaishou">ks</Option>
                </Select>
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="task_id" label="任务筛选">
                <Select allowClear placeholder="全部" showSearch>
                  {tasks.map(t => <Option key={t.id} value={t.id}>{t.name}</Option>)}
                </Select>
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="level" label="意向等级">
                <Select allowClear placeholder="全部">
                  <Option value="high">高意向(≥50分)</Option>
                  <Option value="medium">中意向(25-49分)</Option>
                  <Option value="low">低意向(&lt;25分)</Option>
                </Select>
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="ip_location" label="地域筛选">
                <Input placeholder="如: 广东,四川" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="keyword" label="关键词筛选">
                <Input placeholder="内容中包含的关键词" />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="price_per_lead" label="单价(元/条)" rules={[
                { required: true, message: '请输入单价' },
                { type: 'number', min: 0.01, message: '单价不能低于0.01元' }
              ]}>
                <InputNumber min={0.01} precision={2} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="expire_days" label="有效期(天)" initialValue={90}>
                <InputNumber min={1} max={365} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      {/* 编辑线索包弹窗 */}
      <Modal
        title="编辑线索包"
        open={editPackageModal}
        onCancel={() => { setEditPackageModal(false); packageForm.resetFields(); setSelectedPackage(null); }}
        onOk={() => packageForm.submit()}
      >
        <Form form={packageForm} onFinish={handleSavePackage} layout="vertical">
          <Form.Item name="name" label="包名" rules={[{ required: true }]}>
            <Input placeholder="如: 广东高意向家具线索100条" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <TextArea rows={2} placeholder="详细描述" />
          </Form.Item>
          <Form.Item name="price_per_lead" label="单价(元/条)" rules={[
            { required: true, message: '请输入单价' },
            { type: 'number', min: 0.01, message: '单价不能低于0.01元' }
          ]}>
            <InputNumber min={0.01} precision={2} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="expire_days" label="有效期(天)">
            <InputNumber min={1} max={365} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 购买弹窗 */}
      <Modal
        title={`购买线索包: ${selectedPackage?.name}`}
        open={purchaseModal}
        onCancel={() => { setPurchaseModal(false); purchaseForm.resetFields(); }}
        onOk={() => purchaseForm.submit()}
      >
        <Descriptions column={2} style={{ marginBottom: 16 }}>
          <Descriptions.Item label="可售数量">{selectedPackage?.available_count}</Descriptions.Item>
          <Descriptions.Item label="单价">{selectedPackage && formatMoney(selectedPackage.price_per_lead)}</Descriptions.Item>
          <Descriptions.Item label="有效期">{selectedPackage?.expire_days}天</Descriptions.Item>
          <Descriptions.Item label="意向等级">
            <Tag color={selectedPackage?.level === 'high' ? 'red' : selectedPackage?.level === 'medium' ? 'orange' : 'default'}>
              {selectedPackage?.level === 'high' ? '高意向' : selectedPackage?.level === 'medium' ? '中意向' : selectedPackage?.level === 'low' ? '低意向' : '全部'}
            </Tag>
          </Descriptions.Item>
        </Descriptions>
        <Divider />
        <Form form={purchaseForm} onFinish={handlePurchase} layout="vertical">
          <Form.Item name="lead_count" label="购买数量" rules={[{ required: true, message: '请输入购买数量' }]} initialValue={1}>
            <InputNumber min={1} max={selectedPackage?.available_count || 1000} precision={0} style={{ width: '100%' }} placeholder="请输入购买数量" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 创建API客户端弹窗 */}
      <Modal
        title="创建API客户端"
        open={createApiClientModal}
        onCancel={() => { setCreateApiClientModal(false); apiClientForm.resetFields(); }}
        onOk={() => apiClientForm.submit()}
      >
        <Form form={apiClientForm} onFinish={handleCreateApiClient} layout="vertical">
          <Form.Item name="name" label="客户端名称" rules={[{ required: true }]}>
            <Input placeholder="如: XX家具公司CRM对接" />
          </Form.Item>
          <Form.Item name="webhook_url" label="Webhook推送地址">
            <Input placeholder="您的系统接收线索的URL" />
          </Form.Item>
          <Form.Item name="callback_url" label="回调地址(可选)">
            <Input placeholder="用于接收状态更新回调" />
          </Form.Item>
          <Form.Item name="push_mode" label="推送模式" initialValue="batch">
            <Select>
              <Option value="batch">批量推送(每5分钟)</Option>
              <Option value="realtime">实时推送</Option>
            </Select>
          </Form.Item>
          <Form.Item name="push_interval" label="推送间隔(秒)" initialValue={300}>
            <InputNumber min={60} max={3600} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑API客户端弹窗 */}
      <Modal
        title="编辑API客户端"
        open={editApiClientModal}
        onCancel={() => { setEditApiClientModal(false); apiClientForm.resetFields(); setSelectedApiClient(null); }}
        onOk={() => apiClientForm.submit()}
      >
        <Form form={apiClientForm} onFinish={handleSaveApiClient} layout="vertical">
          <Form.Item name="name" label="客户端名称" rules={[{ required: true }]}>
            <Input placeholder="如: XX家具公司CRM对接" />
          </Form.Item>
          <Form.Item name="webhook_url" label="Webhook推送地址" rules={[{ required: true }]}>
            <Input placeholder="您的系统接收线索的URL" />
          </Form.Item>
          <Form.Item name="callback_url" label="回调地址(可选)">
            <Input placeholder="用于接收状态更新回调" />
          </Form.Item>
          <Form.Item name="push_mode" label="推送模式">
            <Select>
              <Option value="batch">批量推送(每5分钟)</Option>
              <Option value="realtime">实时推送</Option>
            </Select>
          </Form.Item>
          <Form.Item name="push_interval" label="推送间隔(秒)">
            <InputNumber min={60} max={3600} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default BusinessManager;