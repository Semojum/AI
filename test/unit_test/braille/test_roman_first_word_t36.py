"""「한글 점자」 제37항 — 로마자표 바로 뒤 영어 낱말은 단어 약자 없이 풀어 적는다. 기대값은 재추출 원문."""
from app.ai.braille.translator import translate_body


def test_로마자표_바로_뒤_낱말은_풀어_적는다():
    # 1843~1844행 `0,can`y`help`me8` — Can 은 풀고 이어지는 you 는 약자
    assert "⠴⠠⠉⠁⠝⠀⠽⠀⠓⠑⠇⠏" in translate_body("그는 Can you help me?라고 도움을 요청했다.")[0][0]
    # 1845~1846행 `0be4cz`
    assert translate_body("be는 am, are, is의 원형 동사이다.")[0][0].startswith("⠴⠃⠑⠲⠉⠵")


def test_아래칸_단어_약자는_문장_부호에_닿으면_풀어_적는다():
    # [붙임] 1847~1850행 `0be1`his1`was1`w]e4w`
    assert translate_body("be, his, was, were의 약자를 바르게 쓰시오.")[0][0].startswith(
        "⠴⠃⠑⠂⠀⠓⠊⠎⠂⠀⠺⠁⠎⠂⠀⠺⠻⠑⠲⠺")
