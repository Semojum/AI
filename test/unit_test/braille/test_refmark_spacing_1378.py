"""참고표 ※ 앞뒤 한 칸(#1378). 「한국 점자 규정」 제60항(재추출 2533행): 별표(*)와 참고표(※)는 ⠐⠔ 으로 적고
앞뒤를 한 칸씩 띄어 쓴다. [다만 2](2537행) 주석을 가리키는 별표는 묵자를 따른다 — 별표는 건드리지 않는다.
"""
from app.ai.braille.translator import translate_tagged_text

REF = "⠐⠔"   # 제60항 `"9`


def test_묵자가_붙여_쓴_참고표도_앞뒤를_띄운다():
    assert "⠀" + REF + "⠀" in translate_tagged_text("정답※은 해설 참조")
    assert translate_tagged_text("※당류: 설탕류").startswith(REF + "⠀")      # gold 화작 p0126 도 띄운다
    assert translate_tagged_text("제시문※").endswith("⠀" + REF)


def test_줄머리_여는_괄호_뒤는_붙인다():
    assert translate_tagged_text("※ 다음 물음에").startswith(REF + "⠀")
    assert "⠦⠄" + REF + "⠀" in translate_tagged_text("(※ NASA에 따르면)")    # gold 언매 p0182 `(※ NASA`


def test_별표는_묵자를_따른다():
    # [다만 2] 예문 `모티프*를` 은 붙여 적는다.
    assert REF + "⠐⠮" in translate_tagged_text("모티프*를 따와")
