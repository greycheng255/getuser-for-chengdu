import React from 'react';
import { Card, Skeleton } from 'antd';

const SkeletonCard: React.FC<{ rows?: number }> = ({ rows = 4 }) => (
  <Card><Skeleton active paragraph={{ rows }} /></Card>
);

export default SkeletonCard;
