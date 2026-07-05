"""PART 4-2 — 텍스트 점역 최적화 (HyperCLOVA X SEED Think 14B INT4, GPU 1).

ZERO     → LLM 호출 없음 (텍스트 그대로 반환)
STANDARD → LLM 호출 없음 (OCR 품질 충분 — 교정 불필요)
QUALITY  → HyperCLOVA X, 90초 제한 (저신뢰 스캔 OCR 오류 교정만)
FALLBACK → GPT-4o API, 45초 제한 (3회 연속 실패 후)

공통 추론·폴백·재시도는 base_opt — 여기서는 텍스트에 최적화된 프롬프트·후처리만 정의한다.
추출 텍스트는 rule-based로 그대로 옮기는 것이 원칙이므로, LLM은 저신뢰 스캔의 OCR 오류
교정에만 개입한다(내용 재작성·교정 금지).
"""

from __future__ import annotations

import logging
import re
import time

from app.ai.braille.regulations import make_rule
from app.ai.llm.base_opt import (
    BaseOpt,
    fallback_optimize,
    generate_with_retry,
    hcxt_optimize,
)
from app.core.config import config
from app.core.model_manager import model_manager  # noqa: F401 (단위 테스트가 이 네임스페이스를 patch)
from app.schemas.content import ExtractedContent, LLMOutput, RuleApplication

logger = logging.getLogger(__name__)

# 요소당 HCXT 상한은 config에서(단일 GPU 직렬 — 작게, 페이지 예산 보호). 구 90s/30s는 과도.

# ── 점자 레이아웃 태깅 (LLM이 점역 직전 텍스트에 인라인 태그 삽입) ───────────────
# 점역자주(BBPG-1.2.6)·글상자 테두리(BBPG-1.2.5)·빈칸을 LLM이 삽입하고 translator가
# 1:1 점자로 변환한다(plan §3-5). 하이브리드: HCXT 우선 → 검증 → GPT-4o 폴백 → 원문.
# 효율·환각 방지: 태그 후보 신호(□·____·<보기> 등)가 있는 요소만 LLM 호출, 평문은 그대로.
_TAG_CANDIDATE_RE = re.compile(
    r"[□☐▢☑✓]|_{3,}|[<〈【\[]\s*(?:보기|자료|예시)"
)

_KNOWN_TAGS = {"테두리_위", "테두리_아래", "점역자주", "빈칸_네모", "빈칸_표"}
_TAG_TOKEN_RE = re.compile(r"<!(/?)([^>]+)>")
_FENCE_RE = re.compile(r"```[a-zA-Z]*\n?|```")

_TAG_PROMPT = """다음 '대상 텍스트'에 한국어 점자 레이아웃 태그만 삽입해 변환 결과만 출력하라.
글자·내용·띄어쓰기는 절대 바꾸지 말고 태그만 추가한다. 설명·추론 없이 변환된 텍스트만 한 번 출력한다.

태그 규칙:
- 네모 빈칸 □ 또는 ☐ → <!빈칸_네모> (개수만큼 각각).
- 채워 넣는 빈칸(____ 또는 빈 괄호) → <!빈칸_표>.
- 글상자: 대상 텍스트 '전체'가 자료/보기 표지 하나(예: [자료1], <보기>, [자료2])로만 이루어졌을 때만 <!테두리_위>표지<!/테두리_위>로 감싼다.
- 점역자 주(독자에게 덧붙인 설명) → <!점역자주>설명<!/점역자주>.

[중요] 표지 뒤에 조사·서술·다른 글자가 한 글자라도 붙어 있으면 그것은 '참조'다. 글상자가 아니므로 절대 태그하지 않는다.
- "①[자료1]은 ~이다." → 그대로 (태그 없음)
- "37. <보기>에 나타난 ~" → 그대로 (태그 없음)
- "38. <보기>의 ㄱ에 대한 설명" → 그대로 (태그 없음)
- "[자료2]는 ~" → 그대로 (태그 없음)
빈칸(□·____)은 문장 중간이라도 항상 태그한다. 해당 요소가 없으면 원문 그대로 출력한다.

대상 텍스트:
\"\"\"{text}\"\"\""""


def _strip_fence(s: str) -> str:
    return _FENCE_RE.sub("", s or "").strip().strip('"').strip()


def _content_sig(s: str) -> str:
    """태그·빈칸·테두리 구획문자·공백을 제거한 '내용 지문' — 보존 검증용."""
    s = _TAG_TOKEN_RE.sub("", s)
    return re.sub(r"[□☐▢☑✓_\s<>〈〉【】\[\]「」『』]", "", s)


def _validate_tagging(original: str, tagged: str) -> bool:
    """LLM 태깅 결과 안전 검증: 알려진 태그만·내용 보존·비어있지 않음."""
    if not tagged.strip():
        return False
    for _slash, name in _TAG_TOKEN_RE.findall(tagged):
        if name not in _KNOWN_TAGS:
            return False
    return _content_sig(original) == _content_sig(tagged)


async def _tag_layout(text: str) -> str:
    """후보 신호가 있으면 LLM으로 레이아웃 태그 삽입(HCXT→검증→GPT-4o→원문)."""
    if not text.strip() or not _TAG_CANDIDATE_RE.search(text):
        return text
    prompt = _TAG_PROMPT.format(text=text)
    max_tokens = min(1024, max(128, int(len(text) * 1.6)))

    # 1) HCXT 우선(로컬·무료). 로드돼 있을 때만.
    if model_manager.get_status().get("hcxt_loaded"):
        try:
            out = _strip_fence(await hcxt_optimize(
                prompt, config.hcxt_element_timeout_seconds, max_new_tokens=max_tokens, kind="태깅"))
            if _validate_tagging(text, out):
                return out
            logger.info("HCXT 태깅 검증 실패 → GPT-4o 폴백")
        except Exception as exc:  # noqa: BLE001
            logger.warning("HCXT 태깅 예외 → GPT-4o 폴백: %s", exc)

    # 2) GPT-4o 폴백(포맷 안정).
    try:
        out = _strip_fence(await fallback_optimize(prompt, max_tokens=max_tokens, kind="태깅"))
        if _validate_tagging(text, out):
            return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("GPT-4o 태깅 예외: %s", exc)

    # 3) 둘 다 실패 → 원문 보존(빈 결과·내용변경 금지).
    return text


def _min_trail(text: str) -> list[RuleApplication]:
    """텍스트 점역 기본 원칙(KBR-0.1) — 요소 전체(line_no=-1, 포괄 규칙)."""
    return [make_rule("KBR-0.1")]

# QUALITY 티어(저신뢰 스캔)에서만 호출 — OCR 오류 교정. 프롬프트 잔재('신뢰도/입력/출력'
# 라벨)가 출력에 새지 않도록 라벨을 넣지 않고 결과만 받도록 지시한다(누출 버그 방지).
_PROMPT_QUALITY = """다음 텍스트의 OCR 오류(깨진 글자·잘못된 띄어쓰기·오인식)만 교정해 교정된 텍스트만 출력하세요. 설명·머리말·따옴표 없이 결과만.

{text}"""

# 답변을 `교정된 텍스트: `로 프리필 — Think 모델이 "원본 텍스트에서 오류를 발견했습니다…" 식
# 설명을 늘어놓지 않고 곧바로 교정문을 내도록 시작을 강제(시각 opt 프리필과 동일 기법).
# 프리필 스캐폴드는 _extract에서 제거하므로 최종 출력엔 라벨이 남지 않는다.
_PREFILL = "교정된 텍스트: "

# 모델이 프롬프트 라벨을 복창한 경우 선두에서 제거(방어적 후처리).
_ARTIFACT_RE = re.compile(r"^\s*(신뢰도|입력|출력|교정(된)?\s*텍스트|결과)\s*[:：].*$")


def _clean_output(text: str) -> str:
    """LLM 출력에서 프롬프트 잔재(선두 라벨 줄)·감싼 따옴표 제거."""
    raw = text or ""
    lines = raw.splitlines()
    while lines and (not lines[0].strip() or _ARTIFACT_RE.match(lines[0])):
        lines.pop(0)
    cleaned = "\n".join(lines).strip().strip("\"'`「」“”").strip()
    return cleaned or raw.strip()


def _extract(resp: str) -> str:
    """프리필 스캐폴드만 제거하고 본문은 그대로 둔다(여러 줄 교정문 보존).

    프리필이 이미 설명 머리말을 억제하므로 첫 줄만 자르지 않는다 — 여러 문장/줄로 된
    교정 텍스트가 잘려 소실되는 것을 막는다. 선두 라벨·따옴표는 _clean_output이 정리.
    """
    t = resp[len(_PREFILL):] if resp.startswith(_PREFILL) else resp
    return _clean_output(t)


class TextOpt(BaseOpt):
    """ExtractedContent 목록 → LLMOutput 목록."""

    async def _optimize_one(self, ext: ExtractedContent, routing_tier: str) -> LLMOutput:
        text = ext.corrected_text or ""
        start = time.monotonic()

        # ZERO / STANDARD Tier: OCR 교정은 생략(품질 충분) — 텍스트 원문 보존.
        # HCXT OCR 교정은 QUALITY(신뢰도 < threshold, 저화질 스캔)에서만.
        if routing_tier in ("ZERO", "STANDARD") or ext.ocr_confidence >= config.ocr_confidence_threshold:
            tagged = await _tag_layout(text)  # 레이아웃 태깅(점역자주·테두리·빈칸)
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text=tagged,
                render_mode="text_only",
                routing_tier=routing_tier if routing_tier in ("ZERO", "STANDARD") else "STANDARD",
                processing_time_ms=int((time.monotonic() - start) * 1000),
                rule_trail=_min_trail(tagged),
            )

        # 입력 텍스트 길이 기반 max_new_tokens: 한글 1자 ≈ 1~2토큰, 여유분 30% 추가
        max_new_tokens = min(512, max(64, int(len(text) * 1.3)))
        response, used_fb = await generate_with_retry(
            _PROMPT_QUALITY.format(text=text),
            timeout=config.hcxt_quality_timeout_seconds, element_id=ext.element_id, kind="텍스트",
            prefill=_PREFILL, max_new_tokens=max_new_tokens, fallback_max_tokens=1024,
            transform=_extract,
        )
        tier = "FALLBACK" if used_fb else "QUALITY"

        corrected = await _tag_layout(response or text)  # OCR 교정 후 레이아웃 태깅
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return LLMOutput(
            element_id=ext.element_id,
            corrected_text=corrected,
            render_mode="text_only",
            routing_tier=tier,
            processing_time_ms=elapsed_ms,
            rule_trail=_min_trail(corrected),
        )
