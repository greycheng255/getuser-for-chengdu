import React, { useEffect, useState, useCallback } from 'react';
import {
  Modal,
  Spin,
  Alert,
  Card,
  Row,
  Col,
  Divider,
  Input,
  Button,
  Space,
  Typography,
  message,
} from 'antd';
import {
  VideoCameraOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
  SendOutlined,
  EditOutlined,
} from '@ant-design/icons';
import { xWorkbenchApi, type WorkbenchPost } from '../../api/xWorkbench';

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

export interface BreakdownModalProps {
  post: WorkbenchPost;
  open: boolean;
  onClose: () => void;
}

/**
 * 视频拆解 Modal
 * 展示 AI 拆解的脚本/分镜/关键要点/推荐评论，并支持发送评论
 */
const BreakdownModal: React.FC<BreakdownModalProps> = ({ post, open, onClose }) => {
  const [loading, setLoading] = useState(false);
  const [script, setScript] = useState('');
  const [storyboards, setStoryboards] = useState<string[]>([]);
  const [keyPoints, setKeyPoints] = useState<string[]>([]);
  const [suggestedComments, setSuggestedComments] = useState<string[]>([]);
  const [editComment, setEditComment] = useState('');
  const [sending, setSending] = useState(false);
  const [generating, setGenerating] = useState(false);

  const doBreakdown = useCallback(async (force = false) => {
    setLoading(true);
    try {
      const r = await xWorkbenchApi.generateBreakdown(post.post_id, force);
      setScript(r.script || '');
      setStoryboards(Array.isArray(r.storyboards) ? r.storyboards : []);
      setKeyPoints(Array.isArray(r.key_points) ? r.key_points : []);
      setSuggestedComments(Array.isArray(r.suggested_comments) ? r.suggested_comments : []);
      if (r.suggested_comments && Array.isArray(r.suggested_comments) && r.suggested_comments[0]) {
        setEditComment(r.suggested_comments[0]);
      }
    } catch (e: any) {
      message.error('拆解失败: ' + (e?.message || ''));
    } finally {
      setLoading(false);
    }
  }, [post.post_id]);

  useEffect(() => {
    if (open) {
      doBreakdown(false);
    }
  }, [open]);

  const doGenComments = async () => {
    setGenerating(true);
    try {
      const r = await xWorkbenchApi.generateComments(post.post_id, 3);
      if (r.comments && r.comments.length > 0) {
        setSuggestedComments(r.comments);
        setEditComment(r.comments[0]);
        message.success(`已生成 ${r.comments.length} 条评论`);
      }
    } catch (e: any) {
      message.error('生成评论失败: ' + (e?.message || ''));
    } finally {
      setGenerating(false);
    }
  };

  const doSend = async (real: boolean) => {
    if (!editComment.trim()) {
      message.warning('评论内容不能为空');
      return;
    }
    setSending(true);
    try {
      const r = await xWorkbenchApi.sendComment({
        post_id: post.post_id,
        post_url: post.post_url,
        content: editComment,
        real_send: real,
      });
      if (r.success) {
        message.success(`评论已${real ? '发送' : '保存为草稿'}（ID: ${r.sent_comment_id}）`);
        onClose();
      } else {
        message.error(`发送失败: ${r.message || '未知错误'}`);
      }
    } catch (e: any) {
      message.error('发送异常: ' + (e?.message || ''));
    } finally {
      setSending(false);
    }
  };

  return (
    <Modal
      title={
        <Space>
          <VideoCameraOutlined />
          <span>视频拆解 - @{post.username}</span>
        </Space>
      }
      open={open}
      onCancel={onClose}
      width={900}
      footer={
        <Space>
          <Button onClick={onClose}>关闭</Button>
          <Button icon={<ReloadOutlined />} loading={loading} onClick={() => doBreakdown(true)}>
            重新拆解
          </Button>
        </Space>
      }
    >
      <Spin spinning={loading}>
        <Paragraph ellipsis={{ rows: 2 }} type="secondary">
          {post.content}
        </Paragraph>
        {post.video_url && (
          <Alert
            type="warning"
            message="本系统暂未接入视频转写，AI 将基于推文文本进行分析"
            style={{ marginBottom: 12 }}
            showIcon
          />
        )}

        <Card size="small" title="【脚本分析】" style={{ marginBottom: 12 }}>
          <Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>{script || '（暂无）'}</Paragraph>
        </Card>

        <Row gutter={12} style={{ marginBottom: 12 }}>
          <Col span={12}>
            <Card size="small" title="【分镜拆解】" style={{ height: '100%' }}>
              {storyboards.length === 0 ? (
                <Text type="secondary">暂无</Text>
              ) : (
                <ol style={{ paddingLeft: 20, marginBottom: 0 }}>
                  {storyboards.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ol>
              )}
            </Card>
          </Col>
          <Col span={12}>
            <Card size="small" title="【关键要点】" style={{ height: '100%' }}>
              {keyPoints.length === 0 ? (
                <Text type="secondary">暂无</Text>
              ) : (
                <ul style={{ paddingLeft: 20, marginBottom: 0 }}>
                  {keyPoints.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              )}
            </Card>
          </Col>
        </Row>

        <Card
          size="small"
          title="【推荐评论】"
          extra={
            <Button size="small" icon={<ThunderboltOutlined />} loading={generating} onClick={doGenComments}>
              重新生成
            </Button>
          }
          style={{ marginBottom: 12 }}
        >
          {suggestedComments.length === 0 ? (
            <Text type="secondary">暂无</Text>
          ) : (
            <Space direction="vertical" style={{ width: '100%' }}>
              {suggestedComments.map((c, i) => (
                <Button
                  key={i}
                  block
                  style={{ textAlign: 'left', height: 'auto', whiteSpace: 'normal', padding: '8px 12px' }}
                  onClick={() => setEditComment(c)}
                >
                  {c}
                </Button>
              ))}
            </Space>
          )}
        </Card>

        <Divider>发送评论</Divider>
        <TextArea
          rows={3}
          placeholder="编辑评论内容（最多 280 字符）"
          value={editComment}
          onChange={(e) => setEditComment(e.target.value)}
          maxLength={280}
          showCount
        />
        <Space style={{ marginTop: 12 }}>
          <Button
            type="primary"
            icon={<SendOutlined />}
            loading={sending}
            onClick={() => doSend(true)}
          >
            真实发送
          </Button>
          <Button icon={<EditOutlined />} loading={sending} onClick={() => doSend(false)}>
            保存为草稿
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>
            真实发送需要 X_TWITTER_COOKIES 已配置
          </Text>
        </Space>
      </Spin>
    </Modal>
  );
};

export default BreakdownModal;
