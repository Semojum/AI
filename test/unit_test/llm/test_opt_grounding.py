"""시각 opt 수치 그라운딩 공통화 회귀 (리뷰 후속).

실모델서 이미지 캡션 수치가 변조(3→5)되던 것을 검출하도록 chart 전용이던 R5 검증을
VisualDraftOpt 공통(GROUND_NUMBERS)으로 끌어올림. 이미지·차트=on, 만화=off.
"""
from __future__ import annotations

from uuid import uuid4

from app.ai.llm.base_opt import numbers_grounded
from app.ai.llm.chart_graph_opt import ChartGraphOpt
from app.schemas.content import Draft, ExtractedContent


def _draft(text: str) -> Draft:
    return Draft(option=1, text=text, render_mode="narrative", label="x")


def _ext(caption: str) -> ExtractedContent:
    return ExtractedContent(element_id=uuid4(), corrected_text=caption, ocr_confidence=0.5)


class TestNumbersGrounded:
    def test_전부_보존(self):
        assert numbers_grounded("3과 100", "값은 3, 그리고 100")

    def test_누락_검출(self):
        assert not numbers_grounded("3", "값은 5")

    def test_소수_보존(self):
        assert numbers_grounded("21.6", "비율 21.6%")


# 이미지는 §6.3 rule-based 골격 + 설명문 2안으로 전환됨(_post_process 대신 _optimize_one에서
# numbers_grounded로 R5 표시). 골격 회귀는 test_image_skeleton.py 참조.


class TestChartGrounding:
    def test_차트_수치누락_R5(self):
        ext = _ext("980권, 1100권")
        ChartGraphOpt()._post_process(ext, "980권, 1100권", [_draft("980권만 언급")])
        assert "R5" in ext.flags


# 만화는 VisualDraftOpt가 아니라 rule-based 골격(§5.3) 조립으로 전환됨(수치 그라운딩 비대상).
# 만화 골격 회귀는 test_cartoon_skeleton.py 참조.
