import React, { useEffect, useState, useCallback } from 'react';
import {
  Card,
  Button,
  Space,
  List,
  Input,
  Tag,
  Modal,
  Form,
  InputNumber,
  message,
  Popconfirm,
  Typography,
  Empty,
} from 'antd';
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  SaveOutlined,
  ReloadOutlined,
  MessageOutlined,
} from '@ant-design/icons';
import {
  xWorkbenchApi,
  type KeywordReplyRule,
} from '../../api/xWorkbench';

const { Text, Title } = Typography;

const ReplyRulesPanel: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [rules, setRules] = useState<KeywordReplyRule[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingIndex, setEditingIndex] = useState<number>(-1);
  const [form] = Form.useForm<{
    keywords: string;
    replies: string;
    priority: number;
  }>();

  const loadRules = useCallback(async () => {
    setLoading(true);
    try {
      const r = await xWorkbenchApi.getReplyRules();
      setRules(r.rules || []);
    } catch (e: any) {
      message.error('加载回复规则失败: ' + (e?.message || ''));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRules();
  }, [loadRules]);

  const openAddModal = () => {
    setEditingIndex(-1);
    form.setFieldsValue({
      keywords: '',
      replies: '',
      priority: 99,
    });
    setModalOpen(true);
  };

  const openEditModal = (index: number) => {
    const rule = rules[index];
    setEditingIndex(index);
    form.setFieldsValue({
      keywords: rule.keywords.join(', '),
      replies: rule.replies.join('\n'),
      priority: rule.priority,
    });
    setModalOpen(true);
  };

  const handleDelete = (index: number) => {
    const newRules = rules.filter((_, i) => i !== index);
    setRules(newRules);
    saveRules(newRules);
  };

  const saveRules = async (newRules: KeywordReplyRule[]) => {
    try {
      const r = await xWorkbenchApi.updateReplyRules(newRules);
      if (r.success) {
        setRules(r.rules);
        message.success('规则已保存');
      }
    } catch (e: any) {
      message.error('保存失败: ' + (e?.message || ''));
      loadRules();
    }
  };

  const handleModalOk = async () => {
    try {
      const values = await form.validateFields();
      const keywords = values.keywords
        .split(/[,，]/)
        .map((k) => k.trim())
        .filter((k) => k.length > 0);
      const replies = values.replies
        .split(/\n/)
        .map((r) => r.trim())
        .filter((r) => r.length > 0);

      if (keywords.length === 0) {
        message.warning('请至少输入一个关键词');
        return;
      }
      if (replies.length === 0) {
        message.warning('请至少输入一条回复内容');
        return;
      }

      const newRule: KeywordReplyRule = {
        keywords,
        replies,
        priority: values.priority,
      };

      let newRules: KeywordReplyRule[];
      if (editingIndex >= 0) {
        newRules = [...rules];
        newRules[editingIndex] = newRule;
      } else {
        newRules = [...rules, newRule];
      }

      newRules.sort((a, b) => a.priority - b.priority);
      await saveRules(newRules);
      setModalOpen(false);
    } catch {
      // 校验失败
    }
  };

  return (
    <div>
      <Card
        size="small"
        title={
          <Space>
            <MessageOutlined />
            <span>关键词回复规则</span>
            <Tag color="blue">共 {rules.length} 条</Tag>
          </Space>
        }
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={loadRules} size="small">
              刷新
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={openAddModal}
              size="small"
            >
              新增规则
            </Button>
          </Space>
        }
        style={{ marginBottom: 16 }}
      >
        <Text type="secondary" style={{ fontSize: 13 }}>
          当收到的评论包含指定关键词时，系统会从回复内容中随机选择一条进行自动回复。优先级数字越小越先匹配。
        </Text>
      </Card>

      {loading ? (
        <Empty description="加载中..." />
      ) : rules.length === 0 ? (
        <Empty
          description="暂无回复规则，点击「新增规则」开始配置"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        />
      ) : (
        <List
          itemLayout="vertical"
          dataSource={rules}
          pagination={{
            pageSize: 10,
            showTotal: (total) => `共 ${total} 条规则`,
            size: 'small',
          }}
          renderItem={(rule, index) => (
            <List.Item
              actions={[
                <Button
                  key="edit"
                  size="small"
                  type="link"
                  icon={<EditOutlined />}
                  onClick={() => openEditModal(index)}
                >
                  编辑
                </Button>,
                <Popconfirm
                  key="delete"
                  title="确定删除这条规则吗？"
                  onConfirm={() => handleDelete(index)}
                  okText="删除"
                  cancelText="取消"
                >
                  <Button size="small" type="link" danger icon={<DeleteOutlined />}>
                    删除
                  </Button>
                </Popconfirm>,
              ]}
            >
              <List.Item.Meta
                title={
                  <Space>
                    <Tag color="orange">优先级 {rule.priority}</Tag>
                    <Text strong>关键词：{rule.keywords.length} 个</Text>
                    <Text type="secondary">回复：{rule.replies.length} 条</Text>
                  </Space>
                }
                description={
                  <div>
                    <div style={{ marginBottom: 8 }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>触发关键词：</Text>
                      <Space wrap size={[4, 4]} style={{ marginLeft: 8 }}>
                        {rule.keywords.map((kw, i) => (
                          <Tag key={i} color="blue">{kw}</Tag>
                        ))}
                      </Space>
                    </div>
                    <div>
                      <Text type="secondary" style={{ fontSize: 12 }}>回复内容（随机选一条）：</Text>
                      <div
                        style={{
                          marginTop: 4,
                          padding: '8px 12px',
                          background: '#f5f5f5',
                          borderRadius: 4,
                          fontSize: 13,
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-all',
                          overflowWrap: 'anywhere',
                          maxHeight: 120,
                          overflowY: 'auto',
                        }}
                      >
                        {rule.replies.map((r, i) => (
                          <div key={i} style={{ marginBottom: i < rule.replies.length - 1 ? 4 : 0 }}>
                            {i + 1}. {r}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                }
              />
            </List.Item>
          )}
        />
      )}

      <Modal
        title={editingIndex >= 0 ? '编辑回复规则' : '新增回复规则'}
        open={modalOpen}
        onOk={handleModalOk}
        onCancel={() => setModalOpen(false)}
        okText="保存"
        cancelText="取消"
        width={600}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            label="触发关键词"
            name="keywords"
            rules={[{ required: true, message: '请输入关键词' }]}
            extra="多个关键词用英文或中文逗号分隔，评论中包含任意一个关键词即触发"
          >
            <Input placeholder="例如：怎么学, 教程, 求推荐" />
          </Form.Item>

          <Form.Item
            label="回复内容"
            name="replies"
            rules={[{ required: true, message: '请输入回复内容' }]}
            extra="每行一条回复，系统会随机选择一条发送"
          >
            <Input.TextArea
              rows={6}
              placeholder={'例如：\n感谢关注！可以私信我了解更多~\n有兴趣的话欢迎交流~'}
            />
          </Form.Item>

          <Form.Item
            label="优先级"
            name="priority"
            extra="数字越小优先级越高，默认为 99"
          >
            <InputNumber min={1} max={999} style={{ width: 120 }} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default ReplyRulesPanel;
