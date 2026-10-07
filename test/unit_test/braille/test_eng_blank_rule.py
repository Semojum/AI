"""영어 지문 속 밑줄 빈칸 → 통일영어점자 밑줄 ⠨⠤ (이슈 #1170 · 원장 C-05 부록).

「한국 점자 규정」 제7항(재추출 99행)·제28항(1329행)이 로마자를 「통일영어점자 규정」에 맡기고 UEB 밑줄은 ⠨⠤ 다.
제33항(1667행): 쉼표·쌍점·쌍반점은 두 규정 점형이 달라 영어 쪽은 ⠂ · ⠒ · ⠆ 다.
gold 영어책 한글 없는 줄의 빈칸 ⠨⠤ 3,436 : ⠸⠤ 394(그중 369 가 단어장 뜻 칸).

빈칸 앞 첫 낱말에 붙는 로마자표 ⠴…⠲(태그 이름의 한글을 세는 별개 결함)는 이 시험이 단언하지 않는다.
"""
import pytest

from app.ai.braille.translator import translate_body


def _br(text: str) -> str:
    return "".join(translate_body(text)[0])


@pytest.mark.parametrize("text", [
    "she <!밑줄> the room yesterday.",       # 뒤에 영어 낱말
    "what time will bill come? <!밑줄>",     # 앞에 영어 낱말 둘 이상
    "yellow <!밑줄>.",                       # 바로 뒤 문장 부호
    "05 in my mind, the world is <!밑줄>",   # 번호 항목이어도 문장이면 영어 빈칸
])
def test_영어_지문_빈칸은_UEB_밑줄(text):
    out = _br(text)
    assert "⠨⠤" in out and "⠸⠤" not in out, out


def test_빈칸_뒤_쉼표는_UEB_꼴():
    """gold MS-REF-007 body p0209 `___, he tried to climb the tree.` = ⠨⠤⠂⠀⠓⠑…"""
    assert _br("<!밑줄>, he tried to climb the tree.").startswith("⠨⠤⠂⠀⠓⠑")


@pytest.mark.parametrize("text", [
    "humble  <!밑줄>",                       # 단어장 뜻 칸 — gold ⠸⠤(HS-REF-T25-023)
    "07 step forward <!밑줄>",               # 번호 항목 뜻 칸 — gold ⠸⠤(HS-REF-T26-013 body p0059)
    "빈칸 <!밑줄> 에 알맞은 말",              # 한글 줄
    "다음 문장 she <!밑줄> the room. 에서",   # 한글이 섞인 줄은 종전대로
])
def test_한글_꼴_빈칸은_그대로(text):
    out = _br(text)
    assert "⠸⠤" in out and "⠨⠤" not in out, out
