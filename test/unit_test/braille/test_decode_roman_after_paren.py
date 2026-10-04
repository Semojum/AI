"""여는 괄호 바로 뒤 로마자 런 역점역 (#1109, 「한글 점자」 제29항).

제29항(재추출 1496행): 국어 문장 안의 로마자는 낱말 앞에 로마자표 ⠴ 를 적는다.
여는 괄호 뒤도 낱말 앞이다. 기대값은 gold 생활과 윤리(EBS-E26-014) body p0162 의 원문 `(paternalistically)`.
"""
from app.utils.braille_back import decode


def test_괄호_속_영어():
    assert decode("⠦⠄⠴⠏⠁⠞⠻⠝⠁⠇⠊⠌⠊⠉⠁⠇⠇⠽⠠⠴⠀⠚⠗⠶⠍⠗⠚⠗⠠⠎⠉⠵") == "(paternalistically) 행위해서는"


def test_괄호_속_퍼센트는_그대로():
    assert decode("⠦⠄⠴⠏⠠⠴") == "(%)"
