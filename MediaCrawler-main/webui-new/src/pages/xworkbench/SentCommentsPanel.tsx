import React, { useEffect, useState, useCallback } from 'react';
import {
  Row,
  Col,
  Card,
  Statistic,
  List,
  Input,
  Tag,
  Button,
  Space,
  Switch,
  message,
  Typography,
  Select,
  DatePicker,
  Dropdown,
} from 'antd';
import type { Dayjs } from 'dayjs';
import {
  TwitterOutlined,
  MessageOutlined,
  ReloadOutlined,
  SendOutlined,
  ThunderboltOutlined,
  CheckCircleTwoTone,
  CloseCircleTwoTone,
  EyeOutlined,
  LinkOutlined,
  EditOutlined,
  PlayCircleOutlined,
  DownloadOutlined,
  FileExcelOutlined,
  FileTextOutlined,
} from '@ant-design/icons';
import {
  xWorkbenchApi,
  type SentComment,
  type WorkbenchStats,
} from '../../api/xWorkbench';
import RepliesModal from './RepliesModal';

const { Text } = Typography;

/**
 * 已发评论 & 回复面板
 * 展示已发评论列表 + 统计卡片 + 搜索筛选 + 回复管理
 */
const SentCommentsPanel: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [list, setList] = useState<SentComment[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [statusFilter, setStatusFilter] = useState<string>('');
  // keyword=输入框值(即时更新);searchKeyword=实际查询值(防抖后更新)
  // 分离两者避免每次按键都触发 load
  const [keyword, setKeyword] = useState('');
  const [searchKeyword, setSearchKeyword] = useState('');
  const [dateRange, setDateRange] = useState<[Dayjs | null, Dayjs | null] | null>(null);
  const [repliesModal, setRepliesModal] = useState<{ open: boolean; sc?: SentComment }>({ open: false });
  const [stats, setStats] = useState<WorkbenchStats | null>(null);
  const [exporting, setExporting] = useState<'sent-csv' | 'sent-xlsx' | 'replies-csv' | 'replies-xlsx' | null>(null);

  // 导出已发评论或回复
  const handleExport = useCallback(async (
    kind: 'sent' | 'replies',
    format: 'csv' | 'xlsx',
  ) => {
    const key = `${kind}-${format}` as typeof exporting;
    setExporting(key);
    try {
      const params: any = { format };
      if (statusFilter) params.status = statusFilter;
      if (dateRange && dateRange[0]) params.start_ts = dateRange[0].startOf('day').unix();
      if (dateRange && dateRange[1]) params.end_ts = dateRange[1].endOf('day').unix();
      if (kind === 'sent') {
        await xWorkbenchApi.exportSentComments(params);
      } else {
        await xWorkbenchApi.exportReplies(params);
      }
      message.success('导出成功,请检查浏览器下载');
    } catch (e: any) {
      message.error('导出失败: ' + (e?.message || ''));
    } finally {
      setExporting(null);
    }
  }, [statusFilter, dateRange]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params: any = { page, page_size: pageSize };
      if (statusFilter) params.status = statusFilter;
      if (searchKeyword) params.keyword = searchKeyword;
      if (dateRange && dateRange[0]) params.start_ts = dateRange[0].startOf('day').unix();
      if (dateRange && dateRange[1]) params.end_ts = dateRange[1].endOf('day').unix();

      const r = await xWorkbenchApi.listComments(params);
      setList(r.items || []);
      setTotal(r.total || 0);
    } catch (e: any) {
      message.error('加载失败: ' + (e?.message || ''));
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, statusFilter, searchKeyword, dateRange]);

  const loadStats = useCallback(async () => {
    try {
      const s = await xWorkbenchApi.getStats();
      setStats(s);
    } catch {}
  }, []);

  // 防抖:keyword 输入停止 400ms 后,同步到 searchKeyword 并重置到第 1 页
  useEffect(() => {
    const t = setTimeout(() => {
      setSearchKeyword(keyword);
      setPage(1);
    }, 400);
    return () => clearTimeout(t);
  }, [keyword]);

  useEffect(() => {
    load();
    loadStats();
  }, [load, loadStats]);

  const toggleMonitoring = async (sc: SentComment, checked: boolean) => {
    try {
      await xWorkbenchApi.updateMonitoring(sc.id, checked ? 1 : 0);
      message.success(checked ? '已开始监控回复' : '已停止监控');
      load();
    } catch (e: any) {
      message.error('操作失败: ' + (e?.message || ''));
    }
  };

  const renderItem = (item: SentComment) => {
    const statusMap: Record<string, { color: string; text: string; icon: React.ReactNode }> = {
      success: { color: 'green', text: '已发送', icon: <CheckCircleTwoTone twoToneColor="#52c41a" /> },
      failed: { color: 'red', text: '失败', icon: <CloseCircleTwoTone twoToneColor="#ff4d4f" /> },
      draft: { color: 'orange', text: '草稿', icon: <EditOutlined /> },
      pending: { color: 'blue', text: '待发', icon: <SendOutlined /> },
    };
    const status = statusMap[item.sent_status] || statusMap.pending;

    return (
      <List.Item
        key={item.id}
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          gap: 16,
          padding: '16px 0',
          borderBottom: '1px solid #f0f0f0',
          flexWrap: 'wrap',
        }}
      >
        {/* 左侧: 内容区 (自适应宽度) */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {/* 原帖内容 */}
          <div style={{ fontSize: 12, color: '#8c8c8c', marginBottom: 8, lineHeight: 1.6, wordBreak: 'break-all', overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' }}>
            <Text strong>@{item.post_username}</Text>: {item.post_content}
          </div>
          {/* 我的评论 */}
          <div style={{ fontSize: 14, marginBottom: 10, lineHeight: 1.8, wordBreak: 'break-all', overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' }}>
            {item.comment_content}
          </div>
          {/* 操作链接按钮 */}
          <Space size="small" wrap>
            {item.video_url && (
              <Button size="small" type="link" icon={<PlayCircleOutlined />} href={item.video_url} target="_blank">
                视频
              </Button>
            )}
            {item.post_url && (
              <Button size="small" type="link" icon={<TwitterOutlined />} href={item.post_url} target="_blank">
                原贴
              </Button>
            )}
            {item.comment_url && (
              <Button size="small" type="link" icon={<LinkOutlined />} href={item.comment_url} target="_blank">
                我的评论
              </Button>
            )}
          </Space>
        </div>

        {/* 右侧: 状态 + 操作 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 200, alignItems: 'flex-end' }}>
          <Space size={8}>
            <Tag color={status.color} icon={status.icon}>{status.text}</Tag>
          </Space>
          <Space size={16}>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 12, color: '#8c8c8c' }}>收到回复</div>
              <div style={{ fontSize: 16, fontWeight: 600 }}>{item.reply_count || 0}</div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 12, color: '#52c41a' }}>AI 回复</div>
              <div style={{ fontSize: 16, fontWeight: 600, color: '#52c41a' }}>{item.auto_replied_count || 0}</div>
            </div>
          </Space>
          {item.sent_status === 'success' && (
            <Space size={8}>
            <Text type="secondary" style={{ fontSize: 12 }}>监控回复</Text>
            <Switch
              checked={item.monitoring === 1}
              size="small"
              onChange={(c) => toggleMonitoring(item, c)}
            />
            </Space>
          )}
          <div style={{ fontSize: 12, color: '#8c8c8c' }}>
            {item.sent_at ? new Date(item.sent_at * 1000).toLocaleString('zh-CN') : '-'}
          </div>
          <Space>
            <Button size="small" icon={<EyeOutlined />} onClick={() => setRepliesModal({ open: true, sc: item })}>
              查看回复
            </Button>
          </Space>
        </div>
      </List.Item>
    );
  };

  return (
    <div style={{ overflow: 'hidden' }}>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="已发评论总数" value={stats?.total_sent_comments || 0} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="成功发送" value={stats?.success_sent || 0} prefix={<CheckCircleTwoTone twoToneColor="#52c41a" />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="收到回复" value={stats?.total_replies || 0} prefix={<MessageOutlined />} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="待处理" value={stats?.pending_replies || 0} prefix={<ThunderboltOutlined />} valueStyle={{ color: (stats?.pending_replies || 0) > 0 ? '#fa8c16' : undefined }} />
          </Card>
        </Col>
      </Row>

      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          placeholder="筛选状态"
          value={statusFilter || undefined}
          onChange={(v) => {
            setStatusFilter(v || '');
            setPage(1);
          }}
          allowClear
          style={{ width: 140 }}
          options={[
            { value: 'success', label: '已发送' },
            { value: 'failed', label: '失败' },
            { value: 'draft', label: '草稿' },
          ]}
        />
        <Input.Search
          placeholder="搜索关键词（评论/推文/作者）"
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onSearch={(v) => { setSearchKeyword(v); setPage(1); }}
          style={{ width: 260 }}
          allowClear
        />
        <DatePicker.RangePicker
          value={dateRange}
          onChange={(dates) => {
            setDateRange(dates ? [dates[0], dates[1]] : null);
            setPage(1);
          }}
          placeholder={['开始日期', '结束日期']}
          style={{ width: 240 }}
          allowClear
        />
        <Button icon={<ReloadOutlined />} onClick={load}>
          刷新
        </Button>
        <Dropdown.Button
          icon={<DownloadOutlined />}
          loading={exporting?.startsWith('sent-')}
          onClick={() => handleExport('sent', 'csv')}
          menu={{
            items: [
              { key: 'csv', label: '导出为 CSV', icon: <FileTextOutlined /> },
              { key: 'xlsx', label: '导出为 Excel', icon: <FileExcelOutlined /> },
            ],
            onClick: ({ key }) => handleExport('sent', key as 'csv' | 'xlsx'),
          }}
        >
          导出评论
        </Dropdown.Button>
        <Dropdown.Button
          icon={<DownloadOutlined />}
          loading={exporting?.startsWith('replies-')}
          onClick={() => handleExport('replies', 'csv')}
          menu={{
            items: [
              { key: 'csv', label: '导出为 CSV', icon: <FileTextOutlined /> },
              { key: 'xlsx', label: '导出为 Excel', icon: <FileExcelOutlined /> },
            ],
            onClick: ({ key }) => handleExport('replies', key as 'csv' | 'xlsx'),
          }}
        >
          导出回复
        </Dropdown.Button>
      </Space>
      <List
        loading={loading}
        dataSource={list}
        renderItem={renderItem}
        style={{ background: '#fff', padding: '0 16px', borderRadius: 8 }}
        pagination={{
          current: page,
          pageSize,
          total,
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
          showSizeChanger: true,
          style: { padding: '16px 0', justifyContent: 'flex-end' },
        }}
      />
      <RepliesModal
        open={repliesModal.open}
        sc={repliesModal.sc}
        onClose={() => setRepliesModal({ open: false })}
        onChanged={load}
      />
    </div>
  );
};

export default SentCommentsPanel;
