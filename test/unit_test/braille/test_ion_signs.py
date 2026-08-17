"""깨진 이온 전하 부호 복원 (2026-08-17).

한컴 수식 폰트가 위첨자 +/− 를 ±·— 로 매핑해 깨뜨린다. 복원 전에는 위첨자표가
통째로 사라져 H⁺가 ⠠⠓⠢⠔(플러스마이너스)로 나갔다.

기대값은 「한국 점자 규정」 과학점자 제2항 원문 예시에서 옮겼다.
    H+       ,h^5
    SO4²⁻    ,s,o;#d^#b9
    HCO3⁻    ,,hco;#c^9
"""
import pytest

from app.ai.braille.translator import _restore_ion_signs, translate_tagged_text


@pytest.mark.parametrize("raw,expected", [
    ("Na±", "Na⁺"),
    ("H±", "H⁺"),
    ("K±의 이동", "K⁺의 이동"),
    ("Rh±, B형", "Rh⁺, B형"),
    ("Ca²`±", "Ca²⁺"),      # 가수 2 — 위첨자 숫자와 좁은 공백(백틱)을 건너뛴다
    ("HCO₃—", "HCO₃⁻"),     # 아래첨자 뒤 위첨자 마이너스
    ("Rh—형", "Rh⁻형"),
])
def test_원소기호_뒤_부호는_위첨자로_복원된다(raw, expected):
    assert _restore_ion_signs(raw) == expected


@pytest.mark.parametrize("raw", [
    "75±",                  # 다른 교재에서 ±는 도(°)다 — 숫자 뒤는 건드리지 않는다
    "x = 3 ± 2",            # 진짜 플러스마이너스
    "a ± b",
    "이것은 — 줄표다",         # 본문 줄표
    "GDP — 국내총생산",
    "A–B",                  # en dash(유전자형 A–)는 대상이 아니다
])
def test_이온이_아닌_자리는_안_건드린다(raw):
    assert _restore_ion_signs(raw) == raw


@pytest.mark.parametrize("text,expected", [
    ("H⁺", "⠠⠓⠘⠢"),         # 홀로 쓴 이온 — 규정 ,h^5 (로마자표 없음)
    ("Na⁺", "⠠⠝⠁⠘⠢"),
    ("Rh⁻", "⠠⠗⠓⠘⠔"),       # - 기호는 9 = ⠔
])
def test_규정_예시대로_점역된다(text, expected):
    assert translate_tagged_text(text) == expected


def test_문장_속_이온은_로마자표를_앞세우고_한_칸_띄운다():
    """규정 예시: 수소가 전자를 잃으면 H+가 된다 = …0[e*`0,h^5`$`iy3i4

    백틱이 한 칸이므로 이온 앞뒤가 각각 **한 칸**이고, 제11항의 두 칸이 아니다
    (제2항 [붙임] "이온 표시 뒤에는 로마자 종료표 없이 한 칸 띄어 쓴다").
    """
    got = translate_tagged_text("잃으면 H±가 된다.")
    assert "⠴⠠⠓⠘⠢⠀⠫" in got, got
    assert "⠀⠀" not in got, got          # 두 칸이 끼면 안 된다
    assert "⠘⠢⠲" not in got, got         # 로마자 종료표를 붙이지 않는다


def test_깨진_입력이_규정_점형까지_간다():
    """복원 전에는 ⠠⠓⠢⠔(위첨자표 없음)로 나갔다."""
    assert translate_tagged_text("Na±") == translate_tagged_text("Na⁺")
