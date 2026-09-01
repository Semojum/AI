"""칸이 길면 한 줄에 칸 하나 — 원장 C-30b (2026-08-27 신설).

지침 §3.1.1(1)③: "열 항목이 여러 단어와 문장으로 되어 있어 가로로 풀어 적을 경우 표를
이해하기 어렵다면 번호 체계를 활용하여 풀어 적는다." 규정은 ②(가로 풀어쓰기)와 ③을
**칸 내용 길이**로 가르는데 우리는 열 수만 봤다.

gold 실측(dev-2027 900쪽 표 186개): 행우선 127개 칸당 중앙 25자(p75 36) ·
열우선 59개 칸당 중앙 82자(p25 48) → 임계 40~45자.

★ 축은 바꾸지 않는다. gold 가 어느 축을 레코드로 삼는지는 안 갈렸다(머리행 11 : 첫열 13).
⚠ 기본 끔. 채택은 A/B.
"""
import pytest

from app.ai.braille import table_braille as tb

SHORT = "구분 | 갑 | 을\n키 | 170 | 165\n몸무게 | 60 | 55"
LONG = ("구분 | 전통 사회 | 근대 이후의 사회\n"
        "특징 | " + "가" * 120 + " | " + "나" * 120 + "\n"
        "사례 | " + "다" * 90 + " | " + "라" * 90)


@pytest.fixture(autouse=True)
def _off(monkeypatch):
    monkeypatch.delenv("TABLE_RECORD_ROWS", raising=False)
    monkeypatch.delenv("TABLE_RECORD_MIN_CELL", raising=False)


def _grid(text):
    return [[c.strip() for c in r.split("|")] for r in text.splitlines() if r.strip()]


class TestSwitch:
    def test_기본은_끔(self):
        assert tb.record_rows_enabled() is False
        assert tb._use_record_rows(_grid(LONG)) is False

    def test_켜고_칸이_길면_쓴다(self, monkeypatch):
        monkeypatch.setenv("TABLE_RECORD_ROWS", "1")
        assert tb._use_record_rows(_grid(LONG)) is True

    def test_켜도_칸이_짧으면_안_쓴다(self, monkeypatch):
        """짧은 칸은 규정 ②(가로로 두 칸씩 띄어 풀어 적기)가 맞다."""
        monkeypatch.setenv("TABLE_RECORD_ROWS", "1")
        assert tb._use_record_rows(_grid(SHORT)) is False


class TestShape:
    def test_한_줄에_칸_하나만_적는다(self, monkeypatch):
        """대표 지적(2026-08-26): 한 줄에 긴 칸 둘이 붙어 왼위-오른위로 읽힌다."""
        monkeypatch.setenv("TABLE_RECORD_ROWS", "1")
        lines = tb._render_grid(LONG)
        body = [l for l in lines[1:-1] if l.strip()]
        for l in body:
            assert "⠀⠀⠀⠀" not in l.strip("⠀") or l.count("⠐⠂") <= 1

    def test_행머리가_제목_줄로_선다(self, monkeypatch):
        monkeypatch.setenv("TABLE_RECORD_ROWS", "1")
        lines = tb._render_grid(LONG)
        heads = [l for l in lines if l.startswith("⠀⠀") and not l.startswith("⠀⠀⠀⠀")]
        assert len(heads) == 2            # 특징 · 사례

    def test_축은_안_바꾼다(self, monkeypatch):
        """머리행 이름을 이름표로 쓴다 — 전치하지 않으므로 축 오판 위험이 없다."""
        monkeypatch.setenv("TABLE_RECORD_ROWS", "1")
        out = "\n".join(tb._render_grid(LONG))
        assert tb._translate("전통 사회") in out
        assert tb._translate("특징") in out

    def test_임계는_환경변수로_옮길_수_있다(self, monkeypatch):
        monkeypatch.setenv("TABLE_RECORD_ROWS", "1")
        monkeypatch.setattr(tb, "_RECORD_MIN_CELL", 500.0)
        assert tb._use_record_rows(_grid(LONG)) is False
