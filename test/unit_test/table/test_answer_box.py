"""단원 정답 상자 — MinerU 가 표로 본 것을 gold 꼴 글상자로 적는다(T33 §2-3 후속).

gold(생명과학 ans p0026 · 국어 ans p0003 · p0012): 제목은 상자 위, 여러 묶음이면 소제목은 상자 안,
쌍 사이 두 칸 · 번호와 답 사이 한 칸, 줄마다 3칸부터(정답 상자 쪽 gold 다수).
"""
import pytest

from app.ai.braille import table_braille as tb
from app.ai.braille.translator import translate_tagged_text as tr

PAD = "⠀"
TITLED = [["수능 2점 테스트", "본문 118~121쪽"],
          ["01 4", "02 5", "03 1", "04 3", "05 2", "06 1"],
          ["07 2", "08 4", "", ""]]
SECTIONS = [["언어", "01", "01 3", "02 3", "03 2", "04 3", "05 5", "06 5"],
            ["02", "01 4", "02 4", "03 3", "04 4", "05 3", "06 5"]]


def test_제목은_상자_위_쌍은_상자_안():
    titles, groups = tb.answer_box_parts(TITLED)
    assert titles == ["수능 2점 테스트", "본문 118~121쪽"]
    assert groups == [([], [("01", "4"), ("02", "5"), ("03", "1"), ("04", "3"),
                            ("05", "2"), ("06", "1"), ("07", "2"), ("08", "4")])]


def test_여러_묶음은_소제목을_상자_안에():
    titles, groups = tb.answer_box_parts(SECTIONS)
    assert titles == []
    assert [g[0] for g in groups] == [["[언어]", "(01)"], ["(02)"]]
    assert [len(g[1]) for g in groups] == [6, 6]


@pytest.mark.parametrize("rows", [
    [["구분", "A", "B", "C"], ["1 20", "2 30", "3 40", "4 50"], ["5 60", "6 70", "특징이 있다", "7 80"]],  # 긴 글이 낌
    [["01 4", "02 5", "04 3", "05 2", "06 1", "07 2"]],                                                   # 번호가 건너뜀
    [["01 4", "02 5", "03 1"]],                                                                           # 쌍이 모자람
    [["세포", "염색체 수"], ["A", "46"], ["B", "23"]],                                                      # 자료 표
])
def test_자료_표는_정답_상자가_아니다(rows):
    assert tb.answer_box_parts(rows) is None


def test_점자_꼴():
    lines = tb._render_answer_box(tb.answer_box_parts(TITLED))
    assert lines[0] == PAD * 4 + tr("수능 2점 테스트")
    assert lines[1] == PAD * 2 + tr("본문 118~121쪽")
    assert lines[2] == tb._TBL_TOP and lines[-1] == tb._TBL_BOT
    body = lines[3:-1]
    assert all(ln.startswith(PAD * 2) and len(ln) <= tb._COLS for ln in body)
    assert body[0] == PAD * 2 + (PAD * 2).join(tr(f"0{i} {a}") for i, a in ((1, 4), (2, 5), (3, 1), (4, 3)))


def test_초안_자리와_기본_선택(monkeypatch):
    text = "\n".join(" | ".join(r) for r in TITLED)
    assert tb.print_layout(text, "linear").splitlines()[:3] == ["수능 2점 테스트", "본문 118~121쪽", "┌"]
    monkeypatch.setenv("ANSWER_BOX_FORM", "0")          # 대조군: 종전 "테두리만"
    assert tb.print_layout(text, "linear").splitlines()[0] == "┌"


class _Page:
    """텍스트층 흉내 — `_restore_answer_marks` 가 쓰는 것만."""
    rotation = 0

    class rect:                                   # noqa: N801
        width, height = 500.0, 700.0

    def __init__(self, text):
        self._t = text

    def get_text(self, kind, clip=None):
        return self._t


_HTML = ("<table><tr><td colspan=\"4\">수능 2점 테스트</td></tr>"
         "<tr><td>01 4</td><td>02 5</td><td>03 1</td></tr><tr><td>04 3</td><td>05 2</td><td>06 20</td></tr></table>")


def _el():
    return [{"type": "table", "content": _HTML, "bbox": [100, 100, 900, 300]}]


def test_텍스트층이_같으면_원문자를_되살린다():
    from app.core import pipeline
    els = _el()
    n = pipeline._restore_answer_marks(els, _Page("01 ④\t\n02 ⑤\n03 ①\n04 ③\n05 ②\n06 20\n본문 12~14쪽"))
    assert n == 5
    assert "<td>01 ④</td>" in els[0]["content"] and "<td>06 20</td>" in els[0]["content"]


@pytest.mark.parametrize("layer", [
    "01 ④\n02 ⑤\n03 ①\n04 ③\n05 ②",             # 하나 모자람
    "01 ④\n02 ⑤\n03 ②\n04 ③\n05 ②\n06 20",       # 값이 다름(③ ≠ 1)
])
def test_텍스트층이_어긋나면_손대지_않는다(layer):
    from app.core import pipeline
    els = _el()
    assert pipeline._restore_answer_marks(els, _Page(layer)) == 0
    assert els[0]["content"] == _HTML


def test_정답_상자_표는_보기_쪼개기를_안_탄다():
    from app.core import pipeline
    html = _HTML.replace("01 4", "01 ④").replace("02 5", "02 ⑤")
    ext = {"meta": {"extraction_method": "OCR"},
           "elements": [{"id": "t", "order": 1, "type": "table", "content": html}]}
    _, ext_map, _ = pipeline._parse_txt_result(ext, "p_001")
    assert "01 ④" in next(iter(ext_map.values())).corrected_text


def test_관측된_상자_제목은_위_테두리에():
    """gold(동아시아사 ans p0018 · 사회문화 ans p0050): 【글상자 수능 기본 문제】, 쪽 범위는 상자 위."""
    rows = [["수능 기본 문제", "본문 79~80쪽"], ["01 3", "02 5", "03 3", "04 2", "05 3", "06 1"]]
    lines = tb._render_answer_box(tb.answer_box_parts(rows))
    assert lines[0] == PAD * 2 + tr("본문 79~80쪽")
    assert lines[1] == tr("<!상자>수능 기본 문제<!/상자>")


def test_본문_쪽_표지가_있으면_세_쌍도_정답_상자():
    titles, groups = tb.answer_box_parts([["Level", "3", "실력 완성", "본문 50쪽"], ["1 5", "2 3", "3 4"]])
    assert titles == ["Level 3", "실력 완성", "본문 50쪽"] and len(groups[0][1]) == 3


def test_두_쌍이_한_칸에_붙으면_표로_둔다():
    """MinerU 가 `01 4` 와 `05 3` 을 한 칸에 붙인 것 — 번호가 1에서 시작하지 않아 거른다."""
    assert tb.answer_box_parts([["01 매체", "본문 110~119쪽"], ["01 405 3", "02 4", "03 5", "04 5"]]) is None


_CIRCLED_TABLE = ("<table><tr><td>구분</td><td>물질의 전환</td></tr>"
                  "<tr><td>(가)</td><td> $⑦ \\rightarrow ①$ </td></tr><tr><td>(나)</td><td> $① \\rightarrow ③$ </td></tr></table>")


@pytest.mark.parametrize("keep, split", [("", False), ("0", True)])
def test_표는_보기_쪼개기를_안_탄다(monkeypatch, keep, split):
    """#1042 — 칸 안에 줄바꿈이 들어가면 격자가 행째로 부서진다. 스위치 0 이 종전(대조군)."""
    from app.core import pipeline
    monkeypatch.setenv("TABLE_KEEP_CELLS", keep)
    ext = {"meta": {"extraction_method": "OCR"},
           "elements": [{"id": "t", "order": 1, "type": "table", "content": _CIRCLED_TABLE}]}
    _, ext_map, _ = pipeline._parse_txt_result(ext, "p_001")
    assert ("\n" in next(iter(ext_map.values())).corrected_text) is split
