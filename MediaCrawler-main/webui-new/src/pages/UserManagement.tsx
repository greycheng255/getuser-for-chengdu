import React, { useEffect, useState, useCallback } from 'react';
import {
  Card, Table, Button, Tag, Space, Modal, Form, Input, Select, message,
  Popconfirm, Avatar, Row, Col, Statistic, Tooltip,
} from 'antd';
import {
  UserOutlined, PlusOutlined, DeleteOutlined, EditOutlined,
  LockOutlined, UnlockOutlined, ReloadOutlined,
} from '@ant-design/icons';
import {
  listUsers, createUser, updateUser, deleteUser,
  type UserInfo, type CreateUserParams, type UpdateUserParams,
} from '../api/auth';

const { Option } = Select;

const roleMap: Record<string, { text: string; color: string }> = {
  admin: { text: '管理员', color: 'red' },
  operator: { text: '运营', color: 'blue' },
  viewer: { text: '观察员', color: 'green' },
};

const formatTs = (ts?: number) => {
  if (!ts) return '-';
  try {
    return new Date(ts).toLocaleString('zh-CN', { hour12: false });
  } catch {
    return '-';
  }
};

const UserManagement: React.FC = () => {
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalVisible, setModalVisible] = useState(false);
  const [editingUser, setEditingUser] = useState<UserInfo | null>(null);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listUsers();
      setUsers(res?.users || []);
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '加载用户列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUsers();
  }, [fetchUsers]);

  const handleSave = async (values: CreateUserParams & { password?: string; status?: 'active' | 'disabled' }) => {
    setSaving(true);
    try {
      if (editingUser) {
        const payload: UpdateUserParams = {
          nickname: values.nickname,
          email: values.email,
          role: values.role,
          status: values.status,
        };
        if (values.password) {
          payload.password = values.password;
        }
        await updateUser(editingUser.id, payload);
        message.success('用户更新成功');
      } else {
        await createUser({
          username: values.username,
          password: values.password!,
          nickname: values.nickname,
          email: values.email,
          role: values.role || 'operator',
        });
        message.success('用户创建成功');
      }
      setModalVisible(false);
      form.resetFields();
      setEditingUser(null);
      fetchUsers();
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteUser(id);
      message.success('用户已删除');
      fetchUsers();
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '删除失败');
    }
  };

  const handleToggleStatus = async (record: UserInfo) => {
    try {
      await updateUser(record.id, {
        status: record.status === 'active' ? 'disabled' : 'active',
      });
      message.success(`用户已${record.status === 'active' ? '禁用' : '启用'}`);
      fetchUsers();
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '操作失败');
    }
  };

  const columns = [
    {
      title: '用户',
      key: 'user',
      render: (_: any, record: UserInfo) => (
        <Space>
          <Avatar
            icon={<UserOutlined />}
            style={{
              backgroundColor:
                record.role === 'admin' ? '#f5222d' : record.role === 'operator' ? '#1890ff' : '#52c41a',
            }}
          />
          <div>
            <div style={{ fontWeight: 500 }}>{record.nickname || record.username}</div>
            <div style={{ fontSize: 12, color: '#999' }}>@{record.username}</div>
          </div>
        </Space>
      ),
    },
    { title: '邮箱', dataIndex: 'email', key: 'email', render: (v: string) => v || '-' },
    {
      title: '角色',
      dataIndex: 'role',
      key: 'role',
      width: 100,
      render: (v: string) => <Tag color={roleMap[v]?.color}>{roleMap[v]?.text || v}</Tag>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (v: string) => (
        <Tag color={v === 'active' ? 'success' : 'default'}>{v === 'active' ? '正常' : '禁用'}</Tag>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_ts',
      key: 'created_ts',
      width: 170,
      render: (v: number) => formatTs(v),
    },
    {
      title: '最后登录',
      dataIndex: 'last_login_ts',
      key: 'last_login_ts',
      width: 170,
      render: (v: number) => formatTs(v),
    },
    {
      title: '操作',
      key: 'action',
      width: 220,
      render: (_: any, record: UserInfo) => (
        <Space size="small">
          <Tooltip title="编辑">
            <Button
              type="text"
              icon={<EditOutlined />}
              size="small"
              onClick={() => {
                setEditingUser(record);
                form.setFieldsValue({
                  username: record.username,
                  nickname: record.nickname,
                  email: record.email,
                  role: record.role,
                  status: record.status,
                });
                setModalVisible(true);
              }}
            />
          </Tooltip>
          <Tooltip title={record.status === 'active' ? '禁用' : '启用'}>
            <Button
              type="text"
              icon={record.status === 'active' ? <LockOutlined /> : <UnlockOutlined />}
              size="small"
              onClick={() => handleToggleStatus(record)}
            />
          </Tooltip>
          <Popconfirm title="确认删除此用户?" onConfirm={() => handleDelete(record.id)}>
            <Button type="text" danger icon={<DeleteOutlined />} size="small" />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small" hoverable>
            <Statistic title="总用户" value={users.length} prefix={<UserOutlined />} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" hoverable>
            <Statistic
              title="管理员"
              value={users.filter((u) => u.role === 'admin').length}
              valueStyle={{ color: '#f5222d' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" hoverable>
            <Statistic
              title="运营"
              value={users.filter((u) => u.role === 'operator').length}
              valueStyle={{ color: '#1890ff' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" hoverable>
            <Statistic
              title="观察员"
              value={users.filter((u) => u.role === 'viewer').length}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
      </Row>

      <Card
        title="用户列表"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={fetchUsers} loading={loading}>
              刷新
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => {
                setEditingUser(null);
                form.resetFields();
                setModalVisible(true);
              }}
            >
              添加用户
            </Button>
          </Space>
        }
      >
        <Table
          columns={columns}
          dataSource={users}
          rowKey="id"
          size="small"
          loading={loading}
          pagination={{ pageSize: 10, showSizeChanger: true }}
        />
      </Card>

      <Modal
        title={editingUser ? '编辑用户' : '添加用户'}
        open={modalVisible}
        onCancel={() => {
          setModalVisible(false);
          form.resetFields();
          setEditingUser(null);
        }}
        confirmLoading={saving}
        footer={[
          <Button
            key="cancel"
            onClick={() => {
              setModalVisible(false);
              form.resetFields();
              setEditingUser(null);
            }}
          >
            取消
          </Button>,
          <Button key="save" type="primary" loading={saving} onClick={() => form.submit()}>
            保存
          </Button>,
        ]}
      >
        <Form form={form} layout="vertical" onFinish={handleSave} initialValues={{ role: 'operator', status: 'active' }}>
          <Form.Item
            name="username"
            label="用户名"
            rules={[
              { required: true, message: '请输入用户名' },
              { min: 3, max: 64, message: '用户名长度 3-64 位' },
            ]}
          >
            <Input disabled={!!editingUser} placeholder="3-64 位" />
          </Form.Item>
          <Form.Item name="nickname" label="昵称" rules={[{ max: 64 }]}>
            <Input placeholder="选填" />
          </Form.Item>
          <Form.Item name="email" label="邮箱" rules={[{ type: 'email', message: '邮箱格式不正确' }, { max: 128 }]}>
            <Input placeholder="选填" />
          </Form.Item>
          <Form.Item name="role" label="角色" rules={[{ required: true }]}>
            <Select>
              <Option value="admin">管理员</Option>
              <Option value="operator">运营</Option>
              <Option value="viewer">观察员</Option>
            </Select>
          </Form.Item>
          {editingUser && (
            <Form.Item name="status" label="状态" rules={[{ required: true }]}>
              <Select>
                <Option value="active">正常</Option>
                <Option value="disabled">禁用</Option>
              </Select>
            </Form.Item>
          )}
          <Form.Item
            name="password"
            label={editingUser ? '重置密码(留空则不修改)' : '初始密码'}
            rules={editingUser ? [] : [{ required: true, message: '请输入密码' }, { min: 6, message: '至少 6 位' }]}
          >
            <Input.Password placeholder={editingUser ? '留空不修改' : '至少 6 位'} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default UserManagement;
