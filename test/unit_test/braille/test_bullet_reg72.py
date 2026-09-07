"""제72항 줄머리 글머리 기호 — 평문 경로(`translate_plain`)까지 같은 점형인가.

## 왜 이 파일이 있나 (2026-09-07)

`○□△`는 문맥에 따라 두 조항으로 갈린다.
  · 줄머리 단독      → **제72항 글머리 기호** `_0`·`_7`·`_+` (꼬리 `l` 없음)
  · 줄 안·붙어 나옴  → **제49·57항 숨김표** `_0l`·`_+l`·`_7l` (꼬리 `l` 있음)

본문 경로는 `layout_braille._apply_bullet_marker`가 정정하는데 그건 layout 단계다.
`translate_plain`(TranslateText RPC · 정방향 CER 하네스)은 layout을 안 타서
줄머리도 숨김표형으로 나갔다. docstring이 "본문과 같은 rule-based 경로"라고 쓴 것과
어긋나 있었다.

기대값은 **규정 원문 BRF에서 직접 만든다** —
`braille-source/text/한국 점자 규정_재추출.txt` 행 2879~2901(제72항 표와 예시).
"""
from __future__ import annotations

import pytest

from app.ai.braille.translator import translate_plain
from app.utils.braille_ascii import ascii_to_unicode


def _reg(brf: str) -> str:
    """규정 원문 BRF → 유니코드 점자. 규정 관례상 백틱은 칸 띄우기."""
    return ascii_to_unicode(brf, backtick="space")


@pytest.mark.parametrize("korean,reg_brf", [
    # 규정 제72항 예시 "2021 한글날 주요 문화행사"(행 2890~2897) 그대로.
    ("□ 2021 세계한국어한마당", "_7`#bjba`,n@/j3@masj3ei7"),
    ("○ (기간/방식) 10. 4.", "_0`8'@o$3_/~7,oa,0`#aj4`#d4"),
])
def test_line_head_is_bullet_not_hidden(korean: str, reg_brf: str) -> None:
    assert translate_plain(korean) == _reg(reg_brf)


@pytest.mark.parametrize("korean,head", [
    ("○ 기산에 늙은 사람", "⠸⠴"),
    ("□ standardise 표준화하다", "⠸⠶"),
    ("△ 주의할 점", "⠸⠬"),
])
def test_all_three_shapes(korean: str, head: str) -> None:
    out = translate_plain(korean)
    assert out.startswith(head + "⠀"), out[:8]


@pytest.mark.parametrize("korean,head", [
    # 붙어 나오는 진짜 숨김표(제57항 반복형)는 건드리면 안 된다.
    # 실측 1,180쪽 줄머리 ○□△ 37건 중 19건이 이 부류다.
    ("○○ 고등학교, 빗물 재활용", "⠸⠴⠴⠇"),
    ("□□고 여러분", "⠸⠶⠶⠇"),
    ("△△ 지역의 초등학교", "⠸⠬⠬⠇"),
    # 줄머리가 아닌 숨김표도 그대로(규정 제57항 예시).
    ("김○○ 씨", "⠈⠕⠢⠸⠴⠴⠇"),
])
def test_hidden_marks_survive(korean: str, head: str) -> None:
    assert translate_plain(korean).startswith(head), translate_plain(korean)[:10]
