import {
  BedrockRuntimeClient,
  InvokeModelCommand,
} from '@aws-sdk/client-bedrock-runtime';
import { config } from '../config.js';

/**
 * 공지/일정 내용을 사용자에게 설명하기 좋은 형태로 요약합니다.
 * - Bedrock(Claude) 사용 가능하면 LLM 요약
 * - 실패하거나 미설정이면 규칙 기반 추출 요약으로 폴백
 */

let bedrockClient = null;
function getBedrockClient() {
  if (!bedrockClient) {
    bedrockClient = new BedrockRuntimeClient({ region: config.ai.bedrockRegion });
  }
  return bedrockClient;
}

const SYSTEM_PROMPT = `너는 조직 공지/일정을 사용자에게 브리핑하는 비서다.
주어진 공지를 한국어로 다음 형식에 맞춰 간결하게 정리해라.
- 핵심요약: 한두 문장
- 중요정보: 날짜/시간/장소/대상/마감 등 있으면 불릿으로
- 해야할일: 사용자가 취해야 할 행동이 있으면 불릿으로 (없으면 생략)
과장 없이 사실만, 존댓말로 작성.`;

async function summarizeWithBedrock(notice) {
  const client = getBedrockClient();
  const userText = [
    `제목: ${notice.title}`,
    notice.type === 'schedule' && notice.startsAt
      ? `일정 시작: ${notice.startsAt}`
      : null,
    `내용:\n${notice.content}`,
  ]
    .filter(Boolean)
    .join('\n');

  const body = {
    anthropic_version: 'bedrock-2023-05-31',
    max_tokens: 600,
    system: SYSTEM_PROMPT,
    messages: [{ role: 'user', content: [{ type: 'text', text: userText }] }],
  };

  const command = new InvokeModelCommand({
    modelId: config.ai.bedrockModelId,
    contentType: 'application/json',
    accept: 'application/json',
    body: JSON.stringify(body),
  });

  const response = await client.send(command);
  const payload = JSON.parse(new TextDecoder().decode(response.body));
  const text = payload?.content?.[0]?.text?.trim();
  if (!text) throw new Error('Bedrock 응답이 비어 있습니다.');
  return text;
}

// LLM 없이도 동작하는 아주 단순한 추출 요약(폴백)
function fallbackSummary(notice) {
  const clean = (notice.content || '').replace(/\s+/g, ' ').trim();
  const sentences = clean.split(/(?<=[.!?。])\s+/).filter(Boolean);
  const head = sentences.slice(0, 2).join(' ');

  const lines = [`핵심요약: ${head || notice.title}`];
  const info = [];
  if (notice.type === 'schedule' && notice.startsAt) {
    info.push(`- 일정 시작: ${notice.startsAt}`);
  }
  const dateMatch = clean.match(
    /\d{4}[-./]\d{1,2}[-./]\d{1,2}|\d{1,2}월\s*\d{1,2}일|\d{1,2}:\d{2}/g
  );
  if (dateMatch) info.push(`- 날짜/시간 언급: ${[...new Set(dateMatch)].join(', ')}`);
  if (notice.url) info.push(`- 링크: ${notice.url}`);

  if (info.length) {
    lines.push('중요정보:');
    lines.push(...info);
  }
  return lines.join('\n');
}

export async function summarize(notice) {
  if (config.ai.provider === 'bedrock') {
    try {
      return await summarizeWithBedrock(notice);
    } catch (err) {
      console.warn(
        `[summarizer] Bedrock 요약 실패, 폴백 사용: ${err.message}`
      );
    }
  }
  return fallbackSummary(notice);
}
