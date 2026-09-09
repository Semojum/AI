"""LLM 비전 추출 — 쪽 이미지를 모델이 직접 읽어 경계 파일 요소를 만든다.

**고급 점역**(`advanced_ai=true`, 2026-09-01 대표 결정)
   MinerU **대신** 이 경로가 지면을 읽는다. 기본은 Sonnet 5, 실패하거나 결과가 빈약하면
   Opus 5로 한 번 더 간다. 실측 근거(수학 정답 해설 10쪽, `temp/reports/0901_모델사다리_전문.html`):

   | | 깨진 글자가 든 블록 | LaTeX 비율 | 10쪽 비용 |
   |---|---|---|---|
   | MinerU | 128 | 44.9% | GPU 20~35초/쪽 |
   | Sonnet 5 | **0** | **77.5%** | $1.27 |
   | Opus 5 | 0 | 74.1% | $2.71 |

   MinerU 는 한자·가나가 섞여 나온다(`以⑦）`·`軸`·`구-七기가를`). Sonnet 5 는 그게 없고
   값이 Opus 의 절반이라 기본으로 둔다.

★ 2026-09-08(재구조화 5단계) — **빈약 폴백(L10)을 지웠다.** 기본 off(`OPUS_EXTRACT_FALLBACK=1`
opt-in)로 두 달을 뒀는데 켠 적이 없고, 코퍼스 1,131쪽에서 임계 근처가 0쪽이었다
(설계 §2-1 L10). 되살릴 일이 있으면 `git log -- app/ai/parser/opus_fallback.py` 에 있다.

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
# 상한을 넘겨 JSON 이 잘리면 그 쪽이 통째로 날아간다. 실측에서 16,000 으로는 10쪽 중
# 2쪽이 잘렸다. 큰 상한은 스트리밍으로 받아야 HTTP 타임아웃에 안 걸린다.
_MAX_TOKENS = int(os.environ.get("ADVANCED_EXTRACT_MAX_TOKENS", "32000"))

# 1차가 오래 걸렸으면 2차를 부르지 않는다. 페이지 예산이 180초(C7)인데 추출 한 번이
# 실측 60~110초라, 두 번 부르면 점역·조판 시간이 남지 않아 쪽 전체가 BLOCKED 로 죽는다.
# 되돌아갈 MinerU 는 20~35초라 그쪽이 낫다.
_ADVANCED_RETRY_BUDGET = float(os.environ.get("ADVANCED_EXTRACT_RETRY_BUDGET", "60"))

# ★ 2026-09-07 — image 지시를 캡셔너(`captioning/captioner.py::_PROMPTS`)와 맞췄다.
#   두 프롬프트가 같은 자료에 다른 것을 시키고 있었고, 어긋난 세 축이 전부 gold 와
#   맞지 않는 쪽이었다(캡셔너만 고치면 이 경로가 옛 동작으로 남는다):
#     · 분량   여기 "한두 문장" → 쪽 추출 929건 중 99.4%가 한 줄. gold 그림은 4줄+가 32.7%
#     · 추세   여기 "값의 대소 관계를 적습니다" → 우리 그래프 16건 중 11건(68.8%)에
#              추세 표현. gold 그래프 34건 전수 **0건**. 캡셔너는 같은 것을 금지한다
#     · 종류어 gold 그림 565건 중 **0건**인데 쪽 추출 199/929(21.4%)
#   유형어만 이 프롬프트 쪽이 맞았다(gold 733건 중 "도표" 1건).
_PROMPT = """이 교과서 페이지의 모든 텍스트를 읽기 순서대로 추출하세요.

JSON 배열만 출력합니다. 각 요소: {"type": "...", "content": "..."}
type: text(문단 단위로, 중간에 자르지 말 것) | list_item(선택지 묶음은 한 요소) |
header_footer | page_number | caption | table(행은 |, 줄은 개행) | formula(LaTeX) |
image(그림·사진·그래프·지도·만화·도표. content 첫 줄에 유형어를 쓰고, **다음 줄부터
      항목을 한 줄씩** 적는다. 한 문단으로 잇지 않는다. **분량은 자료가 정한다**)

★ image 의 content 를 비우지 마세요. 이 설명이 점자책에서 그림을 대신합니다.
- 자료 유형으로 시작합니다. 예: `그래프: …` `그림: …` `사진: …` `지도: …` `만화: …`
- 문제를 푸는 데 필요한 것만 적습니다. 색·질감·장식·촬영 각도·자세·구도는 적지 않습니다
  ('위에서 내려다본'·'늘어선'·'~가 보인다'·'~한 모습').
- **줄을 나누는 근거는 자료가 이미 나뉘어 있는 자리입니다.** 가로축·세로축이 있으면
  축 한 줄 뒤에 계열마다 한 줄. 칸이 둘 이상이면 칸마다 한 줄. 화살표 사슬이 둘 이상이면
  사슬마다 한 줄. 사슬이 하나면 아무리 길어도 한 줄. 이름표마다 값이 한 낱말뿐이면
  한 줄에 몰아 씁니다. 아무것도 아니면 한 줄로 끝냅니다.
  한 줄은 한글 21자(중앙값)~33자(3사분위)입니다.
- 그래프는 `항목: 값` 을 한 줄씩 적습니다. **대소 관계·추세·해석은 한 글자도 쓰지 않습니다**
  ('증가'·'가장 높음'·'~보다 많다'). 값이 막대·조각에 찍혀 있으면 축 줄을 쓰지 말고,
  값이 없어 눈금에서 읽어야 할 때만 `세로축(단위): 눈금 나열` 을 씁니다.
- 도식은 **종류 이름(모식도·구조도·흐름도·조직도·계통도)을 쓰지 말고** 순서와 갈래만 적습니다.
- **지도**는 있는 범주만 한 줄씩 적습니다: 이름표 대응(`㉠ 사할린섬`) · 범례 ·
  `<주체>의 최대 영역: 지명 …` · `<주체>의 침입로: A → B → C` · 지명 나열(쉼표로 한 줄) · 출처.
- **만화**는 두 조각으로 나눠 적습니다. content 첫 줄은 `만화: <누가 무엇을 하고 있음.>`
  한 문장이고, 그다음 줄부터 `<인물>: <말풍선 글자 그대로>` 를 한 줄씩 적습니다.
  화면·자막·인용 상자의 글자는 대사가 아닙니다. 말풍선이 없으면 대사 줄을 쓰지 않습니다.
- **사진**은 그 대상의 **이름 한 줄**로 끝냅니다(한글 13자 안팎). 문장으로 늘리지 마세요.
- 이름표(㉠·(가)·①)가 가리키는 곳은 **그 대상의 이름**으로 적습니다.
  위치('일본 열도 동북쪽')로 대신하지 마세요. 이름을 모르면 적지 않습니다.
- 칸이 **8개 이상 격자로** 늘어선 자료는 격자 값을 산문으로 뭉뚱그리지 말고
  행 이름·열 이름과 칸 수를 밝힌 뒤 '표로 옮겨야 함'이라고 적습니다.
- **자료가 둘이면 image 요소도 둘입니다.** 나란히 놓인 그래프·지도를 한 요소로 합치지 마세요.
- 자료 **안에** 있는 글자만 그대로 옮겨 적습니다. **사진 아래 캡션은 이미 caption 요소로
  따로 내므로 image content 에 다시 적지 마세요.**

수식은 반드시 LaTeX으로 적습니다. 이 규칙이 가장 중요합니다.
- 유니코드 수학 기호를 그대로 쓰지 마세요. `≤`는 `\\le`, `≥`는 `\\ge`, `≠`는 `\\neq`,
  `∫`는 `\\int`, `∑`는 `\\sum`, `√`는 `\\sqrt{}`, `→`는 `\\to`, `×`는 `\\times`,
  `⊥`는 `\\perp`, `∠`는 `\\angle`, `∈`는 `\\in`, `∞`는 `\\infty`로 적습니다.
- 분수는 `\\frac{분자}{분모}`, 첨자는 `x^{2}`·`a_{n}`으로 적습니다.
- 문장 안에 섞인 수식도 `$...$`로 감쌉니다. 예: `함수 $f(x)$가 $0 \\le x \\le 4$에서`
- 독립된 수식 줄은 type을 formula로 하고 `$...$` 없이 LaTeX만 적습니다.

규칙: 글자를 지어내지 마세요. 지면에 없는 한자를 넣지 마세요.
강조 구간은 <!강조>…<!/강조>. 흐릿해서 못 읽는 글자는 `□` 하나로 적습니다. JSON 외 출력 금지."""


def advanced_available() -> bool:
    """고급 점역을 쓸 수 있나 — 키가 있어야 한다."""
    return bool(config.anthropic_api_key)


# 빈약 판정: 요소가 이만큼도 안 나오거나, 텍스트류 총 글자가 이만큼도 안 되면
# 페이지를 사실상 못 읽은 것이다(실측: 문제 페이지는 보통 요소 0~3·수십 자).
_MIN_ELEMENTS = 3
_MIN_TEXT_CHARS = 120


def is_meager(elements: list[dict]) -> bool:
    """추출이 빈약한가 — 고급 점역 2차(Opus 5) 트리거 신호."""
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


def extract(image_path: str, model: str, label: str = "고급추출") -> list[dict] | None:
    """쪽 이미지 → 경계 파일 형식 elements. 실패 시 None(호출부가 원 추출을 유지한다)."""
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
