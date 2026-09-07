"""시각자료 점역자 주 **양식 불변식** (2026-09-08 대표 지시 — 양식은 코드가 정한다).

배포판 499afac 실물에서 한 문서 안에 세 꼴이 섞여 나왔다:
    <!2칸><!주>만화: …              ← 열고
    <!4칸><!주>장면 1<!/주><!/주>   ← 안에서 또 열고, 닫는 태그가 둘
    <!4칸>장면 1(현재)              ← 아예 안 감싸고
    <!2칸>60년 후                   ← 주가 닫힌 뒤 남은 조각

불변식 넷을 유형 넷(그림·사진·만화·도표)에서 전부 확인한다 — 어제 형제 경로 누락이
두 번 났다. 조립 경로 둘(`visual_drafts._outline_text_indents` · `diagram_opt.assemble_*`)이
모두 `tag_names.apply_indent_tags` 를 지나므로 그 자리를 함께 건다.
"""
from __future__ import annotations

import re

import pytest

from app.ai.braille import tag_names as T
from app.ai.llm import diagram_opt as D
from app.ai.llm.visual_drafts import _outline_text_indents

_OPEN, _CLOSE = f"<!{T.TN}>", f"<!/{T.TN}>"

# 유형 넷 × 재료 두 꼴(대사 있음 / 없음). 대표 QA 실물을 그대로 재현한 재료다.
CASES = [
    ("만화", [(1, "장면 1"), (0, "남학생: 이게 그 유명한 탄산 약수구나!"),
              (1, "장면 2"), (0, "여학생: 톡 쏘는 맛이 나네.")]),
    ("만화", [(1, "장면 1(현재)"), (0, "남성: 잘 다녀올게."),
              (0, "지팡이 짚은 배우자와 나란히 걷고 있음"), (0, "60년 후")]),
    ("만화", [(0, "두 사람이 마주 서 있음"), (0, "뒤로 산이 보임")]),   # 대사 없는 만화
    ("그림", [(0, "왼쪽에 원자핵이 있다."), (1, "전자 1개"), (0, "오른쪽은 비어 있다.")]),
    ("사진", [(0, "가운데에 여섯 개의 자판이 있다."), (0, "학생: 이건 뭔가요?")]),
    ("도표", [(0, "가로축: 시간"), (1, "0~10분"), (0, "세로축: 농도")]),
]


def _render(kind, items, title="원본 제목", desc="짧은 설명이다."):
    text, indents = _outline_text_indents(kind, title, desc, items, kind)
    return T.apply_indent_tags(text, indents)


@pytest.mark.parametrize("kind,items", CASES)
def test_tn_pairs_balanced_and_flat(kind, items):
    """짝이 맞고 · 중첩이 없다. 여는 태그 하나에 닫는 태그 하나."""
    out = _render(kind, items)
    assert T.tn_spans_ok(out), out
    assert out.count(_OPEN) == out.count(_CLOSE), out
    assert f"{_CLOSE}{_CLOSE}" not in out, out
    assert f"{_OPEN}{_OPEN}" not in out, out


@pytest.mark.parametrize("kind,items", CASES)
def test_lines_meant_for_the_note_never_fall_outside(kind, items):
    """주 안으로 정한 줄이 주 밖 조각으로 안 남는다.

    조항이 정한 것은 셋이다 — 머리줄(§6.3.4(1)) · 장면 표시(§5.3.3(1)) · 조립기가
    이미 주로 감싸 보낸 행동·상황(§5.3.3(6)(7)). 그 셋은 어디에 있든 주 안이어야 한다.
    (`60년 후` 처럼 조항이 없는 줄은 강제하지 않는다 — 원장 C-D5 자문 대기.)
    """
    out = _render(kind, items)
    depth, outside = 0, []
    for line in out.split("\n"):
        bare = T.split_indent(line)[1]
        opened = _OPEN in bare
        if not opened and depth == 0:
            outside.append(bare.strip())
        depth += bare.count(_OPEN) - bare.count(_CLOSE)
    for text in outside:
        assert not re.match(r"^(?:장면|컷)\s*\d+", text), f"장면 표시가 주 밖: {text!r}\n{out}"


def test_pretagged_situation_lines_stay_inside():
    """조립기가 감싸 보낸 상황 줄(`cartoon_opt._material_items`)은 대사 뒤에 와도 주 안이다."""
    items = [(1, "장면 1"), (0, "남성: 잘 다녀올게."),
             (0, f"{_OPEN}지팡이 짚은 배우자와 걷고 있음{_CLOSE}")]
    out = _render("만화", items, desc="한 인물의 인생.")
    assert T.tn_spans_ok(out), out
    line = next(l for l in out.split("\n") if "지팡이" in l)
    assert _OPEN in line and _CLOSE in line, out


@pytest.mark.parametrize("kind,items", CASES)
def test_head_line_opens_with_the_type_word(kind, items):
    """머리줄은 유형 제시어로 연다 — §6.3.4(1) "점역자 주표 안에 '시각 자료 유형'을 적고"."""
    head = next(l for l in _render(kind, items).split("\n") if _OPEN in l)
    assert head.split(_OPEN, 1)[1].startswith(kind), head


@pytest.mark.parametrize("kind,items", CASES)
def test_indent_tag_stays_outside_the_note(kind, items):
    """들여쓰기 태그는 조판 표식이라 주 **밖**에 남는다(줄머리)."""
    for line in _render(kind, items).split("\n"):
        if _OPEN in line:
            assert re.match(r"^(<!\d+칸>)?<!주>", line), line


@pytest.mark.parametrize("assembler,structure", [
    (D.assemble_concept_map, {"nodes": [{"text": "산소", "children": []}]}),
    (D.assemble_flowchart, {"boxes": [{"no": 1, "text": "물을 끓인다"}]}),
    (D.assemble_timeline, {"events": [{"date": "1919", "text": "삼일 운동"}]}),
    (D.assemble_family_tree, {"mode": "top_down", "nodes": [{"text": "해모수"}]}),
])
def test_diagram_skeletons_keep_the_regulation_form(assembler, structure):
    """형제 경로 — `build_visual_drafts` 를 안 타는 골격 조립기도 태그가 성해야 한다.

    ⚠ 쌍점은 **주 밖**이다(도서지침 제3장 제2절 4)(1) L2367-2369 · [예 3-19] BRF
      `,'@["o5,'"1`). 관문이 이 자리를 건드리지 않는다는 것까지 여기서 못 박는다 —
      gold 는 반대(주 안 97.4%)지만 빈도로 규정을 뒤집지 않는다(원장 C-D4 자문 대기).
    """
    text, indents = assembler(structure)
    out = T.apply_indent_tags(text, indents)
    assert T.tn_spans_ok(out), out
    assert f"{_OPEN}그림{_CLOSE}:" in out, out


@pytest.mark.parametrize("broken", [
    "<!주>머리\n<!주>장면 1<!/주><!/주>\n대사",                # 중첩 + 닫는 태그 둘
    "<!주>머리\n장면 1<!/주>\n<!주>꼬리",                      # 열린 채로 끝남
    "<!주>머리<!/주><!/주>",                                    # 짝이 안 맞는 닫힘
    "머리<!/주>\n<!주>꼬리<!/주>",                              # 여는 태그 없는 닫힘
])
def test_normalizer_repairs_any_broken_input(broken):
    """관문 — 깨진 꼴이 들어와도 성한 꼴만 나간다. 줄 수는 안 바뀐다."""
    out = T.normalize_tn_spans(broken)
    assert T.tn_spans_ok(out), out
    assert out.count("\n") == broken.count("\n"), out


def test_normalizer_keeps_plain_text_untouched():
    """정방향 이물질 없는 글은 한 글자도 안 바뀐다."""
    plain = "제목\n본문 한 줄\n또 한 줄"
    assert T.normalize_tn_spans(plain) == plain
    assert T.apply_indent_tags(plain, [4, 0, 0]) == "<!4칸>제목\n본문 한 줄\n또 한 줄"
