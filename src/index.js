import express from 'express';
import { config } from './config.js';
import { store } from './store.js';
import { ingestNotice } from './pipeline.js';
import { startPoller } from './poller.js';

const app = express();
app.use(express.json({ limit: '1mb' }));

// 헬스체크
app.get('/health', (_req, res) => res.json({ ok: true }));

/**
 * 공지/일정 등록 웹훅.
 * 다른 시스템(게시판, 캘린더 등)이 새 공지를 만들면 여기로 POST 합니다.
 * body: { title, content, type?, startsAt?, url?, sourceId? }
 */
app.post('/notices', async (req, res) => {
  const { title, content } = req.body || {};
  if (!title && !content) {
    return res.status(400).json({ error: 'title 또는 content가 필요합니다.' });
  }
  try {
    const result = await ingestNotice(req.body);
    if (result.skipped) {
      return res.status(200).json({ status: 'skipped', reason: result.reason });
    }
    return res.status(201).json({
      status: 'notified',
      notice: result.notice,
      notifyResults: result.notifyResults,
    });
  } catch (err) {
    console.error('[api] /notices 처리 오류:', err);
    return res.status(500).json({ error: err.message });
  }
});

// 등록된 공지 목록 조회
app.get('/notices', async (_req, res) => {
  res.json(await store.list());
});

app.listen(config.port, () => {
  console.log(`✅ 능동형 공지 서비스 실행 중: http://localhost:${config.port}`);
  console.log(`   AI provider : ${config.ai.provider}`);
  console.log(`   알림 채널   : ${config.notify.channels.join(', ')}`);
  startPoller();
});
