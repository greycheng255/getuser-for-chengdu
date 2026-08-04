import { message } from '../utils/antdMessage';
import React, { useEffect, useState, useCallback } from 'react';
import { Card, Table, Tag, Button, Space, Modal, Form, Input, Select, Popconfirm, Row, Col, Empty, Spin, Tabs, Tooltip, InputNumber, Switch, Alert, Typography } from 'antd';
import {
  ReloadOutlined, PlusOutlined, DeleteOutlined, GiftOutlined,
  VideoCameraOutlined, PlayCircleOutlined, FontSizeOutlined,
  QrcodeOutlined, EditOutlined, ThunderboltOutlined, BulbOutlined,
} from '@ant-design/icons';
import { marketingApi } from '../api/prdGap';

const { Option } = Select;
const { TextArea } = Input;
const { Text, Paragraph } = Typography;

// 素材类型 (与后端 MaterialType 枚举对齐: logo/qr_code/link/slogan/event/contact)
const MATERIAL_TYPE_OPTIONS = [
  { value: 'logo', label: 'LOGO', color: 'blue' },
  { value: 'qr_code', label: '二维码', color: 'cyan' },
  { value: 'link', label: '引流链接', color: 'geekblue' },
  { value: 'slogan', label: '品牌口号', color: 'gold' },
  { value: 'event', label: '活动信息', color: 'magenta' },
  { value: 'contact', label: '联系方式', color: 'purple' },
];

const MATERIAL_TYPE_MAP: Record<string, { label: string; color: string }> = MATERIAL_TYPE_OPTIONS
  .reduce((acc, cur) => {
    acc[cur.value] = { label: cur.label, color: cur.color };
    return acc;
  }, {} as Record<string, { label: string; color: string }>);

// 水印位置选项
const POSITION_OPTIONS = [
  'top-left', 'top-right', 'bottom-left', 'bottom-right', 'center',
];

// 植入类型
type InsertType = 'watermark' | 'text-watermark' | 'qr-code' | 'copy-insert' | 'auto-insert';

const INSERT_TYPE_OPTIONS: { value: InsertType; label: string; icon: React.ReactNode }[] = [
  { value: 'watermark', label: '图片水印', icon: <PlayCircleOutlined /> },
  { value: 'text-watermark', label: '文字水印', icon: <FontSizeOutlined /> },
  { value: 'qr-code', label: '二维码贴片', icon: <QrcodeOutlined /> },
  { value: 'copy-insert', label: '文案植入', icon: <EditOutlined /> },
  { value: 'auto-insert', label: 'AI 自动植入', icon: <ThunderboltOutlined /> },
];

const MarketingMaterials: React.FC = () => {
  const [activeTab, setActiveTab] = useState('library');

  return (
    <div>
      <Row justify="space-between" align="middle" style={{ marginBottom: 16 }}>
        <Col>
          <h3 style={{ margin: 0 }}>
            <GiftOutlined style={{ color: '#1677ff', marginRight: 8 }} />
            营销素材管理
          </h3>
        </Col>
      </Row>

      <Card>
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            {
              key: 'library',
              label: (
                <span>
                  <GiftOutlined />
                  素材库
                </span>
              ),
              children: <MaterialLibraryPanel />,
            },
            {
              key: 'video',
              label: (
                <span>
                  <VideoCameraOutlined />
                  视频植入工具
                </span>
              ),
              children: <VideoInsertPanel />,
            },
          ]}
        />
      </Card>
    </div>
  );
};

// ==================== 素材库面板 ====================
const MaterialLibraryPanel: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState<{ material_type?: string; keyword?: string }>({});
  const [modalOpen, setModalOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm();

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await marketingApi.listMaterials({
        material_type: filter.material_type || '',
        only_active: false,
      });
      const data = res?.data || res || {};
      let list: any[] = data.materials || [];
      // 前端关键词过滤 (名称 / 内容 / URL)
      if (filter.keyword) {
        const kw = filter.keyword.toLowerCase();
        list = list.filter((m) =>
          String(m.name || '').toLowerCase().includes(kw) ||
          String(m.content || '').toLowerCase().includes(kw) ||
          String(m.link_url || '').toLowerCase().includes(kw)
        );
      }
      setItems(list);
      setTotal(list.length);
    } catch (e) {
      console.error('fetch materials failed', e);
      message.error('加载营销素材失败');
      setItems([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleAdd = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      const payload: any = {
        name: values.name,
        material_type: values.material_type || 'slogan',
        content: values.content || '',
        link_url: values.link_url || '',
        position: values.position || 'bottom-right',
        is_active: values.is_active !== false,
      };
      // LOGO / 二维码 类型携带 file_path
      if (['logo', 'qr_code'].includes(payload.material_type)) {
        payload.file_path = values.file_path || values.link_url || '';
      }
      await marketingApi.createMaterial(payload);
      message.success('素材添加成功');
      setModalOpen(false);
      form.resetFields();
      fetchData();
    } catch (e: any) {
      if (e?.errorFields) return;
      console.error('create material failed', e);
      message.error('添加素材失败');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await marketingApi.deleteMaterial(id);
      message.success('已删除');
      fetchData();
    } catch (e) {
      console.error('delete material failed', e);
      message.error('删除失败');
    }
  };

  const columns = [
    {
      title: 'ID',
      dataIndex: 'id',
      width: 70,
    },
    {
      title: '类型',
      dataIndex: 'material_type',
      width: 110,
      render: (v: string) => {
        const info = MATERIAL_TYPE_MAP[v] || { label: v, color: 'default' };
        return <Tag color={info.color}>{info.label}</Tag>;
      },
    },
    {
      title: '名称',
      dataIndex: 'name',
      width: 160,
      render: (v: string) => (
        <strong>{v || '-'}</strong>
      ),
    },
    {
      title: '内容预览',
      dataIndex: 'content',
      render: (v: string) => {
        if (!v) return <Text type="secondary">-</Text>;
        const text = String(v);
        if (text.length <= 40) {
          return (
            <div style={{ wordBreak: 'break-all', overflowWrap: 'anywhere', overflowX: 'hidden' }}>
              {text}
            </div>
          );
        }
        return (
          <Tooltip
            title={
              <div style={{ wordBreak: 'break-all', overflowWrap: 'anywhere', maxWidth: 400 }}>
                {text}
              </div>
            }
          >
            <div style={{ wordBreak: 'break-all', overflowWrap: 'anywhere', overflowX: 'hidden' }}>
              {text.slice(0, 40)}...
            </div>
          </Tooltip>
        );
      },
    },
    {
      title: 'URL/文件路径',
      dataIndex: 'link_url',
      width: 200,
      render: (v: string, r: any) => {
        const url = v || r.file_path || '';
        if (!url) return <Text type="secondary">-</Text>;
        return (
          <Tooltip title={<div style={{ wordBreak: 'break-all', overflowWrap: 'anywhere', maxWidth: 400 }}>{url}</div>}>
            <div style={{ wordBreak: 'break-all', overflowWrap: 'anywhere', overflowX: 'hidden', color: '#1677ff' }}>
              {url.length > 35 ? url.slice(0, 35) + '...' : url}
            </div>
          </Tooltip>
        );
      },
    },
    {
      title: '标签/位置',
      dataIndex: 'position',
      width: 120,
      render: (v: string) => v ? <Tag>{v}</Tag> : <Text type="secondary">-</Text>,
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      width: 80,
      render: (v: boolean) => v ? <Tag color="green">启用</Tag> : <Tag color="default">停用</Tag>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 170,
      render: (v: any) => {
        if (!v) return '-';
        try {
          return new Date(v).toLocaleString('zh-CN');
        } catch {
          return String(v);
        }
      },
    },
    {
      title: '操作',
      width: 80,
      render: (_: any, r: any) => (
        <Popconfirm title="确认删除该素材?" onConfirm={() => handleDelete(r.id)}>
          <Button size="small" type="text" danger icon={<DeleteOutlined />} />
        </Popconfirm>
      ),
    },
  ];

  return (
    <div>
      <Space style={{ marginBottom: 16 }} wrap>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
          新增素材
        </Button>
        <Select
          allowClear
          placeholder="类型筛选"
          style={{ width: 150 }}
          value={filter.material_type}
          onChange={(v) => setFilter({ ...filter, material_type: v })}
        >
          {MATERIAL_TYPE_OPTIONS.map((t) => (
            <Option key={t.value} value={t.value}>{t.label}</Option>
          ))}
        </Select>
        <Input.Search
          allowClear
          placeholder="搜索名称/内容/URL"
          style={{ width: 240 }}
          onSearch={(v) => setFilter({ ...filter, keyword: v })}
        />
        <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>刷新</Button>
      </Space>

      <Spin spinning={loading}>
        {items.length === 0 && !loading ? (
          <Empty description="暂无营销素材">
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>
              新增素材
            </Button>
          </Empty>
        ) : (
          <Table
            rowKey="id"
            columns={columns}
            dataSource={items}
            size="middle"
            pagination={{ pageSize: 15, showSizeChanger: true, total }}
            scroll={{ x: 1100 }}
          />
        )}
      </Spin>

      <Modal
        title="新增营销素材"
        open={modalOpen}
        onOk={handleAdd}
        onCancel={() => { setModalOpen(false); form.resetFields(); }}
        okText="添加"
        cancelText="取消"
        confirmLoading={submitting}
        width={560}
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ material_type: 'slogan', position: 'bottom-right', is_active: true }}
        >
          <Form.Item name="material_type" label="素材类型" rules={[{ required: true }]}>
            <Select>
              {MATERIAL_TYPE_OPTIONS.map((t) => (
                <Option key={t.value} value={t.value}>
                  <Tag color={t.color} style={{ marginRight: 4 }}>{t.label}</Tag>
                </Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入素材名称' }]}>
            <Input placeholder="如：品牌LOGO / 双11活动链接" />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, cur) => prev.material_type !== cur.material_type}>
            {({ getFieldValue }) => {
              const t = getFieldValue('material_type');
              return ['logo', 'qr_code'].includes(t) ? (
                <Form.Item name="file_path" label="素材文件路径">
                  <Input placeholder="LOGO/二维码 图片文件路径（如 /data/logo.png）" />
                </Form.Item>
              ) : null;
            }}
          </Form.Item>
          <Form.Item name="content" label="内容">
            <TextArea
              rows={3}
              placeholder="文案内容 / 活动信息 / 联系方式等"
              showCount
              maxLength={2000}
            />
          </Form.Item>
          <Form.Item name="link_url" label="URL（引流链接）">
            <Input placeholder="https://..." />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="position" label="标签/位置">
                <Select>
                  {POSITION_OPTIONS.map((p) => (
                    <Option key={p} value={p}>{p}</Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="is_active" label="是否启用">
                <Switch checkedChildren="启用" unCheckedChildren="停用" />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </div>
  );
};

// ==================== 视频植入工具面板 ====================
const VideoInsertPanel: React.FC = () => {
  const [form] = Form.useForm();
  const [insertType, setInsertType] = useState<InsertType>('watermark');
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<any>(null);

  const handleTypeChange = (t: InsertType) => {
    setInsertType(t);
    setResult(null);
  };

  const handleExec = async () => {
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      let res: any;
      switch (insertType) {
        case 'watermark':
          res = await marketingApi.addWatermark({
            video_path: values.video_path,
            logo_path: values.logo_path,
            output_path: values.output_path || `${values.video_path}.watermark.mp4`,
            position: values.position || 'bottom-right',
            scale: values.scale || 'iw*0.15',
          });
          break;
        case 'text-watermark':
          res = await marketingApi.addTextWatermark({
            video_path: values.video_path,
            text: values.text,
            output_path: values.output_path || `${values.video_path}.text.mp4`,
            position: values.position || 'bottom-right',
            font_size: values.font_size || 24,
            font_color: values.font_color || 'white',
          });
          break;
        case 'qr-code':
          res = await marketingApi.addQrCode({
            video_path: values.video_path,
            qr_image_path: values.qr_image_path,
            output_path: values.output_path || `${values.video_path}.qr.mp4`,
            position: values.position || 'bottom-right',
            duration: values.duration ?? 5.0,
          });
          break;
        case 'copy-insert':
          res = await marketingApi.insertCopy({
            content: values.content,
            platform: values.platform || '',
            slogans: (values.slogans || []).filter(Boolean),
            link: values.link || null,
            event_info: values.event_info || null,
          });
          break;
        case 'auto-insert':
          res = await marketingApi.autoInsertCopy({
            content: values.content,
            platform: values.platform || '',
          });
          break;
        default:
          message.warning('未知植入类型');
          return;
      }
      const data = res?.data || res || {};
      if (data.success === false) {
        message.error(data.message || '执行失败');
        setResult(data);
      } else {
        message.success('执行成功');
        setResult(data);
      }
    } catch (e: any) {
      if (e?.errorFields) return;
      console.error('exec video insert failed', e);
      message.error('执行失败');
    } finally {
      setSubmitting(false);
    }
  };

  const isVideoOp = ['watermark', 'text-watermark', 'qr-code'].includes(insertType);
  const outputPath = result?.output_path || '';
  const isOutputUrl = /^https?:\/\//i.test(outputPath);

  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={12}>
        <Card
          title={
            <Space>
              <VideoCameraOutlined style={{ color: '#1677ff' }} />
              参数配置
            </Space>
          }
          size="small"
        >
          <Form
            form={form}
            layout="vertical"
            initialValues={{
              insert_type: 'watermark',
              position: 'bottom-right',
              scale: 'iw*0.15',
              font_size: 24,
              font_color: 'white',
              duration: 5.0,
            }}
          >
            <Form.Item name="insert_type" label="植入类型">
              <Select onChange={(v) => handleTypeChange(v as InsertType)} value={insertType}>
                {INSERT_TYPE_OPTIONS.map((t) => (
                  <Option key={t.value} value={t.value}>
                    <Space>
                      {t.icon}
                      {t.label}
                    </Space>
                  </Option>
                ))}
              </Select>
            </Form.Item>

            {isVideoOp && (
              <Form.Item
                name="video_path"
                label="视频路径/URL"
                rules={[{ required: true, message: '请输入视频路径' }]}
              >
                <Input placeholder="如 /data/videos/input.mp4 或 https://..." />
              </Form.Item>
            )}

            {insertType === 'watermark' && (
              <>
                <Form.Item
                  name="logo_path"
                  label="水印图片路径"
                  rules={[{ required: true, message: '请输入水印图片路径' }]}
                >
                  <Input placeholder="如 /data/logo.png" />
                </Form.Item>
                <Row gutter={16}>
                  <Col span={12}>
                    <Form.Item name="position" label="位置">
                      <Select>
                        {POSITION_OPTIONS.map((p) => (
                          <Option key={p} value={p}>{p}</Option>
                        ))}
                      </Select>
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item name="scale" label="尺寸比例">
                      <Input placeholder="iw*0.15" />
                    </Form.Item>
                  </Col>
                </Row>
              </>
            )}

            {insertType === 'text-watermark' && (
              <>
                <Form.Item
                  name="text"
                  label="水印文字"
                  rules={[{ required: true, message: '请输入水印文字' }]}
                >
                  <Input placeholder="如 @品牌官方" />
                </Form.Item>
                <Row gutter={16}>
                  <Col span={8}>
                    <Form.Item name="position" label="位置">
                      <Select>
                        {POSITION_OPTIONS.map((p) => (
                          <Option key={p} value={p}>{p}</Option>
                        ))}
                      </Select>
                    </Form.Item>
                  </Col>
                  <Col span={8}>
                    <Form.Item name="font_size" label="字号">
                      <InputNumber min={8} max={200} style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                  <Col span={8}>
                    <Form.Item name="font_color" label="颜色">
                      <Select>
                        {['white', 'black', 'red', 'yellow', 'green', 'blue'].map((c) => (
                          <Option key={c} value={c}>{c}</Option>
                        ))}
                      </Select>
                    </Form.Item>
                  </Col>
                </Row>
              </>
            )}

            {insertType === 'qr-code' && (
              <>
                <Form.Item
                  name="qr_image_path"
                  label="二维码图片路径"
                  rules={[{ required: true, message: '请输入二维码图片路径' }]}
                >
                  <Input placeholder="如 /data/qrcode.png" />
                </Form.Item>
                <Row gutter={16}>
                  <Col span={12}>
                    <Form.Item name="position" label="位置">
                      <Select>
                        {POSITION_OPTIONS.map((p) => (
                          <Option key={p} value={p}>{p}</Option>
                        ))}
                      </Select>
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item name="duration" label="时长(秒)">
                      <InputNumber min={0.5} max={600} step={0.5} style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                </Row>
              </>
            )}

            {insertType === 'copy-insert' && (
              <>
                <Form.Item
                  name="content"
                  label="原始文案"
                  rules={[{ required: true, message: '请输入文案' }]}
                >
                  <TextArea rows={4} placeholder="待植入营销信息的文案" showCount maxLength={5000} />
                </Form.Item>
                <Form.Item name="platform" label="目标平台">
                  <Select allowClear placeholder="选择平台（可空）">
                    {['douyin', 'xiaohongshu', 'bilibili', 'weibo', 'zhihu', 'x_twitter', 'kuaishou', 'toutiao'].map((p) => (
                      <Option key={p} value={p}>{p}</Option>
                    ))}
                  </Select>
                </Form.Item>
                <Form.Item name="slogans" label="品牌口号（每行一个）">
                  <TextArea rows={3} placeholder={'品牌口号1\n品牌口号2'} />
                </Form.Item>
                <Row gutter={16}>
                  <Col span={12}>
                    <Form.Item name="link" label="引流链接">
                      <Input placeholder="https://..." />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item name="event_info" label="活动信息">
                      <Input placeholder="如：双11满减活动" />
                    </Form.Item>
                  </Col>
                </Row>
              </>
            )}

            {insertType === 'auto-insert' && (
              <>
                <Form.Item
                  name="content"
                  label="原始文案"
                  rules={[{ required: true, message: '请输入文案' }]}
                >
                  <TextArea rows={4} placeholder="AI 将从素材库自动选取口号/链接/活动植入" showCount maxLength={5000} />
                </Form.Item>
                <Form.Item name="platform" label="目标平台">
                  <Select allowClear placeholder="选择平台（可空）">
                    {['douyin', 'xiaohongshu', 'bilibili', 'weibo', 'zhihu', 'x_twitter', 'kuaishou', 'toutiao'].map((p) => (
                      <Option key={p} value={p}>{p}</Option>
                    ))}
                  </Select>
                </Form.Item>
                <Alert
                  message="AI 自动植入会从素材库中读取启用的品牌口号、引流链接、活动信息，自动拼接到文案末尾。"
                  type="info"
                  showIcon
                  style={{ marginBottom: 16 }}
                />
              </>
            )}

            {isVideoOp && (
              <Form.Item name="output_path" label="输出文件路径">
                <Input placeholder="留空则自动生成（输入路径.mp4.xxx）" />
              </Form.Item>
            )}

            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              onClick={handleExec}
              loading={submitting}
              block
            >
              执行
            </Button>
          </Form>
        </Card>
      </Col>

      <Col xs={24} lg={12}>
        <Card
          title={
            <Space>
              <BulbOutlined style={{ color: '#52c41a' }} />
              执行结果
            </Space>
          }
          size="small"
        >
          {!result ? (
            <Empty description="尚未执行，请配置参数后点击执行" />
          ) : (
            <Spin spinning={submitting}>
              {isVideoOp ? (
                <Space direction="vertical" style={{ width: '100%' }} size="middle">
                  <div>
                    <Text strong>状态：</Text>
                    {result.success ? <Tag color="green">成功</Tag> : <Tag color="red">失败</Tag>}
                  </div>
                  <div>
                    <Text strong>输出路径：</Text>
                    <div
                      style={{
                        wordBreak: 'break-all',
                        overflowWrap: 'anywhere',
                        overflowX: 'hidden',
                        color: '#1677ff',
                        marginTop: 4,
                      }}
                    >
                      {outputPath || '-'}
                    </div>
                  </div>
                  {isOutputUrl && (
                    <video
                      src={outputPath}
                      controls
                      style={{ width: '100%', maxHeight: 360, background: '#000' }}
                    />
                  )}
                  {!isOutputUrl && outputPath && (
                    <Alert
                      type="info"
                      message="输出为本地文件路径，无法直接预览"
                      description="如需在线预览，请使用 HTTP(S) URL 作为输出地址。"
                      showIcon
                    />
                  )}
                </Space>
              ) : (
                <Space direction="vertical" style={{ width: '100%' }} size="middle">
                  <div>
                    <Text strong>状态：</Text>
                    {result.success ? <Tag color="green">成功</Tag> : <Tag color="red">失败</Tag>}
                  </div>
                  {result.original && (
                    <div>
                      <Text strong>原始文案：</Text>
                      <div
                        style={{
                          wordBreak: 'break-all',
                          overflowWrap: 'anywhere',
                          overflowX: 'hidden',
                          background: '#f5f5f5',
                          padding: 8,
                          borderRadius: 6,
                          marginTop: 4,
                        }}
                      >
                        {result.original}
                      </div>
                    </div>
                  )}
                  {result.content && (
                    <div>
                      <Text strong>植入后文案：</Text>
                      <div
                        style={{
                          wordBreak: 'break-all',
                          overflowWrap: 'anywhere',
                          overflowX: 'hidden',
                          background: '#f6ffed',
                          padding: 8,
                          borderRadius: 6,
                          marginTop: 4,
                        }}
                      >
                        {result.content}
                      </div>
                    </div>
                  )}
                  <Paragraph type="secondary" style={{ marginBottom: 0 }}>
                    可复制结果文案到发布中心进行多平台分发。
                  </Paragraph>
                </Space>
              )}
            </Spin>
          )}
        </Card>
      </Col>
    </Row>
  );
};

export default MarketingMaterials;
