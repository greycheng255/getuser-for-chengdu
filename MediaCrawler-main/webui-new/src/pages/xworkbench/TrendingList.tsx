import { memo, useMemo } from 'react';
import { List, Tag, Avatar, Space, Button, Typography, Checkbox } from 'antd';
import {
  TwitterOutlined,
  VideoCameraOutlined,
  MessageOutlined,
  PlayCircleOutlined,
  LinkOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import type { WorkbenchPost } from '../../api/xWorkbench';

const { Text } = Typography;

interface PostCardProps {
  post: WorkbenchPost;
  onOpenBreakdown: (post: WorkbenchPost) => void;
  onStartAutoPipeline: (post: WorkbenchPost) => void;
  onOpenComment?: (post: WorkbenchPost) => void;
  selectable?: boolean;
  selected?: boolean;
  onSelectChange?: (postId: string, checked: boolean) => void;
  primaryColor?: string;
  PlatformIcon?: React.ComponentType<any>;
}

const PostCard = memo<PostCardProps>(({
  post,
  onOpenBreakdown,
  onStartAutoPipeline,
  onOpenComment,
  selectable,
  selected,
  onSelectChange,
  primaryColor = '#1DA1F2',
  PlatformIcon = TwitterOutlined,
}) => {
  return (
    <List.Item
      key={post.post_id}
      actions={[
        <Button
          type="primary"
          size="small"
          icon={<ThunderboltOutlined />}
          onClick={() => onStartAutoPipeline(post)}
          style={{ backgroundColor: primaryColor, borderColor: primaryColor }}
        >
          一键拆解全流程
        </Button>,
        <Button
          size="small"
          icon={<VideoCameraOutlined />}
          onClick={() => onOpenBreakdown(post)}
        >
          视频拆解
        </Button>,
        <Button
          size="small"
          icon={<MessageOutlined />}
          onClick={() => (onOpenComment ? onOpenComment(post) : onOpenBreakdown(post))}
        >
          生成评论
        </Button>,
        <Button
          size="small"
          type="link"
          icon={<LinkOutlined />}
          href={post.post_url}
          target="_blank"
        >
          打开原帖
        </Button>,
      ]}
    >
      <List.Item.Meta
        avatar={
          selectable ? (
            <Space direction="vertical" size={8} align="center">
              <Checkbox
                checked={selected}
                onChange={(e) => onSelectChange?.(post.post_id, e.target.checked)}
              />
              <Avatar icon={<PlatformIcon />} style={{ backgroundColor: primaryColor }} />
            </Space>
          ) : (
            <Avatar icon={<PlatformIcon />} style={{ backgroundColor: primaryColor }} />
          )
        }
        title={
          <Space>
            <Text strong>@{post.username || 'unknown'}</Text>
            {post.source_keyword && <Tag color="blue">{post.source_keyword}</Tag>}
            {post.video_url && (
              <Tag color="purple" icon={<PlayCircleOutlined />}>
                视频
              </Tag>
            )}
          </Space>
        }
        description={
          <div style={{ 
            marginBottom: 0, 
            color: '#595959', 
            fontSize: 14, 
            lineHeight: 1.7,
            wordBreak: 'break-all',
            overflowWrap: 'anywhere',
            whiteSpace: 'pre-wrap',
            maxHeight: '4.2em',
            overflow: 'hidden',
            textOverflow: 'ellipsis'
          }}>
            {post.content}
          </div>
        }
      />
      <Space size="middle" style={{ color: '#8c8c8c', fontSize: 12 }}>
        <span>❤️ {post.likes_count || 0}</span>
        <span>🔁 {post.retweets_count || 0}</span>
        <span>💬 {post.replies_count || 0}</span>
        <span>👁 {post.views_count || 0}</span>
      </Space>
    </List.Item>
  );
});

PostCard.displayName = 'PostCard';

interface TrendingListProps {
  posts: WorkbenchPost[];
  onOpenBreakdown: (post: WorkbenchPost) => void;
  onStartAutoPipeline: (post: WorkbenchPost) => void;
  onOpenComment?: (post: WorkbenchPost) => void;
  loading: boolean;
  selectable?: boolean;
  selectedIds?: string[];
  onSelectChange?: (postId: string, checked: boolean) => void;
  primaryColor?: string;
  PlatformIcon?: React.ComponentType<any>;
}

/**
 * 热点内容列表(带分页,避免一次渲染过多)
 */
const TrendingList = memo<TrendingListProps>(({
  posts,
  onOpenBreakdown,
  onStartAutoPipeline,
  onOpenComment,
  loading,
  selectable,
  selectedIds,
  onSelectChange,
  primaryColor,
  PlatformIcon,
}) => {
  const dataSource = useMemo(() => posts, [posts]);

  if (loading) return null;
  if (dataSource.length === 0) return null;

  return (
    <List
      itemLayout="vertical"
      dataSource={dataSource}
      pagination={{
        pageSize: 20,
        showSizeChanger: false,
        showTotal: (total) => `共 ${total} 条`,
        size: 'small',
      }}
      style={{ marginTop: 16 }}
      renderItem={(post) => (
        <PostCard
          key={post.post_id}
          post={post}
          onOpenBreakdown={onOpenBreakdown}
          onStartAutoPipeline={onStartAutoPipeline}
          onOpenComment={onOpenComment}
          selectable={selectable}
          selected={selectedIds?.includes(post.post_id)}
          onSelectChange={onSelectChange}
          primaryColor={primaryColor}
          PlatformIcon={PlatformIcon}
        />
      )}
    />
  );
});

TrendingList.displayName = 'TrendingList';

export default TrendingList;
