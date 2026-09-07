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


def test_본문_요소_안_글상자_테두리도_안_접는다():
    """글상자는 **유형이 아니라 줄**이다 — 요소 유형은 `text`라 _FOLDABLE_TYPES로는 못 거른다.

    2026-09-08 대표 지적 ②. `<!상자>…<!상자끝>`이 든 본문 요소가 통째로 한 줄
    (위 테두리 32 + 본문 115 + 아래 테두리 32 = 181칸)로 나갔고, BE가 32칸에서
    그냥 자르니 **아래 테두리가 문장 끝에 이어 찍혔다.**
    """
    top = "⠿" + "⠛" * 30 + "⠿"
    bottom = "⠿" + "⠶" * 30 + "⠿"
    body = "⠑" * 115
    lines, pads = [top, body, bottom], [0, 2, 0]
    _, seps = _fold_full_lines(lines, pads, "text")
    assert seps == ["\n", "\n"]


def test_본문끼리는_그대로_접는다():
    """테두리 가드가 일반 본문 접기를 막지 않는다(회귀)."""
    lines, pads = ["⠁" * 31, "⠃" * 31, "⠉⠙"], [0, 0, 0]
    _, seps = _fold_full_lines(lines, pads, "text")
    assert seps == ["⠀", "⠀"]


def test_선택지_줄은_길어도_안_접는다():
    """NLD 3장3절2 4)(3) — "선택지는 한 줄에 하나의 선택지 항목을 적는다".

    2026-09-08 실물(수능 국어 9쪽): 선택지 ①~⑤ 다섯 줄이 전부 28칸을 넘어 접기 조건에
    걸려 **한 줄 856칸**이 됐다. BE가 32칸에서 자르면 ①과 ②가 한 줄에 섞인다.
    점자만 보면 수표+숫자가 일반 숫자와 구분되지 않으므로 원문 줄머리로 가른다.
    """
    src = [f"{m}(가)에서 밝음과 어두움의 이미지를 활용하는 양상이 서로 다르다."
           for m in "①②③④⑤"]
    lines, pads = ["⠁" * 31] * 5, [2, 2, 2, 2, 2]
    _, seps = _fold_full_lines(lines, pads, "text", src)
    assert seps == ["\n"] * 4
    # 원문을 안 주면 종전대로 접힌다 — 회귀 방지용 대조군
    _, seps_no_src = _fold_full_lines(lines, pads, "text")
    assert seps_no_src == ["⠀"] * 4


def test_선택지_안_줄바꿈은_그대로_접는다():
    """항목 안에서 칸수에 밀려 끊긴 줄은 접는다 — 항목 머리 줄만 지킨다."""
    src = ["① 화자는 ⓐ가 흔드는 것이 감나무 잎새뿐이라고 여기다가 ⓑ를",
           "보며 그 생각을 바로잡고 있다.",
           "② 화자는 ⓑ가 내는 소리와 ⓒ의 움직임을 통해 짐작하고 있다."]
    lines, pads = ["⠁" * 31, "⠃" * 31, "⠉" * 31], [2, 0, 2]
    _, seps = _fold_full_lines(lines, pads, "text", src)
    assert seps == ["⠀", "\n"]
