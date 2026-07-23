"""Backend integration API for Campus AI.

This API intentionally contains no Streamlit/UI code. A separate backend or
frontend can call POST /v1/chat with the authenticated student's profile.
"""

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ai_service import (
    BedrockUnavailableError,
    KnowledgeBaseUnavailableError,
    answer_question,
    health_status,
)
from notice_service import (
    NOTICE_POLL_INTERVAL_SECONDS,
    NOTICE_POLL_SOURCE_URL,
    ingest_notice,
    poll_notices,
    store as notice_store,
)

logger = logging.getLogger(__name__)

API_PREFIX = os.getenv("API_PREFIX", "/v1")
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]

async def _notice_poll_loop() -> None:
    while True:
        await asyncio.sleep(NOTICE_POLL_INTERVAL_SECONDS)
        try:
            result = await asyncio.to_thread(poll_notices)
            logger.info("공지 polling 완료: %s", result)
        except Exception:
            logger.exception("공지 polling 실패")


@asynccontextmanager
async def lifespan(app: FastAPI):
    poll_task = None
    if NOTICE_POLL_SOURCE_URL and NOTICE_POLL_INTERVAL_SECONDS > 0:
        poll_task = asyncio.create_task(_notice_poll_loop())
        logger.info("공지 polling 활성화: interval=%s초", NOTICE_POLL_INTERVAL_SECONDS)
    try:
        yield
    finally:
        if poll_task is not None:
            poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await poll_task


app = FastAPI(
    title="Campus AI Backend Integration API",
    version="1.1.0",
    description="교내 공지·학사정보 통합 AI 도우미의 학사정보 질의 및 공지·알림 API",
    lifespan=lifespan,
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


class NoticeRequest(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    content: str | None = Field(default=None, max_length=20000)
    type: str | None = Field(default=None, max_length=30)
    starts_at: str | None = Field(default=None, max_length=100)
    url: str | None = Field(default=None, max_length=2000)
    source_id: str | None = Field(default=None, max_length=200)
    target_grade: str | None = Field(default=None, max_length=20)
    target_department: str | None = Field(default=None, max_length=100)


class NoticeIngestResponse(BaseModel):
    skipped: bool
    reason: str | None = None
    notice: dict[str, Any] | None = None
    notify_results: list[dict[str, Any]] = Field(default_factory=list)


class NoticeListResponse(BaseModel):
    notices: list[dict[str, Any]]
    count: int


class NoticePollResponse(BaseModel):
    enabled: bool
    new_count: int
    processed_count: int = 0
    message: str | None = None


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": "INVALID_REQUEST",
                "message": "요청 형식이 올바르지 않습니다.",
                "request_id": str(uuid4()),
            }
        },
    )


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


@app.post(f"{API_PREFIX}/notices", response_model=NoticeIngestResponse, responses={400: {"model": ErrorResponse}})
async def create_notice(request: NoticeRequest) -> dict[str, Any]:
    payload = request.model_dump(exclude_none=True)
    if not str(payload.get("title", "")).strip() and not str(payload.get("content", "")).strip():
        raise ValueError("title 또는 content가 필요합니다.")
    return await asyncio.to_thread(ingest_notice, payload)


@app.get(f"{API_PREFIX}/notices", response_model=NoticeListResponse)
async def list_notices(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    notices = notice_store.list()[:limit]
    return {"notices": notices, "count": len(notices)}


@app.post(f"{API_PREFIX}/notices/poll", response_model=NoticePollResponse, responses={400: {"model": ErrorResponse}, 502: {"model": ErrorResponse}})
async def poll_notice_source() -> dict[str, Any]:
    try:
        return await asyncio.to_thread(poll_notices)
    except Exception as exc:
        logger.exception("수동 공지 polling 실패")
        raise ValueError("공지 원본을 조회하지 못했습니다.") from exc
