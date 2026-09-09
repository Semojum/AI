"""직선 큰따옴표 여닫이(제49항) · 나열 쉼표 vs 자릿점(제41항).

둘 다 **braillify 가 문맥을 안 보는 자리**를 우리가 갈라 주는 규칙이라, 외부
라이브러리를 올리면 조용히 되돌아갈 수 있다. 여기서 그 상태를 못 박는다.

  · 제49항 (`한국 점자 규정_재추출.txt` 2148~2149행)
      여는 큰따옴표 “ = `8`(⠦) · 닫는 큰따옴표 ” = `0`(⠴)
    추출(MinerU·Opus)이 곡선 따옴표를 직선 `"` 로 평탄화해 오면 braillify 는 늘
    여는 쪽 ⠦ 을 낸다 — 닫는 자리가 전부 틀린다.
  · 제41항 (같은 파일 1939행)
      "숫자 사이에 **붙어 나오는** 쉼표와 자릿점은 `1`(⠂)으로 적는다."
    braillify 는 '붙어'를 안 봐서 `1274, 1281` 의 나열 쉼표까지 자릿점으로 삼켰다.
    제43항(1956행)이 자릿점이면 뒤 숫자에 수표를 다시 안 적는다고 하므로,
    빈칸과 수표가 따라오는 그 출력은 그 자체로 자기모순이었다.
"""
from app.ai.braille.translator import translate_with_breaks

OPEN_DQ, CLOSE_DQ = "⠦", "⠴"
DIGIT_COMMA, LIST_COMMA = "⠂", "⠐"


def _line(text: str) -> str:
    return translate_with_breaks(text)[0][0]


# ── 제49항 큰따옴표 ────────────────────────────────────────────────────────
def test_closing_straight_quote_is_close_cell():
    out = _line('그는 "그렇다"고 답했다.')
    assert out.startswith("⠈⠪⠉⠵⠀" + OPEN_DQ)
    # ⚠ ⠴ 는 한글 셀과 겹친다('렇' = ⠐⠎⠴) — 개수로 세면 안 되고 자리로 본다.
    assert out == "⠈⠪⠉⠵⠀⠦⠈⠪⠐⠎⠴⠊" + CLOSE_DQ + "⠈⠥⠀⠊⠃⠚⠗⠌⠊⠲"


def test_question_mark_then_closing_quote_is_not_two_question_marks():
    # `있소?"` 가 ⠦⠦(물음표 둘) 로 나가면 읽는 쪽이 틀리게 읽는다.
    out = _line('"있소?" 하고 물었다.')
    assert "⠦⠴" in out and "⠦⠦" not in out


def test_nested_quotes_keep_both_pairs():
    out = _line('그는 "\'배열\'이 낫다"고 했다.')
    assert "⠦⠠⠦" in out                    # 여는 큰 + 여는 작은
    assert "⠴⠄" in out                     # 닫는 작은
    assert out.count(CLOSE_DQ) >= 1


# ── 제41항 자릿점 ↔ 나열 쉼표 ──────────────────────────────────────────────
def test_thousands_separator_stays_digit_comma():
    assert _line("1,000명이 넘었다").startswith("⠼⠁" + DIGIT_COMMA + "⠚⠚⠚")
    assert _line("1,234,567원").startswith("⠼⠁⠂⠃⠉⠙⠂⠑⠋⠛")


def test_list_comma_between_numbers_is_sentence_comma():
    out = _line("원 간섭기(1274, 1281)에")
    assert "⠼⠁⠃⠛⠙" + LIST_COMMA + "⠀⠼⠁⠃⠓⠁" in out
    assert DIGIT_COMMA not in out


def test_decimal_point_survives_list_comma_split():
    # 소수점 ⠲(제48항)은 그대로, 나열 쉼표만 ⠐.
    assert _line("3.14, 2.71") == "⠼⠉⠲⠁⠙" + LIST_COMMA + "⠀⠼⠃⠲⠛⠁"


def test_english_run_keeps_ueb_comma():
    """영문 구간의 쉼표는 영어 점자 ⠂ 그대로 — gold 외국어 val p007 실측."""
    out = _line("On January 10, 1992, a travel")
    assert "⠼⠁⠚" + DIGIT_COMMA in out          # 10, → ⠂ (영어 점자 쉼표)
    assert "⠼⠁⠚" + LIST_COMMA not in out
