# 🎓 교내 공지·학사정보 통합 AI 도우미 — AI 엔진

학생의 학년·학과 정보를 바탕으로 학사규정, 기업 협력사, 실무프로젝트, 교육과정 문서를 검색하고 학교 특성에 맞춰 답변하는 RAG AI 엔진입니다.

이 저장소는 학생용 UI가 아니라 **프론트/기존 백엔드가 호출하는 AI 기능과 API 연동 통로**를 제공합니다.

## 역할 분리

```text
프론트엔드 → 기존 백엔드(인증·회원 DB) → Campus AI API → 기존 백엔드 → 프론트엔드
                                             ├─ FAISS 검색
                                             ├─ Titan 임베딩
                                             └─ Bedrock Claude 답변
```

- 프론트엔드: 질문 입력, 답변/출처 표시
- 기존 백엔드: JWT 검증, `user_id` 확인, 회원 DB에서 학년·학과 조회, AI API 호출
- 이 프로젝트: RAG 검색, 프롬프트 구성, Claude 호출, 출처 생성
- AWS 자격증명과 내부 문서는 프론트엔드에 노출하지 않음

## 주요 파일

- `ai_service.py`: UI 프레임워크가 없는 AI 엔진. 프로필 식별, FAISS 검색, 프롬프트, Claude, 출처 반환
- `api_server.py`: 기존 백엔드가 호출할 FastAPI 연동 API (`POST /v1/chat`, 공지 API)
- `notice_service.py`: 공지 중복검사·JSON 저장·Bedrock 요약·fallback 요약·console/Slack/SES 알림·외부 polling
- `bedrock_faiss_indexer.py`: 카테고리별 문서를 청킹하고 FAISS 인덱스를 생성
- `bedrock_faiss_rag_chatbot.py`: AI 엔진 동작을 확인하는 CLI 테스트
- `bedrock_simple_test.py`: Bedrock 연결 테스트
- `knowledge_base/`: 학사규정·기업 협력사·실무프로젝트·교육과정 원본 문서
- `faiss_index/`: 생성된 로컬 벡터 인덱스
- `ai_backend_integration_spec.md`: 백엔드 담당자에게 전달할 작업 명세서와 AI 코딩 프롬프트
- `Dockerfile`, `docker-compose.yml`: API 컨테이너 실행 설정
- `campus-ai-api.service`: EC2 systemd 운영 설정

## AI API 계약

### 요청

```http
POST /v1/chat
Content-Type: application/json
```

```json
{
  "query": "현장실습은 어떻게 신청해?",
  "grade": "3학년",
  "department": "소프트웨어개발과",
  "top_k": 4,
  "score_threshold": 1.5
}
```

`grade`와 `department`는 기존 백엔드가 JWT의 `user_id`로 회원 DB에서 조회해 전달해야 합니다. 프론트가 보낸 프로필을 그대로 신뢰하지 마세요. 값이 없으면 질문 텍스트에서 보조적으로 추론합니다.

### 응답

```json
{
  "answer": "3학년 소프트웨어개발과 학생은 3학년 2학기부터 현장실습을 신청할 수 있습니다.",
  "profile": {
    "grade": "3학년",
    "department": "소프트웨어개발과"
  },
  "sources": [
    {
      "category": "기업 협력사",
      "document": "01_기업_협력사.md",
      "snippet": "3학년 2학기부터 현장실습 신청이 가능하다.",
      "score": 0.42
    }
  ],
  "has_context": true,
  "retrieval": {
    "top_k": 4,
    "score_threshold": 1.5,
    "matched": true
  },
  "request_id": "uuid"
}
```

### 오류 응답

```json
{
  "error": {
    "code": "KNOWLEDGE_BASE_UNAVAILABLE",
    "message": "사용자에게 보여줄 안전한 메시지",
    "request_id": "uuid"
  }
}
```

- `400 INVALID_REQUEST`: 빈 질문 또는 잘못된 검색 옵션
- `502 AI_PROVIDER_UNAVAILABLE`: Bedrock 호출 실패
- `503 KNOWLEDGE_BASE_UNAVAILABLE`: FAISS 인덱스 로드 실패

## 로컬 실행

```bash
python3 -m venv venv
# Windows PowerShell: .\venv\Scripts\Activate.ps1
# Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
python bedrock_faiss_indexer.py
uvicorn api_server:app --host 0.0.0.0 --port 8000
```

- API 문서: `http://localhost:8000/docs`
- 헬스체크: `GET http://localhost:8000/health`
- 질의 API: `POST http://localhost:8000/v1/chat`
- 공지 등록: `POST http://localhost:8000/v1/notices`
- 공지 목록: `GET http://localhost:8000/v1/notices`
- 공지 source 수동 polling: `POST http://localhost:8000/v1/notices/poll`

```bash
curl -X POST http://localhost:8000/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"3학년 현장실습은 어떻게 신청해?","grade":"3학년","department":"소프트웨어개발과"}'
```

## 환경변수

- `AWS_REGION` (기본 `us-east-1`)
- `BEDROCK_MODEL_ID` (기본 `us.anthropic.claude-sonnet-5`)
- `EMBEDDING_MODEL_ID` (기본 `amazon.titan-embed-text-v2:0`)
- `FAISS_INDEX_PATH` (기본 `faiss_index`)
- `API_PREFIX` (기본 `/v1`)
- `CORS_ORIGINS` (기본 `http://localhost:3000`, 직접 브라우저 호출이 필요한 개발 환경에서만 설정)
- `NOTICE_DATA_FILE` (기본 `data/notices.json`)
- `NOTICE_AI_PROVIDER` (기본 `bedrock`, `fallback` 지정 시 규칙 기반 요약)
- `NOTICE_BEDROCK_MODEL_ID` / `NOTICE_BEDROCK_REGION` (공지 요약용 Bedrock 설정)
- `NOTICE_POLL_SOURCE_URL` (선택, JSON 배열 또는 `{ "items": [] }`를 반환하는 외부 공지 URL)
- `NOTICE_POLL_INTERVAL_SECONDS` (기본 `300`, URL이 있을 때 백그라운드 polling 주기)
- `NOTICE_CHANNELS` (기본 `console`, 쉼표 구분: `console`, `slack`, `email`)
- `SLACK_WEBHOOK_URL`, `EMAIL_FROM`, `EMAIL_TO`, `SES_REGION` (해당 알림 채널 사용 시)

AWS 인증은 EC2 IAM Role을 사용하며 액세스 키를 코드나 프론트엔드에 넣지 않습니다.

## 공지·알림 API

학사정보 질의(`/v1/chat`)와 분리된 공지 처리 흐름입니다. 공지는 등록되면 저장 → 요약 → 선제 알림 순서로 처리됩니다. 이 API는 기존 백엔드의 내부 관리자/수집 서버에서 호출하고, 인증·권한 검증은 기존 백엔드 경계에서 적용해야 합니다.

### 공지 등록 요청

```json
{
  "title": "2026학년도 현장실습 신청 안내",
  "content": "3학년 재학생은 8월 1일까지 신청서를 제출하세요.",
  "type": "notice",
  "starts_at": null,
  "url": "https://school.example/notices/123",
  "source_id": "school-123",
  "target_grade": "3학년",
  "target_department": "소프트웨어개발과"
}
```

`source_id`가 있으면 이를 우선 사용하고, 없으면 제목과 본문 SHA-256 해시로 중복을 판별합니다. 중복 등록은 HTTP 200과 `skipped: true`로 반환되며 새 알림을 보내지 않습니다.

```json
{
  "skipped": false,
  "notice": {
    "id": "uuid",
    "title": "2026학년도 현장실습 신청 안내",
    "summary": "핵심요약: ...",
    "summary_provider": "bedrock",
    "notified": true
  },
  "notify_results": [{"channel": "console", "ok": true}]
}
```

`NOTICE_POLL_SOURCE_URL`을 설정하면 API 프로세스가 시작된 뒤 지정 주기마다 외부 JSON 공지를 polling합니다. URL이 없으면 자동 polling은 비활성화되며, 수동 polling API는 `enabled: false`를 반환합니다. Bedrock 요약이 실패하면 공지 원문에서 추출한 fallback 요약으로 계속 처리합니다.

## 인덱스 갱신

```bash
python bedrock_faiss_indexer.py
```

관리자 문서 업로드/재인덱싱은 학생용 API와 분리된 기존 백엔드 관리자 기능으로 연결해야 합니다. 일반 학생 질의 API가 파일을 쓰거나 인덱스를 재생성하지 않도록 하세요.

## 운영 배포

- systemd: `campus-ai-api.service`
- 내부 API 포트: `127.0.0.1:8000`
- Nginx: 외부 `80` → 내부 `8000`
- 로그: `sudo journalctl -u campus-ai-api -f`
- 재시작: `sudo systemctl restart campus-ai-api`

## 백엔드 담당자용 명세서

`ai_backend_integration_spec.md`에 회원 DB·JWT·AI 엔진 연결 순서, 요청/응답 계약, 보안 요구사항, AI 코딩 도구에 전달할 전문 프롬프트를 작성해 두었습니다.
