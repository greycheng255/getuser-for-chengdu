import { message } from '../../utils/antdMessage';
import React, { useState } from 'react';
import { Modal, Spin, Card, Space, Button, Input, Divider, Typography, Tag, Tooltip } from 'antd';
import {
  MessageOutlined,
  ThunderboltOutlined,
  SendOutlined,
  EditOutlined,
  CopyOutlined,
  RocketOutlined,
  FileTextOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import {
  xWorkbenchApi,
  type WorkbenchPost,
} from '../../api/xWorkbench';
import { usePlatform } from '../../context/PlatformContext';

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

// 平台别名映射（与 BreakdownModal 保持一致，避免循环依赖）
const PLATFORM_TO_PIPELINE: Record<string, string> = {
  x: 'x', x_twitter: 'x', tw: 'x',
  youtube: 'youtube', yt: 'youtube',
  douyin: 'douyin', dy: 'douyin',
  bilibili: 'bilibili', bili: 'bilibili',
  kuaishou: 'kuaishou', ks: 'kuaishou',
  xiaohongshu: 'xiaohongshu', xhs: 'xiaohongshu',
  weibo: 'weibo', wb: 'weibo',
  zhihu: 'zhihu',
};

const apiErrorMessage = (error: any, fallback: string) =>
  error?.response?.data?.message || error?.response?.data?.detail || error?.message || fallback;

export interface CommentComposeModalProps {
  post: WorkbenchPost;
  open: boolean;
  onClose: () => void;
}

/**
 * 评论撰写 Modal（互动监控页面入口）
 * 承接从 BreakdownModal 迁移出来的「发送评论」「生成发布文案」两个功能：
 *   - Section 1「发送评论」：AI 生成候选评论 + 编辑 + 真实发送/草稿
 *   - Section 2「生成发布文案」：AI 生成发布文案 + 复制剪贴板 + 跳转发布中心预填
 */
const CommentComposeModal: React.FC<CommentComposeModalProps> = ({ post, open, onClose }) => {
  const { platform } = usePlatform();
  const navigate = useNavigate();
  const normalizedPlatform = PLATFORM_TO_PIPELINE[platform] || platform;

  const generationParams = () => ({
    post_id: post.post_id,
    platform: normalizedPlatform,
    post_url: post.post_url,
    content: post.content,
    username: post.username,
    video_url: post.video_url || '',
    count: 3,
  });

  // ===== Section 1: 发送评论 =====
  const [suggestedComments, setSuggestedComments] = useState<string[]>([]);
  const [editComment, setEditComment] = useState('');
  const [generating, setGenerating] = useState(false);
  const [sending, setSending] = useState(false);

  // ===== Section 2: 生成发布文案 =====
  const [postContents, setPostContents] = useState<string[]>([]);
  const [selectedPostContent, setSelectedPostContent] = useState('');
  const [generatingContent, setGeneratingContent] = useState(false);

  const doGenComments = async () => {
    setGenerating(true);
    try {
      const r = await xWorkbenchApi.generateComments(generationParams());
      if (r.comments && r.comments.length > 0) {
        setSuggestedComments(r.comments);
        setEditComment(r.comments[0]);
        message.success(`已生成 ${r.comments.length} 条候选评论`);
      } else {
        message.warning('未生成候选评论');
      }
    } catch (e: any) {
      message.error('生成评论失败: ' + apiErrorMessage(e, ''));
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
        platform,
      });
      if (r.success) {
        message.success(`评论已${real ? '发送' : '保存为草稿'}（ID: ${r.sent_comment_id}）`);
        onClose();
      } else {
        message.error(`发送失败: ${r.message || '未知错误'}`);
      }
    } catch (e: any) {
      message.error('发送异常: ' + apiErrorMessage(e, ''));
    } finally {
      setSending(false);
    }
  };

  const doGenPostContent = async () => {
    setGeneratingContent(true);
    try {
      const r = await xWorkbenchApi.generateXPostContent(generationParams());
      if (r.contents && r.contents.length > 0) {
        setPostContents(r.contents);
        setSelectedPostContent(r.contents[0]);
        message.success(`已生成 ${r.contents.length} 条发布文案`);
      } else {
        message.warning('未生成发布文案');
      }
    } catch (e: any) {
      message.error('生成发布文案失败: ' + apiErrorMessage(e, ''));
    } finally {
      setGeneratingContent(false);
    }
  };

  const copyToClipboard = async (text: string) => {
    if (!text) {
      message.warning('请先选择一条文案');
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      message.success('已复制到剪贴板');
    } catch {
      // 某些浏览器在非 HTTPS 下禁用 clipboard API，降级提示
      message.warning('剪贴板不可用，请手动选择文案复制');
    }
  };

  const goToPublishCenter = () => {
    if (!selectedPostContent) {
      message.warning('请先选择一条文案');
      return;
    }
    onClose();
    navigate('/publish-center', {
      state: {
        from_breakdown: true,
        source_post_id: post.post_id,
        video_url: post.video_url || '',
        content: selectedPostContent,
        platform: PLATFORM_TO_PIPELINE[platform] || platform,
        title: `@${post.username} 热点拆解`,
      },
    });
  };

  return (
    <Modal
      title={
        <Space>
          <MessageOutlined />
          <span>评论与文案 - @{post.username}</span>
        </Space>
      }
      open={open}
      onCancel={onClose}
      width={720}
      footer={
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            当前平台：{normalizedPlatform}
          </Text>
          <Button onClick={onClose}>关闭</Button>
        </Space>
      }
    >
      <Paragraph ellipsis={{ rows: 2 }} type="secondary">
        {post.content}
      </Paragraph>

      {/* ===== Section 1: 发送评论 ===== */}
      <Card
        size="small"
        title={
          <Space>
            <MessageOutlined style={{ color: '#1677ff' }} />
            <span>【发送评论】</span>
          </Space>
        }
        extra={
          <Button
            size="small"
            icon={<ThunderboltOutlined />}
            loading={generating}
            onClick={doGenComments}
          >
            {suggestedComments.length > 0 ? '重新生成' : '生成候选评论'}
          </Button>
        }
        style={{ marginBottom: 12 }}
      >
        {suggestedComments.length > 0 && (
          <Space direction="vertical" style={{ width: '100%', marginBottom: 12 }} size={8}>
            {suggestedComments.map((c, i) => (
              <Button
                key={i}
                block
                style={{
                  textAlign: 'left',
                  height: 'auto',
                  whiteSpace: 'normal',
                  padding: '8px 12px',
                }}
                type={editComment === c ? 'primary' : 'default'}
                onClick={() => setEditComment(c)}
              >
                {c}
              </Button>
            ))}
          </Space>
        )}

        <TextArea
          rows={3}
          placeholder="编辑评论内容（最多 280 字符）"
          value={editComment}
          onChange={(e) => setEditComment(e.target.value)}
          maxLength={280}
          showCount
        />
        <Space style={{ marginTop: 12 }} wrap>
          <Button type="primary" icon={<SendOutlined />} loading={sending} onClick={() => doSend(true)}>
            真实发送
          </Button>
          <Button icon={<EditOutlined />} loading={sending} onClick={() => doSend(false)}>
            保存为草稿
          </Button>
          <Text type="secondary" style={{ fontSize: 12 }}>
            真实发送需要 Cookie 已配置
          </Text>
        </Space>
      </Card>

      {/* ===== Section 2: 生成发布文案 ===== */}
      <Card
        size="small"
        title={
          <Space>
            <FileTextOutlined style={{ color: '#722ed1' }} />
            <span>【生成发布文案】</span>
            <Tag color="purple" style={{ fontSize: 11 }}>用于发布中心预填</Tag>
          </Space>
        }
        extra={
          <Button
            size="small"
            icon={<ThunderboltOutlined />}
            loading={generatingContent}
            onClick={doGenPostContent}
          >
            {postContents.length > 0 ? '重新生成' : '生成文案'}
          </Button>
        }
      >
        {postContents.length === 0 ? (
          <Text type="secondary">
            点击右上角「生成文案」按钮，AI 将基于当前热点内容生成适合发布的文案；选中后可复制或直接跳转发布中心预填发布。
          </Text>
        ) : (
          <Spin spinning={generatingContent}>
            <Space direction="vertical" style={{ width: '100%' }} size={8}>
              {postContents.map((c, i) => (
                <Button
                  key={i}
                  block
                  style={{
                    textAlign: 'left',
                    height: 'auto',
                    whiteSpace: 'normal',
                    padding: '8px 12px',
                  }}
                  type={selectedPostContent === c ? 'primary' : 'default'}
                  onClick={() => setSelectedPostContent(c)}
                >
                  {c}
                </Button>
              ))}
            </Space>

            <Divider style={{ margin: '12px 0' }} />

            <Space wrap>
              <Tooltip title="复制选中文案到剪贴板">
                <Button
                  icon={<CopyOutlined />}
                  onClick={() => copyToClipboard(selectedPostContent)}
                  disabled={!selectedPostContent}
                >
                  复制文案
                </Button>
              </Tooltip>
              <Button
                type="primary"
                icon={<RocketOutlined />}
                onClick={goToPublishCenter}
                disabled={!selectedPostContent}
                style={{ background: '#722ed1', borderColor: '#722ed1' }}
              >
                跳转发布中心（预填文案）
              </Button>
              <Text type="secondary" style={{ fontSize: 12 }}>
                跳转后发布中心将自动填入文案、视频 URL、来源帖子 ID
              </Text>
            </Space>
          </Spin>
        )}
      </Card>
    </Modal>
  );
};

export default CommentComposeModal;
