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
- `api_server.py`: 기존 백엔드가 호출할 FastAPI 연동 API (`POST /v1/chat`)
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

AWS 인증은 EC2 IAM Role을 사용하며 액세스 키를 코드나 프론트엔드에 넣지 않습니다.

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
