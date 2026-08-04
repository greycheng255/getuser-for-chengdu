import { message } from '../utils/antdMessage';
import React, { useState } from 'react';
import { Form, Input, Button, Card, Tabs } from 'antd';
import { UserOutlined, LockOutlined, RobotOutlined, MailOutlined } from '@ant-design/icons';
import { useNavigate, useLocation } from 'react-router-dom';
import { login, register, authStorage } from '../api/auth';

interface LocationState {
  from?: { pathname: string };
}

const Login: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'login' | 'register'>('login');
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as LocationState)?.from?.pathname || '/';

  const handleLogin = async (values: { username: string; password: string }) => {
    setLoading(true);
    try {
      const res = await login(values);
      authStorage.setToken(res.token);
      authStorage.setUser(res.user);
      message.success('登录成功');
      navigate(from, { replace: true });
    } catch (err: any) {
      const detail = err?.response?.data?.detail || '登录失败,请检查用户名和密码';
      message.error(detail);
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async (values: {
    username: string;
    password: string;
    nickname?: string;
    email?: string;
  }) => {
    setLoading(true);
    try {
      const res = await register(values);
      authStorage.setToken(res.token);
      authStorage.setUser(res.user);
      message.success(res.message || '注册成功');
      navigate(from, { replace: true });
    } catch (err: any) {
      const detail = err?.response?.data?.detail || '注册失败';
      message.error(detail);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
      }}
    >
      <Card style={{ width: 420, borderRadius: 8, boxShadow: '0 4px 20px rgba(0,0,0,0.1)' }}>
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <RobotOutlined style={{ fontSize: 48, color: '#1677ff' }} />
          <h2 style={{ marginTop: 16, marginBottom: 8 }}>获客系统</h2>
          <p style={{ color: '#999' }}>登录或注册您的账户</p>
        </div>

        <Tabs
          activeKey={activeTab}
          onChange={(k) => setActiveTab(k as 'login' | 'register')}
          centered
          items={[
            {
              key: 'login',
              label: '登录',
              children: (
                <Form name="login" onFinish={handleLogin} autoComplete="off" size="large">
                  <Form.Item
                    name="username"
                    rules={[{ required: true, message: '请输入用户名' }]}
                  >
                    <Input prefix={<UserOutlined />} placeholder="用户名" />
                  </Form.Item>
                  <Form.Item
                    name="password"
                    rules={[{ required: true, message: '请输入密码' }]}
                  >
                    <Input.Password prefix={<LockOutlined />} placeholder="密码" />
                  </Form.Item>
                  <Form.Item>
                    <Button type="primary" htmlType="submit" loading={loading} block>
                      登录
                    </Button>
                  </Form.Item>
                </Form>
              ),
            },
            {
              key: 'register',
              label: '注册',
              children: (
                <Form name="register" onFinish={handleRegister} autoComplete="off" size="large">
                  <Form.Item
                    name="username"
                    rules={[
                      { required: true, message: '请输入用户名' },
                      { min: 3, max: 64, message: '用户名长度 3-64 位' },
                    ]}
                  >
                    <Input prefix={<UserOutlined />} placeholder="用户名(3-64位)" />
                  </Form.Item>
                  <Form.Item
                    name="password"
                    rules={[
                      { required: true, message: '请输入密码' },
                      { min: 6, max: 128, message: '密码至少 6 位' },
                    ]}
                  >
                    <Input.Password prefix={<LockOutlined />} placeholder="密码(至少6位)" />
                  </Form.Item>
                  <Form.Item name="nickname" rules={[{ max: 64 }]}>
                    <Input prefix={<UserOutlined />} placeholder="昵称(选填)" />
                  </Form.Item>
                  <Form.Item name="email" rules={[{ type: 'email', message: '邮箱格式不正确' }, { max: 128 }]}>
                    <Input prefix={<MailOutlined />} placeholder="邮箱(选填)" />
                  </Form.Item>
                  <Form.Item>
                    <Button type="primary" htmlType="submit" loading={loading} block>
                      注册
                    </Button>
                  </Form.Item>
                </Form>
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
};

export default Login;
