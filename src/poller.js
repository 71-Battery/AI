import cron from 'node-cron';
import { config } from './config.js';
import { ingestNotice } from './pipeline.js';

/**
 * 외부 소스를 주기적으로 확인해 새 공지를 자동 감지하는 능동형 트리거(옵션).
 * POLL_SOURCE_URL 은 아래 형태의 JSON 배열을 반환한다고 가정합니다:
 *   [{ "sourceId": "123", "title": "...", "content": "...", "type": "notice", "url": "..." }]
 * 실제 소스에 맞게 normalize()만 수정하면 됩니다.
 */

function normalize(item) {
  return {
    sourceId: item.sourceId ?? item.id ?? null,
    title: item.title ?? item.subject ?? '(제목 없음)',
    content: item.content ?? item.body ?? item.description ?? '',
    type: item.type ?? (item.startsAt ? 'schedule' : 'notice'),
    startsAt: item.startsAt ?? item.date ?? null,
    url: item.url ?? item.link ?? null,
  };
}

async function pollOnce() {
  if (!config.poll.sourceUrl) {
    console.warn('[poller] POLL_SOURCE_URL 미설정 — 폴링 건너뜀');
    return;
  }
  try {
    const res = await fetch(config.poll.sourceUrl);
    if (!res.ok) throw new Error(`소스 응답 ${res.status}`);
    const data = await res.json();
    const items = Array.isArray(data) ? data : data.items || [];
    let newCount = 0;
    for (const raw of items) {
      const result = await ingestNotice(normalize(raw));
      if (!result.skipped) newCount++;
    }
    if (newCount > 0) console.log(`[poller] 새 공지 ${newCount}건 처리`);
  } catch (err) {
    console.error(`[poller] 폴링 오류: ${err.message}`);
  }
}

export function startPoller() {
  if (!config.poll.enabled) return;
  if (!cron.validate(config.poll.cron)) {
    console.error(`[poller] 잘못된 CRON 표현식: ${config.poll.cron}`);
    return;
  }
  console.log(`[poller] 활성화됨 (cron: ${config.poll.cron})`);
  cron.schedule(config.poll.cron, pollOnce);
  // 시작 시 1회 즉시 실행
  pollOnce();
}
