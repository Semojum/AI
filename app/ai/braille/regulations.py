"""점자 규정 레지스트리 로더 (T4-3 rule_trail).

환각 0 아키텍처: 변환 코드(translator/symbol_rules/kor_math_rules/layout_braille)가
변환 지점에서 `make_rule(rule_id, line_no, col_start, col_end, tag)` / `make_rule_at`을 호출하면
source/section/rule_name/contents 메타는 `regulations.json`(239개 조항) dict 조회로만 채운다.

금지: ①LLM 규정 자가보고 ②출력↔규정 유사도검색 ③DB에 없는 rule_id.
rule_id가 JSON에 없으면 KeyError raise — 댕글링/가짜 rule_id 차단.
"""

from __future__ import annotations

import json
import pathlib

from app.schemas.content import RuleApplication

_REGS_PATH = pathlib.Path(__file__).parent / "regulations.json"

# 2026-08-31 접두 개편 — 편찬 기관 이니셜로 바꿨다.
# 코드 안 리터럴은 전부 새 접두로 고쳤지만, test_data/ 의 동결 픽스처처럼 손댈 수
# 없는 자리에 옛 id 가 남아 있다. 조회 단계에서만 옛 접두를 받아 준다.
_LEGACY_PREFIX = {"BBPG-": "NLD-", "JAJAK-": "NISE-"}


def _legacy_kbr(rule_id: str) -> str:
    """옛 KBR id → 현행 MCST id. 편(한글·수학·과학·기본·외국어)이 접두에 붙었다."""
    body = rule_id[len("KBR-"):]
    if body.startswith("수학-"):
        c, _, p = body[3:].partition(".")
        return f"MCST-과학-{p}" if c == "9" and p.isdigit() and int(p) <= 32 else f"MCST-수학-{body[3:]}"
    if body.startswith("영어-"):
        return f"MCST-외국어-1.1.{body[3:]}"
    head, _, rest = body.partition(".")
    return f"MCST-기본-{rest}" if head == "0" else f"MCST-한글-{body}"

# section 위계 dict 를 평문으로 접을 때의 순서. 없는 key 는 건너뛴다.
_SECTION_LEVELS = ("Part", "Chapter", "Section", "Paragraph", "Subparagraph", "Item")


def _load_rules() -> dict[str, dict]:
    with _REGS_PATH.open(encoding="utf-8") as f:
        raw = json.load(f)
    return raw["rules"]


_RULES: dict[str, dict] = _load_rules()


def _canon(rule_id: str) -> str:
    """옛 접두(KBR/BBPG/JAJAK)로 들어온 id 를 현행 id 로 바꾼다."""
    if rule_id.startswith("KBR-"):
        return _legacy_kbr(rule_id)
    for old, new in _LEGACY_PREFIX.items():
        if rule_id.startswith(old):
            return new + rule_id[len(old):]
    return rule_id


def section_text(section: dict[str, str]) -> str:
    """위계 dict → 표시용 한 줄. gRPC RuleTrail.section 이 string 이라 여기서 접는다."""
    return " · ".join(section[k] for k in _SECTION_LEVELS if section.get(k))


def make_rule(
    rule_id: str,
    *,
    line_no: int = -1,
    col_start: int = 0,
    col_end: int = 0,
    tag: str = "",
    priority: str = "primary",
) -> RuleApplication:
    """rule_id로 regulations.json 메타를 조회해 RuleApplication을 구성한다.

    좌표는 요소-로컬(조판 후) — line_no = 해당 블록 contents 줄 인덱스, col_* = 줄 안 칸 범위.
    line_no 기본 -1 = 요소 전체(블록 전체에 적용되는 포괄·구조 규칙). 정밀 지점은 make_rule_at.
    tag가 ""이면 해당 rule의 default_tag를 사용한다.
    rule_id가 JSON에 없으면 KeyError(댕글링 방지).
    """
    rule_id = _canon(rule_id)
    meta = _RULES.get(rule_id)
    if meta is None:
        raise KeyError(
            f"rule_id {rule_id!r} not in regulations.json "
            f"(댕글링 rule_id 금지 — regulations.json에 조항을 먼저 추가하라)"
        )
    return RuleApplication(
        rule_id=rule_id,
        source=meta["source"],
        section=section_text(meta["section"]),
        rule_name=meta["rule_name"],
        contents=meta["contents"],
        priority=priority,
        line_no=line_no,
        col_start=col_start,
        col_end=col_end,
        tag=tag or meta.get("default_tag", ""),
    )


def _offset_to_linecol(lines: list[str], offset: int) -> tuple[int, int]:
    """'\\n'.join(lines) 기준 char offset → (line_no, col). 범위 밖이면 마지막 줄 끝."""
    pos = 0
    for li, line in enumerate(lines):
        if offset <= pos + len(line):
            return li, offset - pos
        pos += len(line) + 1  # + '\n'
    last = max(0, len(lines) - 1)
    return last, (len(lines[last]) if lines else 0)


def _linecol_span(lines: list[str], start: int, end: int) -> tuple[int, int, int]:
    """char offset span [start, end) → 요소-로컬 (line_no, col_start, col_end).

    줄 경계를 넘는 span(드묾: 32칸 단순분리가 글리프 가운데를 끊는 경우)은
    시작 줄 끝까지로 클램프(best-effort) — FE 계산 없이 한 줄 안 범위만 보장.
    """
    line_no, col_start = _offset_to_linecol(lines, start)
    if end <= start:
        return line_no, col_start, col_start
    end_line, end_col = _offset_to_linecol(lines, end - 1)
    if end_line != line_no:
        return line_no, col_start, len(lines[line_no]) if lines else col_start
    return line_no, col_start, end_col + 1


def make_rule_at(
    rule_id: str,
    lines: list[str],
    start: int,
    end: int,
    *,
    tag: str = "",
    priority: str = "primary",
) -> RuleApplication:
    """변환 출력(lines)의 char offset span을 요소-로컬 좌표로 바꿔 make_rule 호출.

    lines = 이 블록의 점자 줄 목록(= BrailleOutput.braille_lines, 조판 in-place 전).
    start/end = '\\n'.join(lines) 기준 char offset(symbol_rule_spans/tn_marker_spans 산출).
    """
    line_no, col_start, col_end = _linecol_span(lines, start, end)
    return make_rule(
        rule_id, line_no=line_no, col_start=col_start, col_end=col_end,
        tag=tag, priority=priority,
    )


def rule_meta(rule_id: str) -> dict | None:
    """rule_id 의 원본 메타(publisher · version · section 위계 dict)를 그대로 돌려준다.

    RuleApplication 은 gRPC 옛 필드를 채우느라 표시용 평문만 들고 있다.
    위계·기관·판이 필요한 곳(gRPC 직렬화)은 여기서 꺼낸다. 없는 id 면 None.
    """
    return _RULES.get(_canon(rule_id))


def all_rule_ids() -> frozenset[str]:
    """등록된 모든 rule_id 집합 (test_rule_registry.py 검증용)."""
    return frozenset(_RULES.keys())
