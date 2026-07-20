"""PART 6-2 — 표 점역 최적화 (HyperCLOVA X SEED Think 14B INT4, GPU 1).

점역사주 복수 초안 생성 + render_mode 결정.
render_mode 우선순위: table_structure['render_mode'] → 행/열 수 기반 추론 → unfold(풀어쓰기)

공통 추론·폴백·재시도는 base_opt — 여기서는 표에 최적화된 프롬프트·구조 추론만 정의한다.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Optional

from app.ai.braille.nested_block import box_narrative
from app.ai.braille.regulations import make_rule
from app.ai.braille.table_braille import build_table_tags
from app.ai.llm.base_opt import BaseOpt, decide_tier_timeout, generate_with_retry
from app.ai.llm.draft_utils import ensure_tn_prefix
from app.core.model_manager import model_manager  # noqa: F401 (단위 테스트가 이 네임스페이스를 patch)
from app.schemas.content import ExtractedContent, LLMOutput, RuleApplication

logger = logging.getLogger(__name__)

_NESTED_IMAGE_TYPES = {"image", "picture", "photo", "그림", "사진", "illustration"}


def _nested_image_text(ext: ExtractedContent) -> Optional[str]:
    """표 안 그림(Q11) → 그림을 글상자처럼 1단으로 풀어 쓴 보조 narrative. 없으면 None."""
    for src in (ext.structure, ext.table_structure):
        if src and src.get("nested"):
            blocks = [n for n in src["nested"]
                      if (n.get("type") or "").strip() in _NESTED_IMAGE_TYPES]
            if blocks:
                return box_narrative(blocks, default_label="그림")
    return None


def _min_trail(text: str) -> list[RuleApplication]:
    """표 점역 일반 사항(BBPG-3.1.1) — 요소 전체(line_no=-1)."""
    return [make_rule("BBPG-3.1.1")]

_PROMPT_TABLE_GRID = """당신은 한국어 점역 전문가입니다.
다음 표 내용을 점역사주([점역사주])로 표현하는 2가지 방식을 제안하세요.

표 내용:
{table_text}

형식:
[방식1] [점역사주] ...
[방식2] [점역사주] ...

가장 적합한 방식 번호(1 또는 2)를 마지막 줄에 "선택: N" 형식으로 기재하세요."""

_PROMPT_IRREGULAR = """당신은 한국어 점역 전문가입니다.
다음 비정형 표 내용을 점역사주로 간결하게 표현하세요.

원문:
{text}

[점역사주]로 시작하는 설명 1문장만 반환하세요."""


def _table_title(ext: ExtractedContent) -> Optional[str]:
    """표 제목(전사) — 도서 제작 지침 제3장 5)(1) 5칸·(2) 표 위에 먼저.

    구조화 입력(table_structure 또는 structure)의 'title'을 그대로 전사한다(rule-based).
    원본에서 제목이 표 안에 있어도 점역 자료에서는 표 위로 올린다(§3 5)(2)).
    """
    for src in (ext.table_structure, ext.structure):
        if src:
            t = (src.get("title") or "").strip()
            if t:
                return t
    return None


def _table_to_grid(table_structure: dict) -> list[list[str]]:
    """table_structure dict → 행렬(list[list[str]]). 셀 없으면 빈 리스트."""
    cells: list[dict] = table_structure.get("cells", [])
    if not cells:
        return []
    max_row = max((c.get("row", 0) for c in cells), default=0) + 1
    max_col = max((c.get("col", 0) for c in cells), default=0) + 1
    grid: list[list[str]] = [[""] * max_col for _ in range(max_row)]
    for cell in cells:
        r, c = cell.get("row", 0), cell.get("col", 0)
        if r < max_row and c < max_col:
            grid[r][c] = str(cell.get("text", ""))
    return grid


def _table_to_text(table_structure: dict) -> str:
    """table_structure dict → '|' 구분 텍스트(LLM 프롬프트·render_mode 추론용)."""
    grid = _table_to_grid(table_structure)
    if not grid:
        return table_structure.get("text", "") or ""
    return "\n".join(" | ".join(row) for row in grid)


def _pipe_to_grid(text: str) -> list[list[str]]:
    """'|' 구분 텍스트 → 행렬(현주 핸드오프가 파이프 텍스트만 줄 때 대비)."""
    return [[c.strip() for c in ln.split("|")] for ln in text.splitlines() if ln.strip()]


# MinerU는 표를 <table><tr><td>… HTML로 낸다(P5). 셀을 보존하려면 격자로 파싱해야
# narrative(산문 요약)로 오분류되지 않고 unfold/linear로 점역된다.
# ★ colspan/rowspan을 펼쳐야 한다 — 무시하면 행마다 셀 수가 달라져 열이 어긋나고
#   빈칸(⠿⠿)이 엉뚱한 자리에 찍힌다(정답과 대조해 확인, 2026-07-13).
_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
_TD_RE = re.compile(r"<(t[dh])([^>]*)>(.*?)</\1>", re.DOTALL | re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SPAN_RE = re.compile(r"(col|row)span\s*=\s*[\"']?(\d+)", re.IGNORECASE)


def _is_html_table(text: str) -> bool:
    return "<table" in (text or "").lower()


def _spans(attrs: str) -> tuple[int, int]:
    """(colspan, rowspan)."""
    col = row = 1
    for kind, n in _SPAN_RE.findall(attrs or ""):
        v = max(1, int(n))
        if kind.lower() == "col":
            col = v
        else:
            row = v
    return col, row


# MinerU가 밀집 숫자표에서 소수점 '.'을 쉼표 ','로 자주 오독한다(PDF 원문 대조로 확정:
# '42.8'→'42,8'). 규정 제48항 소수점은 ⠲, 제41항 자릿점(천단위)은 ⠂로 서로 다르므로
# 오독을 그대로 두면 엉뚱한 점형이 된다. 쉼표 뒤 1~2자리+경계면 소수(복원 '.'),
# 3자리면 천단위(그대로)로 판별 — '2,575'(천단위)는 건드리지 않고 '42,8'만 '42.8'로.
_DECIMAL_COMMA_RE = re.compile(r"(?<=\d),(?=\d{1,2}(?:\D|$))")


def _fix_decimal_comma(text: str) -> str:
    return _DECIMAL_COMMA_RE.sub(".", text)


# 대각선으로 나뉜 머리칸(`현상\특징`)의 백슬래시는 인쇄 구획선이지 옮길 문자가 아니다.
# MinerU가 그 선을 `\`로 표기해 넘기면 점역이 ⠸⠡(백슬래시)를 찍는데, 정답 도서에는
# 이 점형이 **전 코퍼스 0회**다(우리 표 출력에는 60회, 2026-07-19 실측). 두 머리말을
# 한 칸 띄어 잇는 형태가 정답의 표기다.
_DIAGONAL_HEAD_RE = re.compile(r"(?<=[^\s\\])\s*\\\s*(?=[^\s\\])")


def _strip_diagonal_rule(text: str) -> str:
    return _DIAGONAL_HEAD_RE.sub(" ", text)


# 병합 헤더 코너의 범용(의미 없는) 라벨 — 점역은 반복하지 않는다(2026-07-20 실측).
# '구분'은 행·열 축 이름이 따로 없을 때 표 좌상단을 채우는 관용적 필러 단어로, 정보값이
# 없다. 사회문화·생물 8개 표(15건, val+dev 양쪽)를 정답과 대조: colspan/rowspan으로
# 펼쳐진 '구분' 복제 중 정답에 그대로 남아 있는 사례는 0/8 — 나머지는 좌표만 다른
# 실제 열/행 라벨(예 '어느 계층에 속한다고 생각하는가?', '소득 계층')로 대체돼 있었다.
# 대조군: 같은 방식으로 반복되는 '제재'(표 주제, 언어 7개 표)는 정답에 그대로
# 유지된다(개수까지 일치) — 의미 있는 열 그룹 제목은 유지, 값 없는 필러만 접는다.
# 앵커(펼침의 첫 칸)만 남기고 나머지 칸은 빈칸으로 접는다 — 격자 폭(열 정렬)은 그대로
# 유지되므로 _render_grid/_render_unfold 등 다른 렌더러의 폭 계산에 영향 없다.
_GENERIC_CORNER_LABELS = {"구분"}

# 표 안 유도점(leader dots) — 인쇄본은 열 항목 사이 긴 간격을 점선으로 시각 정렬하지만
# 그 점선 자체가 MinerU에서 독립된 <td>로 추출된다(외국어 p014/p236 실측, colspan 없음
# — 병합 복제가 아니라 원본 HTML 자체가 빈 칸을 별도 셀로 낸 것). 정답은 이 칸을 아예
# 없는 것처럼 취급하고 값 칸 사이를 그냥 빈칸으로 잇는다("EXAMPLE␣␣MOREOVER", 점형
# 없음, 2026-07-20 실측) — 표 안 말줄임표(⠲⠲⠲, 문장부호 규정)로 잘못 옮기면 안 된다.
# 규정(점자 자료 제작 지침 §3.2.1(5))의 진짜 유도점(열 간격 5칸 이상일 때 " 연속)은
# 열 너비 인지가 필요해 미구현(table_braille.py 기존 주석) — 여기서는 최소한 오기호
# (⠲⠲⠲)를 내지 않도록 빈 칸으로만 접는다.
_LEADER_DOTS_RE = re.compile(r"^\.{3,}$")


def _html_to_grid(html: str) -> list[list[str]]:
    """MinerU <table> HTML → 행렬(병합 셀 펼침). 내부 태그 제거(이미지 셀=빈칸).

    colspan/rowspan은 같은 값을 복제해 채운다 — 점역은 격자를 전제하므로 병합을 그대로
    두면 열 정렬이 무너진다. 풀어쓰기(_render_unfold)도 열 머리를 복제된 값에서 읽는다.
    단, 값 없는 범용 코너 라벨(_GENERIC_CORNER_LABELS)은 앵커 칸에만 남긴다.
    """
    grid: list[list[str]] = []
    pending: dict[tuple[int, int], str] = {}   # (row, col) → rowspan으로 내려오는 값
    for r, tr in enumerate(_TR_RE.findall(html)):
        row: list[str] = []
        c = 0
        for _tag, attrs, body in _TD_RE.findall(tr):
            while (r, c) in pending:            # 위에서 내려온 rowspan 자리 먼저 채움
                row.append(pending.pop((r, c)))
                c += 1
            text = _strip_diagonal_rule(
                _fix_decimal_comma(_HTML_TAG_RE.sub("", body).strip()))
            if _LEADER_DOTS_RE.match(text):
                text = ""                        # 유도점 칸 — 값처럼 옮기지 않는다
            colspan, rowspan = _spans(attrs)
            is_generic_merge = (
                text in _GENERIC_CORNER_LABELS and (colspan > 1 or rowspan > 1))
            for dc in range(colspan):
                keep = (not is_generic_merge) or (dc == 0)
                row.append(text if keep else "")
                for dr in range(1, rowspan):
                    pending[(r + dr, c + dc)] = "" if is_generic_merge else text
            c += colspan
        while (r, c) in pending:                 # 행 끝에 남은 rowspan 자리
            row.append(pending.pop((r, c)))
            c += 1
        if row:
            grid.append(row)
    if grid:                                     # 행 길이 정규화
        w = max(len(r) for r in grid)
        grid = [r + [""] * (w - len(r)) for r in grid]
    return grid


def _table_tags(table_structure, table_text: str) -> str:
    """표 구조 → <!표> 태그(stage② 표시·table_braille 입력). 비정형은 원문 유지."""
    grid = _table_to_grid(table_structure) if table_structure else []
    if not grid and _is_html_table(table_text):
        grid = _html_to_grid(table_text)
    if not grid and "|" in table_text:
        grid = _pipe_to_grid(table_text)
    return build_table_tags(grid) if grid else table_text


def _infer_render_mode(table_structure: Optional[dict], text: str = "") -> str:
    if table_structure:
        if rm := table_structure.get("render_mode"):
            return rm
        cells = table_structure.get("cells", [])
        if cells:
            max_row = max((c.get("row", 0) for c in cells), default=0) + 1
            max_col = max((c.get("col", 0) for c in cells), default=0) + 1
            if max_col == 2:
                return "linear"
            if max_row == 1:
                return "transposed"
            return "unfold"   # 3열 이상 = 풀어쓰기 기본(BBPG-3.1.2), 격자는 대안 초안
    # table_structure 없음/빈 셀: HTML 표(MinerU) 또는 '|' 격자로 추론(narrative 오분류 방지).
    if _is_html_table(text):
        grid = _html_to_grid(text)
        if grid:
            max_col = max(len(r) for r in grid)
            return "linear" if max_col == 2 else "unfold"
    rows = [ln for ln in (text or "").splitlines() if "|" in ln]
    if not rows:
        return "narrative"
    max_col = max(len(r.split("|")) for r in rows)
    return "linear" if max_col == 2 else "unfold"


def _parse_tn_from_response(response: str) -> str:
    """LLM 응답에서 [점역사주] 텍스트 추출. 선택된 방식 우선."""
    lines = [ln.strip() for ln in response.splitlines() if ln.strip()]
    selected_idx = None
    for ln in lines:
        if ln.startswith("선택:"):
            try:
                selected_idx = int(ln.split(":")[1].strip()) - 1
            except (ValueError, IndexError):
                pass

    drafts = [ln for ln in lines if "[점역사주]" in ln]
    if not drafts:
        # 응답 전체가 TN인 경우
        return response.strip() if response.strip() else "[처리 불가: 표 점역사주 생성 실패]"

    if selected_idx is not None and 0 <= selected_idx < len(drafts):
        return drafts[selected_idx]
    return drafts[0]


class TableOpt(BaseOpt):
    """ExtractedContent 목록 → LLMOutput 목록 (표)."""

    async def _optimize_one(self, ext: ExtractedContent, routing_tier: str) -> LLMOutput:
        start = time.monotonic()
        title = _table_title(ext)              # §3 5) 표 제목 5칸(전사). 없으면 None.
        nested_text = _nested_image_text(ext)  # 표 안 그림(Q11) → 글상자 1단. 없으면 None.
        render_mode = _infer_render_mode(ext.table_structure, ext.corrected_text or "")
        is_irregular = render_mode == "narrative" or (
            ext.table_structure is not None
            and ext.table_structure.get("irregular", False)
        )

        # C4: 표 신뢰도 낮음
        if "C4_FALLBACK" in ext.flags:
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text="[표 수동 입력 필요]",
                render_mode="narrative",
                routing_tier="FALLBACK",
                processing_time_ms=0,
                rule_trail=_min_trail("[표 수동 입력 필요]"),
            )

        # 텍스트 준비
        if ext.table_structure:
            table_text = _table_to_text(ext.table_structure)
        else:
            table_text = ext.corrected_text or ""
        # MinerU HTML 표 → '|' 격자 텍스트로 정규화(셀 보존·tn 요약·rule_trail용, P5)
        if _is_html_table(table_text):
            grid = _html_to_grid(table_text)
            if grid:
                table_text = "\n".join(" | ".join(row) for row in grid)

        if not table_text.strip():
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text="[처리 불가: 표 내용 없음]",
                render_mode="narrative",
                routing_tier="FALLBACK",
                processing_time_ms=0,
                rule_trail=_min_trail("[처리 불가: 표 내용 없음]"),
            )

        # 점역 직전 텍스트(stage②) = 표 구조 태그. table_braille가 파싱해 4안 렌더에 위임.
        # table_text(파이프)는 LLM 프롬프트·render_mode 추론·rule_trail 소스로만 사용.
        table_tags = _table_tags(ext.table_structure, table_text)

        if routing_tier == "ZERO":
            tn = ensure_tn_prefix(f"표. {table_text[:100]}")  # <!점역자주>…<!/점역자주>
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text=table_tags,
                render_mode=render_mode,
                tn_text=tn,
                routing_tier="ZERO",
                processing_time_ms=0,
                rule_trail=_min_trail(table_tags),
                table_title=title,
                nested_text=nested_text,
            )

        tier, timeout = decide_tier_timeout(ext.ocr_confidence)   # 요소당 상한 = config(작게)
        if is_irregular:
            prompt = _PROMPT_IRREGULAR.format(text=table_text[:500])
        else:
            prompt = _PROMPT_TABLE_GRID.format(table_text=table_text[:800])

        response, used_fb = await generate_with_retry(
            prompt, timeout=timeout, element_id=ext.element_id, kind="표",
            max_new_tokens=512, fallback_max_tokens=1024,
        )
        if used_fb:
            tier = "FALLBACK"

        if response:
            parsed = _parse_tn_from_response(response)
            # 처리불가 플레이스홀더는 TN 태그로 감싸지 않는다
            tn_text = parsed if parsed.startswith("[처리 불가") else ensure_tn_prefix(parsed)
        else:
            tn_text = ensure_tn_prefix(f"표. {table_text[:80]}")
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return LLMOutput(
            element_id=ext.element_id,
            corrected_text=table_tags,
            render_mode=render_mode,
            tn_text=tn_text,
            routing_tier=tier,
            processing_time_ms=elapsed_ms,
            rule_trail=_min_trail(table_tags),
            table_title=title,
            nested_text=nested_text,
        )
