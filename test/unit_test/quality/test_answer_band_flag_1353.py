"""#1353 정답 띠 표에서 번호 · 답 짝을 못 지었으면 R4 로 짚는다(답이 틀리거나 빠진다)."""
from uuid import uuid4

from app.ai.quality.quality_checker import QualityChecker
from app.schemas.content import ExtractedContent, LLMOutput
from app.schemas.layout import BBoxItem, LayoutResult

# 생활과 윤리 해설 p9 실물. 묵자는 `01 ①  02 ③  03 ④  04 ③  05 ②  06 ④  07 ⑤  08 ①` 인데 원문자가 벗겨지고 05 · 06 이 빠졌다.
UNPAIRED = ("<table><tr><td>수능</td><td>기본</td><td>문제</td><td></td><td></td><td></td><td>본문 35~36쪽</td></tr>"
            "<tr><td>01</td><td>1</td><td>02</td><td>3</td><td>03</td><td>4</td><td>04</td></tr>"
            "<tr><td>07</td><td>5</td><td>08</td><td>1</td><td></td><td></td><td></td></tr></table>")
# 동아시아사 해설 p36 실물. 짝을 지어 정답 상자로 나간다.
PAIRED = ("<table><tr><td colspan=\"5\">수능 기본 문제</td><td>본문 136~137쪽</td></tr>"
          "<tr><td>01 ④</td><td>02 ⑤</td><td>03 ②</td><td>04 ③</td><td>05 ②</td><td>06 ①</td></tr>"
          "<tr><td>07 ①</td><td>08 ③</td><td></td><td></td><td></td><td></td></tr></table>")


def _check(html):
    a = uuid4()
    rep = QualityChecker().check(
        "p_001",
        layout_result=LayoutResult(page_id="p_001", elements=[BBoxItem(element_id=a, type="table", bbox=(0, 0, 10, 10), reading_order=1)]),
        extracted=[ExtractedContent(element_id=a, corrected_text=html, ocr_confidence=0.95)],
        llm_outputs=[LLMOutput(element_id=a, corrected_text="표", render_mode="table_grid", routing_tier="STANDARD", processing_time_ms=0)])
    return rep, [f for f in rep.review_flags if f.type == "R4"], str(a)


def test_짝_못_지은_정답_띠는_R4_와_검토_필요():
    rep, r4, a = _check(UNPAIRED)
    assert [(f.element_id, f.message) for f in r4] == [
        (a, "정답 띠의 번호와 답을 짝짓지 못했습니다(원문자가 숫자로 바뀌거나 답이 빠졌을 수 있음). 원본의 답과 대조가 필요합니다")]
    assert rep.status == "NEEDS_REVIEW"


def test_짝_지은_정답_띠는_달지_않는다():
    rep, r4, _ = _check(PAIRED)
    assert not r4
    assert rep.status == "COMPLETED"


def test_띠_머리_없는_표는_달지_않는다():
    rep, r4, _ = _check(UNPAIRED.replace("본문 35~36쪽", ""))
    assert not r4
    assert rep.status == "COMPLETED"
