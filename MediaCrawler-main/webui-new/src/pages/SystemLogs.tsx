import React, { useEffect, useState } from 'react';
import {
  Card, Table, Tag, Space, Button, Input, Select, DatePicker, message,
  Empty, Spin, Badge, Tooltip,
} from 'antd';
import {
  ReloadOutlined, ClearOutlined, FileTextOutlined,
  CheckCircleOutlined, WarningOutlined, CloseCircleOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';

const { Option } = Select;
const { RangePicker } = DatePicker;

interface LogEntry {
  id: string;
  timestamp: string;
  level: 'info' | 'success' | 'warning' | 'error';
  module: string;
  message: string;
  detail?: string;
}

const mockLogs: LogEntry[] = [
  { id: '1', timestamp: new Date(Date.now() - 1000 * 60).toISOString(), level: 'info', module: 'crawler', message: '开始执行采集任务 #task_001', detail: '平台: xhs, 关键词: AI工具' },
  { id: '2', timestamp: new Date(Date.now() - 1000 * 120).toISOString(), level: 'success', module: 'crawler', message: '采集任务完成', detail: '共获取 156 条数据，识别 23 条线索' },
  { id: '3', timestamp: new Date(Date.now() - 1000 * 300).toISOString(), level: 'warning', module: 'scorer', message: '评分模型置信度较低', detail: '部分文本内容过短，评分可能不准确' },
  { id: '4', timestamp: new Date(Date.now() - 1000 * 600).toISOString(), level: 'error', module: 'crawler', message: '采集请求失败', detail: '请求超时，请检查网络连接' },
  { id: '5', timestamp: new Date(Date.now() - 1000 * 900).toISOString(), level: 'info', module: 'system', message: '系统启动', detail: '获客系统已启动' },
  { id: '6', timestamp: new Date(Date.now() - 1000 * 1200).toISOString(), level: 'success', module: 'lead', message: '新线索入库', detail: '用户 @ai_lover 被识别为高意向线索' },
  { id: '7', timestamp: new Date(Date.now() - 1000 * 1800).toISOString(), level: 'info', module: 'task', message: '定时任务触发', detail: '执行每日数据汇总' },
  { id: '8', timestamp: new Date(Date.now() - 1000 * 3600).toISOString(), level: 'warning', module: 'system', message: '内存使用率较高', detail: '当前内存使用率 82%，建议清理缓存' },
];

const levelConfig: Record<string, { color: string; icon: React.ReactNode }> = {
  info: { color: 'blue', icon: <InfoCircleOutlined /> },
  success: { color: 'green', icon: <CheckCircleOutlined /> },
  warning: { color: 'orange', icon: <WarningOutlined /> },
  error: { color: 'red', icon: <CloseCircleOutlined /> },
};

const moduleOptions = [
  { value: 'crawler', label: '采集模块' },
  { value: 'scorer', label: '评分模块' },
  { value: 'lead', label: '线索模块' },
  { value: 'task', label: '任务调度' },
  { value: 'system', label: '系统' },
];

const SystemLogs: React.FC = () => {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [filterLevel, setFilterLevel] = useState<string>('');
  const [filterModule, setFilterModule] = useState<string>('');
  const [searchText, setSearchText] = useState('');
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);

  useEffect(() => {
    fetchLogs();
    const interval = setInterval(fetchLogs, 10000);
    return () => clearInterval(interval);
  }, []);

  const fetchLogs = async () => {
    setLoading(true);
    try {
      await new Promise(resolve => setTimeout(resolve, 500));
      setLogs(mockLogs);
    } finally {
      setLoading(false);
    }
  };

  const filteredLogs = logs.filter(log => {
    if (filterLevel && log.level !== filterLevel) return false;
    if (filterModule && log.module !== filterModule) return false;
    if (searchText && !log.message.toLowerCase().includes(searchText.toLowerCase())) return false;
    if (dateRange && dateRange[0] && dateRange[1]) {
      const logDate = dayjs(log.timestamp);
      if (logDate.isBefore(dateRange[0]) || logDate.isAfter(dateRange[1])) return false;
    }
    return true;
  });

  const handleClear = () => {
    setLogs([]);
    message.success('日志已清空');
  };

  const columns = [
    {
      title: '时间',
      dataIndex: 'timestamp',
      key: 'timestamp',
      width: 180,
      render: (v: string) => dayjs(v).format('YYYY-MM-DD HH:mm:ss'),
      sorter: (a: LogEntry, b: LogEntry) => dayjs(a.timestamp).unix() - dayjs(b.timestamp).unix(),
    },
    {
      title: '级别',
      dataIndex: 'level',
      key: 'level',
      width: 100,
      render: (v: string) => {
        const config = levelConfig[v];
        return <Tag color={config?.color} icon={config?.icon}>{v.toUpperCase()}</Tag>;
      },
    },
    {
      title: '模块',
      dataIndex: 'module',
      key: 'module',
      width: 120,
      render: (v: string) => {
        const moduleLabel = moduleOptions.find(m => m.value === v)?.label || v;
        return <Tag>{moduleLabel}</Tag>;
      },
    },
    {
      title: '消息',
      dataIndex: 'message',
      key: 'message',
      render: (v: string, record: LogEntry) => (
        <Tooltip title={record.detail} placement="topLeft">
          <span style={{ cursor: 'help' }}>{v}</span>
        </Tooltip>
      ),
    },
  ];

  const stats = {
    total: filteredLogs.length,
    error: filteredLogs.filter(l => l.level === 'error').length,
    warning: filteredLogs.filter(l => l.level === 'warning').length,
    info: filteredLogs.filter(l => l.level === 'info').length,
  };

  return (
    <div>
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Input
            placeholder="搜索日志内容"
            value={searchText}
            onChange={e => setSearchText(e.target.value)}
            style={{ width: 200 }}
            allowClear
          />
          <Select
            placeholder="日志级别"
            value={filterLevel || undefined}
            onChange={setFilterLevel}
            style={{ width: 120 }}
            allowClear
          >
            <Option value="info">INFO</Option>
            <Option value="success">SUCCESS</Option>
            <Option value="warning">WARNING</Option>
            <Option value="error">ERROR</Option>
          </Select>
          <Select
            placeholder="模块"
            value={filterModule || undefined}
            onChange={setFilterModule}
            style={{ width: 120 }}
            allowClear
          >
            {moduleOptions.map(m => (
              <Option key={m.value} value={m.value}>{m.label}</Option>
            ))}
          </Select>
          <RangePicker
            showTime
            value={dateRange}
            onChange={setDateRange}
          />
          <Button icon={<ReloadOutlined />} onClick={fetchLogs}>刷新</Button>
          <Button icon={<ClearOutlined />} danger onClick={handleClear}>清空</Button>
        </Space>
      </Card>

      <Card>
        <Space style={{ marginBottom: 16 }}>
          <Badge count={stats.total} showZero color="#1890ff">
            <Tag icon={<FileTextOutlined />}>全部</Tag>
          </Badge>
          <Badge count={stats.error} showZero color="#f5222d">
            <Tag icon={<CloseCircleOutlined />} color="error">错误</Tag>
          </Badge>
          <Badge count={stats.warning} showZero color="#faad14">
            <Tag icon={<WarningOutlined />} color="warning">警告</Tag>
          </Badge>
          <Badge count={stats.info} showZero color="#1890ff">
            <Tag icon={<InfoCircleOutlined />} color="processing">信息</Tag>
          </Badge>
        </Space>

        {loading && logs.length === 0 ? (
          <Spin style={{ display: 'flex', justifyContent: 'center', padding: 50 }} />
        ) : filteredLogs.length > 0 ? (
          <Table
            columns={columns}
            dataSource={filteredLogs}
            rowKey="id"
            size="small"
            pagination={{ pageSize: 20, showSizeChanger: true }}
          />
        ) : (
          <Empty description="暂无日志" />
        )}
      </Card>
    </div>
  );
};

export default SystemLogs;
