"""로마자 구간의 끝 — 「한글 점자」 제35·36항 (원장 R-69 · 이슈 #625).

규정 원문(`braille-source/text/한국 점자 규정_재추출.txt`)에서 그대로 옮긴 예문이다.

* **제35항**(1720행) "로마자와 숫자가 이어 나올 때에는 로마자 종료표를 적지 않는다."
  종료표가 없으니 뒤에 나오는 ⠲ 는 **마침표**인데 `_roman_span_ahead` 가 그걸
  종료표로 보고 구간을 이어 붙여 숫자 뒤 한글을 로마자로 읽었다.
* **제36항**(1753행) 로마 숫자 범위 `v-x`. 붙임표 ⠤ 가 런을 끊어 뒤의 `⠰⠭`
  (문자표+x)가 한글 `촉` 으로 떨어졌다. 제32항(1650행)이 로마자표와 종료표 **사이**를
  「통일영어점자」로 적으라 하므로 그 구간의 ⠤ 는 하이픈이다.

가드도 함께 지킨다 — 좁히지 않으면 이미 맞던 자리를 깬다(전권 실측).
"""
from __future__ import annotations

import pytest

from app.utils.braille_ascii import ascii_to_unicode
from app.utils.braille_back import decode


def _dec(brf: str) -> str:
    """규정 원문 BRF 한 줄(백틱=빈칸)을 역점역한다."""
    return decode(ascii_to_unicode(brf.replace("`", " "), backtick="space")).strip()


@pytest.mark.parametrize("brf, want", [
    # ── 고치는 자리 ────────────────────────────────────────────────────────
    # 제35항 예문(묵자 1746행 · 점자 1747~1748행)
    ("d};<7`i=@/`u1\"o5doaw`0,,sns4 @/.]z`0pye;g*ang`#bjahoi4",
     "평창 동계 올림픽의 SNS 계정은 pyeongchang 2018이다."),
    # 제36항 예문(묵자 1793행 · 점자 1794행)
    ("@[`;raw`0v-;x4,.x!`o1as`^u,n+4", "그 책의 v-x쪽을 읽어 보세요."),
    # ── 가드 — 바뀌면 안 되는 자리 ─────────────────────────────────────────
    ("0,a#d+7.o", "A4용지"),                                  # 제35항 예문 1724~1725행
    ("#bjbc`jac*iu`,mc{7`0,d-#ajjo1 ja,{b`.)\">a",             # 제35항 예문 1734~1736행
     "2023학년도 수능 D-100일 학습 전략"),
    (",r\"ug`0,,mp#d`,play}4\"!`;&,o jr/i4",                    # 제35항 예문 1731~1733행
     "새로운 MP4 Player를 출시 했다."),
])
def test_로마자_구간의_끝(brf: str, want: str) -> None:
    assert _dec(brf) == want


@pytest.mark.parametrize("cells, want", [
    ("⠴⠧⠤⠰⠭⠲", "v-x"),                       # 제36항 — 붙임표로 이은 로마자
    ("⠴⠠⠉⠓⠑⠉⠅⠤⠥⠏⠲", "Check-up"),            # 붙임표 영어 복합어(전권 최다 이득)
    ("⠴⠠⠠⠊⠊⠊⠤⠼⠑⠉", "Ⅲ-53"),                 # 로마 숫자는 조각마다 되돌린다
    ("⠴⠠⠠⠁⠃⠉⠤⠙⠑⠋⠲", "ABC-def"),             # 대문자 단어표는 붙임표에서 풀린다
    ("⠴⠇⠁⠞⠑⠀⠼⠁⠊⠙⠚⠎⠂⠀⠞⠕⠲", "late 1940s, to"),  # 숫자에 붙는 복수 s 는 수의 일부
    ("⠴⠠⠚⠥⠝⠑⠀⠼⠃⠉⠗⠙⠲", "June 23rd"),          # 서수 접미사도 마찬가지
])
def test_로마자_런_가드(cells: str, want: str) -> None:
    assert decode(cells).strip() == want
