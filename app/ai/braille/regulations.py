"""점자 규정 레지스트리 로더 (T4-3 rule_trail).

환각 0 아키텍처: 변환 코드(translator/symbol_rules/kor_math_rules/layout_braille)가
변환 지점에서 `make_rule(rule_id, span_start, span_end, tag)`을 결정적으로 호출하면
source/section/title/excerpt 메타는 `regulations.json`(226개 조항) dict 조회로만 채운다.

금지: ①LLM 규정 자가보고 ②출력↔규정 유사도검색 ③DB에 없는 rule_id.
rule_id가 JSON에 없으면 KeyError raise — 댕글링/가짜 rule_id 차단.
"""

from __future__ import annotations

import json
import pathlib

from app.schemas.content import RuleApplication

_REGS_PATH = pathlib.Path(__file__).parent / "regulations.json"


def _load_rules() -> dict[str, dict]:
    with _REGS_PATH.open(encoding="utf-8") as f:
        raw = json.load(f)
    return raw["rules"]


_RULES: dict[str, dict] = _load_rules()


def make_rule(
    rule_id: str,
    *,
    span_start: int = 0,
    span_end: int = 0,
    tag: str = "",
    priority: str = "primary",
) -> RuleApplication:
    """rule_id로 regulations.json 메타를 조회해 RuleApplication을 구성한다.

    tag가 ""이면 해당 rule의 default_tag를 사용한다.
    rule_id가 JSON에 없으면 KeyError(댕글링 방지).
    """
    meta = _RULES.get(rule_id)
    if meta is None:
        raise KeyError(
            f"rule_id {rule_id!r} not in regulations.json "
            f"(댕글링 rule_id 금지 — regulations.json에 조항을 먼저 추가하라)"
        )
    return RuleApplication(
        rule_id=rule_id,
        source=meta["source"],
        section=meta["section"],
        title=meta["title"],
        excerpt=meta["excerpt"],
        priority=priority,
        span_start=span_start,
        span_end=span_end,
        tag=tag or meta.get("default_tag", ""),
    )


def all_rule_ids() -> frozenset[str]:
    """등록된 모든 rule_id 집합 (test_rule_registry.py 검증용)."""
    return frozenset(_RULES.keys())
