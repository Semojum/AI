"""#1275 점역 못 한 요소의 점자 칸에는 점자만 싣고, 검토 표시(R1)를 붙인다.

자리표시 `[처리 불가: …]` 를 점자 칸에 한글 그대로 실으면 BRF 로 못 옮겨, BE 가 내려받는 .brf 에 `⟨XXXX⟩` 마커가
찍혔다(2027 동아시아사 2줄). 점자 칸은 점역자 주 꼴 '점역 못 함', 까닭은 묵자 창과 R1 로 본다(pm 10-10 결정).
"""
from uuid import uuid4

from app.ai.braille import isolation
from app.ai.braille.constants import KOREAN_GRADE1
from app.ai.braille.table_braille import TableBraille
from app.ai.braille.visual_braille import _to_braille
from app.ai.quality.quality_checker import QualityChecker
from app.schemas.content import BrailleOutput, LLMOutput
from app.schemas.layout import BBoxItem, LayoutResult


def _braille_only(lines) -> bool:
    return all("⠀" <= c <= "⣿" for c in "".join(lines))


def _opt(text: str) -> LLMOutput:
    return LLMOutput(element_id=uuid4(), corrected_text=text, render_mode="text_only",
                     routing_tier="ZERO", processing_time_ms=0)


def test_점역_못_한_요소는_점자_칸에_점자만_싣는다():
    def boom(_o):
        raise ValueError("Invalid character")
    out = isolation.safe_translate([_opt("౽࿒ཱ࿒໙")], boom)[0]
    assert isolation.is_blocked_braille(out.braille_lines)
    assert _braille_only(out.braille_lines) and out.braille_lines[0].startswith("⠠⠄")   # 점역자 주 표
    assert out.rule_trail                                                               # 불변 규칙 2


def test_표_시각_자리표시도_점자로_바뀐다():
    tb = TableBraille().translate([_opt("[표 수동 입력 필요]")])[0]
    assert isolation.is_blocked_braille(tb.braille_lines) and _braille_only(tb.braille_lines)
    lines, _ = _to_braille("[처리 불가: 이미지 경로 없음]")
    assert isolation.is_blocked_braille(lines) and _braille_only(lines)


def test_정자_문맥에서_적은_꼴도_알아본다():
    tok = KOREAN_GRADE1.set(True)
    try:
        g1 = isolation.blocked_braille()
    finally:
        KOREAN_GRADE1.reset(tok)
    assert g1 != isolation.blocked_braille()
    assert isolation.is_blocked_braille([g1]) and isolation.is_blocked_braille([isolation.blocked_braille()])
    assert isolation.is_blocked_braille(["[처리 불가: 점역 오류]"])                     # 옛 꼴도
    assert isolation.is_blocked_braille(["⠀⠀[처리 불가: 점역 오류]"])                 # 조판이 들인 줄도(종전 검사기가 놓침)
    assert isolation.is_blocked_braille(["⠀⠀⠀⠀" + isolation.blocked_braille()])
    assert not isolation.is_blocked_braille(["⠠⠄⠈⠪⠐⠕⠢⠠⠄"])                       # 다른 점역자 주는 아니다


def test_점역_못_한_요소에는_C2_와_R1_이_하나씩_붙는다():
    items = [BBoxItem(element_id=uuid4(), type="text", bbox=(0, 0, 10, 10), reading_order=i + 1) for i in range(2)]
    ids = [b.element_id for b in items]
    report = QualityChecker().check(
        "p_001", layout_result=LayoutResult(page_id="p_001", elements=items),
        llm_outputs=[LLMOutput(element_id=ids[0], corrected_text="정상", render_mode="text_only",
                               routing_tier="ZERO", processing_time_ms=0),
                     LLMOutput(element_id=ids[1], corrected_text="[처리 불가: OCR 실패]", render_mode="text_only",
                               routing_tier="ZERO", processing_time_ms=0)],
        braille_outputs=[BrailleOutput(element_id=ids[0], braille_lines=[isolation.blocked_braille()]),
                         BrailleOutput(element_id=ids[1], braille_lines=[isolation.blocked_braille()])],
    )
    for eid in map(str, ids):
        assert [c.type for c in report.critical_errors if c.element_id == eid] == ["C2"]
        assert [r.type for r in report.review_flags if r.element_id == eid and r.type == "R1"] == ["R1"]
    assert report.status == "NEEDS_REVIEW"
