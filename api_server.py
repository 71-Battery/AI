"""Backend integration API for Campus AI.

This API intentionally contains no Streamlit/UI code. A separate backend or
frontend can call POST /v1/chat with the authenticated student's profile.
"""

import os
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ai_service import (
    BedrockUnavailableError,
    KnowledgeBaseUnavailableError,
    answer_question,
    health_status,
)

API_PREFIX = os.getenv("API_PREFIX", "/v1")
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]

app = FastAPI(
    title="Campus AI Backend Integration API",
    version="1.0.0",
    description="교내 공지·학사정보 통합 AI 도우미의 백엔드 연동 API",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    # 회원 DB에서 조회한 값을 백엔드가 전달한다. 둘 다 없으면 질문에서 보조 추론한다.
    grade: str | None = Field(default=None, max_length=20)
    department: str | None = Field(default=None, max_length=50)
    top_k: int = Field(default=4, ge=1, le=10)
    score_threshold: float = Field(default=1.5, gt=0)


class ProfileResponse(BaseModel):
    grade: str
    department: str


class SourceResponse(BaseModel):
    category: str
    document: str
    snippet: str
    score: float


class ChatResponse(BaseModel):
    answer: str
    profile: ProfileResponse
    sources: list[SourceResponse]
    has_context: bool
    retrieval: dict[str, Any]
    request_id: str


class ErrorResponse(BaseModel):
    error: dict[str, str]


@app.exception_handler(ValueError)
async def handle_value_error(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=400,
        content={"error": {"code": "INVALID_REQUEST", "message": str(exc), "request_id": str(uuid4())}},
    )


@app.exception_handler(KnowledgeBaseUnavailableError)
async def handle_knowledge_base_error(request: Request, exc: KnowledgeBaseUnavailableError):
    return JSONResponse(
        status_code=503,
        content={"error": {"code": "KNOWLEDGE_BASE_UNAVAILABLE", "message": str(exc), "request_id": str(uuid4())}},
    )


@app.exception_handler(BedrockUnavailableError)
async def handle_bedrock_error(request: Request, exc: BedrockUnavailableError):
    return JSONResponse(
        status_code=502,
        content={"error": {"code": "AI_PROVIDER_UNAVAILABLE", "message": str(exc), "request_id": str(uuid4())}},
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return health_status()


@app.post(f"{API_PREFIX}/chat", response_model=ChatResponse, responses={400: {"model": ErrorResponse}, 502: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
async def chat(request: ChatRequest) -> dict[str, Any]:
    result = answer_question(
        query=request.query,
        grade=request.grade,
        department=request.department,
        top_k=request.top_k,
        score_threshold=request.score_threshold,
    )
    payload = result.to_dict()
    payload["request_id"] = str(uuid4())
    return payload
