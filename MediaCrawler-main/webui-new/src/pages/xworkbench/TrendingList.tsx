import { memo, useMemo } from 'react';
import { List, Tag, Avatar, Space, Button, Typography, Checkbox } from 'antd';
import {
  TwitterOutlined,
  VideoCameraOutlined,
  MessageOutlined,
  PlayCircleOutlined,
  LinkOutlined,
} from '@ant-design/icons';
import type { WorkbenchPost } from '../../api/xWorkbench';

const { Text } = Typography;

interface PostCardProps {
  post: WorkbenchPost;
  onOpenBreakdown: (post: WorkbenchPost) => void;
  selectable?: boolean;
  selected?: boolean;
  onSelectChange?: (postId: string, checked: boolean) => void;
}

/**
 * 单条热点推文卡片
 *
 * 用 React.memo 包裹,只有当 post 或 onOpenBreakdown 变化时才重渲染。
 * 避免父组件输入搜索关键词时,200 条卡片全部重渲染。
 */
const PostCard = memo<PostCardProps>(({ post, onOpenBreakdown, selectable, selected, onSelectChange }) => {
  return (
    <List.Item
      key={post.post_id}
      actions={[
        <Button
          type="primary"
          size="small"
          icon={<VideoCameraOutlined />}
          onClick={() => onOpenBreakdown(post)}
        >
          视频拆解
        </Button>,
        <Button
          size="small"
          icon={<MessageOutlined />}
          onClick={() => onOpenBreakdown(post)}
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
          打开原推
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
              <Avatar icon={<TwitterOutlined />} style={{ backgroundColor: '#1DA1F2' }} />
            </Space>
          ) : (
            <Avatar icon={<TwitterOutlined />} style={{ backgroundColor: '#1DA1F2' }} />
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
  loading: boolean;
  selectable?: boolean;
  selectedIds?: string[];
  onSelectChange?: (postId: string, checked: boolean) => void;
}

/**
 * 热点推文列表(带分页,避免一次渲染 200 条)
 */
const TrendingList = memo<TrendingListProps>(({ posts, onOpenBreakdown, loading, selectable, selectedIds, onSelectChange }) => {
  // 用 useMemo 缓存 dataSource,避免每次 render 创建新数组
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
          selectable={selectable}
          selected={selectedIds?.includes(post.post_id)}
          onSelectChange={onSelectChange}
        />
      )}
    />
  );
});

TrendingList.displayName = 'TrendingList';

export default TrendingList;
