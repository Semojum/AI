"""수식 경로의 원문자 자모 `\\textcircled{7}`(㉠ 오독)도 제64항대로 ⠶…⠶ 로 감싼다.

「한국 점자 규정」 제64항(재추출 2566~2567행) "그 밖의 동그라미 문자는 7 7으로 … 묶어 나타낸다", 예 2573~2574행
㉠ = `7=a7` = ⠶⠿⠁⠶. 유니코드 ㉠ 경로는 이미 이 꼴을 내는데 수식 경로만 ⠿⠁ 였다.
"""
import pytest

from app.ai.braille.kor_math_rules import convert_latex
from app.ai.braille.translator import translate_tagged_text


@pytest.mark.parametrize("arg,cells", [("7", "⠶⠿⠁⠶"), ("T", "⠶⠿⠁⠶"), ("L", "⠶⠿⠒⠶"), ("E", "⠶⠿⠔⠶"), ("B", "⠶⠿⠂⠶")])
def test_수식_경로_원문자_자모는_감싼다(arg, cells):
    assert convert_latex(rf"\textcircled{{{arg}}}") == cells


def test_유니코드_경로와_같다():
    assert translate_tagged_text("<!수식>\\textcircled{7}<!/수식>") == translate_tagged_text("㉠")


def test_숫자와_로마자는_종전대로():
    assert convert_latex(r"\textcircled{2}") == "⠼⠆"          # ② 선택지
    assert convert_latex(r"\textcircled{a}") == "⠶⠴⠁⠶"        # ⓐ
