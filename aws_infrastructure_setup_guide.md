# 🎓 교내 공지·학사정보 통합 AI 도우미 운영 가이드

## 1. 프로젝트 개요
학교의 학사규정, 기업 협력사, 실무프로젝트 목록, 교육과정을 통합한 RAG 챗봇입니다.
학생의 학년·학과를 반영해 관련 정보를 찾아 학교 특성에 맞게 설명합니다.

## 2. 실행 구조
- `app.py`: Streamlit 웹 UI, 학년·학과 선택, 질의응답, 출처 표시, 문서 관리
- `bedrock_faiss_indexer.py`: 4개 카테고리 문서 청킹 및 FAISS 인덱스 생성
- `knowledge_base/`: `academic_rules`, `partner_companies`, `field_projects`, `curriculum`
- `faiss_index/`: Titan 임베딩 결과를 저장하는 로컬 벡터 인덱스
- Amazon Bedrock Claude: 답변 생성
- Amazon Titan Embed Text v2: 문서와 질문 임베딩
- EC2 IAM Role: S3·Bedrock 인증

## 3. 지식베이스 갱신
```bash
cd ~/gsm-hackathon
source venv/bin/activate
python bedrock_faiss_indexer.py
ls -lh faiss_index/
```
문서는 카테고리 폴더에 `.md` 또는 `.txt`로 저장합니다. 인덱서가 각 청크에 `category`와 `source`를 부여합니다.

## 4. 웹 앱 실행
```bash
python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```
운영 환경에서는 systemd와 Nginx를 사용합니다.

## 5. EC2 운영 배포
```bash
sudo systemctl enable gsm-streamlit
sudo systemctl start gsm-streamlit
sudo systemctl status gsm-streamlit
sudo systemctl restart gsm-streamlit
sudo journalctl -u gsm-streamlit -f
```
Nginx는 외부 `80`번 포트를 내부 `127.0.0.1:8501`로 전달합니다.

## 6. 네트워크 및 보안 그룹
- `22/tcp`: SSH, 가능하면 관리자 IP만 허용
- `80/tcp`: HTTP 웹 접속
- `443/tcp`: HTTPS 사용 시 허용
- `8501/tcp`: Nginx를 사용하므로 외부 공개하지 않음

## 7. AWS 권한
EC2 인스턴스에 S3 읽기/쓰기와 Bedrock 임베딩·모델 호출 권한이 있는 IAM Role을 연결합니다.
액세스 키, 비밀번호, JWT 비밀값은 코드에 저장하지 않습니다.

## 8. 대표 검증 질문
- `3학년 소프트웨어개발과 현장실습은 어떻게 신청해?`
- `소프트웨어개발과 2학년 교육과정 알려줘`
- `오늘 급식 메뉴가 뭐야?` → 지식베이스에 없다고 안내
