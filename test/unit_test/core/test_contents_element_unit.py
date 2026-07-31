"""`contents` 직렬화 계약 — BE proto 기준(줄 배열).

계약(`protos/braille_service.proto`):
  · `TextElement.contents` = **선택 초안의 32칸 조판 줄 배열**. 항목 하나 = 줄 하나.
  · `Draft.contents`       = 그 초안의 점자 줄 배열. 시각 요소만 채운다(본문·수식은 `drafts=[]`).
  · 불변식 `contents == drafts[selected_idx].contents` — BE는 타입 구분 없이 항상
    `contents`로 렌더하고, 피커를 붙이는 FE만 `drafts`를 추가로 읽는다.
  · `RuleTrail.line_no` = 이 배열의 인덱스.

이력: 2026-07-28에 '항목 = 초안, 줄은 `\\n`' 형식으로 바꿨다가 2026-07-31 BE proto에
맞춰 되돌렸다. 내부 표현(줄 리스트)은 그동안에도 바뀐 적이 없고 직렬화 경계만 오갔다.
`/finalize`는 그 시기 응답을 저장해 둔 BE를 위해 두 형식을 계속 받는다.

이 파일이 지키는 것:
  1. `_selected_lines`가 줄 배열을 그대로 낸다(빈 요소는 빈 배열 유지).
  2. 불변식 `contents == drafts[selected_idx].contents`.
  3. 초안 **정규 순서를 재배열하지 않는다**(라벨·근거가 순서에 묶여 있다).
  4. `/finalize`가 줄 배열·줄바꿈 결합 **두 형식을 모두** 받는다.
"""
from __future__ import annotations

from app.core.pipeline import _selected_lines
from app.core.routes import FinalizeBlock

_L1 = "⠓⠣⠉⠁"
_L2 = "⠑⠕⠃⠎"
_L3 = "⠠⠍⠓⠪⠁"


class _D:
    """Draft 최소 대역."""
    def __init__(self, lines, label=""):
        self.braille_lines = lines
        self.label = label
        self.text = ""


class _BO:
    """BrailleOutput 최소 대역.

    layout이 `braille_lines`를 **선택 초안의 조판 결과**로 write-back한다
    (`layout_braille._layout_one`). 대역도 그 상태를 재현한다.
    """
    def __init__(self, lines, drafts=None, selected_idx=0):
        self.braille_lines = lines
        self.drafts = drafts or []
        self.selected_idx = selected_idx


def _drafts_payload(bo) -> list[dict]:
    """pipeline._build_response의 drafts 직렬화와 같은 표현식."""
    return [{"text": d.text, "label": d.label, "contents": list(d.braille_lines)}
            for d in bo.drafts]


class TestSelectedLines:
    def test_줄_배열을_그대로_낸다(self) -> None:
        assert _selected_lines(_BO([_L1, _L2, _L3])) == [_L1, _L2, _L3]

    def test_한_줄짜리(self) -> None:
        assert _selected_lines(_BO([_L1])) == [_L1]

    def test_빈_요소는_빈_배열(self) -> None:
        """빈 문자열 1개짜리 배열을 만들지 않는다 — BE가 '내용 있음'으로 오인한다."""
        assert _selected_lines(_BO([])) == []

    def test_None이면_빈_배열(self) -> None:
        assert _selected_lines(None) == []

    def test_빈_줄도_보존된다(self) -> None:
        """제목 앞뒤 빈 줄은 조판 규칙이라 사라지면 안 된다."""
        assert _selected_lines(_BO([_L1, "", _L2])) == [_L1, "", _L2]

    def test_원본_리스트를_공유하지_않는다(self) -> None:
        """응답 dict를 나중에 손대도 BrailleOutput이 오염되면 안 된다."""
        src = [_L1, _L2]
        got = _selected_lines(_BO(src))
        got.append(_L3)
        assert src == [_L1, _L2]


class TestDraftsInvariant:
    """BE proto 불변식: contents == drafts[selected_idx].contents"""

    def test_선택_초안과_상위_contents가_같다(self) -> None:
        sel = 2
        drafts = [_D([_L1]), _D([_L2]), _D([_L3, _L1]), _D([_L2, _L3])]
        bo = _BO(list(drafts[sel].braille_lines), drafts=drafts, selected_idx=sel)
        assert _selected_lines(bo) == _drafts_payload(bo)[sel]["contents"]

    def test_초안이_넷이면_drafts도_넷(self) -> None:
        bo = _BO([_L1], drafts=[_D([_L1]), _D([_L2]), _D([_L3]), _D([_L1, _L2])])
        assert len(_drafts_payload(bo)) == 4

    def test_정규_순서를_재배열하지_않는다(self) -> None:
        """라벨·근거가 순서에 묶여 있어 선택된 초안을 앞으로 끌어오면 안 된다."""
        bo = _BO([_L3], drafts=[_D([_L1], "생략"), _D([_L2], "짧은 제목"),
                                _D([_L3], "개조식")], selected_idx=2)
        got = _drafts_payload(bo)
        assert [d["label"] for d in got] == ["생략", "짧은 제목", "개조식"]
        assert got[0]["contents"] == [_L1]

    def test_빈_초안도_자리를_지킨다(self) -> None:
        """생략 초안은 점자가 비어 있다 — 항목이 사라지면 selected_idx가 어긋난다."""
        bo = _BO([_L1], drafts=[_D([]), _D([_L1])], selected_idx=1)
        assert [d["contents"] for d in _drafts_payload(bo)] == [[], [_L1]]

    def test_본문_수식은_drafts가_비어_있다(self) -> None:
        assert _drafts_payload(_BO([_L1, _L2])) == []


class TestFinalizeAcceptsBothForms:
    """BE가 7/28~7/31 사이 응답을 저장해 뒀을 수 있어 결합 형식도 계속 받는다."""

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


def test_왕복_직렬화_후_조판_입력이_동일하다() -> None:
    """AI 응답(contents) → BE 저장 → FE 편집 → /finalize 왕복에서 줄이 안 깨진다."""
    original = [_L1, _L2, _L3]
    serialized = _selected_lines(_BO(original))                     # AI → BE
    restored = FinalizeBlock(lines=serialized).normalized_lines()   # BE → AI
    assert restored == original
