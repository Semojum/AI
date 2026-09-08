"""표 구조 태그(<!표>/<!행>/<!칸>) 빌드·파싱·렌더 동등성 회귀 테스트.

table_opt가 stage②에 태그를 출력하고 table_braille가 파싱해 기존 4안 렌더러에 위임한다.
태그 경로와 기존 '|' 경로의 점역 결과가 동일해야 한다(렌더링 변경 없음).
"""
import uuid

from app.ai.braille.table_braille import (
    TableBraille,
    build_table_tags,
    parse_table_tags,
)
from app.schemas.content import LLMOutput

ROWS = [["구분", "2023", "2024"], ["수입", "100", "120"], ["지출", "80", "90"]]


class TestBuildParse:
    def test_round_trip(self):
        assert parse_table_tags(build_table_tags(ROWS)) == ROWS

    def test_no_tag_returns_none(self):
        assert parse_table_tags("구분 | 2023") is None

    def test_tag_form(self):
        out = build_table_tags([["a", "b"]])
        assert out == "<!표>\n<!행><!칸>a<!칸>b<!/행>\n<!/표>"


def _llm(text, **kw):
    return LLMOutput(element_id=uuid.uuid4(), corrected_text=text,
                     render_mode=kw.get("render_mode", "unfold"), routing_tier="ZERO",
                     processing_time_ms=0, rule_trail=[], **{k: v for k, v in kw.items() if k != "render_mode"})


class TestRenderEquivalence:
    def test_태그와_파이프_동일점역(self):
        tag_text = build_table_tags(ROWS)
        pipe_text = "\n".join(" | ".join(r) for r in ROWS)
        for rm in ("unfold", "table_grid", "transposed", "linear"):
            b_tag = TableBraille().translate([_llm(tag_text, render_mode=rm)])[0]
            b_pipe = TableBraille().translate([_llm(pipe_text, render_mode=rm)])[0]
            assert b_tag.braille_lines == b_pipe.braille_lines, f"render_mode={rm} 불일치"

    def test_빈셀_보존(self):
        rows = [["a", "", "c"]]
        assert parse_table_tags(build_table_tags(rows)) == rows


class TestPrintDraftsFromTags:
    """mode b(태그 원문)에서도 묵자 초안 다섯 안이 선다 (2026-09-08).

    「대체 텍스트 선택」 모달의 피커가 `text_list[].drafts` 를 쓴다. 점역사가 고친 글을
    되돌리면 원문에 `<!표>` 구조 태그만 있고 파이프가 없어, `"|" in table_text` 만 보던
    `_print_drafts` 가 빈 목록을 냈다 — 고를 안이 없었다. 점자 쪽(`table_braille`)은
    자기 초안을 따로 만들어 5개였으므로 두 목록이 갈렸고 `selected_idx` 도 어긋났다.
    """

    def test_태그_원문도_다섯_안을_낸다(self) -> None:
        from app.ai.llm.table_opt import _print_drafts

        drafts, sel = _print_drafts(build_table_tags(ROWS), "table_grid")
        assert len(drafts) == 5, f"초안이 5개가 아니다: {len(drafts)}"
        assert sel == 1, f"기본 선택이 table_grid(1)가 아니다: {sel}"

    def test_태그와_파이프가_같은_초안을_낸다(self) -> None:
        """한 길로 모은다 — 태그로 오든 파이프로 오든 묵자 초안이 같아야 한다."""
        from app.ai.llm.table_opt import _print_drafts

        pipe = "\n".join(" | ".join(r) for r in ROWS)
        a, sa = _print_drafts(build_table_tags(ROWS), "unfold")
        b, sb = _print_drafts(pipe, "unfold")
        assert (sa, [d.text for d in a]) == (sb, [d.text for d in b])

    def test_표가_아니면_초안을_안_만든다(self) -> None:
        from app.ai.llm.table_opt import _print_drafts

        assert _print_drafts("그냥 줄글이다.", "narrative") == ([], 0)
