import { message } from '../utils/antdMessage';
import React, { useEffect, useState, useCallback, useRef } from 'react';
import {
  Card, Table, Tag, Button, Space, Modal, Form, Input, Select,
  Row, Col, Statistic, Tabs, Empty, Spin, Switch, InputNumber,
  Tooltip, Badge, Popconfirm, Descriptions,
} from 'antd';
import {
  ReloadOutlined, PlusOutlined, PlayCircleOutlined, PauseCircleOutlined,
  ThunderboltOutlined, EditOutlined, DeleteOutlined, EyeOutlined,
  CommentOutlined, UserOutlined, VideoCameraOutlined, FireOutlined,
} from '@ant-design/icons';
import {
  getPlatforms, listTasks, createTask, updateTask, deleteTask,
  startTask, stopTask, checkNow, listRecords, getTaskStats,
  type CommentMonitorTask, type CommentMonitorRecord, type TaskStats,
} from '../api/commentMonitor';

const PLATFORM_LABEL: Record<string, string> = {
  douyin: '抖音',
  xhs: '小红书',
  ks: '快手',
  bili: 'B站',
  wb: '微博',
};

const STATUS_TAG: Record<string, { text: string; color: string }> = {
  pending: { text: '待启动', color: 'default' },
  running: { text: '运行中', color: 'processing' },
  paused: { text: '已暂停', color: 'warning' },
  stopped: { text: '已停止', color: 'default' },
  error: { text: '错误', color: 'error' },
};

const INTENT_LABEL: Record<string, { text: string; color: string }> = {
  inquiry: { text: '询价', color: 'orange' },
  recommendation: { text: '推荐', color: 'blue' },
  comparison: { text: '比价', color: 'cyan' },
  purchase: { text: '求购', color: 'red' },
  negative: { text: '负面', color: 'error' },
  irrelevant: { text: '无关', color: 'default' },
};

const CommentMonitor: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [tasks, setTasks] = useState<CommentMonitorTask[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [platforms, setPlatforms] = useState<string[]>([]);
  const [tab, setTab] = useState('tasks');
  const [createOpen, setCreateOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [editing, setEditing] = useState<CommentMonitorTask | null>(null);
  const [form] = Form.useForm();
  const [editForm] = Form.useForm();
  const [recordsModal, setRecordsModal] = useState<{ open: boolean; task?: CommentMonitorTask }>({ open: false });
  const [records, setRecords] = useState<CommentMonitorRecord[]>([]);
  const [recordsTotal, setRecordsTotal] = useState(0);
  const [recordsPage, setRecordsPage] = useState(1);
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [statsMap, setStatsMap] = useState<Record<string, TaskStats>>({});
  const fetchSeqRef = useRef(0);

  const fetchTasks = useCallback(async () => {
    const seq = ++fetchSeqRef.current;
    setLoading(true);
    try {
      const res = await listTasks({ page, page_size: pageSize });
      if (seq !== fetchSeqRef.current) return;
      setTasks(res.items || []);
      setTotal(res.total || 0);
    } catch (e: any) {
      message.error(e?.message || '获取任务列表失败');
    } finally {
      if (seq === fetchSeqRef.current) setLoading(false);
    }
  }, [page, pageSize]);

  const fetchMeta = useCallback(async () => {
    try {
      const res = await getPlatforms();
      setPlatforms(res.platforms || []);
    } catch (e) {
      // ignore
    }
  }, []);

  const fetchStats = useCallback(async (taskId: string) => {
    try {
      const stats = await getTaskStats(taskId);
      setStatsMap(prev => ({ ...prev, [taskId]: stats }));
    } catch (e) {
      // ignore
    }
  }, []);

  useEffect(() => {
    fetchMeta();
  }, [fetchMeta]);

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  // 拉取任务统计（每 30s 轮询一次）
  useEffect(() => {
    if (tasks.length === 0) return;
    tasks.forEach(t => fetchStats(t.task_id));
    const timer = setInterval(() => {
      tasks.forEach(t => fetchStats(t.task_id));
    }, 30000);
    return () => clearInterval(timer);
  }, [tasks, fetchStats]);

  // ============ 操作 ============

  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      await createTask({
        platform: values.platform,
        monitor_type: values.monitor_type,
        target_id: values.target_id.trim(),
        target_nickname: values.target_nickname || '',
        keywords: values.keywords || '',
        enable_auto_reply: values.enable_auto_reply || false,
        enable_lead_extract: values.enable_lead_extract !== false,
        check_interval: values.check_interval || 300,
        max_comments_per_check: values.max_comments_per_check || 100,
      });
      message.success('监控任务已创建');
      setCreateOpen(false);
      form.resetFields();
      fetchTasks();
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error(e?.message || '创建任务失败');
    }
  };

  const handleEdit = (task: CommentMonitorTask) => {
    setEditing(task);
    editForm.setFieldsValue({
      target_nickname: task.target_nickname,
      keywords: task.keywords,
      enable_auto_reply: task.enable_auto_reply,
      enable_lead_extract: task.enable_lead_extract,
      check_interval: task.check_interval,
      max_comments_per_check: task.max_comments_per_check,
    });
    setEditOpen(true);
  };

  const handleEditSubmit = async () => {
    if (!editing) return;
    try {
      const values = await editForm.validateFields();
      await updateTask(editing.task_id, values);
      message.success('已更新');
      setEditOpen(false);
      setEditing(null);
      fetchTasks();
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error(e?.message || '更新失败');
    }
  };

  const handleStart = async (taskId: string) => {
    try {
      await startTask(taskId);
      message.success('监控已启动');
      fetchTasks();
    } catch (e: any) {
      message.error(e?.message || '启动失败');
    }
  };

  const handleStop = async (taskId: string) => {
    try {
      await stopTask(taskId);
      message.success('监控已停止');
      fetchTasks();
    } catch (e: any) {
      message.error(e?.message || '停止失败');
    }
  };

  const handleCheckNow = async (taskId: string) => {
    try {
      await checkNow(taskId);
      message.success('已触发检查，稍后查看抓取记录');
    } catch (e: any) {
      message.error(e?.message || '触发失败');
    }
  };

  const handleDelete = async (taskId: string) => {
    try {
      await deleteTask(taskId);
      message.success('已删除');
      fetchTasks();
    } catch (e: any) {
      message.error(e?.message || '删除失败');
    }
  };

  const handleViewRecords = async (task: CommentMonitorTask, newPage = 1) => {
    setRecordsModal({ open: true, task });
    setRecordsPage(newPage);
    setRecordsLoading(true);
    try {
      const res = await listRecords(task.task_id, { page: newPage, page_size: 20 });
      setRecords(res.items || []);
      setRecordsTotal(res.total || 0);
    } catch (e: any) {
      message.error(e?.message || '获取记录失败');
    } finally {
      setRecordsLoading(false);
    }
  };

  // ============ 表格列 ============

  const taskColumns = [
    {
      title: '平台', dataIndex: 'platform', width: 80,
      render: (v: string) => <Tag color="blue">{PLATFORM_LABEL[v] || v}</Tag>,
    },
    {
      title: '类型', dataIndex: 'monitor_type', width: 100,
      render: (v: string) => v === 'account'
        ? <Tag icon={<UserOutlined />} color="purple">同行账号</Tag>
        : <Tag icon={<VideoCameraOutlined />} color="geekblue">爆款视频</Tag>,
    },
    {
      title: '监控目标', dataIndex: 'target_nickname', ellipsis: true,
      render: (v: string, r: CommentMonitorTask) => (
        <Tooltip title={r.target_id}>
          <span>{v || r.target_id}</span>
        </Tooltip>
      ),
    },
    {
      title: '关键词', dataIndex: 'keywords', ellipsis: true,
      render: (v: string) => v ? <span style={{ wordBreak: 'break-all', whiteSpace: 'normal' }}>{v}</span> : <span style={{ color: '#999' }}>-</span>,
    },
    {
      title: '状态', width: 100,
      render: (_: any, r: CommentMonitorTask) => {
        const st = STATUS_TAG[r.status] || STATUS_TAG.pending;
        return <Badge status={r.is_running ? 'processing' : 'default'} text={<Tag color={st.color}>{st.text}</Tag>} />;
      },
    },
    {
      title: '已抓/线索', width: 110,
      render: (_: any, r: CommentMonitorTask) => {
        const s = statsMap[r.task_id];
        return s ? `${s.total_comments} / ${s.total_leads}` : '-';
      },
    },
    {
      title: '上次检查', dataIndex: 'last_check_at', width: 150,
      render: (v: number) => v ? new Date(v * 1000).toLocaleString() : '-',
    },
    {
      title: '操作', width: 280, fixed: 'right' as const,
      render: (_: any, r: CommentMonitorTask) => (
        <Space size="small" wrap>
          {r.is_running ? (
            <Button size="small" icon={<PauseCircleOutlined />} onClick={() => handleStop(r.task_id)}>停止</Button>
          ) : (
            <Button size="small" type="primary" icon={<PlayCircleOutlined />} onClick={() => handleStart(r.task_id)}>启动</Button>
          )}
          <Button size="small" icon={<ThunderboltOutlined />} onClick={() => handleCheckNow(r.task_id)}>立即检查</Button>
          <Button size="small" icon={<EyeOutlined />} onClick={() => handleViewRecords(r)}>记录</Button>
          <Button size="small" icon={<EditOutlined />} onClick={() => handleEdit(r)} />
          <Popconfirm title="确认删除该任务及其抓取记录？" onConfirm={() => handleDelete(r.task_id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const recordColumns = [
    {
      title: '评论内容', dataIndex: 'comment_text', ellipsis: false,
      render: (v: string) => (
        <div style={{ maxWidth: 360, wordBreak: 'break-all', whiteSpace: 'normal' }}>{v}</div>
      ),
    },
    {
      title: '作者', dataIndex: 'author_nickname', width: 120, ellipsis: true,
      render: (v: string, r: CommentMonitorRecord) => (
        <Tooltip title={r.author_sec_uid || r.author_id}>
          <span>{v || r.author_id}</span>
        </Tooltip>
      ),
    },
    {
      title: '意图', dataIndex: 'intent_type', width: 80,
      render: (v: string) => {
        const it = INTENT_LABEL[v] || { text: v || '-', color: 'default' };
        return <Tag color={it.color}>{it.text}</Tag>;
      },
    },
    {
      title: '评分', dataIndex: 'lead_score', width: 70,
      render: (v: number) => (
        <span style={{ color: v >= 50 ? '#f5222d' : v >= 25 ? '#fa8c16' : '#999', fontWeight: v >= 50 ? 600 : 400 }}>
          {v}
        </span>
      ),
    },
    {
      title: '关键词', dataIndex: 'matched_keywords', width: 150, ellipsis: true,
      render: (v: string) => v ? <span style={{ wordBreak: 'break-all', whiteSpace: 'normal' }}>{v}</span> : '-',
    },
    {
      title: '转线索', width: 70,
      render: (_: any, r: CommentMonitorRecord) => r.converted_to_lead ? <Tag color="red">已转</Tag> : <span style={{ color: '#999' }}>-</span>,
    },
    {
      title: '已回复', width: 70,
      render: (_: any, r: CommentMonitorRecord) => r.is_replied ? <Tag color="green">已回</Tag> : <span style={{ color: '#999' }}>-</span>,
    },
    {
      title: '抓取时间', dataIndex: 'created_at', width: 150,
      render: (v: number) => v ? new Date(v * 1000).toLocaleString() : '-',
    },
  ];

  // ============ 渲染 ============

  return (
    <div style={{ padding: 16 }}>
      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          { key: 'tasks', label: <span><CommentOutlined /> 监控任务</span> },
          {
            key: 'overview', label: <span><FireOutlined /> 汇总看板</span>,
            disabled: tasks.length === 0,
          },
        ]}
      />

      {tab === 'tasks' && (
        <Card
          title="评论监控任务"
          extra={
            <Space>
              <Button icon={<ReloadOutlined />} onClick={fetchTasks}>刷新</Button>
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>新建监控</Button>
            </Space>
          }
        >
          <Table
            rowKey="task_id"
            loading={loading}
            dataSource={tasks}
            columns={taskColumns}
            scroll={{ x: 1200 }}
            pagination={{
              current: page, pageSize, total,
              onChange: (p, ps) => { setPage(p); setPageSize(ps); },
              showTotal: (t) => `共 ${t} 条`,
              showSizeChanger: true,
            }}
            locale={{ emptyText: <Empty description="暂无监控任务，点击「新建监控」开始" /> }}
          />
        </Card>
      )}

      {tab === 'overview' && (
        <Row gutter={16}>
          {tasks.map(t => {
            const s = statsMap[t.task_id];
            return (
              <Col key={t.task_id} xs={24} sm={12} md={8} lg={6} style={{ marginBottom: 16 }}>
                <Card size="small" title={
                  <Space>
                    <Tag color="blue">{PLATFORM_LABEL[t.platform] || t.platform}</Tag>
                    <span style={{ fontSize: 13 }}>{t.target_nickname || t.target_id}</span>
                  </Space>
                } extra={t.is_running ? <Badge status="processing" /> : null}>
                  {s ? (
                    <Row gutter={8}>
                      <Col span={12}><Statistic title="抓取评论" value={s.total_comments} /></Col>
                      <Col span={12}><Statistic title="转线索" value={s.total_leads} valueStyle={{ color: '#f5222d' }} /></Col>
                      <Col span={12}><Statistic title="已回复" value={s.total_replied} /></Col>
                      <Col span={12}><Statistic title="平均分" value={s.avg_lead_score} precision={1} /></Col>
                    </Row>
                  ) : <Spin size="small" />}
                </Card>
              </Col>
            );
          })}
        </Row>
      )}

      {/* 新建任务 Modal */}
      <Modal
        title="新建评论监控任务"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={handleCreate}
        width={640}
        destroyOnClose
        okText="创建"
        cancelText="取消"
      >
        <Form form={form} layout="vertical" initialValues={{
          platform: 'douyin', monitor_type: 'video',
          enable_lead_extract: true, enable_auto_reply: false,
          check_interval: 300, max_comments_per_check: 100,
        }}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="平台" name="platform" rules={[{ required: true }]}>
                <Select>
                  {platforms.map(p => (
                    <Select.Option key={p} value={p}>{PLATFORM_LABEL[p] || p}</Select.Option>
                  ))}
                  {!platforms.includes('douyin') && (
                    <Select.Option value="douyin">抖音</Select.Option>
                  )}
                </Select>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="监控类型" name="monitor_type" rules={[{ required: true }]}>
                <Select>
                  <Select.Option value="video">爆款视频（指定视频URL/ID）</Select.Option>
                  <Select.Option value="account">同行账号（指定用户sec_uid）</Select.Option>
                </Select>
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            label="监控目标 ID / URL"
            name="target_id"
            rules={[{ required: true, message: '请输入监控目标' }]}
            extra="video 模式填视频URL或ID；account 模式填用户 sec_uid"
          >
            <Input placeholder="如 https://www.douyin.com/video/xxx 或 sec_uid" />
          </Form.Item>
          <Form.Item label="目标昵称（可选，便于展示）" name="target_nickname">
            <Input placeholder="如 同行A / 爆款视频标题" />
          </Form.Item>
          <Form.Item
            label="筛选关键词"
            name="keywords"
            extra="逗号分隔，用于评论匹配与意向评分加成，如：怎么卖,多少钱,电话"
          >
            <Input placeholder="怎么卖,多少钱,电话" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="检查间隔（秒）" name="check_interval" rules={[{ required: true }]}>
                <InputNumber min={60} max={86400} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="单次抓取上限" name="max_comments_per_check" rules={[{ required: true }]}>
                <InputNumber min={10} max={500} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item label="意向客户识别（AI）" name="enable_lead_extract" valuePropName="checked">
                <Switch checkedChildren="开" unCheckedChildren="关" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="自动回复评论（AI）" name="enable_auto_reply" valuePropName="checked">
                <Switch checkedChildren="开" unCheckedChildren="关" />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      {/* 编辑任务 Modal */}
      <Modal
        title="编辑监控任务"
        open={editOpen}
        onCancel={() => { setEditOpen(false); setEditing(null); }}
        onOk={handleEditSubmit}
        width={640}
        destroyOnClose
        okText="保存"
        cancelText="取消"
      >
        {editing && (
          <Form form={editForm} layout="vertical">
            <Descriptions column={2} size="small" style={{ marginBottom: 16 }}>
              <Descriptions.Item label="任务ID">{editing.task_id}</Descriptions.Item>
              <Descriptions.Item label="平台">{PLATFORM_LABEL[editing.platform] || editing.platform}</Descriptions.Item>
              <Descriptions.Item label="类型">{editing.monitor_type === 'account' ? '同行账号' : '爆款视频'}</Descriptions.Item>
              <Descriptions.Item label="目标ID" span={2}>
                <span style={{ wordBreak: 'break-all', whiteSpace: 'normal' }}>{editing.target_id}</span>
              </Descriptions.Item>
            </Descriptions>
            <Form.Item label="目标昵称" name="target_nickname">
              <Input />
            </Form.Item>
            <Form.Item label="筛选关键词（逗号分隔）" name="keywords">
              <Input placeholder="怎么卖,多少钱,电话" />
            </Form.Item>
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item label="检查间隔（秒）" name="check_interval" rules={[{ required: true }]}>
                  <InputNumber min={60} max={86400} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label="单次抓取上限" name="max_comments_per_check" rules={[{ required: true }]}>
                  <InputNumber min={10} max={500} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
            </Row>
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item label="意向客户识别（AI）" name="enable_lead_extract" valuePropName="checked">
                  <Switch checkedChildren="开" unCheckedChildren="关" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label="自动回复评论（AI）" name="enable_auto_reply" valuePropName="checked">
                  <Switch checkedChildren="开" unCheckedChildren="关" />
                </Form.Item>
              </Col>
            </Row>
            {editing.last_error && (
              <div style={{ color: '#f5222d', fontSize: 12, marginTop: 8 }}>
                最近错误：{editing.last_error}
              </div>
            )}
          </Form>
        )}
      </Modal>

      {/* 抓取记录 Modal */}
      <Modal
        title={recordsModal.task ? `抓取记录 - ${recordsModal.task.target_nickname || recordsModal.task.target_id}` : '抓取记录'}
        open={recordsModal.open}
        onCancel={() => setRecordsModal({ open: false })}
        footer={null}
        width={1100}
      >
        <Table
          rowKey="id"
          loading={recordsLoading}
          dataSource={records}
          columns={recordColumns}
          scroll={{ x: 1100 }}
          size="small"
          pagination={{
            current: recordsPage, pageSize: 20, total: recordsTotal,
            onChange: (p) => recordsModal.task && handleViewRecords(recordsModal.task, p),
            showTotal: (t) => `共 ${t} 条`,
          }}
          locale={{ emptyText: <Empty description="暂无抓取记录" /> }}
        />
      </Modal>
    </div>
  );
};

export default CommentMonitor;
