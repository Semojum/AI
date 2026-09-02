"""PART 5-2 — 수식 점역 최적화 (HyperCLOVA X SEED Think 14B INT4, GPU 1).

ZERO     → LLM 호출 없음, LaTeX 정규화만 수행
STANDARD → HyperCLOVA X, 15초 제한
QUALITY  → HyperCLOVA X, 30초 제한
FALLBACK → GPT-4o API, 45초 제한 (3회 연속 실패 후)

공통 추론·폴백·재시도는 base_opt — 여기서는 수식에 최적화된 프롬프트·정규화만 정의한다.
"""

from __future__ import annotations

import logging
import asyncio
import os
import re
import time

from app.ai.llm.base_opt import BaseOpt, decide_tier_timeout, generate_with_retry
from app.core.model_manager import model_manager  # noqa: F401 (단위 테스트가 이 네임스페이스를 patch)
from app.schemas.content import ExtractedContent, LLMOutput, RuleApplication

logger = logging.getLogger(__name__)



def _min_trail(text: str) -> list[RuleApplication]:
    """Step17(2026-08-08) — 포괄 규정을 달지 않는다. 근거는 formula_braille가 구조별로 낸다."""
    return []

# stage3_complex.md T3-3: LaTeX 기호 → 유니코드 정규화 (LLM 교정 보조용)
# \\times / \\div / \\cdot 는 kor_math_rules에서 단일 처리 — 여기서 제거
_LATEX_NORMALIZE = [
    (r"\\alpha",  "α"),
    (r"\\beta",   "β"),
    (r"\\gamma",  "γ"),
    (r"\\delta",  "δ"),
    (r"\\theta",  "θ"),
    (r"\\pi",     "π"),
    (r"\\sigma",  "σ"),
    (r"\\omega",  "ω"),
    (r"\\infty",  "∞"),
    (r"\\in\b",   "∈"),
    (r"\\notin",  "∉"),
    (r"\\subset", "⊂"),
    (r"\\supset", "⊃"),
    (r"\\cup",    "∪"),
    (r"\\cap",    "∩"),
    (r"\\pm",     "±"),
    (r"\\leq",    "≤"),
    (r"\\geq",    "≥"),
    (r"\\neq",    "≠"),
    (r"\\approx", "≈"),
]

_PROMPT = """당신은 한국어 수학 점역 전문가입니다.
다음 LaTeX 수식을 점역 가능한 형태로 교정하세요.

규칙:
1. LaTeX 구조 유지 (\\frac, \\sqrt, ^, _ 등)
2. 불완전한 LaTeX 구문 복원
3. OCR 오인식 기호 교정 (예: O→0, l→1)
4. [처리 불가: ...] 플레이스홀더는 그대로 유지

LaTeX:
{latex}

교정된 LaTeX만 반환하세요."""

# 답변을 `교정된 LaTeX: `로 프리필 — Think 모델이 "주어진 수식을 교정해야 합니다. 규칙을…"
# 식 사고과정을 출력하지 않고 곧바로 LaTeX를 내도록 시작을 강제. 스캐폴드는 _extract에서 제거.
_PREFILL = "교정된 LaTeX: "


# ★ MinerU LaTeX는 숫자를 자릿수마다 띄운다: \frac {8 0 0}{x}. 그대로 점역하면 수마다
#   수표(⠼)가 붙어 정답(⠼⠓⠚⠚=800 수표 1개)과 전부 어긋난다 — dev 전수에서 수식 무수정
#   1.1%의 주원인(2026-07-17, 수학2 p009 정답 'x분의800' 대조). 숫자-공백-숫자를 붙인다.
#   소수점·쉼표 낀 것(1 2. 5, 1, 2 0 0)도 한 수다. 단어 경계의 진짜 띄움(연산 뒤 "= 2 0"의
#   2 0)도 한 수가 맞아 함께 붙는다.
_DIGIT_GAP_RE = re.compile(r"(?<=\d)\s+(?=[\d.,]\b|\d)")

# MinerU는 수식 속 한글도 음절마다 띄운다("이 므 로"). 정답은 붙인다(수학2 p005 '이므로').
# 1음절 토큰 2개 이상의 연속만 붙인다 — "일의 양"처럼 다음절 어절이 낀 진짜 띄어쓰기는 유지
# (정답 '시간당 일의 양'도 공백 유지).
_KOR_SYL_GAP_RE = re.compile(r"(?<![가-힣])((?:[가-힣] )+[가-힣])(?![가-힣])")


# MinerU가 수학 선지 머리 자모를 기호로 오인한다(수학2 p070 실측): ㄱ.→\neg . / ㄴ.→\llcorner . /
# ㄷ.→\sqsubset . 논리 부정 \neg은 뒤에 마침표가 오지 않으므로 ". " 동반일 때만 자모로 되돌린다.
_JAMO_ALIAS = [(re.compile(r"\\neg\s*\."), "ㄱ."),
               (re.compile(r"\\llcorner\s*\."), "ㄴ."),
               (re.compile(r"\\sqsubset\s*\."), "ㄷ.")]


# 블록 수식 구분자 `$$…$$`(QA 11번, 2026-08-08). 종전에는 _extract에서만 지웠는데,
# _extract는 **HCLOVA X 응답에만** 걸린다(base_opt.generate_with_retry의 transform은
# 폴백 응답을 통과시킨다). 그래서 실제 운영에서는 세 갈래로 새어 나갔다:
#   ZERO 티어      → _normalize(raw)로 MinerU 원문을 그대로 통과
#   GPT-4o 폴백    → 응답에 `$$`가 있어도 transform 미적용
#   LLM 실패       → `response or raw`의 raw 쪽
# 대표님 QA 10 job 전부 FALLBACK이라 `$$\n…\n$$`가 편집창까지 그대로 갔다.
# _normalize는 네 갈래가 **모두** 지나는 유일한 지점이라 여기서 한 번 지운다.
_BLOCK_WRAP_RE = re.compile(r"^\s*(\${1,2})\s*(.*?)\s*\1\s*$", re.DOTALL)


def _normalize(latex: str) -> str:
    m = _BLOCK_WRAP_RE.match(latex or "")
    if m:
        latex = m.group(2)
    latex = _DIGIT_GAP_RE.sub("", latex)
    latex = _KOR_SYL_GAP_RE.sub(lambda m: m.group(1).replace(" ", ""), latex)
    for pat, repl in _JAMO_ALIAS:
        latex = pat.sub(repl, latex)
    for pattern, replacement in _LATEX_NORMALIZE:
        latex = re.sub(pattern, replacement, latex)
    return latex


# ```latex … ``` 코드펜스(언어태그 포함)·$$ 구분자 제거. 백틱만 strip하면 'latex'
# 언어태그가 남아 그대로 점역되는 버그가 있었다(⠇⠁⠞⠑⠭).
_FENCE_RE = re.compile(r"```[a-zA-Z]*\n?|```")
_DOLLAR_RE = re.compile(r"^\s*\${1,2}|\${1,2}\s*$")


# 모델이 수식 옆에 붙여 쓴 해설 줄. 앞머리("주어진 수식을 분석하겠습니다.")로도, 꼬리
# 목록("- `2 π`는 `2π`로 붙여 표기를 통일했습니다.")으로도 온다.
# ★ **수식에 한국어 종결어미가 나올 일이 없다**는 것이 근거다. 실측(storage 산출물
#   수식 출력 10,417개)에서 이 꼬리를 가진 줄은 47개뿐이고 74종 전수를 눈으로 봤을 때
#   **정상 수식은 0개**였다. 본문 텍스트에는 이 규칙을 쓰면 안 된다 — 지문 대사가
#   "…하겠습니다"로 끝나는 일이 흔하다.
_COMMENT_LINE_RE = re.compile(r"(?:습니다|합니다|입니다|됩니다|바랍니다|하겠습니다)\s*[.。]?\s*$")


def _drop_commentary(t: str) -> str:
    """수식 출력에서 모델 해설 줄을 걷어 낸다. 다 걷히면 원본을 지킨다(빈 수식 금지)."""
    if not t:
        return t
    kept = [ln for ln in t.splitlines() if not _COMMENT_LINE_RE.search(ln)]
    if len(kept) == len(t.splitlines()):
        return t                          # 걷을 게 없으면 원본을 그대로 (공백까지 보존)
    out = "\n".join(kept).strip()
    return out or t


def _extract(resp: str) -> str:
    """프리필 스캐폴드·코드펜스·$$ 구분자를 제거하고 본문은 그대로 둔다(여러 줄 LaTeX 보존).

    프리필이 설명 머리말을 억제하므로 첫 줄만 자르지 않는다 — \\begin{cases} 등
    여러 줄 수식이 잘려 깨지는 것을 막는다.
    """
    t = resp[len(_PREFILL):] if resp.startswith(_PREFILL) else resp
    t = _FENCE_RE.sub("", t).strip()      # ```latex … ``` 펜스(언어태그 포함)
    t = t.strip("`").strip()              # 잔여 인라인 백틱(`…`)
    t = _DOLLAR_RE.sub("", t).strip()     # $$ … $$ 구분자
    return _drop_commentary(t)


# ── 배치 교정 (2026-09-02) ────────────────────────────────────────────────
# 종전에는 수식 **요소마다** LLM 을 한 번씩 불렀다. 정답 해설 한 쪽에 수식이 43개면
# 43회다. 동시 4페이지면 순간 170회가 넘어 계정 분당 한도에 걸리고, 재시도 백오프가
# 쌓여 추출·점역이 함께 늘어졌다 — 운영 실측(2026-09-02, 정답 해설 10쪽)에서 7쪽이
# 180초 예산을 넘겨 BLOCKED 였고 `FALLBACK 수식 최적화 실패` 가 6건이었다.
#
# 한 번에 묶어 보내고 번호로 짝을 맞춘다. **개수가 어긋나면 통째로 버리고 원본을 쓴다** —
# 짝이 밀리면 다른 수식의 교정본이 엉뚱한 자리에 박히는데, 그건 안 고친 것보다 나쁘다.
_BATCH_ON = os.environ.get("FORMULA_BATCH", "1") == "1"
_BATCH_SIZE = int(os.environ.get("FORMULA_BATCH_SIZE", "12"))

_BATCH_PROMPT = """당신은 한국어 수학 점역 전문가입니다.
아래 LaTeX 수식들을 각각 점역 가능한 형태로 교정하세요.

규칙:
1. LaTeX 구조 유지 (\\frac, \\sqrt, ^, _ 등)
2. 불완전한 LaTeX 구문 복원
3. OCR 오인식 기호 교정 (예: O→0, l→1)
4. [처리 불가: ...] 플레이스홀더는 그대로 유지

입력은 `[N]` 으로 번호가 붙어 있습니다. 출력도 **같은 번호를 같은 개수만큼**,
한 줄에 하나씩 `[N] 교정된LaTeX` 형식으로만 내세요. 설명·머리말을 붙이지 마세요.

{items}"""

_BATCH_PREFILL = "[1] "
_BATCH_LINE_RE = re.compile(r"^\s*\[(\d+)\]\s*(.*)$")


def _batch_parse(resp: str, n: int) -> list[str] | None:
    """`[N] …` 응답 → 번호순 목록. 짝이 안 맞으면 None(호출부가 원본을 지킨다)."""
    if not resp:
        return None
    text = resp if resp.lstrip().startswith("[") else _BATCH_PREFILL + resp
    got: dict[int, str] = {}
    cur: int | None = None
    for line in text.splitlines():
        m = _BATCH_LINE_RE.match(line)
        if m:
            cur = int(m.group(1))
            got[cur] = m.group(2).strip()
        elif cur is not None and line.strip():
            got[cur] = (got[cur] + "\n" + line.rstrip()).strip()
    if len(got) != n or set(got) != set(range(1, n + 1)):
        return None
    # `[N]` 으로 시작하지 않는 줄은 위에서 앞 수식에 이어 붙는다 — 해설을 덧붙이면
    # 그게 수식이 되어 버린다(FE QA: "~방식으로 처리했습니다"가 초안에 그대로 실림).
    return [_drop_commentary(got[i]) for i in range(1, n + 1)]


class FormulaOpt(BaseOpt):
    """ExtractedContent 목록 → LLMOutput 목록 (수식)."""

    async def optimize(self, extracted, routing_tier, layout=None):
        """LLM 이 필요한 것만 골라 **묶어서** 한 번에 교정한다(위 _BATCH_SIZE 주석).

        ZERO 티어·빈 수식·C3 폴백은 LLM 을 안 타므로 종전 경로 그대로 둔다.
        배치가 실패하거나 짝이 안 맞으면 요소별 호출로 되돌아간다 — 느려질 뿐 결과는 같다.
        """
        if not _BATCH_ON or routing_tier == "ZERO":
            return await super().optimize(extracted, routing_tier, layout)
        need = [e for e in extracted
                if "C3_FALLBACK" not in e.flags
                and (e.latex_string or e.corrected_text or "").strip()]
        if len(need) < 2:
            return await super().optimize(extracted, routing_tier, layout)

        fixed: dict = {}
        for i in range(0, len(need), _BATCH_SIZE):
            chunk = need[i:i + _BATCH_SIZE]
            raws = [(e.latex_string or e.corrected_text or "") for e in chunk]
            items = "\n".join(f"[{k}] {r}" for k, r in enumerate(raws, 1))
            _tier, timeout = decide_tier_timeout(
                min((e.ocr_confidence for e in chunk), default=1.0))
            try:
                resp, used_fb = await generate_with_retry(
                    _BATCH_PROMPT.format(items=items),
                    timeout=timeout * 2, element_id=chunk[0].element_id, kind="수식",
                    prefill=_BATCH_PREFILL,
                    max_new_tokens=256 * len(chunk), fallback_max_tokens=512 * len(chunk),
                    transform=lambda t: t,
                )
            except Exception:                       # noqa: BLE001 — 배치 실패는 요소별로 되돌린다
                resp, used_fb = "", False
            got = _batch_parse(resp, len(chunk))
            if got is None:
                logger.warning("수식 배치 %d개 짝이 안 맞아 원본을 지킨다", len(chunk))
                continue
            for e, raw, out in zip(chunk, raws, got):
                fixed[e.element_id] = (_normalize(_extract(out) or raw),
                                       "FALLBACK" if used_fb else _tier)

        async def _one(e):
            hit = fixed.get(e.element_id)
            if hit is None:
                return await self._optimize_one(e, routing_tier)
            raw = e.latex_string or e.corrected_text or ""
            return LLMOutput(
                element_id=e.element_id, corrected_text=hit[0],
                render_mode="formula_inline" if len(raw) <= 30 else "formula_block",
                routing_tier=hit[1], processing_time_ms=0,
                rule_trail=_min_trail(hit[0]),
            )

        return await asyncio.gather(*[_one(e) for e in extracted])

    async def _optimize_one(self, ext: ExtractedContent, routing_tier: str) -> LLMOutput:
        raw = ext.latex_string or ext.corrected_text or ""
        start = time.monotonic()

        if "C3_FALLBACK" in ext.flags or not raw.strip():
            placeholder = "[수식 재확인 필요]" if raw.strip() else "[처리 불가: 수식 OCR 실패]"
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text=placeholder,
                render_mode="formula_block",
                routing_tier="FALLBACK",
                processing_time_ms=0,
                rule_trail=_min_trail(placeholder),
            )

        render_mode = "formula_inline" if len(raw) <= 30 else "formula_block"

        if routing_tier == "ZERO":
            norm = _normalize(raw)
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text=norm,
                render_mode=render_mode,
                routing_tier="ZERO",
                processing_time_ms=0,
                rule_trail=_min_trail(norm),
            )

        tier, timeout = decide_tier_timeout(ext.ocr_confidence)   # 요소당 상한 = config(작게)
        response, used_fb = await generate_with_retry(
            _PROMPT.format(latex=raw),
            timeout=timeout, element_id=ext.element_id, kind="수식",
            prefill=_PREFILL, max_new_tokens=256, fallback_max_tokens=512,
            transform=_extract,
        )
        if used_fb:
            tier = "FALLBACK"

        corrected = _normalize(response or raw)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return LLMOutput(
            element_id=ext.element_id,
            corrected_text=corrected,
            render_mode=render_mode,
            routing_tier=tier,
            processing_time_ms=elapsed_ms,
            rule_trail=_min_trail(corrected),
        )
