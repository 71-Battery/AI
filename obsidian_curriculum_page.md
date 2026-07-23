# 🎓 교내 공지·학사정보 통합 AI 도우미 실습 가이드

## 프로젝트 목표
학생 질문을 받아 학년·학과를 파악하고, 학사규정·기업 협력사·실무프로젝트·교육과정에서 관련 정보를 찾아 학교 특성에 맞춰 설명합니다.

## 핵심 파일
- `app.py`: Streamlit 질의응답 및 카테고리별 문서 관리
- `bedrock_faiss_indexer.py`: 지식베이스 인덱싱
- `bedrock_faiss_rag_chatbot.py`: CLI 질의 테스트
- `knowledge_base/`: 4개 카테고리 원본 문서
- `faiss_index/`: 생성된 FAISS 벡터 DB

## 설치
```bash
sudo apt-get update
sudo apt-get install -y python3-pip python3.12-venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
aws sts get-caller-identity
```

## 인덱스 생성
```bash
python bedrock_faiss_indexer.py
```
문서가 500자 청크로 분할되고 `category`, `source` 메타데이터와 함께 Titan Embed Text v2로 벡터화됩니다.

## CLI 테스트
```bash
python bedrock_faiss_rag_chatbot.py
```
질문 예시:
- `3학년 소프트웨어개발과 현장실습은 어떻게 신청해?`
- `스마트IoT과 2학년 프로젝트는 뭐야?`
- `오늘 날씨 알려줘` → 지식베이스에 없다고 답해야 함

## 웹 실행
```bash
python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```
사이드바에서 학년과 학과를 선택하면 답변 프롬프트에 학생 프로파일이 반영됩니다.

## 최종 프롬프트
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

## 작동 시나리오 및 기대 효과
1. 관리자가 카테고리별 학교 문서를 등록합니다.
2. 인덱서가 문서를 청킹하고 Titan 임베딩으로 FAISS에 저장합니다.
3. 학생이 학년·학과를 선택하거나 질문에 직접 입력합니다.
4. 질문과 관련된 상위 문서 청크를 검색합니다.
5. Claude가 학생 프로파일과 검색 결과를 바탕으로 맞춤 답변을 생성합니다.
6. 답변과 문서명·카테고리·원문 일부를 함께 표시합니다.
7. 근거가 없으면 추측하지 않고 정보 없음으로 안내합니다.

기대 효과는 공지·규정 탐색 시간 단축, 반복 문의 감소, 학년·학과별 정보 접근성 향상, 공식 문서 기반 답변을 통한 신뢰성 확보입니다.
