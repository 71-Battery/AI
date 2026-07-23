# 교내 공지·학사정보 통합 AI 도우미 - AI API 이미지
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AWS_REGION=us-east-1 \
    FAISS_INDEX_PATH=/app/faiss_index

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY ai_service.py api_server.py bedrock_faiss_indexer.py bedrock_faiss_rag_chatbot.py bedrock_simple_test.py ./
COPY knowledge_base ./knowledge_base

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8000"]
