# AI-백엔드 연동 작업 명세서

이 문서는 백엔드 담당자가 회원·인증 서버와 교내 학사정보 AI 엔진을 연결하기 위한 작업 지시서입니다. 학사정보 질의 엔진은 `ai_service.py`, FastAPI 연동 API와 공지·알림 API는 `api_server.py`, 공지 처리 기능은 `notice_service.py`에 구현되어 있습니다.

학사정보 챗봇과 공지·알림 챗봇은 목적이 다르므로 프롬프트와 처리 흐름을 분리합니다. 학사정보 챗봇은 고정 문서 검색과 출처 기반 정확성에 집중하고, 공지·알림 챗봇은 신규 공지의 중복 제거·요약·선제 알림에 집중합니다.

## 백엔드 담당자용 AI 작업 프롬프트

아래 내용을 그대로 AI 코딩 도구에 입력해 작업하세요.

```text
너는 백엔드 연동 담당 개발자다. 기존 회원가입/로그인 백엔드에 교내 공지·학사정보 통합 AI 엔진을 연결해라.

[프로젝트 구조]
- AI 엔진: ai_service.py
- AI 연동 API 예시: api_server.py
- 지식베이스 인덱서: bedrock_faiss_indexer.py
- AI 모델/벡터 DB: Amazon Bedrock Claude + Titan Embed Text v2 + FAISS
- AI 엔진은 프론트엔드나 회원 DB에 직접 접근하지 않는다.

[역할 분리]
- 너의 백엔드: 회원가입, 로그인, JWT 검증, user_id 확인, 회원 DB 조회, 외부 API 제공
- AI 엔진: 질문 프로파일 처리, FAISS 검색, Claude 호출, 답변 생성, 출처 생성
- 프론트엔드: 질문 입력, 로딩/스트리밍 표시, 답변과 출처 표시

[필수 요청 흐름]
1. 프론트엔드가 인증 토큰과 질문을 백엔드에 보낸다.
2. 백엔드는 JWT를 검증하고 토큰의 user_id로 회원 DB를 조회한다.
3. 회원 DB의 grade와 department를 신뢰할 값으로 사용한다. 프론트가 보낸 학년/학과를 그대로 신뢰하지 않는다.
4. 백엔드는 다음 형태로 AI 엔진을 호출한다.
   answer_question(query=<질문>, grade=<회원DB 학년>, department=<회원DB 학과>, top_k=4, score_threshold=1.5)
5. AI 엔진 반환값을 프론트엔드 계약에 맞게 전달한다.
6. AI 내부 오류나 지식베이스 오류의 내부 traceback, AWS 응답 원문, 파일 경로, 자격증명을 외부에 노출하지 않는다.

[AI 엔진 호출 계약]
입력:
{
  "query": "현장실습은 어떻게 신청해?",
  "grade": "3학년",
  "department": "소프트웨어개발과",
  "top_k": 4,
  "score_threshold": 1.5
}

반환:
{
  "answer": "AI가 생성한 학교 정보 답변",
  "profile": {
    "grade": "3학년",
    "department": "소프트웨어개발과"
  },
  "sources": [
    {
      "category": "기업 협력사",
      "document": "01_기업_협력사.md",
      "snippet": "원문 일부",
      "score": 0.42
    }
  ],
  "has_context": true,
  "retrieval": {
    "top_k": 4,
    "score_threshold": 1.5,
    "matched": true
  }
}

[외부 백엔드 API]
기존 백엔드의 학생용 엔드포인트를 POST /api/v1/chat으로 만든다.
요청:
{
  "query": "소프트웨어개발과 2학년 교육과정 알려줘"
}

처리:
- grade, department는 Authorization 토큰으로 식별한 회원 DB에서 조회
- AI 엔진에 grade, department를 전달

응답:
{
  "answer": "...",
  "profile": {"grade": "2학년", "department": "소프트웨어개발과"},
  "sources": [],
  "has_context": true,
  "request_id": "uuid"
}

[오류 계약]
모든 오류는 아래 형식으로 통일한다.
{
  "error": {
    "code": "INVALID_REQUEST",
    "message": "사용자에게 보여줄 안전한 메시지",
    "request_id": "uuid"
  }
}

상태 코드:
- 400 INVALID_REQUEST: 빈 질문, 허용되지 않은 학년/학과, 잘못된 top_k
- 401 UNAUTHORIZED: 로그인 토큰 없음 또는 유효하지 않음
- 403 FORBIDDEN: 관리자 기능 권한 없음
- 502 AI_PROVIDER_UNAVAILABLE: Bedrock 호출 실패
- 503 KNOWLEDGE_BASE_UNAVAILABLE: FAISS 인덱스 없음/로드 실패

[보안 요구사항]
- 프론트엔드에 AWS 자격증명, Bedrock 모델 ID, FAISS 경로를 전달하지 않는다.
- AI API를 외부에 직접 공개하지 말고 백엔드 내부에서만 호출한다.
- grade와 department는 회원 DB 값을 우선한다.
- 관리자 문서 업로드/인덱스 재생성 API에는 별도 관리자 권한을 적용한다.
- 사용자 질문과 AI 응답을 로그에 남길 때 비밀번호, 토큰, 개인정보를 기록하지 않는다.

[완료 조건]
- 회원 로그인 후 POST /api/v1/chat 호출 가능
- 회원 DB의 학년/학과가 AI 응답 profile에 반영됨
- answer와 sources가 프론트로 전달됨
- 지식베이스 밖 질문은 has_context=false로 반환됨
- AI/FAISS 장애가 안전한 오류 JSON으로 반환됨
- 단위 테스트 또는 통합 테스트에 위 시나리오가 포함됨
- API 명세(OpenAPI 또는 README)에 요청/응답 예시가 기록됨
``` 

## AI API 직접 호출 예시

현재 프로젝트의 AI 연동 서버를 직접 실행할 때:

```bash
uvicorn api_server:app --host 0.0.0.0 --port 8000
```

요청:

```bash
curl -X POST http://localhost:8000/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"3학년 현장실습은 어떻게 신청해?","grade":"3학년","department":"소프트웨어개발과"}'
```

Swagger 문서:

```text
http://localhost:8000/docs
```

## 공지·알림 API 계약

공지 수집기 또는 기존 백엔드의 관리자 기능이 다음 API를 호출합니다. 학생 프론트엔드가 공지 API와 Bedrock을 직접 호출하지 않습니다.

`POST /v1/notices`

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

등록 응답에는 `skipped`, `notice.summary`, `notice.summary_provider`, `notice.notified`, `notify_results`가 포함됩니다. `source_id`가 없으면 제목·본문 해시로 중복을 판별합니다. 중복이면 `skipped: true`이며 저장·요약·알림을 다시 실행하지 않습니다.

`GET /v1/notices?limit=50`은 최신 공지 목록을 반환하고, `POST /v1/notices/poll`은 외부 JSON source를 즉시 한 번 조회합니다. 외부 source는 배열 또는 `{ "items": [] }` 형태를 반환해야 합니다. `NOTICE_POLL_SOURCE_URL`이 설정된 경우에만 프로세스 내부 백그라운드 polling이 활성화됩니다.

공지 API의 기본 알림 채널은 `console`입니다. Slack은 `SLACK_WEBHOOK_URL`, SES 이메일은 `EMAIL_FROM`, `EMAIL_TO`, `SES_REGION`을 설정해야 합니다. Bedrock 요약 실패 시 규칙 기반 fallback 요약을 사용하므로 공지 저장과 알림은 계속됩니다.

## 협업 시 지켜야 할 경계

- 백엔드 담당자는 `ai_service.py` 내부의 검색·프롬프트·Bedrock 로직을 임의로 복제하지 않는다.
- AI 담당자는 회원 비밀번호, JWT 비밀키, 회원 DB 연결정보를 AI 모듈에 넣지 않는다.
- 백엔드는 회원 DB에서 조회한 학년·학과를 `answer_question()`에 전달한다.
- 프론트엔드는 백엔드 API만 호출하고 Bedrock/FAISS에 직접 접근하지 않는다.
