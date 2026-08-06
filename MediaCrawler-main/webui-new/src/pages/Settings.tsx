import { message } from '../utils/antdMessage';
import React, { useEffect, useState } from 'react';
import { Card, Tabs, Form, Input, Button, Tag, Switch, Slider, List, Space, Modal, InputNumber, Row, Col, Divider, Select, Spin, Badge } from 'antd';
import { PlusOutlined, SaveOutlined, ReloadOutlined, DownloadOutlined, EditOutlined } from '@ant-design/icons';
import { authStorage } from '../api/auth';
import { systemConfigApi } from '../api/prdGap';
import SystemLogs from './SystemLogs';
import BusinessProfiles from './BusinessProfiles';

const { TabPane } = Tabs;
const { Option } = Select;

interface KeywordCategory {
  key: string;
  name: string;
  keywords: string[];
  weight: number;
}

interface ScoringConfig {
  intent_weight: number;
  product_weight: number;
  purchase_weight: number;
  sentiment_weight: number;
  min_threshold: number;
}

interface IntentRuleItem {
  id: number;
  rule_type: string;
  pattern: string;
  action: string;
  target_level: string;
  score_delta: number;
  score_cap: number;
  enabled: boolean;
  category: string;
  note: string;
}

const RULE_TYPE_LABELS: Record<string, string> = {
  strong_intent: '通用强意向',
  industry_template: '行业模板',
  nostalgia: '回忆降级',
  discussion: '讨论降级',
  past_purchase: '过去式降级',
};

const IntentRulesTab: React.FC = () => {
  const [rules, setRules] = useState<IntentRuleItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalVisible, setModalVisible] = useState(false);
  const [editing, setEditing] = useState<IntentRuleItem | null>(null);
  const [form] = Form.useForm();

  const load = async () => {
    setLoading(true);
    try {
      const token = authStorage.getToken();
      const resp = await fetch('/api/config/intent-rules', {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (resp.ok) {
        const data = await resp.json();
        setRules(data.items || []);
      }
    } catch (e) {
      console.error('加载意向规则失败', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleSave = async (values: any) => {
    const token = authStorage.getToken();
    const payload = {
      rule_type: values.rule_type,
      pattern: values.pattern,
      action: values.action,
      target_level: values.target_level,
      score_delta: Number(values.score_delta) || 0,
      score_cap: Number(values.score_cap) || 0,
      enabled: values.enabled ? 1 : 0,
      category: values.category || 'general',
      note: values.note || '',
    };
    try {
      const url = editing
        ? `/api/config/intent-rules/${editing.id}`
        : '/api/config/intent-rules';
      const method = editing ? 'PUT' : 'POST';
      const resp = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) throw new Error('保存失败');
      message.success('保存成功');
      setModalVisible(false);
      load();
    } catch (e: any) {
      message.error(e.message || '保存失败');
    }
  };

  const handleDelete = async (id: number) => {
    const token = authStorage.getToken();
    try {
      const resp = await fetch(`/api/config/intent-rules/${id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) throw new Error('删除失败');
      message.success('删除成功');
      load();
    } catch (e: any) {
      message.error(e.message || '删除失败');
    }
  };

  const handleToggle = async (rule: IntentRuleItem, enabled: boolean) => {
    const token = authStorage.getToken();
    try {
      const resp = await fetch(`/api/config/intent-rules/${rule.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ enabled: enabled ? 1 : 0 }),
      });
      if (!resp.ok) throw new Error('切换失败');
      load();
    } catch (e: any) {
      message.error(e.message || '切换失败');
    }
  };

  return (
    <Card
      title="意向识别规则管理"
      extra={
        <Button type="primary" icon={<PlusOutlined />} onClick={() => {
          setEditing(null);
          form.resetFields();
          setModalVisible(true);
        }}>
          添加规则
        </Button>
      }
    >
      <Spin spinning={loading}>
        <List
          dataSource={rules}
          renderItem={item => (
            <List.Item
              actions={[
                <Switch
                  checked={item.enabled}
                  onChange={(checked) => handleToggle(item, checked)}
                  checkedChildren="启用"
                  unCheckedChildren="禁用"
                />,
                <Button type="link" onClick={() => {
                  setEditing(item);
                  form.setFieldsValue(item);
                  setModalVisible(true);
                }}>编辑</Button>,
                <Button type="link" danger onClick={() => handleDelete(item.id)}>删除</Button>,
              ]}
            >
              <List.Item.Meta
                title={
                  <Space>
                    <Tag color={item.action === 'upgrade' ? 'green' : 'orange'}>
                      {item.action === 'upgrade' ? '升级' : '降级'}
                    </Tag>
                    <Tag color="blue">{RULE_TYPE_LABELS[item.rule_type] || item.rule_type}</Tag>
                    <span style={{ fontWeight: 600 }}>{item.pattern}</span>
                    {item.target_level && (
                      <Tag color={item.target_level === 'high' ? 'red' : 'default'}>
                        → {item.target_level === 'high' ? '高意向' : item.target_level === 'middle' ? '中意向' : '低意向'}
                      </Tag>
                    )}
                    {item.score_cap > 0 && <Tag>分数上限: {item.score_cap}</Tag>}
                  </Space>
                }
                description={item.note || `${item.category || '通用'}`}
              />
            </List.Item>
          )}
        />
      </Spin>

      <Modal
        title={editing ? '编辑意向规则' : '新建意向规则'}
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        onOk={() => form.submit()}
        width={600}
      >
        <Form form={form} layout="vertical" onFinish={handleSave}>
          <Form.Item name="rule_type" label="规则类型" rules={[{ required: true }]}>
            <Select>
              {Object.entries(RULE_TYPE_LABELS).map(([k, v]) => (
                <Option key={k} value={k}>{v}</Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item name="pattern" label="匹配模式" rules={[{ required: true }]}
            tooltip="行业模板用 {w} 占位核心词,如'想买{w}'">
            <Input placeholder="如:求链接 / 想买{w} / 小时候" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="action" label="动作" rules={[{ required: true }]}>
                <Select>
                  <Option value="upgrade">升级(加分)</Option>
                  <Option value="downgrade">降级(减分)</Option>
                </Select>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="target_level" label="目标等级">
                <Select>
                  <Option value="high">高意向</Option>
                  <Option value="middle">中意向</Option>
                  <Option value="low">低意向</Option>
                </Select>
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="score_delta" label="分数调整值">
                <InputNumber style={{ width: '100%' }} placeholder="如:20 或 -10" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="score_cap" label="分数上限(降级用)" tooltip="0=不限制">
                <InputNumber style={{ width: '100%' }} placeholder="如:45" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="category" label="分类标签">
            <Input placeholder="如:通用强意向 / 回忆降级" />
          </Form.Item>
          <Form.Item name="note" label="备注">
            <Input.TextArea rows={2} placeholder="规则说明" />
          </Form.Item>
          <Form.Item name="enabled" valuePropName="checked" initialValue={true}>
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
};

interface NotificationConfig {
  realtime: boolean;
  daily_summary: boolean;
  high_value_priority: boolean;
  method: string;
  webhook_url: string;
}

// 按用户隔离 storage key,避免不同用户设置串数据
const getUserId = () => authStorage.getUser()?.id || 'guest';
const STORAGE_KEY = () => `mediacrawler_settings_${getUserId()}`;
const TEMPLATES_KEY = () => `mediacrawler_message_templates_${getUserId()}`;

interface MessageTemplate {
  need_type: string;
  need_name: string;
  friendly: string;
  professional?: string;
  direct?: string;
}

const Settings: React.FC = () => {
  const [keywordCategories, setKeywordCategories] = useState<KeywordCategory[]>([
    { key: 'ai_chat', name: 'AI聊天工具', keywords: ['chatgpt', 'claude', 'gemini', '文心一言', '通义千问', 'kimi'], weight: 1.2 },
    { key: 'ai_image', name: 'AI图像生成', keywords: ['midjourney', 'stable diffusion', 'dalle', 'gpt image'], weight: 1.2 },
    { key: 'ai_platform', name: 'AI聚合平台', keywords: ['聚合平台', 'ai导航', 'ai工具箱', 'poe', 'cursor'], weight: 1.5 },
  ]);

  const [scoringConfig, setScoringConfig] = useState<ScoringConfig>({
    intent_weight: 40,
    product_weight: 35,
    purchase_weight: 15,
    sentiment_weight: 10,
    min_threshold: 50,
  });

  const [notificationConfig, setNotificationConfig] = useState<NotificationConfig>({
    realtime: true,
    daily_summary: true,
    high_value_priority: false,
    method: 'webhook',
    webhook_url: '',
  });

  const [editingCategory, setEditingCategory] = useState<KeywordCategory | null>(null);
  const [modalVisible, setModalVisible] = useState(false);
  const [loading, setLoading] = useState(true);
  const [form] = Form.useForm();
  const [scoringForm] = Form.useForm();
  const [notificationForm] = Form.useForm();

  const [templates, setTemplates] = useState<MessageTemplate[]>([
    {
      need_type: 'link_request',
      need_name: '求链接/网址',
      friendly: '{nickname} 来啦！链接给你 👇\n\n{product_desc}\n\n{link}\n\n{free_quota_text}有问题随时问我～',
      direct: '{link}\n\n{product_desc}\n\n{free_quota_text}',
    },
    {
      need_type: 'product_inquiry',
      need_name: '产品咨询',
      friendly: '嗨 {nickname}！看到你在找{product}，我们刚好有解决方案 😊\n\n{product_desc}\n\n现在注册还有专属优惠，要不要了解一下？\n\n点击链接：{link}',
      professional: '您好 {nickname}，\n\n注意到您对{product}感兴趣。我们是{company}，专注于{field}。\n\n{product_desc}\n\n如有兴趣，可以安排一次免费演示。\n\n联系方式：{contact}',
    },
    {
      need_type: 'price_sensitive',
      need_name: '价格敏感',
      friendly: '嗨 {nickname}！理解你想找性价比高的方案 💰\n\n我们目前有{product}，{price_info}\n\n比同类产品便宜{discount}，功能还更全面！\n\n现在注册送{free_quota}次免费调用，够你体验一个月了～\n\n{link}',
    },
    {
      need_type: 'tutorial_request',
      need_name: '教程需求',
      friendly: '嗨 {nickname}！新手入门确实不容易 😅\n\n我们整理了一份《{tutorial_name}》，免费送你！\n\n{tutorial_desc}\n\n需要的话回复"教程"就行，我发你～\n\n或者加微信：{wechat} 直接发你',
    },
    {
      need_type: 'frustration',
      need_name: '使用痛点',
      friendly: '嗨 {nickname}！理解你的困扰 😔\n\n{problem}确实是个麻烦事。我们有一款{product}，正好解决了这个问题：\n\n{solution}\n\n✅ 无需国外手机号\n✅ 微信一键登录\n✅ 中文界面，操作简单\n\n现在注册送{free_quota}次免费调用！\n\n{link}',
    },
    {
      need_type: 'general',
      need_name: '一般关注',
      friendly: '嗨 {nickname}！感谢关注 😊\n\n我们是{company}，专注于{field}。\n\n{product_desc}\n\n感兴趣的话可以点个关注，后续会有更多干货分享！\n\n有问题随时私信我～',
    },
  ]);
  const [editingTemplate, setEditingTemplate] = useState<MessageTemplate | null>(null);
  const [templateModalVisible, setTemplateModalVisible] = useState(false);
  const [templateForm] = Form.useForm();

  useEffect(() => {
    loadSettings();
  }, []);

  const loadSettings = async () => {
    setLoading(true);
    try {
      // 从后端 API 加载关键词分类
      const token = authStorage.getToken();
      const resp = await fetch('/api/config/keyword-categories', {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (resp.ok) {
        const data = await resp.json();
        if (data.items && data.items.length > 0) {
          setKeywordCategories(data.items.map((c: any) => ({
            key: String(c.id),
            name: c.name,
            keywords: c.keywords || [],
            weight: c.weight || 1,
          })));
        }
      }
      // 评分规则: 优先从后端加载,localStorage 作为 fallback 缓存(阶段三 P2-7)
      let scoringLoaded = false;
      try {
        const scoringResp: any = await systemConfigApi.get('scoring');
        if (scoringResp && scoringResp.found && scoringResp.value) {
          const cfg = scoringResp.value as ScoringConfig;
          setScoringConfig(cfg);
          scoringForm.setFieldsValue(cfg);
          scoringLoaded = true;
          // 同步写回 localStorage 作为本地缓存
          saveSettings('scoringConfig', cfg);
        }
      } catch (e) {
        console.warn('从后端加载评分规则失败,回退到 localStorage', e);
      }
      if (!scoringLoaded) {
        const saved = localStorage.getItem(STORAGE_KEY());
        if (saved) {
          const data = JSON.parse(saved);
          if (data.scoringConfig) {
            setScoringConfig(data.scoringConfig);
            scoringForm.setFieldsValue(data.scoringConfig);
          }
        }
      }
      // 通知设置: 同上,优先后端(阶段三 P2-7)
      let notificationLoaded = false;
      try {
        const notifResp: any = await systemConfigApi.get('notification');
        if (notifResp && notifResp.found && notifResp.value) {
          const cfg = notifResp.value as NotificationConfig;
          setNotificationConfig(cfg);
          notificationForm.setFieldsValue(cfg);
          notificationLoaded = true;
          saveSettings('notificationConfig', cfg);
        }
      } catch (e) {
        console.warn('从后端加载通知设置失败,回退到 localStorage', e);
      }
      if (!notificationLoaded) {
        const saved = localStorage.getItem(STORAGE_KEY());
        if (saved) {
          const data = JSON.parse(saved);
          if (data.notificationConfig) {
            setNotificationConfig(data.notificationConfig);
            notificationForm.setFieldsValue(data.notificationConfig);
          }
        }
      }
      const savedTemplates = localStorage.getItem(TEMPLATES_KEY());
      if (savedTemplates) {
        setTemplates(JSON.parse(savedTemplates));
      }
    } catch (error) {
      console.error('Failed to load settings:', error);
    } finally {
      setLoading(false);
    }
  };

  const saveSettings = (key: string, value: any) => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY());
      const data = saved ? JSON.parse(saved) : {};
      data[key] = value;
      localStorage.setItem(STORAGE_KEY(), JSON.stringify(data));
    } catch (error) {
      console.error('Failed to save settings:', error);
    }
  };

  const handleSaveKeywords = async (values: any) => {
    const keywords = typeof values.keywords === 'string'
      ? values.keywords.split(/[,，]/).map((k: string) => k.trim()).filter(Boolean)
      : values.keywords;

    const token = authStorage.getToken();
    const payload = {
      name: values.name,
      keywords,
      weight: values.weight || 1,
      category: 'general',
      enabled: 1,
    };
    try {
      if (editingCategory?.key) {
        // 更新
        const resp = await fetch(`/api/config/keyword-categories/${editingCategory.key}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify(payload),
        });
        if (!resp.ok) throw new Error('更新失败');
      } else {
        // 新建
        const resp = await fetch('/api/config/keyword-categories', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
          body: JSON.stringify(payload),
        });
        if (!resp.ok) throw new Error('创建失败');
      }
      message.success('保存成功');
      setModalVisible(false);
      loadSettings();
    } catch (e: any) {
      message.error(e.message || '保存失败');
    }
  };

  const handleDeleteCategory = async (key: string) => {
    const token = authStorage.getToken();
    try {
      const resp = await fetch(`/api/config/keyword-categories/${key}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) throw new Error('删除失败');
      message.success('删除成功');
      loadSettings();
    } catch (e: any) {
      message.error(e.message || '删除失败');
    }
  };

  const handleSaveScoring = async (values: any) => {
    setScoringConfig(values);
    // 保留 localStorage 作为本地缓存(fallback)
    saveSettings('scoringConfig', values);
    // 优先写入后端(阶段三 P2-7)
    try {
      await systemConfigApi.set('scoring', values, 'scoring');
      message.success('评分规则已保存');
    } catch (e: any) {
      console.error('保存评分规则到后端失败', e);
      message.warning('评分规则已保存到本地,但同步到后端失败');
    }
  };

  const handleSaveNotification = async (values: any) => {
    setNotificationConfig(values);
    // 保留 localStorage 作为本地缓存(fallback)
    saveSettings('notificationConfig', values);
    // 优先写入后端(阶段三 P2-7)
    try {
      await systemConfigApi.set('notification', values, 'notification');
      message.success('通知配置已保存');
    } catch (e: any) {
      console.error('保存通知设置到后端失败', e);
      message.warning('通知配置已保存到本地,但同步到后端失败');
    }
  };

  const handleSaveTemplate = (values: any) => {
    if (!editingTemplate) return;
    const updated: MessageTemplate = {
      ...editingTemplate,
      friendly: values.friendly,
      professional: values.professional || undefined,
      direct: values.direct || undefined,
    };
    setTemplates(prev => {
      const idx = prev.findIndex(t => t.need_type === updated.need_type);
      const next = idx >= 0
        ? prev.map((t, i) => i === idx ? updated : t)
        : [...prev, updated];
      localStorage.setItem(TEMPLATES_KEY(), JSON.stringify(next));
      return next;
    });
    message.success('文案模板已保存');
    setTemplateModalVisible(false);
  };

  const handleResetTemplates = () => {
    localStorage.removeItem(TEMPLATES_KEY());
    window.location.reload();
  };

  if (loading) return <Spin size="large" style={{ display: 'flex', justifyContent: 'center', padding: 100 }} />;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h3 style={{ margin: 0 }}>系统设置</h3>
        <Button icon={<ReloadOutlined />} onClick={loadSettings}>重新加载</Button>
      </div>

      <Tabs defaultActiveKey="keywords">
        <TabPane tab="关键词库" key="keywords">
          <Card
            title="关键词分类管理"
            extra={
              <Button type="primary" icon={<PlusOutlined />} onClick={() => {
                setEditingCategory(null);
                form.resetFields();
                setModalVisible(true);
              }}>
                添加分类
              </Button>
            }
          >
            <List
              dataSource={keywordCategories}
              renderItem={item => (
                <List.Item
                  actions={[
                    <Button type="link" onClick={() => {
                      setEditingCategory(item);
                      form.setFieldsValue({
                        ...item,
                        keywords: item.keywords.join(', '),
                      });
                      setModalVisible(true);
                    }}>编辑</Button>,
                    <Button type="link" danger onClick={() => handleDeleteCategory(item.key)}>删除</Button>,
                  ]}
                >
                  <List.Item.Meta
                    title={
                      <Space>
                        <span style={{ fontWeight: 600 }}>{item.name}</span>
                        <Tag color="blue">权重: {item.weight}x</Tag>
                      </Space>
                    }
                    description={
                      <Space size={[0, 8]} wrap style={{ marginTop: 8 }}>
                        {item.keywords.map((kw, i) => (
                          <Tag key={i} color="green">{kw}</Tag>
                        ))}
                      </Space>
                    }
                  />
                </List.Item>
              )}
            />
          </Card>
        </TabPane>

        <TabPane tab="意向规则" key="intent-rules">
          <IntentRulesTab />
        </TabPane>

        <TabPane tab="业务画像" key="business-profiles">
          <BusinessProfiles />
        </TabPane>

        <TabPane tab="评分规则" key="scoring">
          <Card title="评分权重配置">
            <Form
              form={scoringForm}
              layout="vertical"
              initialValues={scoringConfig}
              onFinish={handleSaveScoring}
            >
              <Form.Item name="intent_weight" label="咨询意图权重">
                <Slider min={0} max={100} marks={{ 0: '0%', 50: '50%', 100: '100%' }} />
              </Form.Item>
              <Form.Item name="product_weight" label="产品匹配权重">
                <Slider min={0} max={100} marks={{ 0: '0%', 50: '50%', 100: '100%' }} />
              </Form.Item>
              <Form.Item name="purchase_weight" label="购买信号权重">
                <Slider min={0} max={100} marks={{ 0: '0%', 50: '50%', 100: '100%' }} />
              </Form.Item>
              <Form.Item name="sentiment_weight" label="情感倾向权重">
                <Slider min={0} max={100} marks={{ 0: '0%', 50: '50%', 100: '100%' }} />
              </Form.Item>
              <Divider />
              <Form.Item name="min_threshold" label="最低评分阈值">
                <InputNumber min={0} max={100} style={{ width: 120 }} />
              </Form.Item>
              <Form.Item>
                <Button type="primary" icon={<SaveOutlined />} htmlType="submit">保存配置</Button>
              </Form.Item>
            </Form>
          </Card>
        </TabPane>

        <TabPane tab="文案模板" key="templates">
          <Card
            title="私信文案模板管理"
            extra={
              <Button icon={<ReloadOutlined />} onClick={handleResetTemplates}>恢复默认</Button>
            }
          >
            <div style={{ marginBottom: 16, padding: 12, background: '#f6ffed', borderRadius: 8 }}>
              <div style={{ fontSize: 13, color: '#666' }}>
                💡 可用变量：{'{nickname}'} 用户名、{'{product}'} 产品名、{'{product_desc}'} 产品描述、{'{link}'} 推广链接、{'{wechat}'} 微信号、{'{price_info}'} 价格、{'{discount}'} 优惠、{'{free_quota}'} 免费额度、{'{free_quota_text}'} 免费额度文本
              </div>
            </div>
            <List
              dataSource={templates}
              renderItem={item => (
                <List.Item
                  actions={[
                    <Button type="link" icon={<EditOutlined />} onClick={() => {
                      setEditingTemplate(item);
                      templateForm.setFieldsValue({
                        friendly: item.friendly,
                        professional: item.professional || '',
                        direct: item.direct || '',
                      });
                      setTemplateModalVisible(true);
                    }}>编辑</Button>,
                  ]}
                >
                  <List.Item.Meta
                    title={
                      <Space>
                        <span style={{ fontWeight: 600 }}>{item.need_name}</span>
                        <Tag color="blue">{item.need_type}</Tag>
                        {item.direct && <Badge count="有直接版" style={{ backgroundColor: '#52c41a' }} />}
                      </Space>
                    }
                    description={
                      <div style={{ marginTop: 8 }}>
                        <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>友好版：</div>
                        <pre style={{ margin: 0, padding: 8, background: '#f5f5f5', borderRadius: 4, fontSize: 12, whiteSpace: 'pre-wrap' }}>
                          {item.friendly}
                        </pre>
                      </div>
                    }
                  />
                </List.Item>
              )}
            />
          </Card>
        </TabPane>

        <TabPane tab="通知设置" key="notifications">
          <Card title="通知配置">
            <Form
              form={notificationForm}
              layout="vertical"
              initialValues={notificationConfig}
              onFinish={handleSaveNotification}
            >
              <Form.Item name="realtime" label="新线索实时通知" valuePropName="checked">
                <Switch />
              </Form.Item>
              <Form.Item name="daily_summary" label="每日数据汇总" valuePropName="checked">
                <Switch />
              </Form.Item>
              <Form.Item name="high_value_priority" label="高价值线索优先通知" valuePropName="checked">
                <Switch />
              </Form.Item>
              <Form.Item name="method" label="通知方式">
                <Select style={{ width: 200 }}>
                  <Option value="webhook">Webhook</Option>
                  <Option value="email">邮件</Option>
                  <Option value="sms">短信</Option>
                </Select>
              </Form.Item>
              <Form.Item name="webhook_url" label="Webhook地址">
                <Input placeholder="https://your-webhook-url.com" />
              </Form.Item>
              <Form.Item>
                <Button type="primary" icon={<SaveOutlined />} htmlType="submit">保存配置</Button>
              </Form.Item>
            </Form>
          </Card>
        </TabPane>

        <TabPane tab="运行日志" key="logs">
          <SystemLogs />
        </TabPane>

        <TabPane tab="系统信息" key="system">
          <Card title="系统信息">
            <Row gutter={[16, 16]}>
              <Col span={12}>
                <p><strong>系统版本:</strong> v1.0.0</p>
                <p><strong>前端版本:</strong> React 18 + Vite</p>
                <p><strong>后端版本:</strong> FastAPI + Python 3.11</p>
              </Col>
              <Col span={12}>
                <p><strong>数据库:</strong> PostgreSQL 15</p>
                <p><strong>缓存:</strong> Redis 7</p>
                <p><strong>采集引擎:</strong> Playwright</p>
              </Col>
            </Row>
          </Card>
          <Card title="数据备份与恢复" style={{ marginTop: 16 }}>
            <Space direction="vertical" style={{ width: '100%' }}>
              <div>
                <p>备份当前所有设置到本地文件</p>
                <Button icon={<DownloadOutlined />} onClick={() => {
                  const data = localStorage.getItem(STORAGE_KEY()) || '{}';
                  const blob = new Blob([data], { type: 'application/json' });
                  const link = document.createElement('a');
                  link.href = URL.createObjectURL(blob);
                  link.download = `mediacrawler_backup_${new Date().toISOString().slice(0, 10)}.json`;
                  link.click();
                  URL.revokeObjectURL(link.href);
                  message.success('备份文件已下载');
                }}>下载备份</Button>
              </div>
              <Divider />
              <div>
                <p>从备份文件恢复设置</p>
                <Input.TextArea
                  rows={6}
                  placeholder="粘贴备份JSON内容..."
                  onChange={(e) => {
                    try {
                      const data = JSON.parse(e.target.value);
                      localStorage.setItem(STORAGE_KEY(), JSON.stringify(data));
                      loadSettings();
                      message.success('恢复成功，页面将刷新');
                      setTimeout(() => window.location.reload(), 1000);
                    } catch {
                      // 等待完整输入
                    }
                  }}
                />
              </div>
            </Space>
          </Card>
        </TabPane>
      </Tabs>

      {/* 关键词分类编辑弹窗 */}
      <Modal
        title={editingCategory ? '编辑分类' : '添加分类'}
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        footer={[
          <Button key="cancel" onClick={() => setModalVisible(false)}>取消</Button>,
          <Button key="save" type="primary" onClick={() => form.submit()}>保存</Button>,
        ]}
      >
        <Form form={form} layout="vertical" onFinish={handleSaveKeywords}>
          <Form.Item name="name" label="分类名称" rules={[{ required: true }]}>
            <Input placeholder="例如：AI聊天工具" />
          </Form.Item>
          <Form.Item name="keywords" label="关键词" rules={[{ required: true }]}>
            <Input.TextArea
              placeholder="多个关键词用逗号分隔"
              rows={4}
            />
          </Form.Item>
          <Form.Item name="weight" label="权重" initialValue={1.0}>
            <Slider min={0.5} max={2.0} step={0.1} marks={{ 0.5: '0.5x', 1.0: '1.0x', 1.5: '1.5x', 2.0: '2.0x' }} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 文案模板编辑弹窗 */}
      <Modal
        title={editingTemplate ? `编辑模板：${editingTemplate.need_name}` : '编辑模板'}
        open={templateModalVisible}
        onCancel={() => setTemplateModalVisible(false)}
        width={700}
        footer={[
          <Button key="cancel" onClick={() => setTemplateModalVisible(false)}>取消</Button>,
          <Button key="save" type="primary" onClick={() => templateForm.submit()}>保存</Button>,
        ]}
      >
        <Form form={templateForm} layout="vertical" onFinish={handleSaveTemplate}>
          <Form.Item name="friendly" label="友好版文案" rules={[{ required: true }]}>
            <Input.TextArea rows={8} placeholder="输入友好语气文案..." />
          </Form.Item>
          {editingTemplate?.need_type !== 'link_request' && (
            <Form.Item name="professional" label="专业版文案">
              <Input.TextArea rows={6} placeholder="输入专业语气文案（可选）..." />
            </Form.Item>
          )}
          {editingTemplate?.need_type === 'link_request' && (
            <Form.Item name="direct" label="直接版文案（只发链接）">
              <Input.TextArea rows={4} placeholder="输入直接版文案..." />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </div>
  );
};

export default Settings;
