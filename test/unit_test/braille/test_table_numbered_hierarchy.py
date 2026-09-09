"""번호 체계 표(§3.3.3)의 위계 표기 — 「점자 자료 제작 지침」 재추출 2149~2157행.

종전에는 2단계 자리에 **3단계 기호 `1)`** 을 쓰고 값을 쌍점으로 같은 줄에 붙였다
(`1) 열제목: 값`). 규정은 2단계가 `가. 나. 다.` 이고, 항목마다 줄을 바꾼다.
예 3-9 실물(같은 파일 2216~2232행)의 들여쓰기는 1단계 6칸 · 2단계 4칸 · 항목 2칸이다.
"""
from app.ai.braille.table_braille import _render_numbered

SRC = "구분|2000년|2005년\n초혼|88.9|89.2\n재혼|11.1|10.8"


def _body(lines):
    return [l for l in lines if l.strip() and not l.startswith("⠿")]


def test_2단계는_가나다_이고_3단계_기호를_안_쓴다():
    body = _body(_render_numbered(SRC))
    joined = "\n".join(body)
    assert "⠫⠲" in joined, "2단계 `가.`(⠫⠲)가 없다"
    assert "⠉⠲" in joined, "2단계 `나.`(⠉⠲)가 없다"
    # 3단계 기호 `1)` = 수표+숫자+닫는 소괄호 — 이 렌더러에는 나오면 안 된다
    assert "⠼⠁⠠⠴" not in joined and "⠼⠃⠠⠴" not in joined, "3단계 기호 `1)`이 남아 있다"


def test_항목은_줄을_바꾸고_쌍점으로_안_잇는다():
    body = _body(_render_numbered(SRC))
    heads = [l for l in body if l.lstrip("⠀").startswith(("⠫⠲", "⠉⠲"))]
    assert heads, "2단계 줄이 없다"
    for h in heads:
        assert "⠐⠂" not in h, f"2단계 줄에 쌍점이 붙어 있다: {h!r}"
    # 값 88.9 는 2단계 줄이 아니라 **다음 줄**에 온다
    assert any(l.strip("⠀") == "⠼⠓⠓⠲⠊" for l in body), "값이 자기 줄로 안 내려왔다"


def test_들여쓰기가_예_3_9_와_같다():
    body = _body(_render_numbered(SRC))
    def indent(l):
        return len(l) - len(l.lstrip("⠀"))
    lv1 = [l for l in body if l.lstrip("⠀").startswith("⠼⠁⠲") or l.lstrip("⠀").startswith("⠼⠃⠲")]
    lv2 = [l for l in body if l.lstrip("⠀").startswith(("⠫⠲", "⠉⠲"))]
    vals = [l for l in body if l.strip("⠀") in ("⠼⠓⠓⠲⠊", "⠼⠓⠊⠲⠃", "⠼⠁⠁⠲⠁", "⠼⠁⠚⠲⠓")]
    assert lv1 and all(indent(l) == 6 for l in lv1), [(indent(l), l) for l in lv1]
    assert lv2 and all(indent(l) == 4 for l in lv2), [(indent(l), l) for l in lv2]
    assert vals and all(indent(l) == 2 for l in vals), [(indent(l), l) for l in vals]
