# 🎓 교내 공지·학사정보 통합 AI 도우미

학교의 핵심 정보(**학사규정 · 기업 협력사 · 실무프로젝트 목록 · 교육과정**)를 하나의 지식베이스로 통합하고, 학생의 자연어 질문에 RAG(Retrieval-Augmented Generation) 방식으로 답변하는 AI 도우미입니다.

## 프로젝트 목적
학생이 학교 규정과 교육과정, 현장실습·협력사·프로젝트 정보를 여러 문서에서 직접 찾지 않아도 되도록 통합 검색·맞춤 설명을 제공합니다.

## 3가지 중심 기능
1. **학생 학년/학과 파악** — 사이드바에서 직접 선택하거나 질문 텍스트에서 학년·학과를 식별합니다.
2. **관련 정보 찾기(RAG)** — 질문을 임베딩하여 FAISS 지식베이스에서 관련 문서를 의미 기반으로 검색합니다.
3. **학교 특성 맞춤 설명** — 검색된 정보를 학생의 학년·학과와 학교 교육 특성에 맞춰 설명합니다.

모든 답변에는 근거가 된 **문서명·카테고리·원본 내용 일부**가 함께 표시됩니다. 지식베이스에 없는 내용은 추측하지 않습니다.

## 기술 스택
- Python 3.12, Streamlit
- Amazon Bedrock Claude: 답변 생성
- Amazon Titan Embed Text v2: 문서·질문 임베딩
- FAISS: 로컬 벡터 검색
- LangChain: 문서 청킹 및 Bedrock/FAISS 연동
- AWS S3: 문서 백업 저장소
- EC2 IAM Role: AWS 키를 코드에 저장하지 않는 인증

## 프로젝트 구조

```text
.
├── app.py                         # Streamlit 웹 앱
├── bedrock_faiss_indexer.py      # 카테고리별 지식베이스 인덱서
├── bedrock_faiss_rag_chatbot.py  # CLI RAG 테스트 앱
├── bedrock_simple_test.py        # Bedrock 연결 테스트
├── knowledge_base/
│   ├── academic_rules/            # 학사규정
│   ├── partner_companies/         # 기업 협력사
│   ├── field_projects/            # 실무프로젝트 목록
│   └── curriculum/                # 교육과정
├── faiss_index/                   # 생성된 FAISS 인덱스
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

## 실행 방법

### 의존성 설치 및 인덱스 생성

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python bedrock_faiss_indexer.py
```

### CLI 테스트

```bash
python bedrock_faiss_rag_chatbot.py
```

대표 질문:
- `3학년 소프트웨어개발과 현장실습은 어떻게 신청해?`
- `소프트웨어개발과 2학년 교육과정 알려줘`
- `오늘 급식 메뉴가 뭐야?` → 지식베이스에 없다고 안내

### 웹 앱 실행

```bash
python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

## 최종 시스템 프롬프트

아래 프롬프트가 `app.py`의 `build_prompt()`에서 실제로 사용됩니다. `{profile.grade}`, `{profile.department}`, `{context_text}`, `{query}`는 실행 시 실제 값으로 치환됩니다.

```text
당신은 우리 학교 학생을 돕는 교내 학사정보 안내 도우미입니다.
아래 [참고문서]만을 근거로 학생의 질문에 정확하고 친절하게 답하세요.
참고문서에 근거가 없는 내용은 지어내지 말고 "제공된 지식베이스에는 해당 정보가 없습니다"라고 답하세요.
가능하면 어떤 문서를 근거로 삼았는지 자연스럽게 언급하세요.

[학생 정보]
- 학년: {profile.grade}
- 학과: {profile.department}
학년/학과에 해당하는 규정·교육과정·실무프로젝트·협력사 정보가 있으면 그에 맞춰 설명하세요.
학년 또는 학과가 '미지정'이면 일반 정보로 답하되, 더 정확한 안내를 위해 학년/학과 확인을 정중히 요청하세요.

[참고문서]
{context_text}

질문: {query}
답변:
```

### 프롬프트 설계 효과
- 학생의 학년과 학과를 답변 맥락에 포함하여 개인화합니다.
- 검색된 문서만 근거로 사용하도록 하여 환각을 줄입니다.
- 출처 문서명을 답변에 언급하도록 유도합니다.
- 실제 출처 카드는 코드가 검색 청크에서 별도로 생성하여 답변과 연결합니다.

## 최종 작동 시나리오 및 기대 효과

1. 관리자가 학사규정, 기업 협력사, 실무프로젝트, 교육과정 문서를 카테고리별로 등록합니다.
2. 인덱서가 문서를 500자 단위, 50자 중복으로 분할하고 `category`·`source` 메타데이터를 부여합니다.
3. Titan Embed Text v2가 문서 청크를 벡터화하고 FAISS에 저장합니다.
4. 학생이 사이드바에서 학년·학과를 선택하거나 질문에 직접 입력합니다.
5. 질문이 FAISS에서 상위 4개 문서 청크로 검색됩니다.
6. Claude가 학생 프로파일과 검색 결과를 바탕으로 학교 특성에 맞는 답변을 스트리밍합니다.
7. 화면에는 답변과 함께 근거 문서명, 카테고리, 원문 일부가 표시됩니다.
8. 검색 근거가 없으면 답변을 추측하지 않고 지식베이스에 정보가 없다고 안내합니다.

이 흐름으로 학생의 정보 탐색 시간을 줄이고, 학년·학과별로 필요한 정보를 쉽게 이해하도록 하며, 학교에 흩어진 공지와 학사정보의 활용도를 높일 수 있습니다.

## 최종 비즈니스 기대 가치

교내 공지·학사정보 통합 AI 도우미는 학교 정보를 단순 저장하는 것을 넘어 학생별 상황에 맞는 실행 가능한 설명으로 변환합니다. 학생은 규정·교육과정·협력사·프로젝트 정보를 빠르게 확인하고, 교사는 반복적인 문의 응대 부담을 줄이며, 학교는 축적된 공식 문서를 지속적으로 활용할 수 있습니다. 결과적으로 학생 정보 접근성, 학교 행정 효율, 교육과정 참여도와 진로 탐색의 질을 함께 높이는 지식 서비스가 됩니다.

## EC2 운영 배포

- systemd 서비스: `gsm-streamlit`
- Streamlit 내부 포트: `127.0.0.1:8501`
- Nginx 외부 포트: `80`
- 서비스 주소: `http://<EC2-PUBLIC-IP>`
- 로그: `sudo journalctl -u gsm-streamlit -f`
- 재시작: `sudo systemctl restart gsm-streamlit`
- AWS 인증: EC2 IAM Role 사용
