import request from './request';

export interface OpenNotebookConnectionStatus {
  connected: boolean;
  status: 'active' | 'disconnected' | 'reauth_required' | 'revoked' | 'error' | string;
  needs_reauth: boolean;
  provider_user_id?: string;
  tenant_id?: string;
  workspace_id?: string;
  workspace_name?: string;
  grant_id?: string;
  scope?: string;
  access_token_expires_ts?: number;
  refresh_token_expires_ts?: number;
  connected_at?: number;
  updated_at?: number;
}

export interface OpenNotebookOAuthStartResponse {
  authorization_url: string;
  expires_ts: number;
}

export const openNotebookApi = {
  status: () =>
    request.get<any, OpenNotebookConnectionStatus>('/integrations/opennotebook/status'),

  start: (returnTo = '/x-workbench') =>
    request.post<any, OpenNotebookOAuthStartResponse>(
      '/integrations/opennotebook/start',
      { return_to: returnTo },
      // Required when the frontend and MediaCrawler API use different origins:
      // the callback-bound HttpOnly cookie must be stored by the browser.
      { withCredentials: true },
    ),

  disconnect: () =>
    request.post<any, { connected: false; disconnected: boolean }>(
      '/integrations/opennotebook/disconnect',
    ),
};
