"""추출기 읽기순서가 글상자를 가로지를 때 먼저 모아 준다 (2026-08-10, 원장 C-17 후속).

실측 `EBS-E26-001/0137`: 탐구자료 상자(`[107,78,733,923]`) 안 요소가 `1~16`과 `25~27`로
끊기고 그 사이 `17~24`는 오른쪽 단의 다른 상자(개념 체크, x766~924)다. `tag_boxed_elements`의
연속성 가드가 상자를 통째로 건너뛰어 바깥 상자가 안 생겼고, 그래서 안의 표 셋이 전부 깊이 0
→ 1단계 테두리가 됐다. 정답은 그 표들을 **2단계**로 적는다(도서지침 예3-59).

10쪽 표본 효과: 글상자 태깅 **6 → 8**(page_182 0→1 · page_171 1→2), 악화 0.
"""
from __future__ import annotations

from app.ai.preprocessor.pdf_analyzer import regroup_boxed, tag_boxed_elements

BOX = [100.0, 100.0, 500.0, 900.0]


def _el(i: int, x0: float, y0: float, typ: str = "text") -> dict:
    return {"type": typ, "order": i, "bbox": [x0, y0, x0 + 80, y0 + 20],
            "content": f"e{i}", "id": f"id{i}"}


def _texts(els: list[dict]) -> list[str]:
    return [e["content"] for e in els]


class TestRegroup:
    def test_끼어든_바깥열을_상자_뒤로_뺀다(self) -> None:
        els = [_el(1, 120, 150), _el(2, 120, 200),      # 상자 안
               _el(3, 700, 150), _el(4, 700, 200),      # 오른쪽 단(상자 밖)
               _el(5, 120, 800)]                        # 다시 상자 안
        assert regroup_boxed(els, [BOX]) == 1
        assert _texts(els) == ["e1", "e2", "e5", "e3", "e4"]
        assert [e["order"] for e in els] == [1, 2, 3, 4, 5]   # order 재부여

    def test_이미_연속이면_안_건드린다(self) -> None:
        els = [_el(1, 120, 150), _el(2, 120, 200), _el(3, 700, 150)]
        assert regroup_boxed(els, [BOX]) == 0
        assert _texts(els) == ["e1", "e2", "e3"]

    def test_상자가_없으면_무변경(self) -> None:
        els = [_el(1, 120, 150), _el(2, 700, 150)]
        assert regroup_boxed(els, []) == 0

    def test_요소가_하나뿐인_상자는_넘어간다(self) -> None:
        els = [_el(1, 120, 150), _el(2, 700, 150)]
        assert regroup_boxed(els, [BOX]) == 0

    def test_재정렬_뒤_태깅이_붙는다(self) -> None:
        """이게 이 함수의 존재 이유다 — 재정렬 전에는 상자가 통째로 건너뛰어진다."""
        def fresh() -> list[dict]:
            return [_el(1, 120, 150), _el(2, 120, 200),
                    _el(3, 700, 150), _el(4, 700, 200),
                    _el(5, 120, 800)]
        assert tag_boxed_elements(fresh(), [BOX]) == 0     # 끊긴 채로는 못 붙인다
        els = fresh()
        regroup_boxed(els, [BOX])
        assert tag_boxed_elements(els, [BOX]) == 1
        joined = "\n".join(e["content"] for e in els)
        assert "<!테두리_위>" in joined and "<!테두리_아래>" in joined

    def test_표를_품어도_모은다(self) -> None:
        """표·그림도 상자 안 자리를 차지한다(§3장 지문 (4) 속글상자)."""
        els = [_el(1, 120, 150), _el(2, 120, 300, "table"),
               _el(3, 700, 150), _el(4, 120, 800)]
        assert regroup_boxed(els, [BOX]) == 1
        assert _texts(els) == ["e1", "e2", "e4", "e3"]
