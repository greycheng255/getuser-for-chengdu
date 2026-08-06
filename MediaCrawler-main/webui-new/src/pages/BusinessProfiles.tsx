import React, { useEffect, useState } from 'react';
import { Alert, Button, Card, Empty, Form, Input, List, Modal, Space, Switch, Tag, message } from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons';
import { createBusinessProfile, deleteBusinessProfile, listBusinessProfiles, updateBusinessProfile, type BusinessProfile } from '../api/businessProfiles';

const splitTerms = (value = '') => value.split(/[,，\n、\s]+/).map(item => item.trim()).filter(Boolean);

const BusinessProfiles: React.FC = () => {
  const [items, setItems] = useState<BusinessProfile[]>([]);
  const [editing, setEditing] = useState<BusinessProfile | null>(null);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();
  const load = async () => { try { setItems((await listBusinessProfiles()).items || []); } catch { message.error('业务画像加载失败'); } };
  useEffect(() => { load(); }, []);
  const openEditor = (item?: BusinessProfile) => {
    setEditing(item || null);
    form.setFieldsValue(item ? {
      ...item, business_keywords: item.business_keywords.join(', '), intent_keywords: item.intent_keywords.join(', '), exclude_keywords: item.exclude_keywords.join(', '),
    } : { enabled: true });
    setOpen(true);
  };
  const save = async (values: any) => {
    setSaving(true);
    const data = { ...values, business_keywords: splitTerms(values.business_keywords), intent_keywords: splitTerms(values.intent_keywords), exclude_keywords: splitTerms(values.exclude_keywords) };
    try { editing ? await updateBusinessProfile(editing.id, data) : await createBusinessProfile(data); message.success('业务画像已保存'); setOpen(false); load(); }
    catch { message.error('保存失败'); } finally { setSaving(false); }
  };
  return <Card title="业务画像规则" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => openEditor()}>新建画像</Button>}>
    <Alert showIcon type="info" style={{ marginBottom: 16 }} message="规则预览：命中排除词即丢弃；同时命中业务词和意向词才入线索；未配置意向词时回退咨询模式。" />
    {items.length ? <List dataSource={items} renderItem={item => <List.Item actions={[
      <Button type="link" icon={<EditOutlined />} onClick={() => openEditor(item)}>编辑</Button>,
      <Button type="link" danger icon={<DeleteOutlined />} onClick={async () => { await deleteBusinessProfile(item.id); message.success('已删除'); load(); }}>删除</Button>,
    ]}><List.Item.Meta title={<Space><strong>{item.name}</strong>{item.enabled ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>}</Space>}
      description={<div><div>{item.business_intent || '未填写业务意图'}</div><div style={{ marginTop: 6 }}><Tag color="blue">业务词：{item.business_keywords.join('、') || '任务关键词'}</Tag><Tag color="green">意向词：{item.intent_keywords.join('、') || '回退模式'}</Tag><Tag color="red">排除词：{item.exclude_keywords.join('、') || '无'}</Tag></div></div>} />
    </List.Item>} /> : <Empty description="还没有保存的业务画像" />}
    <Modal title={editing ? '编辑业务画像' : '新建业务画像'} open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} confirmLoading={saving} width={640}>
      <Form form={form} layout="vertical" onFinish={save}>
        <Form.Item name="name" label="画像名称" rules={[{ required: true, message: '请输入名称' }]}><Input placeholder="例如：AI Agent 开发者获客" /></Form.Item>
        <Form.Item name="business_intent" label="业务意图"><Input.TextArea rows={2} placeholder="要找的人、提供的价值与转化目标" /></Form.Item>
        <Form.Item name="business_keywords" label="业务词"><Input.TextArea rows={2} placeholder="AI, Agent, 开发者（逗号分隔）" /></Form.Item>
        <Form.Item name="intent_keywords" label="意向词"><Input.TextArea rows={2} placeholder="接单, 找活, 外包（逗号分隔）" /></Form.Item>
        <Form.Item name="exclude_keywords" label="排除词"><Input.TextArea rows={2} placeholder="学习, 教程, MCP（逗号分隔）" /></Form.Item>
        <Form.Item name="enabled" label="启用" valuePropName="checked"><Switch /></Form.Item>
      </Form>
    </Modal>
  </Card>;
};
export default BusinessProfiles;
