import { message } from '../utils/antdMessage';
import React, { useEffect, useState, useCallback } from 'react';
import { Card, Table, Button, Space, Modal, Form, Input, InputNumber, Select, Switch, Tag, Popconfirm, Row, Col, Statistic, Tooltip, Empty, Spin } from 'antd';
import {
  ReloadOutlined, PlusOutlined, EditOutlined, DeleteOutlined, VideoCameraOutlined,
  ThunderboltOutlined, ExperimentOutlined,
} from '@ant-design/icons';
import { videoConfigApi, batchVideoApi } from '../api/prdGap';

const { Option } = Select;

const VideoGenConfig: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<any[]>([]);
  const [validValues, setValidValues] = useState<any>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<any>(null);
  const [form] = Form.useForm();
  const [batchModalOpen, setBatchModalOpen] = useState(false);
  const [batchTasks, setBatchTasks] = useState<any[]>([]);

  const fetchList = useCallback(async () => {
    setLoading(true);
    try {
      const [listRes, vvRes, batchRes] = await Promise.all([
        videoConfigApi.list(),
        videoConfigApi.validValues().catch(() => null),
        batchVideoApi.list().catch(() => ({ data: { items: [] } })),
      ]);
      const data = listRes?.data || listRes || {};
      setItems(data.items || []);
      setValidValues(vvRes?.data || null);
      setBatchTasks(batchRes?.data?.items || []);
    } catch (e) {
      console.error('fetch video configs failed', e);
      message.error('加载视频配置失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchList();
  }, [fetchList]);

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({
      duration_seconds: 30,
      resolution: '720p',
      aspect_ratio: '9:16',
      visual_style: 'modern',
      voice_timbre: 'female_warm',
      subtitle_style: 'white_bold_black_outline',
      bgm_mood: 'upbeat',
      enable_subtitle: true,
      enable_voiceover: true,
      enable_bgm: true,
    });
    setModalOpen(true);
  };

  const openEdit = (record: any) => {
    setEditing(record);
    form.setFieldsValue(record);
    setModalOpen(true);
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      // 编辑暂不支持（后端 update 接口未提供），统一走 create
      await videoConfigApi.create(values);
      message.success(editing ? '已重建配置' : '创建成功');
      setModalOpen(false);
      fetchList();
    } catch (e: any) {
      if (e?.errorFields) return;
      message.error('保存失败');
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await videoConfigApi.delete(id);
      message.success('已删除');
      fetchList();
    } catch {
      message.error('删除失败');
    }
  };

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      render: (v: string, r: any) => (
        <Space>
          <strong>{v}</strong>
          {r.is_preset && <Tag color="purple">预设</Tag>}
        </Space>
      ),
    },
    { title: '时长(秒)', dataIndex: 'duration_seconds', width: 90 },
    { title: '分辨率', dataIndex: 'resolution', width: 90 },
    { title: '比例', dataIndex: 'aspect_ratio', width: 80 },
    { title: '画面风格', dataIndex: 'visual_style', width: 110 },
    { title: '配音', dataIndex: 'voice_timbre', width: 120 },
    { title: '字幕', dataIndex: 'subtitle_style', width: 150,
      render: (v: string) => <span style={{ wordBreak: 'break-all' }}>{v}</span> },
    { title: 'BGM', dataIndex: 'bgm_mood', width: 100 },
    {
      title: '操作', width: 120,
      render: (_: any, r: any) => (
        <Space size="small">
          <Tooltip title="编辑">
            <Button size="small" type="text" icon={<EditOutlined />} onClick={() => openEdit(r)} />
          </Tooltip>
          {!r.is_preset && (
            <Popconfirm title="确认删除?" onConfirm={() => handleDelete(r.config_id)}>
              <Button size="small" type="text" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <h3 style={{ margin: 0 }}>
            <VideoCameraOutlined style={{ color: '#1677ff', marginRight: 8 }} />
            视频参数配置
          </h3>
        </Col>
        <Col>
          <Space>
            <Button icon={<ExperimentOutlined />} onClick={() => setBatchModalOpen(true)}>
              批量生成任务
            </Button>
            <Button icon={<ReloadOutlined />} onClick={fetchList} loading={loading}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建配置</Button>
          </Space>
        </Col>
      </Row>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="配置总数" value={items.length} prefix={<VideoCameraOutlined />} /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="预设" value={items.filter((i) => i.is_preset).length} /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="自定义" value={items.filter((i) => !i.is_preset).length} /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card size="small"><Statistic title="批量任务" value={batchTasks.length} prefix={<ThunderboltOutlined />} /></Card>
        </Col>
      </Row>

      <Card>
        <Spin spinning={loading}>
          {items.length === 0 && !loading ? (
            <Empty description="暂无配置，点击「新建配置」创建第一个">
              <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新建配置</Button>
            </Empty>
          ) : (
            <Table
              rowKey="config_id"
              columns={columns}
              dataSource={items}
              size="middle"
              pagination={{ pageSize: 15 }}
              scroll={{ x: 1000 }}
            />
          )}
        </Spin>
      </Card>

      <Modal
        title={editing ? '编辑配置' : '新建视频参数配置'}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => setModalOpen(false)}
        width={680}
        okText="保存"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="配置名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如：科技解说-竖屏30秒" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="duration_seconds" label="时长(秒)">
                <InputNumber min={5} max={120} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="resolution" label="分辨率">
                <Select>
                  {(validValues?.resolutions || ['480p', '720p', '1080p']).map((v: string) => (
                    <Option key={v} value={v}>{v}</Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="aspect_ratio" label="宽高比">
                <Select>
                  {(validValues?.aspect_ratios || ['9:16', '16:9', '1:1']).map((v: string) => (
                    <Option key={v} value={v}>{v}</Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="visual_style" label="画面风格">
                <Select>
                  {(validValues?.visual_styles || ['modern', 'tech', 'warm']).map((v: string) => (
                    <Option key={v} value={v}>{v}</Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="voice_timbre" label="配音音色">
                <Select>
                  {(validValues?.voice_timbres || ['female_warm', 'male_deep']).map((v: string) => (
                    <Option key={v} value={v}>{v}</Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="bgm_mood" label="BGM 情绪">
                <Select>
                  {(validValues?.bgm_moods || ['upbeat', 'calm', 'energetic']).map((v: string) => (
                    <Option key={v} value={v}>{v}</Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="subtitle_style" label="字幕样式">
            <Select>
              {(validValues?.subtitle_styles || ['white_bold_black_outline']).map((v: string) => (
                <Option key={v} value={v}>{v}</Option>
              ))}
            </Select>
          </Form.Item>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="enable_subtitle" label="启用字幕" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="enable_voiceover" label="启用配音" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="enable_bgm" label="启用BGM" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      <Modal
        title="批量生成任务"
        open={batchModalOpen}
        onCancel={() => setBatchModalOpen(false)}
        footer={null}
        width={700}
      >
        {batchTasks.length === 0 ? (
          <Empty description="暂无批量生成任务" />
        ) : (
          <Table
            rowKey="task_id"
            size="small"
            dataSource={batchTasks}
            pagination={{ pageSize: 10 }}
            columns={[
              { title: '任务ID', dataIndex: 'task_id', render: (v: string) => <span style={{ wordBreak: 'break-all' }}>{v?.slice(0, 8)}...</span> },
              { title: '状态', dataIndex: 'status', render: (v: string) => <Tag color={v === 'completed' ? 'green' : v === 'failed' ? 'red' : 'processing'}>{v}</Tag> },
              { title: '进度', dataIndex: 'progress', render: (v: number) => v ? `${(v * 100).toFixed(0)}%` : '-' },
              { title: '总数', dataIndex: 'total', width: 70 },
              { title: '已完成', dataIndex: 'completed', width: 70 },
              { title: '失败', dataIndex: 'failed', width: 60 },
            ]}
          />
        )}
      </Modal>
    </div>
  );
};

export default VideoGenConfig;
