"""#1296 표 칸 한 음절 오독 자리를 R4 로 짚는다(글자째 보여 준다)."""
from uuid import uuid4

from app.ai.quality.quality_checker import QualityChecker
from app.schemas.content import LLMOutput
from app.schemas.layout import BBoxItem, LayoutResult


def _check(misread, ids):
    items = [BBoxItem(element_id=i, type="table", bbox=(0, 0, 10, 10), reading_order=k + 1) for k, i in enumerate(ids)]
    outs = [LLMOutput(element_id=i, corrected_text="표", render_mode="table_grid", routing_tier="STANDARD", processing_time_ms=0)
            for i in ids]
    return QualityChecker().check("p_001", layout_result=LayoutResult(page_id="p_001", elements=items),
                                  llm_outputs=outs, misread=misread)


def test_표_요소에_R4_를_달고_쪽은_검토_필요다():
    a, b = uuid4(), uuid4()
    report = _check({str(a): ["한정{별→벌}주장"]}, [a, b])
    flags = [f for f in report.review_flags if f.type == "R4"]
    assert [f.element_id for f in flags] == [str(a)]
    assert flags[0].message == "표 칸 글자가 원본과 다름(오독 의심, {우리→원본}): 한정{별→벌}주장"
    assert report.status == "NEEDS_REVIEW"
    assert _check({}, [a, b]).status == "COMPLETED"


def test_넷_넘으면_셋만_보이고_나머지는_수로():
    a = uuid4()
    spots = ["한정{별→벌}주장", "한성{힘→함}락함", "표로{쓰→쑨}원등", "갈등{촉→측}면을"]
    msg = [f for f in _check({str(a): spots}, [a]).review_flags if f.type == "R4"][0].message
    assert msg.endswith("한정{별→벌}주장 · 한성{힘→함}락함 · 표로{쓰→쑨}원등 외 1곳")


def test_이_쪽에_없는_요소에는_달지_않는다():
    a = uuid4()
    assert not [f for f in _check({str(uuid4()): ["한정{별→벌}주장"]}, [a]).review_flags if f.type == "R4"]


# ── B3: 추출이 고친 자리도 R4 를 지우지 않고 '고침' 문구로 남긴다 ─────────────────────

def _check_fixed(misread, fixed, ids):
    items = [BBoxItem(element_id=i, type="table", bbox=(0, 0, 10, 10), reading_order=k + 1) for k, i in enumerate(ids)]
    outs = [LLMOutput(element_id=i, corrected_text="표", render_mode="table_grid", routing_tier="STANDARD", processing_time_ms=0)
            for i in ids]
    return QualityChecker().check("p_001", layout_result=LayoutResult(page_id="p_001", elements=items),
                                  llm_outputs=outs, misread=misread, table_fixed=fixed)


def test_고친_자리는_R4_고침_문구로_남는다():
    a = uuid4()
    report = _check_fixed({}, {str(a): ["한성{힘→함}락함"]}, [a])
    flags = [f for f in report.review_flags if f.type == "R4"]
    assert [(f.element_id, f.message) for f in flags] == [
        (str(a), "표 칸 글자를 원본으로 고침({고치기 전→고친 뒤}): 한성{힘→함}락함")]
    assert report.status == "NEEDS_REVIEW"


def test_고친_자리와_못_고친_자리가_같이_있으면_R4_하나에_둘_다():
    a = uuid4()
    flags = [f for f in _check_fixed({str(a): ["한정{별허→벌하}자주"]}, {str(a): ["한성{힘→함}락함"]}, [a]).review_flags
             if f.type == "R4"]
    assert len(flags) == 1
    assert flags[0].message == ("표 칸 글자를 원본으로 고침({고치기 전→고친 뒤}): 한성{힘→함}락함"
                                " / 표 칸 글자가 원본과 다름(오독 의심, {우리→원본}): 한정{별허→벌하}자주")
