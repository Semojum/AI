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


class TestTwoRunSidebar:
    def test_sidebar_split_in_two_runs_still_deferred(self):
        # 생명과학 p114 축소판(이슈 #643): 좌측 열에 보충설명(순번 1~4)과 정답(6~8)이
        # 따로 실려 순번이 두 토막이다. 참고 자료 단이 두 토막이어도 단이므로 후치한다
        # (「점자 도서 제작 지침」 2장 5, 주종 관계의 다단).
        side_a = [_box(1, 72, 75, 231, 160), _box(2, 72, 196, 231, 220),
                  _box(3, 72, 232, 231, 256), _box(4, 72, 278, 231, 330)]
        main = [_box(5, 264, 60, 897, 520)]
        side_b = [_box(6, 73, 865, 113, 879), _box(7, 73, 880, 113, 895),
                  _box(8, 73, 911, 113, 924)]
        main2 = [_box(9, 260, 600, 897, 700), _box(10, 260, 720, 897, 800)]
        items = side_a + main + side_b + main2
        _reorder_columns(items)
        assert _orders(main + main2) == [1, 2, 3]
        assert _orders(side_a + side_b) == [4, 5, 6, 7, 8, 9, 10]

    def test_three_runs_not_deferred(self):
        # 토막이 셋이면 흩어진 라벨과 구분이 안 된다 — 후치하지 않는다.
        side = [_box(1, 72, 100, 231, 160), _box(2, 72, 170, 231, 230),
                _box(3, 72, 240, 231, 300),
                _box(5, 72, 400, 231, 460), _box(6, 72, 470, 231, 530),
                _box(7, 72, 540, 231, 600),
                _box(9, 72, 700, 231, 760), _box(10, 72, 770, 231, 830),
                _box(11, 72, 840, 231, 900)]
        main = [_box(4, 264, 100, 897, 300), _box(8, 264, 400, 897, 600),
                _box(12, 264, 700, 897, 900)]
        items = sorted(side + main, key=lambda b: b.reading_order)
        _reorder_columns(items)
        # 후치됐다면 사이드가 통째로 본문 뒤로 간다 — 그러지 않았음을 본다.
        assert min(b.reading_order for b in side) < min(b.reading_order for b in main)


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


class TestYsortStaysInsideColumn:
    def test_two_column_scrambled_not_interleaved(self):
        # 언어와 매체 p044 축소판: 머리말·꼬리말 조각이 앞뒤로 튀어 y-위반 2회를 만들면
        # y-정렬이 발동한다. 이때 열을 무시하고 정렬하면 좌/우 단이 한 줄씩 번갈아 나온다
        # (실측 τ 1.00 → 0.37). 열 안에서만 정렬해야 좌열 전체 → 우열 전체가 유지된다.
        foot = _box(1, 100, 1390, 350, 1420)       # 꼬리말이 맨 앞에 방출됨
        left = [_box(i + 1, 100, 100 + i * 120, 550, 200 + i * 120) for i in range(5)]
        head = _box(7, 110, 40, 540, 90)           # 머리말이 본문 뒤에 방출됨
        right = [_box(i + 8, 610, 100 + i * 120, 1060, 200 + i * 120) for i in range(5)]
        items = [foot] + left + [head] + right
        _reorder_columns(items)
        got = [b.reading_order for b in sorted(items, key=lambda b: b.reading_order)]
        assert got == list(range(1, len(items) + 1))
        # 좌열 5개가 모두 우열 5개보다 앞에 온다
        assert max(b.reading_order for b in left) < min(b.reading_order for b in right)

    def test_left_column_comes_before_right(self):
        # 열 번호는 x0 오름차순. 오른쪽 단이 먼저 방출돼도 좌 → 우로 잡아야 한다.
        right = [_box(i + 1, 610, 100 + i * 120, 1060, 200 + i * 120) for i in range(4)]
        left = [_box(i + 5, 100, 100 + i * 120, 550, 200 + i * 120) for i in range(4)]
        stray = _box(9, 100, 1390, 550, 1420)      # y-위반 유발용 꼬리 조각
        stray2 = _box(10, 110, 40, 540, 70)
        _reorder_columns(right + left + [stray, stray2])
        assert max(b.reading_order for b in left) < min(b.reading_order for b in right)


class TestTooManyColumnsUntouched:
    def test_rotated_page_left_alone(self):
        # 270° 회전 페이지(외국어 영역): 줄마다 x가 달라 x-겹침 열이 열 개 넘게 잡힌다.
        # 열 모형이 안 맞는 쪽이라 기하 정렬을 걸면 순서가 통째로 뒤집힌다 → 무변경.
        items = [_box(i + 1, 1300 - i * 40, 187, 1326 - i * 40, 600) for i in range(12)]
        before = _orders(items)
        _reorder_columns(items)
        assert _orders(items) == before


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


# ── 회전 지면(QA Step3 후속, 2026-08-07) ─────────────────────────────────────
# 4열 이상으로 잡히는 쪽 58개 중 57개가 rotation 270°였다(외국어 56·수학2 1).
# 보기엔 평범한 1단 쪽인데 PDF 내부 좌표가 누워 있어 x0가 흩어져 열이 10~30개로 잡힌다.
# 실측(valall 4열+ 47쪽): 원순서 τ 0.677 → 이 규칙 0.996 (LLM opus-5는 0.989·유료).
from app.core.pipeline import _reorder_columns as _rc          # noqa: E402


def _b(order, x0, y0, x1=None, y1=None):
    from app.schemas.layout import BBoxItem
    return BBoxItem(type="text", bbox=(x0, y0, x1 if x1 is not None else x0 + 12,
                                       y1 if y1 is not None else y0 + 40),
                    reading_order=order)


class TestRotatedPage:
    def _many_columns(self):
        """세로로 누운 줄 6개 — x가 오른쪽에서 왼쪽으로 진행하는 것이 표시상 위→아래."""
        return [_b(1, 500, 60), _b(2, 440, 60), _b(3, 380, 60),
                _b(4, 320, 60), _b(5, 260, 60), _b(6, 200, 60)]

    def test_270도면_x_내림차순으로_읽는다(self):
        items = self._many_columns()
        _rc(items, rotation=270)
        assert [b.reading_order for b in items] == [1, 2, 3, 4, 5, 6]

    def test_270도_뒤집힌_입력도_바로잡는다(self):
        items = self._many_columns()
        for i, b in enumerate(reversed(items), start=1):   # 순서를 거꾸로 넣어도
            b.reading_order = i
        _rc(items, rotation=270)
        assert [b.reading_order for b in items] == [1, 2, 3, 4, 5, 6]

    def test_90도면_x_오름차순(self):
        items = self._many_columns()
        _rc(items, rotation=90)
        assert [b.reading_order for b in items] == [6, 5, 4, 3, 2, 1]

    def test_회전_아니면_원순서_유지(self):
        items = self._many_columns()
        _rc(items, rotation=0)
        assert [b.reading_order for b in items] == [1, 2, 3, 4, 5, 6]


# ── 다중 시각요소 쪽 (2026-08-09) ────────────────────────────────────────────
# 대표 지적 "그림·표가 여러 개인 쪽에서 읽기순서가 흐트러진다"를 실측해 고친 세 자리.
class TestMultiVisualPage:
    def test_lone_figure_stays_in_body_flow(self):
        # 생물 p026: 본문 옆에 홀로 놓인 아이콘(자기만의 열)이 '연속 순번 + 좁은 폭'을
        # 공짜로 만족해 쪽 맨 뒤로 밀렸다. 낱개 그림은 '참고 자료 단'이 아니다.
        icon = _box(3, 267, 355, 305, 400, etype="chart_graph")
        main = [_box(1, 400, 100, 1040, 300), _box(2, 400, 320, 1040, 500),
                _box(4, 400, 520, 1040, 900), _box(5, 400, 920, 1040, 1200)]
        _reorder_columns([main[0], main[1], icon, main[2], main[3]])
        assert icon.reading_order == 3
        assert _orders(main) == [1, 2, 4, 5]

    def test_lone_text_label_still_deferred(self):
        # 반대쪽 회귀 방어: 좌측 여백의 낱개 '유형' 라벨(텍스트)은 종전대로 본문 뒤로.
        # (사회문화 p034 — 이걸 같이 막으면 τ 0.927 → 0.709로 떨어진다)
        label = _box(3, 118, 786, 298, 830)
        main = [_box(1, 400, 100, 1040, 300), _box(2, 400, 320, 1040, 500),
                _box(4, 400, 820, 1040, 1000), _box(5, 400, 1020, 1040, 1200)]
        _reorder_columns([main[0], main[1], label, main[2], main[3]])
        assert label.reading_order == 5

    def test_sidebar_deferred_despite_one_stray_member(self):
        # 생물 p180: 좌측 보충설명 열(연속 순번 4개)에 쪽 아래 출전 한 줄이 같은 열로
        # 묶여 '연속'이 깨졌다 → 후치가 막혔다. 블록 3개 이상이면 한 개 이탈은 봐준다.
        side = [_box(i + 1, 96, 200 + i * 150, 264, 320 + i * 150) for i in range(4)]
        stray = _box(9, 138, 1390, 264, 1420)          # 쪽 아래 출전 줄(같은 열)
        main = [_box(i + 5, 309, 130 + i * 300, 1047, 380 + i * 300) for i in range(4)]
        _reorder_columns(side + main + [stray])
        assert max(b.reading_order for b in main) < min(b.reading_order for b in side)

    def test_main_column_is_the_bigger_one_not_the_busier_one(self):
        # 생물 p180: 좁은 보충설명 열이 요소 수만 많아 '본문'으로 뽑혔다.
        # 본문은 면적이 큰 열이다(주종 관계의 다단 — 본문 단이 먼저).
        side = [_box(i + 1, 96, 200 + i * 120, 264, 300 + i * 120) for i in range(6)]
        main = [_box(i + 7, 309, 130 + i * 400, 1047, 500 + i * 400) for i in range(3)]
        _reorder_columns(side + main)
        assert max(b.reading_order for b in main) < min(b.reading_order for b in side)


class TestBridgeElement:
    def test_full_width_title_does_not_glue_two_columns(self):
        # 세계사 p104 축소판: 강 제목(x 151~609)이 좌측 용어열(x 106~283)과
        # 본문(x 318~1071)에 걸쳐 x-겹침 union 이 쪽 전체를 한 덩이로 붙였다.
        # 다리 요소를 클러스터링에서만 빼면 두 단이 갈리고 참고열이 뒤로 간다
        # (「점자 도서 제작 지침」 2장 5, 주종 관계의 다단).
        title = _box(1, 151, 87, 609, 139)
        side = [_box(i + 2, 106, 300 + i * 180, 283, 440 + i * 180) for i in range(4)]
        main = [_box(i + 6, 318, 260 + i * 200, 1071, 420 + i * 200) for i in range(4)]
        _reorder_columns([title] + side + main)
        assert title.reading_order == 1
        assert max(b.reading_order for b in main) < min(b.reading_order for b in side)

    def test_no_bridge_search_when_page_already_splits(self):
        # 이미 두 덩이로 갈리는 쪽은 다리 탐색을 하지 않는다(동작·순서 무변경).
        side = [_box(i + 1, 96, 200 + i * 150, 264, 320 + i * 150) for i in range(3)]
        main = [_box(i + 4, 309, 130 + i * 300, 1047, 380 + i * 300) for i in range(3)]
        _reorder_columns(side + main)
        assert max(b.reading_order for b in main) < min(b.reading_order for b in side)


class TestThreeRunSidebar:
    def test_sidebar_split_in_three_runs_still_deferred(self):
        # 생물 p018 축소판: 좌측 열이 빈칸문제 7개 + 정답 상자 + 낱개로 세 토막이다
        # (runs=[7,1,1]). 최장 토막이 절반 이상이면 한 단으로 본다.
        side = [_box(i + 1, 96, 190 + i * 65, 261, 240 + i * 65) for i in range(7)]
        side.append(_box(12, 107, 1247, 222, 1352))     # 정답 상자(본문 뒤 순번)
        side.append(_box(20, 100, 1380, 240, 1410))     # 낱개 한 줄(맨 끝 순번)
        main = [_box(o, 300, 143 + i * 100, 1044, 220 + i * 100)
                for i, o in enumerate([8, 9, 10, 11, 13, 14, 15, 16, 17, 18, 19])]
        _reorder_columns(side + main)
        assert max(b.reading_order for b in main) < min(b.reading_order for b in side)
