import { message } from '../utils/antdMessage';
import { useState, useEffect } from 'react';
import { Card, Button, Input, Spin, Space, Typography, Tag, Tabs, Modal, Statistic, Row, Col, Progress, Tooltip, Alert } from 'antd';
import {
  ReloadOutlined,
  PlusOutlined,
  DeleteOutlined,
  ThunderboltOutlined,
  StopOutlined,
  HeartOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import {
  getCookiePool, addCookieToPool, removeCookieFromPool, clearCookiePool, clearInvalidCookies,
  getAccounts, refreshAccounts, clearBadIps, checkAccountHealth,
  type CookiePoolStatus, type AccountPoolStatus, type HealthCheckResult,
} from '../api/cookies';

const { TextArea } = Input;
const { Title, Text } = Typography;

const platformIcons: Record<string, string> = {
  xhs: '📕',
  dy: '🎵',
  ks: '📱',
  bili: '📺',
  wb: '🌐',
  x_twitter: '🐦',
};

export default function CookieManager() {
  return (
    <div style={{ padding: 24 }}>
      <Tabs
        defaultActiveKey="pool"
        items={[
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
// 账号池监控 Tab（真实展示 Cookie/IP block 状态 + 健康分）
// ============================================================

// Cookie状态 → 颜色/文字映射
const cookieStatusMap: Record<string, { color: string; text: string; icon: React.ReactNode }> = {
  valid:    { color: 'green',   text: 'Cookie有效',   icon: <CheckCircleOutlined /> },
  invalid:  { color: 'red',     text: 'Cookie无效',   icon: <CloseCircleOutlined /> },
  expired:  { color: 'volcano', text: 'Cookie过期',   icon: <WarningOutlined /> },
  cooldown: { color: 'orange',  text: 'Cookie冷却',   icon: <WarningOutlined /> },
  unknown:  { color: 'default', text: '未知',         icon: <WarningOutlined /> },
};

function AccountPoolTab() {
  const [accountData, setAccountData] = useState<AccountPoolStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [platform, setPlatform] = useState('dy');
  const [healthChecking, setHealthChecking] = useState(false);
  const [healthResult, setHealthResult] = useState<HealthCheckResult | null>(null);

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

  // 主动健康检测：实际检查Cookie格式 + IP是否被block
  const handleHealthCheck = async () => {
    setHealthChecking(true);
    try {
      const result = await checkAccountHealth(platform);
      setHealthResult(result);
      const s = result.summary;
      message.success(
        `检测完成: Cookie ${s.cookie_valid}有效/${s.cookie_invalid}无效/${s.cookie_expired}过期, IP ${s.ip_healthy}健康/${s.ip_blocked}被封`
      );
      // 刷新账号池状态以获取最新数据
      fetchAccounts();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '健康检测失败');
    } finally {
      setHealthChecking(false);
    }
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
        <Space wrap>
          <select
            value={platform}
            onChange={(e) => setPlatform(e.target.value)}
            style={{ padding: '4px 8px', borderRadius: 4, border: '1px solid #d9d9d9' }}
          >
            <option value="dy">抖音(dy)</option>
            <option value="xhs">小红书(xhs)</option>
            <option value="ks">快手(ks)</option>
            <option value="bili">B站(bili)</option>
            <option value="wb">微博(wb)</option>
            <option value="x_twitter">X(x_twitter)</option>
          </select>
          <Button
            type="primary"
            icon={<HeartOutlined />}
            onClick={handleHealthCheck}
            loading={healthChecking}
          >
            健康检测
          </Button>
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

      {/* 健康检测结果横幅 */}
      {healthResult && (
        <Alert
          type={healthResult.summary.ip_blocked > 0 || healthResult.summary.cookie_invalid > 0 ? 'warning' : 'success'}
          showIcon
          icon={<HeartOutlined />}
          message={`健康检测完成 (检测时间: ${new Date(healthResult.checked_at * 1000).toLocaleTimeString()})`}
          description={
            <Space size="large" wrap>
              <span>
                Cookie: <Text type="success">{healthResult.summary.cookie_valid} 有效</Text>
                {healthResult.summary.cookie_invalid > 0 && <Text type="danger"> / {healthResult.summary.cookie_invalid} 无效</Text>}
                {healthResult.summary.cookie_expired > 0 && <Text type="warning"> / {healthResult.summary.cookie_expired} 过期</Text>}
              </span>
              <span>
                IP: <Text type="success">{healthResult.summary.ip_healthy} 健康</Text>
                {healthResult.summary.ip_blocked > 0 && <Text type="danger"> / {healthResult.summary.ip_blocked} 被封</Text>}
              </span>
            </Space>
          }
          style={{ marginBottom: 16 }}
          closable
          onClose={() => setHealthResult(null)}
        />
      )}

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

          {/* IP健康状态面板 - 真实展示每个IP是否被block */}
          {accountData.ip_health && Object.keys(accountData.ip_health).length > 0 && (
            <Card
              title={
                <Space>
                  <span>🌐 IP健康状态</span>
                  <Tag color={accountData.bad_ips > 0 ? 'red' : 'green'}>
                    {accountData.bad_ips > 0 ? `${accountData.bad_ips} 个IP被封` : '全部正常'}
                  </Tag>
                </Space>
              }
              size="small"
              style={{ marginBottom: 16 }}
            >
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 12 }}>
                {Object.entries(accountData.ip_health).map(([iface, info]) => (
                  <div
                    key={iface}
                    style={{
                      padding: 12,
                      borderRadius: 8,
                      background: info.status === 'blocked' ? '#fff2f0' : info.status === 'healthy' ? '#f6ffed' : '#fafafa',
                      border: `1px solid ${info.status === 'blocked' ? '#ffccc7' : info.status === 'healthy' ? '#b7eb8f' : '#d9d9d9'}`,
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <Space>
                        {info.status === 'healthy' ? (
                          <CheckCircleOutlined style={{ color: '#52c41a' }} />
                        ) : info.status === 'blocked' ? (
                          <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
                        ) : (
                          <WarningOutlined style={{ color: '#faad14' }} />
                        )}
                        <Text strong>{iface}</Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>{info.ip}</Text>
                      </Space>
                      <Tag color={info.status === 'blocked' ? 'red' : info.status === 'healthy' ? 'green' : 'default'}>
                        {info.status === 'blocked' ? '已被封' : info.status === 'healthy' ? '正常' : '未知'}
                      </Tag>
                    </div>
                    {info.status === 'blocked' && info.remaining_ttl > 0 && (
                      <div style={{ marginTop: 4, fontSize: 12, color: '#ff4d4f' }}>
                        <Tooltip title="IP被封后自动冷却，过期后恢复使用">
                          <WarningOutlined /> 自动恢复剩余: {Math.ceil(info.remaining_ttl / 60)} 分钟
                        </Tooltip>
                      </div>
                    )}
                  </div>
                ))}
              </div>
              {accountData.bad_ip_list && accountData.bad_ip_list.length > 0 && (
                <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid #f0f0f0' }}>
                  <Text type="secondary" strong style={{ fontSize: 12 }}>被封IP详情:</Text>
                  <div style={{ marginTop: 8 }}>
                    {accountData.bad_ip_list.map((bad, idx) => (
                      <Tag key={idx} color="red" style={{ marginBottom: 4 }}>
                        {bad.interface || bad.key}: {bad.ip} (剩余 {Math.ceil(bad.remaining_ttl / 60)}分钟)
                      </Tag>
                    ))}
                  </div>
                </div>
              )}
            </Card>
          )}

          {/* 账号详情 - 真实展示Cookie状态 + 健康分 */}
          <Card
            title={
              <Space>
                <span>账号详情</span>
                <Text type="secondary" style={{ fontSize: 12, fontWeight: 'normal' }}>
                  (Cookie状态由格式检测+运行时状态综合判定，健康分由请求成功率动态计算)
                </Text>
              </Space>
            }
            size="small"
            extra={
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
            }
          >
            {accountData.accounts.length === 0 ? (
              <Text type="secondary">暂无账号，请在"Cookie池管理"中添加Cookie</Text>
            ) : (
              <div style={{ maxHeight: 500, overflowY: 'auto' }}>
                {accountData.accounts.map((acc) => {
                  const cs = cookieStatusMap[acc.cookie_status] || cookieStatusMap.unknown;
                  return (
                    <div
                      key={acc.account_id}
                      style={{
                        padding: 12,
                        background: acc.status === 'healthy' ? '#f6ffed' : acc.status === 'cooldown' ? '#fffbe6' : '#fff2f0',
                        borderRadius: 8,
                        marginBottom: 8,
                        border: `1px solid ${acc.status === 'healthy' ? '#b7eb8f' : acc.status === 'cooldown' ? '#ffe58f' : '#ffccc7'}`,
                      }}
                    >
                      {/* 第一行：状态标签 + 账号别名 + IP信息 */}
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, flexWrap: 'wrap', gap: 8 }}>
                        <Space wrap>
                          {/* Cookie真实状态标签 */}
                          <Tooltip title={
                            acc.cookie_status === 'invalid' && acc.cookie_missing_fields.length > 0
                              ? `缺少字段: ${acc.cookie_missing_fields.join(', ')}`
                              : acc.cookie_status === 'expired'
                              ? '运行时检测到Cookie已失效（登录过期）'
                              : acc.cookie_status === 'cooldown'
                              ? `冷却原因: ${acc.cooldown_reason || '未知'}`
                              : 'Cookie格式正确且运行时状态正常'
                          }>
                            <Tag color={cs.color} icon={cs.icon}>{cs.text}</Tag>
                          </Tooltip>
                          <Text strong>{acc.alias}</Text>
                          {/* IP状态标签 */}
                          {acc.network_interface && (
                            <Tag
                              color={acc.ip_blocked ? 'red' : 'geekblue'}
                              style={{ fontSize: 11 }}
                              icon={acc.ip_blocked ? <CloseCircleOutlined /> : <CheckCircleOutlined />}
                            >
                              {acc.network_interface} → {acc.public_ip || '未知'}
                              {acc.ip_blocked && ' (IP被封)'}
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

                      {/* 第二行：健康分进度条 */}
                      <Tooltip title={`健康分 = 基础100分 - 失败扣分 + 成功加分。当前: 请求${acc.total_requests}次, 成功${acc.success_count}次, 失败${acc.total_fails}次, 连续失败${acc.fail_count}次`}>
                        <Progress
                          percent={acc.health_score}
                          size="small"
                          status={acc.health_score > 60 ? 'success' : acc.health_score > 30 ? 'normal' : 'exception'}
                          format={(p) => `健康分: ${p}`}
                        />
                      </Tooltip>

                      {/* 第三行：请求统计 */}
                      <div style={{ marginTop: 4, fontSize: 12, color: '#999' }}>
                        请求: {acc.total_requests} | 成功: {acc.success_count} | 失败: {acc.total_fails} | 连续失败: {acc.fail_count}
                        <Text type="secondary" style={{ marginLeft: 8, fontSize: 11 }}>
                          (每次请求随机分配IP)
                        </Text>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
