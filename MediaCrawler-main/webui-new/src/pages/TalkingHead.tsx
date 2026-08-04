import { message } from '../utils/antdMessage';
import React, { useEffect, useState, useCallback } from 'react';
import { Card, Table, Tag, Button, Space, Select, Row, Col, Statistic, Empty, Spin, Tabs, Input, Switch, Badge, Form, Typography, Divider, Alert, Upload, Image, Popconfirm } from 'antd';
import {
  ReloadOutlined, VideoCameraOutlined, SoundOutlined, UserOutlined,
  ThunderboltOutlined, FileTextOutlined, PlayCircleOutlined,
  CopyOutlined, UploadOutlined, PlusOutlined, DeleteOutlined,
} from '@ant-design/icons';
import request from '../api/request';

const { TextArea } = Input;
const { Text, Paragraph } = Typography;

// ============ 服务状态 ============
interface ServiceStatus {
  whisper: { available: boolean; model_size: string; engine: string };
  voice_clone: { mode: string; cosyvoice_available: boolean };
  digital_human: { mode: string; heygem_available: boolean; dashscope_available: boolean };
  ffmpeg: boolean;
  yt_dlp: boolean;
}

const StatusBadge: React.FC<{ status: ServiceStatus | null }> = ({ status }) => {
  if (!status) return <Spin size="small" />;
  const dhDetail = status.digital_human.mode === 'heygem' ? 'HeyGem'
    : status.digital_human.mode === 'dashscope_wan2.2-s2v' ? 'wan2.2-s2v'
    : '图片视频降级';
  const items = [
    { label: 'Whisper', ok: status.whisper.available, detail: status.whisper.model_size },
    { label: '声音克隆', ok: status.voice_clone.cosyvoice_available, detail: status.voice_clone.mode === 'cosyvoice' ? 'CosyVoice' : 'edge-tts降级' },
    { label: '数字人', ok: status.digital_human.heygem_available || status.digital_human.dashscope_available, detail: dhDetail },
    { label: 'FFmpeg', ok: status.ffmpeg, detail: '' },
    { label: 'yt-dlp', ok: status.yt_dlp, detail: '' },
  ];
  return (
    <Space wrap>
      {items.map((item, i) => (
        <Badge
          key={i}
          status={item.ok ? 'success' : 'warning'}
          text={<Text type="secondary" style={{ fontSize: 12 }}>{item.label}{item.detail ? ` (${item.detail})` : ''}</Text>}
        />
      ))}
    </Space>
  );
};

const TalkingHead: React.FC = () => {
  const [activeTab, setActiveTab] = useState('generate');
  const [status, setStatus] = useState<ServiceStatus | null>(null);
  const [loading, setLoading] = useState(false);

  // 文案提取
  const [videoUrl, setVideoUrl] = useState('');
  const [extractedScript, setExtractedScript] = useState('');
  const [extractResult, setExtractResult] = useState<any>(null);

  // 文案仿写
  const [originalText, setOriginalText] = useState('');
  const [rewriteStyle, setRewriteStyle] = useState('');
  const [rewriteIndustry, setRewriteIndustry] = useState('');
  const [rewriteResult, setRewriteResult] = useState<any>(null);

  // 一键生成
  const [genVideoUrl, setGenVideoUrl] = useState('');
  const [genText, setGenText] = useState('');
  const [genStyle, setGenStyle] = useState('');
  const [genIndustry, setGenIndustry] = useState('');
  const [genVoiceModelId, setGenVoiceModelId] = useState(0);
  const [genDhId, setGenDhId] = useState(0);
  const [enableSubtitle, setEnableSubtitle] = useState(true);
  const [enableBgm, setEnableBgm] = useState(true);
  const [enableCover, setEnableCover] = useState(true);
  const [genResult, setGenResult] = useState<any>(null);

  // 声音模型/数字人列表
  const [voiceModels, setVoiceModels] = useState<any[]>([]);
  const [digitalHumans, setDigitalHumans] = useState<any[]>([]);
  const [tasks, setTasks] = useState<any[]>([]);

  // 视频拆解
  const [analyzeUrl, setAnalyzeUrl] = useState('');
  const [analyzeLoading, setAnalyzeLoading] = useState(false);
  const [analyzeResult, setAnalyzeResult] = useState<any>(null);

  const loadStatus = useCallback(async () => {
    try {
      const resp: any = await request.get('/talking-head/status');
      if (resp?.success) setStatus(resp.data);
    } catch (e) { console.error('status error', e); }
  }, []);

  const loadVoiceModels = useCallback(async () => {
    try {
      const resp: any = await request.get('/talking-head/voice-models');
      if (resp?.success) setVoiceModels(resp.data || []);
    } catch (e) { console.error('voice models error', e); }
  }, []);

  const loadDigitalHumans = useCallback(async () => {
    try {
      const resp: any = await request.get('/talking-head/digital-humans');
      if (resp?.success) setDigitalHumans(resp.data || []);
    } catch (e) { console.error('digital humans error', e); }
  }, []);

  const loadTasks = useCallback(async () => {
    try {
      const resp: any = await request.get('/talking-head/tasks?limit=10');
      if (resp?.success) setTasks(resp.data || []);
    } catch (e) { console.error('tasks error', e); }
  }, []);

  // 创建数字人
  const [dhName, setDhName] = useState('');
  const [dhUploading, setDhUploading] = useState(false);
  const [dhFile, setDhFile] = useState<File | null>(null);

  const handleCreateDh = async () => {
    if (!dhFile) { message.warning('请先上传形象照图片'); return; }
    if (!dhName.trim()) { message.warning('请输入数字人名称'); return; }
    setDhUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', dhFile);
      const resp: any = await request.post(
        `/talking-head/digital-human/upload?name=${encodeURIComponent(dhName.trim())}`,
        formData,
        { 
          skipRetry: true,
          headers: { 'Content-Type': undefined as any },
        }
      );
      if (resp?.success) {
        message.success(`数字人「${dhName.trim()}」创建成功`);
        setDhName('');
        setDhFile(null);
        loadDigitalHumans();
      } else {
        message.error(resp?.detail || '创建失败');
      }
    } catch (e: any) {
      message.error(e?.message || '创建失败');
    } finally {
      setDhUploading(false);
    }
  };

  const handleDeleteDh = async (id: number) => {
    try {
      await request.delete(`/talking-head/digital-humans/${id}`);
      message.success('已删除');
      loadDigitalHumans();
    } catch (e: any) {
      message.error(e?.message || '删除失败');
    }
  };

  useEffect(() => {
    loadStatus();
    loadVoiceModels();
    loadDigitalHumans();
    loadTasks();
  }, [loadStatus, loadVoiceModels, loadDigitalHumans, loadTasks]);

  // 文案提取
  const handleExtract = async () => {
    if (!videoUrl.trim()) { message.warning('请输入视频链接'); return; }
    setLoading(true);
    setExtractedScript('');
    setExtractResult(null);
    try {
      const resp: any = await request.post('/talking-head/extract-script', { video_url: videoUrl });
      if (resp?.success) {
        setExtractResult(resp.data);
        setExtractedScript(resp.data.cleaned_text || resp.data.raw_text || '');
        message.success(`提取成功: ${resp.data.cleaned_text?.length || 0}字`);
      } else {
        message.error(resp?.detail || '提取失败');
      }
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '提取失败');
    } finally { setLoading(false); }
  };

  // 文案仿写
  const handleRewrite = async () => {
    if (!originalText.trim()) { message.warning('请输入原始文案'); return; }
    setLoading(true);
    setRewriteResult(null);
    try {
      const resp: any = await request.post('/talking-head/rewrite', {
        original_text: originalText, style: rewriteStyle, industry: rewriteIndustry,
      });
      if (resp?.success) {
        setRewriteResult(resp.data);
        message.success('仿写完成');
      } else {
        message.error(resp?.detail || '仿写失败');
      }
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '仿写失败');
    } finally { setLoading(false); }
  };

  // 一键生成
  const handleGenerate = async () => {
    if (!genVideoUrl.trim() && !genText.trim()) {
      message.warning('请提供视频链接或直接输入文案');
      return;
    }
    setLoading(true);
    setGenResult(null);
    message.info('开始生成口播视频，全链路可能需要1-3分钟...');
    try {
      const resp: any = await request.post('/talking-head/generate', {
        video_url: genVideoUrl,
        text: genText,
        style: genStyle,
        industry: genIndustry,
        voice_model_id: genVoiceModelId,
        digital_human_id: genDhId,
        enable_subtitle: enableSubtitle,
        enable_bgm: enableBgm,
        enable_cover: enableCover,
      });
      if (resp?.success) {
        setGenResult(resp.data);
        message.success(`生成完成，耗时${resp.data.elapsed}秒`);
        loadTasks();
      } else {
        message.error(resp?.data?.error || '生成失败');
        if (resp?.data) setGenResult(resp.data);
      }
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '生成失败');
    } finally { setLoading(false); }
  };

  const copyText = (text: string) => {
    navigator.clipboard.writeText(text);
    message.success('已复制到剪贴板');
  };

  const columns = (titleField: string) => [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '名称', dataIndex: 'name', width: 150 },
    { title: '提供方', dataIndex: 'provider', width: 120, render: (v: string) => (
      <Tag color={v === 'cosyvoice' || v === 'heygem' ? 'green' : 'orange'}>{v}</Tag>
    )},
    { title: '状态', dataIndex: 'status', width: 80, render: (v: string) => (
      <Tag color={v === 'ready' ? 'success' : v === 'failed' ? 'error' : 'processing'}>{v}</Tag>
    )},
    { title: '创建时间', dataIndex: 'created_ts', width: 160, render: (v: number) =>
      new Date(v * 1000).toLocaleString('zh-CN')
    },
  ];

  const taskColumns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '状态', dataIndex: 'status', width: 100, render: (v: string) => (
      <Tag color={v === 'done' ? 'success' : v === 'failed' ? 'error' : 'processing'}>{v}</Tag>
    )},
    { title: '原文案', dataIndex: 'original_script', ellipsis: true, width: 200 },
    { title: '改写文案', dataIndex: 'rewritten_script', ellipsis: true, width: 200 },
    { title: '视频', dataIndex: 'video_path', ellipsis: true, width: 200 },
    { title: '耗时', dataIndex: 'elapsed', width: 80, render: (v: number) => v ? `${v}s` : '-' },
    { title: '时间', dataIndex: 'created_ts', width: 160, render: (v: number) =>
      new Date(v * 1000).toLocaleString('zh-CN')
    },
  ];

  // 视频拆解
  const handleAnalyze = async () => {
    if (!analyzeUrl.trim()) return;
    setAnalyzeLoading(true);
    setAnalyzeResult(null);
    try {
      const resp: any = await request.post('/talking-head/analyze-video', { video_url: analyzeUrl.trim() });
      if (resp?.success) {
        setAnalyzeResult(resp.data);
      } else {
        throw new Error(resp?.detail || '拆解失败');
      }
    } catch (e: any) {
      console.error('analyze error', e);
      alert(`视频拆解失败: ${e.message || e}`);
    } finally {
      setAnalyzeLoading(false);
    }
  };

  return (
    <div style={{ padding: 24 }}>
      <Card
        title={
          <Space>
            <VideoCameraOutlined />
            <span>数字人口播视频生成</span>
          </Space>
        }
        extra={<Button icon={<ReloadOutlined />} onClick={loadStatus} size="small">刷新状态</Button>}
      >
        <div style={{ marginBottom: 16 }}>
          <StatusBadge status={status} />
        </div>

        <Tabs activeKey={activeTab} onChange={setActiveTab} items={[

          /* ========== 一键生成 ========== */
          { key: 'generate', label: <span><ThunderboltOutlined /> 一键生成</span>, children: (
            <Row gutter={16}>
              <Col span={12}>
                <Card title="输入" size="small">
                  <Form layout="vertical">
                    <Form.Item label="对标视频链接（与文案二选一）">
                      <Input
                        placeholder="https://x.com/... 或抖音/小红书/B站链接"
                        value={genVideoUrl}
                        onChange={e => setGenVideoUrl(e.target.value)}
                      />
                    </Form.Item>
                    <Form.Item label="或直接输入文案">
                      <TextArea
                        rows={4}
                        placeholder="直接输入口播文案（如有视频链接则从视频提取）"
                        value={genText}
                        onChange={e => setGenText(e.target.value)}
                      />
                    </Form.Item>
                    <Row gutter={8}>
                      <Col span={12}>
                        <Form.Item label="仿写风格">
                          <Input placeholder="如：激情带货" value={genStyle} onChange={e => setGenStyle(e.target.value)} />
                        </Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item label="行业">
                          <Input placeholder="如：教育" value={genIndustry} onChange={e => setGenIndustry(e.target.value)} />
                        </Form.Item>
                      </Col>
                    </Row>
                    <Row gutter={8}>
                      <Col span={12}>
                        <Form.Item label="声音模型">
                          <Select
                            value={genVoiceModelId}
                            onChange={setGenVoiceModelId}
                            style={{ width: '100%' }}
                          >
                            <Select.Option value={0}>默认（edge-tts降级）</Select.Option>
                            {voiceModels.map(m => (
                              <Select.Option key={m.id} value={m.id}>{m.name} ({m.provider})</Select.Option>
                            ))}
                          </Select>
                        </Form.Item>
                      </Col>
                      <Col span={12}>
                        <Form.Item label="数字人">
                          <Select
                            value={genDhId}
                            onChange={setGenDhId}
                            style={{ width: '100%' }}
                          >
                            <Select.Option value={0}>默认数字人形象</Select.Option>
                            {digitalHumans.map(d => (
                              <Select.Option key={d.id} value={d.id}>{d.name} ({d.provider})</Select.Option>
                            ))}
                          </Select>
                        </Form.Item>
                      </Col>
                    </Row>
                    <Space>
                      <Switch checked={enableSubtitle} onChange={setEnableSubtitle} /> <Text type="secondary">字幕</Text>
                      <Switch checked={enableBgm} onChange={setEnableBgm} /> <Text type="secondary">BGM</Text>
                      <Switch checked={enableCover} onChange={setEnableCover} /> <Text type="secondary">封面</Text>
                    </Space>
                    <div style={{ marginTop: 16 }}>
                      <Button
                        type="primary" size="large" block
                        icon={<ThunderboltOutlined />}
                        loading={loading}
                        onClick={handleGenerate}
                      >
                        一键生成口播视频
                      </Button>
                    </div>
                  </Form>
                </Card>
              </Col>
              <Col span={12}>
                <Card title="生成结果" size="small">
                  {loading && <div style={{ textAlign: 'center', padding: 40 }}><Spin description="生成中..." /></div>}
                  {!loading && !genResult && <Empty description="点击生成后结果显示在这里" />}
                  {genResult && (
                    <div>
                      {genResult.status === 'done' ? (
                        <Alert type="success" title={`生成完成，耗时 ${genResult.elapsed}秒`} style={{ marginBottom: 12 }} />
                      ) : (
                        <Alert type="error" title={`生成失败: ${genResult.error || ''}`} style={{ marginBottom: 12 }} />
                      )}
                      {genResult.steps?.map((s: any, i: number) => (
                        <div key={i} style={{ marginBottom: 4 }}>
                          <Tag color={s.status === 'done' ? 'success' : s.status === 'failed' ? 'error' : s.status === 'skipped' ? 'default' : 'processing'}>
                            {s.status}
                          </Tag>
                          <Text type="secondary">{s.step}</Text>
                          {s.error && <Text type="danger" style={{ fontSize: 12 }}> — {s.error}</Text>}
                        </div>
                      ))}
                      {genResult.rewritten_script && (
                        <div style={{ marginTop: 12 }}>
                          <Divider><FileTextOutlined /> 仿写文案</Divider>
                          <Paragraph style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
                            {genResult.rewritten_script}
                            <Button size="small" type="text" icon={<CopyOutlined />} onClick={() => copyText(genResult.rewritten_script)} />
                          </Paragraph>
                        </div>
                      )}
                      {genResult.title_suggestions?.length > 0 && (
                        <div>
                          <Text strong>标题建议: </Text>
                          {genResult.title_suggestions.map((t: string, i: number) => (
                            <Tag key={i} color="blue">{t}</Tag>
                          ))}
                        </div>
                      )}
                      {genResult.video_path && (
                        <div style={{ marginTop: 8 }}>
                          <Text strong>视频: </Text>
                          {genResult.video_url ? (
                            <video
                              src={genResult.video_url}
                              controls
                              style={{ display: 'block', maxWidth: '100%', marginTop: 8, borderRadius: 4 }}
                              poster={genResult.cover_url}
                            />
                          ) : (
                            <Text copyable code>{genResult.video_path}</Text>
                          )}
                          <div style={{ marginTop: 4 }}>
                            <Text type="secondary" style={{ fontSize: 12 }} copyable code>{genResult.video_path}</Text>
                          </div>
                        </div>
                      )}
                      {genResult.cover_path && !genResult.video_url && (
                        <div>
                          <Text strong>封面: </Text>
                          {genResult.cover_url ? (
                            <img
                              src={genResult.cover_url}
                              alt="封面"
                              style={{ display: 'block', maxWidth: '100%', marginTop: 8, borderRadius: 4 }}
                            />
                          ) : (
                            <Text copyable code>{genResult.cover_path}</Text>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </Card>
              </Col>
            </Row>
          ), },

          /* ========== 文案提取 ========== */
          { key: 'extract', label: <span><FileTextOutlined /> 文案提取</span>, children: (
            <Card title="对标文案提取" size="small">
              <Input.Search
                placeholder="输入对标视频链接（X/抖音/小红书/B站等）"
                enterButton="提取文案"
                size="large"
                value={videoUrl}
                onChange={e => setVideoUrl(e.target.value)}
                onSearch={handleExtract}
                loading={loading}
              />
              {extractResult && (
                <div style={{ marginTop: 16 }}>
                  <Row gutter={16}>
                    <Col span={6}><Statistic title="原始字数" value={extractResult.raw_text?.length || 0} /></Col>
                    <Col span={6}><Statistic title="清洗后字数" value={extractResult.cleaned_text?.length || 0} /></Col>
                    <Col span={6}><Statistic title="分段数" value={extractResult.segments?.length || 0} /></Col>
                    <Col span={6}><Statistic title="视频时长" value={extractResult.duration || 0} suffix="秒" /></Col>
                  </Row>
                  <Divider>清洗后文案</Divider>
                  <Paragraph style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
                    {extractedScript}
                    <Button size="small" type="text" icon={<CopyOutlined />} onClick={() => copyText(extractedScript)} />
                  </Paragraph>
                  <Button type="link" onClick={() => { setOriginalText(extractedScript); setActiveTab('rewrite'); }}>
                    去仿写 →
                  </Button>
                </div>
              )}
            </Card>
          ), },

          /* ========== 文案仿写 ========== */
          { key: 'rewrite', label: <span><CopyOutlined /> 文案仿写</span>, children: (
            <Row gutter={16}>
              <Col span={12}>
                <Card title="原始文案" size="small">
                  <TextArea
                    rows={10}
                    value={originalText}
                    onChange={e => setOriginalText(e.target.value)}
                    placeholder="粘贴或输入原始口播文案"
                  />
                  <Row gutter={8} style={{ marginTop: 8 }}>
                    <Col span={8}>
                      <Input placeholder="风格" value={rewriteStyle} onChange={e => setRewriteStyle(e.target.value)} />
                    </Col>
                    <Col span={8}>
                      <Input placeholder="行业" value={rewriteIndustry} onChange={e => setRewriteIndustry(e.target.value)} />
                    </Col>
                    <Col span={8}>
                      <Button type="primary" block loading={loading} onClick={handleRewrite} icon={<CopyOutlined />}>
                        仿写
                      </Button>
                    </Col>
                  </Row>
                </Card>
              </Col>
              <Col span={12}>
                <Card title="仿写结果" size="small">
                  {rewriteResult ? (
                    <div>
                      <Paragraph style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all', overflowWrap: 'anywhere' }}>
                        {rewriteResult.rewritten_text}
                        <Button size="small" type="text" icon={<CopyOutlined />} onClick={() => copyText(rewriteResult.rewritten_text)} />
                      </Paragraph>
                      {rewriteResult.title_suggestions?.length > 0 && (
                        <div>
                          <Text strong>标题建议:</Text>
                          <div>{rewriteResult.title_suggestions.map((t: string, i: number) => <Tag key={i} color="blue">{t}</Tag>)}</div>
                        </div>
                      )}
                      {rewriteResult.tags?.length > 0 && (
                        <div>
                          <Text strong>话题标签:</Text>
                          <div>{rewriteResult.tags.map((t: string, i: number) => <Tag key={i} color="cyan">#{t}</Tag>)}</div>
                        </div>
                      )}
                    </div>
                  ) : (
                    <Empty description="点击仿写后结果显示在这里" />
                  )}
                </Card>
              </Col>
            </Row>
          ), },

          /* ========== 声音模型 ========== */
          { key: 'voice', label: <span><SoundOutlined /> 声音模型</span>, children: (
            <Card
              title="声音克隆模型列表"
              size="small"
              extra={<Button icon={<ReloadOutlined />} onClick={loadVoiceModels} size="small">刷新</Button>}
            >
              <Table
                dataSource={voiceModels}
                columns={columns('name')}
                rowKey="id"
                size="small"
                pagination={{ pageSize: 10 }}
                locale={{ emptyText: <Empty description="暂无声音模型，通过API创建" /> }}
              />
            </Card>
          ), },

          /* ========== 数字人 ========== */
          { key: 'dh', label: <span><UserOutlined /> 数字人</span>, children: (
            <div>
              <Card title="创建数字人形象" size="small" style={{ marginBottom: 16 }}>
                <Row gutter={16} align="middle">
                  <Col span={8}>
                    <Upload
                      accept="image/*"
                      maxCount={1}
                      beforeUpload={(file) => { setDhFile(file); return false; }}
                      onRemove={() => setDhFile(null)}
                      fileList={dhFile ? [{ uid: '-1', name: dhFile.name, status: 'done' as const }] : []}
                    >
                      <Button icon={<UploadOutlined />}>上传形象照</Button>
                    </Upload>
                  </Col>
                  <Col span={10}>
                    <Input
                      placeholder="数字人名称（如：职场博主形象）"
                      value={dhName}
                      onChange={e => setDhName(e.target.value)}
                      prefix={<UserOutlined />}
                    />
                  </Col>
                  <Col span={6}>
                    <Button
                      type="primary"
                      icon={<PlusOutlined />}
                      loading={dhUploading}
                      onClick={handleCreateDh}
                      block
                    >
                      创建数字人
                    </Button>
                  </Col>
                </Row>
              </Card>
              <Card
                title="数字人形象列表"
                size="small"
                extra={<Button icon={<ReloadOutlined />} onClick={loadDigitalHumans} size="small">刷新</Button>}
              >
                {digitalHumans.length === 0 ? (
                  <Empty description="暂无数字人形象，请在上方上传图片创建（不创建将使用默认数字人形象）" />
                ) : (
                  <Row gutter={[16, 16]}>
                    {digitalHumans.map(d => (
                      <Col key={d.id} span={6}>
                        <Card
                          size="small"
                          hoverable
                          actions={[
                            <Popconfirm
                              key="del"
                              title="确认删除该数字人形象？"
                              onConfirm={() => handleDeleteDh(d.id)}
                            >
                              <DeleteOutlined />
                            </Popconfirm>,
                          ]}
                        >
                          {d.portrait_url ? (
                            <Image
                              src={d.portrait_url}
                              style={{ width: '100%', height: 200, objectFit: 'cover', borderRadius: 4 }}
                            />
                          ) : (
                            <div style={{ width: '100%', height: 200, display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f5f5f5', borderRadius: 4 }}>
                              <UserOutlined style={{ fontSize: 48, color: '#ccc' }} />
                            </div>
                          )}
                          <Card.Meta
                            title={d.name}
                            description={
                              <Space>
                                <Tag color={d.provider === 'heygem' ? 'green' : 'blue'}>
                                  {d.provider === 'heygem' ? 'HeyGem' : '图片视频'}
                                </Tag>
                                <Tag color={d.status === 'ready' ? 'success' : 'default'}>{d.status}</Tag>
                              </Space>
                            }
                            style={{ marginTop: 8 }}
                          />
                        </Card>
                      </Col>
                    ))}
                  </Row>
                )}
              </Card>
            </div>
          ), },

          /* ========== 视频拆解 ========== */
          { key: 'analyze', label: <span><VideoCameraOutlined /> 视频拆解</span>, children: (
            <div>
              <Card title="AI 视频拆解" size="small" style={{ marginBottom: 16 }}>
                <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
                  <Input
                    placeholder="输入抖音/小红书/B站视频链接"
                    value={analyzeUrl}
                    onChange={(e) => setAnalyzeUrl(e.target.value)}
                    onPressEnter={handleAnalyze}
                  />
                  <Button type="primary" onClick={handleAnalyze} loading={analyzeLoading}>
                    AI 拆解
                  </Button>
                </Space.Compact>
                <Text type="secondary">输入对标视频链接，AI 自动生成脚本分析、分镜拆解、关键要点和推荐评论</Text>
              </Card>

              {analyzeLoading && (
                <div style={{ textAlign: 'center', padding: 60 }}>
                  <Spin size="large" tip="正在拆解视频..." />
                  <div style={{ marginTop: 16, color: '#999' }}>
                    正在调用解析服务提取字幕，并用 AI 进行深度分析，预计 30-60 秒...
                  </div>
                </div>
              )}

              {analyzeResult && !analyzeLoading && (
                <div>
                  {/* 脚本分析 */}
                  {analyzeResult.script_analysis && (
                    <Card title="📋 脚本分析" size="small" style={{ marginBottom: 16 }}>
                      <Row gutter={16}>
                        <Col span={6}>
                          <Text strong>内容类型：</Text>
                          <Tag color="blue" style={{ marginTop: 4 }}>
                            {analyzeResult.script_analysis.content_type}
                          </Tag>
                        </Col>
                        <Col span={18}>
                          <Text strong>核心信息：</Text>
                          <Paragraph style={{ marginTop: 4 }}>
                            {analyzeResult.script_analysis.core_info}
                          </Paragraph>
                        </Col>
                      </Row>
                      <Divider style={{ margin: '12px 0' }} />
                      <Text strong>结构分析：</Text>
                      <Paragraph style={{ marginTop: 4, whiteSpace: 'pre-wrap' }}>
                        {analyzeResult.script_analysis.structure}
                      </Paragraph>
                    </Card>
                  )}

                  {/* 分镜拆解 */}
                  {analyzeResult.storyboard && analyzeResult.storyboard.length > 0 && (
                    <Card title="🎬 分镜拆解" size="small" style={{ marginBottom: 16 }}>
                      {analyzeResult.storyboard.map((shot: any, i: number) => (
                        <div key={i} style={{
                          padding: '12px 0',
                          borderBottom: i < analyzeResult.storyboard.length - 1 ? '1px solid #f0f0f0' : 'none',
                        }}>
                          <Row gutter={12}>
                            <Col span={4}>
                              <Tag color="green">{shot.time_range}</Tag>
                              <div style={{ marginTop: 4 }}>
                                <Text type="secondary" style={{ fontSize: 12 }}>{shot.shot_type}</Text>
                              </div>
                            </Col>
                            <Col span={14}>
                              <Text strong>画面：</Text>
                              <Text style={{ display: 'block', marginTop: 2 }}>{shot.visual}</Text>
                              {shot.narration && (
                                <>
                                  <Text strong style={{ marginTop: 6, display: 'block' }}>旁白：</Text>
                                  <Text type="secondary" style={{ display: 'block' }}>{shot.narration}</Text>
                                </>
                              )}
                            </Col>
                            <Col span={6}>
                              <Text type="secondary" style={{ fontSize: 12 }}>作用：</Text>
                              <Text style={{ display: 'block', marginTop: 2 }}>{shot.purpose}</Text>
                            </Col>
                          </Row>
                        </div>
                      ))}
                    </Card>
                  )}

                  {/* 关键要点 */}
                  {analyzeResult.key_points && analyzeResult.key_points.length > 0 && (
                    <Card title="🔑 关键要点" size="small" style={{ marginBottom: 16 }}>
                      {analyzeResult.key_points.map((point: string, i: number) => (
                        <div key={i} style={{ padding: '6px 0', display: 'flex', alignItems: 'flex-start' }}>
                          <Tag color="orange" style={{ marginRight: 8, flexShrink: 0 }}>{i + 1}</Tag>
                          <Text>{point}</Text>
                        </div>
                      ))}
                    </Card>
                  )}

                  {/* 推荐评论 */}
                  {analyzeResult.recommended_comments && analyzeResult.recommended_comments.length > 0 && (
                    <Card title="💬 推荐评论" size="small" style={{ marginBottom: 16 }}>
                      {analyzeResult.recommended_comments.map((comment: string, i: number) => (
                        <div key={i} style={{
                          padding: '8px 12px',
                          background: '#f6f8fa',
                          borderRadius: 6,
                          marginBottom: 8,
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                        }}>
                          <Text>{comment}</Text>
                          <Button
                            size="small"
                            type="link"
                            onClick={() => {
                              navigator.clipboard?.writeText(comment);
                            }}
                          >
                            复制
                          </Button>
                        </div>
                      ))}
                    </Card>
                  )}

                  {/* 视频信息 */}
                  {analyzeResult.video_info && (
                    <Card title="📎 视频信息" size="small">
                      <Row gutter={16}>
                        <Col span={6}><Text strong>标题：</Text></Col>
                        <Col span={18}><Text>{analyzeResult.video_info.title || '-'}</Text></Col>
                      </Row>
                      <Row gutter={16} style={{ marginTop: 8 }}>
                        <Col span={6}><Text strong>作者：</Text></Col>
                        <Col span={18}><Text>{analyzeResult.video_info.author || '-'}</Text></Col>
                      </Row>
                      <Row gutter={16} style={{ marginTop: 8 }}>
                        <Col span={6}><Text strong>时长：</Text></Col>
                        <Col span={18}>
                          <Text>
                            {analyzeResult.video_info.duration > 0
                              ? `${Math.floor(analyzeResult.video_info.duration / 60)}:${String(analyzeResult.video_info.duration % 60).padStart(2, '0')}`
                              : '-'}
                          </Text>
                        </Col>
                      </Row>
                      {analyzeResult.video_info.thumbnail && (
                        <Row gutter={16} style={{ marginTop: 8 }}>
                          <Col span={6}><Text strong>封面：</Text></Col>
                          <Col span={18}>
                            <Image
                              src={analyzeResult.video_info.thumbnail}
                              width={120}
                              style={{ borderRadius: 4 }}
                            />
                          </Col>
                        </Row>
                      )}
                    </Card>
                  )}
                </div>
              )}
            </div>
          ), },

          /* ========== 任务列表 ========== */
          { key: 'tasks', label: <span><PlayCircleOutlined /> 生成任务</span>, children: (
            <Card
              title="口播视频生成任务"
              size="small"
              extra={<Button icon={<ReloadOutlined />} onClick={loadTasks} size="small">刷新</Button>}
            >
              <Table
                dataSource={tasks}
                columns={taskColumns}
                rowKey="id"
                size="small"
                pagination={{ pageSize: 10 }}
                locale={{ emptyText: <Empty description="暂无生成任务" /> }}
              />
            </Card>
          ), },

        ]} />
      </Card>
    </div>
  );
};

export default TalkingHead;
