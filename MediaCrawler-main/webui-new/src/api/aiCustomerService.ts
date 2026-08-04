import request from './request';

// ============ 类型定义 ============

export interface YunkeStatus {
  configured: boolean;
  base_url: string;
  username: string;
  logged_in: boolean;
  user_id: number | null;
}

export interface AskResponse {
  ok: boolean;
  answer?: string;
  conversation_id?: number;
  message_id?: number;
  timeout?: boolean;
  error?: string;
}

export interface ConversationInfo {
  id: number;
  conversation_type: string;
  visitor_id: number;
  agent_id: number;
  status: string;
  chat_mode: string;
  unread_count: number;
  has_participated: boolean;
  last_seen_at: string;
  created_at: string;
  updated_at: string;
  last_message?: {
    content: string;
    created_at: string;
    sender_is_agent: boolean;
  };
}

export interface ChatMessage {
  id: number;
  conversation_id: number;
  content: string;
  sender_is_agent: boolean;
  sender_id: number;
  message_type?: string;
  created_at: string;
  file_url?: string;
  file_type?: string;
}

export interface FaqItem {
  id: number;
  question: string;
  answer: string;
  keywords: string;
}

export interface KnowledgeDoc {
  id: number;
  title: string;
  content: string;
  score: number;
  knowledge_base_id: number;
}

export interface AutoReplyPreview {
  ok: boolean;
  reply?: string;
  conversation_id?: number;
  raw_answer?: string;
  timeout?: boolean;
  error?: string;
}

// ============ API 调用 ============

export const getStatus = (): Promise<YunkeStatus> => {
  return request.get('/ai-customer-service/status');
};

export const healthCheck = (): Promise<{ ok: boolean; upstream: unknown }> => {
  return request.get('/ai-customer-service/health');
};

export const forceLogin = (): Promise<YunkeStatus & { ok: boolean }> => {
  return request.post('/ai-customer-service/login');
};

export const ask = (data: {
  question: string;
  visitor_id?: number;
  ai_config_id?: number;
  max_poll_seconds?: number;
}): Promise<AskResponse> => {
  return request.post('/ai-customer-service/ask', data);
};

export const initConversation = (data: {
  visitor_id?: number;
  ai_config_id?: number;
  website?: string;
  chat_mode?: 'ai' | 'human';
}): Promise<{ ok: boolean; conversation_id: number; status: string; visitor_id: number }> => {
  return request.post('/ai-customer-service/conversation/init', data);
};

export const listConversations = (params: {
  conv_type?: 'visitor' | 'internal';
  status?: 'open' | 'closed';
  user_id?: number;
}): Promise<{ ok: boolean; items: ConversationInfo[] }> => {
  return request.get('/ai-customer-service/conversations', { params });
};

export const getMessages = (params: {
  conversation_id: number;
  include_ai_messages?: boolean;
}): Promise<{ ok: boolean; messages: ChatMessage[] }> => {
  return request.get('/ai-customer-service/messages', { params });
};

export const sendMessage = (data: {
  conversation_id: number;
  content: string;
  sender_is_agent?: boolean;
  sender_id?: number;
  use_knowledge_base?: boolean;
  use_llm?: boolean;
}): Promise<{ ok: boolean; message: ChatMessage }> => {
  return request.post('/ai-customer-service/messages', data);
};

export const listFaqs = (query = ''): Promise<{ ok: boolean; faqs: FaqItem[] }> => {
  return request.get('/ai-customer-service/faqs', { params: { query } });
};

export const searchKnowledge = (params: {
  query: string;
  top_k?: number;
}): Promise<{ ok: boolean; documents: KnowledgeDoc[]; count: number }> => {
  return request.get('/ai-customer-service/knowledge/search', { params });
};

export const autoReplyPreview = (data: {
  comment_text: string;
  platform?: string;
  post_summary?: string;
  ai_config_id?: number;
  max_poll_seconds?: number;
}): Promise<AutoReplyPreview> => {
  return request.post('/ai-customer-service/auto-reply/preview', data);
};
