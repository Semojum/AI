"""꼬리말(TranslateText) 의 로마숫자 — 본문과 규칙이 다르다.

꼬리말은 **한국어 문서의 한 조각**이라 그 안에 한글이 없어도 제29항의 로마자표 ⠴ 를
붙인다. 섹션번호 낱자형 관행도 여기서는 끈다. 근거는 gold 페이지행 실측이다.
  · '로마숫자 + 숫자' 꼬리말 5,318건 중 로마자표를 붙인 것 4,776건(89.8%)
  · 로마숫자 토큰 형태 — 로마자표형 5,762 : 낱자형 466 (92.5%)
본문 경로는 바뀌지 않는다(문턱값 0.2 는 따로 측정된 값).
"""
from app.ai.braille.translator import translate_plain, translate_tagged_text


def test_한글이_없어도_로마자표를_붙인다():
    # gold 페이지행 실물과 같은 값
    assert translate_plain("Ⅱ. 05") == "⠴⠠⠠⠊⠊⠲⠀⠼⠚⠑"


def test_숫자가_이어지면_종료표는_안_붙인다():
    # 제35항 — 예시 `LP 1장` 이 공백을 사이에 두고도 종료표를 안 적는다.
    assert translate_plain("Ⅱ 05") == "⠴⠠⠠⠊⠊⠀⠼⠚⠑"


def test_한글이_이어지면_종료표를_붙인다():
    assert translate_plain("IV 단원").startswith("⠴⠠⠠⠊⠧⠲")


def test_본문은_섹션번호_관행을_그대로_쓴다():
    # 줄머리 + 마침표 = 섹션번호. 본문에서는 낱자형이 관행이다(로마자표 없음).
    assert translate_tagged_text("Ⅱ. 세포와 에너지").startswith("⠠⠊⠊⠲")


def test_한글_꼬리말은_바뀌지_않는다():
    # 「점자 도서 제작 지침」 [예 1-8] 실물
    assert translate_plain("머리말") == "⠑⠎⠐⠕⠑⠂"
