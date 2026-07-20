"""요소별 검수 우선순위 — 점역사가 어디부터 볼지 정하는 신호.

**목적**: 지금 초안은 요소의 55.6%만 정답과 완전히 같고, 오류가 페이지 전반에 흩어져
있어(크게 틀린 요소가 하나도 없는 페이지는 1,131쪽 중 8쪽뿐) 점역사가 전부 검수해야
한다. 검수 자체를 없앨 수는 없어도 **순서**는 정해 줄 수 있다.

**정직한 한계**: 아래 신호로 뽑은 최상위 등급도 실측 정확도가 89%다(9개 중 1개는 틀림).
그래서 이 값은 "확인 안 해도 된다"는 뜻이 **아니다**. 화면에도 그렇게 보여선 안 된다.
쓸 수 있는 용도는 **검수 순서**와 **주의 표시**뿐이다.

**신호와 실측 예측력** (전 코퍼스 22,384 요소, 기준 정확도 55.6%):

  왕복 일치도 = 1.0 ∧ 영문/LaTeX 없음 ∧ <120셀 …… 14% 대상 · 정확도 89.0%
  왕복 일치도 ≥ 0.98 ………………………………………… 18% 대상 · 정확도 83.6%
  표 …………………………………………………………………  2.0%   (가장 나쁨)
  소스에 영문 ………………………………………………… 23.7%
  수식 ………………………………………………………… 25.9%
  120셀 이상 ………………………………………………… 37.3%

왕복 일치도(round-trip)는 점역 결과를 역점역해 원문과 대조한 값이다. 정답이 없어도
런타임에 계산되고 추가 비용이 0이라 운영에서 그대로 쓸 수 있다.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

# 등급 — 숫자가 아니라 이름으로 다룬다. 숫자는 "88%면 안 봐도 되나?" 같은 오해를 부른다.
HIGH = "high"        # 상대적으로 안정 — 마지막에 봐도 되는 축
MEDIUM = "medium"
LOW = "low"          # 먼저 볼 것

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_LATIN_RE = re.compile(r"[A-Za-z]{3,}|\\[a-zA-Z]{2,}")
_RISKY_TYPES = {"table", "formula"}
_LONG_CELLS = 120


def _norm(text: str) -> str:
    return _WS_RE.sub("", _TAG_RE.sub("", text or ""))


def round_trip(cells: str, source_text: str, decode) -> float | None:
    """점역 결과를 역점역해 원문과 얼마나 일치하는가(0~1). 잴 수 없으면 None.

    decode는 호출부가 주입한다(app.utils.braille_back.decode) — 순환 import 회피.
    """
    src = _norm(source_text)
    if len(src) < 10 or len(cells) < 20:
        return None
    try:
        back = _norm(decode(cells))
    except Exception:  # noqa: BLE001 — 디코더 실패는 신호 없음으로 처리
        return None
    return SequenceMatcher(a=back, b=src, autojunk=False).ratio()


def grade(*, element_type: str, cells: str, source_text: str,
          decode, ocr_confidence: float | None = None) -> tuple[str, float | None]:
    """요소 → (등급, 왕복 일치도). 등급 기준은 위 문서의 실측 표에서 나왔다."""
    if element_type in _RISKY_TYPES:
        return LOW, None
    if _LATIN_RE.search(source_text or ""):
        return LOW, None
    if ocr_confidence is not None and ocr_confidence < 0.7:
        return LOW, None

    rt = round_trip(cells, source_text, decode)
    if rt is None:
        return MEDIUM, None
    if rt >= 0.999 and len(cells) < _LONG_CELLS:
        return HIGH, rt
    if rt >= 0.98:
        return MEDIUM, rt
    return LOW, rt


# 페이지 수준 '내용 누락 의심' 신호 — 시각/표 요소가 점자 셀의 이 비율 이상을
# 차지하면 고지. 실측 저오탐 조작점(2026-07-20, val 951p·dev 180p, kpi_v2
# collect·page_parts 헬퍼로 gold 커버리지<70% 페이지를 라벨해 대조):
#   임계 0.40 → val 재현 27.3%·오탐 7.1% / dev 재현 30.0%·오탐 8.8%.
# 재현율이 낮은 것은 신호의 한계가 아니라 라벨의 성질이다 — gold 커버리지 저하의
# 지배 원인은 '내용 누락'이 아니라 수식·표의 조판/렌더 차이여서 gold 없이는
# 감지되지 않는다(미커버 구간 역점역 실측: 대부분 수식 전개·표 격자·인쇄 러닝풋).
# 그래서 이 플래그는 "누락을 다 잡는다"가 아니라 "시각자료·표에 내용이 몰려 자동
# 초안이 원문을 온전히 담기 어려운 페이지를 저오탐으로 짚어준다"에 한정한다.
_VISUAL_TYPES = {"image", "cartoon", "chart_graph", "diagram", "table"}
_PAGE_VISUAL_CELL_FRAC = 0.40
_PAGE_MIN_CELLS = 100  # 내용이 거의 없는 페이지는 판단 보류(분모 노이즈 차단)


def _cell_count(el: dict) -> int:
    return sum(1 for ch in "".join(el.get("contents") or [])
              if 0x2800 < ord(ch) <= 0x28FF)


def page_content_risk(braille_elements: list[dict]) -> str | None:
    """페이지 '내용 누락 의심' 고지 문구(없으면 None). gold 없이 런타임 계산.

    셀 출력은 바꾸지 않는다 — 검수 등급과 같은 메타데이터 신호다(KPI 무영향).
    """
    cells_v = cells_t = 0
    for el in braille_elements:
        c = _cell_count(el)
        if el.get("type") in _VISUAL_TYPES:
            cells_v += c
        else:
            cells_t += c
    total = cells_v + cells_t
    if total < _PAGE_MIN_CELLS:
        return None
    frac = cells_v / total
    if frac >= _PAGE_VISUAL_CELL_FRAC:
        return (f"페이지 내용의 약 {frac * 100:.0f}%가 시각자료·표에 있어 자동 초안이 "
                f"원문을 온전히 담지 못할 수 있음 — 직접 검수 권장")
    return None


def annotate(elements: list[dict], sources: dict, decode) -> None:
    """응답 요소 목록에 `review_grade`·`round_trip`을 붙인다(제자리 수정).

    sources: {element_id: 경계 요소} — 원문 대조에 쓴다.
    """
    for el in elements:
        cells = "".join(ch for ch in "".join(el.get("contents") or [])
                        if 0x2800 < ord(ch) <= 0x28FF)
        src = (sources.get(el.get("id")) or {}).get("content") or ""
        g, rt = grade(element_type=el.get("type", "text"), cells=cells,
                      source_text=src, decode=decode,
                      ocr_confidence=el.get("ocr_confidence"))
        el["review_grade"] = g
        if rt is not None:
            el["round_trip"] = round(rt, 3)
