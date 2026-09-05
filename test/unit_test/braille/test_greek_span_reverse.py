"""그리스 문자 구간 `⠴…⠲` 역규칙 회귀 가드 (규정 제30·31항).

이 파일이 지키는 것
  1. 로마자표~로마자 종료표로 닫힌 그리스 구간을 그리스 문자로 되돌리는 것.
     종전에는 ⠴ 가 닫는 큰따옴표, ⠨+자음이 한글 약자 '자'로 읽혀 `σ` 가 `”저.` 로
     나갔다(전권 18,892쪽에 이 꼴 279건).
  2. 그 밖의 ⠨+자음은 **여전히 한글**인 것 — 낱말 중간의 ⠴ 나 종료표가 없는 자리에서
     그리스로 읽으면 본문이 깨진다.

**순환검증 금지** — 기대값의 출처
  · 규정 예문: 「한국 점자 규정」 제31항(규정_텍스트.txt 1641~1652행)의 묵자·점자 쌍을
    그대로 넣는다. `통계에서 σ는 …` = ``h=@/n,s`0.s4cz`…`` · `그녀는 ΦΒΚ의 …`.
  · 문자표: 같은 문서 제30항 표(1507~1640행). 소문자 `.x`(⠨+자음) · 대문자 `,.x`(⠠⠨+자음).
  · 코퍼스 실물: EBS-E26-001(생명과학 I) body/p0075·p0095 — 재추출 묵자가 각각
    `이자의 $\\alpha$세포에서` · `응집소는 $\\alpha$와 $\\beta$ 두 종류` 로 적는다.
"""
from __future__ import annotations

from app.utils.braille_ascii import ascii_to_unicode
from app.utils.braille_back import decode


def _brf(s: str) -> str:
    return ascii_to_unicode(s.replace("`", " "), backtick="space")


def test_규정_제31항_소문자_예문():
    # 통계에서 σ는 표준 편차를 의미한다.
    got = decode(_brf("``h=@/n,s`0.s4cz`d+.g`d*;<\"!`weo"))
    assert "σ는" in got
    assert "”" not in got


def test_규정_제31항_대문자_단어표_예문():
    # 그녀는 ΦΒΚ의 회원이다.
    got = decode(_brf("``@{c:cz`0,,.f.b.k4w`jyp3oi4"))
    assert "ΦΒΚ의" in got


def test_코퍼스_알파_베타_세포():
    assert decode("⠕⠨⠣⠺⠀⠴⠨⠁⠲⠠⠝⠙⠥⠝⠠⠎").endswith("α세포에서")
    assert decode("⠕⠨⠣⠺⠀⠴⠨⠃⠲⠠⠝⠙⠥⠝⠠⠎").endswith("β세포에서")


def test_낱자_대문자표():
    assert decode("⠴⠠⠨⠎⠲") == "Σ"          # 제30항 `,.s`


def test_종료표가_없으면_안_편다():
    """제4항으로 종료표를 생략한 표기까지 이으면 한글을 삼킨다 — 안전한 쪽으로 둔다."""
    assert "α" not in decode("⠴⠨⠁⠠⠝⠙⠥")


def test_낱말_중간_로마자표는_그리스가_아니다():
    """낱말 중간의 ⠴ 는 로마자표가 아니라 받침 ㅎ·닫는 따옴표다(제29항)."""
    plain = decode("⠈⠮⠴⠨⠎⠲")
    assert "σ" not in plain


def test_구간_안에_로마자가_섞이면_안_편다():
    """제31항 구간은 그리스만이다 — 로마자가 섞이면 로마자 런이 읽어야 한다."""
    assert decode("⠴⠨⠁⠃⠲") != "α"
