"""관문 계수기와 경로 무관 정화 — 재구조화 설계 §2-2 (G1~G4).

LLM 출력이 점자 셀로 가는 길에 규칙 관문은 캡셔너 미스 경로 한 곳뿐이었다. 캐시 히트·
그림 회수·고급 점역·시각 초안 폴백·표 점역자주는 관문 없이 직행했다. 그래서 우리는 뒤에서
기웠다(프롬프트 문구 유출·태그 중첩·유형어 중복·표지가 내용인 척). 이 모듈은 그 자리들이
**한 함수를 지나게** 하는 2단계의 계수·정화 몫이다.

  · G1 = `captioner.guard_llm_text` — LLM 문장이 요소 필드에 쓰이기 직전(호출 여섯)
  · G2 = `llm_order` 순열 검사가 규칙 순서로 되돌린 쪽(기존 검사 유지, 기록만)
  · G3 = 점역기 입력 정화(형식 토큰) — `translator.translate_with_breaks` 한 자리
  · G4 = 최종 셀열의 점자 밖 문자 — **읽기 전용 로그**

⚠ **이 파일에는 무거운 의존을 넣지 마라.** `pipeline` 과 `translator` 가 모듈 최상단에서
  부르는데, 그 둘은 test-fast(openai·torch 없음)에서도 import 된다
  (`test_indent_tag_wins.py:11`). openai 를 무는 `captioner` 를 여기서 import 하면
  점역 단위 게이트가 통째로 죽는다.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from contextvars import ContextVar

from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── 되돌리는 길 ────────────────────────────────────────────────────────────
def guard_on() -> bool:
    """`LLM_TEXT_GUARD=0` 이면 관문(G1·G3)을 통째로 끈다.

    **호출 시** 읽는다 — import 시각에 굳히면 프로세스 env 로 주는 A/B 가 안 먹는다
    (원장 `ab-off-arm-must-be-truly-off`, 0903 에 하루 두 번 무효가 났다).
    끈 팔의 확인은 계수기다: 관문 통과 로그(`관문 G1 발동`)가 0 이어야 정말 꺼진 것이다.
    """
    return os.environ.get("LLM_TEXT_GUARD", "1") != "0"


# ── 계수기 ────────────────────────────────────────────────────────────────
# 쪽마다 따로 세야 한다. `pipeline.run` 은 쪽 하나가 한 Task 이고 여러 쪽이 같은 프로세스에서
# 겹쳐 돈다 — 모듈 전역 카운터를 쓰면 쪽 사이로 샌다. `ContextVar` 는 Task 마다 컨텍스트를
# 복사하므로 쪽 시작에서 새 Counter 를 심으면 그 쪽 안(하위 gather·to_thread 포함)에서만 센다.
_COUNTS: ContextVar[Counter | None] = ContextVar("gate_counts", default=None)

_GATE_MSG = {
    "G1": "AI 문장 관문이 걷어낸 자리",
    "G2": "읽기순서를 규칙 순서로 되돌린 쪽",
    "G3": "점역기 입력에서 걷어낸 것",
    "G4": "점자 밖 문자가 셀열에 남았다",
}


def gate_reset() -> None:
    """쪽 시작. 이 자리부터 세는 것이 이 쪽 몫이다."""
    _COUNTS.set(Counter())


def gate_hit(gate: str, rule: str, n: int = 1) -> None:
    """관문 발동 한 건. 계수기가 없는 자리(단위 테스트·도구)에서도 로그는 남는다."""
    if n <= 0:
        return
    counts = _COUNTS.get()
    if counts is not None:
        counts[(gate, rule)] += n
    logger.info("관문 %s 발동 %s %d건", gate, rule, n,
                extra={"gate": gate, "rule": rule, "n": n})


def gate_counts() -> dict[tuple[str, str], int]:
    return dict(_COUNTS.get() or {})


def gate_flags() -> list[dict]:
    """이 쪽에서 발동한 관문 → `quality_report.review_flags` 코드 넷.

    ★ proto 변경이 아니다 — `ReviewFlag{ string type; … }` 라 코드는 문자열이다
      (`protos/braille_service.proto:87-100`). FE 가 새 코드를 어떻게 보여 줄지만
      합의 대상이다(설계 §2-2 기록).
    """
    counts = _COUNTS.get() or Counter()
    out: list[dict] = []
    for gate in ("G1", "G2", "G3", "G4"):
        rules = {rule: n for (g, rule), n in counts.items() if g == gate}
        if not rules:
            continue
        detail = ", ".join(f"{r} {n}건" for r, n in sorted(rules.items()))
        out.append({"type": gate, "element_id": "page",
                    "message": f"{_GATE_MSG[gate]} — {detail}"})
    return out


# ── 추출 모델의 '못 읽었다' 해설문 ─────────────────────────────────────────
# ★ `pipeline` 에서 옮겨 왔다(설계 §2-2 "정규식 두 벌을 이 함수 안에서 합친다").
#   판정은 두 자리가 쓴다 — `pipeline._parse_txt_result`(요소 content) 와
#   `captioner.guard_llm_text`(관문 G1). 표가 갈리면 같은 문장이 한쪽만 걸린다.
#
# 실측 근거(옮기기 전 주석 그대로): 검출은 아래 2건뿐이고, 오검출 0건이다.
#   "... of a bookshelf ... Therefore, no OCR output can be generated."   (183자)
#   "... Therefore, the correct OCR output is an empty string."           (200자)
#   외국어 지문이 'There is no question…' 처럼 부정문을 흔히 쓰므로, 패턴은
#   **OCR/판독 작업 자체를 자기언급하는 표현**만 잡도록 좁혔다.
#   (재현: temp/r29_census.py)
_TAG_TOKEN_RE = re.compile(r"<!/?[^>]+>")

_EXTRACTION_REFUSAL_RES = (
    # '읽을 수 있는 글자가 없다' 계열
    re.compile(r"\bno\s+(?:discernible|legible|readable|recognizable|visible)\s+"
               r"(?:text|characters|words|content)", re.IGNORECASE),
    re.compile(r"\bno\s+text\s+(?:is\s+)?(?:present|visible|detected|found)\b", re.IGNORECASE),
    # 'OCR 결과가 없다/빈 문자열이다' 계열 — 추출 작업 자체를 자기언급
    re.compile(r"\bno\s+OCR\s+output\b", re.IGNORECASE),
    re.compile(r"\bOCR\s+output\s+(?:is|would\s+be|should\s+be)\s+(?:an?\s+)?empty",
               re.IGNORECASE),
    re.compile(r"\b(?:cannot|can(?:'|no)t|unable\s+to)\s+(?:be\s+)?"
               r"(?:generate|generated|extract|extracted|perform|performed|produce|produced)\b"
               r"[^.]{0,40}\bOCR\b", re.IGNORECASE),
    # 모델 사과·자기소개 계열(문두 한정)
    re.compile(r"^\s*(?:I'?m\s+sorry|I\s+am\s+sorry|As\s+an\s+AI\b)", re.IGNORECASE),
    # ★ 한국어 짝(2026-09-03). 위 패턴이 전부 영어라, 한국어로 답하는 모델이 쓴
    #   해설문은 한 줄도 안 걸려 초안에 그대로 실렸다(FE QA S-7).
    re.compile(r"(?:읽을\s*수\s*있는|판독\s*가능한|인식(?:할\s*수\s*있는|되는))\s*"
               r"(?:글자|문자|텍스트|내용)[가이]?\s*(?:없|보이지\s*않)"),
    re.compile(r"(?:텍스트|글자|내용)[가이]?\s*(?:전혀\s*)?(?:없습니다|없음|보이지\s*않습니다)"),
    re.compile(r"(?:추출|판독|인식)(?:할\s*수\s*(?:없|가\s*없)|이\s*(?:불가|되지\s*않))"),
    re.compile(r"^\s*(?:죄송(?:합니다|하지만)|저는\s*(?:AI|인공지능))"),
    re.compile(r"^\s*이\s*(?:이미지|페이지|지면)에(?:는|서는)?\s*[^.\n]{0,20}"
               r"(?:없습니다|없음|보이지\s*않습니다)"),
)


def is_extraction_refusal(content: str) -> bool:
    """이 글이 '모델이 못 읽었다고 쓴 해설문'인가(내용이 아님)."""
    c = re.sub(r"\s+", " ", _TAG_TOKEN_RE.sub("", content or "")).strip()
    if not c:
        return False
    return any(p.search(c) for p in _EXTRACTION_REFUSAL_RES)


# ── G3 형식 토큰 ──────────────────────────────────────────────────────────
# `⟦재료⟧` 는 캡셔너와 조립기 사이의 **약속 기호**지 본문이 아니다. 조립기 앞단
# (`visual_drafts`·`base_opt`·`cartoon_opt` 의 `split_material`)이 이미 떼지만,
# 그 셋을 안 지나는 길(표 점역자주·중첩 블록·별책 참조)이 남아 있다. 점역기 입구
# 한 자리에서 다시 본다 — 남으면 글자 그대로 점자가 된다(`⟦재료⟧` 는 8셀이 넘는다).
#
# ⚠ **재료 열쇠말 머리(`글자:`·`수치:`)는 여기서 안 건드린다.** 그 말은 정상 캡션에도
#   그대로 나온다("글자: 없음" 이 아니라 "글자 크기가…"). 마커가 사라진 뒤의 열쇠말은
#   본문과 구분이 안 되므로, 지우면 정상 문장을 먹는다. 마커만 센다.
_FORMAT_TOKEN_RE = re.compile(r"⟦[^⟧\n]{0,24}⟧")


def strip_format_tokens(text: str) -> str:
    """G3 — 점역기 입력에서 형식 토큰을 걷는다. **제거만** 한다(다시 쓰지 않는다)."""
    if not text or "⟦" not in text:
        return text or ""
    out, n = _FORMAT_TOKEN_RE.subn("", text)
    if n:
        gate_hit("G3", "형식토큰", n)
    return out


# ── G4 점자 밖 문자(읽기 전용) ────────────────────────────────────────────
# 허용은 점자 블록(U+2800~28FF)·공백·개행뿐이다. 태그는 layout 이 먹으므로 여기 남으면
# 결함이다(정방향 이물질 자와 같은 잣대, `temp/l8/fwd_artifact.py`).
# ⚠ **세기만 한다.** 최종 셀열을 여기서 고치면 그 자리가 새 결함의 출처가 된다.
_FOREIGN_CELL_RE = re.compile(r"[^⠀-⣿ \n]")


def count_foreign_cells(lines) -> Counter:
    """셀열에 남은 점자 밖 문자 → {문자: 횟수}. 읽기 전용."""
    found: Counter = Counter()
    for line in lines or ():
        for ch in _FOREIGN_CELL_RE.findall(line or ""):
            found[ch] += 1
    return found
