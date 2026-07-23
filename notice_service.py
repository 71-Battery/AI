"""Proactive campus notice service.

Ported from the chatbot branch's notice pipeline without its web UI.
Flow: deduplicate -> persist -> summarize -> notify proactively.
"""

import hashlib
import json
import logging
import os
import re
import threading
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3

logger = logging.getLogger(__name__)

NOTICE_DATA_FILE = Path(os.getenv("NOTICE_DATA_FILE", "data/notices.json"))
NOTICE_AI_PROVIDER = os.getenv("NOTICE_AI_PROVIDER", "bedrock").lower()
NOTICE_BEDROCK_MODEL_ID = os.getenv(
    "NOTICE_BEDROCK_MODEL_ID",
    os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-5"),
)
NOTICE_BEDROCK_REGION = os.getenv("NOTICE_BEDROCK_REGION", os.getenv("AWS_REGION", "us-east-1"))
NOTICE_POLL_SOURCE_URL = os.getenv("NOTICE_POLL_SOURCE_URL", "")
NOTICE_POLL_INTERVAL_SECONDS = int(os.getenv("NOTICE_POLL_INTERVAL_SECONDS", "300"))
NOTICE_CHANNELS = [
    channel.strip()
    for channel in os.getenv("NOTICE_CHANNELS", "console").split(",")
    if channel.strip()
]
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_TO = [address.strip() for address in os.getenv("EMAIL_TO", "").split(",") if address.strip()]
SES_REGION = os.getenv("SES_REGION", NOTICE_BEDROCK_REGION)

NOTICE_SUMMARY_PROMPT = """당신은 학교 공지와 일정을 학생이 빠르게 이해하도록 정리하는 공지 브리핑 도우미입니다.
공지 원문에 있는 정보만 사용하고, 원문에 없는 내용을 추가하거나 추측하지 마세요.
다음 형식을 지켜 한국어 존댓말로 간결하게 작성하세요.

핵심요약: 한두 문장
중요정보:
- 대상: 원문에 있으면 작성하고 없으면 '공지에 기재되지 않음'
- 날짜/시간: 원문에 있으면 작성하고 없으면 '공지에 기재되지 않음'
- 장소: 원문에 있으면 작성하고 없으면 '공지에 기재되지 않음'
- 신청/마감: 원문에 있으면 작성하고 없으면 '공지에 기재되지 않음'
해야할일:
- 학생이 해야 할 행동을 원문에 근거해 작성하고 없으면 생략
주의사항:
- 원문에 있으면 작성하고 없으면 생략

날짜, 시간, 장소, 제출기한은 원문과 다르게 바꾸지 마세요."""


class NoticeServiceError(Exception):
    """Base error for notice processing failures."""


class NoticeStore:
    """Small JSON store for demo/small deployments; replace with DB later."""

    def __init__(self, data_file: Path = NOTICE_DATA_FILE):
        self.data_file = data_file
        self._lock = threading.Lock()
        self.notices: list[dict[str, Any]] = []
        self.seen_keys: set[str] = set()
        self.loaded = False

    def load(self) -> None:
        with self._lock:
            if self.loaded:
                return
            try:
                parsed = json.loads(self.data_file.read_text(encoding="utf-8"))
                self.notices = parsed.get("notices", [])
            except (FileNotFoundError, json.JSONDecodeError):
                self.notices = []
            self.seen_keys = {self._key(notice) for notice in self.notices}
            self.loaded = True

    @staticmethod
    def _key(notice: dict[str, Any]) -> str:
        source_id = notice.get("source_id") or notice.get("sourceId")
        if source_id:
            return f"sid:{source_id}"
        raw = f"{notice.get('title', '')}::{notice.get('content', '')}"
        return f"hash:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"

    def is_duplicate(self, notice: dict[str, Any]) -> bool:
        self.load()
        with self._lock:
            return self._key(notice) in self.seen_keys

    def _persist(self) -> None:
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file = self.data_file.with_suffix(".tmp")
        temp_file.write_text(
            json.dumps({"notices": self.notices}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_file.replace(self.data_file)

    @staticmethod
    def _record(notice: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(uuid.uuid4()),
            "title": notice.get("title") or "(제목 없음)",
            "content": notice.get("content") or "",
            "type": notice.get("type") or ("schedule" if notice.get("starts_at") else "notice"),
            "starts_at": notice.get("starts_at") or notice.get("startsAt"),
            "source_id": notice.get("source_id") or notice.get("sourceId"),
            "url": notice.get("url"),
            "target_grade": notice.get("target_grade") or notice.get("targetGrade") or "전체",
            "target_department": notice.get("target_department") or notice.get("targetDepartment") or "전체",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "summary": None,
            "notified": False,
        }

    def add_if_new(self, notice: dict[str, Any]) -> tuple[dict[str, Any] | None, bool]:
        """Atomically check for a duplicate and persist a new record."""
        self.load()
        with self._lock:
            if self._key(notice) in self.seen_keys:
                return None, True
            record = self._record(notice)
            self.notices.append(record)
            self.seen_keys.add(self._key(record))
            self._persist()
            return record, False

    def add(self, notice: dict[str, Any]) -> dict[str, Any]:
        record, duplicate = self.add_if_new(notice)
        if duplicate or record is None:
            raise NoticeServiceError("이미 등록된 공지입니다.")
        return record

    def update(self, notice_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        self.load()
        with self._lock:
            for index, notice in enumerate(self.notices):
                if notice["id"] == notice_id:
                    self.notices[index] = {**notice, **patch}
                    self._persist()
                    return self.notices[index]
        return None

    def list(self) -> list[dict[str, Any]]:
        self.load()
        return sorted(self.notices, key=lambda item: item.get("created_at", ""), reverse=True)


store = NoticeStore()
_bedrock_client = None
_ses_client = None


def _get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        _bedrock_client = boto3.client("bedrock-runtime", region_name=NOTICE_BEDROCK_REGION)
    return _bedrock_client


def _get_ses_client():
    global _ses_client
    if _ses_client is None:
        _ses_client = boto3.client("ses", region_name=SES_REGION)
    return _ses_client


def _extract_text(payload: dict[str, Any]) -> str:
    return "\n".join(
        block.get("text", "")
        for block in payload.get("content", [])
        if isinstance(block, dict) and block.get("text")
    ).strip()


def _summarize_with_bedrock(notice: dict[str, Any]) -> str:
    user_text = "\n".join(
        part
        for part in [
            f"제목: {notice['title']}",
            f"대상 학년: {notice['target_grade']}",
            f"대상 학과: {notice['target_department']}",
            f"일정 시작: {notice['starts_at']}" if notice.get("starts_at") else None,
            f"공지 원문:\n{notice['content']}",
        ]
        if part
    )
    body = json.dumps(
        {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 600,
            "system": NOTICE_SUMMARY_PROMPT,
            "messages": [{"role": "user", "content": [{"type": "text", "text": user_text}]}],
        }
    )
    response = _get_bedrock_client().invoke_model(
        modelId=NOTICE_BEDROCK_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=body,
    )
    summary = _extract_text(json.loads(response["body"].read()))
    if not summary:
        raise NoticeServiceError("Bedrock 요약 응답이 비어 있습니다.")
    return summary


def _fallback_summary(notice: dict[str, Any]) -> str:
    clean = re.sub(r"\s+", " ", notice.get("content", "")).strip()
    sentences = re.split(r"(?<=[.!?。])\s+", clean)
    head = " ".join(sentence for sentence in sentences[:2] if sentence)
    lines = [f"핵심요약: {head or notice['title']}"]
    info = [f"- 대상: {notice['target_grade']} / {notice['target_department']}"]
    if notice.get("starts_at"):
        info.append(f"- 일정 시작: {notice['starts_at']}")
    date_matches = re.findall(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}|\d{1,2}월\s*\d{1,2}일|\d{1,2}:\d{2}", clean)
    if date_matches:
        info.append(f"- 날짜/시간 언급: {', '.join(dict.fromkeys(date_matches))}")
    if notice.get("url"):
        info.append(f"- 원문 링크: {notice['url']}")
    lines.extend(["중요정보:", *info])
    return "\n".join(lines)


def summarize_notice(notice: dict[str, Any]) -> tuple[str, str]:
    if NOTICE_AI_PROVIDER == "bedrock":
        try:
            return _summarize_with_bedrock(notice), "bedrock"
        except Exception as exc:
            logger.warning("Bedrock 공지 요약 실패, 규칙 기반 폴백 사용: %s", exc)
    return _fallback_summary(notice), "fallback"


def _notification_message(notice: dict[str, Any]) -> tuple[str, str]:
    icon = "🗓️" if notice.get("type") == "schedule" else "📢"
    title = f"{icon} 새 {'일정' if notice.get('type') == 'schedule' else '공지'}: {notice['title']}"
    body = "\n".join(
        part for part in [
            title,
            f"대상: {notice['target_grade']} / {notice['target_department']}",
            "",
            notice.get("summary") or notice.get("content", ""),
            f"\n원문: {notice['url']}" if notice.get("url") else None,
        ] if part is not None
    )
    return title, body


def _send_console(notice: dict[str, Any]) -> None:
    _, body = _notification_message(notice)
    logger.info("\n──────── 🔔 능동형 공지 알림 ────────\n%s\n────────────────────────────────", body)


def _send_slack(notice: dict[str, Any]) -> None:
    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL 미설정 — Slack 알림을 건너뜁니다.")
        return
    _, body = _notification_message(notice)
    request = urllib.request.Request(
        SLACK_WEBHOOK_URL,
        data=json.dumps({"text": body}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        if response.status >= 300:
            raise NoticeServiceError(f"Slack 전송 실패: {response.status}")


def _send_email(notice: dict[str, Any]) -> None:
    if not EMAIL_FROM or not EMAIL_TO:
        logger.warning("EMAIL_FROM/EMAIL_TO 미설정 — 이메일 알림을 건너뜁니다.")
        return
    title, body = _notification_message(notice)
    _get_ses_client().send_email(
        Source=EMAIL_FROM,
        Destination={"ToAddresses": EMAIL_TO},
        Message={
            "Subject": {"Data": title, "Charset": "UTF-8"},
            "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
        },
    )


def notify_notice(notice: dict[str, Any]) -> list[dict[str, Any]]:
    handlers = {"console": _send_console, "slack": _send_slack, "email": _send_email}
    results = []
    for channel in NOTICE_CHANNELS:
        handler = handlers.get(channel)
        if handler is None:
            results.append({"channel": channel, "ok": False, "error": "지원하지 않는 알림 채널"})
            continue
        try:
            handler(notice)
            results.append({"channel": channel, "ok": True})
        except Exception as exc:
            logger.exception("공지 알림 실패(%s)", channel)
            results.append({"channel": channel, "ok": False, "error": str(exc)})
    return results


def ingest_notice(input_notice: dict[str, Any]) -> dict[str, Any]:
    """Persist, summarize, and proactively notify a new notice."""
    required = str(input_notice.get("title") or input_notice.get("content") or "").strip()
    if not required:
        raise ValueError("title 또는 content가 필요합니다.")
    notice, duplicate = store.add_if_new(input_notice)
    if duplicate or notice is None:
        return {"skipped": True, "reason": "duplicate"}

    summary, summary_provider = summarize_notice(notice)
    notice = store.update(notice["id"], {"summary": summary, "summary_provider": summary_provider}) or notice
    notify_results = notify_notice(notice)
    notice = store.update(notice["id"], {"notified": any(item["ok"] for item in notify_results)}) or notice
    return {"skipped": False, "notice": notice, "notify_results": notify_results}


def normalize_polled_notice(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": item.get("source_id") or item.get("sourceId") or item.get("id"),
        "title": item.get("title") or item.get("subject") or "(제목 없음)",
        "content": item.get("content") or item.get("body") or item.get("description") or "",
        "type": item.get("type") or ("schedule" if item.get("starts_at") or item.get("startsAt") else "notice"),
        "starts_at": item.get("starts_at") or item.get("startsAt") or item.get("date"),
        "url": item.get("url") or item.get("link"),
        "target_grade": item.get("target_grade") or item.get("targetGrade") or "전체",
        "target_department": item.get("target_department") or item.get("targetDepartment") or "전체",
    }


def poll_notices() -> dict[str, Any]:
    if not NOTICE_POLL_SOURCE_URL:
        return {"enabled": False, "new_count": 0, "message": "NOTICE_POLL_SOURCE_URL 미설정"}
    with urllib.request.urlopen(NOTICE_POLL_SOURCE_URL, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    items = data if isinstance(data, list) else data.get("items", [])
    processed = [ingest_notice(normalize_polled_notice(item)) for item in items]
    return {
        "enabled": True,
        "new_count": sum(1 for result in processed if not result["skipped"]),
        "processed_count": len(processed),
    }
