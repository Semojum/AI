"""⠼ 한 점형의 두 뜻(수표 ⇄ 영어 약자 ble) 회귀 가드.

**무엇을 지키나**
1. `eng_braille`의 `ble` 셀이 3456점(⠼)이다 — 2356점(⠶)은 `gg` 자리라 같은 dict 안에서
   셀이 겹쳤었다(~2026-07-27).
2. 그래서 생기는 ⠼ 중의성을 `number_sign.py`가 가른다 — 수표 뒤에는 숫자 셀이 온다(제40항).
3. 역점역이 로마자 런 안의 ⠼를 무조건 런 종료(수표)로 읽지 않는다.
4. 규정 패널(`content_rules`)이 영어 낱말 속 ⠼를 수표 규정으로 표시하지 않는다.

**기대값 근거(순환검증 금지)**
- 수표: 「한국 점자 규정」 제40항 — "숫자는 수표 #을 앞세워 적는다"
  (`braille-source/text/규정_텍스트.txt` 1911행). 3 = ⠼⠉.
- ble = 3456점: 규정 제32항(1649행)이 로마자표~종료표 사이를 통일영어점자에 위임하고,
  규정 부록에는 영어 약자표가 없다. UEB 해설이 "the former 'ble' contraction, dots 3456"
  이라고 적어 **EBAE에서 ble = 3456점**임을 명시한다(duxburysystems.com/js-adapting_UEB.asp).
  이 표는 ation·ally와 같은 이유로 EBAE 관행을 따른다(정답 코퍼스가 EBAE형).
  코퍼스 실측도 같은 방향: -ble 낱말 gold 점형 ⠼형 133 : ⠶형 0(val 116:0 · dev 17:0).
- 셀 충돌 전수 점검·실측 재현 스크립트: `V2/temp/i2_cellaudit.py` · `i2_wordshape.py` ·
  `i2_romanctx.py`.
"""
from __future__ import annotations

from app.ai.braille import eng_braille
from app.ai.braille.number_sign import (
    contraction_lookalikes,
    has_number_sign,
    number_sign_indices,
)
from app.ai.braille.text_braille import content_rules
from app.utils.braille_back import decode

NS = "⠼"


class TestBleCell:
    def test_ble_is_dots_3456(self):
        assert eng_braille.STRONG_GROUPS["ble"] == NS
        assert ord(NS) - 0x2800 == 0b111100        # 점 3·4·5·6

    def test_gg_keeps_dots_2356(self):
        assert eng_braille.STRONG_GROUPS["gg"] == "⠶"
        assert ord("⠶") - 0x2800 == 0b110110       # 점 2·3·5·6

    def test_no_duplicate_cell_inside_strong_groups(self):
        """같은 dict·같은 위치 계층에서 셀이 겹치면 오류다 (ble/gg 재발 방지)."""
        seen: dict[str, str] = {}
        dups = []
        for key, cell in eng_braille.STRONG_GROUPS.items():
            if cell in seen:
                dups.append((seen[cell], key, cell))
            seen[cell] = key
        assert dups == []

    def test_contracted_words(self):
        # 낱말 첫머리에는 못 쓰고(ble→b·l·e), 그 밖에는 한 셀로 줄인다
        assert eng_braille.translate_word("able") == "⠁" + NS
        assert eng_braille.translate_word("possible") == "⠏⠕⠎⠎⠊" + NS
        assert eng_braille.translate_word("problem") == "⠏⠗⠕" + NS + "⠍"


class TestNumberSignIndices:
    def test_number_sign_needs_digit_cell_after(self):
        # 3 = ⠼⠉ (제40항)
        assert number_sign_indices("⠼⠉") == [0]

    def test_ble_cell_is_not_number_sign(self):
        # possible = ⠏⠕⠎⠎⠊⠼ — ⠼ 뒤가 낱말 끝
        assert number_sign_indices("⠏⠕⠎⠎⠊⠼") == []
        # problem = ⠏⠗⠕⠼⠍ — ⠼ 뒤가 알파벳 셀
        assert number_sign_indices("⠏⠗⠕⠼⠍") == []
        # possible. = ⠏⠕⠎⠎⠊⠼⠲ — ⠲는 제64항 내림 숫자 4와 같은 셀이라 특히 주의
        assert number_sign_indices("⠏⠕⠎⠎⠊⠼⠲") == []

    def test_lookalike_counted_from_source(self):
        # assembled = ⠁⠎⠎⠑⠍⠼⠙ — ⠼ 뒤 ⠙가 숫자 4의 셀과 같아 점형만으론 구별 불가
        assert contraction_lookalikes("assembled 부품") == 1
        assert contraction_lookalikes("possible 한 3가지") == 0

    def test_has_number_sign(self):
        assert has_number_sign("3가지", "⠼⠉⠫⠨⠕")
        assert not has_number_sign("possible 한 3가지", "⠴⠏⠕⠎⠎⠊⠼⠲⠀⠚⠒⠀⠉⠫⠨⠕")
        assert has_number_sign("possible 한 3가지", "⠴⠏⠕⠎⠎⠊⠼⠲⠀⠚⠒⠀⠼⠉⠫⠨⠕")


class TestContentRulesSpans:
    def test_ble_cell_not_tagged_as_number_rule(self):
        lines = ["⠴⠏⠕⠎⠎⠊⠼⠲⠀⠚⠒⠀⠼⠉⠫⠨⠕"]      # possible 한 3가지
        spans = [r for r in content_rules("possible 한 3가지", lines) if r.tag == "number_sign"]
        assert len(spans) == 1                       # 진짜 수표(3의 ⠼) 하나만

    def test_plain_number_still_tagged(self):
        spans = [r for r in content_rules("3가지", ["⠼⠉⠫⠨⠕"]) if r.tag == "number_sign"]
        assert len(spans) == 1


class TestRomanRunDecode:
    """역점역: 로마자 런 안의 ⠼를 뒤 셀로 가른다 (제35항 A4·MP3는 수표)."""

    def test_ble_word_survives(self):
        assert decode("⠴⠁⠼⠲") == "able"            # 로마자표 + a + ble + 종료표
        assert decode("⠴⠞⠁⠼⠎⠲") == "tables"

    def test_roman_then_number_still_number(self):
        assert decode("⠴⠠⠁⠼⠙") == "A4"             # 제35항 — 종료표 없이 숫자
        assert decode("⠴⠠⠠⠍⠏⠼⠉") == "MP3"
