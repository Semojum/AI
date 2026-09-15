"""#898 — MinerU high 가 그래프에서 지어낸 '영어 설명 표'를 걸러 낸다.

실측(#886 A/B 수학2 127쪽): 걸러야 할 표 11개가 있는 9쪽의 편집차 합 +852셀,
그대로 둬야 할 숫자 데이터 표 22개가 있는 14쪽은 −115셀. 두 갈래를 가르는 자리다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.parser.mineru_runner import _chart_data_table, _is_chart_description  # noqa: E402



# ── 버려야 할 것 — 지면에 없는 생성 설명(실제 armH 산출물에서 따왔다) ──────────
BAD = [
    "| Feature | Description |\n|---|---|\n| Function | y = e^(-x^2 + 1) |\n| Curve | y = e |",
    "| Point | x-coordinate | y-coordinate |\n|---|---|---|\n"
    "| Peak | \\(c_{1}\\) | — |\n| Trough | \\(c_{2}\\) | — |",
    "| Point | X-coordinate | Y-coordinate |\n|---|---|---|\n| P | a | f(a) |\n| Q | b | f(b) |",
    "| Point | x | y |\n|---|---|---|\n| Intersection (y=x) | a | ~0.5 |\n| Intersection | b | 1 |",
    "| Point | t | f(t) |\n|---|---|---|\n| a | 0 | ~0.5 |\n| b | b | ~-0.8 |",
    "| Function | Equation |\n|---|---|\n| Solid Line | y = 2/3 x |\n| Dashed Line | y = -x |",
    "| Point | X-coordinate | Y-coordinate |\n|---|---|---|\n"
    "| Leftmost point | (-\\sqrt{3}) | -1 |\n| Rightmost point | (\\sqrt{3}) | 1 |",
]

# ── 살려야 할 것 — 진짜 전사. 좌표 표(수학)와 외국어·생물의 영어 데이터 표 ────
GOOD = [
    "| X | Y |\n|---|---|\n| -1 | ~-0.5 |\n| 0 | ~0.5 |",
    "| X | y=f(x) | y=g(x) |\n|---|---|---|\n| -1 | 0 | — |\n| 0 | 1 | 0 |",
    "| X | y=1/2x+3 | (y=\\sqrt{2x+k}) |\n|---|---|---|\n| -6 | 0 | — |\n| 0 | 3 | 3 |",
    "| Region | 1990-2000 (thousands of hectares per year) |\n|---|---|\n| Africa | ~4000 |",
    "| Year | Ages 0-15 (%) | All Ages (%) |\n|---|---|---|\n| 1959 | ~27 | ~100 |",
    "| Time (hours) | Dynamic force (mmHg) |\n|---|---|\n| 0.0 | ~85 |\n| 0.5 | ~90 |",
    "| Stage | Value |\n|---|---|\n| 1 | ~Low |\n| 2 | ~Medium |",
    "| one | first of all | in addition |\n|---|---|---|\n| first | also | next |",
    "| 언어 문제 | 64.9 |\n|---|---|\n| 수리 | 35.1 |",
]


def test_생성된_설명표는_버린다():
    for md in BAD:
        assert _chart_data_table(md) == "", md.splitlines()[0]


def test_전사된_데이터표는_남긴다():
    for md in GOOD:
        assert _chart_data_table(md), md.splitlines()[0]


def test_한글이_있으면_머리줄이_부위이름이어도_남긴다():
    """한글이 섞이면 전사로 본다 — `_flowchart_lines` 의 한글 가드와 같은 뜻."""
    md = "| Point | 최고점 |\n|---|---|\n| A | 3 |"
    assert _chart_data_table(md)


def test_한글자_변수는_영어낱말로_안_센다():
    """`X | Y` 가 설명으로 오인되면 좌표 전사가 통째로 사라진다."""
    assert not _is_chart_description(["X | Y", "1 | 2"])
    assert not _is_chart_description(["x | y | z", "1 | 2 | 3"])


def test_LaTeX_명령은_영어낱말로_안_센다():
    assert not _is_chart_description([r"\alpha | \beta", "1 | 2"])


def test_머리줄만_본다():
    """데이터 칸의 'line' 때문에 멀쩡한 표가 지워지면 안 된다."""
    md = "| Region | Note |\n|---|---|\n| Africa | dashed line |"
    assert _chart_data_table(md)


def test_표가_아니면_종전대로_빈문자열():
    assert _chart_data_table("") == ""
    assert _chart_data_table("그냥 글") == ""
    assert _chart_data_table("| 한 줄뿐 |") == ""
