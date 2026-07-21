import type { Lead } from '../types';

export const exportToCSV = (leads: Lead[], filename: string = 'leads_export') => {
  const headers = ['ID', '平台', '用户', '用户ID', 'IP属地', '标题', '内容', '评分', '意图', '状态', '匹配关键词', '链接', '创建时间'];
  
  const rows = leads.map(lead => [
    lead.id,
    lead.platform,
    lead.nickname,
    lead.user_id,
    lead.ip_location,
    lead.title || '',
    lead.content || '',
    lead.lead_score,
    lead.intent_type,
    lead.status,
    lead.matched_keywords || '',
    lead.url || '',
    lead.add_ts ? new Date(lead.add_ts).toLocaleString() : '',
  ]);

  const csvContent = [headers, ...rows]
    .map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(','))
    .join('\n');

  const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `${filename}_${new Date().toISOString().slice(0, 10)}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
};

export const exportToJSON = (leads: Lead[], filename: string = 'leads_export') => {
  const data = JSON.stringify(leads, null, 2);
  const blob = new Blob([data], { type: 'application/json' });
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = `${filename}_${new Date().toISOString().slice(0, 10)}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
};
