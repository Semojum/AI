"""#1296 표 칸 한 음절 오독 표시 — mineru_runner.table_misreads.

표 칸 교정(_correct_table_cells)은 칸 하나라도 층에서 못 찾으면 표를 통째로 안 고친다. 그래서 남은 한글 오독
(2027 세계사 정벌 → 정별 · 동아시아사 쑨원 → 쓰원)이 표시 없이 나갔다. 고치지 않고 자리만 짚는다.
잣대: 앞뒤 3자가 두 쪽에서 같은 한글 1~2자 같은 길이 치환만.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.parser import mineru_runner as MR  # noqa: E402

BBOX = [0, 0, 1000, 1000]


@pytest.fixture
def layer(monkeypatch):
    """텍스트 레이어를 원하는 문자열로 고정한다(PDF 없이 순수 로직 검증)."""
    def _set(text):
        monkeypatch.setattr(MR, "_native_text_pair", lambda page, bb, skip_math=False: (text, text))
    return _set


def test_남은_한글_오독_자리를_짚는다(layer):
    layer("청일전쟁 승리 조선에 대한 정벌 주장 → 실행 보류")
    html = "<table><tr><td>조선에 대한 정별 주장 → 실행 보류</td></tr></table>"
    assert MR.table_misreads(None, BBOX, html) == ["한정{별→벌}주장"]


def test_교정을_포기한_표에서도_짚는다(layer):
    """짧은 칸 '흔성반'(닮음 0.67)이 교정을 통째로 막아도 다른 칸의 오독은 짚는다."""
    layer("남학생반 여학생반 혼성반 조선에 대한 정벌 주장 → 실행 보류")
    html = ("<table><tr><td>남학생반</td><td>여학생반</td><td>흔성반</td></tr>"
            "<tr><td>조선에 대한 정별 주장 → 실행 보류</td></tr></table>")
    assert MR._correct_table_cells(None, BBOX, html) == html           # 교정은 포기한다
    assert MR.table_misreads(None, BBOX, html) == ["한정{별→벌}주장"]


def test_앞뒤_3자가_안_맞으면_짚지_않는다(layer):
    """칸 머리 · 끝에 걸친 치환은 창 어긋남과 못 가른다(피동사 ↔ 사동사 칸이 뒤바뀐 꼴)."""
    layer("정벌 주장")
    assert MR.table_misreads(None, BBOX, "<table><tr><td>정별 주장</td></tr></table>") == []


def test_한글_같은_길이_치환이_아니면_짚지_않는다(layer):
    layer("자료 ②(나) 조선에 대한 정벌이 주장 → 실행")
    html = "<table><tr><td>자료 2(나) 조선에 대한 정별 주장 → 실행</td></tr></table>"
    assert MR.table_misreads(None, BBOX, html) == []                    # 2 ↔ ② · 별 ↔ 벌이


def test_층을_못_믿으면_짚지_않는다(layer, monkeypatch):
    layer("청일전쟁 승리 조선에 대한 정벌 주장 → 실행 보류")
    monkeypatch.setattr(MR, "_layer_untrustworthy", lambda s, page=None: True)
    assert MR.table_misreads(None, BBOX, "<table><tr><td>조선에 대한 정별 주장 → 실행 보류</td></tr></table>") == []


# ── B3: 같은 잣대로 고친다(fix_table_misreads) ───────────────────────────────────

def test_포기한_표에서도_확실한_자리는_고친다(layer):
    """교정이 포기한 표에서 짚던 자리를 층 글자로 고친다. 다른 칸('흔성반')은 그대로 둔다."""
    layer("남학생반 여학생반 혼성반 조선에 대한 정벌 주장 → 실행 보류")
    html = ("<table><tr><td>남학생반</td><td>여학생반</td><td>흔성반</td></tr>"
            "<tr><td>조선에 대한 정별 주장 → 실행 보류</td></tr></table>")
    assert MR._correct_table_cells(None, BBOX, html) == html           # 교정은 여전히 포기한다
    out, fixed = MR.fix_table_misreads(None, BBOX, html)
    assert out == html.replace("정별", "정벌")
    assert fixed == ["한정{별→벌}주장"]
    assert MR.table_misreads(None, BBOX, out) == []                     # 고친 뒤에는 짚을 것이 없다


def test_글자_사이에_태그가_끼면_고치지_않고_짚기만_한다(layer):
    """원문에서 연속이 아닌 자리는 바꿀 자리를 확정할 수 없다(_correct_table_cells 와 같은 규칙)."""
    layer("조선에 대한 정벌하자 주장")
    html = "<table><tr><td>조선에 대한 정별<b></b>허자 주장</td></tr></table>"
    assert MR.fix_table_misreads(None, BBOX, html) == (html, [])
    assert MR.table_misreads(None, BBOX, html) == ["한정{별허→벌하}자주"]


def test_칸_안_태그_공백은_건너뛰고_자리를_맞춘다(layer):
    """대조본은 태그 · 공백 · $ 를 뺀 글이다. 고칠 때는 html 자리로 되돌려 그 글자만 바꾼다."""
    layer("청일전쟁 승리 조선에 대한 정벌 주장 → 실행 보류")
    html = "<table><tr><td>청일전쟁 <b>승리</b></td><td>조선에 대한 정별 주장 → $실행$ 보류</td></tr></table>"
    out, fixed = MR.fix_table_misreads(None, BBOX, html)
    assert out == html.replace("정별", "정벌") and fixed == ["한정{별→벌}주장"]


def test_끄거나_층을_못_믿으면_고치지_않는다(layer, monkeypatch):
    layer("청일전쟁 승리 조선에 대한 정벌 주장 → 실행 보류")
    html = "<table><tr><td>조선에 대한 정별 주장 → 실행 보류</td></tr></table>"
    monkeypatch.setenv("TABLE_MISREAD_FIX", "0")
    assert MR.fix_table_misreads(None, BBOX, html) == (html, [])
    monkeypatch.delenv("TABLE_MISREAD_FIX")
    monkeypatch.setattr(MR, "_layer_untrustworthy", lambda s, page=None: True)
    assert MR.fix_table_misreads(None, BBOX, html) == (html, [])
