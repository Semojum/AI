"""T36 ②-a — 문장 속 이온 표기(과학 점자 제2항 [붙임] · 제4항).

종전: 줄 머리 이온 `Na⁺이 세포 밖으로` 에 로마자표가 빠짐 · `HCO₃⁻는` 을 대문자 단어표로 · MinerU 의
`$\\mathrm{Na}^{+}$` · `$Na^{+}-K^{+}$`(Na⁺-K⁺ 펌프)를 수식으로(두 칸 + 빼기 ⠔).
2027 gold 생명과학: `⠴⠠⠝⠁⠘⠢⠤⠠⠅⠘⠢` · `세포 밖 ⠴⠠⠅⠘⠢ 농도` · `⠴⠠⠠⠠⠓⠉⠕⠰⠼⠉⠘⠔⠠⠄`.
"""
from app.ai.braille.translator import translate_body


def _b(text: str) -> str:
    return translate_body(text)[0][0]


def test_구절표_이온은_규정_예문과_같다():
    # 재추출 4350행 `HCO₃⁻는 중탄산 이온이다.` = 0,,,hco;#c^9,'4cz`…
    assert _b("HCO₃⁻는 중탄산 이온이다.").startswith("⠴⠠⠠⠠⠓⠉⠕⠰⠼⠉⠘⠔⠠⠄⠲⠉⠵⠀")


def test_줄_머리_이온도_문장_속이면_로마자표():
    assert _b("Na⁺이 세포 밖으로").startswith("⠴⠠⠝⠁⠘⠢⠀⠕")
    assert _b("Na⁺") == "⠠⠝⠁⠘⠢"                         # 홀로 쓴 이온은 ⠴ 없음(규정 ,h^5)


def test_로만체와_붙임표_이온():
    assert "⠘⠁⠁⠀⠴⠠⠝⠁⠘⠢⠀⠉⠿⠊⠥" in _b("세포 밖 $\\mathrm{Na}^{+}$ 농도")
    assert _b("$Na^{+} - K^{+}$ 펌프").startswith("⠴⠠⠝⠁⠘⠢⠤⠠⠅⠘⠢⠀⠙⠎⠢⠙⠪")
    assert _b("Na⁺-K⁺ 펌프는").startswith("⠴⠠⠝⠁⠘⠢⠤⠠⠅⠘⠢⠀")


def test_수식은_그대로():
    assert "⠘⠔⠭⠔⠼⠃" in _b("$y=|2^{-x}-2|$이다")
