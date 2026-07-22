export interface VideoIntentError {
  status?: number;
  reason?: string;
}

export function shouldClearVideoIntent(error: VideoIntentError): boolean;
