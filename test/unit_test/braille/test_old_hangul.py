"""옛한글(중세 국어) 첫가끝 자모 점역 회귀 가드 — 규정 제3장 「옛 글자」.

이 파일이 지키는 것: 완성형으로 조합되지 않는 옛 음절이 **사라지지 않는 것**.
`ᄒᆞ야`(ᄒ + ᆞ + 야)는 braillify가 거부해 _safe_to_unicode의 "변환 불가 글자 제거"가
음절째 지웠다 — 출력이 `야`뿐이었다(2026-09-03 실측). 예외도 플래그도 없는 무성 삭제라
점역사가 원문과 대조하지 않으면 발견할 수 없다.

**순환검증 금지**: 기대값은 두 출처에서만 왔다.
  ① 「한국 점자 규정」제19~25항 — 옛 글자표 ⠐, 아래아 ㆍ=⠐⠼, 반치음 첫소리 ㅿ=⠐⠨,
     순경음 비읍 ㅸ=⠐⠘⠶, 시옷기역 ㅺ=⠐⠠⠈(`braille-source/text/규정_텍스트.txt` 970행~).
  ② 정답 도서 실측 — 언어와 매체 p035 gold `⠑⠂⠠⠠⠐⠼⠑⠕`(말ᄊᆞ미),
     p082 gold `⠠⠱⠐⠘⠶⠮`(셔ᄫᅳᆯ). 코퍼스 27쪽 235런 중 216(91.9%)이 gold와 일치하고,
     남은 19는 묵자 재추출 오독이다(`어드ᄫᅳᆫ`→`ᄫᅩᆫ` 등).
"""
from __future__ import annotations

import pytest

from app.ai.braille.translator import translate_plain


@pytest.mark.parametrize("text, expected", [
    ("말ᄊᆞ미", "⠑⠂⠠⠠⠐⠼⠑⠕"),      # gold 언어 p035 — ㅆ 초성 + 아래아
    ("셔ᄫᅳᆯ", "⠠⠱⠐⠘⠶⠮"),          # gold 언어 p082 — 순경음 ㅸ + 약자 '을'
    ("ᄒᆞ야", "⠚⠐⠼⠜"),               # 초성 ㅎ + 아래아
    ("ᅀᆞᆷ", "⠐⠨⠐⠼⠢"),              # 반치음 첫소리(제19항)
    ("ᄭᅮᆷ", "⠐⠠⠈⠍⠢"),              # gold 언어 p035 — 합용 병서 ㅺ(제22항)
])
def test_old_syllable_keeps_cells(text, expected):
    assert translate_plain(text) == expected


def test_old_jamo_is_not_silently_dropped():
    """음절이 통째로 사라지던 회귀 — 옛 자모 자리에 셀이 있어야 한다."""
    assert translate_plain("ᄒᆞ야") != translate_plain("야")


def test_modern_text_untouched():
    """첫가끝 자모가 없는 줄은 종전 경로 그대로(약자·약어 보존)."""
    assert translate_plain("하늘") == "⠚⠉⠮"
