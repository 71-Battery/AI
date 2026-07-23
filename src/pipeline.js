import { store } from './store.js';
import { summarize } from './services/summarizer.js';
import { notify } from './services/notifier.js';

/**
 * 능동형 파이프라인의 핵심.
 * 새 공지가 들어오면: 저장 → AI 요약 → 사용자에게 먼저 알림.
 */
export async function ingestNotice(input) {
  await store.load();

  // 이미 본 공지는 건너뜀(폴링 중복 방지)
  if (store.isDuplicate(input)) {
    return { skipped: true, reason: 'duplicate' };
  }

  const notice = await store.add(input);

  // 1) AI가 내용을 요약·설명
  const summary = await summarize(notice);
  await store.update(notice.id, { summary });

  // 2) 사용자에게 먼저 능동적으로 알림
  const notifyResults = await notify({ ...notice, summary });
  await store.update(notice.id, { notified: true });

  return { skipped: false, notice: { ...notice, summary }, notifyResults };
}
