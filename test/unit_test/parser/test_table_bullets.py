"""표 셀 글머리 기호(「한국 점자 규정」 제72항) 복원 — mineru_runner._restore_table_bullets.

추출기가 표 셀의 •를 통째로 흘리거나 가운뎃점 ·로 낮춰 읽으면 항목 경계가 사라져
"…가능함연구 대상에…" 같은 런온 셀이 된다. PDF 텍스트 레이어를 근거로 그 글머리만 되돌린다.
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
        monkeypatch.setattr(MR, "_extract_text_native", lambda page, bb: text)
    return _set


def test_dropped_bullets_are_restored(layer):
    layer("•모든 사회는 안정적임\n•모든 사회는 통합된 체계임")
    html = "<table><tr><td>모든 사회는 안정적임모든 사회는 통합된 체계임</td></tr></table>"
    out = MR._restore_table_bullets(None, BBOX, html)
    assert out.count("•") == 2
    assert "안정적임•모든" in out


def test_middot_misread_is_promoted(layer):
    layer("•연구 대상을 만난다\n•깊이 있는 정보를 얻는다")
    html = "<table><tr><td>·연구 대상을 만난다·깊이 있는 정보를 얻는다</td></tr></table>"
    out = MR._restore_table_bullets(None, BBOX, html)
    assert "·" not in out and out.count("•") == 2


def test_no_bullet_in_layer_is_untouched(layer):
    """사회·문화처럼 정당한 가운뎃점은 건드리지 않는다(레이어에 글머리가 없으면 무동작)."""
    layer("사회·문화 현상의 본질")
    html = "<table><tr><td>사회·문화 현상의 본질</td></tr></table>"
    assert MR._restore_table_bullets(None, BBOX, html) == html


def test_partial_match_aborts_whole_table(layer):
    """한 항목이라도 못 찾으면 통째로 포기 — 부분 복원은 위계를 더 어긋나게 한다."""
    layer("•첫째 항목입니다\n•추출이 놓친 항목입니다")
    html = "<table><tr><td>첫째 항목입니다</td></tr></table>"
    assert MR._restore_table_bullets(None, BBOX, html) == html


def test_repeated_item_text_across_rows(layer):
    """같은 문구가 여러 행에 반복돼도 순서대로 제자리를 찾는다."""
    layer("•첫째 특징이다\n•공통 설명이다\n•둘째 특징이다\n•공통 설명이다")
    html = ("<table><tr><td>첫째 특징이다공통 설명이다</td>"
            "<td>둘째 특징이다공통 설명이다</td></tr></table>")
    out = MR._restore_table_bullets(None, BBOX, html)
    assert out.count("•") == 4


def test_bullet_never_lands_inside_math(layer):
    """셀 안 수식은 $…$로 감싸여 있다 — 글머리를 그 안에 넣으면 수식이 깨진다."""
    layer("•45+XX, 45+XY\n•21번 염색체 3개")
    html = "<table><tr><td> $45 + XX, 45 + XY$  $21번 염색체 3개$ </td></tr></table>"
    out = MR._restore_table_bullets(None, BBOX, html)
    assert out.count("•") == 2
    for i, ch in enumerate(out):
        if ch == "•":
            assert out.count("$", 0, i) % 2 == 0, f"글머리가 수식 안에 들어갔다: {out}"


def test_already_correct_table_is_unchanged(layer):
    layer("•첫째 항목입니다\n•둘째 항목입니다")
    html = "<table><tr><td>•첫째 항목입니다•둘째 항목입니다</td></tr></table>"
    assert MR._restore_table_bullets(None, BBOX, html) == html
