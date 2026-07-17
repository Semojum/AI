"""Opus 4.8 비전 추출 폴백 — MinerU 추출이 빈약한 페이지를 모델이 직접 읽는다 (D-05).

기준: 오프라인 실측(2026-07-17)에서 텍스트 무수정 <15% 페이지만 유효(3~4배 개선),
중간 품질 페이지는 득실 반반이라 교체하지 않는다. 런타임엔 정답이 없으므로
추출 자체의 빈약 신호(요소 수·본문 글자수)로 판정한다.

비용이 드는 경로라 **기본 off** — `OPUS_EXTRACT_FALLBACK=1` + ANTHROPIC_API_KEY 있을 때만.
호출·토큰은 req_log에 기록한다.
"""
from __future__ import annotations

import base64
import json
import logging
import os

logger = logging.getLogger(__name__)

MODEL = os.environ.get("OPUS_EXTRACT_MODEL", "claude-opus-4-8")

# 빈약 판정: 요소가 이만큼도 안 나오거나, 텍스트류 총 글자가 이만큼도 안 되면
# MinerU가 페이지를 사실상 못 읽은 것이다(실측: 문제 페이지는 보통 요소 0~3·수십 자).
_MIN_ELEMENTS = int(os.environ.get("OPUS_FALLBACK_MIN_ELEMENTS", "3"))
_MIN_TEXT_CHARS = int(os.environ.get("OPUS_FALLBACK_MIN_CHARS", "120"))

_PROMPT = """이 교과서 페이지의 모든 텍스트를 읽기 순서대로 추출하세요.

JSON 배열만 출력합니다. 각 요소: {"type": "...", "content": "..."}
type: text(문단 단위로, 중간에 자르지 말 것) | list_item(선택지 묶음은 한 요소) |
header_footer | page_number | caption | table(행은 |, 줄은 개행) | formula(LaTeX) |
image(content는 빈 문자열)

규칙: 글자를 지어내지 마세요. 강조 구간은 <!드러냄>…<!/드러냄>. JSON 외 출력 금지."""


def enabled() -> bool:
    return (os.environ.get("OPUS_EXTRACT_FALLBACK", "0") == "1"
            and bool(os.environ.get("ANTHROPIC_API_KEY")))


def is_meager(elements: list[dict]) -> bool:
    """MinerU 추출이 빈약한가 — Opus 폴백 트리거 신호."""
    if len(elements) < _MIN_ELEMENTS:
        return True
    chars = sum(len(e.get("content") or "") for e in elements
                if e.get("type") not in ("image", "cartoon", "chart_graph"))
    return chars < _MIN_TEXT_CHARS


def extract(image_path: str) -> list[dict] | None:
    """페이지 이미지 → 경계 파일 형식 elements. 실패 시 None(호출부가 원 추출 유지)."""
    try:
        import anthropic
        from app.utils.req_log import record_gpt4o
        client = anthropic.Anthropic()
        b64 = base64.b64encode(open(image_path, "rb").read()).decode()
        resp = client.messages.create(
            model=MODEL, max_tokens=8000,
            messages=[{"role": "user", "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": _PROMPT},
            ]}],
        )
        record_gpt4o("opus추출",
                     getattr(resp.usage, "input_tokens", 0) or 0,
                     getattr(resp.usage, "output_tokens", 0) or 0)
        txt = "".join(b.text for b in resp.content if b.type == "text").strip()
        if txt.startswith("```"):
            txt = txt.split("\n", 1)[1].rsplit("```", 1)[0]
        els = json.loads(txt)
        return [{"id": f"opus-{i:03d}", "order": i, "type": e.get("type", "text"),
                 "content": e.get("content") or ""} for i, e in enumerate(els)]
    except Exception as exc:  # noqa: BLE001 — 폴백 실패는 원 추출 유지로 격리
        logger.warning("Opus 추출 폴백 실패(원 추출 유지): %s", exc)
        return None
