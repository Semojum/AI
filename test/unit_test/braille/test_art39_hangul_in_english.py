"""「한글 점자」 제39항 — 로마자가 주된 문장 속 한글은 한글표 ⠸⠷…⠸⠾ 로 묶는다 (#950).

기대값은 규정 원문(재추출 1890~1905행) BRF 그대로다. 예문 3 은 규정이 머리 로마자표를 뺐고(문단 전체가
로마자 — 제29항 [다만] 생략 가능) 예문 1 은 적었다. 우리는 예문 1 꼴(머리 ⠴)을 따른다 — 그 한 셀만 다르다.
"""
import pytest

from app.ai.braille.translator import translate_body, _english_sentence_with_hangul
from app.utils.braille_ascii import ascii_to_unicode


def _body(text: str) -> str:
    return "".join(translate_body(text)[0])


def test_제39항_예문_1():
    assert _body("What is 김치 in English?") == ascii_to_unicode("0,:at`is`_(@o5;o_)`9`,5gli%8", backtick="space")


def test_제39항_예문_3_머리_로마자표만_다르다():
    want = ascii_to_unicode(",ban*an`\"<,kor1n3`_(~3;<3_)\">`>e`small`side`di%es`s}v$`al;g`)`"
                            "cook$`rice`9`,kor1n`cuis9e4", backtick="space")
    got = _body("Banchan (Korean: 반찬) are small side dishes served along with cooked rice in Korean cuisine.")
    assert got == "⠴" + want


@pytest.mark.parametrize("src", [
    "구분: I(P)  II(Q)  III(P)  IV(P)",          # 한글 머리말 + 목록(2027 실물)
    "유전자형: XY  X'Y  XX  XX'  X'X'",
    "(Grammatical and Ungrammatical Strings)에",  # 영어 인용에 붙은 조사
    "sin B-2 cos A sin C=sin B 또는",             # 수식 줄
    "우리는 English class 를 좋아한다",            # 한국어가 주된 문장
])
def test_제39항_아닌_줄(src):
    assert not _english_sentence_with_hangul(src)
