"""곁단 용어 상자를 §2.4.7 주석으로 적기 — 원장 C-77 (2026-08-27 신설).

지침 §2.4.7: "본문의 특정 영역에 대해서 유도선 등을 이용해 설명하거나 덧붙이는 글상자 등은
주석 표기 방법을 적용할 수 있다." (1) 주석표는 별표(⠐⠔) (4) 주석표 뒤 한 칸 띄고 주석과
설명을 쌍점으로 구분한다.

gold 실측(dev-2027 900쪽): 주석표 ⠐⠔ 110회 · 다른 표시자 1회 · 우리 0회.
⚠ 기본은 **끔**이다 — 곁단이 주석으로 빠지면 글상자 수가 줄어 원장 C-01b 축이 같이 움직인다.
"""
import pytest

from app.ai.preprocessor import pdf_analyzer as pa


def _els():
    """좁은 곁단 상자 하나 — 윗변에 걸친 제목 + 설명 한 문단."""
    return [{"type": "text", "content": "범주화", "bbox": [700, 80, 950, 100]},
            {"type": "text", "content": "여러 사물이나 현상을 묶어 분류하는 과정.",
             "bbox": [700, 140, 950, 260]}]


SIDEBAR = [[690, 90, 960, 280]]      # 폭 270/1000 = 0.27
WIDE = [[50, 90, 950, 400]]          # 폭 900/1000 = 0.90


class TestSwitch:
    def test_기본은_끔이라_글상자_그대로(self, monkeypatch):
        monkeypatch.delenv("SIDEBAR_AS_NOTE", raising=False)
        els = _els()
        assert pa.tag_boxed_elements(els, SIDEBAR) == 1
        assert els[0]["content"].startswith("<!상자>범주화<!/상자>")

    def test_켜면_주석표기로_나간다(self, monkeypatch):
        monkeypatch.setenv("SIDEBAR_AS_NOTE", "1")
        els = _els()
        assert pa.tag_boxed_elements(els, SIDEBAR) == 1
        assert els[0]["content"] == "※ 범주화: 여러 사물이나 현상을 묶어 분류하는 과정."
        assert "<!상자" not in "".join(e["content"] for e in els)


class TestScope:
    def test_본문_폭_상자는_켜도_글상자다(self, monkeypatch):
        """§2.4.7 은 곁단 설명 상자를 겨냥한다. 본문 폭 상자까지 주석으로 돌리면
        지문 상자가 통째로 테두리를 잃는다."""
        monkeypatch.setenv("SIDEBAR_AS_NOTE", "1")
        els = _els()
        assert pa.tag_boxed_elements(els, WIDE) == 1
        assert els[0]["content"].startswith("<!상자>범주화<!/상자>")

    def test_제목이_없으면_주석으로_안_돌린다(self, monkeypatch):
        """주석은 '주석과 설명을 쌍점으로 구분한다'(§2.4.7(4)) — 주석 이름이 있어야 한다."""
        monkeypatch.setenv("SIDEBAR_AS_NOTE", "1")
        els = [{"type": "text", "content": "여러 사물이나 현상을 묶어 분류하는 과정.",
                "bbox": [700, 140, 950, 260]}]
        pa.tag_boxed_elements(els, SIDEBAR)
        assert not els[0]["content"].startswith("※")


def test_주석표는_점자로_별표_두칸이다():
    """§2.4.7(1) 주석표 = ⠐⠔. gold 의 ※ 와 같은 셀인지 실제 점역기로 확인한다."""
    from app.ai.braille.translator import translate_tagged_text as T
    assert T("※ 범주화: 여러 사물").lstrip("⠀").startswith("⠐⠔")
