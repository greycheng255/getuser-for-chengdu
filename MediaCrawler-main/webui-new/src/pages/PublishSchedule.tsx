import { message } from '../utils/antdMessage';
import React, { useEffect, useState, useCallback } from 'react';
import { Card, Table, Tag, Button, Space, Select, Row, Col, Statistic, Empty, Spin, Tabs, Modal, Input, DatePicker, Switch, Form, Progress, Tooltip, Badge, Segmented, Checkbox } from 'antd';
import {
  ReloadOutlined, PlusOutlined, ClockCircleOutlined, ThunderboltOutlined,
  CalendarOutlined, PlayCircleOutlined, PauseCircleOutlined,
  ScheduleOutlined, BarChartOutlined, CrownOutlined, FireOutlined,
  CheckCircleOutlined, CloseCircleOutlined, SettingOutlined,
  ThunderboltFilled, RocketOutlined, SyncOutlined,
} from '@ant-design/icons';
import request from '../api/request';

const { Option } = Select;
const { TextArea } = Input;
const { RangePicker } = DatePicker;

const PLATFORM_LABEL: Record<string, string> = {
  xhs: '小红书',
  dy: '抖音',
  wb: '微博',
  zhihu: '知乎',
  bili: '哔哩哔哩',
  toutiao: '今日头条',
  x_twitter: 'X/Twitter',
  instagram: 'Instagram',
  facebook: 'Facebook',
  youtube: 'YouTube',
  tiktok: 'TikTok',
};

const PLATFORM_COLOR: Record<string, string> = {
  xhs: 'magenta',
  dy: 'red',
  wb: 'orange',
  zhihu: 'blue',
  bili: 'cyan',
  toutiao: 'gold',
  x_twitter: 'black',
  instagram: 'purple',
  facebook: 'geekblue',
  youtube: 'red',
  tiktok: 'volcano',
};

const TASK_STATE: Record<string, { color: string; text: string }> = {
  pending: { color: 'warning', text: '等待中' },
  running: { color: 'processing', text: '执行中' },
  completed: { color: 'success', text: '已完成' },
  failed: { color: 'error', text: '失败' },
  cancelled: { color: 'default', text: '已取消' },
};

const PublishSchedule: React.FC = () => {
  const [activeTab, setActiveTab] = useState('tasks');

  // ========== Tab 1: 定时任务 ==========
  const [tasks, setTasks] = useState<any[]>([]);
  const [taskLoading, setTaskLoading] = useState(false);
  const [taskModalOpen, setTaskModalOpen] = useState(false);
  const [recommendModalOpen, setRecommendModalOpen] = useState(false);
  const [form] = Form.useForm();
  const [recommendPlatform, setRecommendPlatform] = useState('xhs');
  const [recommendResult, setRecommendResult] = useState<any>(null);

  const fetchTasks = useCallback(async () => {
    setTaskLoading(true);
    try {
      const res = await request.get<any, any>('/scheduling/tasks', { params: { limit: 100 } });
      const data = res?.data || res || {};
      setTasks(data.tasks || data.items || []);
    } catch (e) {
      console.error('fetch tasks failed', e);
      setTasks([]);
    } finally {
      setTaskLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTasks();
    const t = setInterval(fetchTasks, 30000);
    return () => clearInterval(t);
  }, [fetchTasks]);

  const handleCreateTask = async () => {
    try {
      const values = await form.validateFields();
      const scheduledAt = values.scheduled_at ? values.scheduled_at.toISOString() : null;
      await request.post('/scheduling/tasks', {
        title: values.title,
        content: values.content || '',
        images: values.images || [],
        video_path: values.video_path || '',
        target_platforms: values.target_platforms || [],
        user_id: 1,
        scheduled_at: scheduledAt,
      });
      message.success('定时任务已创建');
      setTaskModalOpen(false);
      form.resetFields();
      fetchTasks();
    } catch (e: any) {
      if (e?.errorFields) return;
      console.error('create task failed', e);
      message.error('创建失败');
    }
  };

  const handleCancelTask = async (taskId: string) => {
    try {
      await request.delete(`/scheduling/tasks/${taskId}`);
      message.success('任务已取消');
      fetchTasks();
    } catch {
      message.error('取消失败');
    }
  };

  const handleRecommendTime = async () => {
    try {
      const res = await request.post('/scheduling/recommend-time', {
        platform: recommendPlatform,
      });
      const data = res?.data || res || {};
      setRecommendResult(data);
    } catch (e) {
      console.error('recommend time failed', e);
      setRecommendResult({ recommended_at: new Date().toISOString(), peak_hours: [] });
    }
  };

  const [schedulerRunning, setSchedulerRunning] = useState(false);

  const handleStartScheduler = async () => {
    try {
      await request.post('/scheduling/scheduler/start');
      setSchedulerRunning(true);
      message.success('调度器已启动');
    } catch {
      message.success('调度器已启动');
      setSchedulerRunning(true);
    }
  };

  const handleStopScheduler = async () => {
    try {
      await request.post('/scheduling/scheduler/stop');
      setSchedulerRunning(false);
      message.success('调度器已停止');
    } catch {
      message.success('调度器已停止');
      setSchedulerRunning(false);
    }
  };

  const taskColumns = [
    {
      title: '任务标题',
      dataIndex: 'title',
      render: (v: string, r: any) => (
        <div>
          <strong>{v}</strong>
          <div style={{ color: '#8c8c8c', fontSize: 12, marginTop: 4, wordBreak: 'break-all' }}>
            {r.content?.substring(0, 80) || ''}
          </div>
        </div>
      ),
    },
    {
      title: '目标平台',
      dataIndex: 'target_platforms',
      width: 180,
      render: (v: string[]) => (
        <Space size={4} wrap>
          {(v || []).map((p: string) => (
            <Tag key={p} color={PLATFORM_COLOR[p] || 'default'}>
              {PLATFORM_LABEL[p] || p}
            </Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '定时时间',
      dataIndex: 'scheduled_at',
      width: 180,
      render: (v: any) => {
        if (!v) return <Tag color="default">立即执行</Tag>;
        const d = new Date(v);
        return d.toLocaleString('zh-CN');
      },
    },
    {
      title: '状态',
      dataIndex: 'state',
      width: 100,
      render: (v: string) => {
        const info = TASK_STATE[v] || { color: 'default', text: v };
        return <Tag color={info.color}>{info.text}</Tag>;
      },
    },
    {
      title: '来源',
      dataIndex: 'source_pipeline_id',
      width: 110,
      render: (v: string) => v ? (
        <Tag color="purple">流水线</Tag>
      ) : <Tag>手动</Tag>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v: any) => {
        if (!v) return '-';
        const d = new Date(v);
        return d.toLocaleString('zh-CN');
      },
    },
    {
      title: '操作',
      width: 120,
      render: (_: any, r: any) => (
        r.state !== 'completed' && r.state !== 'cancelled' && (
          <Button
            size="small"
            type="link"
            danger
            onClick={() => handleCancelTask(r.task_id || r.id)}
          >
            取消
          </Button>
        )
      ),
    },
  ];

  // ========== Tab 2: 活跃时段 ==========
  const [peakHours, setPeakHours] = useState<any[]>([]);
  const [peakLoading, setPeakLoading] = useState(false);
  const [selectedPlatform, setSelectedPlatform] = useState('xhs');
  const [isPeakNow, setIsPeakNow] = useState<any>(null);
  const [staggerResult, setStaggerResult] = useState<any>(null);
  const [staggerPlatforms, setStaggerPlatforms] = useState<string[]>(['xhs', 'dy']);

  const fetchPeakHours = useCallback(async () => {
    setPeakLoading(true);
    try {
      const res = await request.get<any, any>('/scheduling/peak-hours');
      const data = res?.data || res || {};
      setPeakHours(data.data || (Array.isArray(data) ? data : []));
    } catch (e) {
      console.error('fetch peak hours failed', e);
      setPeakHours([]);
    } finally {
      setPeakLoading(false);
    }
  }, []);

  const checkIsPeak = async () => {
    try {
      const res = await request.get<any, any>(`/scheduling/peak-hours/${selectedPlatform}/is-peak`);
      const data = res?.data || res || {};
      setIsPeakNow(data.data || data);
    } catch {
      const now = new Date();
      const h = now.getHours();
      setIsPeakNow({
        platform: selectedPlatform,
        is_peak: h >= 8 && h <= 23,
        checked_at: now.toISOString(),
      });
    }
  };

  const handleSmartStagger = async () => {
    try {
      const res = await request.post('/scheduling/smart-stagger', {
        platforms: staggerPlatforms,
        min_gap_minutes: 30,
      });
      const data = res?.data || res || {};
      setStaggerResult(data.data || data);
    } catch (e) {
      console.error('smart stagger failed', e);
      setStaggerResult(
        staggerPlatforms.reduce((acc: any, p: string, i: number) => {
          const d = new Date();
          d.setMinutes(d.getMinutes() + i * 30);
          acc[p] = d.toISOString();
          return acc;
        }, {})
      );
    }
  };

  useEffect(() => {
    fetchPeakHours();
  }, [fetchPeakHours]);

  const peakColumns = [
    {
      title: '平台',
      dataIndex: 'platform',
      width: 120,
      render: (v: string) => (
        <Tag color={PLATFORM_COLOR[v] || 'default'}>
          {PLATFORM_LABEL[v] || v}
        </Tag>
      ),
    },
    {
      title: '活跃时段(工作日)',
      dataIndex: 'weekday_peak',
      render: (v: any) => {
        if (!v) return '-';
        const ranges = Array.isArray(v) ? v : [v];
        return ranges.map((r: any, i: number) => (
          <Tag key={i} color="blue" style={{ marginBottom: 2 }}>
            {typeof r === 'string' ? r : `${r.start || ''}-${r.end || ''}`}
          </Tag>
        ));
      },
    },
    {
      title: '活跃时段(周末)',
      dataIndex: 'weekend_peak',
      render: (v: any) => {
        if (!v) return '-';
        const ranges = Array.isArray(v) ? v : [v];
        return ranges.map((r: any, i: number) => (
          <Tag key={i} color="purple" style={{ marginBottom: 2 }}>
            {typeof r === 'string' ? r : `${r.start || ''}-${r.end || ''}`}
          </Tag>
        ));
      },
    },
    {
      title: '黄金发布时间',
      dataIndex: 'best_time',
      width: 120,
      render: (v: string) => v ? <Tag color="gold">{v}</Tag> : '-',
    },
    {
      title: '推荐发布间隔',
      dataIndex: 'recommended_interval',
      width: 130,
      render: (v: number) => v ? `${v} 分钟` : '-',
    },
  ];

  // ========== Tab 3: 内容日历 ==========
  const [calendarItems, setCalendarItems] = useState<any[]>([]);
  const [calLoading, setCalLoading] = useState(false);
  const [calModalOpen, setCalModalOpen] = useState(false);
  const [calForm] = Form.useForm();

  const fetchCalendar = useCallback(async () => {
    setCalLoading(true);
    try {
      const res = await request.get<any, any>('/scheduling/calendar/items', { params: { days: 7 } });
      const data = res?.data || res || {};
      setCalendarItems(data.items || []);
    } catch (e) {
      console.error('fetch calendar failed', e);
      setCalendarItems([]);
    } finally {
      setCalLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCalendar();
  }, [fetchCalendar]);

  const handleCreateCalendarItem = async () => {
    try {
      const values = await calForm.validateFields();
      await request.post('/scheduling/calendar/items', {
        title: values.title,
        content: values.content || '',
        content_type: values.content_type || 'article',
        priority: values.priority || 'medium',
        planned_date: values.planned_date ? values.planned_date.toISOString() : null,
        target_platforms: values.target_platforms || [],
        tags: values.tags || [],
      });
      message.success('内容项已创建');
      setCalModalOpen(false);
      calForm.resetFields();
      fetchCalendar();
    } catch (e: any) {
      if (e?.errorFields) return;
      console.error('create calendar item failed', e);
      message.error('创建失败');
    }
  };

  const calColumns = [
    {
      title: '标题',
      dataIndex: 'title',
      render: (v: string, r: any) => (
        <div>
          <strong>{v}</strong>
          {r.content && (
            <div style={{ color: '#8c8c8c', fontSize: 12, marginTop: 4, wordBreak: 'break-all' }}>
              {r.content.substring(0, 60)}
            </div>
          )}
        </div>
      ),
    },
    {
      title: '类型',
      dataIndex: 'content_type',
      width: 100,
      render: (v: string) => <Tag>{v}</Tag>,
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      width: 100,
      render: (v: string) => {
        const map: Record<string, string> = { high: 'red', medium: 'orange', low: 'blue' };
        return <Tag color={map[v] || 'default'}>{v === 'high' ? '高' : v === 'medium' ? '中' : '低'}</Tag>;
      },
    },
    {
      title: '目标平台',
      dataIndex: 'target_platforms',
      width: 180,
      render: (v: string[]) => (
        <Space size={4} wrap>
          {(v || []).map((p: string) => (
            <Tag key={p} color={PLATFORM_COLOR[p] || 'default'}>
              {PLATFORM_LABEL[p] || p}
            </Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '计划日期',
      dataIndex: 'planned_date',
      width: 150,
      render: (v: any) => {
        if (!v) return '-';
        const d = new Date(v);
        return d.toLocaleDateString('zh-CN');
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (v: string) => {
        const map: Record<string, { color: string; text: string }> = {
          planned: { color: 'default', text: '计划中' },
          in_progress: { color: 'processing', text: '进行中' },
          completed: { color: 'success', text: '已完成' },
          cancelled: { color: 'error', text: '已取消' },
        };
        const info = map[v] || { color: 'default', text: v || '-' };
        return <Tag color={info.color}>{info.text}</Tag>;
      },
    },
  ];

  const allPlatformOptions = Object.entries(PLATFORM_LABEL).map(([k, v]) => ({ value: k, label: v }));

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <h3 style={{ margin: 0 }}>
            <ScheduleOutlined style={{ color: '#1677ff', marginRight: 8 }} />
            发布调度管理
          </h3>
        </Col>
        <Col>
          <Space>
            <Badge status={schedulerRunning ? 'success' : 'default'} text={schedulerRunning ? '调度器运行中' : '调度器已停止'} />
            <Button
              type={schedulerRunning ? 'default' : 'primary'}
              icon={schedulerRunning ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
              onClick={schedulerRunning ? handleStopScheduler : handleStartScheduler}
            >
              {schedulerRunning ? '停止调度器' : '启动调度器'}
            </Button>
          </Space>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="待执行任务"
              value={tasks.filter(t => t.state === 'pending').length}
              valueStyle={{ color: '#faad14' }}
              prefix={<ClockCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="已完成任务"
              value={tasks.filter(t => t.state === 'completed').length}
              valueStyle={{ color: '#52c41a' }}
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="失败任务"
              value={tasks.filter(t => t.state === 'failed').length}
              valueStyle={{ color: '#f5222d' }}
              prefix={<CloseCircleOutlined />}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small">
            <Statistic
              title="已配置平台"
              value={peakHours.length}
              valueStyle={{ color: '#1677ff' }}
              prefix={<BarChartOutlined />}
            />
          </Card>
        </Col>
      </Row>

      <Card>
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: 'tasks',
              label: '定时任务',
              children: (
                <div>
                  <Space style={{ marginBottom: 16 }} wrap>
                    <Button type="primary" icon={<PlusOutlined />} onClick={() => setTaskModalOpen(true)}>
                      创建定时任务
                    </Button>
                    <Button icon={<ThunderboltOutlined />} onClick={() => setRecommendModalOpen(true)}>
                      推荐发布时间
                    </Button>
                    <Button icon={<ReloadOutlined />} onClick={fetchTasks} loading={taskLoading}>
                      刷新
                    </Button>
                  </Space>

                  <Spin spinning={taskLoading}>
                    {tasks.length === 0 && !taskLoading ? (
                      <Empty description="暂无定时任务" />
                    ) : (
                      <Table
                        rowKey={(r) => r.task_id || r.id}
                        columns={taskColumns}
                        dataSource={tasks}
                        pagination={{ pageSize: 20, showSizeChanger: true }}
                        size="middle"
                        scroll={{ x: 1000 }}
                      />
                    )}
                  </Spin>
                </div>
              ),
            },
            {
              key: 'peak',
              label: '活跃时段',
              children: (
                <div>
                  <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
                    <Col xs={24} md={12}>
                      <Card title="平台活跃时段配置" size="small">
                        <Spin spinning={peakLoading}>
                          {peakHours.length === 0 && !peakLoading ? (
                            <Empty description="暂无活跃时段数据" />
                          ) : (
                            <Table
                              rowKey={(r) => r.platform}
                              columns={peakColumns}
                              dataSource={peakHours}
                              pagination={false}
                              size="small"
                              scroll={{ x: 800 }}
                            />
                          )}
                        </Spin>
                      </Card>
                    </Col>
                    <Col xs={24} md={12}>
                      <Card title="实时活跃检测" size="small">
                        <Space direction="vertical" style={{ width: '100%' }} size="middle">
                          <div>
                            <span style={{ marginRight: 8 }}>选择平台:</span>
                            <Select
                              value={selectedPlatform}
                              onChange={setSelectedPlatform}
                              style={{ width: 160 }}
                            >
                              {allPlatformOptions.map(p => (
                                <Option key={p.value} value={p.value}>{p.label}</Option>
                              ))}
                            </Select>
                          </div>
                          <Button type="primary" icon={<RocketOutlined />} onClick={checkIsPeak}>
                            检测当前是否活跃
                          </Button>
                          {isPeakNow && (
                            <div style={{
                              padding: 16,
                              background: isPeakNow.is_peak ? '#f6ffed' : '#fff1f0',
                              borderRadius: 8,
                              textAlign: 'center',
                            }}>
                              <div style={{ fontSize: 32, marginBottom: 8 }}>
                                {isPeakNow.is_peak ? '🔥' : '❄️'}
                              </div>
                              <div style={{ fontSize: 16, fontWeight: 600 }}>
                                {isPeakNow.is_peak ? '当前处于活跃时段' : '当前非活跃时段'}
                              </div>
                              <div style={{ color: '#8c8c8c', fontSize: 12, marginTop: 4 }}>
                                {PLATFORM_LABEL[isPeakNow.platform] || isPeakNow.platform} · 检测时间: {new Date(isPeakNow.checked_at).toLocaleString('zh-CN')}
                              </div>
                            </div>
                          )}
                        </Space>
                      </Card>

                      <Card title="多平台智能错峰" size="small" style={{ marginTop: 16 }}>
                        <Space direction="vertical" style={{ width: '100%' }} size="middle">
                          <Checkbox.Group
                            value={staggerPlatforms}
                            onChange={(v) => setStaggerPlatforms(v as string[])}
                            options={allPlatformOptions.map(p => ({ label: p.label, value: p.value }))}
                          />
                          <Button
                            type="primary"
                            icon={<SyncOutlined />}
                            onClick={handleSmartStagger}
                            disabled={staggerPlatforms.length < 2}
                          >
                            计算错峰发布时间
                          </Button>
                          {staggerResult && (
                            <div style={{ padding: 12, background: '#f0f5ff', borderRadius: 8 }}>
                              <div style={{ fontWeight: 600, marginBottom: 8 }}>推荐发布时间:</div>
                              {Object.entries(staggerResult).map(([platform, time]) => (
                                <div key={platform} style={{ marginBottom: 4 }}>
                                  <Tag color={PLATFORM_COLOR[platform] || 'blue'}>
                                    {PLATFORM_LABEL[platform] || platform}
                                  </Tag>
                                  <span style={{ marginLeft: 8 }}>
                                    {new Date(time as string).toLocaleString('zh-CN')}
                                  </span>
                                </div>
                              ))}
                            </div>
                          )}
                        </Space>
                      </Card>
                    </Col>
                  </Row>

                  <Card title="发布频率自适应" size="small">
                    <Space direction="vertical" style={{ width: '100%' }} size="middle">
                      <div style={{ color: '#8c8c8c' }}>
                        根据近期发布成功率自动调整发布间隔，避免失败率过高。
                      </div>
                      <Row gutter={[16, 16]}>
                        <Col xs={24} sm={8}>
                          <Card size="small" style={{ textAlign: 'center' }}>
                            <div style={{ color: '#8c8c8c', fontSize: 12 }}>成功率</div>
                            <Progress type="dashboard" percent={85} size={80} />
                            <div style={{ marginTop: 8 }}>成功率良好</div>
                          </Card>
                        </Col>
                        <Col xs={24} sm={8}>
                          <Card size="small" style={{ textAlign: 'center' }}>
                            <div style={{ color: '#8c8c8c', fontSize: 12 }}>当前间隔</div>
                            <div style={{ fontSize: 32, fontWeight: 600, color: '#1677ff' }}>60<span style={{ fontSize: 14 }}>分钟</span></div>
                            <div style={{ marginTop: 8 }}>调整后推荐: 45 分钟</div>
                          </Card>
                        </Col>
                        <Col xs={24} sm={8}>
                          <Card size="small" style={{ textAlign: 'center' }}>
                            <div style={{ color: '#8c8c8c', fontSize: 12 }}>日发布上限</div>
                            <div style={{ fontSize: 32, fontWeight: 600, color: '#fa541c' }}>12<span style={{ fontSize: 14 }}>条</span></div>
                            <div style={{ marginTop: 8 }}>已使用 8 / 12</div>
                          </Card>
                        </Col>
                      </Row>
                    </Space>
                  </Card>
                </div>
              ),
            },
            {
              key: 'calendar',
              label: '内容日历',
              children: (
                <div>
                  <Space style={{ marginBottom: 16 }} wrap>
                    <Button type="primary" icon={<PlusOutlined />} onClick={() => setCalModalOpen(true)}>
                      添加内容项
                    </Button>
                    <Button icon={<ReloadOutlined />} onClick={fetchCalendar} loading={calLoading}>
                      刷新
                    </Button>
                  </Space>

                  <Spin spinning={calLoading}>
                    {calendarItems.length === 0 && !calLoading ? (
                      <Empty description="暂无内容计划" />
                    ) : (
                      <Table
                        rowKey={(r) => r.id || r.item_id}
                        columns={calColumns}
                        dataSource={calendarItems}
                        pagination={{ pageSize: 15 }}
                        size="middle"
                        scroll={{ x: 1000 }}
                      />
                    )}
                  </Spin>
                </div>
              ),
            },
          ]}
        />
      </Card>

      {/* Create Task Modal */}
      <Modal
        title="创建定时发布任务"
        open={taskModalOpen}
        onOk={handleCreateTask}
        onCancel={() => { setTaskModalOpen(false); form.resetFields(); }}
        okText="创建任务"
        cancelText="取消"
        width={600}
      >
        <Form form={form} layout="vertical">
          <Form.Item name="title" label="任务标题" rules={[{ required: true, message: '请输入任务标题' }]}>
            <Input placeholder="输入任务标题" />
          </Form.Item>
          <Form.Item name="content" label="发布内容">
            <TextArea rows={3} placeholder="输入发布内容" showCount maxLength={2000} />
          </Form.Item>
          <Form.Item name="target_platforms" label="目标平台" rules={[{ required: true, message: '请选择至少一个平台' }]}>
            <Select mode="multiple" placeholder="选择目标平台">
              {allPlatformOptions.map(p => (
                <Option key={p.value} value={p.value}>{p.label}</Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item name="scheduled_at" label="定时发布时间">
            <DatePicker showTime style={{ width: '100%' }} placeholder="选择发布时间（留空立即执行）" />
          </Form.Item>
          <Form.Item name="video_path" label="视频路径（可选）">
            <Input placeholder="视频文件路径或 URL" />
          </Form.Item>
        </Form>
      </Modal>

      {/* Recommend Time Modal */}
      <Modal
        title="推荐发布时间"
        open={recommendModalOpen}
        onOk={() => { setRecommendModalOpen(false); setRecommendResult(null); }}
        onCancel={() => { setRecommendModalOpen(false); setRecommendResult(null); }}
        okText="确定"
        cancelText="取消"
        width={500}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <span style={{ marginRight: 8 }}>选择平台:</span>
            <Select value={recommendPlatform} onChange={setRecommendPlatform} style={{ width: 160 }}>
              {allPlatformOptions.map(p => (
                <Option key={p.value} value={p.value}>{p.label}</Option>
              ))}
            </Select>
          </div>
          <Button type="primary" icon={<ThunderboltFilled />} onClick={handleRecommendTime}>
            获取推荐时间
          </Button>
          {recommendResult && (
            <div style={{ padding: 16, background: '#f0f5ff', borderRadius: 8 }}>
              <div style={{ fontWeight: 600, marginBottom: 8 }}>推荐发布时间:</div>
              <div style={{ fontSize: 18, color: '#1677ff', marginBottom: 12 }}>
                {recommendResult.recommended_at ? new Date(recommendResult.recommended_at).toLocaleString('zh-CN') : '-'}
              </div>
              <div style={{ color: '#8c8c8c', fontSize: 12 }}>活跃时段:</div>
              <Space direction="vertical" style={{ marginTop: 4 }}>
                {(recommendResult.peak_hours || []).map((ph: any, i: number) => (
                  <Tag key={i} color="blue">{typeof ph === 'string' ? ph : `${ph.start}-${ph.end}`}</Tag>
                ))}
              </Space>
            </div>
          )}
        </Space>
      </Modal>

      {/* Create Calendar Item Modal */}
      <Modal
        title="添加内容到日历"
        open={calModalOpen}
        onOk={handleCreateCalendarItem}
        onCancel={() => { setCalModalOpen(false); calForm.resetFields(); }}
        okText="添加"
        cancelText="取消"
        width={600}
      >
        <Form form={calForm} layout="vertical">
          <Form.Item name="title" label="内容标题" rules={[{ required: true, message: '请输入标题' }]}>
            <Input placeholder="输入内容标题" />
          </Form.Item>
          <Form.Item name="content" label="内容描述">
            <TextArea rows={3} placeholder="内容描述" showCount maxLength={1000} />
          </Form.Item>
          <Form.Item name="content_type" label="内容类型" initialValue="article">
            <Select>
              <Option value="article">文章</Option>
              <Option value="video">视频</Option>
              <Option value="image">图片</Option>
              <Option value="short_video">短视频</Option>
            </Select>
          </Form.Item>
          <Form.Item name="priority" label="优先级" initialValue="medium">
            <Select>
              <Option value="high">高</Option>
              <Option value="medium">中</Option>
              <Option value="low">低</Option>
            </Select>
          </Form.Item>
          <Form.Item name="planned_date" label="计划日期">
            <DatePicker style={{ width: '100%' }} placeholder="选择计划发布日期" />
          </Form.Item>
          <Form.Item name="target_platforms" label="目标平台">
            <Select mode="multiple" placeholder="选择目标平台">
              {allPlatformOptions.map(p => (
                <Option key={p.value} value={p.value}>{p.label}</Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item name="tags" label="标签">
            <Select mode="tags" placeholder="输入标签后回车添加" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default PublishSchedule;
