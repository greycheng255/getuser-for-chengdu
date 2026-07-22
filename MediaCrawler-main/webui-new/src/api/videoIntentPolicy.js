export function shouldClearVideoIntent({ status, reason }) {
  if (status === 402) return true;
  if (status !== 409) return false;

  // A request conflict requires a genuinely new local generation intent.
  // Transient/unknown submission failures intentionally retain the key so
  // the backend can suppress an unsafe duplicate paid AI6700 submission.
  return !reason || reason === 'OPENNOTEBOOK_CONNECTION_CHANGED';
}
