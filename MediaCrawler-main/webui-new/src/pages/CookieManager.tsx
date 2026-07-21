import { useState, useEffect } from 'react';
import { Card, Button, Input, message, Spin, Badge, Space, Typography, Tag, Tabs, Modal, Statistic, Row, Col, Progress } from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  EditOutlined,
  ExperimentOutlined,
  SearchOutlined,
  SaveOutlined,
  ReloadOutlined,
  EyeOutlined,
  PlusOutlined,
  DeleteOutlined,
  ThunderboltOutlined,
  StopOutlined,
} from '@ant-design/icons';
import {
  getCookies, updateCookie, checkCookie, testCookie, parseCookie,
  getCookiePool, addCookieToPool, removeCookieFromPool, clearCookiePool, clearInvalidCookies,
  getAccounts, refreshAccounts, clearBadIps,
  type CookiePoolStatus, type AccountPoolStatus,
} from '../api/cookies';

const { TextArea } = Input;
const { Title, Text } = Typography;

interface CookieStatus {
  name: string;
  platform: string;
  has_cookie: boolean;
  cookie_length: number;
  status: string;
  check_field: string;
}

const platformIcons: Record<string, string> = {
  xhs: '📕',
  dy: '🎵',
  ks: '📱',
  bili: '📺',
  wb: '🌐',
  x_twitter: '🐦',
};

export default function CookieManager() {
  const [cookies, setCookies] = useState<Record<string, CookieStatus>>({});
  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState<Record<string, boolean>>({});
  const [checking, setChecking] = useState<Record<string, boolean>>({});
  const [parsing, setParsing] = useState<Record<string, boolean>>({});
  const [editing, setEditing] = useState<Record<string, boolean>>({});
  const [cookieValues, setCookieValues] = useState<Record<string, string>>({});
  const [testResults, setTestResults] = useState<Record<string, any>>({});
  const [checkResults, setCheckResults] = useState<Record<string, any>>({});
  const [parseResults, setParseResults] = useState<Record<string, any>>({});

  const fetchCookies = async () => {
    setLoading(true);
    try {
      const data = await getCookies();
      setCookies(data);
    } catch (error) {
      message.error('获取 Cookie 状态失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCookies();
  }, []);

  const handleUpdate = async (platform: string) => {
    const value = cookieValues[platform];
    if (!value || !value.trim()) {
      message.warning('请输入 Cookie');
      return;
    }
    try {
      await updateCookie(platform, value.trim());
      message.success('Cookie 更新成功');
      setEditing(prev => ({ ...prev, [platform]: false }));
      setParseResults(prev => ({ ...prev, [platform]: null }));
      fetchCookies();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '更新失败');
    }
  };

  const handleCheck = async (platform: string) => {
    setChecking(prev => ({ ...prev, [platform]: true }));
    try {
      const result = await checkCookie(platform);
      setCheckResults(prev => ({ ...prev, [platform]: result }));
      if (result.valid) {
        message.success(result.message);
      } else {
        message.warning(result.message);
      }
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '检测失败');
    } finally {
      setChecking(prev => ({ ...prev, [platform]: false }));
    }
  };

  const handleTest = async (platform: string) => {
    setTesting(prev => ({ ...prev, [platform]: true }));
    try {
      const result = await testCookie(platform);
      setTestResults(prev => ({ ...prev, [platform]: result }));
      if (result.success && result.logged_in) {
        message.success(result.message);
      } else if (result.success && !result.logged_in) {
        message.warning(result.message);
      } else {
        message.error(result.message);
      }
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '测试失败');
    } finally {
      setTesting(prev => ({ ...prev, [platform]: false }));
    }
  };

  const handleParse = async (platform: string) => {
    const value = cookieValues[platform];
    if (!value || !value.trim()) {
      message.warning('请先输入 Cookie 内容');
      return;
    }
    setParsing(prev => ({ ...prev, [platform]: true }));
    try {
      const result = await parseCookie(platform, value.trim());
      setParseResults(prev => ({ ...prev, [platform]: result }));
      // 将解析后的格式化 Cookie 更新到输入框
      if (result.formatted_cookie) {
        setCookieValues(prev => ({ ...prev, [platform]: result.formatted_cookie }));
      }
      message.success(`解析成功，识别到 ${result.cookie_keys.length} 个 Cookie 字段`);
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '解析失败');
    } finally {
      setParsing(prev => ({ ...prev, [platform]: false }));
    }
  };

  const toggleEdit = (platform: string) => {
    setEditing(prev => ({ ...prev, [platform]: !prev[platform] }));
    if (!editing[platform]) {
      setCookieValues(prev => ({ ...prev, [platform]: '' }));
      setParseResults(prev => ({ ...prev, [platform]: null }));
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <Tabs
        defaultActiveKey="single"
        items={[
          {
            key: 'single',
            label: '单Cookie管理',
            children: <SingleCookieTab
              cookies={cookies}
              loading={loading}
              fetchCookies={fetchCookies}
              testing={testing}
              checking={checking}
              parsing={parsing}
              editing={editing}
              cookieValues={cookieValues}
              testResults={testResults}
              checkResults={checkResults}
              parseResults={parseResults}
              setCookieValues={setCookieValues}
              toggleEdit={toggleEdit}
              handleUpdate={handleUpdate}
              handleCheck={handleCheck}
              handleTest={handleTest}
              handleParse={handleParse}
            />,
          },
          {
            key: 'pool',
            label: 'Cookie池管理',
            children: <CookiePoolTab />,
          },
          {
            key: 'accounts',
            label: '账号池监控',
            children: <AccountPoolTab />,
          },
        ]}
      />
    </div>
  );
}

// ============================================================
// 单Cookie管理 Tab（原有逻辑）
// ============================================================
function SingleCookieTab(props: any) {
  const {
    cookies, loading, fetchCookies,
    testing, checking, parsing, editing,
    cookieValues, testResults, checkResults, parseResults,
    setCookieValues, toggleEdit, handleUpdate, handleCheck, handleTest, handleParse,
  } = props;

  return (
    <>
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Title level={4}>🍪 Cookie 管理中心</Title>
          <Text type="secondary">管理各平台的登录 Cookie，确保采集引擎能正常访问平台数据</Text>
          <br />
          <Text type="secondary" style={{ fontSize: 12 }}>
            支持格式：标准字符串、JSON对象、浏览器开发者工具格式、Network请求头格式
          </Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={fetchCookies} loading={loading}>
          刷新状态
        </Button>
      </div>

      <Spin spinning={loading}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(420px, 1fr))', gap: 16 }}>
          {Object.entries(cookies).map(([platform, data]: [string, any]) => (
            <Card
              key={platform}
              title={
                <Space>
                  <span style={{ fontSize: 20 }}>{platformIcons[platform] || '📱'}</span>
                  <span>{data.name}</span>
                  <Badge
                    status={data.has_cookie ? 'success' : 'error'}
                    text={data.status}
                  />
                </Space>
              }
              extra={
                <Space>
                  <Button
                    size="small"
                    icon={<EditOutlined />}
                    onClick={() => toggleEdit(platform)}
                  >
                    {data.has_cookie ? '更新' : '添加'}
                  </Button>
                  <Button
                    size="small"
                    icon={<SearchOutlined />}
                    onClick={() => handleCheck(platform)}
                    loading={checking[platform]}
                  >
                    检测
                  </Button>
                  <Button
                    size="small"
                    type="primary"
                    icon={<ExperimentOutlined />}
                    onClick={() => handleTest(platform)}
                    loading={testing[platform]}
                  >
                    测试
                  </Button>
                </Space>
              }
            >
              <div style={{ marginBottom: 12 }}>
                <Text type="secondary">平台ID: {platform}</Text>
                <br />
                <Text type="secondary">Cookie长度: {data.cookie_length} 字符</Text>
                <br />
                <Text type="secondary">关键字段: {data.check_field}</Text>
              </div>

              {editing[platform] && (
                <div style={{ marginTop: 12 }}>
                  <div style={{ marginBottom: 8, padding: 8, background: '#fffbe6', border: '1px solid #ffe58f', borderRadius: 4 }}>
                    <Text type="warning" style={{ fontSize: 12 }}>
                      <strong>提示：</strong>必须从已登录的浏览器中复制完整的登录态 Cookie，确保包含 <Tag color="red">{data.check_field}</Tag> 字段。
                      <br />
                      缺少登录态字段的 Cookie 只能匿名访问，无法采集数据。
                    </Text>
                  </div>
                  <TextArea
                    rows={6}
                    placeholder={`支持多种格式粘贴：\n1. 标准格式: key1=value1; key2=value2\n2. JSON格式: {"key1": "value1"}\n3. 浏览器格式: key: value (多行)\n4. Network格式: Cookie: key1=value1; key2=value2\n5. Netscape格式: domain\\tflag\\tpath\\tsecure\\texpiration\\tname\\tvalue\n\n请务必包含登录态字段如 ${data.check_field}`}
                    value={cookieValues[platform] || ''}
                    onChange={e => setCookieValues((prev: Record<string, string>) => ({ ...prev, [platform]: e.target.value }))}
                    style={{ fontFamily: 'monospace', fontSize: 12 }}
                  />
                  <Space style={{ marginTop: 8 }}>
                    <Button
                      icon={<EyeOutlined />}
                      onClick={() => handleParse(platform)}
                      loading={parsing[platform]}
                    >
                      解析预览
                    </Button>
                    <Button
                      type="primary"
                      icon={<SaveOutlined />}
                      onClick={() => handleUpdate(platform)}
                    >
                      保存
                    </Button>
                    <Button onClick={() => toggleEdit(platform)}>取消</Button>
                  </Space>
                </div>
              )}

              {/* 解析预览结果 */}
              {parseResults[platform] && parseResults[platform].success && (
                <div
                  style={{
                    marginTop: 12,
                    padding: 12,
                    borderRadius: 4,
                    background: parseResults[platform].has_login_field ? '#f0f5ff' : '#fff2f0',
                    border: `1px solid ${parseResults[platform].has_login_field ? '#d6e4ff' : '#ffccc7'}`,
                  }}
                >
                  <Text strong style={{ display: 'block', marginBottom: 8 }}>
                    <EyeOutlined /> 解析预览
                    {!parseResults[platform].has_login_field && (
                      <Tag color="error" style={{ marginLeft: 8 }}>缺少登录态字段</Tag>
                    )}
                    {parseResults[platform].has_login_field && (
                      <Tag color="success" style={{ marginLeft: 8 }}>包含登录态字段</Tag>
                    )}
                  </Text>
                  <div style={{ marginBottom: 8, display: 'flex', gap: 16 }}>
                    <Tag color="default">原始: {parseResults[platform].original_length} 字符</Tag>
                    <Tag color="processing">解析后: {parseResults[platform].formatted_length} 字符</Tag>
                    <Tag color="success">共 {parseResults[platform].cookie_keys.length} 个字段</Tag>
                  </div>
                  <div style={{ marginBottom: 8 }}>
                    <Text type="secondary">识别字段: </Text>
                    {parseResults[platform].cookie_keys.map((key: string) => (
                      <Tag key={key} color={parseResults[platform].check_field === key ? 'green' : 'blue'}>{key}</Tag>
                    ))}
                  </div>
                  {!parseResults[platform].has_login_field && (
                    <div style={{ marginBottom: 8, padding: 8, background: '#fff', borderRadius: 4 }}>
                      <Text type="danger" strong>缺少关键字段: </Text>
                      {parseResults[platform].missing_fields.map((field: string) => (
                        <Tag key={field} color="red">{field}</Tag>
                      ))}
                      <br />
                      <Text type="warning" style={{ fontSize: 12 }}>
                        {parseResults[platform].login_tip}
                      </Text>
                    </div>
                  )}
                  <div>
                    <Text type="secondary">格式化预览: </Text>
                    <div style={{
                      marginTop: 4,
                      padding: 8,
                      background: '#fff',
                      borderRadius: 4,
                      fontSize: 12,
                      fontFamily: 'monospace',
                      maxHeight: 120,
                      overflow: 'auto',
                      border: '1px solid #e8e8e8'
                    }}>
                      {Object.entries(parseResults[platform].cookie_preview).map(([key, value]: [string, any]) => (
                        <div key={key} style={{ color: '#666', lineHeight: '1.8' }}>
                          <Text strong style={{ color: parseResults[platform].check_field === key ? '#52c41a' : '#1890ff' }}>{key}</Text>
                          <Text type="secondary">=</Text>
                          <Text>{value}</Text>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {checkResults[platform] && (
                <div
                  style={{
                    marginTop: 12,
                    padding: 12,
                    borderRadius: 4,
                    background: checkResults[platform].valid ? '#f6ffed' : '#fff2f0',
                    border: `1px solid ${checkResults[platform].valid ? '#b7eb8f' : '#ffccc7'}`,
                  }}
                >
                  <Space>
                    {checkResults[platform].valid ? (
                      <CheckCircleOutlined style={{ color: '#52c41a' }} />
                    ) : (
                      <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
                    )}
                    <Text>{checkResults[platform].message}</Text>
                  </Space>
                </div>
              )}

              {testResults[platform] && (
                <div
                  style={{
                    marginTop: 12,
                    padding: 12,
                    borderRadius: 4,
                    background: testResults[platform].success && testResults[platform].logged_in
                      ? '#f6ffed'
                      : testResults[platform].success
                      ? '#fffbe6'
                      : '#fff2f0',
                    border: `1px solid ${
                      testResults[platform].success && testResults[platform].logged_in
                        ? '#b7eb8f'
                        : testResults[platform].success
                        ? '#ffe58f'
                        : '#ffccc7'
                    }`,
                  }}
                >
                  <Space>
                    {testResults[platform].success && testResults[platform].logged_in ? (
                      <CheckCircleOutlined style={{ color: '#52c41a' }} />
                    ) : testResults[platform].success ? (
                      <CloseCircleOutlined style={{ color: '#faad14' }} />
                    ) : (
                      <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
                    )}
                    <Text>{testResults[platform].message}</Text>
                  </Space>
                </div>
              )}
            </Card>
          ))}
        </div>
      </Spin>
    </>
  );
}

// ============================================================
// Cookie池管理 Tab
// ============================================================
function CookiePoolTab() {
  const [poolData, setPoolData] = useState<Record<string, CookiePoolStatus>>({});
  const [loading, setLoading] = useState(false);
  const [addModalVisible, setAddModalVisible] = useState(false);
  const [addPlatform, setAddPlatform] = useState('dy');
  const [addCookie, setAddCookie] = useState('');

  const fetchPool = async () => {
    setLoading(true);
    try {
      const data = await getCookiePool();
      setPoolData(data as Record<string, CookiePoolStatus>);
    } catch {
      message.error('获取Cookie池失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPool();
  }, []);

  const handleAdd = async () => {
    if (!addCookie.trim() || addCookie.trim().length < 50) {
      message.warning('Cookie内容过短，请检查');
      return;
    }
    try {
      const res = await addCookieToPool(addPlatform, addCookie.trim());
      if (res.success) {
        message.success(res.message);
        setAddCookie('');
        setAddModalVisible(false);
        fetchPool();
      } else {
        // 后端返回了详细的失败原因（如缺少sessionid）
        message.error({
          content: res.message,
          duration: 8,
        });
        if (res.missing_fields && res.missing_fields.length > 0) {
          Modal.warning({
            title: 'Cookie不完整',
            content: (
              <div>
                <p>该Cookie缺少关键登录态字段：</p>
                <ul style={{ color: '#ff4d4f', paddingLeft: 20 }}>
                  {res.missing_fields.map((f: string, i: number) => (
                    <li key={i}>{f}</li>
                  ))}
                </ul>
                <p style={{ color: '#faad14', marginTop: 12 }}>
                  {res.hint || '请重新从浏览器获取完整Cookie'}
                </p>
              </div>
            ),
          });
        }
      }
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || '未知错误';
      message.error(`添加失败：${detail}`);
    }
  };

  const handleRemove = async (platform: string, cookie: string, cookieId?: number) => {
    try {
      const res = await removeCookieFromPool(platform, cookie, cookieId);
      message.success(res.message);
      fetchPool();
    } catch {
      message.error('移除失败');
    }
  };

  const handleClearInvalid = async (platform: string) => {
    try {
      const res = await clearInvalidCookies(platform);
      if (res.success) {
        message.success(res.message);
      } else {
        message.error(res.message);
      }
      fetchPool();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || '未知错误';
      message.error(`清理失败：${detail}`);
    }
  };

  const handleClear = async (platform: string) => {
    Modal.confirm({
      title: '确认清空',
      content: `确定要清空 ${platform} 的Cookie池吗？此操作会同时清空账号池和坏IP标记。`,
      okText: '确认清空',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const res = await clearCookiePool(platform);
          if (res.success) {
            message.success(res.message);
          } else {
            message.error(res.message || '清空失败');
          }
          fetchPool();
        } catch (err: any) {
          const detail = err?.response?.data?.detail || err?.message || '未知错误';
          message.error(`清空失败：${detail}`);
        }
      },
    });
  };

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Title level={4}>Cookie 池管理</Title>
          <Text type="secondary">配置多个Cookie，系统会自动轮换使用，检测到风控时自动切换</Text>
        </div>
        <Space>
          <Button icon={<PlusOutlined />} type="primary" onClick={() => setAddModalVisible(true)}>
            添加Cookie
          </Button>
          <Button icon={<ReloadOutlined />} onClick={fetchPool} loading={loading}>
            刷新
          </Button>
        </Space>
      </div>

      <Spin spinning={loading}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(500px, 1fr))', gap: 16 }}>
          {Object.entries(poolData).map(([platform, data]) => (
            <Card
              key={platform}
              title={
                <Space>
                  <span style={{ fontSize: 20 }}>{platformIcons[platform] || '📱'}</span>
                  <span>{platform.toUpperCase()}</span>
                  <Tag color={data.pool_size > 0 ? 'green' : 'default'}>{data.pool_size} 个Cookie</Tag>
                </Space>
              }
              extra={
                <Space>
                  {data.invalid_count && data.invalid_count > 0 ? (
                    <Button size="small" type="primary" danger ghost icon={<DeleteOutlined />} onClick={() => handleClearInvalid(platform)}>
                      清理{data.invalid_count}个无效
                    </Button>
                  ) : null}
                  {data.pool_size > 0 && (
                    <Button size="small" danger icon={<DeleteOutlined />} onClick={() => handleClear(platform)}>
                      清空
                    </Button>
                  )}
                </Space>
              }
            >
              {data.pool_size === 0 ? (
                <Text type="secondary">暂无Cookie，点击"添加Cookie"按钮添加</Text>
              ) : (
                <div style={{ maxHeight: 300, overflowY: 'auto' }}>
                  {(data.valid_count !== undefined || data.invalid_count !== undefined) && (
                    <div style={{ marginBottom: 8, padding: '4px 8px', background: '#f0f0f0', borderRadius: 4, fontSize: 12 }}>
                      <Text type="success">有效: {data.valid_count || 0}</Text>
                      <Text type="secondary" style={{ margin: '0 8px' }}>|</Text>
                      <Text type="danger">无效: {data.invalid_count || 0}</Text>
                      <Text type="secondary" style={{ margin: '0 8px' }}>|</Text>
                      <Text type="secondary">总计: {data.pool_size}</Text>
                    </div>
                  )}
                  {data.cookies.map((item: any) => (
                    <div key={item.index} style={{
                      padding: '8px 12px',
                      background: item.is_valid === false ? '#fff2f0' : '#fafafa',
                      border: item.is_valid === false ? '1px solid #ffccc7' : '1px solid transparent',
                      borderRadius: 6,
                      marginBottom: 8,
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                    }}>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <Space>
                          <Tag color={item.is_valid === false ? 'red' : (item.has_session ? 'green' : 'orange')}>
                            {item.is_valid === false ? '无效（缺登录态）' : (item.has_session ? '有session' : '无session')}
                          </Tag>
                          <Text style={{ fontSize: 12, color: '#999' }}>长度: {item.cookie_length}</Text>
                        </Space>
                        <div style={{
                          fontSize: 11,
                          color: '#999',
                          fontFamily: 'monospace',
                          marginTop: 4,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}>
                          {item.cookie_preview}
                        </div>
                      </div>
                      <Button
                        size="small"
                        type="text"
                        danger
                        icon={<DeleteOutlined />}
                        onClick={() => handleRemove(platform, item.cookie_preview || '', item.id)}
                      />
                    </div>
                  ))}
                </div>
              )}
            </Card>
          ))}
        </div>
      </Spin>

      <Modal
        title="添加Cookie到池"
        open={addModalVisible}
        onOk={handleAdd}
        onCancel={() => { setAddModalVisible(false); setAddCookie(''); }}
        width={700}
        okText="添加"
        cancelText="取消"
      >
        <div style={{ marginBottom: 12 }}>
          <Text strong>选择平台: </Text>
          <select
            value={addPlatform}
            onChange={(e) => setAddPlatform(e.target.value)}
            style={{ marginLeft: 8, padding: '4px 8px', borderRadius: 4, border: '1px solid #d9d9d9' }}
          >
            <option value="dy">dy</option>
            <option value="xhs">xhs</option>
            <option value="ks">ks</option>
            <option value="bili">bili</option>
            <option value="wb">wb</option>
            <option value="x_twitter">x_twitter</option>
          </select>
        </div>
        <TextArea
          value={addCookie}
          onChange={(e) => setAddCookie(e.target.value)}
          placeholder="粘贴完整的Cookie字符串..."
          rows={8}
          style={{ fontFamily: 'monospace', fontSize: 12 }}
        />
      </Modal>
    </div>
  );
}

// ============================================================
// 账号池监控 Tab
// ============================================================
function AccountPoolTab() {
  const [accountData, setAccountData] = useState<AccountPoolStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [platform, setPlatform] = useState('dy');

  const fetchAccounts = async () => {
    setLoading(true);
    try {
      const data = await getAccounts(platform);
      setAccountData(data);
    } catch {
      message.error('获取账号池状态失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAccounts();
    const timer = setInterval(fetchAccounts, 10000);
    return () => clearInterval(timer);
  }, [platform]);

  const handleRefresh = async () => {
    try {
      const res = await refreshAccounts(platform);
      message.success(res.message);
      fetchAccounts();
    } catch {
      message.error('刷新失败');
    }
  };

  const handleClearBadIps = async () => {
    try {
      const res = await clearBadIps(platform);
      message.success(res.message);
      fetchAccounts();
    } catch {
      message.error('清除失败');
    }
  };

  const statusColor = (status: string) => {
    const map: Record<string, string> = {
      healthy: 'green', cooldown: 'orange', banned: 'red', dead: 'default',
    };
    return map[status] || 'default';
  };

  const statusText = (status: string) => {
    const map: Record<string, string> = {
      healthy: '健康', cooldown: '冷却中', banned: '已封禁', dead: '已失效',
    };
    return map[status] || status;
  };

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Title level={4}>账号池监控</Title>
          <Text type="secondary">
            实时监控Cookie+IP组合的健康状态，风控时自动切换。
            IP动态随机分配，{accountData?.accounts?.length || 0}个Cookie × {accountData?.network_interfaces ? Object.keys(accountData.network_interfaces).length : 0}个IP
            {accountData?.accounts?.length && accountData?.network_interfaces && (
              <Tag color="purple" style={{ marginLeft: 8 }}>
                共 {(accountData.accounts.length) * Object.keys(accountData.network_interfaces).length} 种组合
              </Tag>
            )}
          </Text>
        </div>
        <Space>
          <select
            value={platform}
            onChange={(e) => setPlatform(e.target.value)}
            style={{ padding: '4px 8px', borderRadius: 4, border: '1px solid #d9d9d9' }}
          >
            <option value="dy">dy</option>
            <option value="xhs">xhs</option>
            <option value="x_twitter">x_twitter</option>
          </select>
          <Button icon={<ThunderboltOutlined />} onClick={handleRefresh}>
            刷新池
          </Button>
          <Button icon={<StopOutlined />} onClick={handleClearBadIps} danger>
            清除坏IP
          </Button>
          <Button icon={<ReloadOutlined />} onClick={fetchAccounts} loading={loading}>
            刷新
          </Button>
        </Space>
      </div>

      {accountData && (
        <>
          <Row gutter={12} style={{ marginBottom: 16 }}>
            <Col span={4}>
              <Card size="small">
                <Statistic title="总账号" value={accountData.total} styles={{ content: { fontSize: 22 } }} />
              </Card>
            </Col>
            <Col span={4}>
              <Card size="small">
                <Statistic title="健康" value={accountData.healthy}
                  styles={{ content: { fontSize: 22, color: '#52c41a' } }} />
              </Card>
            </Col>
            <Col span={4}>
              <Card size="small">
                <Statistic title="冷却中" value={accountData.cooldown}
                  styles={{ content: { fontSize: 22, color: '#faad14' } }} />
              </Card>
            </Col>
            <Col span={4}>
              <Card size="small">
                <Statistic title="已失效" value={accountData.dead}
                  styles={{ content: { fontSize: 22, color: '#ff4d4f' } }} />
              </Card>
            </Col>
            <Col span={4}>
              <Card size="small">
                <Statistic title="坏IP数" value={accountData.bad_ips}
                  styles={{ content: { fontSize: 22, color: '#ff4d4f' } }} />
              </Card>
            </Col>
            <Col span={4}>
              <Card size="small">
                <Statistic title="当前使用" value={accountData.current_account ? '是' : '无'}
                  styles={{ content: { fontSize: 22 } }} />
              </Card>
            </Col>
          </Row>

          <Card title="账号详情" size="small" extra={
            accountData.network_interfaces && Object.keys(accountData.network_interfaces).length > 0 && (
              <Space size="small" wrap>
                <Text type="secondary" style={{ fontSize: 11 }}>可用IP池:</Text>
                {Object.entries(accountData.network_interfaces).map(([iface, ip]) => (
                  <Tag key={iface} color="blue" style={{ fontSize: 11 }}>
                    {iface}: {ip}
                  </Tag>
                ))}
              </Space>
            )
          }>
            {accountData.accounts.length === 0 ? (
              <Text type="secondary">暂无账号，请在"Cookie池管理"中添加Cookie</Text>
            ) : (
              <div style={{ maxHeight: 500, overflowY: 'auto' }}>
                {accountData.accounts.map((acc) => (
                  <div key={acc.account_id} style={{
                    padding: 12,
                    background: acc.status === 'healthy' ? '#f6ffed' : acc.status === 'cooldown' ? '#fffbe6' : '#fff2f0',
                    borderRadius: 8,
                    marginBottom: 8,
                    border: `1px solid ${acc.status === 'healthy' ? '#b7eb8f' : acc.status === 'cooldown' ? '#ffe58f' : '#ffccc7'}`,
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                      <Space>
                        <Tag color={statusColor(acc.status)}>{statusText(acc.status)}</Tag>
                        <Text strong>{acc.alias}</Text>
                        {acc.network_interface && (
                          <Tag color="geekblue" style={{ fontSize: 11 }}>
                            上次用: {acc.network_interface} → {acc.public_ip || '未知'}
                          </Tag>
                        )}
                        {acc.proxy_ip && <Text type="secondary" style={{ fontSize: 12 }}>代理: {acc.proxy_ip}</Text>}
                      </Space>
                      {acc.status === 'cooldown' && acc.cooldown_remaining > 0 && (
                        <Text type="warning" style={{ fontSize: 12 }}>
                          冷却剩余: {Math.ceil(acc.cooldown_remaining / 60)}分钟 ({acc.cooldown_reason})
                        </Text>
                      )}
                    </div>
                    <Progress
                      percent={acc.health_score}
                      size="small"
                      status={acc.health_score > 60 ? 'success' : acc.health_score > 30 ? 'normal' : 'exception'}
                      format={(p) => `健康分: ${p}`}
                    />
                    <div style={{ marginTop: 4, fontSize: 12, color: '#999' }}>
                      请求: {acc.total_requests} | 成功: {acc.success_count} | 失败: {acc.total_fails} | 连续失败: {acc.fail_count}
                      <Text type="secondary" style={{ marginLeft: 8, fontSize: 11 }}>
                        (每次请求随机分配IP)
                      </Text>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
