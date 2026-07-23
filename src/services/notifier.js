import { SESClient, SendEmailCommand } from '@aws-sdk/client-ses';
import { config } from '../config.js';

/**
 * 알림 발송기. NOTIFY_CHANNELS 에 지정된 채널로 능동적으로 알림을 보냅니다.
 * 지원: console, slack, email(SES)
 */

let sesClient = null;
function getSesClient() {
  if (!sesClient) {
    sesClient = new SESClient({ region: config.notify.email.sesRegion });
  }
  return sesClient;
}

function buildMessage(notice) {
  const icon = notice.type === 'schedule' ? '🗓️' : '📢';
  const title = `${icon} 새 ${notice.type === 'schedule' ? '일정' : '공지'}: ${notice.title}`;
  const body = [
    title,
    '',
    notice.summary || notice.content,
    notice.url ? `\n원문: ${notice.url}` : '',
  ].join('\n');
  return { title, body };
}

async function sendConsole(notice) {
  const { body } = buildMessage(notice);
  console.log('\n──────── 🔔 능동형 알림 ────────');
  console.log(body);
  console.log('────────────────────────────────\n');
}

async function sendSlack(notice) {
  if (!config.notify.slackWebhookUrl) {
    console.warn('[notifier] SLACK_WEBHOOK_URL 미설정 — slack 채널 건너뜀');
    return;
  }
  const { body } = buildMessage(notice);
  const res = await fetch(config.notify.slackWebhookUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: body }),
  });
  if (!res.ok) {
    throw new Error(`Slack 전송 실패: ${res.status} ${await res.text()}`);
  }
}

async function sendEmail(notice) {
  const { from, to } = config.notify.email;
  if (!from || to.length === 0) {
    console.warn('[notifier] EMAIL_FROM/EMAIL_TO 미설정 — email 채널 건너뜀');
    return;
  }
  const { title, body } = buildMessage(notice);
  const command = new SendEmailCommand({
    Source: from,
    Destination: { ToAddresses: to },
    Message: {
      Subject: { Data: title, Charset: 'UTF-8' },
      Body: { Text: { Data: body, Charset: 'UTF-8' } },
    },
  });
  await getSesClient().send(command);
}

const handlers = { console: sendConsole, slack: sendSlack, email: sendEmail };

export async function notify(notice) {
  const results = [];
  for (const channel of config.notify.channels) {
    const handler = handlers[channel];
    if (!handler) {
      console.warn(`[notifier] 알 수 없는 채널: ${channel}`);
      continue;
    }
    try {
      await handler(notice);
      results.push({ channel, ok: true });
    } catch (err) {
      console.error(`[notifier] ${channel} 전송 오류: ${err.message}`);
      results.push({ channel, ok: false, error: err.message });
    }
  }
  return results;
}
