"""`contents` 직렬화 계약 — 조판 가이드 2026-08-05 기준(통 문자열).

계약(`protos/braille_service.proto`):
  · `TextElement.contents` = **항목 1개짜리 통 문자열**. 조판(32칸 자름·면 나눔·들여쓰기·
    가운데 정렬)은 FE(화면)·BE(다운로드, braille-assist)가 한다.
  · **구조적 빈 줄은 이 문자열 안에 `\\n`으로 들어 있다** — 제목 앞뒤 빈 줄은 지침
    (BBPG 2장2절1) 규칙이지 화면 사정이 아니다. FE가 heading_level만 보고 재현하려면
    규정을 다시 구현해야 하므로 우리가 넣는다.
  · `Draft.contents` = 그 초안의 통 문자열. **선택 초안과 같은 앞뒤 빈 줄**을 단다 —
    빈 줄은 초안 내용이 아니라 요소의 위치(제목인가 표인가)가 정하는 값이다.
  · 불변식 `contents == drafts[selected_idx].contents`.
  · `RuleTrail.line_no` = 0 고정, `col_*` = 이 문자열의 문자 오프셋(`\\n`도 1문자).

이력: 07-28 '항목 = 초안' → 07-31 '항목 = 32칸 조판 줄'(BE proto) →
08-05 '항목 = 통 문자열'(조판 가이드, AI finalize 폐기). 세 번 다 직렬화 경계만 바뀌었다.
`/finalize`는 그 시기 응답을 저장해 둔 BE를 위해 여러 형식을 계속 받는다.

이 파일이 지키는 것:
  1. `_selected_lines`가 통 문자열 1개를 낸다(빈 요소는 빈 배열 유지).
  2. 구조적 빈 줄이 `\\n`으로 실려 있고, 요소를 이어 붙이면 지침대로 배치된다.
  3. 불변식 `contents == drafts[selected_idx].contents`.
  4. 초안 **정규 순서를 재배열하지 않는다**(라벨·근거가 순서에 묶여 있다).
  5. `/finalize`가 줄 배열·줄바꿈 결합 두 형식을 모두 받는다.
"""
from __future__ import annotations

from uuid import uuid4

from app.ai.braille.layout_braille import flatten_elements
from app.core.pipeline import _draft_contents, _selected_lines
from app.core.routes import FinalizeBlock
from app.schemas.content import BrailleOutput, RuleApplication
from app.schemas.layout import BBoxItem, LayoutResult

_L1 = "⠓⠣⠉⠁"
_L2 = "⠑⠕⠃⠎"
_L3 = "⠠⠍⠓⠪⠁"


class _D:
    """Draft 최소 대역."""

    def __init__(self, lines, label=""):
        self.braille_lines = lines
        self.label = label
        self.text = ""


def _flat_of(lines, *, etype="text", hlevel=0, drafts=None, selected_idx=0, trail=None):
    """요소 하나를 flatten해 (BrailleOutput, flat dict)를 준다."""
    eid = uuid4()
    bo = BrailleOutput(
        element_id=eid, braille_lines=list(lines),
        rule_trail=list(trail or []),
    )
    bo.drafts = drafts or []
    bo.selected_idx = selected_idx
    lr = LayoutResult(
        page_id="p1",
        elements=[BBoxItem(element_id=eid, type=etype, bbox=(0, 0, 1, 1),
                           reading_order=1, heading_level=hlevel or None)],
    )
    return bo, flatten_elements([bo], lr)


class TestSelectedLines:
    def test_통_문자열_하나를_낸다(self) -> None:
        bo, flat = _flat_of([_L1, _L2, _L3])
        got = _selected_lines(bo, flat)
        assert len(got) == 1
        assert got[0].splitlines() == [_L1, _L2, _L3]

    def test_한_줄짜리(self) -> None:
        bo, flat = _flat_of([_L1])
        assert _selected_lines(bo, flat) == [_L1 + "\n"]

    def test_빈_요소는_빈_배열(self) -> None:
        """빈 문자열 1개짜리 배열을 만들지 않는다 — BE가 '내용 있음'으로 오인한다."""
        bo, flat = _flat_of([])
        assert _selected_lines(bo, flat) == []

    def test_공백만_있는_요소도_빈_배열(self) -> None:
        bo, flat = _flat_of(["", "  "])
        assert _selected_lines(bo, flat) == []

    def test_None이면_빈_배열(self) -> None:
        assert _selected_lines(None, {}) == []

    def test_본문에는_빈_줄이_안_붙는다(self) -> None:
        bo, flat = _flat_of([_L1, _L2], etype="text", hlevel=0)
        assert _selected_lines(bo, flat)[0] == f"{_L1}\n{_L2}\n"


class TestStructuralBlanks:
    """구조적 빈 줄 — 지침 규칙(BBPG 2장2절1·2장2절2)이 통 문자열 안에 실려야 한다."""

    def test_1단계_제목은_앞_두_줄_뒤_한_줄(self) -> None:
        bo, flat = _flat_of([_L1], etype="title", hlevel=1)
        assert _selected_lines(bo, flat)[0] == f"\n\n{_L1}\n\n"

    def test_2단계_제목은_앞뒤_한_줄(self) -> None:
        bo, flat = _flat_of([_L1], etype="title", hlevel=2)
        assert _selected_lines(bo, flat)[0] == f"\n{_L1}\n\n"

    def test_표는_위아래_한_줄(self) -> None:
        bo, flat = _flat_of([_L1], etype="table", hlevel=0)
        assert _selected_lines(bo, flat)[0] == f"\n{_L1}\n\n"

    def test_이어_붙이면_지침대로_배치된다(self) -> None:
        """FE는 order대로 이어 붙이기만 한다 — 그 결과가 지침 배치여야 한다."""
        ids = [uuid4() for _ in range(3)]
        lr = LayoutResult(page_id="p1", elements=[
            BBoxItem(element_id=ids[0], type="title", bbox=(0, 0, 1, 1),
                     reading_order=1, heading_level=2),
            BBoxItem(element_id=ids[1], type="text", bbox=(0, 0, 1, 1), reading_order=2),
            BBoxItem(element_id=ids[2], type="table", bbox=(0, 0, 1, 1), reading_order=3),
        ])
        bos = [BrailleOutput(element_id=ids[0], braille_lines=[_L1]),
               BrailleOutput(element_id=ids[1], braille_lines=[_L2, _L3]),
               BrailleOutput(element_id=ids[2], braille_lines=[_L1])]
        flat = flatten_elements(bos, lr)
        stream = "".join(flat[i].text for i in ids)
        assert stream.split("\n") == [
            "",           # 2단계 제목 앞 한 줄
            _L1,          # 제목
            "",           # 제목 뒤 한 줄
            _L2, _L3,     # 본문
            "",           # 표 위 한 줄
            _L1,          # 표
            "", "",       # 표 아래 한 줄 + 마지막 줄 종료 개행
        ]

    def test_인접_빈_줄은_겹치지_않는다(self) -> None:
        """제목 뒤 한 줄과 표 위 한 줄이 만나면 두 줄이 아니라 한 줄이다."""
        ids = [uuid4(), uuid4()]
        lr = LayoutResult(page_id="p1", elements=[
            BBoxItem(element_id=ids[0], type="title", bbox=(0, 0, 1, 1),
                     reading_order=1, heading_level=2),
            BBoxItem(element_id=ids[1], type="table", bbox=(0, 0, 1, 1), reading_order=2),
        ])
        bos = [BrailleOutput(element_id=ids[0], braille_lines=[_L1]),
               BrailleOutput(element_id=ids[1], braille_lines=[_L2])]
        flat = flatten_elements(bos, lr)
        stream = "".join(flat[i].text for i in ids)
        assert stream.split("\n") == ["", _L1, "", _L2, "", ""]

    def test_빈_요소는_빈_줄도_만들지_않는다(self) -> None:
        bo, flat = _flat_of([], etype="title", hlevel=1)
        assert bo.element_id not in flat


class TestRuleTrailCoords:
    """좌표계 = 통 문자열 문자 오프셋. line_no는 0 고정."""

    def _rule(self, line_no, col_start, col_end):
        return RuleApplication(rule_id="R", source="s", section="1", title="t",
                               excerpt="e", line_no=line_no,
                               col_start=col_start, col_end=col_end, tag="symbol")

    def test_첫_줄_좌표(self) -> None:
        bo, flat = _flat_of([_L1, _L2], trail=[self._rule(0, 1, 3)])
        fe = flat[bo.element_id]
        assert fe.trail[0].line_no == 0
        assert fe.text[fe.trail[0].col_start:fe.trail[0].col_end] == _L1[1:3]

    def test_둘째_줄_좌표는_개행을_센다(self) -> None:
        bo, flat = _flat_of([_L1, _L2], trail=[self._rule(1, 0, 2)])
        fe = flat[bo.element_id]
        assert fe.trail[0].col_start == len(_L1) + 1   # 줄 끝 개행 1문자
        assert fe.text[fe.trail[0].col_start:fe.trail[0].col_end] == _L2[:2]

    def test_구조적_빈_줄만큼_밀린다(self) -> None:
        bo, flat = _flat_of([_L1], etype="title", hlevel=1, trail=[self._rule(0, 0, 2)])
        fe = flat[bo.element_id]
        assert fe.trail[0].col_start == 2              # 앞 빈 줄 두 개
        assert fe.text[fe.trail[0].col_start:fe.trail[0].col_end] == _L1[:2]

    def test_요소_전체_태그는_본문_전_구간(self) -> None:
        bo, flat = _flat_of([_L1, _L2], etype="title", hlevel=2, trail=[self._rule(-1, 0, 0)])
        fe = flat[bo.element_id]
        r = fe.trail[0]
        assert r.line_no == 0
        assert fe.text[r.col_start:r.col_end] == f"{_L1}\n{_L2}"


class TestDraftsInvariant:
    """불변식: contents == drafts[selected_idx].contents"""

    def test_선택_초안과_상위_contents가_같다(self) -> None:
        sel = 2
        drafts = [_D([_L1]), _D([_L2]), _D([_L3, _L1]), _D([_L2, _L3])]
        bo, flat = _flat_of(list(drafts[sel].braille_lines),
                            drafts=drafts, selected_idx=sel)
        assert _selected_lines(bo, flat) == _draft_contents(bo, drafts[sel], flat)

    def test_초안마다_같은_구조적_빈_줄이_붙는다(self) -> None:
        """피커로 초안을 바꿔도 앞뒤 빈 줄은 그대로여야 한다."""
        drafts = [_D([_L1]), _D([_L2, _L3])]
        bo, flat = _flat_of([_L1], etype="image", hlevel=0, drafts=drafts)
        got = [_draft_contents(bo, d, flat)[0] for d in drafts]
        assert got[0] == f"\n{_L1}\n\n"
        assert got[1] == f"\n{_L2}\n{_L3}\n\n"

    def test_정규_순서를_재배열하지_않는다(self) -> None:
        """라벨·근거가 순서에 묶여 있어 선택된 초안을 앞으로 끌어오면 안 된다."""
        drafts = [_D([_L1], "생략"), _D([_L2], "짧은 제목"), _D([_L3], "개조식")]
        bo, flat = _flat_of([_L3], drafts=drafts, selected_idx=2)
        assert [d.label for d in drafts] == ["생략", "짧은 제목", "개조식"]
        assert _draft_contents(bo, drafts[0], flat)[0].strip() == _L1

    def test_빈_초안도_자리를_지킨다(self) -> None:
        """생략 초안은 점자가 비어 있다 — 항목이 사라지면 selected_idx가 어긋난다."""
        drafts = [_D([]), _D([_L1])]
        bo, flat = _flat_of([_L1], drafts=drafts, selected_idx=1)
        got = [_draft_contents(bo, d, flat) for d in drafts]
        assert len(got) == 2
        assert got[0][0].strip() == ""
        assert got[1][0].strip() == _L1


class TestFinalizeAcceptsBothForms:
    """BE가 옛 형식 응답을 저장해 뒀을 수 있어 결합 형식도 계속 받는다."""

    def test_줄_배열_형식(self) -> None:
        assert FinalizeBlock(lines=[_L1, _L2]).normalized_lines() == [_L1, _L2]

    def test_줄바꿈_결합_형식(self) -> None:
        assert FinalizeBlock(lines=[f"{_L1}\n{_L2}"]).normalized_lines() == [_L1, _L2]

    def test_두_형식이_같은_결과(self) -> None:
        a = FinalizeBlock(lines=[_L1, _L2, _L3]).normalized_lines()
        c = FinalizeBlock(lines=[f"{_L1}\n{_L2}\n{_L3}"]).normalized_lines()
        assert a == c

    def test_혼합_형식도_펴진다(self) -> None:
        b = FinalizeBlock(lines=[f"{_L1}\n{_L2}", _L3])
        assert b.normalized_lines() == [_L1, _L2, _L3]

    def test_빈_블록(self) -> None:
        assert FinalizeBlock().normalized_lines() == []


def test_왕복_직렬화_후_줄이_안_깨진다() -> None:
    """AI 응답(통 문자열) → BE 저장 → /finalize 왕복에서 줄이 보존된다."""
    bo, flat = _flat_of([_L1, _L2, _L3])
    serialized = _selected_lines(bo, flat)                          # AI → BE
    restored = FinalizeBlock(lines=serialized).normalized_lines()   # BE → AI
    assert [ln for ln in restored if ln] == [_L1, _L2, _L3]
