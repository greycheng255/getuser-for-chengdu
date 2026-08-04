import { message } from '../utils/antdMessage';
import React, { useEffect, useState, useCallback, useRef } from 'react';
import {
  Card, Table, Tag, Button, Space, Modal, Form, Input, Select,
  Row, Col, Tabs, Empty, Alert, InputNumber, Statistic, Progress,
  Popconfirm, Descriptions, Typography, Tooltip,
} from 'antd';
import {
  ReloadOutlined, PlusOutlined, DeleteOutlined, ThunderboltOutlined,
  CheckCircleOutlined, UserOutlined, TeamOutlined,
} from '@ant-design/icons';
import {
  listPlans, getPlan, deletePlan, createPlan, listAccounts,
  getNext, batchMarkReplied, listRecords, getProgress,
  previewCustomers,
  type DispatchPlan, type DispatchAccount, type DispatchRecord,
  type PlanProgress, type AccountConfig,
  type NextBatchResponse,
} from '../api/customerDispatch';

const { Text } = Typography;

const PLATFORM_OPTIONS = [
  { value: 'douyin', label: '抖音' },
  { value: 'xhs', label: '小红书' },
  { value: 'ks', label: '快手' },
  { value: 'bili', label: 'B站' },
  { value: 'wb', label: '微博' },
];

const STATUS_COLORS: Record<string, string> = {
  pending: 'default',
  sent: 'processing',
  replied: 'success',
  skipped: 'warning',
};
const STATUS_LABELS: Record<string, string> = {
  pending: '待发送',
  sent: '已发送',
  replied: '已回复',
  skipped: '已跳过',
};

// 把 NextBatchResponse 拍平为表格可用的行
interface NextRow {
  seq: number;
  customer?: NextBatchResponse['customers'][number];
}

const CustomerDispatch: React.FC = () => {
  const [tab, setTab] = useState('plans');
  const [plans, setPlans] = useState<DispatchPlan[]>([]);
  const [plansLoading, setPlansLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createForm] = Form.useForm();
  const [previewTotal, setPreviewTotal] = useState<number | null>(null);
  const [previewing, setPreviewing] = useState(false);

  // 详情
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(null);
  const [planDetail, setPlanDetail] = useState<DispatchPlan | null>(null);
  const [accounts, setAccounts] = useState<DispatchAccount[]>([]);
  const [progress, setProgress] = useState<PlanProgress | null>(null);
  const [records, setRecords] = useState<DispatchRecord[]>([]);
  const [recordsTotal, setRecordsTotal] = useState(0);
  const [recordsPage, setRecordsPage] = useState(1);
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [filterAccountIdx, setFilterAccountIdx] = useState<number | undefined>();
  const [filterStatus, setFilterStatus] = useState<string | undefined>();

  // 取下一批
  const [nextAccountIdx, setNextAccountIdx] = useState<number>(1);
  const [nextBatchSize, setNextBatchSize] = useState(20);
  const [nextResult, setNextResult] = useState<NextBatchResponse | null>(null);
  const [nextLoading, setNextLoading] = useState(false);
  const [selectedSeqs, setSelectedSeqs] = useState<React.Key[]>([]);

  const fetchSeqRef = useRef(0);

  // ============ 列表 ============
  const fetchPlans = useCallback(async () => {
    setPlansLoading(true);
    try {
      const res = await listPlans({ page: 1, page_size: 50 });
      setPlans(res.items || []);
    } catch (e: any) {
      message.error(e?.message || '加载计划失败');
    } finally {
      setPlansLoading(false);
    }
  }, []);

  useEffect(() => { fetchPlans(); }, [fetchPlans]);

  // ============ 创建计划 ============
  const handlePreview = useCallback(async () => {
    try {
      const v = await createForm.validateFields();
      setPreviewing(true);
      const res = await previewCustomers({
        platform: v.platform,
        filter_keywords: v.filter_keywords || '',
        min_lead_score: v.min_lead_score || 0,
      });
      setPreviewTotal(res.total || 0);
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error(e?.message || '预览失败');
    } finally {
      setPreviewing(false);
    }
  }, [createForm]);

  const handleCreate = useCallback(async () => {
    try {
      const v = await createForm.validateFields();
      if (!v.accounts || v.accounts.length === 0) {
        message.warning('请至少添加一个账号');
        return;
      }
      setCreating(true);
      const accounts: AccountConfig[] = v.accounts.map((a: any, i: number) => ({
        account_alias: a.account_alias || `账号${i + 1}`,
        cookie_id: a.cookie_id || '',
        batch_size: a.batch_size || 20,
      }));
      await createPlan({
        name: v.name,
        platform: v.platform,
        filter_keywords: v.filter_keywords || '',
        min_lead_score: v.min_lead_score || 0,
        accounts,
      });
      message.success('计划创建成功');
      setCreateOpen(false);
      createForm.resetFields();
      setPreviewTotal(null);
      fetchPlans();
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error(e?.message || '创建失败');
    } finally {
      setCreating(false);
    }
  }, [createForm, fetchPlans]);

  // ============ 详情 ============
  const fetchDetail = useCallback(async (planId: string) => {
    const seq = ++fetchSeqRef.current;
    try {
      const [detail, accs, prog] = await Promise.all([
        getPlan(planId),
        listAccounts(planId),
        getProgress(planId),
      ]);
      if (seq !== fetchSeqRef.current) return;
      setPlanDetail(detail);
      setAccounts(accs || []);
      setProgress(prog || null);
    } catch (e: any) {
      message.error(e?.message || '加载详情失败');
    }
  }, []);

  const fetchRecords = useCallback(async (page = 1) => {
    if (!selectedPlanId) return;
    setRecordsLoading(true);
    setRecordsPage(page);
    try {
      const res = await listRecords(selectedPlanId, {
        account_idx: filterAccountIdx,
        status: filterStatus,
        page,
        page_size: 20,
      });
      setRecords(res.items || []);
      setRecordsTotal(res.total || 0);
    } catch (e: any) {
      message.error(e?.message || '加载记录失败');
    } finally {
      setRecordsLoading(false);
    }
  }, [selectedPlanId, filterAccountIdx, filterStatus]);

  useEffect(() => {
    if (selectedPlanId) {
      fetchDetail(selectedPlanId);
      fetchRecords(1);
    }
  }, [selectedPlanId, fetchDetail, fetchRecords]);

  // ============ 取下一批 ============
  const handleGetNext = useCallback(async () => {
    if (!selectedPlanId) return;
    setNextLoading(true);
    setSelectedSeqs([]);
    try {
      const res = await getNext(selectedPlanId, {
        account_idx: nextAccountIdx,
        batch_size: nextBatchSize,
      });
      setNextResult(res);
      if (!res.ok) {
        message.error(res.reason || '获取失败');
      } else if (!res.seqs || res.seqs.length === 0) {
        message.info(res.message || '本账号区间已发完，且无其他账号漏单');
      } else {
        const leak = (res.leaked_count || 0) > 0 ? `（含其他账号漏单 ${res.leaked_count} 条）` : '';
        message.success(`取到 ${res.seqs.length} 条待发客户${leak}`);
      }
      fetchDetail(selectedPlanId);
    } catch (e: any) {
      message.error(e?.message || '取下一批失败');
    } finally {
      setNextLoading(false);
    }
  }, [selectedPlanId, nextAccountIdx, nextBatchSize, fetchDetail]);

  // ============ 标记已回复 ============
  const handleBatchMarkReplied = useCallback(async () => {
    if (!selectedPlanId || !nextResult || !nextResult.customer_lead_ids || selectedSeqs.length === 0) {
      message.warning('请先选择要标记的客户');
      return;
    }
    try {
      // seqs → customer_lead_ids 映射
      const seqToLeadId = new Map<number, number>();
      nextResult.seqs.forEach((s, i) => {
        const lid = nextResult.customer_lead_ids?.[i];
        if (lid) seqToLeadId.set(s, lid);
      });
      const leadIds = selectedSeqs.map(k => seqToLeadId.get(Number(k))).filter(Boolean) as number[];
      if (leadIds.length === 0) {
        message.warning('无法解析选中的客户ID');
        return;
      }
      const res = await batchMarkReplied(selectedPlanId, {
        customer_lead_ids: leadIds,
        account_idx: nextAccountIdx,
      });
      message.success(`已标记 ${res.success}/${res.total} 条为已回复`);
      setSelectedSeqs([]);
      // 从 nextResult 中移除已标记的
      setNextResult(prev => {
        if (!prev) return prev;
        const newSeqs: number[] = [];
        const newLeadIds: number[] = [];
        const newCustomers: typeof prev.customers = [];
        prev.seqs.forEach((s, i) => {
          if (!selectedSeqs.includes(s)) {
            newSeqs.push(s);
            if (prev.customer_lead_ids) newLeadIds.push(prev.customer_lead_ids[i]);
            if (prev.customers) newCustomers.push(prev.customers[i]);
          }
        });
        return { ...prev, seqs: newSeqs, customer_lead_ids: newLeadIds, customers: newCustomers };
      });
      fetchDetail(selectedPlanId);
      fetchRecords(recordsPage);
    } catch (e: any) {
      message.error(e?.message || '标记失败');
    }
  }, [selectedPlanId, nextResult, selectedSeqs, nextAccountIdx, fetchDetail, fetchRecords, recordsPage]);

  const handleDeletePlan = useCallback(async (planId: string) => {
    try {
      await deletePlan(planId);
      message.success('已删除');
      if (selectedPlanId === planId) {
        setSelectedPlanId(null);
        setPlanDetail(null);
      }
      fetchPlans();
    } catch (e: any) {
      message.error(e?.message || '删除失败');
    }
  }, [selectedPlanId, fetchPlans]);

  // ============ 渲染 ============
  const planColumns = [
    {
      title: '计划名称', dataIndex: 'name', key: 'name',
      render: (v: string, r: DispatchPlan) => (
        <a onClick={() => { setSelectedPlanId(r.plan_id); setTab('detail'); }}>
          {v}
        </a>
      ),
    },
    { title: '平台', dataIndex: 'platform', key: 'platform', width: 90,
      render: (v: string) => PLATFORM_OPTIONS.find(p => p.value === v)?.label || v },
    { title: '客户数', dataIndex: 'total_customers', key: 'total', width: 80, align: 'center' as const },
    { title: '账号数', dataIndex: 'total_accounts', key: 'acc', width: 80, align: 'center' as const },
    {
      title: '覆盖率', key: 'progress', width: 200,
      render: (_: unknown, r: DispatchPlan) => {
        const pct = r.coverage_pct || 0;
        return (
          <Tooltip title={`已回复 ${r.replied || 0}/${r.total_customers}`}>
            <Progress percent={pct} size="small" status={pct >= 100 ? 'success' : 'active'} />
          </Tooltip>
        );
      },
    },
    {
      title: '创建时间', dataIndex: 'created_at', key: 'created', width: 160,
      render: (v: number) => v ? new Date(v * 1000).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作', key: 'op', width: 140,
      render: (_: unknown, r: DispatchPlan) => (
        <Space>
          <Button size="small" onClick={() => { setSelectedPlanId(r.plan_id); setTab('detail'); }}>
            查看
          </Button>
          <Popconfirm title="确认删除该计划？" onConfirm={() => handleDeletePlan(r.plan_id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const recordColumns = [
    { title: '序号', dataIndex: 'customer_seq', key: 'seq', width: 70,
      render: (v: number) => <Text strong>#{String(v).padStart(4, '0')}</Text> },
    { title: '客户昵称', dataIndex: 'customer_nickname', key: 'nick', ellipsis: true,
      render: (v: string) => v || '-' },
    { title: '意向分', dataIndex: 'customer_lead_score', key: 'score', width: 80,
      render: (v: number) => v ? <Tag color={v >= 70 ? 'red' : v >= 50 ? 'orange' : 'default'}>{v}</Tag> : '-' },
    { title: '意向类型', dataIndex: 'customer_intent_type', key: 'it', width: 100,
      render: (v: string) => v ? <Tag>{v}</Tag> : '-' },
    { title: '分配账号', dataIndex: 'assigned_account_idx', key: 'acc', width: 90,
      render: (v: number) => `#${v}` },
    { title: '发送账号', dataIndex: 'sent_by_account', key: 'sacc', width: 90,
      render: (v: number | null) => v ? `#${v}` : '-' },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (v: string) => <Tag color={STATUS_COLORS[v]}>{STATUS_LABELS[v] || v}</Tag>,
    },
    {
      title: '发送时间', dataIndex: 'sent_at', key: 'sent', width: 160,
      render: (v: number) => v ? new Date(v * 1000).toLocaleString('zh-CN') : '-',
    },
  ];

  // 把 NextBatchResponse 转换为表格数据
  const nextRows: NextRow[] = nextResult?.seqs
    ? nextResult.seqs.map((seq, i) => ({
        seq,
        customer: nextResult.customers?.[i],
      }))
    : [];

  const nextColumns = [
    { title: '序号', dataIndex: 'seq', key: 'seq', width: 70,
      render: (v: number) => <Text strong>#{String(v).padStart(4, '0')}</Text> },
    { title: '客户昵称', key: 'nick', ellipsis: true,
      render: (_: unknown, r: NextRow) => r.customer?.nickname || '(未关联客户线索)' },
    { title: '意向分', key: 'score', width: 80,
      render: (_: unknown, r: NextRow) => {
        const v = r.customer?.lead_score;
        return v ? <Tag color={v >= 70 ? 'red' : v >= 50 ? 'orange' : 'default'}>{v}</Tag> : '-';
      } },
    { title: '意向类型', key: 'it', width: 100,
      render: (_: unknown, r: NextRow) => r.customer?.intent_type ? <Tag>{r.customer.intent_type}</Tag> : '-' },
    { title: '是否漏单', key: 'leak', width: 100,
      render: (_: unknown, r: NextRow) => {
        const ownIdx = nextResult?.account_idx;
        // 漏单判断：seq 不属于当前账号的区间
        const acc = accounts.find(a => a.range_start <= r.seq && r.seq <= a.range_end);
        const isLeak = acc && acc.account_idx !== ownIdx;
        return isLeak
          ? <Tag color="orange">漏单(原#{acc?.account_idx})</Tag>
          : <Tag color="green">本账号</Tag>;
      } },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Card
        title={<Space><TeamOutlined />客户分配调度</Space>}
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={fetchPlans}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
              新建计划
            </Button>
          </Space>
        }
      >
        <Tabs activeKey={tab} onChange={setTab} items={[
          { key: 'plans', label: '计划列表', children: (
            <Table
              dataSource={plans}
              columns={planColumns}
              rowKey="plan_id"
              loading={plansLoading}
              pagination={{ pageSize: 20, showSizeChanger: false }}
              locale={{ emptyText: <Empty description="暂无分配计划" /> }}
            />
          )},
          { key: 'detail', label: '计划详情', disabled: !selectedPlanId, children: (
            planDetail ? (
              <Space direction="vertical" style={{ width: '100%' }} size="middle">
                {/* 概览 */}
                <Card size="small" title="计划概览">
                  <Descriptions size="small" column={4}>
                    <Descriptions.Item label="计划名称">{planDetail.name}</Descriptions.Item>
                    <Descriptions.Item label="平台">
                      {PLATFORM_OPTIONS.find(p => p.value === planDetail.platform)?.label || planDetail.platform}
                    </Descriptions.Item>
                    <Descriptions.Item label="客户总数">{planDetail.total_customers}</Descriptions.Item>
                    <Descriptions.Item label="账号数">{planDetail.total_accounts}</Descriptions.Item>
                    <Descriptions.Item label="筛选关键词">{planDetail.filter_keywords || '-'}</Descriptions.Item>
                    <Descriptions.Item label="最低意向分">{planDetail.min_lead_score}</Descriptions.Item>
                  </Descriptions>
                </Card>

                {/* 进度统计 */}
                {progress && (
                  <Row gutter={16}>
                    <Col span={6}>
                      <Card size="small">
                        <Statistic title="覆盖率" value={progress.coverage_pct} suffix="%" />
                      </Card>
                    </Col>
                    <Col span={6}>
                      <Card size="small">
                        <Statistic title="已发送" value={(progress.total || 0) - progress.pending}
                          prefix={<ThunderboltOutlined />} />
                      </Card>
                    </Col>
                    <Col span={6}>
                      <Card size="small">
                        <Statistic title="已回复" value={progress.replied}
                          prefix={<CheckCircleOutlined />} valueStyle={{ color: '#52c41a' }} />
                      </Card>
                    </Col>
                    <Col span={6}>
                      <Card size="small">
                        <Statistic title="待发送" value={progress.pending} />
                      </Card>
                    </Col>
                  </Row>
                )}

                {/* 账号区间分配 */}
                <Card size="small" title={<Space><UserOutlined />账号区间分配</Space>}>
                  <Table
                    dataSource={accounts}
                    rowKey="account_idx"
                    pagination={false}
                    size="small"
                    columns={[
                      { title: '账号序号', dataIndex: 'account_idx', key: 'idx', width: 80,
                        render: (v: number) => <Text strong>#{v}</Text> },
                      { title: '昵称', dataIndex: 'account_alias', key: 'nick' },
                      { title: '负责区间', key: 'range',
                        render: (_: unknown, r: DispatchAccount) =>
                          <Tag color="blue">#{String(r.range_start).padStart(4, '0')} - #{String(r.range_end).padStart(4, '0')}</Tag> },
                      { title: '区间容量', dataIndex: 'batch_size', key: 'cap', width: 90 },
                      { title: '已发送', dataIndex: 'total_sent', key: 'sent', width: 80 },
                      { title: '已回复', dataIndex: 'total_replied', key: 'replied', width: 80,
                        render: (v: number) => <Text style={{ color: '#52c41a' }}>{v}</Text> },
                    ]}
                  />
                </Card>

                {/* 取下一批 */}
                <Card size="small" title={<Space><ThunderboltOutlined />取下一批待发客户</Space>}>
                  <Space style={{ marginBottom: 12 }} wrap>
                    <Text>账号序号：</Text>
                    <InputNumber min={1} max={planDetail.total_accounts} value={nextAccountIdx}
                      onChange={v => setNextAccountIdx(Number(v) || 1)} style={{ width: 80 }} />
                    <Text>批次大小：</Text>
                    <InputNumber min={1} max={200} value={nextBatchSize}
                      onChange={v => setNextBatchSize(Number(v) || 20)} style={{ width: 80 }} />
                    <Button type="primary" loading={nextLoading} onClick={handleGetNext}
                      icon={<ThunderboltOutlined />}>
                      取下一批
                    </Button>
                    {nextResult && nextResult.seqs && nextResult.seqs.length > 0 && (
                      <>
                        <Button type="primary" ghost icon={<CheckCircleOutlined />}
                          onClick={handleBatchMarkReplied}
                          disabled={selectedSeqs.length === 0}>
                          标记选中 {selectedSeqs.length} 条为已回复
                        </Button>
                        <Text type="secondary">共 {nextResult.seqs.length} 条，选中 {selectedSeqs.length} 条</Text>
                      </>
                    )}
                  </Space>
                  <Alert
                    type="info" showIcon
                    message="调度策略"
                    description={
                      <ul style={{ marginBottom: 0, paddingLeft: 18 }}>
                        <li>优先发送本账号区间内的 pending 客户（编号连续推进）</li>
                        <li>本区间发完后，自动补充其他账号漏单（sent 但未 replied）的客户，确保全覆盖</li>
                        <li>已 replied 的客户会被所有账号自动跳过（去重）</li>
                      </ul>
                    }
                    style={{ marginBottom: 12 }}
                  />
                  {nextResult && (
                    <Table
                      dataSource={nextRows}
                      columns={nextColumns}
                      rowKey="seq"
                      pagination={false}
                      size="small"
                      rowSelection={{
                        selectedRowKeys: selectedSeqs,
                        onChange: setSelectedSeqs,
                      }}
                      locale={{ emptyText: <Empty description="无待发客户" /> }}
                    />
                  )}
                </Card>

                {/* 客户分配记录 */}
                <Card size="small" title="客户分配记录">
                  <Space style={{ marginBottom: 12 }} wrap>
                    <Select
                      placeholder="按账号筛选" allowClear style={{ width: 150 }}
                      value={filterAccountIdx}
                      onChange={v => { setFilterAccountIdx(v); }}
                      options={accounts.map(a => ({ value: a.account_idx, label: `#${a.account_idx} ${a.account_alias}` }))}
                    />
                    <Select
                      placeholder="按状态筛选" allowClear style={{ width: 150 }}
                      value={filterStatus}
                      onChange={v => { setFilterStatus(v); }}
                      options={Object.entries(STATUS_LABELS).map(([v, l]) => ({ value: v, label: l }))}
                    />
                    <Button icon={<ReloadOutlined />} onClick={() => fetchRecords(1)}>刷新</Button>
                  </Space>
                  <Table
                    dataSource={records}
                    columns={recordColumns}
                    rowKey="id"
                    loading={recordsLoading}
                    size="small"
                    pagination={{
                      current: recordsPage,
                      total: recordsTotal,
                      pageSize: 20,
                      onChange: fetchRecords,
                      showSizeChanger: false,
                    }}
                  />
                </Card>
              </Space>
            ) : (
              <Empty description="请从计划列表选择一个计划查看详情" />
            )
          )},
        ]} />
      </Card>

      {/* 创建计划弹窗 */}
      <Modal
        title="新建客户分配计划"
        open={createOpen}
        onCancel={() => { setCreateOpen(false); setPreviewTotal(null); }}
        onOk={handleCreate}
        confirmLoading={creating}
        width={720}
        okText="创建"
        cancelText="取消"
      >
        <Form form={createForm} layout="vertical" initialValues={{
          platform: 'douyin',
          min_lead_score: 0,
          accounts: [
            { account_alias: '账号1', cookie_id: '', batch_size: 20 },
            { account_alias: '账号2', cookie_id: '', batch_size: 38 },
          ],
        }}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="name" label="计划名称" rules={[{ required: true, message: '请输入' }]}>
                <Input placeholder="如：成都火锅客户第一批" />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="platform" label="平台" rules={[{ required: true }]}>
                <Select options={PLATFORM_OPTIONS} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="min_lead_score" label="最低意向分">
                <InputNumber min={0} max={100} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="filter_keywords" label="客户筛选关键词（逗号分隔，留空表示全部客户）">
            <Input placeholder="如：火锅,加盟,咨询" />
          </Form.Item>

          <Space style={{ marginBottom: 12 }}>
            <Button loading={previewing} onClick={handlePreview}>预览客户数</Button>
            {previewTotal !== null && (
              <Text type={previewTotal > 0 ? 'success' : 'danger'}>
                符合条件的客户共 {previewTotal} 人
              </Text>
            )}
          </Space>

          <Form.List name="accounts">
            {(fields, { add, remove }) => (
              <>
                <div style={{ marginBottom: 8 }}>
                  <Text strong>账号区间分配</Text>
                  <Text type="secondary" style={{ marginLeft: 8 }}>
                    每个账号的 batch_size 决定其负责的客户区间容量，按顺序累加分配
                  </Text>
                </div>
                {fields.map(f => (
                  <Row gutter={8} key={f.key} style={{ marginBottom: 8 }} align="middle">
                    <Col span={1}><Text>#{f.name + 1}</Text></Col>
                    <Col span={7}>
                      <Form.Item name={[f.name, 'account_alias']} noStyle>
                        <Input placeholder="账号昵称" />
                      </Form.Item>
                    </Col>
                    <Col span={9}>
                      <Form.Item name={[f.name, 'cookie_id']} noStyle>
                        <Input placeholder="关联cookie/账号ID（可选）" />
                      </Form.Item>
                    </Col>
                    <Col span={5}>
                      <Form.Item name={[f.name, 'batch_size']} noStyle>
                        <InputNumber min={1} max={1000} style={{ width: '100%' }} placeholder="区间容量" />
                      </Form.Item>
                    </Col>
                    <Col span={2}>
                      {fields.length > 1 && (
                        <Button danger icon={<DeleteOutlined />} onClick={() => remove(f.name)} size="small" />
                      )}
                    </Col>
                  </Row>
                ))}
                <Button type="dashed" icon={<PlusOutlined />} onClick={() => add({ account_alias: `账号${fields.length + 1}`, cookie_id: '', batch_size: 20 })}>
                  添加账号
                </Button>
              </>
            )}
          </Form.List>
        </Form>
      </Modal>
    </div>
  );
};

export default CustomerDispatch;
