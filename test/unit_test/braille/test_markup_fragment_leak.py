"""마크업 조각이 점자 셀로 나가면 안 된다 (#667).

묵자에 남은 `\\unicode{}`·마크다운 굵게·인라인 HTML 은 글자 그대로 점자가 되면
점역사 눈에 뜻 없는 셀 덩이다. 정답 있는 1,180쪽 전수에서 33건·37쌍·2건이었다.

반대쪽도 같이 지킨다 — 짝 없는 `*` 는 **가리기 표시**라 걷으면 내용이 사라진다.
"""
import re

from app.ai.braille.translator import translate_plain

_LETTERS = {c: chr(ord("a") + i) for i, c in enumerate("⠁⠃⠉⠙⠑⠋⠛⠓⠊⠚⠅⠇⠍⠝⠕⠏⠟⠗⠎⠞⠥⠧⠺⠭⠽⠵")}
_STAR = "⠐⠔"          # 별표 한 개의 점형


def _letters(braille: str) -> str:
    return "".join(_LETTERS.get(c, " ") for c in braille)


def test_unicode_command_becomes_the_character_not_its_name():
    # `\unicode{x24D8}` = ⓘ — 원문자 점형 ⠶⠴⠊⠶ 이 나와야지 "x24d8" 이 나오면 안 된다
    out = translate_plain(r"조건 \unicode{x24D8} 참고")
    assert "⠶⠴⠊⠶" in out
    assert "x24" not in _letters(out)


def test_unicode_command_broken_argument_is_dropped():
    # `x3garbage` 는 못 읽는다 — 글자로 내보내느니 버린다
    assert "garbage" not in _letters(translate_plain(r"식 \unicode{x3garbage} 끝"))


def test_markdown_bold_pair_is_stripped():
    out = translate_plain("**1** ①  **2** ⑤")
    assert _STAR not in out
    assert out.startswith("⠼⠁")          # 굵게 표시만 빠지고 번호는 남는다


def test_unpaired_asterisk_is_masking_and_must_survive():
    # 가리기 표시(코퍼스 11건) — 걷으면 원문 내용이 사라진다
    for src in ("최초 입력 2026. **. **. 06:45",
                "010-*43*-**37로 질문하세요.",
                "이△△ 기자(news***@◎◎.kr)",
                "◇◇◇ (**대, 컴퓨터 공학부)"):
        assert _STAR in translate_plain(src), src


def test_inline_html_tag_is_stripped():
    out = translate_plain("향기로운 MJB<sup>*</sup>의 미각")
    assert "sup" not in _letters(out)


def test_math_inequality_is_not_mistaken_for_a_tag():
    # `<b>` 꼴은 수식 부등호와 겹친다 — 한 글자 태그를 안 다루는 이유
    assert translate_plain("$a<b>c$ 에서") == translate_plain("$a<b>c$ 에서")
    assert "⠔⠔" in translate_plain("$a<b>c$ 에서")     # `<` 가 살아 있다
