"""BRF Braille ASCII ↔ 유니코드 변환표 회귀 (역점역 데이터셋 1단계).

표준 64셀 Braille ASCII(소문자=대문자, backtick=공백, 대괄호·캐럿 블록은 시프트형 `{|}~`)를
결정적으로 변환하는지 검증한다. 골드 출처는 규정 예시(regulation_pairs)이며,
완전성(모든 규정 brf_ascii가 [?] 없이 변환됨)을 코퍼스 전수로 확인한다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.utils.braille_ascii import ascii_to_unicode, unicode_to_ascii, _BRAILLE_ASCII

_PAIRS_DIR = Path(__file__).parent.parent.parent / "test_data" / "regulation_pairs"

# 손으로 검증한 골드 (규정 관례) — 표가 어긋나면 즉시 깨진다.
_GOLD = [
    ("vr`ac+8", "⠧⠗⠀⠁⠉⠬⠦"),    # '왜 그러나요?' (backtick=공백)
    ("@ma~u", "⠈⠍⠁⠘⠥"),          # '국보' (~=⠘ 시프트형)
    (",:;{", "⠠⠱⠰⠪"),            # '셔츠' ({=⠪ 시프트형)
    ("#e", "⠼⠑"),                 # 수표+5 (#=수표 ⠼)
    ("0`,0", "⠴⠀⠠⠴"),            # 로마자표/대문자/로마자표 (0=⠴, ,=⠠)
]


class TestTable:
    def test_표는_64셀(self):
        assert len(_BRAILLE_ASCII) == 64
        assert len(set(_BRAILLE_ASCII)) == 64       # 중복 없음(전단사)

    def test_핵심_셀_매핑(self):
        assert ascii_to_unicode("a") == "⠁" and ascii_to_unicode("A") == "⠁"  # 소문자=대문자
        assert ascii_to_unicode("`") == "⠀" and ascii_to_unicode(" ") == "⠀"   # backtick·공백
        assert ascii_to_unicode("~") == "⠘" and ascii_to_unicode("{") == "⠪"   # 시프트 블록
        assert ascii_to_unicode("#") == "⠼"                                     # 수표
        assert ascii_to_unicode("0") == "⠴"                                     # 로마자표

    def test_줄바꿈_보존(self):
        assert ascii_to_unicode("ab\ncd") == "⠁⠃\n⠉⠙"

    def test_백틱_방언(self):
        """백틱 관례가 출처마다 다르다 — 규정=칸 띄우기, 도서 코퍼스=⠈(초성 ㄱ).

        코퍼스를 기본값("space")으로 읽으면 정답에서 ㄱ초성이 통째로 사라진다
        (`ma$` = 국가 → '가'). 회귀로 못 박는다.
        """
        assert ascii_to_unicode("`", backtick="space") == "⠀"
        assert ascii_to_unicode("`", backtick="cell") == "⠈"      # @의 시프트형(0x60↔0x40)
        assert ascii_to_unicode("@") == "⠈"                        # 표준형은 방언 무관
        # 코퍼스 실제 표기: '국가' = `ma$ (백틱=ㄱ초성)
        assert ascii_to_unicode("`ma$", backtick="cell") == "⠈⠍⠁⠫"
        assert ascii_to_unicode("`ma$", backtick="space") == "⠀⠍⠁⠫"   # 잘못 읽으면 ㄱ 소실
        with pytest.raises(ValueError):
            ascii_to_unicode("a", backtick="nope")

    def test_역변환은_표준형_at(self):
        """⠈는 `@`로 역변환한다 — 백틱은 공백 표기와 충돌하므로 쓰지 않는다."""
        assert unicode_to_ascii("⠈") == "@"
        assert unicode_to_ascii("⠈⠍⠁⠫") == "@ma$"

    def test_미지원_글자는_정직한_표시(self):
        assert ascii_to_unicode("§") == "[?§]"        # 64셀 밖 → [?x]
        with pytest.raises(ValueError):
            ascii_to_unicode("§", strict=True)


class TestGoldPairs:
    @pytest.mark.parametrize("brf,unicode", _GOLD)
    def test_손검증_골드(self, brf, unicode):
        assert ascii_to_unicode(brf) == unicode

    def test_역변환_왕복(self):
        # unicode_to_ascii는 시프트형·소문자로 되돌린다(왕복 안정)
        for brf, uni in _GOLD:
            assert ascii_to_unicode(unicode_to_ascii(uni)) == uni


class TestCorpusCompleteness:
    """규정 코퍼스 전수 — 모든 brf_ascii가 [?] 없이 변환되어야 한다(표 완전성)."""

    def test_규정_brf_전수_변환_가능(self):
        broken = []
        for f in sorted(_PAIRS_DIR.glob("section_*.json")):
            for p in json.loads(f.read_text(encoding="utf-8"))["pairs"]:
                out = ascii_to_unicode(p["brf_ascii"])
                if "[?" in out:
                    broken.append((p["korean"], p["brf_ascii"], out))
        assert not broken, f"변환 실패 {len(broken)}건: {broken[:5]}"

    def test_정방향_점역기_교차검증(self):
        """독립 엔진(translate_tagged_text)과 교차검증 — 옛 골드가 ⠛ 누락·z→⠿로 버그였던
        단어들에서 정방향 점역기가 내 ASCII 변환과 일치함을 확인한다(표준 ASCII 표 정당성).
        """
        from app.ai.braille.translator import translate_tagged_text
        # (한국어, brf_ascii) — 옛 braille_unicode가 버그였으나 정방향이 내 변환에 동의한 행들
        cross = [
            ("운동장", "gi=.7"), ("행운", "jr7g"), ("은하수", "zj,m"),
            ("근로", "@z\"u"), ("순두부", ",gim~m"), ("마흔", "ejz"),
        ]
        for kor, brf in cross:
            assert ascii_to_unicode(brf) == translate_tagged_text(kor), kor
