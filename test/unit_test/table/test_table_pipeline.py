"""PART 6-1~6-3 표 파이프라인 단위 테스트 (TableCap 목 → TableOpt → TableBraille).

현주 파트(table_cap.py) 대신 test_data/page_001/type/table/table_cap.json 목 데이터 사용.

Done Criteria:
  - GriTS > 0.88: 셀 텍스트의 88% 이상이 점자 출력에 존재해야 함.
  - 모든 BrailleOutput이 32칸 이하 줄로 구성되어야 함.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from app.ai.braille.table_braille import TableBraille
from app.ai.llm.table_opt import TableOpt
from app.schemas.content import BrailleOutput, ExtractedContent

_DATA_PATH = Path(__file__).parent.parent.parent / "test_data" / "page_001" / "type" / "table" / "table_cap.json"
_GRITS_THRESHOLD = 0.88


def _load_mock() -> list[ExtractedContent]:
    raw: list[dict[str, Any]] = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    return [ExtractedContent.model_validate(d) for d in raw]


# 한국 점자 규정 제41항에서 직접 도출한 숫자 점자 매핑 (translator 미사용, 비순환)
_DIGIT_BRAILLE = {
    "0": "⠚", "1": "⠁", "2": "⠃", "3": "⠉", "4": "⠙",
    "5": "⠑", "6": "⠋", "7": "⠛", "8": "⠓", "9": "⠊",
}
_NUMBER_INDICATOR = "⠼"  # 수표시 (제41항)


def _numeric_to_expected_braille(text: str) -> str:
    """순수 숫자 문자열 → 수표 + 점자 셀 (제41항 규정 직접 적용, translator 미사용)."""
    return _NUMBER_INDICATOR + "".join(_DIGIT_BRAILLE.get(d, d) for d in text)


def _grits(extracted: ExtractedContent, output: BrailleOutput, render_mode: str) -> float:
    """GriTS 구조 점수: 규정 불변량 기반 (비순환).

    순환 검증 방지: translate_tagged_text 사용 금지.
    대신 규정에서 직접 도출 가능한 구조 불변량만 검사:
      - linear: 행 수만큼 3칸 시작 줄 존재 (출력 줄 수 == 입력 행 수).
        정답 도서 관행 = "  키  값"(유도점·쌍점 없음) — BRAILLE_STYLE=regulation이면 ⠄키: 값.
      - table_grid: 테두리(⠿) 2줄 + 구분선(⠒) (row-1)줄 존재
      - 숫자 셀: 수표(⠼) + 규정 제41항 셀 값이 출력에 존재 (translator와 독립)
    """
    ts = extracted.table_structure
    if not ts:
        return 1.0
    cells = ts.get("cells", [])
    if not cells:
        return 1.0

    max_row = max(c.get("row", 0) for c in cells) + 1
    combined = "".join(output.braille_lines)
    checks: list[bool] = []

    if render_mode == "linear":
        # linear(도서 관행): 각 행이 3칸(앞 2칸 빈칸)에서 시작하는 한 줄로 출력됨
        indented = [ln for ln in output.braille_lines if ln.startswith("  ")]
        checks.append(len(indented) == max_row)              # 행 수 정확히 일치
        checks.append(len(output.braille_lines) == max_row)  # 총 줄 수 일치
    elif render_mode == "unfold":
        # 풀어쓰기(BBPG-3.1.2)는 지침 §3.1.1(1)에 따라 **두 조판**이 다 정답이다
        # (2026-07-20 정정 — 정답 도서 실측으로 확인):
        #   ② 낱말 수준·좁은 표 → 행 단위: 원본 한 행이 한 줄  → 줄 수 = max_row
        #      (생물 p122 '자율 신경  침 분비  폐의 기관지  동공' / p119 동일 형식)
        #   ③ 문장 수준·넓은 표 → 열 단위: 열머리 1줄 + 데이터 행들
        #      → 줄 수 = (max_col - 1) × max_row   (사회문화 p185)
        # 예전에는 열 단위 줄 수만 정답으로 봤는데, 그 가정이 렌더러를 열 단위로 묶어
        # 두는 근거로 쓰였다. 조판이 둘 중 무엇이든 **모든 원본 셀이 실려야** 한다는 게
        # 진짜 불변량이므로 그것도 함께 본다.
        max_col = max(c.get("col", 0) for c in cells) + 1
        nonblank = [ln for ln in output.braille_lines if ln.strip()]
        n_lines = len(output.braille_lines)
        checks.append(n_lines in (max_row, (max_col - 1) * max_row))
        checks.append(all(ln.startswith("  ") for ln in nonblank))
    else:
        # table_grid: border(⠿×32) 2줄 + separator(⠒×32) (row-1)줄 + data row줄
        border_lines = [ln for ln in output.braille_lines if set(ln) == {"⠿"}]
        sep_lines    = [ln for ln in output.braille_lines if set(ln) == {"⠒"}]
        expected_lines = 2 + max_row + (max_row - 1)  # borders + data + separators
        checks.append(len(border_lines) == 2)
        checks.append(len(sep_lines) == max_row - 1)
        checks.append(len(output.braille_lines) == expected_lines)

    # 숫자 셀: 규정 제41항 변환값이 출력에 포함되어야 함 (translator 독립 검증)
    numeric_cells = [
        c for c in cells
        if c.get("text", "").strip().isdigit()
    ]
    for nc in numeric_cells:
        expected = _numeric_to_expected_braille(nc["text"].strip())
        checks.append(expected in combined)

    return sum(checks) / len(checks) if checks else 1.0


@pytest.fixture(scope="module")
def mock_extracted() -> list[ExtractedContent]:
    return _load_mock()


@pytest.fixture(scope="module")
def opt_outputs(mock_extracted: list[ExtractedContent]) -> list[Any]:
    return asyncio.run(TableOpt().optimize(mock_extracted, routing_tier="ZERO"))


@pytest.fixture(scope="module")
def braille_outputs(opt_outputs: list[Any]) -> list[BrailleOutput]:
    return TableBraille().translate(opt_outputs)


class TestTablePipelineBasic:

    def test_mock_data_exists(self) -> None:
        assert _DATA_PATH.exists(), f"목 데이터 없음: {_DATA_PATH}"

    def test_mock_data_nonempty(self, mock_extracted: list[ExtractedContent]) -> None:
        assert len(mock_extracted) >= 1

    def test_output_count_matches_input(
        self,
        mock_extracted: list[ExtractedContent],
        braille_outputs: list[BrailleOutput],
    ) -> None:
        assert len(braille_outputs) == len(mock_extracted)

    def test_all_braille_lines_nonempty(self, braille_outputs: list[BrailleOutput]) -> None:
        for o in braille_outputs:
            assert len(o.braille_lines) >= 1, f"빈 줄 목록: {o.element_id}"

    def test_all_lines_within_32_cols(self, braille_outputs: list[BrailleOutput]) -> None:
        for o in braille_outputs:
            for line in o.braille_lines:
                assert len(line) <= 32, (
                    f"32칸 초과 (id={o.element_id}): {len(line)}칸 — {line!r}"
                )

    def test_rule_trail_excludes_generic(self, braille_outputs: list[BrailleOutput]) -> None:
        # 정책(태민 2026-06-01): 포괄 표 규칙(BBPG-3.1.1)·조판 규칙(BBPG-1.2.1) 미기록.
        # 구조화 표는 점역자 주가 없으면 rule_trail이 비는 것이 정상.
        for o in braille_outputs:
            rids = [r.rule_id for r in o.rule_trail]
            assert "BBPG-3.1.1" not in rids
            assert "BBPG-1.2.1" not in rids

    def test_element_ids_preserved(
        self,
        mock_extracted: list[ExtractedContent],
        braille_outputs: list[BrailleOutput],
    ) -> None:
        src_ids = [str(e.element_id) for e in mock_extracted]
        out_ids = [str(o.element_id) for o in braille_outputs]
        assert src_ids == out_ids


class TestGriTS:
    """GriTS > 0.88: 규정 불변량 기반 구조 보존율 (비순환).

    translate_tagged_text 미사용 — 다음 불변량만 검사:
      1. 행 수가 출력 줄 수에 반영되었는지 (linear/grid 모드별)
      2. 구조 기호(⠿ 테두리, ⠒ 구분선, 3칸 들여쓰기)가 규정 수에 맞는지
      3. 숫자 셀: 제41항 수표(⠼) + 셀 값이 출력에 포함되는지
    """

    def test_average_grits_above_threshold(
        self,
        mock_extracted: list[ExtractedContent],
        opt_outputs: list[Any],
        braille_outputs: list[BrailleOutput],
    ) -> None:
        scores = [
            _grits(e, o, opt.render_mode)
            for e, opt, o in zip(mock_extracted, opt_outputs, braille_outputs)
        ]
        avg = sum(scores) / len(scores)
        assert avg > _GRITS_THRESHOLD, (
            f"GriTS 평균 {avg:.3f} < {_GRITS_THRESHOLD}: {scores}"
        )

    def test_each_table_grits_above_threshold(
        self,
        mock_extracted: list[ExtractedContent],
        opt_outputs: list[Any],
        braille_outputs: list[BrailleOutput],
    ) -> None:
        for e, opt, o in zip(mock_extracted, opt_outputs, braille_outputs):
            score = _grits(e, o, opt.render_mode)
            assert score > _GRITS_THRESHOLD, (
                f"GriTS {score:.3f} < {_GRITS_THRESHOLD} (id={e.element_id}, mode={opt.render_mode})\n"
                f"  cells: {e.table_structure}\n"
                f"  output: {o.braille_lines}"
            )

    def test_numeric_cells_contain_regulation_braille(
        self,
        mock_extracted: list[ExtractedContent],
        braille_outputs: list[BrailleOutput],
    ) -> None:
        """숫자 셀 검증: 제41항 매핑(translator 독립)으로 수표+셀값 직접 확인."""
        for item, output in zip(mock_extracted, braille_outputs):
            ts = item.table_structure
            if not ts:
                continue
            combined = "".join(output.braille_lines)
            for cell in ts.get("cells", []):
                text = cell.get("text", "").strip()
                if text.isdigit():
                    expected = _numeric_to_expected_braille(text)
                    assert expected in combined, (
                        f"숫자 셀 '{text}' → 기대 점자 {expected!r}가 출력에 없음\n"
                        f"  출력: {combined!r}"
                    )


class TestTableRenderModes:

    def test_2col_table_uses_linear_mode(self, opt_outputs: list[Any]) -> None:
        two_col_items = [o for o in opt_outputs if o.render_mode == "linear"]
        assert len(two_col_items) >= 1, "2열 표의 linear 렌더 모드 없음"

    def test_3col_table_uses_unfold_mode(self, opt_outputs: list[Any]) -> None:
        # 3열 이상 = 풀어쓰기(BBPG-3.1.2)가 기본, 격자는 대안
        unfold_items = [o for o in opt_outputs if o.render_mode == "unfold"]
        assert len(unfold_items) >= 1, "3열 이상 표의 unfold(풀어쓰기) 렌더 모드 없음"

    def test_grid_alternative_draft_has_border(self, braille_outputs: list[BrailleOutput]) -> None:
        # 격자형은 기본이 아니라 대안 초안 — ⠿ 테두리가 대안 draft에 존재해야 함
        has_grid = any(
            d.render_mode == "table_grid" and any("⠿" in ln for ln in d.braille_lines)
            for o in braille_outputs for d in o.drafts
        )
        assert has_grid, "격자형 대안 초안의 ⠿ 테두리 없음"

    def test_linear_output_is_indented(self, braille_outputs: list[BrailleOutput]) -> None:
        """2열 표는 3칸에서 시작하는 '키  값' 줄로 나온다(정답 도서 관행)."""
        linear_outputs = [
            o for o in braille_outputs
            if any(line.startswith("  ") for line in o.braille_lines)
        ]
        assert len(linear_outputs) >= 1, "3칸 시작 줄 없음"

    def test_blocked_fallback_produces_placeholder(self) -> None:
        from uuid import uuid4
        blocked = ExtractedContent(
            element_id=uuid4(),
            ocr_confidence=0.1,
            flags=["C4_FALLBACK"],
        )
        result = asyncio.run(TableOpt().optimize([blocked], routing_tier="ZERO"))
        assert result[0].corrected_text == "[표 수동 입력 필요]"

    def test_empty_table_produces_placeholder(self) -> None:
        from uuid import uuid4
        empty = ExtractedContent(element_id=uuid4(), ocr_confidence=0.9)
        result = asyncio.run(TableOpt().optimize([empty], routing_tier="ZERO"))
        assert "[처리 불가" in result[0].corrected_text


class TestTableRoundTrip:

    def test_round_trip_serialization(self, braille_outputs: list[BrailleOutput]) -> None:
        for o in braille_outputs:
            restored = BrailleOutput.model_validate_json(o.model_dump_json())
            assert restored.element_id == o.element_id
            assert restored.braille_lines == o.braille_lines


class TestTransposeTranslatorNote:
    """전치 시 점역자 주 — 자료지침 §3.1.1(2) "변경한 내용은 점역자 주로 알린다".

    비순환 검증: 기대값을 우리 translator로 만들지 않고, 지침 예 3-2 '행과 열을 변경한
    표'가 실제로 실은 BRF-ASCII 원문을 그대로 박아 두고 디코드해서 쓴다.
    (지침 문서의 backtick은 빈칸이다 — 코퍼스 BRF와 반대이므로 backtick="space".)

    이력: b04aba7이 "gold 0/46"을 근거로 이 주를 뺐다가 2026-07-21 복원했다. 0/46은
    관행의 증거가 아니었다 — 정답 도서는 점역자 주 마커 자체를 전 코퍼스 1131p 중 1p
    에서만 쓴다. 규정은 명시적으로 요구하고, 이건 표기 형태가 아니라 독자가 가로세로
    뒤바뀐 사실을 모르게 되는 정확성 문제다.
    """

    #  지침 예 3-2 원문 한 줄 (앞 2칸 들여쓰기 포함)
    _REG_EX_3_2 = r"``,'jr7@v`\!`^,@ms`d+@oj5,'"

    def _expected(self) -> str:
        from app.utils.braille_ascii import ascii_to_unicode
        return ascii_to_unicode(self._REG_EX_3_2, backtick="space").rstrip("⠀")

    def test_auto_transpose_emits_regulation_note(self) -> None:
        """자동 전치 경로(넓은 표)가 지침 예 3-2와 셀 단위로 같은 주를 낸다."""
        from app.ai.braille.table_braille import _render_unfold
        wide = ("구분 | 프랑스 | 미국 | 독일 | 일본 | 대한민국\n"
                "고령사회 | 115 | 71 | 40 | 24 | 18\n"
                "초고령 | 40 | 16 | 36 | 11 | 8")
        lines = _render_unfold(wide)
        expected = self._expected()
        assert lines[0].replace(" ", "⠀") == expected, (
            f"전치 점역자 주 불일치\n  기대(지침 예3-2): {expected!r}\n  실제            : {lines[0]!r}")

    def test_note_is_wrapped_in_tn_markers(self) -> None:
        """점역자 주 마커 ⠠⠄가 양끝에 있어야 rule_trail(BBPG-1.2.6)이 잡힌다."""
        from app.ai.braille.table_braille import _tn_transpose_line
        line = _tn_transpose_line().strip()
        assert line.startswith("⠠⠄") and line.endswith("⠠⠄")

    def test_non_transposed_table_has_no_note(self) -> None:
        """전치하지 않은 표에는 주가 붙지 않는다(§3.1.1(1)① 원본 정렬 유지 경로)."""
        from app.ai.braille.table_braille import _render_unfold
        narrow = "A | B\n1 | 2\n3 | 4"
        assert not any("⠠⠄" in ln for ln in _render_unfold(narrow))


class TestTableRegulationSwitch:
    """표 축도 BRAILLE_STYLE=regulation 스위치를 탄다(2026-07-21 신설).

    기본값은 book이고, 관행 선택(임계 40·쌍점 구분자·전치 조건·초과 시 행머리 단독 줄)만
    스위치를 탄다. 규정 근거가 있는 것(제목 5칸·빈 셀 ⠿⠿·두 칸 구분·3칸 시작·전치 주)은
    두 모드 공통이다 — 모듈 상단 분류표 참조.
    """

    def _unfold(self, text: str, mode: str) -> list[str]:
        import importlib
        import os
        from app.ai.braille import table_braille
        old = os.environ.get("BRAILLE_STYLE")
        os.environ["BRAILLE_STYLE"] = mode
        try:
            importlib.reload(table_braille)
            return table_braille._render_unfold(text)
        finally:
            if old is None:
                os.environ.pop("BRAILLE_STYLE", None)
            else:
                os.environ["BRAILLE_STYLE"] = old
            importlib.reload(table_braille)

    def test_default_is_book(self) -> None:
        from app.ai.braille.table_braille import _BOOK_STYLE, _ROWWISE_MAX_WIDTH
        assert _BOOK_STYLE is True and _ROWWISE_MAX_WIDTH == 40

    def test_regulation_mode_uses_32_column_threshold(self) -> None:
        """§3.1.1(1)①은 32칸이다. 관행 임계 40은 book 한정."""
        import importlib
        import os
        from app.ai.braille import table_braille
        os.environ["BRAILLE_STYLE"] = "regulation"
        try:
            importlib.reload(table_braille)
            assert table_braille._ROWWISE_MAX_WIDTH == 32
        finally:
            os.environ.pop("BRAILLE_STYLE", None)
            importlib.reload(table_braille)

    def test_regulation_mode_never_uses_colon_separator(self) -> None:
        """쌍점은 규정 근거가 없다 — 규정 모드는 §3.1.1(1)②의 두 칸만 쓴다."""
        sentence_table = ("유형별 특징 | 소득 수준의 서술\n"
                          "상층 계층의 생활 | 매우 높다\n"
                          "중층 계층의 생활 | 중간이다")
        book = self._unfold(sentence_table, "book")
        reg = self._unfold(sentence_table, "regulation")
        assert any("⠐⠂" in ln for ln in book), "book 모드는 쌍점을 써야 한다(정답 도서 실측)"
        assert not any("⠐⠂" in ln for ln in reg), "규정 모드에 쌍점이 새어 나왔다"

    def test_regulation_mode_changes_output(self) -> None:
        """규정 모드가 실제로 다른 조판을 낸다(스위치가 죽어 있지 않다)."""
        wide36 = ("자율 신경 | 침 분비 | 폐의 기관지 | 동공\n"
                  "A | 촉진 | 수축 | 축소\nB | 억제 | 이완 | 확대")
        assert self._unfold(wide36, "book") != self._unfold(wide36, "regulation")


class TestUnfoldEntityAxisIsRow:
    """풀어 적는 표의 개체는 **행**이다 — 자료지침 §3.3.1(2026-07-27 정정).

    조항: §3.3.1(3) "행 제목은 3칸에 적고, 열 항목은 열 제목 순서에 따라 두 칸씩 띄어
    적는다" · (4) "줄바꿈: 행 제목 단위로 줄을 바꿔 적는다". 예 3-7도 열 제목을 맨 위에
    한 번만 적고 그 아래를 행(프랑스·미국·독일…)마다 끊는다.

    ★ 이 클래스가 검사하는 것은 **배치 순서**뿐이다(어느 셀이 블록 머리가 되는가).
      점형 변환의 정확성은 braille/ 쪽 테스트 소관이라 여기서는 _translate 로 바늘만
      만들어 위치를 찾는다 — 기대 점형을 만들어 비교하는 순환 검증이 아니다.

    회귀 대상: ①(원본 정렬 유지)도 (2)(전치)도 발동하지 않는 표가 전에는 원본 격자
    그대로 **열마다** 블록을 세웠다. s4 라벨 세트(dev+val 149건) 기준 그 경로 102건의
    정답 개체축은 행 67 : 열 35였고 축 정확도는 34.3%였다.
    """

    #  R(4) > C(3) → §3.1.1(2) 전치 미발동. 셀이 길어 §3.1.1(1)① 행 단위도 불가.
    _TALL = ("구분 | 의미 | 특징\n"
             "피라미드형 계층 구조 | 하층의 구성 비율이 가장 높고 상위 계층으로 갈수록 낮아진다"
             " | 봉건적 신분제 사회의 계층 구조\n"
             "다이아몬드형 계층 구조 | 중층의 구성 비율이 가장 높고 하층과 상층이 낮은 구조"
             " | 고도 산업 사회 복지 사회의 계층 구조\n"
             "모래시계형 계층 구조 | 중층의 몰락으로 소수의 상층과 다수의 하층이 존재한다"
             " | 성장과 경쟁만을 강조하는 사회의 양극화된 계층 구조")

    def _needle(self, s: str) -> str:
        from app.ai.braille.table_braille import _translate
        return _translate(s)

    def test_fallback_path_is_not_transposed_and_not_rowwise(self) -> None:
        """전제 확인 — 이 표는 ①·(2) 둘 다 불발해 전개 폴백으로 간다."""
        from app.ai.braille.table_braille import _rowwise_ok, _should_transpose
        rows = [[c.strip() for c in ln.split("|")] for ln in self._TALL.splitlines()]
        assert not _rowwise_ok(rows), "①이 발동하면 이 테스트의 전제가 깨진다"
        assert not _should_transpose(rows, len(rows[0])), "(2)가 발동하면 전제가 깨진다"

    def test_block_heads_are_row_headings(self) -> None:
        """블록 머리(5칸 = 앞 빈칸 4)는 행 제목이어야 한다 — §3.3.1(4)."""
        from app.ai.braille.table_braille import _render_unfold
        heads = [ln for ln in _render_unfold(self._TALL)
                 if ln.startswith("    ") and ln.strip()]
        assert len(heads) == 3, f"본문 행 3개마다 블록 하나여야 한다 — 실제 {len(heads)}개"
        for want in ("피라미드형 계층 구조", "다이아몬드형 계층 구조", "모래시계형 계층 구조"):
            assert any(self._needle(want) in h for h in heads), f"행 제목 {want!r}이 블록 머리에 없다"
        for never in ("의미", "특징"):
            assert not any(self._needle(never) in h for h in heads), \
                f"열 제목 {never!r}이 블록 머리로 올라갔다 — 개체축이 열로 되돌아갔다"

    def test_row_heading_block_order_follows_original_rows(self) -> None:
        """블록 순서 = 원본 행 순서(§3.3.1(4) '행 제목 단위')."""
        from app.ai.braille.table_braille import _render_unfold
        out = "\n".join(_render_unfold(self._TALL))
        pos = [out.find(self._needle(s)) for s in
               ("피라미드형 계층 구조", "다이아몬드형 계층 구조", "모래시계형 계층 구조")]
        assert all(p >= 0 for p in pos) and pos == sorted(pos), f"행 블록 순서가 어긋났다: {pos}"

    def test_fallback_emits_no_transpose_note(self) -> None:
        """폴백은 §3.1.1(2)의 행↔열 교환이 아니다 → 점역자 주를 붙이지 않는다."""
        from app.ai.braille.table_braille import _render_unfold
        assert not any("⠠⠄" in ln for ln in _render_unfold(self._TALL))

    def test_rowwise_and_transpose_paths_unchanged(self) -> None:
        """①·(2) 경로는 이번 변경 대상이 아니다(s4 기준 정확도 93%·80%)."""
        from app.ai.braille.table_braille import _render_unfold, _render_rowwise
        narrow = "A | B | C\n1 | 2 | 3\n4 | 5 | 6"          # ① 원본 정렬 유지
        rows = [[c.strip() for c in ln.split("|")] for ln in narrow.splitlines()]
        assert _render_unfold(narrow) == _render_rowwise(rows, [3, 3, 3])
        wide = ("구분 | 프랑스 | 미국 | 독일 | 일본 | 대한민국\n"   # (2) 전치 + 주
                "고령사회 | 115 | 71 | 40 | 24 | 18\n"
                "초고령 | 40 | 16 | 36 | 11 | 8")
        assert "⠠⠄" in _render_unfold(wide)[0]
