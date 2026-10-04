"""표 행이 접힐 때 이어지는 줄 들여쓰기(#1113) — 1칸(앞 빈칸 0)에서 잇는다.

근거: 「점자 자료 제작 지침」 §3.3.1 [예 3-7](재추출 2107~2113행)이 열 제목 · 행을 3칸(2109 · 2112행)에,
이어지는 줄을 1칸(2110 · 2113행)에 적는다. 94권 전수에서도 테두리 안 이어지는 줄은 0칸 88.9% · 4칸 0.4% 다.
첫 줄 들여쓰기는 그대로다.
"""
from app.ai.braille.table_braille import _wrap_row

B = "⠀"


def test_이어지는_줄은_1칸에서_잇는다():
    body = B.join(["⠁⠁⠁⠁⠁⠁⠁"] * 8)                  # 7셀 × 8토막 = 한 줄(32칸)에 안 들어간다
    lines = _wrap_row(body, first_indent=2)
    assert len(lines) >= 2
    assert lines[0].startswith(B * 2) and not lines[0].startswith(B * 3)
    assert all(not ln.startswith(B) for ln in lines[1:])


def test_번호_체계_첫_줄_들여쓰기는_그대로다():
    lines = _wrap_row(B.join(["⠁⠁⠁⠁⠁⠁⠁"] * 8), first_indent=6)
    assert lines[0].startswith(B * 6) and not lines[0].startswith(B * 7)
    assert not lines[1].startswith(B)
