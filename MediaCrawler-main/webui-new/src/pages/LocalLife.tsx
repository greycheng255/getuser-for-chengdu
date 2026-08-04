import { message } from '../utils/antdMessage';
import React, { useEffect, useState, useCallback, useRef } from 'react';
import {
  Card, Table, Tag, Button, Space, Modal, Form, Input, Select,
  Row, Col, Tabs, Empty, Alert, InputNumber,
  Tooltip, Popconfirm, Rate, Descriptions,
} from 'antd';
import {
  ReloadOutlined, SearchOutlined, SaveOutlined, ExportOutlined,
  EditOutlined, DeleteOutlined,
  ShopOutlined, CopyOutlined, LinkOutlined,
} from '@ant-design/icons';
import {
  getConfig, search, saveBusiness, batchSave, listBusinesses,
  updateBusiness, deleteBusiness, exportBusinesses, getCities, getCategories,
  type AmapPoi, type LocalBusiness, type CityCount, type CategoryCount,
} from '../api/localLife';

const LocalLife: React.FC = () => {
  const [tab, setTab] = useState('search');
  const [configured, setConfigured] = useState<boolean | null>(null);

  // 搜索
  const [searchForm] = Form.useForm();
  const [searching, setSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<AmapPoi[]>([]);
  const [searchTotal, setSearchTotal] = useState(0);
  const [searchPage, setSearchPage] = useState(1);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);

  // 我的商家
  const [bizList, setBizList] = useState<LocalBusiness[]>([]);
  const [bizTotal, setBizTotal] = useState(0);
  const [bizLoading, setBizLoading] = useState(false);
  const [bizPage, setBizPage] = useState(1);
  const [bizCity, setBizCity] = useState<string>();
  const [bizCategory, setBizCategory] = useState<string>();
  const [bizKeyword, setBizKeyword] = useState<string>();
  const [cities, setCities] = useState<CityCount[]>([]);
  const [categories, setCategories] = useState<CategoryCount[]>([]);
  const [editOpen, setEditOpen] = useState(false);
  const [editing, setEditing] = useState<LocalBusiness | null>(null);
  const [editForm] = Form.useForm();
  const fetchSeqRef = useRef(0);

  // ============ 初始化 ============
  const fetchConfig = useCallback(async () => {
    try {
      const res = await getConfig();
      setConfigured(!!res.configured);
    } catch (e) {
      setConfigured(false);
    }
  }, []);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  // ============ 搜索 ============
  const doSearch = useCallback(async (newPage = 1) => {
    try {
      const values = await searchForm.validateFields();
      setSearching(true);
      setSearchPage(newPage);
      const res = await search({
        keyword: values.keyword.trim(),
        city: values.city?.trim() || undefined,
        page: newPage,
        page_size: 20,
      });
      setSearchResults(res.items || []);
      setSearchTotal(res.total || 0);
      if (res.message) message.warning(res.message);
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error(e?.message || '搜索失败');
    } finally {
      setSearching(false);
    }
  }, [searchForm]);

  const handleSaveOne = async (poi: AmapPoi) => {
    try {
      const res = await saveBusiness({ platform: 'amap', poi_id: poi.poi_id });
      if (res.saved) {
        message.success(`已保存：${poi.name}`);
      } else {
        message.warning(`保存失败：${res.reason || '未知原因'}`);
      }
    } catch (e: any) {
      message.error(e?.message || '保存失败');
    }
  };

  const handleBatchSave = async () => {
    if (selectedRowKeys.length === 0) {
      message.warning('请先勾选要保存的商家');
      return;
    }
    const items = searchResults.filter(r => selectedRowKeys.includes(r.poi_id));
    try {
      const res = await batchSave({ items, platform: 'amap' });
      message.success(`已保存 ${res.saved} 个，跳过 ${res.skipped} 个`);
      setSelectedRowKeys([]);
    } catch (e: any) {
      message.error(e?.message || '批量保存失败');
    }
  };

  const copyText = (text: string) => {
    if (!text) {
      message.warning('无内容可复制');
      return;
    }
    navigator.clipboard.writeText(text).then(
      () => message.success('已复制到剪贴板'),
      () => message.error('复制失败')
    );
  };

  // ============ 我的商家 ============
  const fetchBusinesses = useCallback(async () => {
    const seq = ++fetchSeqRef.current;
    setBizLoading(true);
    try {
      const res = await listBusinesses({
        city: bizCity, category: bizCategory, keyword: bizKeyword,
        page: bizPage, page_size: 20,
      });
      if (seq !== fetchSeqRef.current) return;
      setBizList(res.items || []);
      setBizTotal(res.total || 0);
    } catch (e: any) {
      message.error(e?.message || '获取商家列表失败');
    } finally {
      if (seq === fetchSeqRef.current) setBizLoading(false);
    }
  }, [bizCity, bizCategory, bizKeyword, bizPage]);

  const fetchMeta = useCallback(async () => {
    try {
      const [cs, cats] = await Promise.all([getCities(), getCategories()]);
      setCities(cs || []);
      setCategories(cats || []);
    } catch (e) {
      // ignore
    }
  }, []);

  useEffect(() => {
    if (tab === 'mine') {
      fetchBusinesses();
      fetchMeta();
    }
  }, [tab, fetchBusinesses, fetchMeta]);

  const handleEdit = (biz: LocalBusiness) => {
    setEditing(biz);
    editForm.setFieldsValue({
      name: biz.name,
      phone: biz.phone,
      address: biz.address,
      business_hours: biz.business_hours,
      category: biz.category,
      city: biz.city,
      district: biz.district,
      price_avg: biz.price_avg,
      rating: biz.rating,
    });
    setEditOpen(true);
  };

  const handleEditSubmit = async () => {
    if (!editing) return;
    try {
      const values = await editForm.validateFields();
      await updateBusiness(editing.business_id, values);
      message.success('已更新');
      setEditOpen(false);
      setEditing(null);
      fetchBusinesses();
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error(e?.message || '更新失败');
    }
  };

  const handleDelete = async (businessId: string) => {
    try {
      await deleteBusiness(businessId);
      message.success('已删除');
      fetchBusinesses();
    } catch (e: any) {
      message.error(e?.message || '删除失败');
    }
  };

  const handleExport = async () => {
    try {
      const blob = await exportBusinesses({
        city: bizCity, category: bizCategory, keyword: bizKeyword,
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `local_businesses_${Date.now()}.xlsx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      message.success('导出成功');
    } catch (e: any) {
      message.error(e?.message || '导出失败');
    }
  };

  // ============ 表格列 ============

  const searchColumns = [
    {
      title: '商家名称', dataIndex: 'name', ellipsis: false,
      render: (v: string, r: AmapPoi) => (
        <div style={{ maxWidth: 220, wordBreak: 'break-all', whiteSpace: 'normal' }}>
          <div style={{ fontWeight: 500 }}>{v}</div>
          {r.category && <div style={{ fontSize: 11, color: '#999' }}>{r.category}</div>}
        </div>
      ),
    },
    {
      title: '电话', dataIndex: 'phone', width: 160,
      render: (v: string) => v ? (
        <Space>
          <span style={{ wordBreak: 'break-all', whiteSpace: 'normal' }}>{v}</span>
          <Button size="small" type="link" icon={<CopyOutlined />} onClick={() => copyText(v)} />
        </Space>
      ) : <span style={{ color: '#999' }}>-</span>,
    },
    {
      title: '地址', dataIndex: 'address', ellipsis: false,
      render: (v: string, r: AmapPoi) => (
        <div style={{ maxWidth: 260, wordBreak: 'break-all', whiteSpace: 'normal' }}>
          {v}
          {(r.province || r.city || r.district) && (
            <div style={{ fontSize: 11, color: '#999' }}>
              {[r.province, r.city, r.district].filter(Boolean).join(' / ')}
            </div>
          )}
        </div>
      ),
    },
    {
      title: '营业时间', dataIndex: 'business_hours', width: 160, ellipsis: false,
      render: (v: string) => v ? (
        <span style={{ wordBreak: 'break-all', whiteSpace: 'normal' }}>{v}</span>
      ) : <span style={{ color: '#999' }}>-</span>,
    },
    {
      title: '评分', dataIndex: 'rating', width: 90,
      render: (v: number) => v ? <Rate disabled allowHalf value={v / 1} style={{ fontSize: 12 }} /> : <span style={{ color: '#999' }}>-</span>,
    },
    {
      title: '操作', width: 140, fixed: 'right' as const,
      render: (_: any, r: AmapPoi) => (
        <Space size="small">
          <Button size="small" type="primary" icon={<SaveOutlined />} onClick={() => handleSaveOne(r)}>保存</Button>
          {r.longitude && r.latitude && (
            <Tooltip title="在高德地图中打开">
              <Button
                size="small"
                icon={<LinkOutlined />}
                href={`https://uri.amap.com/marker?position=${r.longitude},${r.latitude}&name=${encodeURIComponent(r.name)}`}
                target="_blank"
              />
            </Tooltip>
          )}
        </Space>
      ),
    },
  ];

  const bizColumns = [
    {
      title: '商家名称', dataIndex: 'name', ellipsis: false,
      render: (v: string, r: LocalBusiness) => (
        <div style={{ maxWidth: 220, wordBreak: 'break-all', whiteSpace: 'normal' }}>
          <div style={{ fontWeight: 500 }}>{v}</div>
          {r.category && <div style={{ fontSize: 11, color: '#999' }}>{r.category}</div>}
        </div>
      ),
    },
    {
      title: '电话', dataIndex: 'phone', width: 160,
      render: (v: string) => v ? (
        <Space>
          <span style={{ wordBreak: 'break-all', whiteSpace: 'normal' }}>{v}</span>
          <Button size="small" type="link" icon={<CopyOutlined />} onClick={() => copyText(v)} />
        </Space>
      ) : <span style={{ color: '#999' }}>-</span>,
    },
    {
      title: '地址', dataIndex: 'address', ellipsis: false,
      render: (v: string) => (
        <div style={{ maxWidth: 240, wordBreak: 'break-all', whiteSpace: 'normal' }}>{v}</div>
      ),
    },
    {
      title: '营业时间', dataIndex: 'business_hours', width: 150, ellipsis: false,
      render: (v: string) => v ? (
        <span style={{ wordBreak: 'break-all', whiteSpace: 'normal' }}>{v}</span>
      ) : <span style={{ color: '#999' }}>-</span>,
    },
    {
      title: '评分', dataIndex: 'rating', width: 80,
      render: (v: number) => v ? <span>{v} <Tag color={v >= 4 ? 'green' : v >= 3 ? 'orange' : 'red'}>星</Tag></span> : '-',
    },
    {
      title: '城市', dataIndex: 'city', width: 90,
    },
    {
      title: '操作', width: 140, fixed: 'right' as const,
      render: (_: any, r: LocalBusiness) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => handleEdit(r)} />
          <Popconfirm title="确认删除该商家？" onConfirm={() => handleDelete(r.business_id)}>
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // ============ 渲染 ============

  return (
    <div style={{ padding: 16 }}>
      {configured === false && (
        <Alert
          style={{ marginBottom: 16 }}
          type="warning"
          showIcon
          message="未配置高德地图 API Key"
          description={
            <span>
              请在 .env 中设置 <code>AMAP_API_KEY=你的高德Web服务端Key</code>，
              申请地址：<a href="https://lbs.amap.com/api/webservice/guide/create-project/get-key" target="_blank" rel="noreferrer">高德开放平台</a>
            </span>
          }
        />
      )}

      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          { key: 'search', label: <span><SearchOutlined /> 搜索商家</span> },
          { key: 'mine', label: <span><ShopOutlined /> 我的商家</span> },
        ]}
      />

      {tab === 'search' && (
        <Card>
          <Form form={searchForm} layout="inline" style={{ marginBottom: 16 }}>
            <Form.Item label="关键词" name="keyword" rules={[{ required: true, message: '请输入关键词' }]}>
              <Input placeholder="如：火锅" style={{ width: 200 }} />
            </Form.Item>
            <Form.Item label="城市" name="city">
              <Input placeholder="如：成都（可选）" style={{ width: 160 }} />
            </Form.Item>
            <Form.Item>
              <Space>
                <Button type="primary" icon={<SearchOutlined />} loading={searching} onClick={() => doSearch(1)}>搜索</Button>
                <Button
                  icon={<SaveOutlined />}
                  disabled={selectedRowKeys.length === 0}
                  onClick={handleBatchSave}
                >
                  批量保存 ({selectedRowKeys.length})
                </Button>
              </Space>
            </Form.Item>
          </Form>

          <Table
            rowKey="poi_id"
            loading={searching}
            dataSource={searchResults}
            columns={searchColumns}
            scroll={{ x: 1100 }}
            size="small"
            rowSelection={{
              selectedRowKeys,
              onChange: setSelectedRowKeys,
            }}
            pagination={{
              current: searchPage, pageSize: 20, total: searchTotal,
              onChange: (p) => doSearch(p),
              showTotal: (t) => `共 ${t} 条`,
            }}
            locale={{ emptyText: <Empty description="输入关键词后点击搜索" /> }}
          />
        </Card>
      )}

      {tab === 'mine' && (
        <Card>
          <Space style={{ marginBottom: 16 }} wrap>
            <Select
              allowClear
              placeholder="按城市筛选"
              style={{ width: 160 }}
              value={bizCity}
              onChange={(v) => { setBizCity(v); setBizPage(1); }}
              options={cities.map(c => ({ value: c.city, label: `${c.city} (${c.count})` }))}
            />
            <Select
              allowClear
              placeholder="按品类筛选"
              style={{ width: 180 }}
              value={bizCategory}
              onChange={(v) => { setBizCategory(v); setBizPage(1); }}
              options={categories.map(c => ({ value: c.category, label: `${c.category} (${c.count})` }))}
            />
            <Input
              allowClear
              placeholder="搜索名称/电话/地址"
              style={{ width: 200 }}
              value={bizKeyword}
              onChange={(e) => setBizKeyword(e.target.value)}
              onPressEnter={() => { setBizPage(1); fetchBusinesses(); }}
            />
            <Button icon={<ReloadOutlined />} onClick={fetchBusinesses}>刷新</Button>
            <Button icon={<ExportOutlined />} onClick={handleExport}>导出 Excel</Button>
          </Space>

          <Table
            rowKey="business_id"
            loading={bizLoading}
            dataSource={bizList}
            columns={bizColumns}
            scroll={{ x: 1100 }}
            size="small"
            pagination={{
              current: bizPage, pageSize: 20, total: bizTotal,
              onChange: (p) => setBizPage(p),
              showTotal: (t) => `共 ${t} 条`,
            }}
            locale={{ emptyText: <Empty description="暂无保存的商家，去「搜索商家」Tab 保存吧" /> }}
          />
        </Card>
      )}

      {/* 编辑商家 Modal */}
      <Modal
        title="编辑商家信息"
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
              <Descriptions.Item label="商家ID">{editing.business_id}</Descriptions.Item>
              <Descriptions.Item label="来源">{editing.source}</Descriptions.Item>
              <Descriptions.Item label="POI ID" span={2}>{editing.platform_poi_id}</Descriptions.Item>
            </Descriptions>
            <Form.Item label="商家名称" name="name" rules={[{ required: true }]}>
              <Input />
            </Form.Item>
            <Form.Item label="电话（多个用分号分隔）" name="phone">
              <Input placeholder="如 028-12345678;13800138000" />
            </Form.Item>
            <Form.Item label="地址" name="address">
              <Input />
            </Form.Item>
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item label="城市" name="city"><Input /></Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label="区县" name="district"><Input /></Form.Item>
              </Col>
            </Row>
            <Form.Item label="营业时间" name="business_hours">
              <Input placeholder="如 09:00-22:00" />
            </Form.Item>
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item label="品类" name="category"><Input /></Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label="人均消费（分）" name="price_avg">
                  <InputNumber min={0} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item label="评分（0-5）" name="rating">
              <InputNumber min={0} max={5} step={0.1} style={{ width: '100%' }} />
            </Form.Item>
          </Form>
        )}
      </Modal>
    </div>
  );
};

export default LocalLife;
