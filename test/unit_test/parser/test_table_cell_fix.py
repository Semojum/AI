"""표 셀 한글 오독 교정 — mineru_runner._correct_table_cells.

표는 _NATIVE_TEXT_TYPES에서 빠져 있어(HTML 구조를 평문으로 덮으면 표가 깨진다) MinerU
OCR 글자가 그대로 남는다. 코퍼스 1131p 실측에서 남은 오독의 사실상 전부가 여기 있었다
(흔성반→혼성반 · 건년방→건넌방 · 상총→상충 · 쇠큐→쇄국).

핵심 안전 규칙 두 가지를 회귀로 고정한다.
  1. 길이가 바뀌는 편집은 적용하지 않는다 — 레이어는 시각적 줄 단위라 셀 경계에서 잘리고,
     통째 교체하면 글자를 고치는 대신 문장을 잘라먹는다.
  2. 내용 있는 셀 하나라도 레이어에서 못 찾으면 그 표는 통째로 손대지 않는다.
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
        monkeypatch.setattr(MR, "_native_text_spaced", lambda page, bb: text)
    return _set


def test_한글_오독을_고친다(layer):
    # 실측 사례(사회문화 p033): 흔성반 → 혼성반
    layer("남학생반과 여학생반을 합쳐 편성한 혼성반의 학업 성취도")
    html = ("<table><tr><td>남학생반과 여학생반을 합쳐 편성한 "
            "흔성반의 학업 성취도</td></tr></table>")
    out = MR._correct_table_cells(None, BBOX, html)
    assert "혼성반" in out and "흔성반" not in out


def test_아주_짧은_셀은_고치지_않는다(layer):
    """의도된 보수성 — 3글자 셀에서 1글자 오독은 유사도가 0.67까지 떨어져 임계에 못 미친다.

    임계를 낮추면 `국가`↔`국민`처럼 서로 다른 짧은 표제어를 오독으로 오인해 조용히
    바꿔 버린다. 짧은 셀은 못 고치고 넘어가는 쪽을 택했다(그 표는 통째로 포기된다).
    """
    layer("남학생반 여학생반 혼성반")
    html = "<table><tr><td>남학생반</td><td>여학생반</td><td>흔성반</td></tr></table>"
    assert MR._correct_table_cells(None, BBOX, html) == html


def test_두_글자_치환도_같은_길이면_적용(layer):
    # 실측 사례(사회문화 p019): 있어가치 → 잉여가치
    layer("생산이 이루어져 잉여가치의 축적이 나타나지 않음")
    html = "<table><tr><td>생산이 이루어져 있어가치의 축적이 나타나지 않음</td></tr></table>"
    out = MR._correct_table_cells(None, BBOX, html)
    assert "잉여가치" in out


def test_구조는_보존된다(layer):
    layer("남학생반 여학생반 혼성반")
    html = "<table><tr><td>남학생반</td><td>여학생반</td><td>흔성반</td></tr></table>"
    out = MR._correct_table_cells(None, BBOX, html)
    assert out.count("<td>") == 3 and out.count("</tr>") == 1
    assert out.startswith("<table>") and out.endswith("</table>")


def test_레이어가_잘려_있으면_길이가_바뀌므로_무시(layer):
    """레이어가 셀 중간에서 끊긴 경우(실측: `빛(400~700nm의 가시`) 잘라먹으면 안 된다."""
    layer("빛(400~700nm의 가시")
    html = "<table><tr><td>빛(400~700nm의 가시광선)</td></tr></table>"
    assert MR._correct_table_cells(None, BBOX, html) == html


def test_기호_숫자는_건드리지_않는다(layer):
    """물결표·붙임표는 레이어 쪽이 원문 글리프지만 특수기호 축 담당이라 여기서 안 고친다."""
    layer("기원전 6000∼5000년경 – 청동기")
    html = "<table><tr><td>기원전 6000~5000년경 - 청동기</td></tr></table>"
    out = MR._correct_table_cells(None, BBOX, html)
    assert "6000~5000" in out and "∼" not in out


def test_셀_하나라도_못_찾으면_표_전체를_포기(layer):
    """찾은 셀의 교정도 근거가 없다 — 레이어와 표가 다른 것을 가리킨다는 뜻이다."""
    layer("남학생반 여학생반 혼성반")
    html = ("<table><tr><td>흔성반</td>"
            "<td>레이어에 전혀 없는 완전히 다른 문장이 들어 있다</td></tr></table>")
    assert MR._correct_table_cells(None, BBOX, html) == html


def test_레이어에_글자가_없으면_무동작(layer):
    layer("")
    html = "<table><tr><td>흔성반</td></tr></table>"
    assert MR._correct_table_cells(None, BBOX, html) == html


def test_레이어가_PUA면_무동작(layer):
    """한컴 수식 폰트 PDF는 글리프를 사설 영역에 넣는다 — 레이어를 믿으면 안 된다."""
    layer(" 혼성반")
    html = "<table><tr><td>흔성반</td></tr></table>"
    assert MR._correct_table_cells(None, BBOX, html) == html


def test_일치하면_원본_그대로(layer):
    layer("남학생반 여학생반 혼성반")
    html = "<table><tr><td>남학생반</td><td>여학생반</td><td>혼성반</td></tr></table>"
    assert MR._correct_table_cells(None, BBOX, html) == html


def test_빈_셀은_대조_실패로_치지_않는다(layer):
    """표 머리의 빈 칸 때문에 표 전체가 포기되면 안 된다."""
    layer("구분 남학생반과 여학생반을 합쳐 편성한 혼성반의 학업 성취도")
    html = ("<table><tr><td></td><td>구분</td>"
            "<td>남학생반과 여학생반을 합쳐 편성한 흔성반의 학업 성취도</td></tr></table>")
    out = MR._correct_table_cells(None, BBOX, html)
    assert "혼성반" in out


def test_레이어의_인라인_태그는_대조에서_제외(layer):
    """레이어에는 우리가 붙이는 <!강조> 류가 들어 있다 — 그대로 대면 전부 불일치가 된다."""
    layer("남학생반과 여학생반을 합쳐 편성한 <!강조>혼성반<!/강조>의 학업 성취도")
    html = ("<table><tr><td>남학생반과 여학생반을 합쳐 편성한 "
            "흔성반의 학업 성취도</td></tr></table>")
    out = MR._correct_table_cells(None, BBOX, html)
    assert "혼성반" in out and "<!강조>" not in out
