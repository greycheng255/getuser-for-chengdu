import type { FC } from 'react';
import { Skeleton, Card, List } from 'antd';

interface PageSkeletonProps {
  /** 骨架项数量,默认 5 */
  count?: number;
  /** 是否用 Card 包裹,默认 true */
  card?: boolean;
}

/**
 * 通用页面级骨架屏
 *
 * 在数据加载中时显示,替代简单的 Spin 转圈,
 * 提供更好的视觉占位(避免页面跳动)。
 *
 * 用法:
 *   {loading ? <PageSkeleton count={5} /> : <ActualContent />}
 */
const PageSkeleton: FC<PageSkeletonProps> = ({ count = 5, card = true }) => {
  const items = Array.from({ length: count }, (_, i) => i);

  const skeletonList = (
    <List
      itemLayout="vertical"
      dataSource={items}
      renderItem={() => (
        <List.Item>
          <Skeleton
            active
            avatar
            paragraph={{ rows: 3, width: ['60%', '90%', '40%'] }}
            title={{ width: '30%' }}
          />
        </List.Item>
      )}
    />
  );

  if (!card) {
    return skeletonList;
  }

  return (
    <Card size="small">
      {skeletonList}
    </Card>
  );
};

export default PageSkeleton;

/**
 * 表格骨架屏(用于 Table 组件加载中)
 */
export const TableSkeleton: FC<{ rows?: number; columns?: number }> = ({
  rows = 5,
  columns = 4,
}) => {
  const colArr = Array.from({ length: columns }, (_, i) => i);
  const rowArr = Array.from({ length: rows }, (_, i) => i);
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
      <thead>
        <tr>
          {colArr.map((c) => (
            <th key={c} style={{ padding: '12px 8px', textAlign: 'left', borderBottom: '1px solid #f0f0f0' }}>
              <Skeleton.Input active size="small" style={{ width: 80 }} />
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rowArr.map((r) => (
          <tr key={r}>
            {colArr.map((c) => (
              <td key={c} style={{ padding: '12px 8px', borderBottom: '1px solid #f0f0f0' }}>
                <Skeleton active paragraph={{ rows: 1, width: '80%' }} title={false} />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
};

/**
 * 统计卡片骨架屏(用于 Stats Cards 加载中)
 */
export const StatsSkeleton: FC<{ count?: number }> = ({ count = 4 }) => {
  const items = Array.from({ length: count }, (_, i) => i);
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${count}, 1fr)`, gap: 12 }}>
      {items.map((i) => (
        <Card key={i} size="small">
          <Skeleton active paragraph={{ rows: 1, width: '60%' }} title={{ width: '40%' }} />
        </Card>
      ))}
    </div>
  );
};
