"""B-09(원장) 폰트 사설영역 글리프 — 아는 것은 옮기고 모르는 것은 드러낸다.

pm 결재(2026-08-22): ① 표에 있는 글리프만 말로 옮긴다(지금은 U+E3C4 하나)
② 표에 없는 PUA 는 지우되 세고 그 쪽에 R15 를 세운다 ③ 나머지 매핑은 자문 항목.
근거: 묵자 body 177회 대 gold `(예)` 183회 · EBS-E26-004 body p0013 묵자 8회 = gold 8회.
"""
from app.ai.braille.translator import _PUA_TO_TEXT, dropped_pua, sanitize_for_braille

EXAMPLE = ""      # 언매 예문 아이콘 → (예)
UNKNOWN = ""      # 익명화 숨김표 계열 — 아직 자문 대기라 옮기지 않는다


def test_known_glyph_becomes_word():
    assert sanitize_for_braille(f"{EXAMPLE} 다음 글을 읽고") == "(예) 다음 글을 읽고"
    assert _PUA_TO_TEXT[EXAMPLE] == "(예)"


def test_unknown_glyph_is_not_guessed_but_counted():
    out = sanitize_for_braille(f"{UNKNOWN}사 식당")
    assert UNKNOWN not in out                 # 여전히 지운다
    assert dropped_pua(f"{UNKNOWN}사 식당") == {UNKNOWN: 1}


def test_known_glyph_is_not_counted_as_dropped():
    assert dropped_pua(EXAMPLE) == {}


def test_plain_text_counts_nothing():
    assert dropped_pua("보기 중 옳은 것은?") == {}
