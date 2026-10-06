"""영어 보기 표지 `(a)` · 동그라미 로마자 ⓐ~ⓩ 역점역.

보기 표지는 EBAE 소괄호 ⠶ 가 여닫이 같은 셀이고, b 이후 홑 낱자 앞엔 낱자표 ⠰ 가 선다.
동그라미 로마자는 규정 `70a7`(⠶⠴⠁⠶) 꼴이다(translator._CIRCLED 가 정본).
기대값은 gold 원문 그대로다. 손해 쪽은 gold 전권 두 팔 역점역 대조로 0줄을 확인했다
(temp/n46/bk/dec_cmp.py).
"""
import pytest

from app.utils.braille_back import decode


@pytest.mark.parametrize("br, want", [
    # MS-REF-007 body p0236 — 글상자 속 (a)~(e) 문장을 고르는 선택지
    ("⠀⠀⠼⠆⠀⠶⠁⠶⠂⠀⠶⠰⠉⠶⠂⠀⠶⠰⠑⠶", "  ② (a), (c), (e)"),
    # MS-REF-T25-078 body p0165 — 로마자표로 열고 종료표 뒤 조사
    ("⠴⠶⠁⠶⠂⠀⠶⠰⠃⠶⠲⠝", "(a), (b)에"),
    # 같은 책 body p0119 — 로마자표 바로 뒤엔 ⠰ 없이 쓴다
    ("⠴⠶⠃⠶⠂", "(b),"),
    # HS-REF-007 ans p0128 — 순서 선택지
    ("⠶⠁⠶⠤⠶⠰⠑⠶⠤⠶⠰⠃⠶", "(a)-(e)-(b)"),
    # 같은 책 ans p0045 — 범위, 물결 뒤 표지는 ⠰ 없이 적는다
    ("⠴⠶⠁⠶⠈⠔⠶⠑⠶⠲⠀⠨⠍⠶", "(a)~(e) 중"),
    # 같은 책 ans p0039 — 물음표가 붙은 범위
    ("⠶⠁⠶⠈⠔⠶⠙⠶⠦", "(a)~(d)?"),
])
def test_보기_표지(br, want):
    assert decode(br) == want


@pytest.mark.parametrize("br, want", [
    ("⠶⠴⠛⠶", "ⓖ"),                       # MS-TXT-K0313 body p0172
    ("⠶⠴⠋⠶⠫", "ⓕ가"),                    # EBS-E26-001 body p0160
    ("⠶⠴⠠⠁⠶⠧", "Ⓐ와"),                   # EBS-E26-002 ans p0064
])
def test_동그라미_로마자(br, want):
    assert decode(br) == want


@pytest.mark.parametrize("br, want", [
    ("⠶⠫⠶", "㉮"),                         # ⠶ 틀 속 한글은 그대로
    ("⠶⠉⠶⠵", "㉯은"),                      # 낱자표 없는 ⠶⠉⠶ 는 ㉯ 다
    ("⠶⠫⠶⠈⠔⠶⠑⠶", "㉮~㉲"),                  # 동그라미 한글 범위는 그대로
])
def test_한글_틀은_그대로(br, want):
    assert decode(br) == want
