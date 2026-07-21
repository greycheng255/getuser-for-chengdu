/**
 * 我的页面(v6.6)
 *
 * 聚合用户视角的所有账户相关信息:
 * - 套餐状态与配额(核心)
 * - 用量统计(视频/评论/线索)
 * - 余额与充值
 * - Cookie管理(子Tab)
 * - 商业化信息(子Tab,对管理员显示完整版)
 */
import React, { useEffect, useState } from 'react';
import {
  Card, Tabs, Row, Col, Statistic, Progress, Tag, Button, Space, message,
  Modal, InputNumber, Radio, Empty, Spin, Alert, Typography,
} from 'antd';
import {
  CrownOutlined, WalletOutlined, ThunderboltOutlined, FileTextOutlined,
  MessageOutlined, UserOutlined, ReloadOutlined, ArrowUpOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { getMyPlan, listPlans, upgradePlan, rechargeBalance, type PlanInfo, type PlanConfig } from '../api/plan';
import { authStorage } from '../api/auth';
import CookieManager from './CookieManager';
import BusinessManager from './BusinessManager';

const { Title, Text } = Typography;

// 套餐颜色映射
const PLAN_COLORS: Record<string, string> = {
  free: '#8c8c8c',
  basic: '#1677ff',
  pro: '#722ed1',
  enterprise: '#fa8c16',
};

const PLAN_LABELS: Record<string, string> = {
  free: '免费版',
  basic: '基础版',
  pro: '专业版',
  enterprise: '企业版',
};

// 格式化金额(分转元)
const formatMoney = (cents: number) => `¥${(cents / 100).toFixed(2)}`;

// 格式化时间戳
const formatTs = (ts: number) => ts ? dayjs(ts).format('YYYY-MM-DD HH:mm') : '-';

const Mine: React.FC = () => {
  const [plan, setPlan] = useState<PlanInfo | null>(null);
  const [allPlans, setAllPlans] = useState<PlanConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [upgradeModalVisible, setUpgradeModalVisible] = useState(false);
  const [rechargeModalVisible, setRechargeModalVisible] = useState(false);
  const [selectedPlan, setSelectedPlan] = useState<string>('');
  const [duration, setDuration] = useState<'monthly' | 'yearly'>('monthly');
  const [rechargeAmount, setRechargeAmount] = useState<number>(100);
  const [actionLoading, setActionLoading] = useState(false);

  const currentUser = authStorage.getUser();
  const isAdmin = currentUser?.role === 'admin';

  const fetchPlan = async () => {
    setLoading(true);
    try {
      const [planRes, plansRes] = await Promise.all([getMyPlan(), listPlans()]);
      setPlan(planRes.plan);
      setAllPlans(plansRes.plans || []);
    } catch (error) {
      console.error('Failed to fetch plan:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPlan();
  }, []);

  // 计算配额使用百分比
  const calcUsagePercent = (used: number, max: number) => {
    if (max === 0) return 0;
    return Math.min(100, Math.round((used / max) * 100));
  };

  // 套餐升级
  const handleUpgrade = async () => {
    if (!selectedPlan) {
      message.warning('请选择套餐');
      return;
    }
    setActionLoading(true);
    try {
      const res = await upgradePlan(selectedPlan, duration);
      message.success(res.message || '套餐升级成功');
      setUpgradeModalVisible(false);
      fetchPlan();
    } catch (error: any) {
      const detail = error?.response?.data?.detail || '升级失败';
      message.error(detail);
    } finally {
      setActionLoading(false);
    }
  };

  // 余额充值
  const handleRecharge = async () => {
    if (rechargeAmount <= 0) {
      message.warning('充值金额必须大于0');
      return;
    }
    setActionLoading(true);
    try {
      const res = await rechargeBalance(rechargeAmount);
      message.success(res.message || '充值成功');
      setRechargeModalVisible(false);
      fetchPlan();
    } catch (error: any) {
      const detail = error?.response?.data?.detail || '充值失败';
      message.error(detail);
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" tip="加载中..." />
      </div>
    );
  }

  if (!plan) {
    return <Empty description="无法获取套餐信息" />;
  }

  const planColor = PLAN_COLORS[plan.plan_type] || '#8c8c8c';
  const planLabel = PLAN_LABELS[plan.plan_type] || plan.plan_type;

  return (
    <div>
      {/* === 顶部:套餐概览 === */}
      <Card
        style={{
          background: `linear-gradient(135deg, ${planColor}15 0%, ${planColor}05 100%)`,
          border: `1px solid ${planColor}30`,
        }}
      >
        <Row gutter={[24, 16]} align="middle">
          <Col xs={24} md={12}>
            <Space size="large" align="center">
              <div style={{
                width: 64, height: 64, borderRadius: '50%',
                background: planColor, display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                <CrownOutlined style={{ fontSize: 32, color: '#fff' }} />
              </div>
              <div>
                <Title level={4} style={{ margin: 0 }}>
                  {planLabel}
                  {plan.is_active ? (
                    <Tag color="success" style={{ marginLeft: 8 }}>有效</Tag>
                  ) : (
                    <Tag color="error" style={{ marginLeft: 8 }}>已过期</Tag>
                  )}
                </Title>
                <Text type="secondary">
                  {plan.expires_ts > 0
                    ? `有效期至 ${formatTs(plan.expires_ts)}`
                    : '永久有效'
                  }
                </Text>
              </div>
            </Space>
          </Col>
          <Col xs={24} md={12} style={{ textAlign: 'right' }}>
            <Space>
              <Button
                type="primary"
                icon={<ArrowUpOutlined />}
                onClick={() => {
                  // 默认选中比当前高一档的套餐(free→basic→pro→enterprise)
                  const order: Record<string, string> = { free: 'basic', basic: 'pro', pro: 'enterprise' };
                  setSelectedPlan(order[plan.plan_type] || 'basic');
                  setUpgradeModalVisible(true);
                }}
              >
                升级套餐
              </Button>
              <Button
                icon={<WalletOutlined />}
                onClick={() => setRechargeModalVisible(true)}
              >
                余额充值
              </Button>
              <Button icon={<ReloadOutlined />} onClick={fetchPlan} />
            </Space>
          </Col>
        </Row>
      </Card>

      {/* === 核心指标 === */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={12} md={6}>
          <Card>
            <Statistic
              title="账户余额"
              value={plan.balance / 100}
              precision={2}
              prefix={<WalletOutlined />}
              suffix="元"
              valueStyle={{ color: '#52c41a' }}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              累计消费 {formatMoney(plan.total_spent)}
            </Text>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic
              title="最大任务数"
              value={plan.max_tasks === 0 ? '不限' : plan.max_tasks}
              prefix={<ThunderboltOutlined />}
              valueStyle={{ color: '#1677ff' }}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {plan.max_tasks === 0 ? '管理员不限任务数' : `单任务上限 ${plan.max_notes_per_task} 视频`}
            </Text>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic
              title="单任务视频上限"
              value={plan.max_notes_per_task === 0 ? '不限' : plan.max_notes_per_task}
              prefix={<FileTextOutlined />}
              valueStyle={{ color: '#722ed1' }}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              {plan.max_publish_time_type === 0
                ? '数据时效不限'
                : `仅采集 ${plan.max_publish_time_type} 天内数据`
              }
            </Text>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic
              title="评论采集上限"
              value={plan.max_comments_per_task === 0 ? '不限' : plan.max_comments_per_task}
              prefix={<MessageOutlined />}
              valueStyle={{ color: '#fa8c16' }}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              单视频评论数上限
            </Text>
          </Card>
        </Col>
      </Row>

      {/* === 用量统计 === */}
      <Card title="当前周期用量" style={{ marginTop: 16 }}>
        <Alert
          type="info"
          showIcon
          message={`计费周期开始于 ${formatTs(plan.usage_period_start_ts)}`}
          description="用量统计在每个计费周期内累计,套餐升级后自动重置。"
          style={{ marginBottom: 16 }}
        />
        <Row gutter={[24, 16]}>
          <Col xs={24} md={8}>
            <div style={{ textAlign: 'center' }}>
              <div style={{ marginBottom: 8 }}>
                <FileTextOutlined style={{ fontSize: 24, color: '#722ed1' }} />
                <span style={{ marginLeft: 8, fontSize: 16, fontWeight: 500 }}>视频/笔记</span>
              </div>
              <Progress
                type="dashboard"
                percent={plan.max_notes_per_task > 0
                  ? calcUsagePercent(plan.usage_notes_count, plan.max_notes_per_task)
                  : 0
                }
                format={() => `${plan.usage_notes_count}`}
                strokeColor="#722ed1"
              />
              <div style={{ marginTop: 8, color: '#999', fontSize: 12 }}>
                {plan.max_notes_per_task > 0
                  ? `上限 ${plan.max_notes_per_task}/周期`
                  : '不限'
                }
              </div>
            </div>
          </Col>
          <Col xs={24} md={8}>
            <div style={{ textAlign: 'center' }}>
              <div style={{ marginBottom: 8 }}>
                <MessageOutlined style={{ fontSize: 24, color: '#fa8c16' }} />
                <span style={{ marginLeft: 8, fontSize: 16, fontWeight: 500 }}>评论</span>
              </div>
              <Progress
                type="dashboard"
                percent={plan.max_comments_per_task > 0
                  ? calcUsagePercent(plan.usage_comments_count, plan.max_comments_per_task)
                  : 0
                }
                format={() => `${plan.usage_comments_count}`}
                strokeColor="#fa8c16"
              />
              <div style={{ marginTop: 8, color: '#999', fontSize: 12 }}>
                {plan.max_comments_per_task > 0
                  ? `上限 ${plan.max_comments_per_task}/周期`
                  : '不限'
                }
              </div>
            </div>
          </Col>
          <Col xs={24} md={8}>
            <div style={{ textAlign: 'center' }}>
              <div style={{ marginBottom: 8 }}>
                <UserOutlined style={{ fontSize: 24, color: '#52c41a' }} />
                <span style={{ marginLeft: 8, fontSize: 16, fontWeight: 500 }}>线索</span>
              </div>
              <Progress
                type="dashboard"
                percent={0}
                format={() => `${plan.usage_leads_count}`}
                strokeColor="#52c41a"
              />
              <div style={{ marginTop: 8, color: '#999', fontSize: 12 }}>
                线索数无上限
              </div>
            </div>
          </Col>
        </Row>
      </Card>

      {/* === 子Tab:Cookie管理 / 商业化 === */}
      <Card style={{ marginTop: 16 }}>
        <Tabs
          defaultActiveKey="cookies"
          items={[
            {
              key: 'cookies',
              label: (
                <span>
                  <SafetyCertificateOutlined />
                  Cookie管理
                </span>
              ),
              children: <CookieManager />,
            },
            ...(isAdmin ? [{
              key: 'business',
              label: (
                <span>
                  <WalletOutlined />
                  商业化管理
                </span>
              ),
              children: <BusinessManager />,
            }] : []),
          ]}
        />
      </Card>

      {/* === 套餐升级弹窗 === */}
      <Modal
        title="升级套餐"
        open={upgradeModalVisible}
        onCancel={() => setUpgradeModalVisible(false)}
        onOk={handleUpgrade}
        confirmLoading={actionLoading}
        width={600}
      >
        <div style={{ marginBottom: 16 }}>
          <Radio.Group
            value={selectedPlan}
            onChange={(e) => setSelectedPlan(e.target.value)}
            style={{ width: '100%' }}
          >
            <Row gutter={[12, 12]}>
              {allPlans.map((p) => {
                const color = PLAN_COLORS[p.name] || '#8c8c8c';
                const isCurrent = p.name === plan.plan_type;
                return (
                  <Col xs={24} sm={12} key={p.name}>
                    <Radio.Button
                      value={p.name}
                      disabled={isCurrent}
                      style={{
                        width: '100%',
                        height: 'auto',
                        padding: 12,
                        borderRadius: 8,
                        border: `2px solid ${selectedPlan === p.name ? color : '#f0f0f0'}`,
                      }}
                    >
                      <div style={{ textAlign: 'left' }}>
                        <div style={{ fontSize: 16, fontWeight: 600, color }}>
                          {p.display_name}
                          {isCurrent && <Tag style={{ marginLeft: 8 }}>当前</Tag>}
                        </div>
                        <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>
                          {p.max_tasks === 0 ? '不限任务' : `${p.max_tasks} 任务`} ·
                          {p.max_notes_per_task === 0 ? '不限视频' : ` ${p.max_notes_per_task} 视频/任务`}
                        </div>
                        <div style={{ fontSize: 14, marginTop: 4 }}>
                          ¥{(p.price_monthly / 100).toFixed(0)}/月 · ¥{(p.price_yearly / 100).toFixed(0)}/年
                        </div>
                      </div>
                    </Radio.Button>
                  </Col>
                );
              })}
            </Row>
          </Radio.Group>
        </div>

        <div style={{ marginBottom: 16 }}>
          <Text strong>订阅周期:</Text>
          <Radio.Group
            value={duration}
            onChange={(e) => setDuration(e.target.value)}
            style={{ marginLeft: 12 }}
          >
            <Radio.Button value="monthly">月订阅</Radio.Button>
            <Radio.Button value="yearly">年订阅(省2个月)</Radio.Button>
          </Radio.Group>
        </div>

        <Alert
          type="info"
          showIcon
          message={
            (() => {
              const sel = allPlans.find(p => p.name === selectedPlan);
              if (!sel) return '请选择套餐';
              // 价格字段单位为分,统一除100转元
              const priceCents = duration === 'monthly' ? sel.price_monthly : sel.price_yearly;
              const priceYuan = (priceCents / 100).toFixed(2);
              const balanceYuan = (plan.balance / 100).toFixed(2);
              const insufficient = priceCents > plan.balance ? ' (余额不足,请先充值)' : '';
              return `预计扣费: ¥${priceYuan},当前余额 ¥${balanceYuan}${insufficient}`;
            })()
          }
        />
      </Modal>

      {/* === 充值弹窗 === */}
      <Modal
        title="余额充值"
        open={rechargeModalVisible}
        onCancel={() => setRechargeModalVisible(false)}
        onOk={handleRecharge}
        confirmLoading={actionLoading}
      >
        <div style={{ marginBottom: 16 }}>
          <Text>当前余额: </Text>
          <Text strong style={{ color: '#52c41a', fontSize: 18 }}>
            ¥{(plan.balance / 100).toFixed(2)}
          </Text>
        </div>
        <div>
          <Text>充值金额(元): </Text>
          <InputNumber
            value={rechargeAmount}
            onChange={(v) => setRechargeAmount(v || 0)}
            min={1}
            max={100000}
            precision={2}
            style={{ width: 200, marginLeft: 8 }}
          />
        </div>
        <Row gutter={[8, 8]} style={{ marginTop: 16 }}>
          {[50, 100, 200, 500, 1000].map(amount => (
            <Col key={amount}>
              <Button onClick={() => setRechargeAmount(amount)}>¥{amount}</Button>
            </Col>
          ))}
        </Row>
        <Alert
          type="warning"
          showIcon
          message="充值后余额可用于套餐升级或超额按量计费"
          style={{ marginTop: 16 }}
        />
      </Modal>
    </div>
  );
};

export default Mine;
