"""단원 정답 상자 — MinerU 가 표로 본 것을 gold 꼴 글상자로 적는다(T33 §2-3 후속).

gold(생명과학 ans p0026 · 국어 ans p0003 · p0012): 제목은 상자 위, 여러 묶음이면 소제목은 상자 안,
쌍 사이 두 칸 · 번호와 답 사이 한 칸, 줄마다 3칸부터(정답 상자 쪽 gold 다수).
"""
import pytest

from app.ai.braille import table_braille as tb
from app.ai.llm.table_opt import _html_to_grid
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


# ── 정답 띠 다시 만들기(#1353) — 띠 머리가 첫 행에 있는데 위 되살리기를 못 탄 표 ─────────────────
# 생활과 윤리 해설 p9 실물: 번호와 답이 다른 칸이고 원문자가 벗겨졌고 05 · 06 이 빠졌다. 글자층에는 쌍째로 다 있다.
_BAND = ("<table><tr><td>수능</td><td>기본</td><td>문제</td><td></td><td></td><td></td><td>본문 35~36쪽</td></tr>"
         "<tr><td>01</td><td>1</td><td>02</td><td>3</td><td>03</td><td>4</td><td>04</td></tr>"
         "<tr><td>07</td><td>5</td><td>08</td><td>1</td><td></td><td></td><td></td></tr></table>")
_BAND_LAYER = "01 ① \n02 ③ \n03 ④ \n04 ③ \n05 ② \n06 ④ \n07 ⑤ \n08 ①\n본문 35~36쪽\n수능               문제\n기본\n"


def test_정답_띠는_글자층_쌍으로_다시_만든다():
    from app.core import pipeline
    els = [{"type": "table", "content": _BAND, "bbox": [100, 100, 900, 300]}]
    assert pipeline._restore_answer_marks(els, _Page(_BAND_LAYER)) == 8
    titles, groups = tb.answer_box_parts(_html_to_grid(els[0]["content"], expand=False))
    assert titles == ["수능 기본 문제", "본문 35~36쪽"]
    assert groups[0][1] == [("01", "①"), ("02", "③"), ("03", "④"), ("04", "③"),
                            ("05", "②"), ("06", "④"), ("07", "⑤"), ("08", "①")]
    assert els[0]["table_fixes"] == ["정답 띠{01 1 02 3 03 4 04 07 5…→01 ①  02 ③  03 ④  04 ③…}"]


def test_쌍을_빠뜨린_정답_상자도_채운다():
    """언매 해설 p53 실물: MinerU 가 `04 ⑤` 를 빠뜨려 3쌍 대 4쌍이라 위 되살리기가 손대지 않던 표."""
    from app.core import pipeline
    html = ("<table><tr><td colspan=\"2\">05 통합</td><td>본문 215~219쪽</td></tr>"
            "<tr><td>01 1</td><td>02 5</td><td>03 2</td></tr></table>")
    els = [{"type": "table", "content": html, "bbox": [100, 100, 900, 300]}]
    assert pipeline._restore_answer_marks(els, _Page("01 ①\t\n02 ⑤\t\n03 ②\t\n04 ⑤\n통합\n05\n본문 215~219쪽\n")) == 4
    _, groups = tb.answer_box_parts(_html_to_grid(els[0]["content"], expand=False))
    assert groups[0][1] == [("01", "①"), ("02", "⑤"), ("03", "②"), ("04", "⑤")]


@pytest.mark.parametrize("layer", [
    "01 ② \n02 ② \n03 ② \n04 ③ \n05 ② \n06 ④ \n07 ⑤ \n08 ①\n",   # 표 숫자(01 1 02 3 …)가 글자층 숫자에 다 안 든다 — 엉뚱한 글자층
    "02 ③ \n03 ④ \n04 ③ \n05 ② \n06 ④ \n07 ⑤ \n08 ①\n",          # 번호가 1부터가 아니다
    "01 ① \n02 ③\n",                                                # 글자층 쌍이 표 숫자의 절반도 못 덮는다
])
def test_못_믿을_글자층이면_정답_띠를_손대지_않는다(layer):
    from app.core import pipeline
    els = [{"type": "table", "content": _BAND, "bbox": [100, 100, 900, 300]}]
    assert pipeline._restore_answer_marks(els, _Page(layer)) == 0
    assert els[0]["content"] == _BAND and "table_fixes" not in els[0]


def test_답이_하나인_띠도_정답_상자로_그린다():
    """사회문화 해설 p44 실물: 쌍이 머리 칸에 붙어 왔다(`기출 플러스1 5`). gold 는 `본문 111쪽` · 【글상자 기출 플러스】 · `1 ⑤`."""
    from app.core import pipeline
    from app.ai.llm.table_opt import _infer_render_mode
    html = "<table><tr><td>기출 플러스1 5</td><td>본문 111쪽</td></tr></table>"
    els = [{"type": "table", "content": html, "bbox": [100, 100, 900, 300]}]
    assert pipeline._restore_answer_marks(els, _Page("1 ⑤\n본문 111쪽\n기출 플러스\n")) == 1
    titles, groups = tb.answer_box_parts(_html_to_grid(els[0]["content"], expand=False))
    assert titles == ["기출 플러스", "본문 111쪽"] and groups[0][1] == [("1", "⑤")]
    assert _infer_render_mode(None, els[0]["content"]) == "linear"     # 2열이어도 띠 머리가 있으면 정답 상자
