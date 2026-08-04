import { message } from '../../utils/antdMessage';
import React, { useEffect, useState, useCallback } from 'react';
import { Modal, Spin, Empty, List, Avatar, Tag, Button, Space, Input, Typography } from 'antd';
import {
  MessageOutlined,
  LinkOutlined,
  RobotOutlined,
  SendOutlined,
  TwitterOutlined,
  PlayCircleOutlined,
} from '@ant-design/icons';
import { xWorkbenchApi, type SentComment, type ReplyRecord } from '../../api/xWorkbench';

const { TextArea } = Input;
const { Text } = Typography;

export interface RepliesModalProps {
  open: boolean;
  sc?: SentComment;
  onClose: () => void;
  onChanged: () => void;
}

/**
 * 回复列表 Modal
 * 展示某条已发评论收到的回复，支持 AI 自动回复 / 手动回复
 */
const RepliesModal: React.FC<RepliesModalProps> = ({ open, sc, onClose, onChanged }) => {
  const [loading, setLoading] = useState(false);
  const [replies, setReplies] = useState<ReplyRecord[]>([]);
  const [replying, setReplying] = useState<number | null>(null);
  const [manualText, setManualText] = useState<Record<number, string>>({});

  const load = useCallback(async () => {
    if (!sc) return;
    setLoading(true);
    try {
      const r = await xWorkbenchApi.listReplies(sc.id);
      setReplies(r.items || []);
    } catch (e: any) {
      message.error('加载回复失败: ' + (e?.message || ''));
    } finally {
      setLoading(false);
    }
  }, [sc]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const triggerAuto = async (reply_id: number) => {
    setReplying(reply_id);
    try {
      const r = await xWorkbenchApi.triggerAutoReply(reply_id);
      if (r.success) {
        message.success('AI 已自动回复');
      } else {
        message.warning(`AI 回复未成功: ${r.message || ''}`);
      }
      load();
      onChanged();
    } catch (e: any) {
      message.error('AI 回复失败: ' + (e?.message || ''));
    } finally {
      setReplying(null);
    }
  };

  const sendManual = async (reply_id: number) => {
    const text = manualText[reply_id] || '';
    if (!text.trim()) {
      message.warning('请输入回复内容');
      return;
    }
    setReplying(reply_id);
    try {
      const r = await xWorkbenchApi.manualReply({ reply_id, content: text, real_send: true });
      if (r.success) {
        message.success('手动回复已发送');
        setManualText({ ...manualText, [reply_id]: '' });
      } else {
        message.error(`回复失败: ${r.message || ''}`);
      }
      load();
      onChanged();
    } catch (e: any) {
      message.error('回复失败: ' + (e?.message || ''));
    } finally {
      setReplying(null);
    }
  };

  return (
    <Modal
      title={
        <Space>
          <MessageOutlined />
          <span>回复管理 - 已发评论 #{sc?.id}</span>
        </Space>
      }
      open={open}
      onCancel={onClose}
      footer={null}
      width={900}
      styles={{ body: { padding: 24 } }}
    >
      <div style={{ marginBottom: 20, padding: 16, background: '#f5f5f5', borderRadius: 8 }}>
        <div style={{ fontSize: 12, color: '#8c8c8c', marginBottom: 8 }}>
          <Text strong>原帖: </Text>@{sc?.post_username}
        </div>
        <div style={{ fontSize: 13, marginBottom: 8, color: '#666', wordBreak: 'break-word', whiteSpace: 'pre-wrap' }}>
          {sc?.post_content}
        </div>
        <Space size="small" wrap style={{ marginBottom: 12 }}>
          {sc?.post_url && (
            <Button
              size="small"
              type="link"
              icon={<TwitterOutlined />}
              href={sc.post_url}
              target="_blank"
            >
              原贴链接
            </Button>
          )}
          {sc?.video_url && (
            <Button
              size="small"
              type="link"
              icon={<PlayCircleOutlined />}
              href={sc.video_url}
              target="_blank"
            >
              原视频
            </Button>
          )}
          {sc?.comment_url && (
            <Button
              size="small"
              type="link"
              icon={<LinkOutlined />}
              href={sc.comment_url}
              target="_blank"
            >
              我的评论链接
            </Button>
          )}
        </Space>
        <div style={{ fontSize: 12, color: '#8c8c8c', marginBottom: 8 }}>
          <Text strong>我的评论: </Text>
        </div>
        <div style={{ fontSize: 14, fontWeight: 500, wordBreak: 'break-word', whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
          {sc?.comment_content}
        </div>
      </div>
      <Spin spinning={loading}>
        {replies.length === 0 && !loading ? (
          <Empty description="暂无回复" />
        ) : (
          <List
            itemLayout="vertical"
            dataSource={replies}
            renderItem={(r) => (
              <List.Item key={r.id} style={{ padding: 16, borderBottom: '1px solid #f0f0f0', marginBottom: 8 }}>
                <List.Item.Meta
                  avatar={<Avatar src={r.replier_avatar} icon={<TwitterOutlined />} size={40} />}
                  title={
                    <Space>
                      <Text strong style={{ fontSize: 14 }}>@{r.replier_username || 'unknown'}</Text>
                      <Tag color={r.auto_reply_status === 'sent' ? 'green' : r.auto_reply_status === 'failed' ? 'red' : 'orange'}>
                        {r.auto_reply_status === 'sent'
                          ? '已 AI 回复'
                          : r.auto_reply_status === 'failed'
                          ? 'AI 回复失败'
                          : r.auto_reply_status === 'skipped'
                          ? '已跳过'
                          : '待回复'}
                      </Tag>
                      {r.reply_url && (
                        <Button size="small" type="link" icon={<LinkOutlined />} href={r.reply_url} target="_blank">
                          打开
                        </Button>
                      )}
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {r.reply_created_at ? new Date(r.reply_created_at * 1000).toLocaleString('zh-CN') : r.add_ts ? new Date(r.add_ts * 1000).toLocaleString('zh-CN') : ''}
                      </Text>
                    </Space>
                  }
                  description={
                    <div style={{ marginTop: 8 }}>
                      <div style={{ fontSize: 14, marginBottom: 12, wordBreak: 'break-word', whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                        {r.reply_content}
                      </div>
                      {r.auto_reply_content && (
                        <div style={{ padding: 12, background: '#e6f7ff', borderRadius: 6, marginBottom: 12 }}>
                          <div style={{ fontSize: 12, color: '#1890ff', marginBottom: 6, fontWeight: 500 }}>
                            <RobotOutlined style={{ marginRight: 4 }} />
                            AI 自动回复
                          </div>
                          <div style={{ fontSize: 13, wordBreak: 'break-word', whiteSpace: 'pre-wrap', lineHeight: 1.6, color: '#333' }}>
                            {r.auto_reply_content}
                          </div>
                        </div>
                      )}
                      <TextArea
                        rows={3}
                        placeholder="手动回复内容（可选）"
                        value={manualText[r.id] || ''}
                        onChange={(e) => setManualText({ ...manualText, [r.id]: e.target.value })}
                        maxLength={280}
                        style={{ marginBottom: 10 }}
                      />
                      <Space>
                        <Button
                          type="primary"
                          size="small"
                          icon={<RobotOutlined />}
                          loading={replying === r.id}
                          onClick={() => triggerAuto(r.id)}
                        >
                          AI 自动回复
                        </Button>
                        <Button
                          size="small"
                          icon={<SendOutlined />}
                          loading={replying === r.id}
                          onClick={() => sendManual(r.id)}
                        >
                          手动回复
                        </Button>
                      </Space>
                    </div>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Spin>
    </Modal>
  );
};

export default RepliesModal;
