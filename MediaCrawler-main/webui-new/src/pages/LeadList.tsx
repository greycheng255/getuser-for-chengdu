import React, { useEffect, useState, useCallback } from 'react';
import {
  Card, Tag, Button, Space, Modal, Input, Select, message, Tabs, Tooltip,
  Avatar, Table, Popconfirm, Progress, DatePicker, InputNumber, Upload,
} from 'antd';
import {
  ReloadOutlined, DownloadOutlined, EyeOutlined, DeleteOutlined, EnvironmentOutlined, UserOutlined,
  UploadOutlined, CopyOutlined, LinkOutlined,
} from '@ant-design/icons';
import type { Lead, LeadStats } from '../types';
import { PLATFORM_MAP, INTENT_MAP, STATUS_MAP } from '../types';
import { getLeads, getLeadStats, updateLeadStatus, deleteLead, batchDeleteLeads, getLeadDetail, exportLeads, getLeadRegions } from '../api/leads';
import { getTasks } from '../api/tasks';
import { authStorage } from '../api/auth';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';

dayjs.extend(relativeTime);

const { Option } = Select;

const LeadList: React.FC = () => {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [stats, setStats] = useState<LeadStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [detailModal, setDetailModal] = useState<{ visible: boolean; lead: Lead | null }>({ visible: false, lead: null });
  const [detailLoading, setDetailLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('all');
  const [searchText, setSearchText] = useState('');
  const [filterPlatform, setFilterPlatform] = useState<string>('');
  // 请求竞态保护:只接受最新一次 fetchData 的结果(避免快速切换筛选时旧响应覆盖新响应)
  const fetchSeqRef = React.useRef(0);
  const [filterTaskId, setFilterTaskId] = useState<string>('');
  // 意向等级筛选(high/medium/low/空)— 后端按 lead_score 分档,跨任务统一筛选
  const [filterLevel, setFilterLevel] = useState<string>('');
  // 地域筛选(模糊匹配,如"四川"/"巴中")
  const [filterIpLocation, setFilterIpLocation] = useState<string>('');
  // 时间范围筛选(对应后端 start_ts/end_ts,秒级时间戳)
  const [filterDateRange, setFilterDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null);
  // 分数区间筛选(对应后端 min_score/max_score)
  const [filterMinScore, setFilterMinScore] = useState<number | null>(null);
  const [filterMaxScore, setFilterMaxScore] = useState<number | null>(null);
  // 意向类型筛选(对应后端 intent_type)
  const [filterIntentType, setFilterIntentType] = useState<string>('');
  // 视图模式:列表视图(list) / 看板视图(board,支持拖拽变更状态)
  const [viewMode, setViewMode] = useState<'list' | 'board'>('list');
  // 拖拽中的线索ID(用于高亮目标列)
  const [draggingLeadId, setDraggingLeadId] = useState<number | null>(null);
  // 地域快捷标签(只显示前20个,其余折叠)
  const [showAllRegions, setShowAllRegions] = useState(false);
  const [regions, setRegions] = useState<Array<{ ip_location: string; count: number }>>([]);
  const displayedRegions = showAllRegions ? regions : regions.slice(0, 20);
  const hasMoreRegions = regions.length > 20;
  const [tasks, setTasks] = useState<any[]>([]);
  const [pagination, setPagination] = useState({ page: 1, pageSize: 50, total: 0 });
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);

  // 打开详情:调用详情API获取来源视频信息
  const openDetail = useCallback(async (lead: Lead) => {
    setDetailModal({ visible: true, lead });
    setDetailLoading(true);
    try {
      const full = await getLeadDetail(lead.id);
      setDetailModal({ visible: true, lead: full });
    } catch (err) {
      // 失败时保留基本信息
    } finally {
      setDetailLoading(false);
    }
  }, []);

  // 新增筛选维度(意向类型/分数区间/时间范围)的公共参数对象,供列表/统计/导出复用
  const extraFilterParams = React.useMemo(() => {
    const p: any = {};
    if (filterIntentType) p.intent_type = filterIntentType;
    if (filterMinScore != null) p.min_score = filterMinScore;
    if (filterMaxScore != null) p.max_score = filterMaxScore;
    if (filterDateRange && filterDateRange[0] && filterDateRange[1]) {
      p.start_ts = filterDateRange[0].startOf('day').unix();
      p.end_ts = filterDateRange[1].endOf('day').unix();
    }
    return p;
  }, [filterIntentType, filterMinScore, filterMaxScore, filterDateRange]);

  const fetchData = useCallback(async (page = 1) => {
    // 自增序列号,只接受最新一次请求的结果(防止竞态:旧响应覆盖新响应)
    const seq = ++fetchSeqRef.current;
    setLoading(true);
    try {
      // 看板视图需展示所有状态的线索,拉取较大页量;列表视图保持 50 条/页
      const pageSize = viewMode === 'board' ? 200 : 50;
      const params: any = { page, page_size: pageSize, ...extraFilterParams };
      if (filterTaskId) params.task_id = filterTaskId;
      if (filterPlatform) params.platform = filterPlatform;
      if (activeTab !== 'all') params.status = activeTab;
      if (searchText) params.keyword = searchText;
      if (filterLevel) params.level = filterLevel;
      if (filterIpLocation.trim()) params.ip_location = filterIpLocation.trim();
      const res = await getLeads(params);
      // 如果这不是最新请求,丢弃结果(避免旧响应覆盖新响应)
      if (seq !== fetchSeqRef.current) return;
      setLeads(res.items);
      setPagination(prev => ({ ...prev, page, total: res.total }));
    } catch (err: any) {
      if (seq !== fetchSeqRef.current) return;
      message.error(err?.message || '获取线索列表失败');
    } finally {
      if (seq === fetchSeqRef.current) setLoading(false);
    }
  }, [filterTaskId, filterPlatform, activeTab, searchText, filterLevel, filterIpLocation, extraFilterParams, viewMode]);

  const fetchStats = useCallback(async () => {
    try {
      const params: any = { ...extraFilterParams };
      if (filterTaskId) params.task_id = filterTaskId;
      if (searchText) params.keyword = searchText;
      if (filterLevel) params.level = filterLevel;
      if (filterIpLocation.trim()) params.ip_location = filterIpLocation.trim();
      if (filterPlatform) params.platform = filterPlatform;
      const res = await getLeadStats(params);
      setStats(res);
    } catch (error) {
      console.error('Failed to fetch stats:', error);
    }
  }, [filterTaskId, searchText, filterLevel, filterIpLocation, filterPlatform, extraFilterParams]);

  // 看板视图:把当前页线索按 status 分组(用于 Kanban 拖拽)
  const boardData = React.useMemo(() => {
    const groups: Record<string, Lead[]> = {};
    Object.keys(STATUS_MAP).forEach(k => { groups[k] = []; });
    leads.forEach(l => {
      if (groups[l.status]) groups[l.status].push(l);
    });
    return groups;
  }, [leads]);

  // 拉取地域分布 Top 10(用于快捷标签)
  // 注意:level 筛选需同步传入,否则地域标签数量与列表不一致
  const fetchRegions = useCallback(async () => {
    try {
      const res = await getLeadRegions({ task_id: filterTaskId || undefined, level: filterLevel || undefined, limit: 50 });
      setRegions(res || []);
    } catch (e) {
      // 静默失败
    }
  }, [filterTaskId, filterLevel]);

  // 导出当前筛选条件下的全量线索为 Excel(含用户信息/评论/源视频/意向/IP属地)
  const handleExportExcel = async () => {
    if (pagination.total === 0) {
      message.warning('当前筛选下没有可导出的线索');
      return;
    }
    setExporting(true);
    try {
      const params: any = { ...extraFilterParams };
      if (filterTaskId) params.task_id = filterTaskId;
      if (filterPlatform) params.platform = filterPlatform;
      if (activeTab !== 'all') params.status = activeTab;
      if (searchText) params.keyword = searchText;
      if (filterLevel) params.level = filterLevel;
      if (filterIpLocation.trim()) params.ip_location = filterIpLocation.trim();
      const blob = await exportLeads(params);
      // 触发浏览器下载
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const taskName = tasks.find(t => t.id === filterTaskId)?.name || '全部任务';
      const levelText = filterLevel === 'high' ? '高意向' : filterLevel === 'medium' ? '中意向' : filterLevel === 'low' ? '低意向' : '全部意向';
      const regionText = filterIpLocation.trim() || '全部地域';
      a.download = `线索导出_${taskName}_${levelText}_${regionText}_${pagination.total}条.xlsx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
      message.success(`已导出 ${pagination.total} 条线索`);
    } catch (error: any) {
      console.error('Failed to export leads:', error);
      message.error(error?.message || '导出失败');
    } finally {
      setExporting(false);
    }
  };

  const fetchTasks = useCallback(async () => {
    try {
      const res = await getTasks();
      setTasks(res || []);
    } catch (e) {
      // ignore
    }
  }, []);

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  useEffect(() => {
    fetchData(1);
    fetchStats();
  }, [fetchData, fetchStats]);

  // 任务切换时重新拉地域分布
  useEffect(() => {
    fetchRegions();
  }, [fetchRegions]);

  // 订阅新线索 WebSocket 推送:采集写入线索后自动刷新列表
  const wsRef = React.useRef<WebSocket | null>(null);
  useEffect(() => {
    const token = authStorage.getToken();
    if (!token) return;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/ws/leads?token=${encodeURIComponent(token)}`;
    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let closed = false;

    const connect = () => {
      try {
        ws = new WebSocket(wsUrl);
        wsRef.current = ws;
        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data?.type === 'new_lead') {
              message.success(`收到 ${data.count} 条新线索(高${data.high_count}/中${data.medium_count}/低${data.low_count})`, 3);
              fetchData(pagination.page);
              fetchStats();
            }
          } catch {
            // ignore non-JSON (ping/pong)
          }
        };
        ws.onclose = () => {
          if (!closed) {
            // 断线重连(5 秒后)
            reconnectTimer = setTimeout(connect, 5000);
          }
        };
      } catch (e) {
        // 静默失败,不影响主流程
      }
    };
    connect();

    return () => {
      closed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (ws) { ws.onclose = null; ws.close(); }
      wsRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleStatusChange = async (leadId: number, status: string) => {
    try {
      await updateLeadStatus(leadId, status);
      message.success('状态更新成功');
      fetchData(pagination.page);
      fetchStats();
    } catch (error) {
      message.error('状态更新失败');
    }
  };

  const handleDeleteLead = async (leadId: number) => {
    try {
      await deleteLead(leadId);
      message.success('删除成功');
      fetchData(pagination.page);
      fetchStats();
    } catch (error) {
      message.error('删除失败');
    }
  };

  // 批量导入线索(CSV/Excel)- 上传到 /api/leads/import-file
  const handleImportFile = async (file: File) => {
    if (!filterTaskId) {
      message.warning('请先选择目标任务');
      return;
    }
    setImporting(true);
    try {
      const token = authStorage.getToken();
      const formData = new FormData();
      formData.append('file', file);
      const params = new URLSearchParams({ task_id: filterTaskId, platform: 'manual' });
      const resp = await fetch(`/api/leads/import-file?${params.toString()}`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      });
      const data = await resp.json();
      if (!resp.ok || !data?.success) {
        throw new Error(data?.detail || `HTTP ${resp.status}`);
      }
      message.success(`导入成功:新增 ${data.imported} 条,跳过 ${data.skipped} 行(共 ${data.total_rows} 行)`);
      fetchData(1);
      fetchStats();
    } catch (e: any) {
      message.error(e?.message || '导入失败');
    } finally {
      setImporting(false);
    }
  };

  const handleBatchDelete = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先选择要删除的线索');
      return;
    }
    try {
      await batchDeleteLeads(selectedRowKeys.map(k => Number(k)));
      message.success(`成功删除 ${selectedRowKeys.length} 条线索`);
      setSelectedRowKeys([]);
      fetchData(pagination.page);
      fetchStats();
    } catch (error) {
      message.error('批量删除失败');
    }
  };

  const tabCounts = {
    all: stats?.total_leads || 0,
    new: stats?.new_leads || 0,
    pending: stats?.pending_leads || 0,
    contacted: stats?.contacted_leads || 0,
    qualified: stats?.qualified_leads || 0,
    converted: stats?.converted_leads || 0,
    failed: stats?.failed_leads || 0,
    ignored: stats?.ignored_leads || 0,
  };

  const getScoreColor = (score: number) => {
    if (score >= 80) return '#f5222d';
    if (score >= 60) return '#fa8c16';
    if (score >= 40) return '#1890ff';
    return '#52c41a';
  };

  const getStatusTag = (status: string) => {
    const info = STATUS_MAP[status];
    if (!info) return <Tag>{status}</Tag>;
    return <Tag color={info.color}>{info.text}</Tag>;
  };

  const columns = [
    {
      title: '用户',
      dataIndex: 'nickname',
      key: 'nickname',
      width: 160,
      render: (text: string, record: Lead) => (
        <Space>
          <Avatar size="small" icon={<UserOutlined />} src={record.avatar} />
          <span style={{ fontWeight: 500 }}>{text}</span>
        </Space>
      ),
    },
    {
      title: '评分',
      dataIndex: 'lead_score',
      key: 'lead_score',
      width: 100,
      sorter: (a: Lead, b: Lead) => a.lead_score - b.lead_score,
      render: (score: number) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Progress type="circle" percent={score} size={28} strokeColor={getScoreColor(score)} format={() => ''} />
          <span style={{ color: getScoreColor(score), fontWeight: 600 }}>{score}</span>
        </div>
      ),
    },
    {
      title: '意向',
      dataIndex: 'intent_type',
      key: 'intent_type',
      width: 100,
      filters: Object.entries(INTENT_MAP).map(([k, v]) => ({ text: v, value: k })),
      onFilter: (value: any, record: Lead) => record.intent_type === value,
      render: (type: string) => <Tag color="blue">{INTENT_MAP[type] || type}</Tag>,
    },
    {
      title: '内容',
      dataIndex: 'content',
      key: 'content',
      ellipsis: true,
      render: (text: string) => (
        <Tooltip title={text}>
          <span style={{ color: '#333' }}>{text?.slice(0, 60)}{text?.length > 60 ? '...' : ''}</span>
        </Tooltip>
      ),
    },
    {
      title: '关键词',
      dataIndex: 'matched_keywords',
      key: 'matched_keywords',
      width: 180,
      render: (text: string) => (
        <Space size={4} wrap>
          {text?.split(',').slice(0, 3).map((kw: string, i: number) => (
            <Tag key={i} style={{ fontSize: 11 }}>{kw.trim()}</Tag>
          ))}
          {text?.split(',').length > 3 && <Tag style={{ fontSize: 11 }}>+{text.split(',').length - 3}</Tag>}
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      filters: Object.entries(STATUS_MAP).map(([k, v]) => ({ text: v.text, value: k })),
      onFilter: (value: any, record: Lead) => record.status === value,
      render: (status: string) => getStatusTag(status),
    },
    {
      title: '平台',
      dataIndex: 'platform',
      key: 'platform',
      width: 80,
      render: (platform: string) => <Tag>{PLATFORM_MAP[platform] || platform}</Tag>,
    },
    {
      title: 'IP属地',
      dataIndex: 'ip_location',
      key: 'ip_location',
      width: 100,
      render: (loc: string) => loc ? (
        <Tag color="geekblue" icon={<EnvironmentOutlined />}>{loc}</Tag>
      ) : <span style={{ color: '#ccc' }}>-</span>,
    },
    {
      title: '源视频',
      dataIndex: 'source_video_title',
      key: 'source_video_title',
      width: 120,
      render: (title: string, record: Lead) => {
        if (!title && !record.source_video_url) return <span style={{ color: '#ccc' }}>-</span>;
        return (
          <Tooltip title={title || '点击查看原视频'}>
            <Button
              size="small"
              type="link"
              style={{ padding: 0, fontSize: 12 }}
              href={record.source_video_url || '#'}
              target="_blank"
            >
              {title ? (title.length > 18 ? title.slice(0, 18) + '...' : title) : '查看原视频 ↗'}
            </Button>
          </Tooltip>
        );
      },
    },
    {
      title: '时间',
      key: 'time',
      width: 130,
      sorter: (a: Lead, b: Lead) => (a.create_time || a.add_ts/1000) - (b.create_time || b.add_ts/1000),
      render: (_: any, record: Lead) => {
        const ts = record.create_time ? record.create_time * 1000 : record.add_ts;
        return <span style={{ fontSize: 12, color: '#999' }}>{dayjs(ts).fromNow()}</span>;
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      render: (_: any, record: Lead) => (
        <Space size={4}>
          <Button size="small" type="link" icon={<EyeOutlined />} onClick={() => openDetail(record)}>详情</Button>
          {record.status === 'new' && (
            <Button size="small" type="primary" onClick={() => handleStatusChange(record.id, 'contacted')}>联系</Button>
          )}
          {record.status === 'failed' && (
            <Button size="small" type="primary" danger onClick={() => handleStatusChange(record.id, 'new')}>重试</Button>
          )}
          {record.status === 'pending' && (
            <Button size="small" onClick={() => handleStatusChange(record.id, 'ignored')}>忽略</Button>
          )}
          <Popconfirm title="确定删除该线索？" onConfirm={() => handleDeleteLead(record.id)} okText="删除" cancelText="取消">
            <Button size="small" type="text" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      {/* 统计概览 - 紧凑横向排列 */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <Card size="small" style={{ minWidth: 110, flex: '0 0 auto' }}>
          <div style={{ fontSize: 12, color: '#999' }}>新线索</div>
          <div style={{ fontSize: 20, fontWeight: 700, color: '#52c41a' }}>{stats?.new_leads || 0}</div>
        </Card>
        <Card size="small" style={{ minWidth: 110, flex: '0 0 auto' }}>
          <div style={{ fontSize: 12, color: '#999' }}>触达中</div>
          <div style={{ fontSize: 20, fontWeight: 700, color: '#1890ff' }}>{stats?.pending_leads || 0}</div>
        </Card>
        <Card size="small" style={{ minWidth: 110, flex: '0 0 auto' }}>
          <div style={{ fontSize: 12, color: '#999' }}>已联系</div>
          <div style={{ fontSize: 20, fontWeight: 700, color: '#722ed1' }}>{stats?.contacted_leads || 0}</div>
        </Card>
        <Card size="small" style={{ minWidth: 110, flex: '0 0 auto' }}>
          <div style={{ fontSize: 12, color: '#999' }}>发送失败</div>
          <div style={{ fontSize: 20, fontWeight: 700, color: '#ff4d4f' }}>{stats?.failed_leads || 0}</div>
        </Card>
        <Card size="small" style={{ minWidth: 110, flex: '0 0 auto' }}>
          <div style={{ fontSize: 12, color: '#999' }}>已转化</div>
          <div style={{ fontSize: 20, fontWeight: 700, color: '#fa8c16' }}>{stats?.converted_leads || 0}</div>
        </Card>
        <Card size="small" style={{ minWidth: 130, flex: '1 1 auto' }}>
          <div style={{ fontSize: 12, color: '#999' }}>总线索 / 均分</div>
          <div style={{ fontSize: 20, fontWeight: 700 }}>
            {stats?.total_leads || 0}
            <span style={{ fontSize: 13, color: '#999', marginLeft: 8 }}>{stats?.avg_lead_score?.toFixed(0) || 0}分</span>
          </div>
        </Card>
      </div>

      {/* 筛选工具栏 */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <Input
          placeholder="搜索内容..."
          value={searchText}
          onChange={e => setSearchText(e.target.value)}
          style={{ width: 200 }}
          allowClear
          onPressEnter={() => fetchData(1)}
          prefix={<span style={{ color: '#999' }}>🔍</span>}
        />
        <Select
          placeholder="选择任务"
          allowClear
          style={{ width: 200 }}
          value={filterTaskId || undefined}
          onChange={val => { setFilterTaskId(val || ''); setFilterIpLocation(''); }}
        >
          {tasks.map(t => (
            <Option key={t.id} value={t.id}>{t.name}</Option>
          ))}
        </Select>
        <Select
          placeholder="意向等级"
          allowClear
          style={{ width: 130 }}
          value={filterLevel || undefined}
          onChange={val => setFilterLevel(val || '')}
        >
          <Option value="high">高意向 (≥50)</Option>
          <Option value="medium">中意向 (25-49)</Option>
          <Option value="low">低意向 (&lt;25)</Option>
        </Select>
        <Select
          placeholder={filterTaskId ? "选择地域" : "请先选任务"}
          allowClear
          showSearch
          style={{ width: 150 }}
          value={filterIpLocation || undefined}
          onChange={val => setFilterIpLocation(val || '')}
          disabled={!filterTaskId}
          filterOption={(input, option) =>
            (option?.children as unknown as string)?.toLowerCase().includes(input.toLowerCase())
          }
        >
          {regions.map(r => (
            <Option key={r.ip_location} value={r.ip_location}>{r.ip_location} ({r.count})</Option>
          ))}
        </Select>
        <Select
          placeholder="平台"
          allowClear
          style={{ width: 110 }}
          value={filterPlatform || undefined}
          onChange={setFilterPlatform}
        >
          {Object.entries(PLATFORM_MAP).map(([key, label]) => (
            <Option key={key} value={key}>{label}</Option>
          ))}
        </Select>
        <Select
          placeholder="意向类型"
          allowClear
          style={{ width: 130 }}
          value={filterIntentType || undefined}
          onChange={val => setFilterIntentType(val || '')}
        >
          {Object.entries(INTENT_MAP).map(([key, label]) => (
            <Option key={key} value={key}>{label}</Option>
          ))}
        </Select>
        <Space.Compact style={{ width: 180 }}>
          <InputNumber
            placeholder="最低分"
            min={0}
            max={100}
            value={filterMinScore ?? undefined}
            onChange={v => setFilterMinScore(v ?? null)}
            style={{ width: '50%' }}
          />
          <InputNumber
            placeholder="最高分"
            min={0}
            max={100}
            value={filterMaxScore ?? undefined}
            onChange={v => setFilterMaxScore(v ?? null)}
            style={{ width: '50%' }}
          />
        </Space.Compact>
        <DatePicker.RangePicker
          value={filterDateRange as any}
          onChange={dates => setFilterDateRange(dates as [dayjs.Dayjs | null, dayjs.Dayjs | null] | null)}
          style={{ width: 240 }}
          placeholder={['开始日期', '结束日期']}
        />
        <Button icon={<ReloadOutlined />} onClick={() => fetchData(pagination.page)}>刷新</Button>
        <Button type="primary" ghost icon={<DownloadOutlined />} loading={exporting} onClick={handleExportExcel}>
          导出 ({pagination.total})
        </Button>
        <Upload
          accept=".csv,.xlsx,.xls"
          showUploadList={false}
          beforeUpload={(file) => {
            // 校验任务已选
            if (!filterTaskId) {
              message.warning('请先选择目标任务,导入的线索将归属该任务');
              return Upload.LIST_IGNORE;
            }
            handleImportFile(file);
            return false; // 阻止默认上传,改用自定义请求
          }}
        >
          <Button icon={<UploadOutlined />} loading={importing}>导入</Button>
        </Upload>
        {selectedRowKeys.length > 0 && (
          <Popconfirm title={`删除 ${selectedRowKeys.length} 条？`} onConfirm={handleBatchDelete}>
            <Button danger icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        )}
      </div>

      {/* 热门地域标签 - 折叠显示 */}
      {regions.length > 0 && (
        <div style={{ marginBottom: 12, padding: '8px 12px', background: '#fafafa', borderRadius: 6 }}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ fontSize: 12, color: '#999', marginRight: 4 }}>📍 热门地域:</span>
            {displayedRegions.map(r => (
              <Tag
                key={r.ip_location}
                color={filterIpLocation === r.ip_location ? 'red' : 'geekblue'}
                style={{ cursor: 'pointer', margin: 2 }}
                onClick={() => setFilterIpLocation(filterIpLocation === r.ip_location ? '' : r.ip_location)}
              >
                {r.ip_location} ({r.count.toLocaleString()})
              </Tag>
            ))}
            {hasMoreRegions && (
              <Button size="small" type="link" onClick={() => setShowAllRegions(!showAllRegions)}>
                {showAllRegions ? '收起' : `展开更多 (${regions.length - 20}+)`}
              </Button>
            )}
            {filterIpLocation && (
              <Button size="small" type="link" onClick={() => setFilterIpLocation('')}>清除</Button>
            )}
          </div>
        </div>
      )}

      {/* 视图切换 + 状态Tab(看板模式下隐藏状态Tab,看板本身按状态分列) */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        {viewMode === 'list' ? (
          <Tabs
            activeKey={activeTab}
            onChange={setActiveTab}
            size="small"
            style={{ marginBottom: 0 }}
            items={[
              { key: 'all', label: `全部 (${tabCounts.all.toLocaleString()})` },
              { key: 'new', label: `新线索 (${tabCounts.new.toLocaleString()})` },
              { key: 'pending', label: `触达中 (${tabCounts.pending.toLocaleString()})` },
              { key: 'contacted', label: `已联系 (${tabCounts.contacted.toLocaleString()})` },
              { key: 'qualified', label: `已确认 (${tabCounts.qualified.toLocaleString()})` },
              { key: 'converted', label: `已转化 (${tabCounts.converted.toLocaleString()})` },
              { key: 'failed', label: `发送失败 (${tabCounts.failed.toLocaleString()})` },
              { key: 'ignored', label: `已忽略 (${tabCounts.ignored.toLocaleString()})` },
            ]}
          />
        ) : <span style={{ color: '#666', fontSize: 13 }}>看板视图:拖拽卡片到其他列即可变更状态(仅展示最新 {leads.length} 条)</span>}
        <Space>
          <Button.Group size="small">
            <Button type={viewMode === 'list' ? 'primary' : 'default'} onClick={() => setViewMode('list')}>列表</Button>
            <Button type={viewMode === 'board' ? 'primary' : 'default'} onClick={() => { setViewMode('board'); setActiveTab('all'); }}>看板</Button>
          </Button.Group>
        </Space>
      </div>

      {/* 看板视图:Kanban 布局,HTML5 拖拽变更状态 */}
      {viewMode === 'board' ? (
        <div style={{ display: 'flex', gap: 8, overflowX: 'auto', paddingBottom: 8, minHeight: 400 }}>
          {Object.entries(STATUS_MAP).map(([statusKey, { text, color }]) => (
            <div
              key={statusKey}
              onDragOver={(e) => { e.preventDefault(); }}
              onDrop={(e) => {
                e.preventDefault();
                const leadId = Number(e.dataTransfer.getData('leadId'));
                setDraggingLeadId(null);
                if (leadId && !boardData[statusKey]?.some(l => l.id === leadId)) {
                  handleStatusChange(leadId, statusKey);
                }
              }}
              onDragEnter={() => setDraggingLeadId(prev => prev)}
              style={{
                flex: '0 0 280px',
                background: '#fafafa',
                borderRadius: 6,
                padding: 8,
                border: '1px solid #f0f0f0',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, paddingBottom: 6, borderBottom: `2px solid ${color}` }}>
                <span style={{ fontWeight: 600, fontSize: 13 }}>{text}</span>
                <Tag color={color}>{boardData[statusKey]?.length || 0}</Tag>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minHeight: 100 }}>
                {boardData[statusKey]?.map(lead => (
                  <div
                    key={lead.id}
                    draggable
                    onDragStart={(e) => {
                      e.dataTransfer.setData('leadId', String(lead.id));
                      setDraggingLeadId(lead.id);
                    }}
                    onDragEnd={() => setDraggingLeadId(null)}
                    onDoubleClick={() => openDetail(lead)}
                    style={{
                      background: '#fff',
                      border: '1px solid #e8e8e8',
                      borderRadius: 4,
                      padding: 8,
                      cursor: 'move',
                      opacity: draggingLeadId === lead.id ? 0.5 : 1,
                      boxShadow: '0 1px 2px rgba(0,0,0,0.04)',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                      <span style={{ fontWeight: 600, fontSize: 13 }}>
                        {lead.nickname || lead.user_id?.slice(-6) || '匿名'}
                      </span>
                      <Tag color={lead.lead_score >= 50 ? 'red' : lead.lead_score >= 25 ? 'orange' : 'default'}>
                        {lead.lead_score}
                      </Tag>
                    </div>
                    <div style={{ fontSize: 12, color: '#666', lineHeight: 1.4, maxHeight: 40, overflow: 'hidden' }}>
                      {lead.content?.slice(0, 60)}
                    </div>
                    <div style={{ marginTop: 4 }}>
                      {lead.intent_type && <Tag style={{ fontSize: 11 }}>{INTENT_MAP[lead.intent_type] || lead.intent_type}</Tag>}
                      {lead.platform && <Tag style={{ fontSize: 11 }}>{PLATFORM_MAP[lead.platform] || lead.platform}</Tag>}
                    </div>
                  </div>
                ))}
                {boardData[statusKey]?.length === 0 && (
                  <div style={{ textAlign: 'center', color: '#bbb', fontSize: 12, padding: '20px 0' }}>拖拽至此</div>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <>
      {/* 线索表格(antd 6 虚拟滚动,大数据量不卡顿) */}
      <Table
        dataSource={leads}
        columns={columns}
        rowKey="id"
        loading={loading}
        size="small"
        virtual
        scroll={{ x: 1400, y: 600 }}
        rowSelection={{
          selectedRowKeys,
          onChange: setSelectedRowKeys,
        }}
        pagination={{
          current: pagination.page,
          pageSize: pagination.pageSize,
          total: pagination.total,
          showSizeChanger: false,
          showTotal: (total) => `共 ${total} 条`,
          onChange: (page) => fetchData(page),
        }}
        onRow={(record) => ({
          onDoubleClick: () => openDetail(record),
        })}
      />
        </>
      )}

      {/* 线索详情侧边弹窗 */}
      <Modal
        title="线索详情"
        open={detailModal.visible}
        onCancel={() => setDetailModal({ visible: false, lead: null })}
        footer={null}
        width={520}
      >
        {detailModal.lead && (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
              <Avatar size={48} icon={<UserOutlined />} src={detailModal.lead.avatar} />
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 16, fontWeight: 600 }}>{detailModal.lead.nickname}</div>
                <div style={{ fontSize: 13, color: '#999' }}>
                  {PLATFORM_MAP[detailModal.lead.platform]} · {detailModal.lead.ip_location || '未知地区'}
                </div>
              </div>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 24, fontWeight: 700, color: getScoreColor(detailModal.lead.lead_score) }}>
                  {detailModal.lead.lead_score}
                </div>
                <div style={{ fontSize: 11, color: '#999' }}>评分</div>
              </div>
            </div>

            {/* 状态标签 */}
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 13, color: '#999', marginBottom: 8 }}>当前状态</div>
              <Space wrap>
                {Object.entries(STATUS_MAP).map(([key, { text, color }]) => (
                  <Button
                    key={key}
                    size="small"
                    type={detailModal.lead?.status === key ? 'primary' : 'default'}
                    style={detailModal.lead?.status === key ? { background: color, borderColor: color } : undefined}
                    onClick={() => handleStatusChange(detailModal.lead!.id, key)}
                  >
                    {text}
                  </Button>
                ))}
              </Space>
            </div>

            {/* 意向类型 */}
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 13, color: '#999', marginBottom: 8 }}>意向类型</div>
              <Tag color="blue" style={{ fontSize: 13 }}>{INTENT_MAP[detailModal.lead?.intent_type || ''] || detailModal.lead?.intent_type}</Tag>
            </div>

            {/* 用户信息快速操作(客户需求) */}
            <div style={{ marginBottom: 16, padding: 12, background: '#fafafa', borderRadius: 8 }}>
              <div style={{ fontSize: 13, color: '#999', marginBottom: 8 }}>用户信息</div>
              <Space wrap size={[4, 8]}>
                {detailModal.lead.user_id && (
                  <Tooltip title="复制用户ID">
                    <Button size="small" icon={<CopyOutlined />}
                      onClick={() => { navigator.clipboard.writeText(detailModal.lead!.user_id || ''); message.success('已复制用户ID'); }}>
                      复制ID
                    </Button>
                  </Tooltip>
                )}
                {detailModal.lead.nickname && (
                  <Tooltip title="复制昵称">
                    <Button size="small" icon={<CopyOutlined />}
                      onClick={() => { navigator.clipboard.writeText(detailModal.lead!.nickname || ''); message.success('已复制昵称'); }}>
                      复制昵称
                    </Button>
                  </Tooltip>
                )}
                {detailModal.lead.platform_display_id && (
                  <Tooltip title="复制平台显示ID(如抖音号)">
                    <Button size="small" icon={<CopyOutlined />}
                      onClick={() => { navigator.clipboard.writeText(detailModal.lead!.platform_display_id || ''); message.success('已复制平台ID'); }}>
                      复制平台ID
                    </Button>
                  </Tooltip>
                )}
                {detailModal.lead.comment_url && (
                  <Tooltip title="打开原评论">
                    <Button size="small" icon={<LinkOutlined />} type="link" href={detailModal.lead.comment_url} target="_blank">
                      原评论
                    </Button>
                  </Tooltip>
                )}
                {detailModal.lead.profile_url && (
                  <Tooltip title="打开用户主页">
                    <Button size="small" icon={<UserOutlined />} type="link" href={detailModal.lead.profile_url} target="_blank">
                      用户主页
                    </Button>
                  </Tooltip>
                )}
              </Space>
            </div>

            {/* 内容 */}
            <div style={{ padding: 12, background: '#f6ffed', borderRadius: 8, marginBottom: 16 }}>
              <div style={{ fontSize: 14, lineHeight: 1.6, color: '#333', whiteSpace: 'pre-wrap' }}>
                {detailModal.lead.content}
              </div>
            </div>

            {/* 来源视频/原作品信息 - 用于营销时查看原视频 */}
            {detailLoading ? (
              <div style={{ textAlign: 'center', padding: 16, color: '#999', marginBottom: 16 }}>加载来源视频...</div>
            ) : detailModal.lead.source_aweme_id ? (
              <div style={{ padding: 12, background: '#f0f5ff', borderRadius: 8, marginBottom: 16, border: '1px solid #adc6ff' }}>
                <div style={{ fontSize: 13, color: '#1d39c4', fontWeight: 600, marginBottom: 8 }}>
                  📺 来源视频 / 原文案
                </div>
                {detailModal.lead.source_cover_url && (
                  <div style={{ marginBottom: 8, textAlign: 'center' }}>
                    <img
                      src={detailModal.lead.source_cover_url}
                      alt="视频封面"
                      style={{ maxWidth: '100%', maxHeight: 200, borderRadius: 6, objectFit: 'cover' }}
                      onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                    />
                  </div>
                )}
                {detailModal.lead.source_video_title && (
                  <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4, color: '#333' }}>
                    {detailModal.lead.source_video_title}
                  </div>
                )}
                {detailModal.lead.source_video_desc && (
                  <div style={{ fontSize: 13, color: '#666', lineHeight: 1.5, whiteSpace: 'pre-wrap', marginBottom: 8 }}>
                    {detailModal.lead.source_video_desc}
                  </div>
                )}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 12, color: '#999' }}>
                  <span>作者: {detailModal.lead.source_author_nickname || '未知'}</span>
                  <span>ID: {detailModal.lead.source_aweme_id}</span>
                </div>
                {detailModal.lead.source_video_url && (
                  <Button
                    block
                    size="small"
                    type="link"
                    href={detailModal.lead.source_video_url}
                    target="_blank"
                    style={{ marginTop: 8, padding: 0 }}
                  >
                    打开原视频 ↗
                  </Button>
                )}
              </div>
            ) : null}

            {/* 标题 */}
            {detailModal.lead.title && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 13, color: '#999', marginBottom: 4 }}>原帖标题</div>
                <div style={{ fontSize: 13, color: '#666' }}>{detailModal.lead.title}</div>
              </div>
            )}

            {/* 关键词 */}
            {detailModal.lead.matched_keywords && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 13, color: '#999', marginBottom: 8 }}>匹配关键词</div>
                <Space wrap>
                  {detailModal.lead.matched_keywords.split(',').map((kw: string, i: number) => (
                    <Tag key={i} color="orange">{kw.trim()}</Tag>
                  ))}
                </Space>
              </div>
            )}

            {/* 备注 */}
            {detailModal.lead.notes && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 13, color: '#999', marginBottom: 4 }}>备注</div>
                <div style={{ fontSize: 13, color: '#666', background: '#fafafa', padding: 8, borderRadius: 4 }}>
                  {detailModal.lead.notes}
                </div>
              </div>
            )}

            {/* 操作按钮 */}
            <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
              {detailModal.lead.sec_uid && detailModal.lead.platform === 'douyin' && (
                <Button block type="primary" icon={<UserOutlined />} href={`https://www.douyin.com/user/${detailModal.lead.sec_uid}`} target="_blank">
                  打开用户主页(私信)
                </Button>
              )}
              {detailModal.lead.user_id && ['xhs', 'kuaishou', 'weibo', 'bilibili'].includes(detailModal.lead.platform || '') && (
                <Button block type="primary" icon={<UserOutlined />}
                  href={
                    detailModal.lead.platform === 'xhs' ? `https://www.xiaohongshu.com/user/profile/${detailModal.lead.user_id}` :
                    detailModal.lead.platform === 'kuaishou' ? `https://www.kuaishou.com/profile/${detailModal.lead.user_id}` :
                    detailModal.lead.platform === 'weibo' ? `https://weibo.com/u/${detailModal.lead.user_id}` :
                    `https://space.bilibili.com/${detailModal.lead.user_id}`
                  }
                  target="_blank"
                >
                  打开用户主页(私信)
                </Button>
              )}
              {detailModal.lead.url && (
                <Button block icon={<EyeOutlined />} href={detailModal.lead.url} target="_blank">查看原帖</Button>
              )}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default LeadList;
