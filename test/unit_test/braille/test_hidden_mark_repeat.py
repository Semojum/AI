"""숨김표 반복 표기 회귀 — 한국 점자 규정 제57항.

제57항: "숨김표가 여러 개 붙어 나올 때에는 _과 l 사이에 해당 숨김표의 점형을 묵자의
개수만큼 적어 나타낸다."

기대값은 규정 원문(`braille-source/text/규정_텍스트.txt` 제5장 제13절)의 **BRF 예시를
그대로 옮겨** 유니코드로 환산한다 — 우리 출력에서 뽑지 않는다(순환검증 방지).
    김○○ 씨     @o5_00l`,,o
    △△도서관    _++liu,s@v3
백틱은 코퍼스와 달리 규정 문서에서 빈칸이므로 backtick="space"로 읽는다.
"""
import pytest

from app.ai.braille.symbol_rules import symbol_rule_spans
from app.ai.braille.translator import merge_hidden_runs, translate_tagged_text
from app.utils.braille_ascii import ascii_to_unicode


def reg(brf: str) -> str:
    return ascii_to_unicode(brf, backtick="space")


class TestRegulationExamples:
    @pytest.mark.parametrize("text,brf", [
        ("김○○ 씨", "@o5_00l`,,o"),
        ("△△도서관", "_++liu,s@v3"),
    ])
    def test_제57항_예시_전문일치(self, text, brf):
        assert translate_tagged_text(text) == reg(brf)

    def test_묵자_개수만큼_반복(self):
        """래퍼는 하나, 안쪽 점형은 묵자 글자 수만큼."""
        for n in (2, 3, 5):
            out = translate_tagged_text("○" * n)
            assert out == "⠸" + "⠴" * n + "⠇"
            assert len(out) == n + 2          # 래퍼 2셀 + 글자 n셀


class TestScope:
    def test_단독_숨김표는_그대로(self):
        """'여러 개 붙어 나올 때' 조건 — 하나뿐이면 손대지 않는다."""
        assert translate_tagged_text("○") == "⠸⠴⠇"

    def test_떨어져_있으면_합치지_않는다(self):
        out = translate_tagged_text("○ ○")
        assert out.count("⠸⠴⠇") == 2

    def test_서로_다른_숨김표는_합치지_않는다(self):
        """제57항의 '해당 숨김표'가 하나로 정해지지 않는 배열 — 규정 밖."""
        assert translate_tagged_text("○△") == "⠸⠴⠇⠸⠬⠇"

    def test_멱등(self):
        once = merge_hidden_runs("⠸⠴⠇⠸⠴⠇")
        assert merge_hidden_runs(once) == once == "⠸⠴⠴⠇"


class TestRuleTrailSurvives:
    def test_반복형에도_규정_span이_남는다(self):
        """합쳐진 뒤에도 숨김표 규정 근거가 rule_trail에서 사라지지 않아야 한다."""
        src = "○○ 및 △△△"
        spans = symbol_rule_spans(src, translate_tagged_text(src))
        assert len(spans) == 2
        assert {s[2] for s in spans} == {"KBR-6.13.49"}
        assert [s[1] - s[0] for s in spans] == [4, 5]   # ⠸⠴⠴⠇ · ⠸⠬⠬⠬⠇
