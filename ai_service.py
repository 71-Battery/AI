"""Campus AI RAG engine.

This module contains no web/UI framework code. Backend applications call
answer_question() with a student's question and profile.
"""

import json
import os
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any

import boto3
from langchain_aws import BedrockEmbeddings
from langchain_community.vectorstores import FAISS

KB_INDEX_PATH = os.getenv("FAISS_INDEX_PATH", "faiss_index")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-5")
EMBEDDING_MODEL_ID = os.getenv("EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0")
DEFAULT_TOP_K = 4
DEFAULT_SCORE_THRESHOLD = 1.5

ALLOWED_GRADES = {"미지정", "1학년", "2학년", "3학년"}
ALLOWED_DEPARTMENTS = {"미지정", "소프트웨어개발과", "스마트IoT과"}
DEPARTMENT_ALIASES = {
    "소프트웨어개발과": ["소프트웨어개발과", "소프트웨어과", "소프트웨어", "sw과", "sw"],
    "스마트IoT과": ["스마트iot과", "스마트 iot", "iot과", "iot", "사물인터넷", "스마트아이오티"],
}
NO_CONTEXT_ANSWER = (
    "제공된 지식베이스에는 해당 정보가 없습니다. "
    "학사규정·기업 협력사·실무프로젝트·교육과정에 관한 질문을 해주세요."
)


class AIServiceError(Exception):
    """Base error for predictable AI service failures."""


class KnowledgeBaseUnavailableError(AIServiceError):
    """Raised when the FAISS index cannot be loaded."""


class BedrockUnavailableError(AIServiceError):
    """Raised when Bedrock cannot generate an answer."""


@dataclass(frozen=True)
class StudentProfile:
    grade: str = "미지정"
    department: str = "미지정"


@dataclass(frozen=True)
class SourceCitation:
    category: str
    document: str
    snippet: str
    score: float


@dataclass(frozen=True)
class RetrievedChunk:
    content: str
    category: str
    source: str
    score: float


@dataclass(frozen=True)
class ChatResult:
    answer: str
    profile: StudentProfile
    sources: list[SourceCitation]
    has_context: bool
    retrieval: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "profile": asdict(self.profile),
            "sources": [asdict(source) for source in self.sources],
            "has_context": self.has_context,
            "retrieval": self.retrieval,
        }


def _normalize_grade(value: str | None) -> str:
    value = (value or "").strip()
    return value if value in ALLOWED_GRADES else "미지정"


def _normalize_department(value: str | None) -> str:
    value = (value or "").strip()
    return value if value in ALLOWED_DEPARTMENTS else "미지정"


def identify_profile(
    query: str,
    grade: str | None = None,
    department: str | None = None,
) -> StudentProfile:
    """Use trusted backend profile values first, then infer missing values."""
    resolved_grade = _normalize_grade(grade)
    resolved_department = _normalize_department(department)
    normalized_query = query.lower()

    if resolved_grade == "미지정":
        match = re.search(r"([1-3])\s*학년", query)
        if match:
            resolved_grade = f"{match.group(1)}학년"

    if resolved_department == "미지정":
        for name, aliases in DEPARTMENT_ALIASES.items():
            if any(alias in normalized_query for alias in aliases):
                resolved_department = name
                break

    return StudentProfile(resolved_grade, resolved_department)


@lru_cache(maxsize=1)
def _get_clients():
    bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    return bedrock, BedrockEmbeddings(client=bedrock, model_id=EMBEDDING_MODEL_ID)


@lru_cache(maxsize=1)
def load_vector_db():
    try:
        _, embeddings = _get_clients()
        return FAISS.load_local(
            KB_INDEX_PATH,
            embeddings,
            allow_dangerous_deserialization=True,
        )
    except Exception as exc:
        raise KnowledgeBaseUnavailableError(
            "지식베이스를 불러올 수 없습니다. 관리자에게 인덱스 상태를 확인해 주세요."
        ) from exc


def retrieve(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
) -> tuple[list[RetrievedChunk], bool]:
    """Return top-k chunks and whether at least one passes the distance threshold."""
    if not 1 <= top_k <= 10:
        raise ValueError("top_k must be between 1 and 10")
    if score_threshold <= 0:
        raise ValueError("score_threshold must be greater than 0")

    results = load_vector_db().similarity_search_with_score(query, k=top_k)
    chunks = [
        RetrievedChunk(
            content=document.page_content,
            category=document.metadata.get("category", "미분류"),
            source=document.metadata.get("source", "알 수 없는 문서"),
            score=float(score),
        )
        for document, score in results
    ]
    relevant = [chunk for chunk in chunks if chunk.score <= score_threshold]
    return relevant, bool(relevant)


def build_prompt(profile: StudentProfile, chunks: list[RetrievedChunk], query: str) -> str:
    context = "\n---\n".join(
        f"[카테고리: {chunk.category} | 출처: {chunk.source}]\n{chunk.content}"
        for chunk in chunks
    )
    return f"""
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
{context}

질문: {query}
답변:
"""


def _extract_text(response_body: dict[str, Any]) -> str:
    parts = [
        block.get("text", "")
        for block in response_body.get("content", [])
        if isinstance(block, dict)
    ]
    return "\n".join(part for part in parts if part).strip()


def _generate_answer(prompt: str) -> str:
    bedrock, _ = _get_clients()
    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 800,
            "messages": [{"role": "user", "content": prompt}],
        }
    )
    try:
        response = bedrock.invoke_model(modelId=BEDROCK_MODEL_ID, body=body)
        answer = _extract_text(json.loads(response["body"].read()))
        if not answer:
            raise BedrockUnavailableError("Bedrock가 빈 답변을 반환했습니다.")
        return answer
    except BedrockUnavailableError:
        raise
    except Exception as exc:
        raise BedrockUnavailableError(
            "AI 답변 생성에 실패했습니다. 잠시 후 다시 시도해 주세요."
        ) from exc


def answer_question(
    query: str,
    grade: str | None = None,
    department: str | None = None,
    top_k: int = DEFAULT_TOP_K,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
) -> ChatResult:
    """Run profile identification, retrieval, generation, and citation creation."""
    query = query.strip()
    if not query:
        raise ValueError("query must not be empty")

    profile = identify_profile(query, grade, department)
    chunks, has_context = retrieve(query, top_k, score_threshold)
    sources = [
        SourceCitation(
            category=chunk.category,
            document=chunk.source,
            snippet=chunk.content.strip().replace("\n", " ")[:200],
            score=round(chunk.score, 6),
        )
        for chunk in chunks
    ]

    if not has_context:
        return ChatResult(
            answer=NO_CONTEXT_ANSWER,
            profile=profile,
            sources=[],
            has_context=False,
            retrieval={"top_k": top_k, "score_threshold": score_threshold, "matched": False},
        )

    answer = _generate_answer(build_prompt(profile, chunks, query))
    return ChatResult(
        answer=answer,
        profile=profile,
        sources=sources,
        has_context=True,
        retrieval={"top_k": top_k, "score_threshold": score_threshold, "matched": True},
    )


def health_status() -> dict[str, str]:
    """Return dependency status without exposing AWS exception details."""
    try:
        load_vector_db()
        vector_db = "loaded"
    except KnowledgeBaseUnavailableError:
        vector_db = "unavailable"
    return {"status": "ok" if vector_db == "loaded" else "degraded", "vector_db": vector_db}
