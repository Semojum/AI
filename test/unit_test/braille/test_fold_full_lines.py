"""꽉 찬 줄 뒤 개행 접기 — contents는 조판하지 않은 통 문자열이 계약이다.

proto §TextElement.contents는 통 문자열이고 32칸 자름은 FE·BE 몫인데, 32칸에 밀려
끊긴 줄이 개행으로 남아 나갔다(eval 실측 점자 요소의 25%, 그중 32%가 이 얼굴).

대표 기준(2026-08-16) 그대로다 — 칸수 초과 때문이면 한 줄로, 의도된 줄바꿈이면 살린다.
셀 폭은 AI만 아니까 자리도 여기다.
"""
from app.ai.braille.layout_braille import _fold_full_lines, _pad_join, _flat_trail
from app.schemas.content import RuleApplication


def _trail(n: int) -> list[RuleApplication]:
    return [RuleApplication(rule_id="T", source="s", section="1", rule_name="t",
                            contents="e", priority="primary",
                            line_no=i, col_start=0, col_end=1) for i in range(n)]


def test_꽉_찬_줄_뒤는_점자공백으로_잇는다():
    lines, pads = ["⠁" * 31, "⠃⠉"], [0, 0]
    _, seps = _fold_full_lines(lines, pads)
    assert seps == ["⠀"]


def test_짧은_줄_뒤_개행은_살린다():
    """시행·대사·목록처럼 줄바꿈이 내용인 자리다."""
    lines, pads = ["⠁" * 12, "⠃⠉"], [0, 0]
    _, seps = _fold_full_lines(lines, pads)
    assert seps == ["\n"]


def test_표와_시각자료는_안_접는다():
    """테두리 ⠿⠛…⠿가 정확히 32칸이라 조건에 걸린다 — 조판이 아니라 구조다."""
    border = "⠿" + "⠛" * 30 + "⠿"
    lines, pads = [border, "⠁⠃"], [0, 0]
    for etype in ("table", "image", "chart_graph", "diagram"):
        _, seps = _fold_full_lines(lines, pads, etype)
        assert seps == ["\n"], etype


def test_접어도_rule_trail_오프셋이_맞는다():
    """개행과 점자공백이 둘 다 1문자라 오프셋이 안 바뀐다 — 줄 문자열에 손대면 밀린다."""
    lines, pads = ["⠁" * 31, "⠃⠉⠙", "⠑" * 12, "⠋⠛"], [0, 3, 0, 3]
    pads2, seps = _fold_full_lines(lines, pads)
    body = _pad_join(lines, pads2, seps)
    for i, r in enumerate(_flat_trail(_trail(len(lines)), lines, 0, len(body), pads2)):
        assert body[r.col_start] == lines[i][0], f"줄 {i}"


def test_이어_붙는_줄은_들여쓰기를_잃는다():
    """같은 논리 줄의 뒷부분이라 다시 들여쓰면 안 된다."""
    lines, pads = ["⠁" * 31, "⠃⠉"], [0, 3]
    pads2, _ = _fold_full_lines(lines, pads)
    assert pads2[1] == 0
