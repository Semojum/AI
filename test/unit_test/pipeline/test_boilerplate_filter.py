"""판권·러닝헤드 보일러플레이트 필터 + 사이드바 재정렬 가드 (GPU 불필요).

정답 BRL 전수조사(1131p)에서 판권·URL·러닝헤드 문구는 출현 0% — 점역사는 전부
제거한다. 파이프라인은 경계 파일 소비 시점(_parse_txt_result)에 해당 요소를 드롭한다.
"""

from __future__ import annotations

from uuid import uuid4

from app.core.pipeline import (
    _is_boilerplate,
    _is_running_foot,
    _parse_txt_result,
    _reorder_sidebar,
)
from app.schemas.layout import BBoxItem


# ── _is_boilerplate ──────────────────────────────────────────────────────

class TestIsBoilerplate:
    def test_observed_variants_dropped(self):
        # 코퍼스 경계 파일 전수에서 실제로 관측된 변형들
        for c in [
            "www.ebsi.co.kr",
            "EBS",
            "EBS 수능특강 언어영역",
            "EBS 수능특강 세계사 | V.아시아 사회의 성숙",
            "EBS 수능특강\\_ 생물 I",
            "EBS 수능특강외국어영역",
            "http://www.ebsi.co.kr",
            "ⓒ EBS 한국교육방송공사",
        ]:
            assert _is_boilerplate(c), c

    def test_body_text_kept(self):
        # content "전체"가 패턴일 때만 드롭 — 본문 문장 속 언급은 보존
        for c in [
            "이 문제는 EBS 교재에서 발췌한 것이다.",
            "자세한 내용은 www.ebsi.co.kr 에서 확인하시오.",
            "EBS는 한국의 공영 방송사이다.",  # 'EBS ' 시작이지만 수능특강 아님 + 단독 아님
            "01 (가), (나)와 관련된 옳은 설명을 고른 것은?",
            "",
        ]:
            assert not _is_boilerplate(c), c


# ── _is_running_foot (header_footer 전용 인쇄 러닝풋) ────────────────────

class TestIsRunningFoot:
    def test_observed_running_feet_suppressed(self):
        # 코퍼스 실측(2026-07-20): gold BRF에 재현되지 않는 인쇄 러닝풋 변형들
        for c in [
            "SCIENCE",                       # 생물 러닝풋
            "수능 SCIENCE 29 테 스트",        # OCR 변형
            "SCIENCE\n수능\n점",
            "<!드러냄>SCIENCE<!/드러냄>",     # 태그 감쌈 변형
            "테스트",                         # 생물 단독 배너
            "中",                             # 사회문화·세계사 장식 OCR 노이즈
            "04 | 혈액의 구성과 혈액형",       # 생물 강 러닝헤더
            "<!드러냄>13 | 유전 형질과 염색체 이상<!/드러냄>",
            "www e b si co k r",              # ebsi URL OCR 흩뿌림 변형
            "w w w e b s i c o k r",
            "www. e b s i . co . k r",
        ]:
            assert _is_running_foot(c), c

    def test_gold_reproduced_headers_kept(self):
        # gold가 유지하는 헤더 — 억제하면 CER 악화(실측)라 반드시 보존
        for c in [
            "Level 1 기초연습",               # 수학2 섹션 배너
            "PartⅢ 테스트편",                 # 외국어 — '테스트' 부분 포함해도 전체일치 아님
            "수능 기본 문제",
            "Exercises",
            "Ⅱ. 개인과 사회 구조",            # 장 표제(도서별 관행 갈림 → 유지)
            "정답과 해설 3쪽",
            "테스트 결과 분석",               # '테스트' 시작이지만 전체 일치 아님
            "",
        ]:
            assert not _is_running_foot(c), c


# ── _parse_txt_result 통합 ───────────────────────────────────────────────

def _el(content: str, etype: str = "text", order: int = 1) -> dict:
    return {"id": str(uuid4()), "order": order, "type": etype, "content": content}


class TestParseDropsBoilerplate:
    def test_boilerplate_elements_dropped_others_kept(self):
        extraction = {
            "meta": {"extraction_method": "OCR"},
            "elements": [
                _el("www.ebsi.co.kr", etype="header_footer", order=1),
                _el("본문 문단입니다.", order=2),
                _el("EBS 수능특강 세계사 | II. 문명의 새벽", order=3),
                _el("EBS", order=4),
                _el("41", etype="page_number", order=5),
            ],
        }
        layout, ext_map, _ = _parse_txt_result(extraction, "p-test")
        types = sorted(b.type for b in layout.elements)
        assert types == ["page_number", "text"]
        assert len(ext_map) == 2

    def test_formula_content_never_dropped(self):
        # 필터는 텍스트 계열 타입에만 적용 — 수식 latex는 건드리지 않는다
        extraction = {
            "meta": {"extraction_method": "OCR"},
            "elements": [_el("EBS", etype="formula")],
        }
        layout, _, _ = _parse_txt_result(extraction, "p-test")
        assert len(layout.elements) == 1

    def test_running_foot_only_dropped_for_header_footer(self):
        # 러닝풋 패턴은 header_footer 타입에만 적용 — 본문 text의 동일 문자열은 보존
        extraction = {
            "meta": {"extraction_method": "OCR"},
            "elements": [
                _el("테스트", etype="header_footer", order=1),
                _el("테스트", etype="text", order=2),
                _el("04 | 혈액의 구성과 혈액형", etype="header_footer", order=3),
                _el("사회 조사 과정과 자료 수집 방법", etype="header_footer", order=4),
            ],
        }
        layout, ext_map, _ = _parse_txt_result(extraction, "p-test")
        kept = [(b.type, ext_map[b.element_id].corrected_text) for b in layout.elements]
        assert ("header_footer", "테스트") not in kept
        assert ("text", "테스트") in kept
        assert ("header_footer", "04 | 혈액의 구성과 혈액형") not in kept
        assert ("header_footer", "사회 조사 과정과 자료 수집 방법") in kept


# ── _reorder_sidebar 다수-스트림 가드 ────────────────────────────────────

def _box(order: int, x0: int, y0: int, x1: int, y1: int, etype: str = "text") -> BBoxItem:
    return BBoxItem(element_id=uuid4(), type=etype, bbox=(x0, y0, x1, y1),
                    reading_order=order)


class TestSidebarGuard:
    def test_majority_left_stream_not_reordered(self):
        # 우측 보조열 페이지: 최대 x0 간격이 본문 오른쪽(우측열↔최우측 요소 사이)에
        # 잡혀 본문(다수)이 "사이드바"로 분류되는 오발동 → 무변경 (세계사 p041 회귀).
        items = [_box(i, 100 + (i - 1) * 140, 100 + i * 100,
                      160 + (i - 1) * 140, 180 + i * 100) for i in range(1, 7)]
        items += [_box(7, 880, 150, 990, 300), _box(8, 1050, 1380, 1076, 1400)]
        before = [b.reading_order for b in items]
        _reorder_sidebar(items, [b for b in items if b.bbox[2] > b.bbox[0]])
        assert [b.reading_order for b in items] == before

    def test_minority_left_sidebar_still_merged(self):
        # 의도된 케이스: 좁은 좌측 사이드바(소수)가 본문 흐름에 y로 끼워진다.
        # MinerU 원순서는 사이드바(페이지 하단, y=900)를 본문보다 먼저 방출.
        sidebar = _box(1, 50, 900, 200, 1000)
        main = [_box(i + 1, 400, 100 + i * 300, 1000, 250 + i * 300) for i in range(4)]
        items = [sidebar] + main
        _reorder_sidebar(items, list(items))
        # 사이드바(y=900)는 y가 앞서는 본문 요소들 뒤로 밀린다
        assert sidebar.reading_order > main[0].reading_order
        assert sidebar.reading_order > main[1].reading_order
