import { message } from '../utils/antdMessage';
import React, { useEffect, useState, useCallback } from 'react';
import { Card, Table, Tag, Space, Button, Input, Select, DatePicker, Empty, Spin, Tooltip, Form } from 'antd';
import {
  ReloadOutlined, FileTextOutlined, DownloadOutlined,
  CheckCircleOutlined, WarningOutlined, CloseCircleOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons';
import dayjs from 'dayjs';
import { auditLogApi } from '../api/prdGap';

const { Option } = Select;
const { RangePicker } = DatePicker;

// 真实后端 AuditLog 字段（与 api/services/utils/audit_log.py: AuditLog 一致）
interface AuditLogEntry {
  log_id: string;
  action_type: string;
  user_id?: number | null;
  platform?: string;
  target?: string;
  description?: string;
  request_data?: Record<string, unknown>;
  response_data?: Record<string, unknown>;
  ip_address?: string;
  user_agent?: string;
  status: string; // success / failed / partial / needs_review / started
  error_message?: string;
  created_at?: string;
}

interface ActionTypeOption {
  value: string;
  label: string;
}

// 状态 -> 颜色/图标 映射
const statusConfig: Record<string, { color: string; icon: React.ReactNode }> = {
  success: { color: 'green', icon: <CheckCircleOutlined /> },
  partial: { color: 'blue', icon: <InfoCircleOutlined /> },
  started: { color: 'blue', icon: <InfoCircleOutlined /> },
  needs_review: { color: 'orange', icon: <WarningOutlined /> },
  failed: { color: 'red', icon: <CloseCircleOutlined /> },
};

// 平台选项（与后端 PLATFORMS 对齐，部分常用）
const platformOptions = [
  { value: 'douyin', label: '抖音' },
  { value: 'xiaohongshu', label: '小红书' },
  { value: 'weibo', label: '微博' },
  { value: 'zhihu', label: '知乎' },
  { value: 'bilibili', label: '哔哩哔哩' },
  { value: 'baidu', label: '百度' },
  { value: 'toutiao', label: '头条' },
  { value: 'x', label: 'X' },
  { value: 'hackernews', label: 'Hacker News' },
  { value: 'reddit', label: 'Reddit' },
  { value: 'github', label: 'GitHub' },
  { value: 'youtube', label: 'YouTube' },
];

// action_type 中文标签
const actionTypeLabels: Record<string, string> = {
  publish: '发布',
  interaction: '互动',
  config_change: '配置变更',
  account_mgmt: '账号管理',
  login: '登录',
  export: '数据导出',
  other: '其他',
};

const SystemLogs: React.FC = () => {
  const [logs, setLogs] = useState<AuditLogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [actionTypes, setActionTypes] = useState<ActionTypeOption[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  // 筛选条件
  const [filterActionType, setFilterActionType] = useState<string>('');
  const [filterUserId, setFilterUserId] = useState<string>('');
  const [filterPlatform, setFilterPlatform] = useState<string>('');
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);

  // 加载操作类型枚举
  useEffect(() => {
    (async () => {
      try {
        const resp: any = await auditLogApi.actionTypes();
        const items: any[] = resp?.data?.items || [];
        setActionTypes(items.map(it => ({
          value: it.value,
          label: actionTypeLabels[it.value] || it.label || it.value,
        })));
      } catch (e) {
        // 降级使用本地枚举
        setActionTypes(Object.entries(actionTypeLabels).map(([v, l]) => ({ value: v, label: l })));
      }
    })();
  }, []);

  const buildParams = useCallback(() => {
    const params: Record<string, unknown> = {
      limit: pageSize,
      offset: (page - 1) * pageSize,
    };
    if (filterActionType) params.action_type = filterActionType;
    if (filterUserId) {
      const uid = parseInt(filterUserId, 10);
      if (!Number.isNaN(uid)) params.user_id = uid;
    }
    if (filterPlatform) params.platform = filterPlatform;
    if (dateRange && dateRange[0] && dateRange[1]) {
      params.start_date = dateRange[0].format('YYYY-MM-DD');
      params.end_date = dateRange[1].format('YYYY-MM-DD');
    }
    return params;
  }, [filterActionType, filterUserId, filterPlatform, dateRange, page, pageSize]);

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    try {
      const resp: any = await auditLogApi.list(buildParams());
      const data = resp?.data || {};
      const items: AuditLogEntry[] = data.items || [];
      setLogs(items);
      // 后端 total 为本页条数（list_logs 不返回真实 total），用 items 长度+偏移估算
      setTotal(Number(data.total ?? items.length) + Number(data.offset ?? 0));
    } catch (e) {
      console.error('fetch audit logs failed:', e);
      message.error('加载操作日志失败');
      setLogs([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [buildParams]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  const handleSearch = () => {
    setPage(1);
    fetchLogs();
  };

  const handleReset = () => {
    setFilterActionType('');
    setFilterUserId('');
    setFilterPlatform('');
    setDateRange(null);
    setPage(1);
  };

  const handleExportCsv = async () => {
    setExporting(true);
    try {
      const params: Record<string, unknown> = {};
      if (filterActionType) params.action_type = filterActionType;
      if (filterUserId) {
        const uid = parseInt(filterUserId, 10);
        if (!Number.isNaN(uid)) params.user_id = uid;
      }
      if (filterPlatform) params.platform = filterPlatform;
      if (dateRange && dateRange[0] && dateRange[1]) {
        params.start_date = dateRange[0].format('YYYY-MM-DD');
        params.end_date = dateRange[1].format('YYYY-MM-DD');
      }
      const blob: any = await auditLogApi.exportCsv(params);
      // axios responseType=blob 时返回 Blob
      const url = window.URL.createObjectURL(
        blob instanceof Blob ? blob : new Blob([blob as any], { type: 'text/csv' })
      );
      const a = document.createElement('a');
      a.href = url;
      a.download = `audit_logs_${dayjs().format('YYYYMMDD_HHmmss')}.csv`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
      message.success('CSV 导出成功');
    } catch (e) {
      console.error('export csv failed:', e);
      message.error('CSV 导出失败');
    } finally {
      setExporting(false);
    }
  };

  const columns = [
    {
      title: '时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (v: string) => v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-',
      sorter: (a: AuditLogEntry, b: AuditLogEntry) =>
        dayjs(a.created_at || 0).unix() - dayjs(b.created_at || 0).unix(),
    },
    {
      title: '操作类型',
      dataIndex: 'action_type',
      key: 'action_type',
      width: 110,
      render: (v: string) => (
        <Tag color="blue">{actionTypeLabels[v] || v || '-'}</Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (v: string) => {
        const cfg = statusConfig[v] || { color: 'default', icon: <InfoCircleOutlined /> };
        return <Tag color={cfg.color} icon={cfg.icon}>{(v || 'other').toUpperCase()}</Tag>;
      },
    },
    {
      title: '用户ID',
      dataIndex: 'user_id',
      key: 'user_id',
      width: 90,
      render: (v: number | null | undefined) => v ?? '-',
    },
    {
      title: '平台',
      dataIndex: 'platform',
      key: 'platform',
      width: 120,
      render: (v: string) => v ? <Tag>{v}</Tag> : '-',
    },
    {
      title: '操作描述',
      dataIndex: 'description',
      key: 'description',
      render: (v: string, record: AuditLogEntry) => {
        const detail = record.error_message
          ? `错误: ${record.error_message}`
          : JSON.stringify(record.response_data || {});
        return (
          <Tooltip title={detail} placement="topLeft">
            <span style={{ cursor: 'help' }}>{v || '-'}</span>
          </Tooltip>
        );
      },
    },
    {
      title: '目标',
      dataIndex: 'target',
      key: 'target',
      width: 180,
      ellipsis: true,
      render: (v: string) => v || '-',
    },
    {
      title: 'IP',
      dataIndex: 'ip_address',
      key: 'ip_address',
      width: 130,
      render: (v: string) => v || '-',
    },
  ];

  return (
    <div>
      <Card size="small" style={{ marginBottom: 16 }}>
        <Form layout="inline" onFinish={handleSearch}>
          <Form.Item label="操作类型">
            <Select
              placeholder="全部"
              value={filterActionType || undefined}
              onChange={setFilterActionType}
              style={{ width: 140 }}
              allowClear
            >
              {actionTypes.map(at => (
                <Option key={at.value} value={at.value}>{at.label}</Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item label="用户ID">
            <Input
              placeholder="用户ID"
              value={filterUserId}
              onChange={e => setFilterUserId(e.target.value)}
              style={{ width: 120 }}
              allowClear
            />
          </Form.Item>
          <Form.Item label="平台">
            <Select
              placeholder="全部"
              value={filterPlatform || undefined}
              onChange={setFilterPlatform}
              style={{ width: 140 }}
              allowClear
            >
              {platformOptions.map(p => (
                <Option key={p.value} value={p.value}>{p.label}</Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item label="时间范围">
            <RangePicker
              value={dateRange as any}
              onChange={(dates) => setDateRange(dates as any)}
            />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" icon={<ReloadOutlined />}>
                查询
              </Button>
              <Button onClick={handleReset}>重置</Button>
              <Button
                icon={<DownloadOutlined />}
                loading={exporting}
                onClick={handleExportCsv}
              >
                导出 CSV
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Card>

      <Card>
        <Space style={{ marginBottom: 16 }}>
          <Tag icon={<FileTextOutlined />} color="blue">
            共 {total} 条
          </Tag>
        </Space>

        {loading && logs.length === 0 ? (
          <Spin style={{ display: 'flex', justifyContent: 'center', padding: 50 }} />
        ) : logs.length > 0 ? (
          <Table
            columns={columns}
            dataSource={logs}
            rowKey="log_id"
            size="small"
            pagination={{
              current: page,
              pageSize,
              total,
              showSizeChanger: true,
              showQuickJumper: true,
              showTotal: (t) => `共 ${t} 条`,
              onChange: (p, ps) => {
                setPage(p);
                setPageSize(ps);
              },
            }}
          />
        ) : (
          <Empty description="暂无操作日志" />
        )}
      </Card>
    </div>
  );
};

export default SystemLogs;
