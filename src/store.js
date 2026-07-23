import { promises as fs } from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const DATA_DIR = path.resolve('data');
const DATA_FILE = path.join(DATA_DIR, 'notices.json');

/**
 * 아주 단순한 JSON 파일 기반 저장소.
 * 데모/소규모용이며, 실서비스에서는 DynamoDB/RDS 등으로 교체하세요.
 */
class NoticeStore {
  constructor() {
    this.notices = [];
    this.seenKeys = new Set(); // 중복(이미 처리한 공지) 감지용
    this.loaded = false;
  }

  async load() {
    if (this.loaded) return;
    try {
      const raw = await fs.readFile(DATA_FILE, 'utf-8');
      const parsed = JSON.parse(raw);
      this.notices = parsed.notices || [];
      this.notices.forEach((n) => this.seenKeys.add(this.#key(n)));
    } catch {
      // 파일이 없으면 빈 상태로 시작
      this.notices = [];
    }
    this.loaded = true;
  }

  async #persist() {
    await fs.mkdir(DATA_DIR, { recursive: true });
    await fs.writeFile(
      DATA_FILE,
      JSON.stringify({ notices: this.notices }, null, 2),
      'utf-8'
    );
  }

  // 동일 공지 식별 키: 명시적 sourceId 우선, 없으면 title+content 해시
  #key(notice) {
    if (notice.sourceId) return `sid:${notice.sourceId}`;
    const h = crypto
      .createHash('sha256')
      .update(`${notice.title || ''}::${notice.content || ''}`)
      .digest('hex');
    return `hash:${h}`;
  }

  isDuplicate(notice) {
    return this.seenKeys.has(this.#key(notice));
  }

  async add(notice) {
    await this.load();
    const record = {
      id: crypto.randomUUID(),
      title: notice.title || '(제목 없음)',
      content: notice.content || '',
      type: notice.type || 'notice', // notice | schedule
      startsAt: notice.startsAt || null, // 일정인 경우
      sourceId: notice.sourceId || null,
      url: notice.url || null,
      createdAt: new Date().toISOString(),
      summary: null,
      notified: false,
    };
    this.notices.push(record);
    this.seenKeys.add(this.#key(record));
    await this.#persist();
    return record;
  }

  async update(id, patch) {
    await this.load();
    const idx = this.notices.findIndex((n) => n.id === id);
    if (idx === -1) return null;
    this.notices[idx] = { ...this.notices[idx], ...patch };
    await this.#persist();
    return this.notices[idx];
  }

  async list() {
    await this.load();
    return [...this.notices].sort((a, b) =>
      b.createdAt.localeCompare(a.createdAt)
    );
  }
}

export const store = new NoticeStore();
