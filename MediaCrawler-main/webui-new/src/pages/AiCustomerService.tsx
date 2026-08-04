import { message } from '../utils/antdMessage';
import React, { useEffect, useState, useCallback, useRef } from 'react';
import {
  Card, Table, Tag, Button, Space, Form, Input, Select,
  Row, Col, Tabs, Empty, Alert, Statistic,
  Typography, List, Spin, Badge,
} from 'antd';
import {
  ReloadOutlined, ThunderboltOutlined, CheckCircleOutlined,
  CustomerServiceOutlined, MessageOutlined, RobotOutlined, SendOutlined,
} from '@ant-design/icons';
import {
  getStatus, healthCheck, forceLogin, ask,
  listConversations, getMessages, sendMessage, listFaqs, searchKnowledge,
  autoReplyPreview,
  type YunkeStatus, type ConversationInfo, type ChatMessage,
  type FaqItem, type KnowledgeDoc, type AutoReplyPreview,
} from '../api/aiCustomerService';

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

const PLATFORM_OPTIONS = [
  { value: 'douyin', label: '抖音' },
  { value: 'xhs', label: '小红书' },
  { value: 'ks', label: '快手' },
  { value: 'bili', label: 'B站' },
  { value: 'wb', label: '微博' },
];

const AiCustomerService: React.FC = () => {
  const [tab, setTab] = useState('status');
  const [status, setStatus] = useState<YunkeStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);

  // ask
  const [question, setQuestion] = useState('');
  const [askResult, setAskResult] = useState<string>('');
  const [askConvId, setAskConvId] = useState<number | null>(null);
  const [asking, setAsking] = useState(false);

  // 会话列表
  const [conversations, setConversations] = useState<ConversationInfo[]>([]);
  const [convLoading, setConvLoading] = useState(false);
  const [selectedConvId, setSelectedConvId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [newMsg, setNewMsg] = useState('');

  // FAQ
  const [faqs, setFaqs] = useState<FaqItem[]>([]);
  const [faqLoading, setFaqLoading] = useState(false);
  const [faqQuery, setFaqQuery] = useState('');

  // 知识库
  const [kbQuery, setKbQuery] = useState('');
  const [kbDocs, setKbDocs] = useState<KnowledgeDoc[]>([]);
  const [kbLoading, setKbLoading] = useState(false);

  // 自动回复预览
  const [replyPlatform, setReplyPlatform] = useState('douyin');
  const [replyPostSummary, setReplyPostSummary] = useState('');
  const [replyComment, setReplyComment] = useState('');
  const [replyResult, setReplyResult] = useState<string>('');
  const [replyLoading, setReplyLoading] = useState(false);

  const msgSeqRef = useRef(0);

  // ============ 状态 ============
  const fetchStatus = useCallback(async () => {
    setStatusLoading(true);
    try {
      const s = await getStatus();
      setStatus(s);
    } catch (e: any) {
      message.error(e?.message || '加载状态失败');
    } finally {
      setStatusLoading(false);
    }
  }, []);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);

  const handleForceLogin = useCallback(async () => {
    try {
      const s = await forceLogin();
      setStatus(s);
      message.success('登录成功');
    } catch (e: any) {
      message.error(e?.message || '登录失败');
    }
  }, []);

  const handleHealthCheck = useCallback(async () => {
    try {
      const r = await healthCheck();
      message.success(`云客后端正常：${JSON.stringify(r.upstream).slice(0, 80)}`);
    } catch (e: any) {
      message.error(e?.message || '健康检查失败');
    }
  }, []);

  // ============ Ask ============
  const handleAsk = useCallback(async () => {
    if (!question.trim()) {
      message.warning('请输入问题');
      return;
    }
    setAsking(true);
    setAskResult('');
    try {
      const r = await ask({ question: question.trim(), max_poll_seconds: 30 });
      if (r.ok && r.answer) {
        setAskResult(r.answer);
        setAskConvId(r.conversation_id || null);
        message.success('AI 已回复');
      } else if (r.timeout) {
        message.warning('AI 客服回复超时，请稍后重试');
      } else {
        message.error(r.error || 'AI 调用失败');
      }
    } catch (e: any) {
      message.error(e?.message || '调用失败');
    } finally {
      setAsking(false);
    }
  }, [question]);

  // ============ 会话 ============
  const fetchConversations = useCallback(async () => {
    setConvLoading(true);
    try {
      const r = await listConversations({ conv_type: 'visitor', status: 'open' });
      setConversations(r.items || []);
    } catch (e: any) {
      message.error(e?.message || '加载会话失败');
    } finally {
      setConvLoading(false);
    }
  }, []);

  const fetchMessages = useCallback(async (convId: number) => {
    const seq = ++msgSeqRef.current;
    setMessagesLoading(true);
    try {
      const r = await getMessages({ conversation_id: convId, include_ai_messages: true });
      if (seq !== msgSeqRef.current) return;
      setMessages(r.messages || []);
    } catch (e: any) {
      message.error(e?.message || '加载消息失败');
    } finally {
      if (seq === msgSeqRef.current) setMessagesLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tab === 'conversations' && conversations.length === 0) {
      fetchConversations();
    }
  }, [tab, conversations.length, fetchConversations]);

  useEffect(() => {
    if (selectedConvId) fetchMessages(selectedConvId);
  }, [selectedConvId, fetchMessages]);

  const handleSendMsg = useCallback(async () => {
    if (!selectedConvId || !newMsg.trim()) return;
    try {
      await sendMessage({
        conversation_id: selectedConvId,
        content: newMsg.trim(),
        sender_is_agent: true,
      });
      setNewMsg('');
      message.success('已发送');
      fetchMessages(selectedConvId);
    } catch (e: any) {
      message.error(e?.message || '发送失败');
    }
  }, [selectedConvId, newMsg, fetchMessages]);

  // ============ FAQ ============
  const fetchFaqs = useCallback(async () => {
    setFaqLoading(true);
    try {
      const r = await listFaqs(faqQuery);
      setFaqs(r.faqs || []);
    } catch (e: any) {
      message.error(e?.message || '加载FAQ失败');
    } finally {
      setFaqLoading(false);
    }
  }, [faqQuery]);

  useEffect(() => {
    if (tab === 'faqs') fetchFaqs();
  }, [tab, fetchFaqs]);

  // ============ 知识库 ============
  const handleKbSearch = useCallback(async () => {
    if (!kbQuery.trim()) {
      message.warning('请输入关键词');
      return;
    }
    setKbLoading(true);
    try {
      const r = await searchKnowledge({ query: kbQuery.trim(), top_k: 10 });
      setKbDocs(r.documents || []);
    } catch (e: any) {
      message.error(e?.message || '检索失败');
    } finally {
      setKbLoading(false);
    }
  }, [kbQuery]);

  // ============ 自动回复预览 ============
  const handleReplyPreview = useCallback(async () => {
    if (!replyComment.trim()) {
      message.warning('请输入评论文本');
      return;
    }
    setReplyLoading(true);
    setReplyResult('');
    try {
      const r: AutoReplyPreview = await autoReplyPreview({
        comment_text: replyComment.trim(),
        platform: replyPlatform,
        post_summary: replyPostSummary,
        max_poll_seconds: 30,
      });
      if (r.ok && r.reply) {
        setReplyResult(r.reply);
        message.success('AI 回复生成成功');
      } else if (r.timeout) {
        message.warning('AI 客服回复超时');
      } else {
        message.error(r.error || '生成失败');
      }
    } catch (e: any) {
      message.error(e?.message || '调用失败');
    } finally {
      setReplyLoading(false);
    }
  }, [replyComment, replyPlatform, replyPostSummary]);

  // ============ 渲染 ============
  const renderStatus = () => (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      {status && !status.configured && (
        <Alert
          type="warning" showIcon
          message="云客客服未配置"
          description="请在 .env 设置 YUNKE_BASE_URL / YUNKE_USERNAME / YUNKE_PASSWORD"
        />
      )}
      <Card size="small" title={<Space><CustomerServiceOutlined />云客客服连接状态</Space>}>
        <Row gutter={16}>
          <Col span={6}>
            <Statistic title="配置状态" valueRender={() =>
              status?.configured
                ? <Tag color="green">已配置</Tag>
                : <Tag color="red">未配置</Tag>
            } />
          </Col>
          <Col span={6}>
            <Statistic title="登录状态" valueRender={() =>
              status?.logged_in
                ? <Tag color="green">已登录</Tag>
                : <Tag color="orange">未登录</Tag>
            } />
          </Col>
          <Col span={6}>
            <Statistic title="User ID" value={status?.user_id || '-'} />
          </Col>
          <Col span={6}>
            <Statistic title="Base URL"
              value={status?.base_url || '-'} />
          </Col>
        </Row>
        <Space style={{ marginTop: 16 }}>
          <Button icon={<ReloadOutlined />} loading={statusLoading} onClick={fetchStatus}>刷新</Button>
          <Button icon={<CheckCircleOutlined />} onClick={handleHealthCheck}>健康检查</Button>
          <Button type="primary" icon={<CustomerServiceOutlined />} onClick={handleForceLogin}>
            强制重新登录
          </Button>
        </Space>
      </Card>

      <Card size="small" title={<Space><RobotOutlined />一站式咨询 AI 客服</Space>}>
        <Alert
          type="info" showIcon
          message="使用场景"
          description="输入任意问题，AI 客服（云客系统 122.51.51.177:8063）会基于知识库生成回复。该接口已集成到评论监控自动回复流程，作为优先回复源。"
          style={{ marginBottom: 12 }}
        />
        <TextArea
          value={question}
          onChange={e => setQuestion(e.target.value)}
          rows={3}
          placeholder="请输入要咨询的问题…"
          maxLength={2000}
          showCount
        />
        <Space style={{ marginTop: 12 }}>
          <Button type="primary" icon={<ThunderboltOutlined />} loading={asking} onClick={handleAsk}>
            咨询 AI
          </Button>
          {askConvId && <Text type="secondary">会话 ID: {askConvId}</Text>}
        </Space>
        {askResult && (
          <Card size="small" type="inner" title="AI 回复" style={{ marginTop: 12 }}>
            <Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>{askResult}</Paragraph>
          </Card>
        )}
      </Card>
    </Space>
  );

  const renderConversations = () => (
    <Row gutter={16}>
      <Col span={8}>
        <Card size="small" title={<Space><MessageOutlined />会话列表<Badge count={conversations.length} /></Space>}
          extra={<Button size="small" icon={<ReloadOutlined />} onClick={fetchConversations} loading={convLoading} />}>
          <List
            dataSource={conversations}
            locale={{ emptyText: <Empty description="暂无会话" /> }}
            renderItem={item => (
              <List.Item
                onClick={() => setSelectedConvId(item.id)}
                style={{
                  cursor: 'pointer',
                  background: selectedConvId === item.id ? '#e6f4ff' : undefined,
                  padding: '8px 12px',
                }}
              >
                <List.Item.Meta
                  title={`#${item.id} 访客 ${item.visitor_id}`}
                  description={
                    <Space size={4} wrap>
                      <Tag color={item.chat_mode === 'ai' ? 'blue' : 'default'}>
                        {item.chat_mode === 'ai' ? 'AI' : '人工'}
                      </Tag>
                      <Tag color={item.status === 'open' ? 'green' : 'default'}>
                        {item.status === 'open' ? '进行中' : '已关闭'}
                      </Tag>
                      {item.unread_count > 0 && <Tag color="red">{item.unread_count} 未读</Tag>}
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
        </Card>
      </Col>
      <Col span={16}>
        <Card size="small" title={selectedConvId ? `会话 #${selectedConvId} 消息` : '请选择会话'}
          extra={selectedConvId && (
            <Button size="small" icon={<ReloadOutlined />} onClick={() => fetchMessages(selectedConvId)} loading={messagesLoading} />
          )}>
          {selectedConvId ? (
            <>
              <div style={{ maxHeight: 400, overflowY: 'auto', marginBottom: 12 }}>
                {messagesLoading ? (
                  <div style={{ textAlign: 'center', padding: 24 }}><Spin /></div>
                ) : messages.length === 0 ? (
                  <Empty description="无消息" />
                ) : (
                  messages.map(m => (
                    <div key={m.id} style={{
                      textAlign: m.sender_is_agent ? 'right' : 'left',
                      marginBottom: 8,
                    }}>
                      <div style={{
                        display: 'inline-block',
                        maxWidth: '75%',
                        padding: '8px 12px',
                        borderRadius: 8,
                        background: m.sender_is_agent ? '#1890ff' : '#f0f0f0',
                        color: m.sender_is_agent ? '#fff' : '#333',
                        textAlign: 'left',
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                      }}>
                        <div style={{ fontSize: 11, opacity: 0.7, marginBottom: 4 }}>
                          {m.sender_is_agent ? '客服' : '访客'}
                          {m.message_type === 'system_message' && ' / AI'}
                        </div>
                        {m.content}
                      </div>
                    </div>
                  ))
                )}
              </div>
              <Space.Compact style={{ width: '100%' }}>
                <Input
                  value={newMsg}
                  onChange={e => setNewMsg(e.target.value)}
                  placeholder="以客服身份发送消息…"
                  onPressEnter={handleSendMsg}
                />
                <Button type="primary" icon={<SendOutlined />} onClick={handleSendMsg}>发送</Button>
              </Space.Compact>
            </>
          ) : (
            <Empty description="请从左侧选择一个会话" />
          )}
        </Card>
      </Col>
    </Row>
  );

  const renderFaqs = () => (
    <Card size="small" title="FAQ / 事件管理"
      extra={
        <Space>
          <Input.Search
            placeholder="搜索关键词"
            value={faqQuery}
            onChange={e => setFaqQuery(e.target.value)}
            onSearch={fetchFaqs}
            style={{ width: 220 }}
            allowClear
          />
          <Button icon={<ReloadOutlined />} onClick={fetchFaqs} loading={faqLoading}>刷新</Button>
        </Space>
      }>
      <Table
        dataSource={faqs}
        rowKey="id"
        loading={faqLoading}
        pagination={{ pageSize: 20, showSizeChanger: false }}
        columns={[
          { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
          { title: '问题', dataIndex: 'question', key: 'q' },
          { title: '答案', dataIndex: 'answer', key: 'a', ellipsis: true },
          { title: '关键词', dataIndex: 'keywords', key: 'kw', width: 180,
            render: (v: string) => v ? v.split(',').map((k, i) => <Tag key={i}>{k.trim()}</Tag>) : '-' },
        ]}
      />
    </Card>
  );

  const renderKnowledge = () => (
    <Card size="small" title="知识库向量检索">
      <Space style={{ marginBottom: 12, width: '100%' }}>
        <Input
          placeholder="输入检索关键词"
          value={kbQuery}
          onChange={e => setKbQuery(e.target.value)}
          onPressEnter={handleKbSearch}
          style={{ width: 360 }}
        />
        <Button type="primary" icon={<ThunderboltOutlined />} loading={kbLoading} onClick={handleKbSearch}>
          检索
        </Button>
      </Space>
      <List
        dataSource={kbDocs}
        loading={kbLoading}
        locale={{ emptyText: <Empty description="请输入关键词检索知识库" /> }}
        renderItem={item => (
          <List.Item>
            <List.Item.Meta
              title={<Space>{item.title}<Tag color="blue">相关度 {(item.score * 100).toFixed(1)}%</Tag></Space>}
              description={
                <Paragraph ellipsis={{ rows: 3 }} style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
                  {item.content}
                </Paragraph>
              }
            />
          </List.Item>
        )}
      />
    </Card>
  );

  const renderAutoReply = () => (
    <Card size="small" title={<Space><RobotOutlined />评论自动回复预览</Space>}>
      <Alert
        type="info" showIcon
        message="功能说明"
        description="输入用户评论文本，AI 客服会基于上下文生成建议回复。该回复仅用于预览，不会自动发出。评论监控任务开启自动回复后，会调用同一接口生成并自动回复。"
        style={{ marginBottom: 16 }}
      />
      <Form layout="vertical">
        <Row gutter={16}>
          <Col span={8}>
            <Form.Item label="评论所在平台">
              <Select value={replyPlatform} onChange={setReplyPlatform} options={PLATFORM_OPTIONS} />
            </Form.Item>
          </Col>
          <Col span={16}>
            <Form.Item label="视频/笔记摘要（可选）">
              <Input value={replyPostSummary} onChange={e => setReplyPostSummary(e.target.value)}
                placeholder="如：成都火锅店推荐" />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item label="用户评论文本">
          <TextArea
            value={replyComment}
            onChange={e => setReplyComment(e.target.value)}
            rows={4}
            placeholder="粘贴用户评论内容…"
            maxLength={2000}
            showCount
          />
        </Form.Item>
        <Space>
          <Button type="primary" icon={<ThunderboltOutlined />} loading={replyLoading} onClick={handleReplyPreview}>
            生成 AI 回复
          </Button>
        </Space>
        {replyResult && (
          <Card size="small" type="inner" title="AI 建议回复" style={{ marginTop: 12 }}>
            <Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>{replyResult}</Paragraph>
          </Card>
        )}
      </Form>
    </Card>
  );

  return (
    <div style={{ padding: 24 }}>
      <Card
        title={<Space><CustomerServiceOutlined />AI 客服（云客智能客服系统）</Space>}
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={fetchStatus} loading={statusLoading}>刷新状态</Button>
          </Space>
        }
      >
        {status && (
          <div style={{ marginBottom: 12 }}>
            <Space>
              <Text type="secondary">服务地址：</Text>
              <Text code>{status.base_url}</Text>
              <Tag color={status.configured ? 'green' : 'red'}>
                {status.configured ? '已配置' : '未配置'}
              </Tag>
              <Tag color={status.logged_in ? 'green' : 'orange'}>
                {status.logged_in ? '已登录' : '未登录'}
              </Tag>
            </Space>
          </div>
        )}
        <Tabs activeKey={tab} onChange={setTab} items={[
          { key: 'status', label: '状态 / 咨询', children: renderStatus() },
          { key: 'conversations', label: '会话管理', children: renderConversations() },
          { key: 'faqs', label: 'FAQ', children: renderFaqs() },
          { key: 'knowledge', label: '知识库检索', children: renderKnowledge() },
          { key: 'auto-reply', label: '评论自动回复预览', children: renderAutoReply() },
        ]} />
      </Card>
    </div>
  );
};

export default AiCustomerService;
