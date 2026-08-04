import { message } from '../utils/antdMessage';
import React, { useEffect, useState, useRef, useCallback } from 'react';
import { Card, Button, Tag, Space, Modal, Form, Input, Select, notification, Radio, Row, Col, Statistic, Empty, Progress, Spin, Alert, Steps, Tooltip, Tabs, Descriptions, Badge, List, Popover, Popconfirm } from 'antd';
import {
  PlayCircleOutlined, PauseCircleOutlined, DeleteOutlined,
  PlusOutlined, RobotOutlined, ReloadOutlined,
  CheckCircleOutlined, EyeOutlined, RedoOutlined,
  FileTextOutlined, CodeOutlined, StopOutlined, ThunderboltOutlined,
  DownloadOutlined,
} from '@ant-design/icons';
import type { CrawlerTask } from '../types';
import { PLATFORM_MAP } from '../types';
import {
  getTasks, createTask, startTask, pauseTask, deleteTask, deleteTaskComments, retryTask, getTaskDetail, getTaskLogs, updateTaskPromo,
  analyzeUserNeeds, generateAdContent, createOutreachTask, executeOutreachTask, getOutreachStatus,
  startAutoOutreach, getAutoOutreachStatus, listAutoOutreachJobs, getAutoOutreachStats, cancelAutoOutreachJob, retryAutoOutreachJob, getOutreachTaskLogs,
  scanTaskLeads, getTaskLeadsSummary,
} from '../api/tasks';
import { getLeads, exportLeads } from '../api/leads';

const { Option } = Select;

const { TabPane } = Tabs;

// 获客任务面板 - 必须定义在 TaskManager 外部，避免父组件重渲染导致卸载重建
const OutreachJobsPanel: React.FC<{ taskId?: string }> = ({ taskId }) => {
  const [jobsLoading, setJobsLoading] = useState(true);
  const [localJobs, setLocalJobs] = useState<any[]>([]);
  const [localStats, setLocalStats] = useState<any>(null);
  const [fetchError, setFetchError] = useState<string>('');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchJobs = useCallback(async () => {
    try {
      setFetchError('');
      const [jobsRes, statsRes] = await Promise.all([
        taskId ? listAutoOutreachJobs(taskId, 50) : listAutoOutreachJobs('', 50),
        getAutoOutreachStats(),
      ]);
      setLocalJobs(jobsRes.jobs || []);
      setLocalStats(statsRes);
    } catch (err: any) {
      console.error('[OutreachJobsPanel] fetchJobs error:', err);
      setFetchError(err?.message || '获取数据失败');
    } finally {
      setJobsLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    fetchJobs();
    pollRef.current = setInterval(fetchJobs, 8000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [fetchJobs, taskId]);

  const [expandedJob, setExpandedJob] = useState<string | null>(null);
  const [jobDetails, setJobDetails] = useState<Record<string, any>>({});
  const [detailsLoading, setDetailsLoading] = useState<Record<string, boolean>>({});

  const fetchJobDetail = async (job: any) => {
    setDetailsLoading(prev => ({ ...prev, [job.job_id]: true }));
    try {
      const detail = await getAutoOutreachStatus(job.task_id, job.job_id);
      setJobDetails(prev => ({ ...prev, [job.job_id]: detail }));
    } catch (err) {
      console.error('[OutreachJobsPanel] fetchJobDetail error:', err);
    } finally {
      setDetailsLoading(prev => ({ ...prev, [job.job_id]: false }));
    }
  };

  const toggleJobDetail = (job: any) => {
    if (expandedJob === job.job_id) {
      setExpandedJob(null);
    } else {
      setExpandedJob(job.job_id);
      fetchJobDetail(job);
    }
  };

  // 自动刷新运行中任务的详情
  useEffect(() => {
    if (!expandedJob) return;
    const detail = jobDetails[expandedJob];
    if (!detail || detail.status === 'running') {
      const interval = setInterval(() => {
        const job = localJobs.find(j => j.job_id === expandedJob);
        if (job) fetchJobDetail(job);
      }, 5000);
      return () => clearInterval(interval);
    }
  }, [expandedJob, localJobs]);

  const handleCancelJob = async (job: any) => {
    try {
      await cancelAutoOutreachJob(job.task_id, job.job_id);
      message.success('任务已取消');
      fetchJobs();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '取消失败');
    }
  };

  const [retryingJobId, setRetryingJobId] = useState<string | null>(null);

  // 用户详细日志
  const [logModalVisible, setLogModalVisible] = useState(false);
  const [logModalData, setLogModalData] = useState<any>(null);
  const [logModalLoading, setLogModalLoading] = useState(false);

  const showUserLogs = async (result: any) => {
    if (!result.outreach_task_id) {
      message.warning('无详细日志记录');
      return;
    }
    setLogModalVisible(true);
    setLogModalLoading(true);
    setLogModalData(null);
    try {
      const data = await getOutreachTaskLogs(result.outreach_task_id);
      setLogModalData(data);
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '获取日志失败');
    } finally {
      setLogModalLoading(false);
    }
  };

  const handleRetryJob = async (job: any) => {
    try {
      setRetryingJobId(job.job_id);
      const res = await retryAutoOutreachJob(job.task_id, job.job_id);
      message.success(res.message || `正在重试 ${res.retry_count} 个失败任务`);
      fetchJobs();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '重试失败');
    } finally {
      setRetryingJobId(null);
    }
  };

  const formatTime = (ts: number) => {
    if (!ts) return '-';
    return new Date(ts).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  };

  const formatDuration = (startTs: number, endTs: number) => {
    if (!startTs) return '-';
    const diff = ((endTs || Date.now()) - startTs) / 1000;
    if (diff < 60) return `${Math.round(diff)}秒`;
    if (diff < 3600) return `${Math.round(diff / 60)}分钟`;
    return `${(diff / 3600).toFixed(1)}小时`;
  };

  return (
    <div>
      {/* 加载状态 */}
      {jobsLoading && !localStats && (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <Spin description="加载获客任务数据..." />
        </div>
      )}

      {/* 错误提示 */}
      {fetchError && !localStats && (
        <div style={{ textAlign: 'center', padding: 20 }}>
          <Alert type="error" title={fetchError} showIcon style={{ marginBottom: 16 }} />
          <Button type="primary" onClick={() => { setJobsLoading(true); fetchJobs(); }}>重试</Button>
        </div>
      )}

      {/* 统计卡片 */}
      {localStats && (
        <Row gutter={12} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Card size="small" styles={{ body: { padding: '12px 16px' } }}>
              <Statistic title="总发送" value={localStats.total_success + localStats.total_failed} suffix={<span style={{ fontSize: 12, color: '#999' }}>/ {localStats.total_targets}</span>} styles={{ content: { fontSize: 22 } }} />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small" styles={{ body: { padding: '12px 16px' } }}>
              <Statistic title="成功" value={localStats.total_success} styles={{ content: { fontSize: 22, color: '#52c41a' } }} prefix="✅" />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small" styles={{ body: { padding: '12px 16px' } }}>
              <Statistic title="失败" value={localStats.total_failed} styles={{ content: { fontSize: 22, color: '#ff4d4f' } }} prefix="❌" />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small" styles={{ body: { padding: '12px 16px' } }}>
              <Statistic title="成功率" value={localStats.success_rate} suffix="%" styles={{ content: { fontSize: 22, color: localStats.success_rate > 50 ? '#52c41a' : '#faad14' } }} />
            </Card>
          </Col>
        </Row>
      )}

      {/* 今日统计 + 风控状态 */}
      {localStats && (
        <Row gutter={12} style={{ marginBottom: 16 }}>
          <Col span={12}>
            <Card size="small" title="今日统计" styles={{ body: { padding: '8px 16px' } }}>
              <Space size={24}>
                <span>发送: <b>{(localStats.today_success || 0) + (localStats.today_failed || 0)}</b></span>
                <span style={{ color: '#52c41a' }}>成功: <b>{localStats.today_success || 0}</b></span>
                <span style={{ color: '#ff4d4f' }}>失败: <b>{localStats.today_failed || 0}</b></span>
              </Space>
            </Card>
          </Col>
          <Col span={12}>
            <Card size="small" title="风控状态" styles={{ body: { padding: '8px 16px' } }}>
              {localStats.cooldown_remaining > 0 ? (
                <span style={{ color: '#ff4d4f' }}>🔥 冷却中，剩余 {Math.ceil(localStats.cooldown_remaining / 60)} 分钟</span>
              ) : (
                <span style={{ color: '#52c41a' }}>✅ 正常</span>
              )}
              <span style={{ marginLeft: 16 }}>运行中: <b>{localStats.running_count || 0}</b></span>
            </Card>
          </Col>
        </Row>
      )}

      {/* 7天趋势 */}
      {localStats?.daily_stats && localStats.daily_stats.some((d: any) => d.success > 0 || d.failed > 0) && (
        <Card size="small" title="最近7天趋势" style={{ marginBottom: 16 }} styles={{ body: { padding: '8px 16px' } }}>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, height: 80 }}>
            {localStats.daily_stats.map((d: any, i: number) => {
              const maxVal = Math.max(...localStats.daily_stats.map((x: any) => x.success + x.failed), 1);
              const total = d.success + d.failed;
              const heightPct = (total / maxVal) * 60;
              return (
                <div key={i} style={{ flex: 1, textAlign: 'center' }}>
                  <div style={{ fontSize: 11, color: '#52c41a', marginBottom: 2 }}>{d.success || ''}</div>
                  <div style={{ height: Math.max(heightPct, 4), background: `linear-gradient(to top, #52c41a ${d.success / (total || 1) * 100}%, #ff4d4f ${d.success / (total || 1) * 100}%)`, borderRadius: 3, minWidth: 20, margin: '0 auto' }} />
                  <div style={{ fontSize: 11, color: '#999', marginTop: 4 }}>{d.date}</div>
                </div>
              );
            })}
          </div>
        </Card>
      )}

      {/* 任务列表 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontWeight: 600 }}>获客任务列表</span>
        <Button size="small" icon={<ReloadOutlined />} loading={jobsLoading} onClick={() => { setJobsLoading(true); fetchJobs().finally(() => setJobsLoading(false)); }}>刷新</Button>
      </div>
      {localJobs.length === 0 ? (
        <Empty description="暂无获客任务" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <div style={{ maxHeight: 500, overflowY: 'auto' }}>
          {localJobs.map((job: any) => (
            <div key={job.job_id} style={{
              padding: 12, background: job.status === 'running' ? '#e6f7ff' : '#fafafa',
              borderRadius: 8, marginBottom: 8, border: `1px solid ${job.status === 'running' ? '#91d5ff' : job.status === 'completed' ? '#b7eb8f' : '#f0f0f0'}`,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <Space>
                  <Tag color={job.status === 'running' ? 'blue' : job.status === 'completed' ? 'green' : job.status === 'cancelled' ? 'orange' : 'red'}>
                    {job.status === 'running' ? '运行中' : job.status === 'completed' ? '已完成' : job.status === 'cancelled' ? '已取消' : '失败'}
                  </Tag>
                  <span style={{ fontSize: 12, color: '#999' }}>{formatTime(job.created_at)}</span>
                  {job.finished_at > 0 && <span style={{ fontSize: 11, color: '#999' }}>耗时 {formatDuration(job.created_at, job.finished_at)}</span>}
                </Space>
                {job.status === 'running' && (
                  <Button size="small" danger icon={<StopOutlined />} onClick={() => handleCancelJob(job)}>取消</Button>
                )}
                {job.failed > 0 && job.status !== 'running' && (
                  <Button size="small" type="primary" icon={<ReloadOutlined />} loading={retryingJobId === job.job_id} onClick={() => handleRetryJob(job)}>重试失败({job.failed})</Button>
                )}
                {job.failed === 0 && job.completed < job.total && job.status !== 'running' && (
                  <Button size="small" type="primary" icon={<ReloadOutlined />} loading={retryingJobId === job.job_id} onClick={() => handleRetryJob(job)}>重试未完成({job.total - job.completed})</Button>
                )}
              </div>
              <div style={{ marginBottom: 8 }}>
                <Progress
                  percent={job.total > 0 ? Math.round(job.completed / job.total * 100) : 0}
                  size="small"
                  status={job.status === 'running' ? 'active' : job.failed > job.success ? 'exception' : 'success'}
                  format={() => `${job.completed}/${job.total}`}
                />
              </div>
              <Space size={16} style={{ fontSize: 12 }}>
                <span style={{ color: '#52c41a' }}>✅ {job.success}</span>
                <span style={{ color: '#ff4d4f' }}>❌ {job.failed}</span>
                {job.skipped > 0 && <span style={{ color: '#faad14' }}>⏭ {job.skipped}</span>}
                <span style={{ color: '#999' }}>意向: {job.intent_level === 'high' ? '高' : '中'}</span>
                <span style={{ color: '#999' }}>来源: {job.data_source === 'customer_lead' ? '客户线索' : '评论分析'}</span>
              </Space>
              {/* 查看详情按钮 */}
              <div style={{ marginTop: 8, textAlign: 'center' }}>
                <Button
                  type="link"
                  size="small"
                  onClick={() => toggleJobDetail(job)}
                  icon={<EyeOutlined />}
                  loading={detailsLoading[job.job_id]}
                >
                  {expandedJob === job.job_id ? '收起详情' : '查看详情'}
                </Button>
              </div>
              {/* 展开的详情 */}
              {expandedJob === job.job_id && jobDetails[job.job_id] && (
                <div style={{ marginTop: 8, borderTop: '1px dashed #d9d9d9', paddingTop: 8 }}>
                  {jobDetails[job.job_id].results && jobDetails[job.job_id].results.length > 0 ? (
                    <div style={{ maxHeight: 300, overflowY: 'auto' }}>
                      {jobDetails[job.job_id].results.map((r: any, idx: number) => (
                        <div key={idx} style={{
                          padding: '6px 8px', marginBottom: 4, borderRadius: 4,
                          background: r.success ? '#f6ffed' : '#fff2f0',
                          fontSize: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                          cursor: 'pointer',
                        }} onClick={() => showUserLogs(r)}>
                          <Space>
                            <span>{r.success ? '✅' : '❌'}</span>
                            <span style={{ fontWeight: 500 }}>{r.nickname || r.user_id?.slice(0, 8) || '未知'}</span>
                          </Space>
                          <Space size={8}>
                            <span style={{ color: r.success ? '#52c41a' : '#ff4d4f', fontSize: 11, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {r.message || '-'}
                            </span>
                            <FileTextOutlined style={{ color: '#1890ff', fontSize: 13 }} />
                          </Space>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div style={{ textAlign: 'center', color: '#999', fontSize: 12, padding: 8 }}>暂无执行记录</div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* 用户详细日志弹窗 */}
      <Modal
        title={logModalData ? `${logModalData.nickname || '用户'} - 执行日志` : '执行日志'}
        open={logModalVisible}
        onCancel={() => setLogModalVisible(false)}
        footer={null}
        width={600}
      >
        {logModalLoading ? (
          <div style={{ textAlign: 'center', padding: 30 }}><Spin description="加载日志..." /></div>
        ) : logModalData ? (
          <div>
            {/* 基本信息 */}
            <div style={{ marginBottom: 12, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              <Tag color={logModalData.status === 'success' ? 'green' : logModalData.status === 'failed' ? 'red' : 'blue'}>
                {logModalData.status === 'success' ? '成功' : logModalData.status === 'failed' ? '失败' : logModalData.status}
              </Tag>
              <Tag>{logModalData.platform}</Tag>
              {logModalData.error_message && <Tag color="red">{logModalData.error_message}</Tag>}
            </div>

            {/* 执行步骤 */}
            {logModalData.steps && logModalData.steps.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 13 }}>执行步骤</div>
                <Steps
                  size="small"
                  current={logModalData.steps.filter((s: any) => s.status === 'success').length - 1}
                  items={logModalData.steps.map((s: any) => ({
                    title: s.name,
                    status: s.status === 'success' ? 'finish' : s.status === 'failed' ? 'error' : 'process',
                    description: s.message,
                  }))}
                />
              </div>
            )}

            {/* 详细日志 */}
            {logModalData.logs && logModalData.logs.length > 0 && (
              <div>
                <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 13 }}>运行日志</div>
                <div style={{
                  background: '#1e1e1e', color: '#d4d4d4', padding: 12, borderRadius: 6,
                  maxHeight: 300, overflowY: 'auto', fontFamily: 'monospace', fontSize: 12, lineHeight: 1.8,
                }}>
                  {logModalData.logs.map((log: string, idx: number) => (
                    <div key={idx} style={{
                      color: log.includes('✅') || log.includes('🎉') ? '#52c41a' :
                             log.includes('❌') || log.includes('⚠️') ? '#ff4d4f' :
                             log.includes('Step') ? '#1890ff' : '#d4d4d4',
                    }}>
                      {log}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <Empty description="无日志数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}
      </Modal>
    </div>
  );
};

const TaskManager: React.FC = () => {
  const [tasks, setTasks] = useState<CrawlerTask[]>([]);
  const [, setLoading] = useState(false);
  const [modalVisible, setModalVisible] = useState(false);
  const [createStep, setCreateStep] = useState(0);
  const [form] = Form.useForm();
  const [previewData, setPreviewData] = useState<any>(null);

  // 任务详情弹窗状态
  const [detailVisible, setDetailVisible] = useState(false);
  const [detailTask, setDetailTask] = useState<CrawlerTask | null>(null);
  const [detailLogs, setDetailLogs] = useState<any[]>([]);
  const [detailData, setDetailData] = useState<any[]>([]);
  const [detailDataCount, setDetailDataCount] = useState(0);
  const [detailComments, setDetailComments] = useState<any[]>([]);
  const [detailCommentCount, setDetailCommentCount] = useState(0);
  const [commentFilter, setCommentFilter] = useState<string>('all');
  const [commentPageSize, setCommentPageSize] = useState(50);
  const [commentOffset, setCommentOffset] = useState(0);
  const [commentLoadingMore, setCommentLoadingMore] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('info');
  // 任务详情页的线索列表(从 CustomerLead 表分页拉取,支持按意向等级筛选全量数据)
  const [taskLeadsList, setTaskLeadsList] = useState<any[]>([]);
  const [taskLeadsTotal, setTaskLeadsTotal] = useState(0);
  const [taskLeadsPage, setTaskLeadsPage] = useState(1);
  const [taskLeadsLoading, setTaskLeadsLoading] = useState(false);
  // 地域筛选(支持模糊匹配,如"四川"/"巴中")和导出 loading
  const [ipLocationFilter, setIpLocationFilter] = useState<string>('');
  const [exportingLeads, setExportingLeads] = useState(false);
  const [promoEditVisible, setPromoEditVisible] = useState(false);
  const [promoEditLoading, setPromoEditLoading] = useState(false);
  const [promoForm] = Form.useForm();
  const logsIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const logsContainerRef = useRef<HTMLDivElement | null>(null);
  const logsAutoScrollRef = useRef<boolean>(true);
  // 任务线索扫描状态(全量评论意向统计,从 CustomerLead 表查)
  const [leadsSummary, setLeadsSummary] = useState<{ total: number; high_count: number; medium_count: number; low_count: number; scanned: boolean } | null>(null);
  const [scanningLeads, setScanningLeads] = useState(false);

  // 自动化获客弹窗状态
  const [analyzeModalVisible, setAnalyzeModalVisible] = useState(false);
  const [analyzeResult, setAnalyzeResult] = useState<any>(null);
  const [analyzeLoading, setAnalyzeLoading] = useState(false);
  const [selectedUser, setSelectedUser] = useState<any>(null);

  const [contentModalVisible, setContentModalVisible] = useState(false);
  const [contentResult, setContentResult] = useState<any>(null);
  const [contentLoading, setContentLoading] = useState(false);
  const [contentTone, setContentTone] = useState('friendly');

  const [outreachModalVisible, setOutreachModalVisible] = useState(false);
  const [outreachResult, setOutreachResult] = useState<any>(null);
  const [outreachLoading, setOutreachLoading] = useState(false);
  const [outreachLoadingMap, setOutreachLoadingMap] = useState<Record<string, boolean>>({});
  const [outreachStatus, setOutreachStatus] = useState<any>(null);
  const [outreachMethod, setOutreachMethod] = useState<'direct_message' | 'comment_reply'>('direct_message');
  const [replyLoadingMap, setReplyLoadingMap] = useState<Record<string, boolean>>({});
  const outreachStatusRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 自动获客状态
  const [autoOutreachLoading, setAutoOutreachLoading] = useState(false);
  const [autoOutreachJob, setAutoOutreachJob] = useState<any>(null);
  const [autoOutreachModalVisible, setAutoOutreachModalVisible] = useState(false);
  const autoOutreachPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 主页面Tab
  const [mainTab, setMainTab] = useState('crawler');

  // 获客任务列表 & 统计（由 OutreachJobsPanel 内部管理）

  useEffect(() => {
    fetchTasks();
    const interval = setInterval(fetchTasks, 5000);
    return () => clearInterval(interval);
  }, []);

  const fetchTasks = async () => {
    setLoading(true);
    try {
      const res = await getTasks();
      setTasks(res);
    } catch (error) {
      console.error('Failed to fetch tasks:', error);
    } finally {
      setLoading(false);
    }
  };

  const statusColors: Record<string, string> = {
    pending: 'default',
    running: 'processing',
    paused: 'warning',
    completed: 'success',
    failed: 'error',
    cancelled: 'default',
  };

  const statusTexts: Record<string, string> = {
    pending: '待启动',
    running: '运行中',
    paused: '已暂停',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
  };

  const handleCreateTask = async (values: any) => {
    try {
      let keywords: string[];
      if (Array.isArray(values.keywords)) {
        keywords = values.keywords;
      } else if (typeof values.keywords === 'string') {
        keywords = values.keywords.split(/[,，]/).map((k: string) => k.trim()).filter(Boolean);
      } else {
        keywords = [];
      }
      const payload: any = {
        ...values,
        keywords,
        status: 'pending',
        created_ts: Date.now(),
      };
      // 确保 promo_config 是对象格式
      if (values.promo_config) {
        payload.promo_config = values.promo_config;
      }
      await createTask(payload);
      message.success('任务创建成功');
      setModalVisible(false);
      setCreateStep(0);
      setPreviewData(null);
      form.resetFields();
      fetchTasks();
    } catch (error: any) {
      console.error('Create task error:', error);
      message.error(error?.response?.data?.detail || '任务创建失败');
    }
  };

  const handleStart = async (taskId: string) => {
    try {
      const res = await startTask(taskId);
      if (res.success) {
        message.success('任务已启动');
        fetchTasks();
      } else {
        message.error(res.message || '启动失败');
      }
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '启动失败');
    }
  };

  const handlePause = async (taskId: string) => {
    try {
      await pauseTask(taskId);
      message.success('任务已暂停');
      fetchTasks();
    } catch (error) {
      message.error('暂停失败');
    }
  };

  const handleDelete = async (taskId: string) => {
    try {
      await deleteTask(taskId);
      message.success('任务已删除');
      fetchTasks();
    } catch (error) {
      message.error('删除失败');
    }
  };

  const handleRetry = async (taskId: string) => {
    try {
      await retryTask(taskId);
      message.success('任务已重启');
      fetchTasks();
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '重启失败');
    }
  };

  // 查看任务详情
  const handleViewDetail = async (task: CrawlerTask) => {
    setDetailTask(task);
    setDetailVisible(true);
    setDetailLoading(true);
    setActiveTab('info');
    setCommentOffset(0);
    setLeadsSummary(null);
    try {
      const res = await getTaskDetail(task.id, 0, 100);
      setDetailTask(res.task);
      setDetailLogs(res.logs || []);
      setDetailData(res.data || []);
      setDetailDataCount(res.data_count || 0);
      setDetailComments(res.comments || []);
      setDetailCommentCount(res.comment_count || 0);
      setCommentOffset(res.comments?.length || 0);
      // 拉取线索统计(全量扫描结果)
      try {
        const summary = await getTaskLeadsSummary(task.id);
        setLeadsSummary(summary);
      } catch (e) {
        console.warn('Failed to fetch leads summary:', e);
      }
      // 拉取第一页线索列表(从 CustomerLead 表,支持全量筛选)
      fetchTaskLeads(task.id, 'all', 1, true);
    } catch (error) {
      console.error('Failed to fetch task detail:', error);
      message.error('获取任务详情失败');
    } finally {
      setDetailLoading(false);
    }
  };

  // 加载更多评论
  const handleLoadMoreComments = async () => {
    if (!detailTask) return;
    setCommentLoadingMore(true);
    try {
      const res = await getTaskDetail(detailTask.id, commentOffset, 100);
      setDetailComments(prev => [...prev, ...(res.comments || [])]);
      setCommentOffset(prev => prev + (res.comments?.length || 0));
      setDetailCommentCount(res.comment_count || 0);
    } catch (error) {
      console.error('Failed to load more comments:', error);
      message.error('加载更多评论失败');
    } finally {
      setCommentLoadingMore(false);
    }
  };

  // 打开推广配置编辑
  const handleOpenPromoEdit = (task: CrawlerTask) => {
    setDetailTask(task);
    promoForm.setFieldsValue({
      product_name: task.promo_config?.product_name || 'AI聚合平台',
      product_desc: task.promo_config?.product_desc || '一站式AI工具平台，集成ChatGPT、Claude、Gemini等主流大模型',
      promo_link: task.promo_config?.promo_link || '',
      contact_wechat: task.promo_config?.contact_wechat || '',
      price_info: task.promo_config?.price_info || '',
      discount_info: task.promo_config?.discount_info || '',
      free_quota: task.promo_config?.free_quota || '',
      solution_desc: task.promo_config?.solution_desc || '',
    });
    setPromoEditVisible(true);
  };

  // 保存推广配置
  const handleSavePromo = async (values: any) => {
    if (!detailTask) return;
    setPromoEditLoading(true);
    try {
      const res = await updateTaskPromo(detailTask.id, { promo_config: values });
      if (res.success) {
        message.success('推广配置已更新');
        setPromoEditVisible(false);
        // 刷新任务列表和详情
        fetchTasks();
        if (detailVisible) {
          const detailRes = await getTaskDetail(detailTask.id);
          setDetailTask(detailRes.task);
        }
      } else {
        message.error(res.message || '更新失败');
      }
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '更新失败');
    } finally {
      setPromoEditLoading(false);
    }
  };

  // 关闭详情弹窗
  const handleCloseDetail = () => {
    setDetailVisible(false);
    setDetailTask(null);
    setDetailLogs([]);
    setDetailData([]);
    setDetailDataCount(0);
    setDetailComments([]);
    setDetailCommentCount(0);
    setTaskLeadsList([]);
    setTaskLeadsTotal(0);
    setTaskLeadsPage(1);
    setIpLocationFilter('');
    setLeadsSummary(null);
    setActiveTab('info');
    if (logsIntervalRef.current) {
      clearInterval(logsIntervalRef.current);
      logsIntervalRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  };

  // ========== 自动化获客功能 ==========

  // 1. 分析用户需求（保留供将来使用）
  // @ts-ignore
  const _handleAnalyzeNeed = useCallback(async (user: any) => {
    console.log('[handleAnalyzeNeed] ====== START ======');
    console.log('[handleAnalyzeNeed] Called with user:', user);
    console.log('[handleAnalyzeNeed] detailTask:', detailTask);
    try {
      if (!detailTask) {
        message.error('请先选择任务');
        return;
      }
      if (!user) {
        message.error('用户信息无效');
        return;
      }
      const uid = user.user_id || user.id || '';
      if (!uid) {
        message.error('用户ID为空，无法分析');
        return;
      }
      setSelectedUser(user);
      setAnalyzeLoading(true);
      setAnalyzeModalVisible(true);
      setAnalyzeResult(null);
      console.log('[handleAnalyzeNeed] Modal should be open now, calling API with uid:', uid);
      const res = await analyzeUserNeeds(detailTask.id, {
        user_ids: [uid],
        max_users: 1,
      });
      console.log('[handleAnalyzeNeed] API response:', res);
      if (res.results && res.results.length > 0) {
        setAnalyzeResult(res.results[0]);
      } else {
        message.warning('未分析到需求，请检查用户数据');
      }
    } catch (error: any) {
      console.error('Analyze need error:', error);
      message.error(error?.response?.data?.detail || '需求分析失败');
    } finally {
      setAnalyzeLoading(false);
      console.log('[handleAnalyzeNeed] ====== END ======');
    }
  }, [detailTask]);

  // 批量分析需求 - 对当前筛选的所有高/中意向用户进行分析
  const handleBatchAnalyze = useCallback(async () => {
    if (!detailTask) return;
    const filtered = commentFilter === 'all' ? detailComments :
      commentFilter === 'high' ? detailComments.filter((c: any) => c.value_level === '高') :
      commentFilter === 'medium' ? detailComments.filter((c: any) => c.value_level === '中') :
      detailComments.filter((c: any) => c.value_level === '低');
    const targetUsers = filtered.filter((c: any) => c.value_level === '高' || c.value_level === '中').slice(0, 20);
    if (targetUsers.length === 0) {
      message.warning('没有高/中意向用户可分析');
      return;
    }
    setAnalyzeLoading(true);
    setAnalyzeModalVisible(true);
    setAnalyzeResult(null);
    message.info(`正在批量分析 ${targetUsers.length} 个用户的需求...`);
    try {
      const res = await analyzeUserNeeds(detailTask.id, {
        user_ids: targetUsers.map((u: any) => u.user_id || u.id || ''),
        max_users: targetUsers.length,
      });
      if (res.results && res.results.length > 0) {
        setAnalyzeResult({
          batch: true,
          count: res.results.length,
          results: res.results,
          summary: `已分析 ${res.results.length} 个用户需求`,
        });
        message.success(`成功分析 ${res.results.length} 个用户需求`);
      } else {
        message.warning('未分析到需求');
      }
    } catch (error: any) {
      console.error('Batch analyze error:', error);
      message.error(error?.response?.data?.detail || '批量分析失败');
    } finally {
      setAnalyzeLoading(false);
    }
  }, [detailTask, commentFilter, detailComments]);

  // 批量生成文案 - 为当前筛选的高/中意向用户生成广告文案
  const handleBatchGenerateCopy = async () => {
    if (!detailTask) return;
    const filtered = commentFilter === 'all' ? detailComments :
      commentFilter === 'high' ? detailComments.filter((c: any) => c.value_level === '高') :
      commentFilter === 'medium' ? detailComments.filter((c: any) => c.value_level === '中') :
      detailComments.filter((c: any) => c.value_level === '低');
    const targetUsers = filtered.filter((c: any) => c.value_level === '高' || c.value_level === '中').slice(0, 20);
    if (targetUsers.length === 0) {
      message.warning('没有高/中意向用户可生成文案');
      return;
    }
    setContentLoading(true);
    setContentModalVisible(true);
    setContentResult(null);
    message.info(`正在批量生成 ${targetUsers.length} 个用户的文案...`);
    try {
      const res = await generateAdContent(detailTask.id, {
        user_ids: targetUsers.map((u: any) => u.user_id),
        content_type: 'direct_message',
        tone: contentTone,
      });
      if (res.contents && res.contents.length > 0) {
        setContentResult({
          batch: true,
          count: res.contents.length,
          contents: res.contents,
          summary: `已生成 ${res.contents.length} 条文案`,
        });
        message.success(`成功生成 ${res.contents.length} 条文案`);
      } else {
        message.warning('未生成文案');
      }
    } catch (error: any) {
      console.error('Batch generate error:', error);
      message.error(error?.response?.data?.detail || '批量生成文案失败');
    } finally {
      setContentLoading(false);
    }
  };

  // 一键自动获客
  const handleAutoOutreach = async () => {
    if (!detailTask) return;
    const intentLevel = commentFilter === 'high' ? 'high' : commentFilter === 'medium' ? 'medium' : 'high';
    const intentCount = intentLevel === 'high'
      ? detailComments.filter((c: any) => c.value_level === '高').length
      : detailComments.filter((c: any) => c.value_level === '高' || c.value_level === '中').length;
    if (intentCount === 0) {
      message.warning('没有符合条件的意向用户，无法启动自动获客');
      return;
    }
    setAutoOutreachLoading(true);
    setAutoOutreachModalVisible(true);
    setAutoOutreachJob(null);
    try {
      const res = await startAutoOutreach(detailTask.id, {
        intent_level: intentLevel,
        max_users: intentCount,
        tone: contentTone,
        auto_send: true,
        interval_seconds: 90,
        method: outreachMethod,
      });
      if (res.job_id) {
        setAutoOutreachJob(res);
        message.success(res.message);
        // 开始轮询状态（后台运行，关闭弹窗不影响）
        if (autoOutreachPollRef.current) clearInterval(autoOutreachPollRef.current);
        autoOutreachPollRef.current = setInterval(async () => {
          try {
            const status = await getAutoOutreachStatus(detailTask.id, res.job_id);
            setAutoOutreachJob((prev: any) => ({ ...prev, ...status }));
            if (status.status === 'completed' || status.status === 'no_targets') {
              if (autoOutreachPollRef.current) clearInterval(autoOutreachPollRef.current);
              autoOutreachPollRef.current = null;
              notification.success({
                message: '自动获客完成',
                description: `成功 ${status.success}，失败 ${status.failed}，总计 ${status.total}`,
                duration: 6,
              });
            }
          } catch { /* ignore */ }
        }, 5000);
        // 3秒后自动关闭弹窗，转为后台运行
        setTimeout(() => {
          setAutoOutreachModalVisible(false);
          setMainTab('outreach'); // 切换到获客任务Tab查看进度
        }, 3000);
      } else {
        message.warning(res.message || '未找到符合条件的用户');
        setAutoOutreachModalVisible(false);
      }
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '启动自动获客失败');
      setAutoOutreachModalVisible(false);
    } finally {
      setAutoOutreachLoading(false);
    }
  };

  // 2. 生成广告文案
  const handleGenerateContent = async () => {
    if (!detailTask || !selectedUser) return;
    setContentLoading(true);
    setContentModalVisible(true);
    setContentResult(null);
    try {
      const res = await generateAdContent(detailTask.id, {
        user_ids: [selectedUser.user_id],
        content_type: 'direct_message',
        tone: contentTone,
      });
      if (res.contents && res.contents.length > 0) {
        setContentResult(res.contents[0]);
      } else {
        message.warning('未生成文案，请检查用户数据');
      }
    } catch (error: any) {
      console.error('Generate content error:', error);
      message.error(error?.response?.data?.detail || '文案生成失败');
    } finally {
      setContentLoading(false);
    }
  };

  // 3. 创建触达任务
  const handleCreateOutreach = async () => {
    if (!detailTask || !selectedUser || !contentResult) return;
    setOutreachLoading(true);
    setOutreachModalVisible(true);
    setOutreachResult(null);
    setOutreachStatus(null);
    try {
      const content = outreachMethod === 'comment_reply' 
        ? (contentResult.comment_reply || contentResult.direct_message || '')
        : (contentResult.direct_message || '');
      const res = await createOutreachTask(detailTask.id, {
        user_id: selectedUser.user_id,
        sec_uid: selectedUser.sec_uid || '',
        platform: detailTask.platform,
        method: outreachMethod,
        content: content,
        nickname: selectedUser.author || selectedUser.nickname || '',
        note_id: selectedUser.aweme_id || selectedUser.note_id || '',
        comment_id: selectedUser.comment_id || selectedUser.id || '',
        require_confirm: true,
      });
      setOutreachResult(res);
      message.success('触达任务已创建');
    } catch (error: any) {
      console.error('Create outreach error:', error);
      message.error(error?.response?.data?.detail || '创建触达任务失败');
    } finally {
      setOutreachLoading(false);
    }
  };

  // 4. 执行触达任务 - 自动发送私信
  const handleExecuteOutreach = async () => {
    if (!detailTask || !outreachResult) return;
    setOutreachLoading(true);
    try {
      const res = await executeOutreachTask(detailTask.id, outreachResult.task_id);
      message.success('自动化触达已启动');
      setOutreachResult({ ...outreachResult, ...res });
      // 开始轮询状态
      startOutreachStatusPolling(detailTask.id, outreachResult.task_id);
    } catch (error: any) {
      console.error('Execute outreach error:', error);
      message.error(error?.response?.data?.detail || '执行触达任务失败');
    } finally {
      setOutreachLoading(false);
    }
  };

  // 轮询触达任务状态
  const startOutreachStatusPolling = (taskId: string, outreachId: string) => {
    if (outreachStatusRef.current) {
      clearInterval(outreachStatusRef.current);
    }
    const poll = async () => {
      try {
        const status = await getOutreachStatus(taskId, outreachId);
        setOutreachStatus(status);
        // 如果任务已完成或失败，停止轮询
        if (status.status === 'success' || status.status === 'failed') {
          if (outreachStatusRef.current) {
            clearInterval(outreachStatusRef.current);
            outreachStatusRef.current = null;
          }
          if (status.status === 'success') {
            message.success('私信发送成功！');
          } else {
            message.error(`私信发送失败: ${status.error_message || '未知错误'}`);
          }
        }
      } catch (e) {
        console.error('Poll status error:', e);
      }
    };
    poll(); // 立即执行一次
    outreachStatusRef.current = setInterval(poll, 2000);
  };

  // 清理轮询
  useEffect(() => {
    return () => {
      if (outreachStatusRef.current) {
        clearInterval(outreachStatusRef.current);
      }
    };
  }, []);

  // 加载任务日志
  const fetchTaskLogs = async (taskId: string) => {
    try {
      const res = await getTaskLogs(taskId, 200);
      setDetailLogs(res.logs || []);
      // 自动滚动到底部(仅在用户未手动上滚时)
      setTimeout(() => {
        if (logsAutoScrollRef.current && logsContainerRef.current) {
          const container = logsContainerRef.current;
          container.scrollTop = container.scrollHeight;
        }
      }, 50);
    } catch (error) {
      console.error('Failed to fetch task logs:', error);
    }
  };

  // 扫描任务全部评论,按任务上下文评分,写入 CustomerLead 表
  const handleScanLeads = async () => {
    if (!detailTask) return;
    setScanningLeads(true);
    try {
      const res = await scanTaskLeads(detailTask.id);
      message.success(res.message || `扫描完成: ${res.scanned} 条评论`);
      // 刷新线索统计:从数据库查实际总数,而非用扫描结果(增量扫描时 res.saved 可能是 0,
      // 但数据库里仍有历史线索,直接用扫描结果会导致统计显示 0)
      try {
        const summary = await getTaskLeadsSummary(detailTask.id);
        setLeadsSummary({
          total: summary.total,
          high_count: summary.high_count,
          medium_count: summary.medium_count,
          low_count: summary.low_count,
          scanned: true,
        });
      } catch (e) {
        // 统计接口失败时回退到扫描结果
        setLeadsSummary({
          total: res.saved,
          high_count: res.high_count,
          medium_count: res.medium_count,
          low_count: res.low_count,
          scanned: true,
        });
      }
      // 扫描后自动加载第一页线索列表(按当前筛选器)
      fetchTaskLeads(detailTask.id, commentFilter, 1, true);
    } catch (error: any) {
      console.error('Failed to scan leads:', error);
      message.error(error?.response?.data?.detail || '扫描失败');
    } finally {
      setScanningLeads(false);
    }
  };

  // 从 CustomerLead 表分页拉取线索(支持按意向等级筛选全量数据,不受评论100条分页限制)
  const fetchTaskLeads = async (taskId: string, filter: string, page: number, reset: boolean = false, ipLocation?: string) => {
    setTaskLeadsLoading(true);
    try {
      const params: any = {
        task_id: taskId,
        page,
        page_size: 50,
      };
      if (filter === 'high') params.level = 'high';
      else if (filter === 'medium') params.level = 'medium';
      else if (filter === 'low') params.level = 'low';
      const ipLoc = (ipLocation !== undefined ? ipLocation : ipLocationFilter).trim();
      if (ipLoc) params.ip_location = ipLoc;
      const res = await getLeads(params);
      if (reset || page === 1) {
        setTaskLeadsList(res.items || []);
      } else {
        setTaskLeadsList(prev => [...prev, ...(res.items || [])]);
      }
      setTaskLeadsTotal(res.total || 0);
      setTaskLeadsPage(page);
    } catch (error) {
      console.error('Failed to fetch task leads:', error);
    } finally {
      setTaskLeadsLoading(false);
    }
  };

  // 加载更多线索(下一页)
  const handleLoadMoreLeads = () => {
    if (!detailTask) return;
    fetchTaskLeads(detailTask.id, commentFilter, taskLeadsPage + 1, false);
  };

  // 筛选器切换:从 CustomerLead 表重新拉取
  const handleCommentFilterChange = (v: string) => {
    setCommentFilter(v);
    setCommentPageSize(50);
    if (detailTask) {
      fetchTaskLeads(detailTask.id, v, 1, true);
    }
  };

  // 地域筛选输入框回车触发
  const handleIpLocationSearch = (v: string) => {
    setIpLocationFilter(v);
    if (detailTask) {
      fetchTaskLeads(detailTask.id, commentFilter, 1, true, v);
    }
  };

  // 导出当前筛选结果为 Excel
  const handleExportLeads = async () => {
    if (!detailTask) return;
    if (taskLeadsTotal === 0) {
      message.warning('当前筛选下没有可导出的线索');
      return;
    }
    setExportingLeads(true);
    try {
      const params: any = { task_id: detailTask.id };
      if (commentFilter === 'high') params.level = 'high';
      else if (commentFilter === 'medium') params.level = 'medium';
      else if (commentFilter === 'low') params.level = 'low';
      if (ipLocationFilter.trim()) params.ip_location = ipLocationFilter.trim();
      const blob = await exportLeads(params);
      // 触发浏览器下载
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `线索导出_${detailTask.name || detailTask.id}_${commentFilter}_${ipLocationFilter || '全部'}_${taskLeadsTotal}条.xlsx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
      message.success(`已导出 ${taskLeadsTotal} 条线索`);
    } catch (error: any) {
      console.error('Failed to export leads:', error);
      message.error(error?.message || '导出失败');
    } finally {
      setExportingLeads(false);
    }
  };

  // Tab 切换时处理日志轮询和WebSocket
  const handleTabChange = (tab: string) => {
    setActiveTab(tab);
    if (tab === 'logs' && detailTask) {
      // 重置自动滚动标志
      logsAutoScrollRef.current = true;
      fetchTaskLogs(detailTask.id);
      // 启动定时轮询(每 3 秒拉最新日志),无论任务是否在运行都轮询
      if (logsIntervalRef.current) {
        clearInterval(logsIntervalRef.current);
      }
      logsIntervalRef.current = setInterval(() => {
        if (detailTask) {
          fetchTaskLogs(detailTask.id);
        }
      }, 3000);
      // 如果任务正在运行，启动WebSocket实时日志
      if (detailTask.status === 'running') {
        connectWebSocketLogs();
      }
    } else {
      if (logsIntervalRef.current) {
        clearInterval(logsIntervalRef.current);
        logsIntervalRef.current = null;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    }
  };

  // 连接WebSocket接收实时日志
  const connectWebSocketLogs = () => {
    if (wsRef.current) return;
    
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/ws/logs`;
    
    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      
      ws.onopen = () => {
        console.log('[WS] Log connection opened');
      };
      
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data && data.message) {
            setDetailLogs(prev => {
              const newLogs = [...prev, {
                time: Date.now(),
                level: data.level || 'info',
                message: data.message,
              }];
              return newLogs.slice(-500);
            });
          }
        } catch (e) {
          // ignore non-JSON messages like ping/pong
        }
      };
      
      ws.onerror = (err) => {
        console.error('[WS] Log connection error:', err);
      };
      
      ws.onclose = () => {
        console.log('[WS] Log connection closed');
        wsRef.current = null;
      };
    } catch (e) {
      console.error('[WS] Failed to connect:', e);
    }
  };

  const nextStep = () => {
    if (createStep === 0) {
      const platform = form.getFieldValue('platform');
      const name = form.getFieldValue('name');
      if (!platform || !name) {
        message.warning('请选择平台并输入任务名称');
        return;
      }
    }
    if (createStep === 1) {
      const keywords = form.getFieldValue('keywords');
      if (!keywords) {
        message.warning('请输入关键词');
        return;
      }
      // 直接进入预览步骤(推广配置已默认填充)
      const values = form.getFieldsValue();
      setPreviewData({
        platform: values.platform,
        name: values.name,
        keywords: typeof values.keywords === 'string'
          ? values.keywords.split(/[,，]/).map((k: string) => k.trim()).filter(Boolean)
          : values.keywords,
        crawl_type: values.crawl_type || 'search',
        max_notes: values.max_notes || 50000,
        promo_config: values.promo_config || {},
      });
    }
    setCreateStep(createStep + 1);
  };

  const prevStep = () => setCreateStep(createStep - 1);

  // 平台图标映射（统一使用通用图标，避免平台识别）
  const platformIcons: Record<string, string> = {
    xhs: '📱',
    douyin: '📱',
    dy: '📱',
    kuaishou: '📱',
    bilibili: '📱',
    weibo: '📱',
    zhihu: '📱',
    tieba: '📱',
  };

  return (
    <div>
      <Tabs activeKey={mainTab} onChange={setMainTab} style={{ marginBottom: 0 }}>
        <TabPane tab="采集任务" key="crawler">
          {/* 统计卡片 */}
          <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small" hoverable>
            <Statistic title="总任务" value={tasks.length} prefix={<RobotOutlined />} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" hoverable>
            <Statistic title="运行中" value={tasks.filter(t => t.status === 'running').length} styles={{ content: { color: '#52c41a' } }} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" hoverable>
            <Statistic title="已完成" value={tasks.filter(t => t.status === 'completed').length} styles={{ content: { color: '#1890ff' } }} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small" hoverable>
            <Statistic title="失败" value={tasks.filter(t => t.status === 'failed').length} styles={{ content: { color: '#f5222d' } }} />
          </Card>
        </Col>
      </Row>

      {/* 任务卡片列表 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h3 style={{ margin: 0 }}>获客任务</h3>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={fetchTasks}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => { setModalVisible(true); setCreateStep(0); form.resetFields(); }}>
            新建任务
          </Button>
        </Space>
      </div>

      {tasks.length === 0 ? (
        <Empty description="暂无任务，点击右上角创建">
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalVisible(true)}>
            创建第一个任务
          </Button>
        </Empty>
      ) : (
        <Row gutter={[16, 16]}>
          {tasks.map(task => (
            <Col xs={24} sm={12} lg={8} key={task.id}>
              <Card
                hoverable
                onClick={() => handleViewDetail(task)}
                actions={[
                  <Tooltip title="查看详情"><Button type="text" icon={<EyeOutlined />} onClick={(e) => { e.stopPropagation(); handleViewDetail(task); }}>详情</Button></Tooltip>,
                  task.status === 'running' ? (
                    <Tooltip title="暂停"><Button type="text" icon={<PauseCircleOutlined />} onClick={(e) => { e.stopPropagation(); handlePause(task.id); }}>暂停</Button></Tooltip>
                  ) : (
                    <Tooltip title="启动"><Button type="text" icon={<PlayCircleOutlined />} onClick={(e) => { e.stopPropagation(); handleStart(task.id); }}>启动</Button></Tooltip>
                  ),
                  <Tooltip title={task.status !== 'running' && task.status !== 'pending' ? '重启' : ''}>
                    <Button
                      type="text"
                      icon={<RedoOutlined />}
                      disabled={task.status === 'running' || task.status === 'pending'}
                      onClick={(e) => { e.stopPropagation(); if (task.status !== 'running' && task.status !== 'pending') handleRetry(task.id); }}
                    >
                      重启
                    </Button>
                  </Tooltip>,
                  <Tooltip title="删除"><Button type="text" danger icon={<DeleteOutlined />} onClick={(e) => { e.stopPropagation(); handleDelete(task.id); }}>删除</Button></Tooltip>,
                ]}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
                  <div>
                    <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 4 }}>{task.name}</div>
                    <div style={{ fontSize: 13, color: '#666' }}>
                      {platformIcons[task.platform] || '📱'} {PLATFORM_MAP[task.platform] || task.platform}
                      {' · '}
                      {task.keywords?.slice(0, 2).join(', ')}
                      {task.keywords?.length > 2 && ` +${task.keywords.length - 2}`}
                    </div>
                  </div>
                  <Tag color={statusColors[task.status]}>{statusTexts[task.status]}</Tag>
                </div>

                {/* 数据指标快速展示 */}
                <div style={{ display: 'flex', gap: 12, marginBottom: 12, padding: '8px 0', borderTop: '1px solid #f0f0f0', borderBottom: '1px solid #f0f0f0' }}>
                  <div style={{ textAlign: 'center', flex: 1 }}>
                    <div style={{ fontSize: 18, fontWeight: 700, color: '#1677ff' }}>{task.total_crawled || 0}</div>
                    <div style={{ fontSize: 11, color: '#999' }}>📊 采集内容</div>
                  </div>
                  <div style={{ width: 1, background: '#f0f0f0' }} />
                  <div style={{ textAlign: 'center', flex: 1 }}>
                    <div style={{ fontSize: 18, fontWeight: 700, color: '#52c41a' }}>{task.comment_count || 0}</div>
                    <div style={{ fontSize: 11, color: '#999' }}>💬 评论获客</div>
                  </div>
                  <div style={{ width: 1, background: '#f0f0f0' }} />
                  <div style={{ textAlign: 'center', flex: 1 }}>
                    <div style={{ fontSize: 18, fontWeight: 700, color: '#fa8c16' }}>{task.total_leads || 0}</div>
                    <div style={{ fontSize: 11, color: '#999' }}>🎯 已获客</div>
                  </div>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, color: '#999' }}>
                  <span>{new Date(task.created_ts).toLocaleDateString()}</span>
                  <span>{task.status === 'running' ? '🟢 运行中' : task.status === 'paused' ? '⏸️ 已暂停' : task.status === 'completed' ? '✅ 已完成' : '⏳ 待启动'}</span>
                </div>
              </Card>
            </Col>
          ))}
        </Row>
      )}

        </TabPane>
        <TabPane tab={<span><ThunderboltOutlined /> 获客任务</span>} key="outreach">
          <OutreachJobsPanel />
        </TabPane>
      </Tabs>

      {/* 新建任务向导 */}
      <Modal
        title="新建获客任务"
        open={modalVisible}
        onCancel={() => { setModalVisible(false); setCreateStep(0); form.resetFields(); }}
        mask={{ closable: false }}
        width={600}
        footer={null}
        destroyOnHidden
      >
        <Steps
          current={createStep}
          size="small"
          style={{ marginBottom: 24 }}
          items={[
            { title: '选择平台' },
            { title: '配置关键词' },
            { title: '确认启动' },
          ]}
        />

        <Form form={form} layout="vertical" onFinish={handleCreateTask}>
          {createStep === 0 && (
            <div>
              <Form.Item name="platform" label="你想从哪里获客？" rules={[{ required: true, message: '请选择平台' }]}>
                <Select placeholder="选择平台" size="large">
                  {Object.entries(PLATFORM_MAP).filter(([key]) => ['dy', 'xhs', 'ks', 'bili', 'wb', 'zhihu', 'tieba'].includes(key)).map(([key, label]) => (
                    <Option key={key} value={key}>
                      <span style={{ fontSize: 18, marginRight: 8 }}>{platformIcons[key] || '📱'}</span>
                      {label}
                    </Option>
                  ))}
                </Select>
              </Form.Item>

              <Form.Item name="name" label="任务名称" rules={[{ required: true, message: '请输入任务名称' }]}>
                <Input placeholder="例如：AI工具获客监控" size="large" />
              </Form.Item>

              <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <Button type="primary" onClick={nextStep}>下一步</Button>
              </div>
            </div>
          )}

          {createStep === 1 && (
            <div>
              <Form.Item name="keywords" label="你想找什么样的客户？" rules={[{ required: true, message: '请输入关键词' }]}>
                <Input.TextArea
                  placeholder="输入关键词，用逗号分隔。例如：AI工具, 聚合平台, ChatGPT"
                  rows={3}
                  size="large"
                />
              </Form.Item>

              <Form.Item name="crawl_type" label="获客方式" initialValue="search">
                <Radio.Group>
                  <Radio.Button value="search">🔍 关键词搜索</Radio.Button>
                  <Radio.Button value="creator">👤 创作者主页</Radio.Button>
                  <Radio.Button value="trending">🔥 热门内容</Radio.Button>
                </Radio.Group>
              </Form.Item>

              <Form.Item name="max_notes" hidden initialValue={50000}><Input type="number" /></Form.Item>
              <div style={{ padding: 12, background: '#f6ffed', borderRadius: 8, marginBottom: 16 }}>
                <div style={{ fontSize: 13, color: '#52c41a' }}>♾️ 获客数量不限，系统会尽可能多地采集数据</div>
              </div>

              <Form.Item name="publish_time_type" label="内容时间范围" initialValue={14}>
                <Radio.Group>
                  <Radio.Button value={0}>不限</Radio.Button>
                  <Radio.Button value={7}>最近一周</Radio.Button>
                  <Radio.Button value={14}>最近两周</Radio.Button>
                  <Radio.Button value={180}>最近半年</Radio.Button>
                </Radio.Group>
              </Form.Item>

              {/* 推广配置折叠(简化向导,默认填充,可选展开) */}
              <Form.Item name={['promo_config', 'product_name']} hidden initialValue="AI聚合平台"><Input /></Form.Item>
              <Form.Item name={['promo_config', 'product_desc']} hidden initialValue="一站式AI工具平台，集成ChatGPT、Claude、Gemini等主流大模型"><Input /></Form.Item>

              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <Button onClick={prevStep}>上一步</Button>
                <Button type="primary" onClick={nextStep}>下一步</Button>
              </div>
            </div>
          )}

          {createStep === 2 && previewData && (
            <div>
              {/* 隐藏的表单字段，确保提交时有值 */}
              <Form.Item name="platform" hidden><Input /></Form.Item>
              <Form.Item name="name" hidden><Input /></Form.Item>
              <Form.Item name="keywords" hidden><Input /></Form.Item>
              <Form.Item name="crawl_type" hidden><Input /></Form.Item>
              <Form.Item name="max_notes" hidden><Input type="number" /></Form.Item>

              <div style={{ padding: 16, background: '#f6ffed', borderRadius: 8, marginBottom: 16 }}>
                <h4 style={{ margin: '0 0 12px' }}>📋 任务预览</h4>
                <div style={{ fontSize: 14, lineHeight: 2 }}>
                  <div><strong>平台：</strong>{PLATFORM_MAP[previewData.platform] || previewData.platform}</div>
                  <div><strong>关键词：</strong>{previewData.keywords?.join(', ')}</div>
                  <div><strong>获客方式：</strong>{previewData.crawl_type === 'search' ? '关键词搜索' : previewData.crawl_type === 'creator' ? '创作者主页' : '热门内容'}</div>
                  <div><strong>获客数量：</strong>♾️ 不限（尽可能多爬）</div>
                  <div><strong>预计耗时：</strong>取决于关键词热度</div>
                </div>
              </div>

              {previewData.promo_config && (
                <div style={{ padding: 16, background: '#fff7e6', borderRadius: 8, marginBottom: 16 }}>
                  <h4 style={{ margin: '0 0 12px' }}>🎯 推广信息</h4>
                  <div style={{ fontSize: 14, lineHeight: 2 }}>
                    <div><strong>产品：</strong>{previewData.promo_config.product_name || '-'}</div>
                    <div><strong>链接：</strong>{previewData.promo_config.promo_link || '-'}</div>
                    <div><strong>微信：</strong>{previewData.promo_config.contact_wechat || '-'}</div>
                    <div><strong>价格：</strong>{previewData.promo_config.price_info || '-'}</div>
                  </div>
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <Button onClick={prevStep}>上一步</Button>
                <Space>
                  <Button onClick={() => { setModalVisible(false); setCreateStep(0); form.resetFields(); }}>保存草稿</Button>
                  <Button type="primary" htmlType="submit" icon={<CheckCircleOutlined />}>立即启动</Button>
                </Space>
              </div>
            </div>
          )}
        </Form>
      </Modal>

      {/* 任务详情弹窗 */}
      <Modal
        title={
          <Space>
            <FileTextOutlined />
            <span>任务详情</span>
            {detailTask && (
              <Tag color={statusColors[detailTask.status]}>{statusTexts[detailTask.status]}</Tag>
            )}
          </Space>
        }
        open={detailVisible}
        onCancel={handleCloseDetail}
        mask={{ closable: false }}
        width={800}
        footer={[
          <Button key="close" onClick={handleCloseDetail}>关闭</Button>,
        ]}
        destroyOnHidden
      >
        {detailLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}>加载中...</div>
        ) : detailTask ? (
          <Tabs activeKey={activeTab} onChange={handleTabChange}>
            <TabPane tab="任务信息" key="info">
              <Descriptions bordered column={2} size="small">
                <Descriptions.Item label="任务ID">{detailTask.id}</Descriptions.Item>
                <Descriptions.Item label="任务名称">{detailTask.name}</Descriptions.Item>
                <Descriptions.Item label="平台">
                  {platformIcons[detailTask.platform] || '📱'} {PLATFORM_MAP[detailTask.platform] || detailTask.platform}
                </Descriptions.Item>
                <Descriptions.Item label="获客方式">
                  {detailTask.crawl_type === 'search' ? '🔍 关键词搜索' : detailTask.crawl_type === 'creator' ? '👤 创作者主页' : '🔥 热门内容'}
                </Descriptions.Item>
                <Descriptions.Item label="关键词" span={2}>
                  {detailTask.keywords?.join(', ')}
                </Descriptions.Item>
                <Descriptions.Item label="数据类型" span={2}>
                  {detailTask.data_types?.join(', ')}
                </Descriptions.Item>
                <Descriptions.Item label="获客数量">♾️ 不限</Descriptions.Item>
                <Descriptions.Item label="创建时间">
                  {new Date(detailTask.created_ts).toLocaleString()}
                </Descriptions.Item>
                <Descriptions.Item label="已采集">{detailTask.total_crawled} 条</Descriptions.Item>
                <Descriptions.Item label="已获客">{detailTask.total_leads} 条</Descriptions.Item>
              </Descriptions>

              {/* 推广配置区域 */}
              <div style={{ marginTop: 16, padding: 16, background: '#fff7e6', borderRadius: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                  <h4 style={{ margin: 0 }}>🎯 推广配置</h4>
                  <Button type="primary" size="small" onClick={() => handleOpenPromoEdit(detailTask)}>编辑</Button>
                </div>
                {detailTask.promo_config?.product_name ? (
                  <div style={{ fontSize: 14, lineHeight: 2 }}>
                    <div><strong>产品：</strong>{detailTask.promo_config.product_name}</div>
                    <div><strong>链接：</strong>{detailTask.promo_config.promo_link || '-'}</div>
                    <div><strong>微信：</strong>{detailTask.promo_config.contact_wechat || '-'}</div>
                    <div><strong>价格：</strong>{detailTask.promo_config.price_info || '-'}</div>
                    <div><strong>优惠：</strong>{detailTask.promo_config.discount_info || '-'}</div>
                  </div>
                ) : (
                  <div style={{ color: '#999', fontSize: 13 }}>尚未配置推广信息，点击"编辑"按钮设置</div>
                )}
              </div>
            </TabPane>
            {detailTask.platform !== 'xhs' && (
            <TabPane tab={<span>📊 采集数据 {detailDataCount > 0 && <Badge count={detailDataCount} style={{ marginLeft: 4 }} size="small" />}</span>} key="data">
              <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'flex-end' }}>
                <Button
                  type="primary"
                  icon={<ReloadOutlined />}
                  size="small"
                  loading={detailTask?.status === 'running'}
                  onClick={async () => {
                    try {
                      await retryTask(detailTask.id);
                      message.success('重新采集已启动');
                      // 刷新详情
                      const res = await getTaskDetail(detailTask.id, 0, 100);
                      setDetailTask(res.task);
                      setDetailData(res.data || []);
                      setDetailDataCount(res.data_count || 0);
                      fetchTasks();
                    } catch (error: any) {
                      message.error(error?.response?.data?.detail || '重新采集失败');
                    }
                  }}
                >
                  重新采集
                </Button>
              </div>
              {detailData.length === 0 ? (
                <Empty description="暂无采集数据" style={{ padding: 40 }} />
              ) : (
                <List
                  size="small"
                  dataSource={detailData}
                  renderItem={(item: any, index: number) => (
                    <List.Item
                      key={index}
                      style={{ padding: '12px 0', borderBottom: '1px solid #f0f0f0' }}
                    >
                      <List.Item.Meta
                        title={
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <span style={{ fontWeight: 500, fontSize: 14 }}>
                              {item.type === 'video' ? '🎬' : item.type === 'note' ? '📝' : '📄'} {item.title || '无标题'}
                            </span>
                            <Tag color="blue">{item.type === 'video' ? '视频' : item.type === 'note' ? '笔记' : '内容'}</Tag>
                          </div>
                        }
                        description={
                          <div>
                            <div style={{ color: '#666', marginBottom: 4, fontSize: 13 }}>
                              {item.content ? item.content.substring(0, 100) + (item.content.length > 100 ? '...' : '') : ''}
                            </div>
                            <div style={{ display: 'flex', gap: 12, fontSize: 12, color: '#999' }}>
                              <span>👤 {item.author || '未知用户'}</span>
                              <span>👍 {item.stats?.likes || 0}</span>
                              <span>💬 {item.stats?.comments || 0}</span>
                              <span>🔄 {item.stats?.shares || 0}</span>
                              {item.url && (
                                <a href={item.url} target="_blank" rel="noopener noreferrer" style={{ color: '#1890ff' }}>
                                  查看原文
                                </a>
                              )}
                            </div>
                          </div>
                        }
                      />
                    </List.Item>
                  )}
                />
              )}
            </TabPane>
            )}
            {detailTask.platform !== 'xhs' && (
            <TabPane tab={<span>💬 评论获客 {detailCommentCount > 0 && <Badge count={detailCommentCount} style={{ marginLeft: 4 }} size="small" />}</span>} key="comments">
              <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                <Button
                  type="primary"
                  icon={<ReloadOutlined />}
                  size="small"
                  loading={detailTask?.status === 'running'}
                  onClick={async () => {
                    try {
                      await retryTask(detailTask.id);
                      message.success('重新采集评论已启动');
                      const res = await getTaskDetail(detailTask.id, 0, 100);
                      setDetailTask(res.task);
                      setDetailComments(res.comments || []);
                      setDetailCommentCount(res.comment_count || 0);
                      fetchTasks();
                    } catch (error: any) {
                      message.error(error?.response?.data?.detail || '重新采集失败');
                    }
                  }}
                >
                  重新采集
                </Button>
                <Popconfirm
                  title="确定清空该任务的所有采集数据？此操作不可恢复"
                  onConfirm={async () => {
                    try {
                      const res = await deleteTaskComments(detailTask.id);
                      message.success(`已清空 ${res.deleted_count || 0} 条评论数据`);
                      setDetailComments([]);
                      setDetailCommentCount(0);
                      setCommentOffset(0);
                      fetchTasks();
                    } catch (error: any) {
                      message.error(error?.response?.data?.detail || '清空数据失败');
                    }
                  }}
                  okText="确定清空"
                  cancelText="取消"
                  okButtonProps={{ danger: true }}
                >
                  <Button danger icon={<DeleteOutlined />} size="small">清空数据</Button>
                </Popconfirm>
              </div>
              {detailComments.length === 0 ? (
                <Empty description="暂无评论数据" style={{ padding: 40 }} />
              ) : (
                <>
                  {/* 统计栏 - 意向统计来自 CustomerLead 表(全量扫描结果),不受评论分页100条限制 */}
                  <div style={{ display: 'flex', gap: 8, marginBottom: 16, padding: '12px 16px', background: '#f6ffed', borderRadius: 8, border: '1px solid #b7eb8f', flexWrap: 'wrap', alignItems: 'center' }}>
                    <Tag color="red" style={{ minWidth: 80 }}>高意向: {leadsSummary?.high_count ?? 0}</Tag>
                    <Tag color="orange" style={{ minWidth: 80 }}>中意向: {leadsSummary?.medium_count ?? 0}</Tag>
                    <Tag color="default" style={{ minWidth: 90 }}>低意向: {leadsSummary?.low_count ?? 0}</Tag>
                    <Tag color="blue" style={{ minWidth: 80 }}>总线索: {leadsSummary?.total ?? 0}</Tag>
                    <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
                      <Tooltip title="扫描该任务全部评论(不限100条),按任务关键词/名称评分生成线索。重复扫描会覆盖旧数据。">
                        <Button
                          size="small"
                          type="primary"
                          icon={<ThunderboltOutlined />}
                          loading={scanningLeads}
                          onClick={() => handleScanLeads()}
                        >
                          {leadsSummary?.scanned ? '重新扫描全部评论' : '扫描全部评论'}
                        </Button>
                      </Tooltip>
                      <Select size="small" value={commentFilter} onChange={(v) => handleCommentFilterChange(v)} style={{ width: 120 }}>
                        <Option value="all">全部显示</Option>
                        <Option value="high">仅高意向</Option>
                        <Option value="medium">仅中意向</Option>
                        <Option value="low">仅低意向</Option>
                      </Select>
                      <Input.Search
                        size="small"
                        placeholder="地域筛选(如四川/巴中)"
                        value={ipLocationFilter}
                        onChange={(e) => setIpLocationFilter(e.target.value)}
                        onSearch={(v) => handleIpLocationSearch(v)}
                        style={{ width: 160 }}
                        allowClear
                        enterButton="筛选"
                      />
                      <Tooltip title="导出当前筛选条件下的全量线索为 Excel(含用户信息/评论/源视频/意向评分/IP属地),用于销售跟进变现">
                        <Button
                          size="small"
                          type="primary"
                          ghost
                          icon={<DownloadOutlined />}
                          loading={exportingLeads}
                          onClick={() => handleExportLeads()}
                        >
                          导出Excel
                        </Button>
                      </Tooltip>
                      <Button size="small" icon={<RobotOutlined />} onClick={() => handleBatchAnalyze()}>
                        批量分析
                      </Button>
                      <Button size="small" icon={<FileTextOutlined />} onClick={() => handleBatchGenerateCopy()}>
                        批量文案
                      </Button>
                      <Select size="small" value={outreachMethod} onChange={setOutreachMethod} style={{ width: 110 }}>
                        <Select.Option value="direct_message">📨 私信</Select.Option>
                        <Select.Option value="comment_reply">💬 评论回复</Select.Option>
                      </Select>
                      <Button size="small" type="primary" danger icon={<RobotOutlined />} loading={autoOutreachLoading} onClick={() => handleAutoOutreach()}>
                        一键获客
                      </Button>
                      <Button size="small" type="primary" onClick={() => {
                        const filtered = commentFilter === 'all' ? detailComments :
                          commentFilter === 'high' ? detailComments.filter((c: any) => c.value_level === '高') :
                          commentFilter === 'medium' ? detailComments.filter((c: any) => c.value_level === '中') :
                          detailComments.filter((c: any) => c.value_level === '低');
                        const dataStr = filtered.map((c: any) => `${c.author}\t${c.user_id}\t${c.sec_uid}\t${c.content?.substring(0, 50)}\t${c.intent}\t${c.value_score}\t${c.value_level}`).join('\n');
                        const header = '昵称\t用户ID\tSEC_UID\t评论内容\t意向\t评分\t等级\n';
                        const BOM = '\uFEFF';
                        const blob = new Blob([BOM + header + dataStr], { type: 'text/csv;charset=utf-8;' });
                        const link = document.createElement('a');
                        link.href = URL.createObjectURL(blob);
                        link.download = `评论用户_${detailTask?.id || ''}_${commentFilter}.csv`;
                        link.click();
                        message.success(`已导出 ${filtered.length} 条用户数据`);
                      }}>
                        导出CSV
                      </Button>
                    </div>
                  </div>
                  {(() => {
                    // 数据源切换:从 CustomerLead 表分页拉取(支持全量筛选),不再用 detailComments.filter(只覆盖前100条)
                    const displayComments = taskLeadsList;
                    const hasMore = taskLeadsList.length < taskLeadsTotal;
                    // 适配字段:CustomerLead 表用 lead_score/nickname,而原评论渲染用 value_score/value_level/author
                    const adaptItem = (item: any) => ({
                      ...item,
                      value_score: item.lead_score ?? item.value_score ?? 0,
                      value_level: item.lead_score >= 50 ? '高' : item.lead_score >= 25 ? '中' : '低',
                      comment_content: item.content || item.comment_content || '',
                      // CustomerLead 用 nickname,渲染代码用 author — 同步两份
                      author: item.nickname || item.author || '',
                      nickname: item.nickname || item.author || '',
                    });
                    return (
                      <>
                        <div style={{ marginBottom: 8, color: '#888', fontSize: 12 }}>
                          {taskLeadsLoading ? '加载中...' : `显示 ${taskLeadsList.length} / ${taskLeadsTotal} 条线索(从 CustomerLead 表查询)`}
                        </div>
                        <List
                          size="small"
                          dataSource={displayComments}
                          renderItem={(rawItem: any, index: number) => {
                            const item = adaptItem(rawItem);
                            const scoreColor = item.value_score >= 70 ? '#f5222d' : item.value_score >= 40 ? '#fa8c16' : '#8c8c8c';
                            const levelColor = item.value_level === '高' ? 'red' : item.value_level === '中' ? 'orange' : 'default';
                            return (
                              <List.Item
                                key={index}
                                style={{ padding: '12px 0', borderBottom: '1px solid #f0f0f0' }}
                              >
                                <List.Item.Meta
                                  avatar={
                                    <div style={{ position: 'relative' }}>
                                      {item.avatar ? (
                                        <img src={item.avatar} alt="avatar" style={{ width: 44, height: 44, borderRadius: '50%' }} />
                                      ) : (
                                        <div style={{ width: 44, height: 44, borderRadius: '50%', background: '#f0f0f0', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 20 }}>
                                          👤
                                        </div>
                                      )}
                                      <div style={{
                                        position: 'absolute',
                                        bottom: -2,
                                        right: -2,
                                        width: 18,
                                        height: 18,
                                        borderRadius: '50%',
                                        background: scoreColor,
                                        color: '#fff',
                                        fontSize: 10,
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'center',
                                        fontWeight: 'bold',
                                        border: '2px solid #fff'
                                      }}>
                                        {item.value_score || 0}
                                      </div>
                                    </div>
                                  }
                                  title={
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                      <span style={{ fontWeight: 500, fontSize: 14 }}>
                                        {item.author || '未知用户'}
                                        {item.ip_location && <Tag color="default" style={{ marginLeft: 8, fontSize: 11 }}>{item.ip_location}</Tag>}
                                        <Tag color={levelColor} style={{ marginLeft: 8, fontSize: 11 }}>{item.intent || '一般关注'}</Tag>
                                      </span>
                                      <Space>
                                        <Popover
                                          content={
                                            <div style={{ maxWidth: 280 }}>
                                              <div style={{ marginBottom: 8 }}><strong>价值评分:</strong> <span style={{ color: scoreColor, fontSize: 16 }}>{item.value_score || 0}分</span></div>
                                              <div style={{ marginBottom: 8 }}><strong>意向等级:</strong> <Tag color={levelColor}>{item.value_level || '低'}</Tag></div>
                                              <div style={{ marginBottom: 8 }}><strong>意向类型:</strong> {item.intent || '一般关注'}</div>
                                              <div style={{ marginBottom: 8 }}><strong>评分原因:</strong> {item.value_reason || '普通评论'}</div>
                                              <div><strong>用户ID:</strong> {item.user_id || '未知'}</div>
                                              <div><strong>SEC_UID:</strong> <span style={{ fontSize: 11, wordBreak: 'break-all' }}>{item.sec_uid || '无'}</span></div>
                                            </div>
                                          }
                                          title="用户价值分析"
                                          trigger="click"
                                        >
                                          <Button size="small" type="link" style={{ fontSize: 12 }}>查看价值</Button>
                                        </Popover>
                                        {item.sec_uid && (
                                          <a
                                            href={`https://www.douyin.com/user/${item.sec_uid}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            style={{ color: '#1890ff', fontSize: 12 }}
                                          >
                                            主页
                                          </a>
                                        )}
                                      </Space>
                                    </div>
                                  }
                                  description={
                                    <div>
                                      <div style={{ color: '#333', marginBottom: 6, fontSize: 13, lineHeight: 1.6, background: '#fafafa', padding: '8px 12px', borderRadius: 6 }}>
                                        {item.content || '无内容'}
                                      </div>
                                      {/* 源视频/作品信息 — 让用户回复评论时知道上下文 */}
                                      {(item.source_video_title || item.source_video_url || item.source_aweme_id) && (
                                        <div style={{ marginBottom: 8, padding: '8px 12px', background: '#fff7e6', border: '1px solid #ffd591', borderRadius: 6, fontSize: 12 }}>
                                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                                            <Tag color="orange" style={{ margin: 0 }}>源视频</Tag>
                                            {item.source_author_nickname && (
                                              <span style={{ color: '#8c8c8c' }}>作者: {item.source_author_nickname}</span>
                                            )}
                                          </div>
                                          {item.source_video_title && (
                                            <div style={{ color: '#333', fontWeight: 500, marginBottom: 4 }}>
                                              📺 {item.source_video_title.length > 80 ? item.source_video_title.substring(0, 80) + '...' : item.source_video_title}
                                            </div>
                                          )}
                                          {item.source_video_desc && item.source_video_desc !== item.source_video_title && (
                                            <div style={{ color: '#8c8c8c', marginBottom: 4 }}>
                                              {item.source_video_desc.length > 120 ? item.source_video_desc.substring(0, 120) + '...' : item.source_video_desc}
                                            </div>
                                          )}
                                          {item.source_video_url && (
                                            <a
                                              href={item.source_video_url}
                                              target="_blank"
                                              rel="noopener noreferrer"
                                              style={{ color: '#1890ff', fontSize: 12 }}
                                            >
                                              🔗 查看原视频/作品
                                            </a>
                                          )}
                                        </div>
                                      )}
                                      <div style={{ display: 'flex', gap: 16, fontSize: 12, color: '#999', alignItems: 'center' }}>
                                        <span>👍 {item.like_count || 0}</span>
                                        <span>🆔 {item.user_id || '未知'}</span>
                                        <span>📅 {(item.create_time ? new Date(item.create_time * 1000) : (item.add_ts ? new Date(item.add_ts) : null))?.toLocaleString() || ''}</span>
                                        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
                                          <Button size="small" type="primary" ghost onClick={() => {
                                            const text = `用户: ${item.author}\nID: ${item.user_id}\nSEC_UID: ${item.sec_uid}\n评论: ${item.content}\n评分: ${item.value_score}\n意向: ${item.intent}`;
                                            navigator.clipboard.writeText(text).then(() => message.success('已复制用户信息'));
                                          }}>
                                            复制信息
                                          </Button>
                                          <Button size="small" onClick={() => {
                                            if (item.sec_uid) {
                                              window.open(`https://www.douyin.com/user/${item.sec_uid}`, '_blank');
                                            } else {
                                              message.warning('无用户主页链接');
                                            }
                                          }}>
                                            访问主页
                                          </Button>
                                          <Button size="small" icon={<RobotOutlined />} onClick={async () => {
                                            console.log('[分析需求按钮] 被点击, item=', item);
                                            if (!detailTask) {
                                              message.error('请先选择任务');
                                              return;
                                            }
                                            if (!item) {
                                              message.error('用户数据为空');
                                              return;
                                            }
                                            const uid = item.user_id || item.id || '';
                                            if (!uid) {
                                              message.error('用户ID为空，无法分析');
                                              return;
                                            }
                                            message.info('正在打开需求分析...');
                                            setSelectedUser(item);
                                            setAnalyzeLoading(true);
                                            setAnalyzeModalVisible(true);
                                            setAnalyzeResult(null);
                                            try {
                                              const res = await analyzeUserNeeds(detailTask.id, {
                                                user_ids: [uid],
                                                max_users: 1,
                                              });
                                              console.log('[分析需求] API返回:', res);
                                              if (res.results && res.results.length > 0) {
                                                setAnalyzeResult(res.results[0]);
                                              } else {
                                                message.warning('未分析到需求，请检查用户数据');
                                              }
                                            } catch (error: any) {
                                              console.error('分析需求错误:', error);
                                              message.error(error?.response?.data?.detail || '需求分析失败');
                                            } finally {
                                              setAnalyzeLoading(false);
                                            }
                                          }}>
                                            分析需求
                                          </Button>
                                          <Button size="small" type="primary" loading={outreachLoadingMap[item.comment_id || item.id] || false} onClick={async () => {
                                            if (!detailTask || !item) return;
                                            const oKey = item.comment_id || item.id || '';
                                            setOutreachLoadingMap(prev => ({ ...prev, [oKey]: true }));
                                            try {
                                              const res = await createOutreachTask(detailTask.id, {
                                                user_id: item.user_id || item.id || '',
                                                sec_uid: item.sec_uid || '',
                                                platform: detailTask.platform,
                                                method: 'direct_message',
                                                content: '',
                                                nickname: item.author || item.nickname || '',
                                                require_confirm: false,
                                              });
                                              message.success('私信任务已创建，正在发送...');
                                              // 轮询状态
                                              if (res.task_id) {
                                                const pollInterval = setInterval(async () => {
                                                  try {
                                                    const status = await getOutreachStatus(detailTask.id, res.task_id);
                                                    if (status.status === 'completed' || status.status === 'failed') {
                                                      clearInterval(pollInterval);
                                                      if (status.status === 'completed') {
                                                        message.success(`私信发送成功: ${item.author || '用户'}`);
                                                      } else {
                                                        message.error(`私信发送失败: ${status.error_message || '未知错误'}`);
                                                      }
                                                    }
                                                  } catch { clearInterval(pollInterval); }
                                                }, 3000);
                                              }
                                            } catch (error: any) {
                                              message.error(error?.response?.data?.detail || '私信发送失败');
                                            } finally {
                                              setOutreachLoadingMap(prev => ({ ...prev, [oKey]: false }));
                                            }
                                          }}>
                                            📨 私信
                                          </Button>
                                          <Button size="small" type="primary" danger loading={replyLoadingMap[item.comment_id || item.id] || false} onClick={async () => {
                                            if (!detailTask || !item) return;
                                            const cid = item.comment_id || item.id || '';
                                            const awemeId = item.aweme_id || item.note_id || '';
                                            if (!cid) {
                                              message.error('缺少评论ID，无法回复');
                                              return;
                                            }
                                            if (!awemeId) {
                                              message.error('缺少视频ID，无法回复');
                                              return;
                                            }
                                            setReplyLoadingMap(prev => ({ ...prev, [cid]: true }));
                                            try {
                                              // 先生成回复文案
                                              let replyContent = '';
                                              try {
                                                const contentRes = await generateAdContent(detailTask.id, {
                                                  user_ids: [item.user_id || item.id || ''],
                                                  content_type: 'comment_reply',
                                                });
                                                if (contentRes.contents && contentRes.contents.length > 0) {
                                                  replyContent = contentRes.contents[0].comment_reply || contentRes.contents[0].direct_message || '';
                                                }
                                              } catch {
                                                // 文案生成失败，使用默认回复
                                              }
                                              if (!replyContent) {
                                                replyContent = '感谢关注！了解更多请私信我哦~';
                                              }
                                              const res = await createOutreachTask(detailTask.id, {
                                                user_id: item.user_id || item.id || '',
                                                sec_uid: item.sec_uid || '',
                                                platform: detailTask.platform,
                                                method: 'comment_reply',
                                                content: replyContent,
                                                nickname: item.author || item.nickname || '',
                                                note_id: awemeId,
                                                comment_id: cid,
                                                require_confirm: false,
                                              });
                                              message.success('评论回复任务已创建，正在发送...');
                                              // 轮询状态
                                              if (res.task_id) {
                                                const pollInterval = setInterval(async () => {
                                                  try {
                                                    const status = await getOutreachStatus(detailTask.id, res.task_id);
                                                    if (status.status === 'completed' || status.status === 'failed') {
                                                      clearInterval(pollInterval);
                                                      if (status.status === 'completed') {
                                                        const videoUrl = `https://www.douyin.com/video/${awemeId}`;
                                                        notification.success({
                                                          message: '评论回复成功',
                                                          description: (
                                                            <div>
                                                              <div>已回复 <strong>{item.author || '用户'}</strong> 的评论</div>
                                                              <div style={{ marginTop: 8 }}>回复内容：{replyContent}</div>
                                                              <a href={videoUrl} target="_blank" rel="noopener noreferrer" style={{ marginTop: 8, display: 'inline-block' }}>
                                                                👉 点击查看原视频评论
                                                              </a>
                                                            </div>
                                                          ),
                                                          duration: 15,
                                                        });
                                                      } else {
                                                        notification.error({
                                                          message: '评论回复失败',
                                                          description: status.error_message || '未知错误',
                                                          duration: 10,
                                                        });
                                                      }
                                                    }
                                                  } catch { clearInterval(pollInterval); }
                                                }, 3000);
                                              }
                                            } catch (error: any) {
                                              message.error(error?.response?.data?.detail || '评论回复失败');
                                            } finally {
                                              setReplyLoadingMap(prev => ({ ...prev, [cid]: false }));
                                            }
                                          }}>
                                            💬 回复评论
                                          </Button>
                                        </div>
                                      </div>
                                    </div>
                                  }
                                />
                              </List.Item>
                            );
                          }}
                        />
                        {hasMore && (
                          <div style={{ textAlign: 'center', padding: '16px 0' }}>
                            <Button
                              type="primary"
                              ghost
                              loading={taskLeadsLoading}
                              onClick={() => handleLoadMoreLeads()}
                            >
                              加载更多 ({taskLeadsTotal - taskLeadsList.length} 条未加载)
                            </Button>
                          </div>
                        )}
                      </>
                    );
                  })()}
                </>
              )}
            </TabPane>
            )}
            <TabPane tab={<span><CodeOutlined /> 运行日志 {detailLogs.length > 0 && <Badge count={detailLogs.length} style={{ marginLeft: 4 }} size="small" />}</span>} key="logs">
              <div
                ref={logsContainerRef}
                onScroll={(e) => {
                  const el = e.currentTarget;
                  // 用户上滚(距底超过 80px)时关闭自动滚动,滚到底部时重新开启
                  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
                  logsAutoScrollRef.current = atBottom;
                }}
                style={{
                  background: '#1e1e1e',
                  color: '#d4d4d4',
                  padding: 12,
                  borderRadius: 4,
                  fontFamily: "'JetBrains Mono', 'Consolas', monospace",
                  fontSize: 12,
                  maxHeight: 400,
                  overflowY: 'auto',
                  minHeight: 200,
                }}
              >
                {detailLogs.length === 0 ? (
                  <div style={{ color: '#666', textAlign: 'center', padding: '40px 0' }}>暂无日志</div>
                ) : (
                  <List
                    size="small"
                    dataSource={detailLogs}
                    renderItem={(log: any, index: number) => {
                      // 去掉消息中重复的时间前缀（如 "2026-06-06 15:56:20 "）
                      let message = log.message || '';
                      const timePrefixMatch = message.match(/^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+/);
                      if (timePrefixMatch) {
                        message = message.substring(timePrefixMatch[0].length);
                      }
                      return (
                        <div
                          key={index}
                          style={{
                            padding: '2px 0',
                            borderBottom: index < detailLogs.length - 1 ? '1px solid #333' : 'none',
                            wordBreak: 'break-all',
                          }}
                        >
                          <span style={{ color: '#858585', marginRight: 8 }}>
                            {log.time ? new Date(log.time).toLocaleTimeString() : '--:--:--'}
                          </span>
                          <span
                            style={{
                              color:
                                log.level === 'error'
                                  ? '#f48771'
                                  : log.level === 'warn'
                                  ? '#dcdcaa'
                                  : log.level === 'success'
                                  ? '#4ec9b0'
                                  : '#d4d4d4',
                            }}
                          >
                            {message}
                          </span>
                        </div>
                      );
                    }}
                  />
                )}
              </div>
              {detailTask.status === 'running' && (
                <div style={{ marginTop: 8, textAlign: 'center' }}>
                  <Badge status="processing" text="任务运行中，日志实时更新..." />
                </div>
              )}
            </TabPane>
            <TabPane tab={<span><ThunderboltOutlined /> 获客任务</span>} key="outreach-jobs">
              <OutreachJobsPanel taskId={detailTask?.id} />
            </TabPane>
          </Tabs>
        ) : (
          <div style={{ textAlign: 'center', padding: 40 }}>任务不存在</div>
        )}
      </Modal>

      {/* ========== 需求分析弹窗 ========== */}
      <Modal
        title={<Space><RobotOutlined /><span>智能需求分析</span></Space>}
        open={analyzeModalVisible}
        onCancel={() => setAnalyzeModalVisible(false)}
        mask={{ closable: false }}
        forceRender
        zIndex={2000}
        width={analyzeResult?.batch ? 800 : 600}
        footer={
          <Space>
            <Button key="close" onClick={() => setAnalyzeModalVisible(false)}>关闭</Button>
            {analyzeResult && !analyzeResult.batch && (
              <Button key="next" type="primary" onClick={() => { setAnalyzeModalVisible(false); handleGenerateContent(); }}>
                生成文案 →
              </Button>
            )}
          </Space>
        }
      >
        {analyzeLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}>正在分析用户需求...</div>
        ) : analyzeResult ? (
          analyzeResult.batch ? (
            <div>
              <div style={{ marginBottom: 16, padding: 12, background: '#f6ffed', borderRadius: 8 }}>
                <div style={{ fontWeight: 600 }}>📊 {analyzeResult.summary}</div>
              </div>
              <List
                size="small"
                dataSource={analyzeResult.results || []}
                renderItem={(item: any, idx: number) => (
                  <List.Item key={idx} style={{ padding: '12px 0', borderBottom: '1px solid #f0f0f0' }}>
                    <div style={{ width: '100%' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                        <span style={{ fontWeight: 600 }}>👤 {item.nickname || '未知用户'}</span>
                        <Tag color="blue">{item.need_type_name || '一般关注'}</Tag>
                      </div>
                      <div style={{ color: '#666', fontSize: 13, marginBottom: 8 }}>
                        <strong>需求摘要:</strong> {item.need_summary || '无'}
                      </div>
                      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        {item.pain_points?.map((p: string, i: number) => (
                          <Tag key={i} color="red">{p}</Tag>
                        ))}
                      </div>
                    </div>
                  </List.Item>
                )}
              />
            </div>
          ) : (
            <div>
              <div style={{ marginBottom: 16, padding: 12, background: '#f6ffed', borderRadius: 8 }}>
                <div style={{ fontWeight: 600, marginBottom: 8 }}>👤 {analyzeResult.nickname || selectedUser?.author || '未知用户'}</div>
                <div style={{ color: '#666', fontSize: 13 }}>📝 {selectedUser?.content || ''}</div>
              </div>

              <Descriptions bordered column={1} size="small" style={{ marginBottom: 16 }}>
                <Descriptions.Item label="需求类型">
                  <Tag color="blue">{analyzeResult.need_type_name || '一般关注'}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="需求摘要">{analyzeResult.need_summary || '无'}</Descriptions.Item>
                <Descriptions.Item label="痛点识别">
                  {analyzeResult.pain_points?.length > 0 ? analyzeResult.pain_points.map((p: string, i: number) => (
                    <Tag key={i} color="red">{p}</Tag>
                  )) : <span style={{ color: '#999' }}>未识别到痛点</span>}
                </Descriptions.Item>
                <Descriptions.Item label="预算敏感度">
                  {analyzeResult.budget_sensitivity === 'high' ? <Tag color="red">高（在意价格）</Tag> :
                   analyzeResult.budget_sensitivity === 'medium' ? <Tag color="orange">中（关注性价比）</Tag> :
                   <Tag color="green">低（不敏感）</Tag>}
                </Descriptions.Item>
                <Descriptions.Item label="紧急程度">
                  {analyzeResult.urgency === 'urgent' ? <Tag color="red">紧急</Tag> :
                   analyzeResult.urgency === 'normal' ? <Tag color="orange">一般</Tag> :
                   <Tag color="default">不急</Tag>}
                </Descriptions.Item>
                <Descriptions.Item label="置信度">
                  <span style={{ color: '#1890ff', fontWeight: 600 }}>{Math.round((analyzeResult.confidence || 0) * 100)}%</span>
                </Descriptions.Item>
              </Descriptions>

              <div style={{ padding: 12, background: '#e6f7ff', borderRadius: 8 }}>
                <div style={{ fontWeight: 600, marginBottom: 8 }}>💡 推荐话术</div>
                <div style={{ color: '#333', fontSize: 13, lineHeight: 1.6 }}>{analyzeResult.recommended_pitch || '暂无推荐话术'}</div>
              </div>
            </div>
          )
        ) : (
          <Empty description="暂无分析结果" />
        )}
      </Modal>

      {/* ========== 生成文案弹窗 ========== */}
      <Modal
        title={<Space><FileTextOutlined /><span>生成个性化文案</span></Space>}
        open={contentModalVisible}
        onCancel={() => setContentModalVisible(false)}
        mask={{ closable: false }}
        width={contentResult?.batch ? 800 : 600}
        footer={[
          <Button key="close" onClick={() => setContentModalVisible(false)}>关闭</Button>,
          contentResult && !contentResult.batch && (
            <Button key="reply" loading={outreachLoading} onClick={async () => {
              // 评论回复：创建触达任务 → 自动执行
              if (!detailTask || !selectedUser || !contentResult) return;
              setOutreachLoading(true);
              try {
                const content = contentResult.comment_reply || contentResult.direct_message || '';
                const res = await createOutreachTask(detailTask.id, {
                  user_id: selectedUser.user_id,
                  sec_uid: selectedUser.sec_uid || '',
                  platform: detailTask.platform,
                  method: 'comment_reply',
                  content: content,
                  nickname: selectedUser.author || selectedUser.nickname || '',
                  note_id: selectedUser.aweme_id || selectedUser.note_id || '',
                  comment_id: selectedUser.comment_id || selectedUser.id || '',
                  require_confirm: false,
                });
                if (res.task_id) {
                  const execRes = await executeOutreachTask(detailTask.id, res.task_id);
                  message.success('评论回复已启动');
                  setContentModalVisible(false);
                  setOutreachResult({ ...res, ...execRes });
                  setOutreachModalVisible(true);
                  startOutreachStatusPolling(detailTask.id, res.task_id);
                }
              } catch (error: any) {
                message.error(error?.response?.data?.detail || '评论回复失败');
              } finally {
                setOutreachLoading(false);
              }
            }}>
              💬 评论回复
            </Button>
          ),
          contentResult && !contentResult.batch && (
            <Button key="send" type="primary" danger loading={outreachLoading} onClick={async () => {
              // 一键发送私信：创建触达任务 → 自动执行
              if (!detailTask || !selectedUser || !contentResult) return;
              setOutreachLoading(true);
              try {
                const res = await createOutreachTask(detailTask.id, {
                  user_id: selectedUser.user_id,
                  sec_uid: selectedUser.sec_uid || '',
                  platform: detailTask.platform,
                  method: 'direct_message',
                  content: contentResult.direct_message || '',
                  nickname: selectedUser.author || selectedUser.nickname || '',
                  note_id: selectedUser.aweme_id || selectedUser.note_id || '',
                  comment_id: selectedUser.comment_id || selectedUser.id || '',
                  require_confirm: false,
                });
                if (res.task_id) {
                  const execRes = await executeOutreachTask(detailTask.id, res.task_id);
                  message.success('私信发送已启动');
                  setContentModalVisible(false);
                  setOutreachResult({ ...res, ...execRes });
                  setOutreachModalVisible(true);
                  startOutreachStatusPolling(detailTask.id, res.task_id);
                }
              } catch (error: any) {
                message.error(error?.response?.data?.detail || '发送私信失败');
              } finally {
                setOutreachLoading(false);
              }
            }}>
              🚀 一键发送私信
            </Button>
          ),
          contentResult && !contentResult.batch && (
            <Button key="next" onClick={() => { setContentModalVisible(false); handleCreateOutreach(); }}>
              创建触达任务 →
            </Button>
          ),
          contentResult?.batch && (
            <Button key="export" type="primary" onClick={() => {
              const lines = (contentResult.contents || []).map((c: any) => `${c.nickname}\t${c.need_type_name}\t${c.direct_message}`).join('\n');
              const header = '昵称\t需求类型\t私信文案\n';
              const BOM = '\uFEFF';
              const blob = new Blob([BOM + header + lines], { type: 'text/csv;charset=utf-8;' });
              const link = document.createElement('a');
              link.href = URL.createObjectURL(blob);
              link.download = `批量文案_${new Date().toISOString().slice(0,10)}.csv`;
              link.click();
              message.success('已导出文案');
            }}>
              导出文案
            </Button>
          ),
        ]}
      >
        {contentLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}>正在生成文案...</div>
        ) : contentResult ? (
          contentResult.batch ? (
            <div>
              <div style={{ marginBottom: 16, padding: 12, background: '#f6ffed', borderRadius: 8 }}>
                <div style={{ fontWeight: 600 }}>📊 {contentResult.summary}</div>
              </div>
              <List
                size="small"
                dataSource={contentResult.contents || []}
                renderItem={(item: any, idx: number) => (
                  <List.Item key={idx} style={{ padding: '12px 0', borderBottom: '1px solid #f0f0f0' }}>
                    <div style={{ width: '100%' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                        <span style={{ fontWeight: 600 }}>👤 {item.nickname || '未知用户'}</span>
                        <Tag color="blue">{item.need_type_name || '一般关注'}</Tag>
                      </div>
                      <div style={{ padding: 10, background: '#fafafa', borderRadius: 6, border: '1px solid #e8e8e8', whiteSpace: 'pre-wrap', fontSize: 13, lineHeight: 1.5, marginBottom: 8 }}>
                        {item.direct_message || '无'}
                      </div>
                      <Button size="small" onClick={() => {
                        navigator.clipboard.writeText(item.direct_message || '').then(() => message.success('已复制'));
                      }}>复制</Button>
                    </div>
                  </List.Item>
                )}
              />
            </div>
          ) : (
            <div>
              <div style={{ marginBottom: 16 }}>
                <span style={{ fontWeight: 600 }}>语气风格：</span>
                <Radio.Group size="small" value={contentTone} onChange={(e) => { setContentTone(e.target.value); handleGenerateContent(); }}>
                  <Radio.Button value="friendly">友好</Radio.Button>
                  <Radio.Button value="professional">专业</Radio.Button>
                  <Radio.Button value="casual">随意</Radio.Button>
                </Radio.Group>
              </div>

              <div style={{ marginBottom: 16, padding: 12, background: '#f6ffed', borderRadius: 8 }}>
                <div style={{ fontWeight: 600, marginBottom: 8 }}>👤 {contentResult.nickname || selectedUser?.author || '未知用户'}</div>
                <div><Tag color="blue">{contentResult.need_type_name || '一般关注'}</Tag></div>
              </div>

              <div style={{ marginBottom: 16 }}>
                <div style={{ fontWeight: 600, marginBottom: 8 }}>📨 私信文案</div>
                <div style={{ padding: 12, background: '#fafafa', borderRadius: 8, border: '1px solid #e8e8e8', whiteSpace: 'pre-wrap', fontSize: 13, lineHeight: 1.6 }}>
                  {contentResult.direct_message || '无'}
                </div>
                <Button size="small" style={{ marginTop: 8 }} onClick={() => {
                  navigator.clipboard.writeText(contentResult.direct_message || '').then(() => message.success('已复制私信文案'));
                }}>复制文案</Button>
              </div>

              <div style={{ marginBottom: 16 }}>
                <div style={{ fontWeight: 600, marginBottom: 8 }}>💬 评论回复文案</div>
                <div style={{ padding: 12, background: '#fafafa', borderRadius: 8, border: '1px solid #e8e8e8', whiteSpace: 'pre-wrap', fontSize: 13, lineHeight: 1.6 }}>
                  {contentResult.comment_reply || '无'}
                </div>
              </div>

              <div>
                <div style={{ fontWeight: 600, marginBottom: 8 }}>🎯 行动号召</div>
                <div style={{ color: '#1890ff', fontSize: 13 }}>{contentResult.call_to_action || '无'}</div>
              </div>
            </div>
          )
        ) : (
          <Empty description="暂无文案结果" />
        )}
      </Modal>

      {/* ========== 触达任务弹窗 ========== */}
      <Modal
        title={<Space><CheckCircleOutlined /><span>自动化触达</span></Space>}
        open={outreachModalVisible}
        onCancel={() => {
          setOutreachModalVisible(false);
          if (outreachStatusRef.current) {
            clearInterval(outreachStatusRef.current);
            outreachStatusRef.current = null;
          }
        }}
        mask={{ closable: false }}
        width={600}
        footer={[
          <Button key="close" onClick={() => {
            setOutreachModalVisible(false);
            if (outreachStatusRef.current) {
              clearInterval(outreachStatusRef.current);
              outreachStatusRef.current = null;
            }
          }}>关闭</Button>,
          outreachResult && outreachResult.status === 'pending' && !outreachStatus && (
            <Button key="execute" type="primary" loading={outreachLoading} onClick={handleExecuteOutreach}>
              🚀 开始自动发送私信
            </Button>
          ),
        ]}
      >
        {outreachLoading && !outreachStatus ? (
          <div style={{ textAlign: 'center', padding: 40 }}>正在创建触达任务...</div>
        ) : outreachResult ? (
          <div>
            {/* 状态头部 */}
            <div style={{ marginBottom: 16, padding: 12, background: outreachStatus?.status === 'success' ? '#f6ffed' : outreachStatus?.status === 'failed' ? '#fff2f0' : '#e6f7ff', borderRadius: 8 }}>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>
                {outreachStatus?.status === 'success' ? '✅ 私信发送成功' :
                 outreachStatus?.status === 'failed' ? '❌ 私信发送失败' :
                 outreachStatus?.status === 'running' ? '🚀 正在自动发送私信...' :
                 '⏳ 等待执行'}
              </div>
              <div style={{ fontSize: 13, color: '#666' }}>
                {outreachStatus?.error_message || outreachResult.message || '触达任务已创建'}
              </div>
            </div>

            {/* 执行进度步骤 */}
            {outreachStatus && outreachStatus.steps && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontWeight: 600, marginBottom: 8 }}>📋 执行进度</div>
                <div style={{ padding: 12, background: '#fafafa', borderRadius: 8 }}>
                  {outreachStatus.steps.map((s: any) => (
                    <div key={s.step} style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
                      <span style={{
                        width: 20, height: 20, borderRadius: '50%', display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                        fontSize: 12, marginRight: 8,
                        background: s.status === 'success' ? '#52c41a' : s.status === 'running' ? '#1890ff' : s.status === 'failed' ? '#ff4d4f' : '#d9d9d9',
                        color: '#fff'
                      }}>
                        {s.status === 'success' ? '✓' : s.status === 'failed' ? '✗' : s.step}
                      </span>
                      <span style={{ flex: 1, fontSize: 13 }}>{s.name}</span>
                      <span style={{ fontSize: 12, color: s.status === 'success' ? '#52c41a' : s.status === 'running' ? '#1890ff' : s.status === 'failed' ? '#ff4d4f' : '#999' }}>
                        {s.status === 'success' ? '完成' : s.status === 'running' ? '执行中...' : s.status === 'failed' ? '失败' : '等待'}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 执行日志 */}
            {outreachStatus && outreachStatus.logs && outreachStatus.logs.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontWeight: 600, marginBottom: 8 }}>📝 执行日志</div>
                <div style={{
                  padding: 12,
                  background: '#1e1e1e',
                  borderRadius: 8,
                  maxHeight: 220,
                  overflowY: 'auto',
                  fontFamily: 'Consolas, Monaco, "Courier New", monospace',
                  fontSize: 12,
                  lineHeight: 1.6
                }}>
                  {outreachStatus.logs.map((log: string, index: number) => (
                    <div key={index} style={{
                      color: log.includes('❌') || log.includes('failed') ? '#ff6b6b' :
                             log.includes('✅') || log.includes('success') ? '#4caf50' :
                             log.includes('⚠️') ? '#ffb74d' :
                             '#e0e0e0',
                      marginBottom: 2,
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word'
                    }}>
                      {log}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div style={{ marginBottom: 16 }}>
              <div style={{ fontWeight: 600, marginBottom: 8 }}>👤 目标用户</div>
              <div style={{ fontSize: 13 }}>{selectedUser?.author || '未知'} (ID: {selectedUser?.user_id || '无'})</div>
            </div>

            <div style={{ marginBottom: 16 }}>
              <div style={{ fontWeight: 600, marginBottom: 8 }}>📨 发送内容</div>
              <div style={{ padding: 12, background: '#fafafa', borderRadius: 8, border: '1px solid #e8e8e8', whiteSpace: 'pre-wrap', fontSize: 13, lineHeight: 1.6 }}>
                {contentResult?.direct_message || '无'}
              </div>
            </div>

            {/* 截图展示 */}
            {outreachStatus?.steps?.some((s: any) => s.screenshot) && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontWeight: 600, marginBottom: 8 }}>📸 执行截图</div>
                {outreachStatus.steps.filter((s: any) => s.screenshot).map((s: any) => (
                  <div key={s.step} style={{ marginBottom: 8 }}>
                    <div style={{ fontSize: 12, color: '#666', marginBottom: 4 }}>{s.name}</div>
                    <img src={`/api/screenshots/${encodeURIComponent(s.screenshot)}`} alt={s.name} style={{ maxWidth: '100%', borderRadius: 4, border: '1px solid #e8e8e8' }} />
                  </div>
                ))}
              </div>
            )}

            {!outreachStatus && (
              <div style={{ padding: 12, background: '#fff7e6', borderRadius: 8 }}>
                <div style={{ fontWeight: 600, marginBottom: 8, color: '#d46b08' }}>🤖 自动化说明</div>
                <div style={{ fontSize: 13, color: '#666', lineHeight: 1.6 }}>
                  点击"开始自动发送私信"后，系统将自动：<br/>
                  1. 启动浏览器并访问用户主页<br/>
                  2. 自动点击"私信"按钮<br/>
                  3. 自动输入文案并发送<br/>
                  4. 保存执行结果截图<br/>
                  <br/>
                  <span style={{ color: '#ff4d4f' }}>注意：请确保系统已配置目标平台(dy)登录态，且浏览器可见</span>
                </div>
              </div>
            )}
          </div>
        ) : (
          <Empty description="暂无触达任务" />
        )}
      </Modal>

      {/* 自动获客进度弹窗 */}
      <Modal
        title="🤖 一键自动获客"
        open={autoOutreachModalVisible}
        onCancel={() => {
          setAutoOutreachModalVisible(false);
          // 任务在后台继续运行，不停止轮询
          if (autoOutreachJob?.status === 'running') {
            message.info('任务将在后台继续运行，可在"获客任务"标签页查看进度');
          } else if (autoOutreachPollRef.current) {
            clearInterval(autoOutreachPollRef.current);
            autoOutreachPollRef.current = null;
          }
        }}
        mask={{ closable: false }}
        width={750}
        footer={[
          <Button key="close" onClick={() => {
            setAutoOutreachModalVisible(false);
            if (autoOutreachJob?.status === 'running') {
              message.info('任务将在后台继续运行，可在"获客任务"标签页查看进度');
            } else if (autoOutreachPollRef.current) {
              clearInterval(autoOutreachPollRef.current);
              autoOutreachPollRef.current = null;
            }
          }}>关闭</Button>,
        ]}
      >
        {autoOutreachJob ? (
          <div>
            {/* 进度概览 */}
            <div style={{ marginBottom: 16, padding: 16, background: autoOutreachJob.status === 'completed' ? '#f6ffed' : '#e6f7ff', borderRadius: 8, border: `1px solid ${autoOutreachJob.status === 'completed' ? '#b7eb8f' : '#91d5ff'}` }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <span style={{ fontWeight: 600, fontSize: 15 }}>
                  {autoOutreachJob.status === 'completed' ? '✅ 自动获客完成' :
                   autoOutreachJob.status === 'running' ? '🚀 正在自动获客...' :
                   autoOutreachJob.status === 'no_targets' ? '⚠️ 未找到目标用户' : '⏳ 准备中...'}
                </span>
                <span style={{ fontSize: 13, color: '#666' }}>
                  {autoOutreachJob.completed || 0}/{autoOutreachJob.total || 0}
                </span>
              </div>
              {(autoOutreachJob.total || 0) > 0 && (
                <div style={{ background: '#f0f0f0', borderRadius: 4, height: 10, overflow: 'hidden' }}>
                  <div style={{
                    width: `${((autoOutreachJob.completed || 0) / (autoOutreachJob.total || 1)) * 100}%`,
                    height: '100%',
                    background: autoOutreachJob.failed > autoOutreachJob.success ? '#ff4d4f' : '#52c41a',
                    borderRadius: 4,
                    transition: 'width 0.5s',
                  }} />
                </div>
              )}
              <div style={{ display: 'flex', gap: 16, marginTop: 8, fontSize: 13 }}>
                <span style={{ color: '#52c41a', fontWeight: 500 }}>✅ 成功: {autoOutreachJob.success || 0}</span>
                <span style={{ color: '#ff4d4f', fontWeight: 500 }}>❌ 失败: {autoOutreachJob.failed || 0}</span>
                <span style={{ color: '#999' }}>总计: {autoOutreachJob.total || 0}</span>
                {autoOutreachJob.skipped > 0 && <span style={{ color: '#faad14' }}>⏭ 跳过: {autoOutreachJob.skipped}</span>}
              </div>
              {/* 当前正在发送的用户 */}
              {autoOutreachJob.status === 'running' && autoOutreachJob.results && autoOutreachJob.results.length < (autoOutreachJob.total || 0) && (
                <div style={{ marginTop: 8, padding: 8, background: '#fff', borderRadius: 4, fontSize: 12, color: '#1890ff' }}>
                  📤 正在发送第 {(autoOutreachJob.results?.length || 0) + 1} 个用户...
                </div>
              )}
            </div>

            {/* 目标用户列表 */}
            {autoOutreachJob.targets && autoOutreachJob.targets.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontWeight: 600, marginBottom: 8 }}>📋 目标用户 & 生成文案</div>
                <div style={{ maxHeight: 400, overflowY: 'auto' }}>
                  {autoOutreachJob.targets.map((t: any, idx: number) => {
                    const result = autoOutreachJob.results?.find((r: any) => r.user_id === t.user_id);
                    const isCurrent = autoOutreachJob.status === 'running' && !result && autoOutreachJob.results?.length === idx;
                    return (
                      <div key={idx} style={{
                        padding: 12,
                        background: isCurrent ? '#e6f7ff' : '#fafafa',
                        borderRadius: 8,
                        marginBottom: 8,
                        border: `1px solid ${isCurrent ? '#91d5ff' : result ? (result.success ? '#b7eb8f' : '#ffa39e') : '#f0f0f0'}`,
                      }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                          <span style={{ fontWeight: 500 }}>
                            <span style={{ color: '#999', marginRight: 8 }}>#{idx + 1}</span>
                            {t.nickname || '未知'}
                            <Tag color="red" style={{ marginLeft: 8, fontSize: 11 }}>{t.value_level}</Tag>
                            <Tag style={{ fontSize: 11 }}>{t.need_type_name}</Tag>
                          </span>
                          {isCurrent && <Tag color="blue">发送中...</Tag>}
                          {result && (
                            <Tag color={result.success ? 'green' : 'red'}>
                              {result.success ? '✅ 已发送' : '❌ 失败'}
                            </Tag>
                          )}
                        </div>
                        <div style={{ fontSize: 12, color: '#999', marginBottom: 4 }}>
                          评论: {t.content?.substring(0, 50)}{t.content?.length > 50 ? '...' : ''}
                        </div>
                        <div style={{ fontSize: 12, color: '#333', background: '#fff', padding: 8, borderRadius: 4, border: '1px solid #e8e8e8' }}>
                          {t.direct_message}
                        </div>
                        {result && !result.success && result.message && (
                          <div style={{ fontSize: 11, color: '#ff4d4f', marginTop: 4 }}>
                            失败原因: {result.message}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div style={{ textAlign: 'center', padding: 40 }}>
            {autoOutreachLoading ? '正在启动自动获客...' : '准备中...'}
          </div>
        )}
      </Modal>

      {/* 推广配置编辑弹窗 */}
      <Modal
        title="编辑推广配置"
        open={promoEditVisible}
        onCancel={() => setPromoEditVisible(false)}
        mask={{ closable: false }}
        footer={null}
        width={560}
      >
        <Form form={promoForm} layout="vertical" onFinish={handleSavePromo}>
          <div style={{ padding: 12, background: '#e6f7ff', borderRadius: 8, marginBottom: 16 }}>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>💡 推广配置说明</div>
            <div style={{ fontSize: 13, color: '#666' }}>配置你的产品信息，系统会在生成文案时自动带入</div>
          </div>

          <Form.Item name="product_name" label="产品名称" rules={[{ required: true, message: '请输入产品名称' }]}>
            <Input placeholder="例如：AI聚合平台" />
          </Form.Item>

          <Form.Item name="product_desc" label="产品描述">
            <Input.TextArea placeholder="一句话描述你的产品" rows={2} />
          </Form.Item>

          <Form.Item name="promo_link" label="推广链接">
            <Input placeholder="your-domain.com/register（不要加https://）" />
          </Form.Item>

          <Form.Item name="contact_wechat" label="联系微信">
            <Input placeholder="你的微信号" />
          </Form.Item>

          <Form.Item name="price_info" label="价格信息">
            <Input placeholder="例如：月费29元，年费249元" />
          </Form.Item>

          <Form.Item name="discount_info" label="优惠信息">
            <Input placeholder="例如：新用户首月5折" />
          </Form.Item>

          <Form.Item name="free_quota" label="免费额度">
            <Input placeholder="例如：注册送100次免费调用" />
          </Form.Item>

          <Form.Item name="solution_desc" label="解决方案描述">
            <Input.TextArea placeholder="你的产品如何解决用户痛点" rows={2} />
          </Form.Item>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
            <Button onClick={() => setPromoEditVisible(false)}>取消</Button>
            <Button type="primary" htmlType="submit" loading={promoEditLoading}>保存</Button>
          </div>
        </Form>
      </Modal>
    </div>
  );
};

export default TaskManager;
