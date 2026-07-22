import assert from 'node:assert/strict';
import test from 'node:test';

import { shouldRetryRequest } from '../src/api/retryPolicy.js';

test('skipRetry blocks network and 5xx retries for paid POST requests', () => {
  assert.equal(
    shouldRetryRequest({ skipRetry: true, hasResponse: false }),
    false,
  );
  assert.equal(
    shouldRetryRequest({ skipRetry: true, hasResponse: true, status: 503 }),
    false,
  );
});

test('ordinary retryable requests retain the bounded retry policy', () => {
  assert.equal(
    shouldRetryRequest({ hasResponse: false, retryCount: 0 }),
    true,
  );
  assert.equal(
    shouldRetryRequest({ hasResponse: true, status: 500, retryCount: 0 }),
    true,
  );
  assert.equal(
    shouldRetryRequest({ hasResponse: true, status: 500, retryCount: 3 }),
    false,
  );
  assert.equal(
    shouldRetryRequest({ hasResponse: true, status: 400, retryCount: 0 }),
    false,
  );
});
