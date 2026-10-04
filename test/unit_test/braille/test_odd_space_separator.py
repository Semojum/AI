"""#1067 — 유니코드 공백 구분자(Zs)는 점역 결과 셀열에 남지 않는다. 남으면 BRF 를 못 낸다."""
import pytest

from app.ai.braille.translator import _ODD_SPACE_RE, translate_tagged_text


@pytest.mark.parametrize("text", [
    # 수학 I 원본 58쪽 실물(한컴 글꼴 깨진 글자 포함). 영어 낱말이 섞인 경로가 U+2009 를 옮겼다.
    '참고  그림과 같은 사각형 "#$%에서 두 대각선의 길이가 각각  p, q이고, 두 대각선이 이루는  \n'
    '각의 크기가  D일 때, 사각형 "#$%의 넓이를  S라 하면',
    "넓이를  S라 하면", "길이가　p이다", "a b와 c d",
])
def test_점자_밖_공백이_셀열에_안_남는다(text):
    out = translate_tagged_text(text)
    # Zs 만 본다. 깨진 한컴 글자("#$%)가 든 실물은 앞선 시험이 남긴 전역 상태에 따라 다른 경로로 갈 수 있다
    # (`test_rule_engine.py` 뒤에 돌면 한글이 그대로 남는 폴백을 탄다. 이 PR 과 무관한 기존 동작).
    assert not _ODD_SPACE_RE.search(out), [hex(ord(c)) for c in _ODD_SPACE_RE.findall(out)]


def test_줄_바꿈_없는_공백_뒤_로마자는_로마자_그대로():
    # 입구에서 보통 공백으로 바꾸면 이 `I` 가 수식 경로로 빠져 두 칸 + 종료표 없음이 됐다(2027 경계 383 요소).
    assert translate_tagged_text("생명과학\u00a0I").endswith("⠀⠴⠠⠊⠲")
