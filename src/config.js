import dotenv from 'dotenv';
dotenv.config();

const parseList = (value, fallback = []) =>
  (value ? value.split(',').map((s) => s.trim()).filter(Boolean) : fallback);

export const config = {
  port: Number(process.env.PORT) || 3000,

  ai: {
    provider: process.env.AI_PROVIDER || 'bedrock', // bedrock | none
    bedrockModelId:
      process.env.BEDROCK_MODEL_ID || 'anthropic.claude-3-5-sonnet-20240620-v1:0',
    bedrockRegion:
      process.env.BEDROCK_REGION || process.env.AWS_REGION || 'us-east-1',
  },

  notify: {
    channels: parseList(process.env.NOTIFY_CHANNELS, ['console']),
    slackWebhookUrl: process.env.SLACK_WEBHOOK_URL || '',
    email: {
      from: process.env.EMAIL_FROM || '',
      to: parseList(process.env.EMAIL_TO),
      sesRegion: process.env.SES_REGION || process.env.AWS_REGION || 'us-east-1',
    },
  },

  poll: {
    enabled: String(process.env.POLL_ENABLED).toLowerCase() === 'true',
    sourceUrl: process.env.POLL_SOURCE_URL || '',
    cron: process.env.POLL_CRON || '*/5 * * * *',
  },
};
