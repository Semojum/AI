"""표 칸 교정 쪼개기(#1317) — 실패 칸이 있어도 표를 통째로 놓지 않고, 창이 맞은 칸만 가드 셋을 지켜 고친다.

층 글은 손으로 짓는다(순환 검증 금지). 예는 2027 dev · val 실측 자리다(생활과 윤리 `촉은지심` · 생명과학 `콩팔` ·
언매 `피동사 ↔ 사동사` 창 어긋남).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.parser import mineru_runner as MR  # noqa: E402

BBOX = [0, 0, 1000, 1000]
# 둘째 칸 `⑦` 은 층에 글이 없다(그림 글자) → 종전엔 이 칸 하나 때문에 표를 통째로 놓았다.
HTML = "<table><tr><td>촉은지심은 남을 불쌍히 여기는 마음</td><td>⑦</td></tr></table>"
LAYER = "측은지심은 남을 불쌍히 여기는 마음 ○"


@pytest.fixture
def layer(monkeypatch):
    def _set(text):
        monkeypatch.setattr(MR, "_native_text_pair", lambda page, bb, skip_math=False: (text, text))
    return _set


@pytest.mark.parametrize("seg, off, ln, repl, layer_ns, ok", [
    ("콩팔에서", 1, 1, "팥", "콩팥에서물의재흡수", True),        # 종성 하나(ㄹ → ㅌ)
    ("해야함을", 0, 3, "장정리", "장정리를", False),              # ① 세 음절 — 창 어긋남
    ("이화작용", 0, 1, "동", "이화작용동화작용", False),          # ② 우리 글 `이화` 가 층에 있다
    ("시(인쇄매체)", 0, 1, "표", "표(인쇄매체)", False),           # ③ 초성 · 중성 둘 다 다름
    ("견지", 0, 1, "걷", "걷지", False),                         # ③ 진짜 오독이지만 자모 둘 — 놓친다(알고 둠)
])
def test_가드_셋(seg, off, ln, repl, layer_ns, ok):
    assert MR._split_fix_ok(seg, off, ln, repl, layer_ns) is ok


def test_실패_칸이_있어도_맞은_칸은_고치고_표지를_남긴다(layer):
    layer(LAYER)
    fixes: list[str] = []
    out = MR._correct_table_cells(None, BBOX, HTML, fixes=fixes)
    assert "측은지심" in out and "촉은지심" not in out and "<td>⑦</td>" in out
    assert fixes == ["{촉→측}은지"]


def test_fixes_를_안_넘기면_종전처럼_표째_놓는다(layer):
    layer(LAYER)
    assert MR._correct_table_cells(None, BBOX, HTML) == HTML


def test_스위치를_끄면_종전(layer, monkeypatch):
    layer(LAYER)
    monkeypatch.setenv("TABLE_CELL_SPLIT", "0")
    fixes: list[str] = []
    assert MR._correct_table_cells(None, BBOX, HTML, fixes=fixes) == HTML and fixes == []


def test_실패_칸이_없는_표는_종전과_같고_표지도_없다(layer):
    # 실패 칸이 없으면 가드를 안 건다 — 자모 둘이 다른 `견 → 걷` 도 종전처럼 고친다.
    layer("‘ㄱ, ㄷ, ㅂ’ 뒤의 경음화 예: 걷지 → [걷찌]")
    html = "<table><tr><td>‘ㄱ, ㄷ, ㅂ’ 뒤의 경음화 예: 견지 → [걷찌]</td></tr></table>"
    fixes: list[str] = []
    out = MR._correct_table_cells(None, BBOX, html, fixes=fixes)
    assert out == MR._correct_table_cells(None, BBOX, html) and "걷지" in out and fixes == []
