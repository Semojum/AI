"""LLM 비전 추출 — 쪽 이미지를 모델이 직접 읽어 경계 파일 요소를 만든다.

두 갈래로 쓴다.

**① 고급 점역**(`advanced_ai=true`, 2026-09-01 대표 결정)
   MinerU **대신** 이 경로가 지면을 읽는다. 기본은 Sonnet 5, 실패하거나 결과가 빈약하면
   Opus 5로 한 번 더 간다. 실측 근거(수학 정답 해설 10쪽, `temp/reports/0901_모델사다리_전문.html`):

   | | 깨진 글자가 든 블록 | LaTeX 비율 | 10쪽 비용 |
   |---|---|---|---|
   | MinerU | 128 | 44.9% | GPU 20~35초/쪽 |
   | Sonnet 5 | **0** | **77.5%** | $1.27 |
   | Opus 5 | 0 | 74.1% | $2.71 |

   MinerU 는 한자·가나가 섞여 나온다(`以⑦）`·`軸`·`구-七기가를`). Sonnet 5 는 그게 없고
   값이 Opus 의 절반이라 기본으로 둔다.

**② 빈약 폴백**(D-05, 기본 off — `OPUS_EXTRACT_FALLBACK=1`)
   고급 점역이 꺼진 보통 경로에서, MinerU 결과가 사실상 비었을 때만 한 번 구제한다.
   중간 품질 페이지는 득실이 반반이라 교체하지 않는다(2026-07-17 오프라인 실측).

호출·토큰은 `req_log` 에 모델명과 함께 남는다 — 모델마다 단가가 달라 이름이 없으면 원가가 안 맞는다.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time

from app.core.config import config

logger = logging.getLogger(__name__)

# 고급 점역 기본 모델과, 그게 실패했을 때 한 번 더 갈 모델.
ADVANCED_MODEL = os.environ.get("ADVANCED_EXTRACT_MODEL", "claude-sonnet-5")
ADVANCED_FALLBACK_MODEL = os.environ.get("ADVANCED_EXTRACT_FALLBACK_MODEL", "claude-opus-5")
# 빈약 폴백(②)에서 쓰는 모델. 종전 동작을 그대로 둔다.
MODEL = os.environ.get("OPUS_EXTRACT_MODEL", "claude-opus-4-8")

# 상한을 넘겨 JSON 이 잘리면 그 쪽이 통째로 날아간다. 실측에서 16,000 으로는 10쪽 중
# 2쪽이 잘렸다. 큰 상한은 스트리밍으로 받아야 HTTP 타임아웃에 안 걸린다.
_MAX_TOKENS = int(os.environ.get("ADVANCED_EXTRACT_MAX_TOKENS", "32000"))

# 1차가 오래 걸렸으면 2차를 부르지 않는다. 페이지 예산이 180초(C7)인데 추출 한 번이
# 실측 60~110초라, 두 번 부르면 점역·조판 시간이 남지 않아 쪽 전체가 BLOCKED 로 죽는다.
# 되돌아갈 MinerU 는 20~35초라 그쪽이 낫다.
_ADVANCED_RETRY_BUDGET = float(os.environ.get("ADVANCED_EXTRACT_RETRY_BUDGET", "60"))

# 빈약 판정: 요소가 이만큼도 안 나오거나, 텍스트류 총 글자가 이만큼도 안 되면
# 페이지를 사실상 못 읽은 것이다(실측: 문제 페이지는 보통 요소 0~3·수십 자).
_MIN_ELEMENTS = int(os.environ.get("OPUS_FALLBACK_MIN_ELEMENTS", "3"))
_MIN_TEXT_CHARS = int(os.environ.get("OPUS_FALLBACK_MIN_CHARS", "120"))

_PROMPT = """이 교과서 페이지의 모든 텍스트를 읽기 순서대로 추출하세요.

JSON 배열만 출력합니다. 각 요소: {"type": "...", "content": "..."}
type: text(문단 단위로, 중간에 자르지 말 것) | list_item(선택지 묶음은 한 요소) |
header_footer | page_number | caption | table(행은 |, 줄은 개행) | formula(LaTeX) |
image(그림·사진·그래프·도표. content 에 **그 자료가 무엇인지** 한두 문장으로 적는다)

★ image 의 content 를 비우지 마세요. 이 설명이 점자책에서 그림을 대신합니다.
- 자료 유형으로 시작합니다. 예: `그래프: …` `그림: …` `표: …` `지도: …`
- 문제를 푸는 데 필요한 것만 적습니다. 색·질감·장식은 적지 않습니다.
- 그래프는 축 이름과 값의 대소 관계를, 도식은 순서와 갈래를 적습니다.
- 자료 안에 글자가 있으면 그 글자를 그대로 옮겨 적습니다.

수식은 반드시 LaTeX으로 적습니다. 이 규칙이 가장 중요합니다.
- 유니코드 수학 기호를 그대로 쓰지 마세요. `≤`는 `\\le`, `≥`는 `\\ge`, `≠`는 `\\neq`,
  `∫`는 `\\int`, `∑`는 `\\sum`, `√`는 `\\sqrt{}`, `→`는 `\\to`, `×`는 `\\times`,
  `⊥`는 `\\perp`, `∠`는 `\\angle`, `∈`는 `\\in`, `∞`는 `\\infty`로 적습니다.
- 분수는 `\\frac{분자}{분모}`, 첨자는 `x^{2}`·`a_{n}`으로 적습니다.
- 문장 안에 섞인 수식도 `$...$`로 감쌉니다. 예: `함수 $f(x)$가 $0 \\le x \\le 4$에서`
- 독립된 수식 줄은 type을 formula로 하고 `$...$` 없이 LaTeX만 적습니다.

규칙: 글자를 지어내지 마세요. 지면에 없는 한자를 넣지 마세요.
강조 구간은 <!강조>…<!/강조>. 흐릿해서 못 읽는 글자는 `□` 하나로 적습니다. JSON 외 출력 금지."""


def enabled() -> bool:
    """빈약 폴백(②)이 켜져 있나. 고급 점역(①)은 요청 플래그로 따로 켠다."""
    return (os.environ.get("OPUS_EXTRACT_FALLBACK", "0") == "1"
            and bool(config.anthropic_api_key))


def advanced_available() -> bool:
    """고급 점역을 쓸 수 있나 — 키가 있어야 한다."""
    return bool(config.anthropic_api_key)


def is_meager(elements: list[dict]) -> bool:
    """추출이 빈약한가 — 폴백 트리거 신호."""
    if len(elements) < _MIN_ELEMENTS:
        return True
    chars = sum(len(e.get("content") or "") for e in elements
                if e.get("type") not in ("image", "cartoon", "chart_graph"))
    return chars < _MIN_TEXT_CHARS


def _parse(txt: str) -> list:
    """모델 응답 → JSON 배열. 코드펜스와 앞뒤 군더더기를 걷어 낸다."""
    txt = txt.strip()
    if txt.startswith("```"):
        txt = txt.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        s, e = txt.find("["), txt.rfind("]")
        if s < 0 or e <= s:
            raise
        return json.loads(txt[s:e + 1])


def extract(image_path: str, model: str | None = None,
            label: str = "opus추출") -> list[dict] | None:
    """쪽 이미지 → 경계 파일 형식 elements. 실패 시 None(호출부가 원 추출을 유지한다)."""
    model = model or MODEL
    try:
        import anthropic

        from app.core.limits import estimate_tokens, llm_limiter
        from app.utils.req_log import record_anthropic
        # ★ 키를 **명시로 넘긴다**(2026-09-02). 인자 없이 만들면 SDK 가 환경변수만 보는데,
        #   우리 키는 `.env` → `config.anthropic_api_key` 로 들어온다. 그래서 운영에서
        #   `advanced_available()` 은 True 인데 정작 호출이
        #   "Could not resolve authentication method" 로 죽어 **고급 점역이 매번 MinerU 로
        #   되돌아갔다** — 기능이 켜져도 한 번도 동작한 적이 없다. 캡셔너(captioner.py)는
        #   처음부터 명시로 넘기고 있었다.
        client = anthropic.Anthropic(api_key=config.anthropic_api_key or None,
                                     timeout=180.0, max_retries=1)
        b64 = base64.b64encode(open(image_path, "rb").read()).decode()
        # 계정 분당 상한. 쪽 전체 이미지라 입력이 크고 출력도 상한까지 잡는다.
        llm_limiter().acquire_sync(estimate_tokens(_PROMPT, len(b64) * 3 // 4), _MAX_TOKENS)
        # 큰 출력은 스트리밍으로 받는다 — 안 그러면 HTTP 타임아웃에 걸린다.
        with client.messages.stream(
            model=model, max_tokens=_MAX_TOKENS,
            messages=[{"role": "user", "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                {"type": "text", "text": _PROMPT},
            ]}],
        ) as stream:
            resp = stream.get_final_message()
        # 모델마다 단가가 다르다 — 이름을 남겨야 원가가 맞는다.
        record_anthropic(label, model, getattr(resp, "usage", None))
        els = _parse("".join(b.text for b in resp.content if b.type == "text"))
        return [{"id": f"llm-{i:03d}", "order": i, "type": e.get("type", "text"),
                 "content": e.get("content") or ""} for i, e in enumerate(els)]
    except Exception as exc:  # noqa: BLE001 — 추출 실패는 호출부가 원 추출로 격리한다
        logger.warning("LLM 추출 실패(%s): %s", model, exc)
        return None


def extract_advanced(image_path: str) -> tuple[list[dict] | None, str]:
    """고급 점역 추출. Sonnet 5 로 읽고, 실패하거나 빈약하면 Opus 5 로 한 번 더 간다.

    반환 `(elements, 쓴 모델)`. 둘 다 못 읽으면 `(None, "")` — 호출부가 MinerU 로 되돌린다.
    """
    t0 = time.monotonic()
    els = extract(image_path, ADVANCED_MODEL, "고급추출")
    if els and not is_meager(els):
        return els, ADVANCED_MODEL
    spent = time.monotonic() - t0
    if spent > _ADVANCED_RETRY_BUDGET:
        # 2차까지 부르면 페이지 예산을 넘긴다. 1차 결과가 있으면 그거라도 쓰고,
        # 없으면 호출부가 MinerU 로 되돌린다.
        logger.warning("고급 추출 1차가 %.0f초 걸려 2차를 건너뛴다(예산 %.0f초)",
                       spent, _ADVANCED_RETRY_BUDGET)
        return (els or None), (ADVANCED_MODEL if els else "")
    logger.warning("고급 추출 1차(%s) %s — %s 로 다시 읽는다",
                   ADVANCED_MODEL, "빈약" if els else "실패", ADVANCED_FALLBACK_MODEL)
    better = extract(image_path, ADVANCED_FALLBACK_MODEL, "고급추출")
    if better and not is_meager(better):
        return better, ADVANCED_FALLBACK_MODEL
    # 2차도 빈약하면 그나마 나온 쪽을 준다. 둘 다 없으면 호출부가 MinerU 로 간다.
    return (better or els or None), (ADVANCED_FALLBACK_MODEL if better else
                                     (ADVANCED_MODEL if els else ""))
