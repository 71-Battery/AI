# Design Document

## Overview

교내 공지·학사정보 통합 AI 도우미(Campus_Assistant)는 학교의 흩어진 정보를 하나의 벡터 지식베이스로 통합하고, 학생의 자연어 질문에 RAG(Retrieval-Augmented Generation) 방식으로 답변하는 Streamlit 웹 챗봇이다.

이 문서는 요구사항 문서(requirements.md)의 6개 요구사항을 실현하기 위한 기술 설계를 정의한다. 기존 프로젝트의 인프라(Streamlit, Amazon Bedrock, FAISS, LangChain, S3, EC2 systemd+Nginx 배포)를 최대한 재활용하되, 주제와 3가지 중심 기능(학년/학과 파악, 관련 정보 검색, 학교 특성 맞춤 설명)에 맞춰 컴포넌트를 재구성한다.

### 설계 목표

- **재활용성**: 기존 검증된 RAG 파이프라인(Titan 임베딩 → FAISS 검색 → Claude 생성)과 출처 메타데이터 패턴을 그대로 계승
- **개인화**: 학생 프로파일(학년/학과)을 검색과 답변 생성 양쪽에 반영
- **카테고리 인지**: 4개 Document_Category(학사규정, 기업 협력사, 실무프로젝트 목록, 교육과정)를 메타데이터로 관리
- **신뢰성**: 환각 방어, 출처 표시, 부분 장애 격리

### 기술 스택

| 영역 | 기술 |
|------|------|
| 프론트엔드/앱 | Python 3.12 + Streamlit |
| LLM | Amazon Bedrock Claude (`us.anthropic.claude-sonnet-5`) |
| 임베딩 | Amazon Titan Embed Text v2 (`amazon.titan-embed-text-v2:0`) |
| 벡터 DB | FAISS (로컬 파일, `faiss-cpu`) |
| 오케스트레이션 | LangChain (`langchain-aws`, `langchain-community`) |
| 문서 저장 | AWS S3 |
| 배포 | EC2 (Ubuntu) + systemd + Nginx |
| 인증 | EC2 IAM Role (키리스) |

## Architecture

### 시스템 구성도

```
┌─────────────────────────────────────────────────────────────┐
│                     Query_Interface (Streamlit)              │
│  ┌────────────────────┐        ┌──────────────────────────┐ │
│  │  💬 학사 Q&A 페이지 │        │ 📁 지식베이스 관리 페이지 │ │
│  │  - 학년/학과 선택   │        │  - 카테고리별 문서 업로드 │ │
│  │  - 질문 입력        │        │  - 인덱싱 실행            │ │
│  │  - 답변 + 출처 표시 │        │  - 등록 문서 목록         │ │
│  └─────────┬──────────┘        └────────────┬─────────────┘ │
└────────────┼──────────────────────────────-─┼───────────────┘
             │ 질문 + Student_Profile          │ 문서 + Category
             ▼                                 ▼
   ┌──────────────────┐              ┌──────────────────┐
   │ Profile_Identifier│              │     Indexer      │
   │ (학년/학과 식별)  │              │ (청킹+메타데이터) │
   └────────┬─────────┘              └────────┬─────────┘
            │                                 │
            ▼                                 ▼
   ┌──────────────────┐              ┌──────────────────┐
   │    Retriever     │◄─────────────│  Knowledge_Base  │
   │ (임베딩+유사검색) │   load/query │  (FAISS Index)   │
   └────────┬─────────┘              └──────────────────┘
            │ 검색 청크 + 메타데이터           ▲
            ▼                                 │ save
   ┌──────────────────┐              ┌──────────────────┐
   │ Answer_Generator │              │   AWS Services   │
   │ (Claude 호출)    │─────────────►│ Bedrock / S3     │
   └────────┬─────────┘   IAM Role   └──────────────────┘
            │ 답변 + Source_Citation
            ▼
      Query_Interface (표시)
```

### 처리 흐름 (질의응답)

```
1. 학생이 질문 제출 (+ 사이드바에서 학년/학과 선택 가능)
2. Profile_Identifier가 Student_Profile 구성
   - 명시적 선택값 우선, 없으면 질문 텍스트에서 추론, 그래도 없으면 "미지정"
3. Retriever가 질문을 Titan으로 임베딩 → FAISS에서 top-k(4) 검색
   - Relevance_Score와 함께 청크 + (category, source) 메타데이터 반환
4. 임계값 필터: 모든 점수가 임계값 미만이면 "관련 정보 없음" 경로로 분기
5. Answer_Generator가 프롬프트 구성 (참고문서 + Student_Profile + 학교 맥락 지침)
   → Claude 스트리밍 호출
6. Source_Citation 생성 (문서명 + 카테고리 + 원본 발췌)
7. Query_Interface가 답변 + 출처 카드 렌더링, 대화기록에 저장
```

## Components and Interfaces

### 1. Profile_Identifier (학년/학과 식별) — 신규

3가지 중심 기능 중 첫 번째. 학생의 학년(Grade)과 학과(Department)를 식별한다.

**식별 우선순위**
1. 사이드바에서 명시적으로 선택한 값 (최우선)
2. 질문 텍스트에서 규칙 기반 추출 (예: "3학년", "소프트웨어과", "SW과")
3. 둘 다 실패 시 "미지정"

**인터페이스**
```python
def identify_profile(query: str, explicit_grade: str | None,
                     explicit_dept: str | None) -> StudentProfile:
    """명시적 입력 우선, 없으면 질문 텍스트에서 학년/학과 추론."""
```

규칙 기반 추출은 정규식과 학과 별칭 사전(alias map)을 사용한다. LLM 추론 대신 규칙 기반을 채택하는 이유는 추가 Bedrock 호출 비용/지연 없이 결정적으로 동작하기 때문이다. (요구사항 2.2, 2.3)

### 2. Retriever (관련 정보 검색) — 기존 재활용 + 확장

3가지 중심 기능 중 두 번째. 기존 `db.similarity_search`를 `similarity_search_with_score`로 교체하여 Relevance_Score를 확보한다.

**인터페이스**
```python
def retrieve(db, query: str, k: int = 4,
             score_threshold: float = THRESHOLD) -> list[RetrievedChunk]:
    """질문 임베딩으로 top-k 검색. 각 청크에 score와 메타데이터(category, source) 포함."""
```

- FAISS의 L2 거리 기반이므로 점수는 "작을수록 유사". 임계값 비교 로직은 이 방향성을 고려한다. (요구사항 3.2, 3.5)
- 반환 청크에는 `category`, `source` 메타데이터가 포함된다. (요구사항 3.4)

### 3. Answer_Generator (학교 특성 맞춤 설명) — 기존 재활용 + 프롬프트 개편

3가지 중심 기능 중 세 번째. 검색된 청크와 Student_Profile을 결합한 프롬프트로 Claude를 스트리밍 호출한다.

**프롬프트 구조**
```
당신은 OO학교 학생을 돕는 교내 학사정보 안내 도우미입니다.
아래 [참고문서]만을 근거로 학생의 질문에 답하세요.
참고문서에 근거가 없으면 "제공된 지식베이스에는 해당 정보가 없습니다"라고 답하세요.

[학생 정보]
- 학년: {grade}
- 학과: {department}
(학년/학과에 해당하는 규정·과정·프로젝트가 있으면 그에 맞춰 설명하세요.
 미지정 항목이 있으면 일반 정보로 답하고 학년/학과 확인을 정중히 요청하세요.)

[참고문서]
[카테고리: 학사규정 | 출처: 파일명]
...청크...
---
질문: {query}
답변:
```

**인터페이스**
```python
def stream_answer(profile: StudentProfile, chunks: list[RetrievedChunk],
                  query: str) -> Iterator[str]:
    """프롬프트 구성 후 Claude 스트리밍 응답을 청크 단위로 yield."""
```

- 응답 파싱은 `content` 배열에서 text 타입 블록만 안전 추출 (기존 발견된 KeyError 버그 방지). (요구사항 4.6)
- Source_Citation은 검색된 청크에서 결정적으로 구성 (LLM이 아닌 코드가 생성). 청크가 있으면 항상 출처 생성 가능. (요구사항 4.4, 4.5)

### 4. Indexer (지식베이스 구축) — 기존 재활용 + 카테고리 확장

카테고리별 하위 폴더 구조로 문서를 관리하고, 각 청크에 `category`와 `source` 메타데이터를 부여한다.

**저장소 구조**
```
knowledge_base/
├── academic_rules/      # 학사규정
├── partner_companies/   # 기업 협력사
├── field_projects/      # 실무프로젝트 목록
└── curriculum/          # 교육과정
```

**인터페이스**
```python
CATEGORY_DIRS = {
    "학사규정": "academic_rules",
    "기업 협력사": "partner_companies",
    "실무프로젝트 목록": "field_projects",
    "교육과정": "curriculum",
}

def rebuild_index() -> tuple[int, int]:
    """모든 카테고리 폴더의 문서를 청킹(500자/overlap 50)하고
    category+source 메타데이터를 부여해 FAISS 인덱스 재빌드. (문서수, 청크수) 반환."""
```

- 처리 문서가 없으면 (0, 0) 반환. (요구사항 5.5)
- 청킹 파라미터는 기존과 동일(chunk_size=500, overlap=50). (요구사항 5.2)

### 5. Query_Interface (Streamlit UI) — 기존 재활용 + 개편

**페이지 1: 학사 Q&A**
- 사이드바: 학년(1~3 또는 미지정) / 학과 선택 셀렉트박스
- 질문 입력(`st.chat_input`), 대화기록 표시(`st.session_state.messages`)
- 답변 + "📎 답변 출처 보기" 확장 카드 (카테고리 배지 포함)
- 빈 질문은 chat_input 특성상 제출 불가(빈 문자열 미전송)로 처리. (요구사항 1.2)

**페이지 2: 지식베이스 관리**
- 카테고리 선택 후 문서(.md/.txt) 업로드 → 해당 카테고리 폴더 저장 + S3 백업
- "전체 재인덱싱" 버튼
- 카테고리별 등록 문서 목록 표시. (요구사항 5.6)

### 6. AWS 접근 계층 — 기존 재활용

- `boto3.client('s3')`, `boto3.client('bedrock-runtime', region_name='us-east-1')`
- 자격증명 명시 없음 → EC2 IAM Role 자동 사용. (요구사항 6.1)
- 각 AWS 호출은 try/except로 감싸 부분 장애를 격리. (요구사항 6.2, 6.3)

## Data Models

### StudentProfile
```python
@dataclass
class StudentProfile:
    grade: str = "미지정"        # "1", "2", "3", "미지정"
    department: str = "미지정"    # 학과명 or "미지정"

    @property
    def is_complete(self) -> bool:
        return self.grade != "미지정" and self.department != "미지정"
```

### RetrievedChunk
```python
@dataclass
class RetrievedChunk:
    content: str          # 청크 원본 텍스트
    category: str         # Document_Category
    source: str           # 문서 파일명
    score: float          # Relevance_Score (L2 거리, 작을수록 유사)
```

### SourceCitation
```python
@dataclass
class SourceCitation:
    source: str           # 문서명
    category: str         # 카테고리
    snippet: str          # 원본 발췌 (최대 ~200자)
```

### FAISS 메타데이터 스키마
각 벡터 문서의 `metadata`: `{"category": str, "source": str}`

## Error Handling

| 상황 | 처리 | 요구사항 |
|------|------|----------|
| Knowledge_Base 미로드 | 안내 메시지 표시, 답변 생성 차단 | 3.3 |
| 검색 점수 전부 임계값 미만 | "관련 정보 없음" 답변 | 3.5 |
| 참고문서에 근거 없음 | "제공된 지식베이스에는 해당 정보가 없습니다" | 4.3 |
| 출처 생성 불가 | 답변 미표시 + 출처 확인 불가 메시지 | 4.5 |
| Claude 호출 오류 | 오류 메시지 표시 | 4.6 |
| S3 백업 실패 | 경고 표시 후 로컬 저장·인덱싱 계속 | 5.4 |
| IAM 권한 부족(부분) | 해당 기능 오류, 나머지 기능 유지 | 6.2 |
| 자격증명+권한 동시 오류 | 단일 접근 오류 메시지 | 6.3 |

**에러 격리 전략**: 각 컴포넌트 경계에서 예외를 잡아 사용자 메시지로 변환하고, 한 기능의 실패가 전체 앱 크래시로 번지지 않도록 한다.

## Correctness Properties

시스템이 항상 만족해야 하는 불변 속성(invariants)이다. 테스트와 코드 리뷰의 기준으로 사용한다.

### Property 1: 근거 기반 답변
Answer_Generator가 생성하는 모든 사실 진술은 Retriever가 반환한 청크에서 근거를 가진다. 근거가 없으면 "정보 없음"으로 답한다.
**Validates: Requirements 4.1, 4.3**

### Property 2: 답변-출처 일관성
표시되는 모든 답변에는 최소 1개의 Source_Citation이 동반된다. 출처를 만들 수 없으면 답변을 표시하지 않는다.
**Validates: Requirements 4.4, 4.5**

### Property 3: 출처 무결성
각 Source_Citation의 `source`와 `category`는 실제 Knowledge_Base에 존재하는 문서 메타데이터와 일치한다.
**Validates: Requirements 3.4, 4.4**

### Property 4: 프로파일 결정성
동일한 (질문, 명시적 학년, 명시적 학과) 입력에 대해 Profile_Identifier는 항상 동일한 StudentProfile을 반환한다.
**Validates: Requirements 2.1, 2.2, 2.3**

### Property 5: 검색 개수 상한
Retriever가 반환하는 청크 수는 항상 k(기본 4) 이하이다.
**Validates: Requirements 3.2**

### Property 6: 장애 격리
하나의 AWS 호출 실패가 전체 앱 크래시를 유발하지 않으며, 영향받지 않는 기능은 계속 동작한다.
**Validates: Requirements 6.2**

### Property 7: 인덱싱 카운트 정확성
인덱싱 완료 시 표시되는 문서 수/청크 수는 실제 처리된 값과 일치하며, 처리 대상이 없으면 0이다.
**Validates: Requirements 5.5**

## Testing Strategy

### 단위 테스트
- **Profile_Identifier**: 명시적 입력 우선순위, 질문 텍스트 추론("3학년 소프트웨어과..."), 미지정 처리
- **Retriever**: top-k 반환 개수, 임계값 필터링, 메타데이터(category/source) 보존
- **Indexer**: 카테고리별 청킹, 메타데이터 부여, 빈 폴더 시 (0,0) 반환
- **응답 파서**: text 블록만 추출, text 없는 블록 혼재 시 안전 동작

### 통합 테스트 (검증 시나리오)
1. **개인화 답변**: 학년/학과 선택 후 질문 → 프로파일 반영된 답변 + 출처
2. **RAG 정확성**: 각 카테고리별 대표 질문(학사규정/협력사/실무프로젝트/교육과정) → 해당 카테고리 문서에서 검색·인용
3. **환각 방어**: 지식베이스에 없는 질문(예: "오늘 급식 메뉴") → 정중한 거부
4. **미지정 처리**: 학년/학과 미선택 + 추론 불가 질문 → 일반 답변 + 학년/학과 확인 요청
5. **에러 처리**: 인덱스 없는 상태 접속 → 안내 메시지

### 배포 검증
- systemd 서비스 active + Nginx 프록시 HTTP 200
- 외부 접속 및 카테고리별 질의응답 엔드투엔드 확인

## 기존 코드 대비 변경 요약

| 파일 | 변경 내용 |
|------|-----------|
| `app.py` | 주제/문구 교체, 학년·학과 사이드바 추가, 카테고리 인지 검색·출처, 프로파일 반영 프롬프트 |
| `bedrock_faiss_indexer.py` | 카테고리 폴더 구조, category 메타데이터, 점수 기반 검색 지원 |
| `bedrock_faiss_rag_chatbot.py` | 동일 프롬프트/출처 정책으로 CLI 갱신 (선택) |
| `knowledge_base/` (신규) | 4개 카테고리 하위 폴더 + 시드 문서 |
| 응답 파싱 | `content[0]['text']` → text 블록 안전 추출로 통일 |
