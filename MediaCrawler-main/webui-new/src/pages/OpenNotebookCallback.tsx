import { useEffect, useMemo } from 'react';
import { Button, Result } from 'antd';

const safeReturnTo = (value: string | null) => {
  if (!value || !value.startsWith('/') || value.startsWith('//') || value.includes('\\')) {
    return '/x-workbench';
  }
  return value;
};

const OpenNotebookCallback = () => {
  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const result = params.get('result') === 'success' ? 'success' : 'error';
  const error = params.get('error') || '';
  const returnTo = safeReturnTo(params.get('return_to'));

  useEffect(() => {
    if (window.opener && !window.opener.closed) {
      // callback 只通知成败，Token/code/state 从不进入前端消息。
      window.opener.postMessage(
        { type: 'opennotebook-oauth-complete', result, error },
        window.location.origin,
      );
      const closeTimer = window.setTimeout(() => window.close(), 150);
      return () => window.clearTimeout(closeTimer);
    }
    // 弹窗被拦截时使用整页跳转，callback 自动回到原功能页。
    const redirectTimer = window.setTimeout(() => window.location.replace(returnTo), 700);
    return () => window.clearTimeout(redirectTimer);
  }, [error, result, returnTo]);

  const success = result === 'success';
  return (
    <Result
      status={success ? 'success' : 'error'}
      title={success ? 'OpenNotebook 连接成功' : 'OpenNotebook 连接失败'}
      subTitle={success ? '授权凭证已安全保存，正在返回 MediaCrawler。' : '请返回 MediaCrawler 重新授权。'}
      extra={<Button type="primary" onClick={() => window.location.replace(returnTo)}>返回 MediaCrawler</Button>}
    />
  );
};

export default OpenNotebookCallback;
