# 교내 공지·학사정보 통합 AI 도우미 - Streamlit RAG 챗봇 컨테이너 이미지
FROM python:3.12-slim

# 시스템 로케일/빌드 도구 (faiss, langchain 의존성 대비)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AWS_DEFAULT_REGION=us-east-1

WORKDIR /app

# 1. 의존성 먼저 설치 (레이어 캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# 2. 애플리케이션 소스 및 지식베이스 복사
COPY app.py bedrock_faiss_indexer.py bedrock_faiss_rag_chatbot.py bedrock_simple_test.py ./
COPY knowledge_base ./knowledge_base
COPY .streamlit ./.streamlit

# 3. Streamlit 포트
EXPOSE 8501

# 4. 헬스체크
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health')" || exit 1

# 5. 실행 (컨테이너 내부는 0.0.0.0 바인딩, 외부 노출은 호스트 포트 매핑/Nginx로 통제)
CMD ["streamlit", "run", "app.py", \
     "--server.address", "0.0.0.0", \
     "--server.port", "8501", \
     "--server.headless", "true", \
     "--browser.gatherUsageStats", "false"]
