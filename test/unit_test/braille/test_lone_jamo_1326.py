"""#1326 — 홀로 쓴 자음자를 첫가끝 초성(U+1100~)으로 받아도 온표 + 받침꼴로 점역한다(제8항)."""
from app.ai.braille import translator as T


def test_첫가끝_초성으로_쓴_홀로_자음도_온표와_받침꼴이다():
    # 「한국 점자 규정」 제8항 예(재추출 479~480행): `삼각형 ㄱㄴㄷ` = l5$aj}`=a=3=9(규정 BRF 백틱은 빈칸)
    assert T.translate_tagged_text("삼각형 ᄀᄂᄃ") == "⠇⠢⠫⠁⠚⠻⠀⠿⠁⠿⠒⠿⠔"
    # gold 언어와 매체 본책 p0014 `‘ㄴ’ 첨가` — 한컴 글자층은 ㄴ 을 U+1102 로 싣는다(종전 ⠉ = 약자 '나')
    assert T.translate_tagged_text("‘ᄂ’ 첨가").startswith("⠠⠦⠿⠒⠴⠄⠀⠰⠎⠢⠫")


def test_중성이_이어지는_옛한글_초성은_건드리지_않는다():
    for s in ("하ᄂᆞᆯ히", "말ᄊᆞ미", "나"):
        assert T._LONE_CHO_RE.search(s) is None, s
