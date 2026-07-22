export function shouldClearVideoIntent({ status, reason }) {
  if (status === 402) return true;
  if (status !== 409) return false;

  // OAuth reauthentication can still safely recover the same upstream
  // idempotency key. A changed destination or a non-OAuth idempotency
  // conflict instead requires a genuinely new user intent.
  return !reason || reason === 'OPENNOTEBOOK_CONNECTION_CHANGED';
}
