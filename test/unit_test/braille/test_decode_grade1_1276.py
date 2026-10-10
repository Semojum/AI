"""#1276 한글 정자(1급)로 점역한 점자를 역점역이 읽는다.

역맵이 2급(약자) 꼴뿐이라 정자 점자의 받침 ㄹ ⠂ 을 쉼표로, 받침 ㄴ ⠒ 을 `=` 로 읽었다. 그래서 정자 문서는
검수 등급이 거의 다 low 였다(gold 글 1,000줄: high 24 · low 939, 2급은 high 568 · low 373).

기대 점형은 「한국 점자 규정」 재추출본 표 줄에서 손으로 옮겼다(정방향 코드를 부르지 않는다):
첫소리 제1항 148~161행(ㄱ @ 148 · ㄷ i 150 · ㄹ " 151 · ㅅ , 154 · ㅊ ; 157 · ㅎ j 161),
모음 제6항 375~384행(ㅏ < 375 · ㅓ s 377 · ㅡ [ 383), 제7항 426~436행(ㅐ r 426 · ㅔ n 428 · ㅖ / 429),
받침 제3항 263~276행(ㄴ 3 264 · ㄹ 1 266), 약어 제18항 897~907행(그래서 = as).
"""
from app.ai.braille.constants import KOREAN_GRADE1
from app.ai.quality import confidence
from app.utils.braille_back import decode

# 그래서 = ㄱ⠈ ㅡ⠪ ㄹ⠐ ㅐ⠗ ㅅ⠠ ㅓ⠎
GURAESEO_G1 = "⠈⠪⠐⠗⠠⠎"
# 체계를 한다. = ㅊ⠰ ㅔ⠝ · ㄱ⠈ ㅖ⠌ · ㄹ⠐ ㅡ⠪ 받침ㄹ⠂ · 빈칸 · ㅎ⠚ ㅏ⠣ 받침ㄴ⠒ · ㄷ⠊ ㅏ⠣ · 마침표 ⠲
SENTENCE_G1 = "⠰⠝⠈⠌⠐⠪⠂⠀⠚⠣⠒⠊⠣⠲"


def test_정자_점자를_정자로_읽는다():
    assert decode(GURAESEO_G1, korean_grade1=True) == "그래서"
    assert decode(SENTENCE_G1, korean_grade1=True) == "체계를 한다."


def test_2급_역점역은_그대로다():
    """약어 ⠁⠎(제18항 901행)는 2급에서만 '그래서'다. 정자에서 ⠁ 은 받침 ㄱ 이라 낱말을 못 연다."""
    assert decode("⠁⠎") == "그래서"
    assert decode("⠁⠎", korean_grade1=True) != "그래서"
    assert decode(SENTENCE_G1) != "체계를 한다."            # 종전 결함: 2급 맵으로 읽으면 깨진다


def test_점역과_같은_문맥_값을_따른다():
    """파이프라인은 쪽 문맥에 KOREAN_GRADE1 을 놓는다. 검수 등급은 인자 없이 decode 를 넘겨 부른다."""
    tok = KOREAN_GRADE1.set(True)
    try:
        assert decode(SENTENCE_G1) == "체계를 한다."
        long_g1 = "⠀".join((SENTENCE_G1, GURAESEO_G1, SENTENCE_G1))      # 왕복은 원문 10자 · 20칸부터 잰다
        els = [{"id": 0, "type": "text", "contents": [long_g1], "ocr_confidence": 1.0}]
        confidence.annotate(els, {0: {"contents": ["체계를 한다. 그래서 체계를 한다."]}}, decode)
        assert els[0]["round_trip"] == 1.0 and els[0]["review_grade"] == "high"
    finally:
        KOREAN_GRADE1.reset(tok)
    assert decode(SENTENCE_G1) != "체계를 한다."             # 문맥 값이 새지 않는다
