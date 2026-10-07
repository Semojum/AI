"""보기 항목 자모 글머리(#1169) — 조판이 상자 안 ㄱ. ㄴ. ㄷ. 항목마다 2칸을 준다.

줄 잇기(`pipeline._is_list_head`)가 항목을 제 줄에 두어도, 조판의 항목 줄머리 판정(`_ITEM_HEAD`)이 자모 글머리를
몰랐고 글상자 요소는 원문 줄 수와 점자 줄 수가 달라 판정을 통째로 건너뛰어 ㄴ. ㄷ. 이 0칸이었다(gold 2칸).
「점자 도서 제작 지침」 〈보기〉 예(재추출본 3243~3249행)는 항목마다 2칸에서 시작한다.
"""
from uuid import uuid4

from app.ai.braille.layout_braille import LayoutBraille, _aligned_src, _is_border_line
from app.ai.braille.text_braille import TextBraille
from app.schemas.content import LLMOutput
from app.schemas.layout import BBoxItem, LayoutResult

SRC = ("<!상자>보기<!/상자>\nㄱ. 지금 떠나면 새벽에 도착하겠구나.\nㄴ. 동생은 낚시하러 간다.\n"
       "ㄷ. 잠시 후 신랑 입장이 있겠습니다. <!상자끝><!/상자끝>")
HEADS = ("⠿⠁⠲", "⠿⠒⠲", "⠿⠔⠲")          # ㄱ. ㄴ. ㄷ. (온표 · 제8항)


def _laid(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    eid = uuid4()
    opt = LLMOutput(element_id=eid, corrected_text=SRC, render_mode="text_only",
                    routing_tier="ZERO", processing_time_ms=0)
    bo = TextBraille().translate([opt])[0]
    lr = LayoutResult(page_id="p1", page_no=1, items=[
        BBoxItem(element_id=eid, type="text", bbox=(0, 0, 10, 10), reading_order=1)])
    LayoutBraille().layout([bo], 1, "jamo1169", layout_result=lr)
    return [ln for ln in bo.braille_lines if any(ln.lstrip("⠀ ").startswith(h) for h in HEADS)]


def test_상자_속_자모_항목마다_2칸(tmp_path, monkeypatch):
    heads = _laid(tmp_path, monkeypatch)
    assert len(heads) == 3 and all(ln.startswith("⠀⠀") and not ln.startswith("⠀⠀⠀") for ln in heads)


def test_끈_스위치는_첫_항목만_들인다(tmp_path, monkeypatch):
    monkeypatch.setenv("JOIN_JAMO_HEAD", "0")
    heads = _laid(tmp_path, monkeypatch)
    assert [ln.startswith("⠀⠀") for ln in heads] == [True, False, False]


LINES = ["", "⠿⠛⠛⠛⠛⠀⠘⠥⠈⠕⠀" + "⠛" * 20 + "⠿", "가", "나", "⠿" + "⠶" * 30 + "⠿"]


def test_원문_줄은_내용_줄끼리_맞댄다():
    assert _is_border_line(LINES[1]) and _is_border_line(LINES[4])
    assert _aligned_src("<!상자>보기<!/상자>\nㄱ. 가\nㄴ. 나 <!상자끝><!/상자끝>", LINES) == ["", "", "ㄱ. 가", "ㄴ. 나 ", ""]


def test_자모_글머리가_없는_상자는_맞대지_않는다():
    # 해설 정답표 상자(`① 2` 줄)까지 맞대 항목으로 들이면 val 이 나빠졌다(A/B 2차)
    src = "<!상자>보기<!/상자>\n① 가\n② 나 <!상자끝><!/상자끝>"
    assert _aligned_src(src, LINES) == src.split("\n")
