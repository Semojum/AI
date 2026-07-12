"""품질 검증 (PART 11).

C1~C7 Critical 오류 감지 + R1~R12 검토 플래그 생성 후 페이지 status 결정.
모델 없음 — 파이프라인 산출물(추출·opt·점역·조판) 신호만 사용하는 규칙 기반.

status 결정 규칙 (plan V2_기술명세서 §4-1):
    C1(전체 실패) 또는 C7(타임아웃)   → BLOCKED
    C2~C6 1개 이상 (요소 BLOCKED)     → NEEDS_REVIEW
    C 오류 없음 + R 플래그 1개 이상   → NEEDS_REVIEW
    오류/플래그 없음                  → COMPLETED

C5(수표 누락)는 런타임 발생 불가 — 배포 전 test_rule_engine.py 전수 통과로 차단.
C7(타임아웃)은 pipeline.run()의 asyncio.wait_for가 직접 BLOCKED 응답을 만들므로
이 검사기는 C1~C4·C6만 판정한다.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from app.schemas.content import BrailleOutput, ExtractedContent, LLMOutput
from app.schemas.layout import LayoutResult
from app.schemas.quality import CriticalError, QualityReport, ReviewFlag
from app.utils.logger import get_logger

logger = get_logger(__name__)

# C6: 32칸 초과율 임계 (plan §4-1)
C6_OVERFLOW_THRESHOLD = 0.30
# R1: OCR 신뢰도 미달 임계
R1_CONFIDENCE_THRESHOLD = 0.85

# opt/점역 placeholder → Critical 유형 (구체 패턴을 먼저 검사한다 — "[처리 불가"가 가장 광범위)
# 실패 문자열이 본문에 남으면 그대로 점자로 찍혀 학생에게 나간다 → 반드시 Critical로 잡는다.
# (구 버전은 "[캡셔닝 실패]"를 목록에 두지 않아, API 쿼터 소진 페이지가 COMPLETED로 나갔다.)
_PLACEHOLDER_CRITICALS: list[tuple[str, str, str]] = [
    ("[수식 재확인 필요", "C3", "수식 파손 — LaTeX 파서 실패로 placeholder 삽입"),
    ("[표 수동", "C4", "표 완전 실패 — 수동 입력 placeholder 삽입"),
    ("[캡셔닝 실패", "C2", "시각자료 캡셔닝 실패 문자열이 본문에 삽입됨"),
    ("[이미지 경로 없음", "C2", "시각자료 이미지 유실 — 경로 없음 문자열이 본문에 삽입됨"),
    ("[처리 불가", "C2", "콘텐츠 블록 소실 — 처리 불가 placeholder 삽입"),
]

# ExtractedContent.flags → 검토 플래그 (content.py 주석의 플래그 어휘)
_FLAG_TO_REVIEW: dict[str, tuple[str, str]] = {
    "C2_FALLBACK": ("R1", "FALLBACK 경로로 처리됨(콘텐츠 블록) — 신뢰도 확인 필요"),
    "C3_FALLBACK": ("R1", "FALLBACK 경로로 처리됨(수식) — 신뢰도 확인 필요"),
    "C4_FALLBACK": ("R1", "FALLBACK 경로로 처리됨(표) — 신뢰도 확인 필요"),
    "VERTICAL_TEXT": ("R7", "세로쓰기 텍스트 — 읽기순서 확인 필요"),
    "SUBTYPE_UNCERTAIN": ("R2", "시각자료 세분류 불확실"),
    # 캡셔닝 실패 → 규정상 '생략' 표기로 폴백하되(§6.3.4(2)②), 점역사가 직접 대체텍스트를
    # 써야 하므로 반드시 검토로 띄운다. 조용히 COMPLETED로 나가면 안 된다.
    "CAPTION_FAILED": ("R11", "시각자료 캡셔닝 실패 — 대체텍스트를 직접 작성해야 함"),
    "R5": ("R5", "초안에 원본 수치 누락 — 수치 변조 검토 필요"),
}
_GENERIC_R_FLAG = re.compile(r"^R([1-9]|1[0-2])$")


class QualityChecker:
    """규칙 기반 페이지 품질 판정. 상태 없음 — check()만 노출."""

    def check(
        self,
        page_id: str,
        *,
        layout_result: Optional[LayoutResult] = None,
        extracted: Iterable[ExtractedContent] = (),
        llm_outputs: Iterable[LLMOutput] = (),
        braille_outputs: Iterable[BrailleOutput] = (),
        line_overflow_rate: float = 0.0,
    ) -> QualityReport:
        extracted = list(extracted)
        llm_outputs = list(llm_outputs)
        braille_outputs = list(braille_outputs)
        criticals: list[CriticalError] = []
        reviews: list[ReviewFlag] = []

        # ── 요소 단위: opt 출력 placeholder → C2/C3/C4 ────────────────────
        blocked_ids: set[str] = set()
        opt_blocked_ids: set[str] = set()   # C1(전체 실패) 판정용 — opt 단계 실패만
        for o in llm_outputs:
            eid = str(o.element_id)
            text = o.corrected_text or ""
            for marker, ctype, msg in _PLACEHOLDER_CRITICALS:
                if marker in text:
                    criticals.append(CriticalError(type=ctype, element_id=eid, message=msg))
                    blocked_ids.add(eid)
                    opt_blocked_ids.add(eid)
                    break

        # 점역 단계에서만 실패한 요소(opt는 정상) → C2
        for b in braille_outputs:
            eid = str(b.element_id)
            if eid in blocked_ids:
                continue
            if any(ln.startswith("[처리 불가") for ln in b.braille_lines):
                criticals.append(CriticalError(
                    type="C2", element_id=eid,
                    message="점역 실패 — 처리 불가 placeholder 삽입",
                ))
                blocked_ids.add(eid)

        # ── 요소 단위: 추출 신호 → R 플래그 ──────────────────────────────
        for e in extracted:
            eid = str(e.element_id)
            for flag in e.flags or []:
                mapped = _FLAG_TO_REVIEW.get(flag)
                if mapped is None and _GENERIC_R_FLAG.match(flag):
                    mapped = (flag, f"검토 권고 플래그 {flag}")
                if mapped:
                    reviews.append(ReviewFlag(type=mapped[0], element_id=eid, message=mapped[1]))
            if eid not in blocked_ids and e.ocr_confidence < R1_CONFIDENCE_THRESHOLD:
                reviews.append(ReviewFlag(
                    type="R1", element_id=eid,
                    message=f"OCR 신뢰도 미달 ({e.ocr_confidence:.2f} < {R1_CONFIDENCE_THRESHOLD})",
                ))

        # ── 페이지 단위 ───────────────────────────────────────────────────
        n_elements = len(layout_result.elements) if layout_result else 0
        c1_message = ""
        if n_elements == 0 and not llm_outputs:
            c1_message = "전체 추출 실패 — 페이지에서 요소를 하나도 얻지 못함"
        elif n_elements > 0 and not llm_outputs:
            c1_message = "전체 처리 실패 — 모든 체인이 출력 없이 종료"
        elif llm_outputs and len(opt_blocked_ids) == len(llm_outputs):
            # 점역 단계만 실패한 요소는 제외 — 텍스트 콘텐츠는 살아 있으므로 C2(NEEDS_REVIEW)
            c1_message = "전체 처리 실패 — 모든 요소가 placeholder로 대체됨"
        if c1_message:
            criticals.append(CriticalError(type="C1", element_id="page", message=c1_message))

        if line_overflow_rate > C6_OVERFLOW_THRESHOLD:
            criticals.append(CriticalError(
                type="C6", element_id="page",
                message=f"32칸 초과율 {line_overflow_rate:.2f} > {C6_OVERFLOW_THRESHOLD}",
            ))

        status = self._decide_status(criticals, reviews)
        conf = [e.ocr_confidence for e in extracted]
        report = QualityReport(
            page_id=page_id,
            status=status,
            ocr_confidence_avg=(sum(conf) / len(conf)) if conf else 0.0,
            line_overflow_rate=line_overflow_rate,
            critical_errors=criticals,
            review_flags=reviews,
        )
        if status != "COMPLETED":
            logger.info(
                "품질 판정 %s (page=%s · C %d건 · R %d건)",
                status, page_id, len(criticals), len(reviews),
            )
        return report

    @staticmethod
    def _decide_status(criticals: list[CriticalError], reviews: list[ReviewFlag]) -> str:
        if any(c.type in ("C1", "C7") for c in criticals):
            return "BLOCKED"
        if criticals or reviews:
            return "NEEDS_REVIEW"
        return "COMPLETED"
