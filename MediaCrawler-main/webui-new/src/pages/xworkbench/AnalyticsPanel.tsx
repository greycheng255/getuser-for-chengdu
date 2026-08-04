import { message } from '../../utils/antdMessage';
import { useEffect, useState, useCallback, useMemo } from 'react';
import { Card, Table, Button, Space, Select, Tag, Tooltip, Typography, Statistic, Row, Col, Progress, Empty } from 'antd';
import {
  ReloadOutlined,
  MessageOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  ThunderboltOutlined,
  FileExcelOutlined,
} from '@ant-design/icons';
import { Line } from '@ant-design/charts';
import {
  xWorkbenchApi,
  type AnalyticsSummary,
  type CommentAnalytics,
  type AnalyticsTimeline,
  type TopicStat,
} from '../../api/xWorkbench';
import PageSkeleton, { StatsSkeleton } from '../../components/PageSkeleton';

const { Text } = Typography;

/**
 * 评论效果分析面板
 *
 * 展示评论发送效果的多维度分析:
 * - 总体概览(发送数/回复数/回复率/AI覆盖率/平均响应时间)
 * - 时间序列折线图(每日发送量 vs 回复量)
 * - 单条评论效果排名(按互动评分排序)
 * - 按话题分组的效果统计
 */
const AnalyticsPanel = () => {
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [commentsLoading, setCommentsLoading] = useState(false);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [topicsLoading, setTopicsLoading] = useState(false);

  const [summary, setSummary] = useState<AnalyticsSummary | null>(null);
  const [comments, setComments] = useState<CommentAnalytics[]>([]);
  const [commentsTotal, setCommentsTotal] = useState(0);
  const [timeline, setTimeline] = useState<AnalyticsTimeline | null>(null);
  const [topics, setTopics] = useState<TopicStat[]>([]);

  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState('reply_count');
  const [days, setDays] = useState(30);
  const [exporting, setExporting] = useState(false);

  // 导出完整效果分析报告(Excel 多 sheet)
  const handleExportReport = useCallback(async () => {
    setExporting(true);
    try {
      await xWorkbenchApi.exportAnalytics();
      message.success('报告导出成功,请检查浏览器下载');
    } catch (e: any) {
      message.error('导出失败: ' + (e?.message || ''));
    } finally {
      setExporting(false);
    }
  }, []);

  // 加载概览
  const loadSummary = useCallback(async () => {
    setSummaryLoading(true);
    try {
      const r = await xWorkbenchApi.analyticsSummary();
      setSummary(r);
    } catch (e: any) {
      message.error('加载概览失败: ' + (e?.message || ''));
    } finally {
      setSummaryLoading(false);
    }
  }, []);

  // 加载评论排名
  const loadComments = useCallback(async () => {
    setCommentsLoading(true);
    try {
      const r = await xWorkbenchApi.analyticsComments({ page, page_size: 20, sort_by: sortBy });
      setComments(r.items || []);
      setCommentsTotal(r.total || 0);
    } catch (e: any) {
      message.error('加载评论排名失败: ' + (e?.message || ''));
    } finally {
      setCommentsLoading(false);
    }
  }, [page, sortBy]);

  // 加载时间序列
  const loadTimeline = useCallback(async () => {
    setTimelineLoading(true);
    try {
      const r = await xWorkbenchApi.analyticsTimeline(days);
      setTimeline(r);
    } catch (e: any) {
      message.error('加载时间序列失败: ' + (e?.message || ''));
    } finally {
      setTimelineLoading(false);
    }
  }, [days]);

  // 加载话题统计
  const loadTopics = useCallback(async () => {
    setTopicsLoading(true);
    try {
      const r = await xWorkbenchApi.analyticsTopics();
      setTopics(r.items || []);
    } catch (e: any) {
      message.error('加载话题统计失败: ' + (e?.message || ''));
    } finally {
      setTopicsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSummary();
    loadTimeline();
    loadTopics();
  }, [loadSummary, loadTimeline, loadTopics]);

  useEffect(() => {
    loadComments();
  }, [loadComments]);

  // 折线图数据(用 useMemo 转换为图表需要的格式)
  const timelineChartData = useMemo(() => {
    if (!timeline) return [];
    const data: Array<{ date: string; type: string; value: number }> = [];
    timeline.dates.forEach((d, i) => {
      data.push({ date: d, type: '发送评论', value: timeline.sent_counts[i] || 0 });
      data.push({ date: d, type: '收到回复', value: timeline.reply_counts[i] || 0 });
      data.push({ date: d, type: 'AI回复', value: timeline.ai_reply_counts[i] || 0 });
    });
    return data;
  }, [timeline]);

  const timelineConfig = useMemo(() => ({
    data: timelineChartData,
    xField: 'date',
    yField: 'value',
    seriesField: 'type',
    smooth: true,
    height: 280,
    color: ['#1890ff', '#52c41a', '#fa8c16'],
    legend: { position: 'top' as const },
    tooltip: { showCrosshairs: true },
  }), [timelineChartData]);

  // 评论排名表格列
  const commentColumns = useMemo(() => [
    {
      title: '排名',
      key: 'rank',
      width: 60,
      render: (_: any, __: CommentAnalytics, idx: number) => (
        <Text strong style={{ color: idx < 3 ? '#fa541c' : '#8c8c8c' }}>
          #{(page - 1) * 20 + idx + 1}
        </Text>
      ),
    },
    {
      title: '评论内容',
      dataIndex: 'comment_content',
      key: 'comment_content',
      ellipsis: true,
      render: (text: string, record: CommentAnalytics) => (
        <Tooltip title={text}>
          <Space direction="vertical" size={0}>
            <Text ellipsis style={{ maxWidth: 300 }}>{text}</Text>
            <Text type="secondary" style={{ fontSize: 11 }}>
              @{record.post_username} · {record.hours_since_sent}h 前
            </Text>
          </Space>
        </Tooltip>
      ),
    },
    {
      title: '回复数',
      dataIndex: 'reply_count',
      key: 'reply_count',
      width: 80,
      sorter: true,
      render: (n: number) => (
        <Tag color={n > 0 ? 'green' : 'default'}>
          <MessageOutlined /> {n}
        </Tag>
      ),
    },
    {
      title: 'AI已回复',
      dataIndex: 'auto_replied_count',
      key: 'auto_replied_count',
      width: 90,
      render: (n: number) => (
        <Tag color={n > 0 ? 'blue' : 'default'}>
          <ThunderboltOutlined /> {n}
        </Tag>
      ),
    },
    {
      title: '互动评分',
      dataIndex: 'engagement_score',
      key: 'engagement_score',
      width: 120,
      render: (score: number) => (
        <Progress
          percent={Math.min(score * 10, 100)}
          size="small"
          format={() => `${score} 分`}
          strokeColor={score >= 5 ? '#52c41a' : score >= 2 ? '#faad14' : '#d9d9d9'}
        />
      ),
    },
    {
      title: '监控',
      dataIndex: 'monitoring',
      key: 'monitoring',
      width: 70,
      render: (m: number) => (
        <Tag color={m === 1 ? 'processing' : 'default'}>
          {m === 1 ? '监控中' : '已停止'}
        </Tag>
      ),
    },
  ], [page]);

  // 话题统计表格列
  const topicColumns = useMemo(() => [
    {
      title: '话题/作者',
      dataIndex: 'topic',
      key: 'topic',
      render: (t: string) => <Text strong>@{t}</Text>,
    },
    {
      title: '评论数',
      dataIndex: 'comment_count',
      key: 'comment_count',
      width: 80,
      sorter: (a: TopicStat, b: TopicStat) => a.comment_count - b.comment_count,
    },
    {
      title: '回复数',
      dataIndex: 'reply_count',
      key: 'reply_count',
      width: 80,
      sorter: (a: TopicStat, b: TopicStat) => a.reply_count - b.reply_count,
      render: (n: number) => <Tag color={n > 0 ? 'green' : 'default'}>{n}</Tag>,
    },
    {
      title: '回复率',
      dataIndex: 'reply_rate',
      key: 'reply_rate',
      width: 120,
      render: (rate: number) => (
        <Progress
          percent={rate}
          size="small"
          strokeColor={rate >= 50 ? '#52c41a' : rate >= 20 ? '#faad14' : '#d9d9d9'}
        />
      ),
    },
    {
      title: 'AI覆盖率',
      dataIndex: 'ai_coverage',
      key: 'ai_coverage',
      width: 120,
      render: (rate: number) => (
        <Progress
          percent={rate}
          size="small"
          strokeColor={rate >= 80 ? '#52c41a' : rate >= 50 ? '#faad14' : '#d9d9d9'}
        />
      ),
    },
  ], []);

  return (
    <div>
      {/* 总体概览卡片 */}
      {summaryLoading ? (
        <StatsSkeleton count={4} />
      ) : summary ? (
        <Row gutter={12} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Card size="small">
              <Statistic
                title="发送评论"
                value={summary.send_stats.total}
                prefix={<MessageOutlined />}
                suffix={<Text type="secondary" style={{ fontSize: 12 }}>({summary.send_stats.success} 成功)</Text>}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic
                title="发送成功率"
                value={summary.send_stats.success_rate}
                precision={1}
                suffix="%"
                prefix={<CheckCircleOutlined />}
                valueStyle={{ color: summary.send_stats.success_rate >= 80 ? '#3f8600' : '#cf1322' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic
                title="回复率"
                value={summary.reply_stats.reply_rate}
                precision={1}
                suffix="%"
                prefix={<MessageOutlined />}
                valueStyle={{ color: summary.reply_stats.reply_rate >= 30 ? '#3f8600' : '#8c8c8c' }}
              />
              <Text type="secondary" style={{ fontSize: 11 }}>
                收到 {summary.reply_stats.total_replies} 条回复
              </Text>
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic
                title="平均响应时间"
                value={summary.response_time.avg_hours}
                precision={1}
                suffix="小时"
                prefix={<ClockCircleOutlined />}
              />
              <Text type="secondary" style={{ fontSize: 11 }}>
                AI覆盖率 {summary.reply_stats.ai_coverage}%
              </Text>
            </Card>
          </Col>
        </Row>
      ) : null}

      {/* 时间序列折线图 */}
      <Card
        title="发送 & 回复趋势"
        size="small"
        style={{ marginBottom: 16 }}
        extra={
          <Space>
            <Select
              value={days}
              onChange={setDays}
              size="small"
              options={[
                { value: 7, label: '最近 7 天' },
                { value: 30, label: '最近 30 天' },
                { value: 90, label: '最近 90 天' },
              ]}
              style={{ width: 120 }}
            />
            <Button size="small" icon={<ReloadOutlined />} onClick={loadTimeline}>刷新</Button>
          </Space>
        }
      >
        {timelineLoading ? (
          <PageSkeleton count={3} card={false} />
        ) : timelineChartData.length > 0 ? (
          <Line {...timelineConfig} />
        ) : (
          <Empty description="暂无时间序列数据" />
        )}
      </Card>

      {/* 评论效果排名 */}
      <Card
        title="评论效果排名(按互动评分)"
        size="small"
        style={{ marginBottom: 16 }}
        extra={
          <Space>
            <Select
              value={sortBy}
              onChange={(v) => { setSortBy(v); setPage(1); }}
              size="small"
              style={{ width: 140 }}
              options={[
                { value: 'reply_count', label: '按回复数排序' },
                { value: 'auto_replied_count', label: '按AI回复数排序' },
                { value: 'sent_at', label: '按发送时间排序' },
              ]}
            />
            <Button size="small" icon={<ReloadOutlined />} onClick={loadComments}>刷新</Button>
          </Space>
        }
      >
        <Table
          rowKey="id"
          columns={commentColumns}
          dataSource={comments}
          loading={commentsLoading}
          size="middle"
          pagination={{
            current: page,
            pageSize: 20,
            total: commentsTotal,
            showTotal: (t) => `共 ${t} 条`,
            onChange: setPage,
            size: 'small',
          }}
        />
      </Card>

      {/* 话题统计 */}
      <Card
        title="按作者/话题分组的效果统计"
        size="small"
        extra={
          <Space>
            <Button
              size="small"
              type="primary"
              ghost
              icon={<FileExcelOutlined />}
              loading={exporting}
              onClick={handleExportReport}
            >
              导出完整报告
            </Button>
            <Button size="small" icon={<ReloadOutlined />} onClick={loadTopics}>刷新</Button>
          </Space>
        }
      >
        <Table
          rowKey="topic"
          columns={topicColumns}
          dataSource={topics}
          loading={topicsLoading}
          size="middle"
          pagination={{ pageSize: 10, size: 'small' }}
        />
      </Card>
    </div>
  );
};

export default AnalyticsPanel;
