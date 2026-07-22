export interface RetryPolicyInput {
  skipRetry?: boolean;
  retryCount?: number;
  hasResponse: boolean;
  status?: number;
  maxRetries?: number;
}

export const MAX_RETRIES: number;
export function shouldRetryRequest(input: RetryPolicyInput): boolean;
