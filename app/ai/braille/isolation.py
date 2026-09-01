"""체인 내부 요소 격리.

6개 점역 모듈의 translate는 요소 목록을 순회한다. 한 요소의 점역이 예외를 던지면
(예: braillify가 거부하는 문자) 같은 체인의 다른 요소까지 모두 잃는 구조였다 —
6-체인 단위 gather 격리(`return_exceptions=True`)는 있으나 체인 *내부* 격리는 없었다.
safe_translate는 요소별로 예외를 가두고, 실패한 요소만 `[처리 불가]` placeholder로
대체한다(불변 규칙 1: 빈 결과 금지). 다른 요소는 정상 점역된다.

★ 예외 없는 소실도 같이 막는다(2026-07-21). 점역 경로는 변환 못 하는 글자를 조용히
  버리는 폴백을 여러 겹 갖고 있어(translator._safe_to_unicode), 원문이 통째로 미지
  글자면 **예외 없이 빈 문자열**이 나온다. 전 코퍼스 실측 63요소가 이 경로였고,
  페이지에 구멍이 난 채로 나갔다. 예외가 안 났으니 위 격리도 안 걸렸다.
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Iterable

from app.ai.braille.regulations import make_rule
from app.schemas.content import BrailleOutput, LLMOutput

logger = logging.getLogger(__name__)


def safe_translate(
    optimized: Iterable[LLMOutput],
    translate_one: Callable[[LLMOutput], BrailleOutput],
) -> list[BrailleOutput]:
    """요소별 격리 점역. translate_one(opt)이 던지면 그 요소만 placeholder로 대체."""
    results: list[BrailleOutput] = []
    for opt in optimized:
        try:
            out = translate_one(opt)
        except Exception as exc:  # noqa: BLE001 — 요소 격리(한 요소 실패가 체인 전체를 막지 않음)
            logger.warning(
                "요소 점역 실패(격리) id=%s: %s: %s",
                getattr(opt, "element_id", "?"), type(exc).__name__, exc,
            )
            results.append(_placeholder(opt))
            continue
        lost = _w2c_lost_source(opt, out)
        if lost is not None:
            logger.warning(
                "요소 점역 소실(무예외) id=%s: 원문 %r → 점자 0셀",
                getattr(opt, "element_id", "?"), lost[:30],
            )
            out = _placeholder(opt, f"점역 불가 문자 {lost[:12]}")
        out.rule_trail = dedupe_trail(out.rule_trail)
        results.append(out)
    return results


def dedupe_trail(trail: list) -> list:
    """같은 근거가 한 요소에 여러 번 붙는 것을 첫 번째만 남긴다 (Step17, 2026-08-08).

    대표 판정 기준의 '뺄 것' 셋째 항목("같은 줄에 중복으로 여러 번 붙는 것") 구현.
    한 문단에 ①②③④⑤가 있으면 종전에는 제64항이 다섯 번 붙었다 — 점역사는 그 정책을
    한 번 확인하면 끝이고, 나머지 넷은 정작 봐야 할 다른 근거를 화면 밖으로 밀어낸다.
    (rule_id, tag)로 가른다 — 드러냄표 tn_open/tn_close 같은 여닫이 쌍은 서로 다른 tag라
    둘 다 살아남고, 좌표는 그 근거의 **첫 등장 자리**를 가리킨다.
    모든 점역 체인이 safe_translate를 지나므로 여기 한 곳에서 건다.
    """
    seen: set[tuple[str, str]] = set()
    out = []
    for r in trail:
        key = (r.rule_id, r.tag)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


# 내용 없음 판정 — 공백·점자 빈칸(⠀ U+2800)·제어문자는 '내용'이 아니다.
# ⚠ 제어문자를 빼먹으면 원문이 \x00 하나뿐인 요소(추출기가 남기는 빈 블록, 실측 10건)를
#   '내용 있음'으로 보고 멀쩡한 빈칸 출력을 placeholder로 덮어쓴다.
_W2C_BLANK_RE = re.compile(r"[\s\x00-\x1f\x7f-\x9f⠀]+")

# ── 의도적 생략 문자 — 2026-07-29 ────────────────────────────────────────────
# 한자는 점역하지 않는 것이 도서 관행이다(translator: '한자 병기 괄호는 통째 생략',
# 정답 대조 확인 — 언어 p053 '과목(果木)'→'과목', '다정(多情)도 병(病)인양하'는
# 정답과 셀 단위로 일치). 그래서 **한자만 있는 요소는 빈 출력이 정답**이다.
# 그런데 소실 가드가 "원문 있음 + 출력 0셀"만 보고 그걸 소실로 판정해,
# `[처리 불가: 점역 불가 문자 匙]` 같은 **한글 리터럴이 점자 인쇄물에 그대로 찍혔다**
# (실측 2026-07-29: dev 160자 · val 779자 · 홀드아웃 65자 — 점자 파일에 읽을 수 없는 줄).
# 원문에서 한자를 뺐을 때 남는 게 없으면 '소실'이 아니라 '의도적 생략'으로 본다.
# ⚠ 전각 범위를 통째로 넣으면 전각 숫자·영문까지 '없는 셈' 치게 된다 — 괄호류만 명시한다.
_CJK_RE = re.compile(
    "[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"        # 한자(확장A·기본·호환)
    "|[\u3000-\u303f]"                              # CJK 문장부호
    "|[\uff08\uff09\uff3b\uff3d\uff5b\uff5d]"          # 전각 괄호(한자 병기에 붙어 온다)
)


def _w2c_empty(text) -> bool:
    if isinstance(text, str):
        return not _W2C_BLANK_RE.sub("", text)
    return not any(_W2C_BLANK_RE.sub("", ln or "") for ln in (text or []))


def _w2c_lost_source(opt: LLMOutput, out: BrailleOutput) -> str | None:
    """원문은 있는데 출력이 비었으면 그 원문을 돌려준다(아니면 None).

    판정은 **불변 규칙 1 그대로 '빈 결과'**만 본다(점자 셀 유무가 아니라). 점자가 아닌
    줄도 정당한 출력이 있다 — placeholder 리터럴이 그렇고, 그걸 다시 placeholder로
    덮으면 사유가 지워진다.
    시각자료는 선택 초안이 비어도 다른 초안에 내용이 있으면 소실이 아니므로 함께 본다.
    원문이 애초에 공백뿐이면(구분용 빈 요소) 소실이 아니다.
    """
    src = (opt.corrected_text or "") or (opt.tn_text or "")
    if _w2c_empty(src):
        return None
    # 한자만 남은 요소는 빈 출력이 정답이다(도서 관행). 위 _CJK_RE 주석 참조.
    if _w2c_empty(_CJK_RE.sub("", src)):
        return None
    if not _w2c_empty(out.braille_lines):
        return None
    for d in out.drafts or []:
        if not _w2c_empty(d.braille_lines):
            return None
    return src.strip()


def _placeholder(opt: LLMOutput, reason: str = "점역 오류") -> BrailleOutput:
    """실패 요소 → [처리 불가] (placeholder 관례 = 리터럴 줄, 비어있지 않게).

    불변 규칙 2(rule_trail 필수): 실패 요소도 포괄 규정(MCST-0.1)을 달아 응답 계약을 지킨다.
    사유에 원문 조각을 실어 점역사가 무엇이 빠졌는지 바로 보게 한다. quality_checker가
    "[처리 불가" 접두로 C2를 올리므로 접두는 바꾸지 않는다.
    """
    return BrailleOutput(
        element_id=opt.element_id,
        braille_lines=[f"[처리 불가: {reason}]"],
        rule_trail=[make_rule("MCST-기본-1")],
    )
