"""「한글 점자」 제46항 — 연산·비교 기호가 한글 사이에 나오면 앞뒤를 한 칸씩 띄운다 (#938).

기대값은 규정 원문(재추출 2062행) BRF 를 그대로 옮겼다(생산 코드로 만들지 않았다). 제품 본문 경로
`translate_body` 로 잰다. 한 줄짜리 예문만 빈칸까지 대조한다(여러 줄 예문은 줄 끝 채움과 진짜 빈칸이 안 갈린다).
"""
import pytest

from app.ai.braille.translator import translate_body
from app.utils.braille_ascii import ascii_to_unicode


def _body(text: str) -> str:
    return "".join(translate_body(text)[0])


@pytest.mark.parametrize("src,brf", [
    ("나루 + 배 = 나룻배", "c\"m`5`^r`33`c\"m'^r"),   # 묵자에 빈칸이 있다
    ("5개-3개=2개", "#e@r`9`#c@r`33`#b@r"),          # 묵자에 빈칸이 없다 · 뺄셈표 ⠔(제45항)
])
def test_제46항_규정_예문(src, brf):
    assert _body(src) == ascii_to_unicode(brf, backtick="space")


def test_제46항_비교_기호도_띄운다():
    # 규정 예문 `(해왕성>지구>금성)` 의 둘째 줄 `f{i8'jrv7,]\`55\`.o@m\`55\`@{5,],0` 과 같은 꼴
    assert "⠻⠀⠢⠢⠀⠨⠕⠈⠍⠀⠢⠢⠀⠈⠪" in _body("크다(해왕성>지구>금성).")


@pytest.mark.parametrize("src", [
    "3-4쪽",                # 붙임표 — 식이 아니다
    "문항 [26004-0143]",     # 문항코드
    "가-나 대립",
    "Rh+형",                # 로마자 옆
    "변화량은 +2이다",       # 부호
    "<보기>에서",            # 홑화살괄호 묶음
    "<자료 1>은",
    "원자핵이 1+이며",       # 숫자 뒤 전하 부호
    "X는+2d이다",            # 한글 뒤 부호(같은 식에 = 없음) — dev-2027 001 p0020 실물
    "‘바>와’, ‘버>워’",      # 국어 음운 변화 표시 — dev-2027 004 p0135 실물
])
def test_제46항_아닌_자리는_그대로(src):
    from app.ai.braille import translator
    assert translator._space_hangul_operators(src) == src
