"""인라인 태그 파서 회귀 테스트 — plan §3-5 / testdata_complex.txt 정본 대조.

순환검증 금지(test_guide 원칙 1): 기대 점자 글리프는 BBPG 규정·testdata_complex.txt에서
수동 도출한다(생산 코드로 생성하지 않음). 테두리·마커 글리프는 braillify 유무와 무관하게
고정이므로 결정적으로 단언한다. 제목 텍스트 점자(braillify 의존)는 구조만 검사하거나
braillify 설치 시에만 정본 대조한다.
"""
from __future__ import annotations

import pytest

from app.ai.braille import translator as _tr
from app.ai.braille.translator import (
    TN_MARKER,
    substitute_tags,
    tn_marker_spans,
    translate_tagged_text,
)


class TestPointMarkers:
    def test_점역자주_양끝_마커(self):
        out = translate_tagged_text("<!점역자주>그림 설명<!/점역자주>")
        assert out.startswith(TN_MARKER)
        assert out.endswith(TN_MARKER)
        assert out.count(TN_MARKER) == 2  # 내부 ⠠⠄ 없는 일반 텍스트 → 양끝만

    def test_점역자주_한글음절_버그_없음(self):
        # 구버그: [점역사주]/점역자주 한글이 그대로 점자화되면 안 됨
        out = translate_tagged_text("<!점역자주>치킨<!/점역자주>")
        assert "⠨⠎⠢⠱⠁⠇⠨⠍" not in out   # "점역자주" 음절
        assert "⠨⠎⠢⠱⠁⠠⠣⠨⠍" not in out  # "점역사주" 음절

    def test_점역자주_구형식_동일토큰(self):
        out = translate_tagged_text("<!점역자주>X<!점역자주>")
        assert out.startswith(TN_MARKER) and out.endswith(TN_MARKER)

    def test_표빈칸(self):
        assert "⠿⠿" in substitute_tags("성명 <!표빈칸>")

    def test_네모빈칸(self):
        assert "⠸⠦" in substitute_tags("동의 <!네모빈칸> 예 <!네모빈칸> 아니오")

    def test_미지태그_안전제거(self):
        out = substitute_tags("도형 1<!직사각형> 끝")
        assert "<!직사각형>" not in out
        assert "<!" not in out and "!>" not in out


class TestBorder:
    """글상자=표 테두리 (BBPG-1.2.5). 캡 ⠿, 위 채움 ⠛(=g), 아래 채움 ⠶(=7), 32칸."""

    def test_위테두리_제목없음_전체채움(self):
        out = substitute_tags("<!표윗테두리><!/표윗테두리>")
        assert out == "⠿" + "⠛" * 30 + "⠿"
        assert len(out) == 32

    def test_아랫테두리_제목없음_전체채움(self):
        out = substitute_tags("<!표아랫테두리><!/표아랫테두리>")
        assert out == "⠿" + "⠶" * 30 + "⠿"
        assert len(out) == 32

    def test_위테두리_제목_32칸_7칸배치(self):
        # BBPG-1.2.5(4)②: 제목 7번째 칸부터, 양옆 한 칸 띔
        out = substitute_tags("<!표윗테두리>범례<!/표윗테두리>")
        assert len(out) == 32
        assert out.startswith("⠿⠛⠛⠛⠛⠀")  # 캡1+채움4+빈칸1 → 제목 col7
        assert out.endswith("⠿")

    def test_위테두리_구형식_동일토큰(self):
        out = substitute_tags("<!표윗테두리>범례<!표윗테두리>")
        assert len(out) == 32

    @pytest.mark.skipif(not _tr._BRAILLIFY_AVAILABLE,
                        reason="braillify 필요 — testdata_complex.txt 정본 점자 대조")
    def test_위테두리_범례_testdata_정본대조(self):
        # testdata_complex.txt 60행 (글상자 범례 위 테두리, 태민 정본)
        expect = "⠿⠛⠛⠛⠛⠀⠘⠎⠢⠐⠌⠀⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠿"
        assert substitute_tags("<!표윗테두리>범례<!/표윗테두리>") == expect


class TestTnMarkerSpans:
    def test_open_close(self):
        assert tn_marker_spans("⠠⠄⠁⠃⠠⠄") == [(0, 2, "tn_open"), (4, 6, "tn_close")]

    def test_단일마커_open만(self):
        assert tn_marker_spans("⠠⠄⠁⠃") == [(0, 2, "tn_open")]

    def test_마커없음(self):
        assert tn_marker_spans("⠁⠃⠉") == []


class TestTnFalsePositiveB1:
    """B1 회귀: ∽(닮음)·ː(장음)은 점역자 주와 동일 점형(⠠⠄)이지만 오인 금지.

    근본 해결: 출력 점자 스캔이 아니라 '원본 태그 유무'로 점역자 주 마커를 판정한다.
    """

    def test_source_has_tn_태그있음(self):
        assert _tr.source_has_tn("<!점역자주>설명<!/점역자주>")

    def test_source_has_tn_기호만(self):
        # ∽·ː만 있고 점역자 주 태그가 없으면 False
        assert not _tr.source_has_tn("삼각형 ABC ∽ DEF")
        assert not _tr.source_has_tn("모ː음 표시")

    def test_source_has_tn_무관태그(self):
        assert not _tr.source_has_tn("도형 <!직사각형> 끝")

    def test_marker_spans_source_gate_기호(self):
        # ∽ → ⠠⠄ 점자가 있어도 원본에 TN 태그 없으면 emit 안 함
        assert tn_marker_spans("⠠⠄⠁⠃", "ABC ∽ DEF") == []

    def test_marker_spans_source_gate_진짜TN(self):
        spans = tn_marker_spans("⠠⠄⠁⠃⠠⠄", "<!점역자주>x<!/점역자주>")
        assert spans == [(0, 2, "tn_open"), (4, 6, "tn_close")]

    def test_marker_spans_source_none이면_무게이트(self):
        # source 미전달 시 기존 순수 스캐너 동작 유지
        assert tn_marker_spans("⠠⠄⠁⠃⠠⠄") == [(0, 2, "tn_open"), (4, 6, "tn_close")]


class TestTnFalsePositivePipeline:
    """text_braille 파이프라인 레벨 B1 회귀."""

    @staticmethod
    def _trail(corrected_text: str):
        import uuid

        from app.ai.braille.text_braille import TextBraille
        from app.schemas.content import LLMOutput

        opt = LLMOutput(
            element_id=str(uuid.uuid4()),
            corrected_text=corrected_text,
            render_mode="text_only",
            routing_tier="ZERO",
        )
        return TextBraille().translate([opt])[0].rule_trail

    def test_닮음기호_점역자주_오탐없음(self):
        # 수학 교과서 빈발: "∽"가 ⠠⠄로 변환돼도 점역자 주(TN)로 잡히면 안 됨.
        # Phase B: ∽은 닮음(KBR-수학-4.42)으로 정상 기록되되 TN 태그는 없어야 한다.
        trail = self._trail("삼각형 ABC ∽ DEF 이다")
        assert not any(r.tag in ("tn_open", "tn_close") for r in trail)
        assert all(r.rule_id != "BBPG-1.2.6" for r in trail)
        assert any(r.rule_id == "KBR-수학-4.42" for r in trail)  # 닮음으로 정상 emit

    def test_장음기호_오탐없음(self):
        # ː(긴소리표)도 ⠠⠄지만 TN 아님 → 긴소리표(KBR-6.14.63)로 정상 기록.
        trail = self._trail("모ː음 표시")
        assert not any(r.tag in ("tn_open", "tn_close") for r in trail)
        assert all(r.rule_id != "BBPG-1.2.6" for r in trail)
        assert any(r.rule_id == "KBR-6.14.63" for r in trail)

    def test_진짜_점역자주_emit(self):
        # 점역자 주 태그만 있는 경우 — 내부에 ∽·ː 없으므로 심볼 emit 없이 TN만.
        trail = self._trail("<!점역자주>그림 설명<!/점역자주>")
        assert [r.tag for r in trail] == ["tn_open", "tn_close"]


class TestSymbolRuleEmit:
    """Phase B: 특수기호·수식 → rule_trail rule_id emit (세분 인용)."""

    @staticmethod
    def _trail(corrected_text: str):
        import uuid

        from app.ai.braille.text_braille import TextBraille
        from app.schemas.content import LLMOutput

        opt = LLMOutput(
            element_id=str(uuid.uuid4()),
            corrected_text=corrected_text,
            render_mode="text_only",
            routing_tier="ZERO",
        )
        return TextBraille().translate([opt])[0].rule_trail

    def test_모든_매핑_rule_id_DB실재(self):
        # 환각 0: emit 가능한 모든 rule_id ⊆ regulations.json (make_rule KeyError 방지)
        from app.ai.braille.regulations import all_rule_ids
        from app.ai.braille.symbol_rules import SYMBOL_RULE_IDS

        db = all_rule_ids()
        missing = {r for r in SYMBOL_RULE_IDS.values() if r not in db}
        assert not missing, f"DB에 없는 rule_id: {missing}"

    def test_섭씨_세분인용(self):
        from app.ai.braille.symbol_rules import symbol_rule_spans
        from app.ai.braille.translator import translate_tagged_text

        src = "온도는 25℃이다"
        spans = symbol_rule_spans(src, translate_tagged_text(src))
        assert any(rid == "KBR-6.14.69" for _, _, rid in spans)

    def test_세분인용_가운뎃점_줄임표_쌍반점(self):
        from app.ai.braille.symbol_rules import SYMBOL_RULE_IDS

        # 태민 결정: 전용 항으로 세분 (제49 단일 아님)
        assert SYMBOL_RULE_IDS["·"] == "KBR-6.13.50"
        assert SYMBOL_RULE_IDS["…"] == "KBR-6.13.53"
        assert SYMBOL_RULE_IDS[";"] == "KBR-6.14.59"
        assert SYMBOL_RULE_IDS["("] == "KBR-6.13.49"  # 괄호는 제49항 유지

    def test_수학기호_emit(self):
        # 집합 ∈ → 7.60, 닮음 ∽ → 4.42, 등호 = → 1.3
        trail = self._trail("A ∈ B, △ABC ∽ △DEF, x = y")
        rids = {r.rule_id for r in trail}
        assert "KBR-수학-7.60" in rids
        assert "KBR-수학-4.42" in rids
        assert "KBR-수학-1.3" in rids

    def test_source_gate_오탐없음(self):
        # 기호 없는 평범한 텍스트 → 심볼 trail 없음
        trail = self._trail("평범한 한국어 문장입니다")
        assert all(r.tag != "symbol" for r in trail)

    def test_미매핑기호_emit제외(self):
        # 미검증/규정DB 부재 기호(∥ 평행·노름 모호, ⋯ 생략, ↗ 점역자정의 대각)는 trail 없음(환각 0)
        from app.ai.braille.symbol_rules import SYMBOL_RULE_IDS

        for excluded in ("∥", "⋯", "↗"):
            assert excluded not in SYMBOL_RULE_IDS

    def test_근삿값_총합_근호_매핑(self):
        # ≒ 근삿값(제20항 2.20), ∑ 총합(제25항 2.25), √ 근호(제22항 2.22) — 규정 검증 후 추가
        from app.ai.braille.symbol_rules import SYMBOL_RULE_IDS

        assert SYMBOL_RULE_IDS["≒"] == "KBR-수학-2.20"
        assert SYMBOL_RULE_IDS["∑"] == "KBR-수학-2.25"
        assert SYMBOL_RULE_IDS["√"] == "KBR-수학-2.22"


class TestSyllableBreaks:
    """BBPG-1.2.1 음절 줄바꿈 — translate_with_breaks가 단위(수·약자·점역자주 마커)
    내부에는 줄바꿈 지점을 만들지 않고, 어절 경계는 항상 보장한다(접두 일관성)."""

    def test_숫자_단위_내부_미분리(self):
        from app.ai.braille.translator import translate_with_breaks

        lines, breaks = translate_with_breaks("답은 25일이다")
        ln, bk = lines[0], breaks[0]
        i = ln.index("⠼")                       # 수표 위치
        assert not any(i < b < i + 3 for b in bk), f"수(⠼…) 내부 줄바꿈: off={bk}"

    def test_약자_내부_미분리(self):
        from app.ai.braille.translator import translate_with_breaks

        # '그래서' = 약자 ⠁⠎(2칸) → 내부 offset 1에 줄바꿈 없음
        lines, breaks = translate_with_breaks("그래서 우리는")
        assert 1 not in breaks[0], f"약자 내부 줄바꿈: {breaks[0]}"

    def test_점역자주_마커_내부_미분리(self):
        from app.ai.braille.translator import TN_MARKER, translate_with_breaks

        lines, breaks = translate_with_breaks("<!점역자주>설명 내용<!/점역자주>")
        ln, bk = lines[0], breaks[0]
        m = ln.find(TN_MARKER)
        while m != -1:
            assert (m + 1) not in bk, f"점역자주 마커 내부 줄바꿈: m={m} off={bk}"
            m = ln.find(TN_MARKER, m + len(TN_MARKER))

    def test_어절경계_항상_줄바꿈가능(self):
        # 한영 혼합 등 접두가 깨져도 공백(어절 경계)은 바닥선으로 보장
        from app.ai.braille.translator import translate_with_breaks

        lines, breaks = translate_with_breaks("ABC 그리고 DEF")
        ln, bk = lines[0], breaks[0]
        space_offsets = [i for i, ch in enumerate(ln) if ch in (" ", "⠀")]
        assert space_offsets and all(s in bk for s in space_offsets)


class TestElementLocalCoords:
    """요소-로컬 좌표(line_no/col_start/col_end) — 태민 결정 2026-06-02.

    FE/BE는 계산하지 않고 contents[line_no][col_start:col_end]만 하이라이트한다.
    좌표가 실제 점자 셀을 정확히 가리키는지(조판 in-place 변형 후에도) 회귀 검증.
    """

    @staticmethod
    def _bo(corrected_text: str):
        import uuid

        from app.ai.braille.text_braille import TextBraille
        from app.schemas.content import LLMOutput

        opt = LLMOutput(
            element_id=str(uuid.uuid4()), corrected_text=corrected_text,
            render_mode="text_only", routing_tier="ZERO",
        )
        return TextBraille().translate([opt])[0]

    def test_좌표_경계_불변(self):
        # line_no>=0 entry는 contents 배열 안 유효 범위(0<=col_start<=col_end<=len(line))를 가리킨다.
        bo = self._bo("온도는 25℃이고 A ∈ B 이다")
        for r in bo.rule_trail:
            if r.line_no < 0:
                continue  # -1 = 요소 전체
            assert 0 <= r.line_no < len(bo.braille_lines)
            line = bo.braille_lines[r.line_no]
            assert 0 <= r.col_start <= r.col_end <= len(line)

    def test_점역자주_마커_좌표_정확(self):
        from app.ai.braille.translator import TN_MARKER

        bo = self._bo("<!점역자주>그림 설명<!/점역자주>")
        marks = [r for r in bo.rule_trail if r.tag in ("tn_open", "tn_close")]
        assert marks, "TN 마커 좌표가 emit돼야 함"
        for r in marks:
            assert bo.braille_lines[r.line_no][r.col_start:r.col_end] == TN_MARKER

    def test_특수기호_좌표_글리프_일치(self):
        from app.ai.braille.symbol_rules import SYMBOL_TABLE

        bo = self._bo("온도는 25℃이다")
        cel = [r for r in bo.rule_trail if r.rule_id == "KBR-6.14.69"]  # 섭씨
        assert cel
        glyph = SYMBOL_TABLE["℃"]
        assert any(
            bo.braille_lines[r.line_no][r.col_start:r.col_end] == glyph for r in cel
        )

    def test_글머리_정정후_좌표(self):
        # _apply_bullet_marker가 글리프를 축소(⠸⠚⠇→⠸⠚)해도 좌표가 셀을 정확히 가리킨다.
        import uuid

        from app.ai.braille.layout_braille import LayoutBraille
        from app.ai.braille.regulations import make_rule
        from app.schemas.content import BrailleOutput

        bo = BrailleOutput(
            element_id=str(uuid.uuid4()), braille_lines=["⠸⠚⠇⠁⠃"],
            rule_trail=[make_rule("KBR-6.13.49", line_no=0, col_start=0, col_end=3, tag="symbol")],
        )
        LayoutBraille()._apply_bullet_marker(bo)
        bullet = next(r for r in bo.rule_trail if r.rule_id == "KBR-6.14.72")
        assert (bullet.line_no, bullet.col_start, bullet.col_end) == (0, 0, 2)
        assert bo.braille_lines[0][bullet.col_start:bullet.col_end] == "⠸⠚"

    def test_글상자_확장후_line_no_재매핑(self):
        # 위 테두리 확장(빈 줄+테두리 삽입)으로 내용 줄이 밀려도 line_no가 갱신돼 셀을 가리킨다.
        import uuid

        from app.ai.braille.layout_braille import LayoutBraille
        from app.ai.braille.regulations import make_rule
        from app.schemas.content import BoxBorder, BrailleOutput

        top = "⠿" + "⠛" * 30 + "⠿"  # 32칸 위 테두리 마커
        bo = BrailleOutput(
            element_id=str(uuid.uuid4()),
            braille_lines=[top, "⠠⠄⠁⠃"],  # idx1 = 내용(앞 ⠠⠄ TN)
            rule_trail=[make_rule("BBPG-1.2.6", line_no=1, col_start=0, col_end=2, tag="tn_open")],
            box_borders=[BoxBorder(kind="top", level=1, title="")],
        )
        LayoutBraille()._expand_box_borders(bo)
        r = bo.rule_trail[0]
        assert r.line_no != 1  # 내용 줄이 밀림
        assert bo.braille_lines[r.line_no][r.col_start:r.col_end] == "⠠⠄"
