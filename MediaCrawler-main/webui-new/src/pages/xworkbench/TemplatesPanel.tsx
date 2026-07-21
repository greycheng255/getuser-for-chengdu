import { useEffect, useState, useCallback, useMemo } from 'react';
import {
  Card,
  Table,
  Button,
  Space,
  Input,
  Select,
  Modal,
  Form,
  Tag,
  Tooltip,
  Popconfirm,
  message,
  Typography,
  Statistic,
  Row,
  Col,
  Empty,
} from 'antd';
import {
  PlusOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
  EditOutlined,
  DeleteOutlined,
  CopyOutlined,
  FireOutlined,
} from '@ant-design/icons';
import {
  xWorkbenchApi,
  type CommentTemplate,
  type TemplateCategory,
} from '../../api/xWorkbench';
import PageSkeleton from '../../components/PageSkeleton';

const { Text, Paragraph } = Typography;

/**
 * 评论模板管理面板
 *
 * 功能:
 * - 模板列表(分页、搜索、按分类筛选)
 * - 创建/编辑/删除模板
 * - 一键复制模板内容到剪贴板
 * - 初始化内置模板
 * - 统计:总模板数、最常用模板、分类分布
 */
const TemplatesPanel = () => {
  const [loading, setLoading] = useState(false);
  const [templates, setTemplates] = useState<CommentTemplate[]>([]);
  const [total, setTotal] = useState(0);
  const [categories, setCategories] = useState<TemplateCategory[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [keyword, setKeyword] = useState('');
  const [category, setCategory] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form] = Form.useForm();

  // 加载分类
  useEffect(() => {
    xWorkbenchApi.templateCategories()
      .then((r) => setCategories(r.categories || []))
      .catch(() => {});
  }, []);

  // 加载模板列表
  const loadTemplates = useCallback(async () => {
    setLoading(true);
    try {
      const r = await xWorkbenchApi.listTemplates({
        page,
        page_size: pageSize,
        keyword,
        category,
        active_only: true,
      });
      setTemplates(r.items || []);
      setTotal(r.total || 0);
    } catch (e: any) {
      message.error('加载模板失败: ' + (e?.message || ''));
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, keyword, category]);

  useEffect(() => {
    loadTemplates();
  }, [loadTemplates]);

  // 统计:用 useMemo 派生,避免每次 render 重算
  const stats = useMemo(() => {
    const totalUses = templates.reduce((sum, t) => sum + (t.use_count || 0), 0);
    const mostUsed = templates.length > 0
      ? templates.reduce((max, t) => (t.use_count > max.use_count ? t : max), templates[0])
      : null;
    const byCategory: Record<string, number> = {};
    templates.forEach((t) => {
      byCategory[t.category] = (byCategory[t.category] || 0) + 1;
    });
    return { totalUses, mostUsed, byCategory };
  }, [templates]);

  // 分类标签映射(用于表格 Tag 显示)
  const categoryMap = useMemo(() => {
    const m: Record<string, TemplateCategory> = {};
    categories.forEach((c) => { m[c.value] = c; });
    return m;
  }, [categories]);

  // 打开新建 modal
  const handleCreate = useCallback(() => {
    setEditingId(null);
    form.resetFields();
    form.setFieldsValue({ category: 'other', tags: '' });
    setModalOpen(true);
  }, [form]);

  // 打开编辑 modal
  const handleEdit = useCallback((template: CommentTemplate) => {
    setEditingId(template.id);
    form.setFieldsValue({
      name: template.name,
      content: template.content,
      category: template.category,
      tags: template.tags,
    });
    setModalOpen(true);
  }, [form]);

  // 提交表单(新建/编辑)
  const handleSubmit = useCallback(async () => {
    try {
      const values = await form.validateFields();
      if (editingId) {
        await xWorkbenchApi.updateTemplate(editingId, values);
        message.success('模板已更新');
      } else {
        await xWorkbenchApi.createTemplate(values);
        message.success('模板已创建');
      }
      setModalOpen(false);
      loadTemplates();
    } catch (e: any) {
      if (e?.errorFields) return; // 表单校验失败,不处理
      message.error('保存失败: ' + (e?.message || ''));
    }
  }, [form, editingId, loadTemplates]);

  // 删除模板
  const handleDelete = useCallback(async (id: number) => {
    try {
      await xWorkbenchApi.deleteTemplate(id);
      message.success('模板已删除');
      loadTemplates();
    } catch (e: any) {
      message.error('删除失败: ' + (e?.message || ''));
    }
  }, [loadTemplates]);

  // 复制模板内容 + 标记为已使用
  const handleUse = useCallback(async (template: CommentTemplate) => {
    try {
      // 替换变量提示(用户可手动替换)
      let content = template.content;
      const hasVar = /\{(\w+)\}/.test(content);
      if (hasVar) {
        message.info('模板含变量,已复制到剪贴板,请手动替换 {topic} {username} 等');
      } else {
        message.success('模板内容已复制到剪贴板');
      }
      await navigator.clipboard.writeText(content);
      // 后台标记使用(不阻塞,失败不提示)
      xWorkbenchApi.useTemplate(template.id).catch(() => {});
      // 本地更新使用次数(避免重新加载)
      setTemplates((prev) =>
        prev.map((t) =>
          t.id === template.id
            ? { ...t, use_count: t.use_count + 1, last_used_ts: Math.floor(Date.now() / 1000) }
            : t,
        ),
      );
    } catch (e: any) {
      message.error('复制失败: ' + (e?.message || '浏览器可能不支持剪贴板'));
    }
  }, []);

  // 初始化内置模板
  const handleSeed = useCallback(async () => {
    try {
      const r = await xWorkbenchApi.seedTemplates();
      if (r.created > 0) {
        message.success(`已创建 ${r.created} 条内置模板`);
      } else {
        message.info(r.message);
      }
      loadTemplates();
    } catch (e: any) {
      message.error('初始化失败: ' + (e?.message || ''));
    }
  }, [loadTemplates]);

  // 表格列定义
  const columns = useMemo(() => [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 180,
      render: (text: string, record: CommentTemplate) => (
        <Tooltip title={record.content}>
          <Text strong>{text}</Text>
        </Tooltip>
      ),
    },
    {
      title: '内容',
      dataIndex: 'content',
      key: 'content',
      ellipsis: true,
      render: (text: string) => (
        <Paragraph
          ellipsis={{ rows: 2 }}
          style={{ marginBottom: 0, color: '#595959', fontSize: 13 }}
        >
          {text}
        </Paragraph>
      ),
    },
    {
      title: '分类',
      dataIndex: 'category',
      key: 'category',
      width: 100,
      render: (cat: string) => {
        const c = categoryMap[cat];
        return c ? <Tag color={c.color}>{c.label}</Tag> : <Tag>{cat}</Tag>;
      },
    },
    {
      title: '标签',
      dataIndex: 'tags_list',
      key: 'tags',
      width: 150,
      render: (tags: string[]) => (
        <Space size={4} wrap>
          {(tags || []).slice(0, 3).map((t) => (
            <Tag key={t} style={{ fontSize: 11 }}>{t}</Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '使用次数',
      dataIndex: 'use_count',
      key: 'use_count',
      width: 90,
      sorter: (a: CommentTemplate, b: CommentTemplate) => a.use_count - b.use_count,
      render: (n: number) => (
        <Space size={4}>
          <FireOutlined style={{ color: n > 5 ? '#fa541c' : '#bfbfbf' }} />
          <Text>{n}</Text>
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 200,
      render: (_: any, record: CommentTemplate) => (
        <Space size={4}>
          <Button
            size="small"
            type="primary"
            icon={<CopyOutlined />}
            onClick={() => handleUse(record)}
          >
            使用
          </Button>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          />
          <Popconfirm
            title="确定删除此模板?"
            onConfirm={() => handleDelete(record.id)}
            okText="删除"
            cancelText="取消"
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ], [categoryMap, handleUse, handleEdit, handleDelete]);

  return (
    <div>
      {/* 统计卡片 */}
      <Row gutter={12} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic title="模板总数" value={total} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic title="累计使用次数" value={stats.totalUses} />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="最常用模板"
              value={stats.mostUsed?.name || '无'}
              suffix={stats.mostUsed ? `(${stats.mostUsed.use_count}次)` : ''}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="分类数"
              value={Object.keys(stats.byCategory).length}
            />
          </Card>
        </Col>
      </Row>

      {/* 工具栏 */}
      <Space style={{ marginBottom: 16 }} wrap>
        <Input.Search
          placeholder="搜索名称/内容/标签"
          value={keyword}
          onChange={(e) => { setKeyword(e.target.value); setPage(1); }}
          onSearch={loadTemplates}
          style={{ width: 240 }}
          allowClear
        />
        <Select
          placeholder="按分类筛选"
          value={category || undefined}
          onChange={(v) => { setCategory(v || ''); setPage(1); }}
          style={{ width: 140 }}
          allowClear
          options={categories.map((c) => ({ value: c.value, label: c.label }))}
        />
        <Button icon={<ReloadOutlined />} onClick={loadTemplates}>刷新</Button>
        <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>新建模板</Button>
        <Button icon={<ThunderboltOutlined />} onClick={handleSeed}>初始化内置模板</Button>
      </Space>

      {/* 模板列表 */}
      {loading ? (
        <PageSkeleton count={5} />
      ) : templates.length === 0 ? (
        <Empty description="暂无模板,点击「初始化内置模板」快速开始">
          <Button type="primary" icon={<ThunderboltOutlined />} onClick={handleSeed}>
            初始化内置模板
          </Button>
        </Empty>
      ) : (
        <Table
          rowKey="id"
          columns={columns}
          dataSource={templates}
          loading={loading}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps); },
          }}
          size="middle"
        />
      )}

      {/* 新建/编辑 Modal */}
      <Modal
        title={editingId ? '编辑模板' : '新建模板'}
        open={modalOpen}
        onOk={handleSubmit}
        onCancel={() => setModalOpen(false)}
        okText="保存"
        cancelText="取消"
        width={600}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="模板名称"
            rules={[{ required: true, message: '请输入模板名称' }]}
          >
            <Input placeholder="如:问候 - 关注已久" maxLength={128} />
          </Form.Item>
          <Form.Item
            name="content"
            label="模板内容"
            rules={[{ required: true, message: '请输入模板内容' }]}
            extra="支持变量:{topic} {username} {keyword},使用时会提示替换"
          >
            <Input.TextArea
              rows={4}
              placeholder="如:一直在关注你的内容,{topic}这个方向太有启发了!🔥"
              maxLength={500}
              showCount
            />
          </Form.Item>
          <Form.Item name="category" label="分类">
            <Select
              options={categories.map((c) => ({
                value: c.value,
                label: `${c.label} - ${c.desc}`,
              }))}
            />
          </Form.Item>
          <Form.Item name="tags" label="标签" extra="逗号分隔,便于搜索">
            <Input placeholder="如:关注,互动,问候" maxLength={255} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default TemplatesPanel;
