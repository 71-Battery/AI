// 설정 없이 전체 파이프라인(등록→요약→알림)을 확인하는 데모 스크립트.
// 실행: npm run demo
import { ingestNotice } from '../src/pipeline.js';

const samples = [
  {
    title: '2026년 1분기 전체 워크샵 안내',
    content:
      '안녕하세요. 2026년 1분기 전사 워크샵을 2026-02-14 오전 10:00 본사 3층 대강당에서 진행합니다. 전 직원 참석 대상이며, 참가 신청은 2026-02-07까지 마감입니다. 준비물은 사원증입니다.',
    type: 'schedule',
    startsAt: '2026-02-14T10:00:00+09:00',
    url: 'https://intra.example.com/notice/101',
    sourceId: 'notice-101',
  },
  {
    title: '사내 시스템 정기 점검',
    content:
      '이번 주 토요일 00:00부터 04:00까지 사내 그룹웨어 정기 점검이 진행됩니다. 해당 시간 동안 로그인이 제한됩니다.',
    type: 'notice',
    sourceId: 'notice-102',
  },
];

for (const s of samples) {
  const result = await ingestNotice(s);
  if (result.skipped) {
    console.log(`(건너뜀: ${result.reason}) ${s.title}`);
  }
}

console.log('\n데모 완료. data/notices.json 에 저장되었습니다.');
