"""_reorder_columns(H3, 운영 기본) — 열 클러스터링 읽기순서 (GPU 불필요).

규칙 근거는 정답 BRL 관찰(2026-07-13, dev 18p): 좁은 용어설명 열은 본문 뒤,
대등 2단은 MinerU 열 순서 보존, MinerU 순서가 뒤죽박죽인 열만 y-정렬.
"""

from __future__ import annotations

from uuid import uuid4

from app.core.pipeline import _reorder_columns
from app.schemas.layout import BBoxItem


def _box(order: int, x0: int, y0: int, x1: int, y1: int, etype: str = "text") -> BBoxItem:
    return BBoxItem(element_id=uuid4(), type=etype, bbox=(x0, y0, x1, y1),
                    reading_order=order)


def _orders(items: list[BBoxItem]) -> list[int]:
    return [b.reading_order for b in items]


class TestPrefixDumpedSidebar:
    def test_narrow_prefix_sidebar_moved_after_main(self):
        # 세계사 p106 축소판: MinerU가 좁은 좌측 용어열(x 106~283)을 본문(x 315~1071)
        # 앞에 연속 방출 → 본문 먼저, 용어열은 뒤로.
        side = [_box(1, 106, 200, 283, 300), _box(2, 106, 350, 283, 700)]
        main = [_box(3, 315, 140, 1071, 380), _box(4, 315, 400, 1071, 550),
                _box(5, 315, 900, 1071, 1000)]
        items = side + main
        _reorder_columns(items)
        assert _orders(main) == [1, 2, 3]
        assert _orders(side) == [4, 5]

    def test_scattered_narrow_labels_keep_position(self):
        # 세계사 p160 축소판: 좁은 좌측 라벨이 본문 사이에 흩어져(비연속 순번) 방출
        # → MinerU 의도 배치로 보고 무변경.
        items = [
            _box(1, 118, 181, 298, 226),    # 라벨1 (문항1 앞)
            _box(2, 327, 158, 853, 400),    # 문항1
            _box(3, 327, 450, 853, 690),    # 문항1 계속
            _box(4, 118, 727, 298, 771),    # 라벨2 (문항2 앞)
            _box(5, 327, 721, 921, 1000),   # 문항2
            _box(6, 327, 1050, 921, 1300),  # 문항2 계속
        ]
        before = _orders(items)
        _reorder_columns(items)
        assert _orders(items) == before


class TestTwoColumnPreserved:
    def test_equal_two_column_page_untouched(self):
        # 대등 2단: MinerU가 좌열 전체 → 우열 전체 순으로 방출(정답과 일치).
        # y-정렬하면 두 열이 섞이므로 무변경이어야 한다 (사회문화 p140 회귀 케이스).
        left = [_box(i, 100, 100 + (i - 1) * 300, 520, 300 + (i - 1) * 300)
                for i in range(1, 5)]
        right = [_box(i + 4, 560, 100 + (i - 1) * 300, 980, 300 + (i - 1) * 300)
                 for i in range(1, 5)]
        items = left + right
        before = _orders(items)
        _reorder_columns(items)
        assert _orders(items) == before


class TestScrambledColumnYsorted:
    def test_scrambled_single_column_restored_by_y(self):
        # 사회문화 p035 축소판: 단일 본문 열인데 MinerU 순번이 y와 무관하게 뒤죽박죽
        # (위반 2회 초과) → y-정렬로 복원.
        a = _box(1, 100, 1300, 900, 1400)   # 실제로는 맨 아래
        b = _box(2, 100, 100, 900, 200)     # 맨 위
        c = _box(3, 100, 900, 900, 1000)
        d = _box(4, 100, 400, 900, 500)
        e = _box(5, 100, 1100, 900, 1200)
        f = _box(6, 100, 600, 900, 700)
        items = [a, b, c, d, e, f]
        _reorder_columns(items)
        assert _orders([b, d, f, c, e, a]) == [1, 2, 3, 4, 5, 6]


class TestPageLineSlotsPreserved:
    def test_page_number_keeps_original_slot(self):
        # 페이지행 요소는 재배열 여파를 받지 않고 원래 순번 슬롯을 지킨다.
        pn = _box(1, 107, 1393, 148, 1415, etype="page_number")
        side = [_box(2, 106, 200, 283, 300), _box(3, 106, 350, 283, 700)]
        main = [_box(4, 315, 140, 1071, 380), _box(5, 315, 400, 1071, 550),
                _box(6, 315, 900, 1071, 1000)]
        items = [pn] + side + main
        _reorder_columns(items)
        assert pn.reading_order == 1
        assert _orders(main) == [2, 3, 4]
        assert _orders(side) == [5, 6]
