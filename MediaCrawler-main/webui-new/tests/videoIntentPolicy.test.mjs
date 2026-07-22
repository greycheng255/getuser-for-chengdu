import assert from 'node:assert/strict';
import test from 'node:test';

import { shouldClearVideoIntent } from '../src/api/videoIntentPolicy.js';

test('keeps the generation intent after ambiguous transport/server failure', () => {
  assert.equal(shouldClearVideoIntent({}), false);
  assert.equal(shouldClearVideoIntent({ status: 502 }), false);
  assert.equal(shouldClearVideoIntent({ status: 503 }), false);
});

test('clears an intent rejected for billing so a post-top-up click is new', () => {
  assert.equal(shouldClearVideoIntent({ status: 402 }), true);
});

test('only terminal conflicts clear while OAuth reauth preserves recovery key', () => {
  assert.equal(shouldClearVideoIntent({ status: 409 }), true);
  assert.equal(
    shouldClearVideoIntent({
      status: 409,
      reason: 'OPENNOTEBOOK_CONNECTION_CHANGED',
    }),
    true,
  );
  assert.equal(
    shouldClearVideoIntent({
      status: 409,
      reason: 'OPENNOTEBOOK_REAUTH_REQUIRED',
    }),
    false,
  );
});
