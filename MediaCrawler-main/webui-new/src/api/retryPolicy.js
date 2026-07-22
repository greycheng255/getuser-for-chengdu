/** Shared retry decision kept framework-free so paid request behavior is testable. */
export const MAX_RETRIES = 3;

/**
 * @param {{
 *   skipRetry?: boolean,
 *   retryCount?: number,
 *   hasResponse: boolean,
 *   status?: number,
 *   maxRetries?: number,
 * }} input
 */
export function shouldRetryRequest({
  skipRetry = false,
  retryCount = 0,
  hasResponse,
  status,
  maxRetries = MAX_RETRIES,
}) {
  if (skipRetry || retryCount >= maxRetries) return false;
  if (!hasResponse) return true;
  return status === 429 || (typeof status === 'number' && status >= 500);
}
