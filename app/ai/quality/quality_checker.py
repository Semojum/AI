"""품질 검증 (PART 11).

C1~C7 Critical 오류 감지 + R1~R12 검토 플래그 생성 후 페이지 status 결정.
모델 없음 — 파이프라인 산출물(추출·opt·점역·조판) 신호만 사용하는 규칙 기반.

status 결정 규칙 (plan V2_기술명세서 §4-1):
    C1(전체 실패) 또는 C7(타임아웃)   → BLOCKED
    C2~C6 1개 이상 (요소 BLOCKED)     → NEEDS_REVIEW
    C 오류 없음 + R 플래그 1개 이상   → NEEDS_REVIEW
    오류/플래그 없음                  → COMPLETED

C5(수표 누락)는 배포 전 test_rule_engine.py 전수 통과가 1차 방어선, 여기 런타임
스캐너가 2차 방어선: opt 텍스트에 아라비아 숫자가 있는데 해당 요소 점자에 수표(⠼)가
하나도 없으면 C5. 현 엔진은 모든 숫자 경로(수식 지수·분수·소수·연도 포함)에 수표를
넣으므로 미검출 = 회귀다. ⚠ **⠼ 유무만 보면 안 된다** — 영어 약자 ble이 같은 점형이라
`possible`(⠏⠕⠎⠎⠊⠼) 한 낱말이 스캐너를 대신 만족시켜 진짜 누락을 가린다.
수표인지 약자인지는 number_sign.has_number_sign이 가른다(2026-07-27).
플래그 신뢰성(30초 케이스: COMPLETED를 믿고 스킴)의 전제라 조용히 COMPLETED로 나가면 안 된다.
C7(타임아웃)은 pipeline.run()의 asyncio.wait_for가 직접 BLOCKED 응답을 만들므로
이 검사기는 C1~C6을 판정한다.

★ 플래그 신뢰성 감사(2026-08-10, dev-2027+val-2027 839쪽·34,709요소를 gold 대비 셀 편집으로
  라벨). 감사 전 플래그는 **무작위보다 나빴다** — 붙은 자리의 28.2%만 크게 틀렸는데 기준선이
  33.2%다(리프트 0.85x). 소음원 셋을 걷어내고 빠진 축 둘을 채웠다:
    · C5 게이트가 태그 이름의 숫자로 열려 146건 중 142건(97.3%)이 오탐 → 게이트에서 태그·원문자를 벗김
    · MinerU 폴백 R1이 요소마다 떠서 38쪽에 2,096건(쪽당 55건) → 쪽 1건으로 합침
    · 시각자료 R11이 '캡셔닝 실패'일 때만 떠서, 오늘 캡션이 복구되자 371요소가 무플래그가 됐다 →
      AI가 쓴 설명 자체를 검토 대상으로(설명이 있다 ≠ 맞다. 눈검사 3건 중 2건 내용 오류)
    · 표에 플래그가 사실상 없었다(0.8%) — 편집량 2위 축(전체 편집셀의 11.2%)인데 →
      R10 배선(편집필요 정밀도 98.7% · 기준선 58.3%)
  결과: 플래그 4,211→2,389건(−43%), '수정필요' 정밀도 60.6%→73.4%. 보고서
  `V2/temp/reports/Flag_reliability_report.html`, 재현 `V2/temp/flagaudit/`.
  ⚠ 그래도 **재현율은 6.9%**고 COMPLETED 쪽의 21.2%가 셀의 30% 이상 수정을 필요로 한다 —
  "플래그 없는 쪽은 안 봐도 된다"를 아직 숫자로 지지할 수 없다. 지금 플래그는 **검수 순서** 신호다.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

from app.ai.braille.number_sign import _TAG_TOKEN_RE, has_number_sign
from app.schemas.content import BrailleOutput, ExtractedContent, LLMOutput
from app.schemas.layout import LayoutResult
from app.schemas.quality import CriticalError, QualityReport, ReviewFlag
from app.utils.logger import get_logger

logger = get_logger(__name__)

# C6: 32칸 초과율 임계 (plan §4-1)
C6_OVERFLOW_THRESHOLD = 0.30
# R1: OCR 신뢰도 미달 임계
R1_CONFIDENCE_THRESHOLD = 0.85

# ── 글자 소실 감지 (2026-08-02) ──────────────────────────────────────────────
# 일부 교과서 PDF는 폰트 cmap이 깨져 있어 텍스트 레이어에 **제어문자가 글자 자리를
# 대신 차지**한다(PUA 사례와 같은 부류). 실측(코퍼스 1,131쪽): 277요소·352자·126쪽(11%),
# 생물이 234건으로 압도적.
#   예) `**\x08국 인구는 \x03\x06\x04\x06년까지 …`  ← "한국 인구는 2020년까지"
# MinerU 오추출이 아니라 **PDF 자체가 그렇다** — 같은 자리의 텍스트 레이어도 동일하다.
# `translator.sanitize_for_braille`가 점역 전에 이 글자들을 지우므로 점자에 쓰레기가
# 나가지는 않는다. 대신 **글자가 조용히 사라진다** — 점역사는 원본을 봐야 하는데
# 아무 표시가 없었다. 그래서 R1(추출 신뢰도 미달)로 올려 알린다.
# 셀 수 영향은 무시할 수준이지만(352자) 그건 이 플래그의 목적이 아니다.
_LOST_GLYPH_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
# R2: 시각자료 세분류 신뢰도 미달 임계 (classifier logprob 기반, test_classifier 경계 기준)
R2_SUBTYPE_CONFIDENCE_THRESHOLD = 0.75

# C5: 수표(⠼) 런타임 스캐너 — 아라비아 숫자와 수표 기호
_C5_DIGIT_RE = re.compile(r"[0-9]")
# ★ 게이트는 **점역 대상 글자에만** 연다(2026-08-10). 종전엔 corrected_text를 원문 그대로
# 훑어 인라인 태그 이름의 숫자(`<!상자끝2>`)가 게이트를 열었다 — 태그는 테두리 점형으로
# 치환되니 수표가 나올 리 없고, 그래서 무조건 C5가 떴다. 실측(dev+val 839쪽) C5 146건 중
# **142건(97.3%)이 이 오탐**이고, 남은 4건도 제64항 원문자(`\textcircled{7}`)라 number_sign
# 주석대로 수표가 아니다. C5는 배포 블로커 신호다 — 오탐이 쌓이면 점역사가 제일 중요한
# 플래그부터 무시하게 되므로 진짜 누락만 남긴다. 태그 제거는 contraction_lookalikes와
# **같은 정규식**을 쓴다(둘이 갈리면 판정이 어긋난다).
_C5_CIRCLED_RE = re.compile(r"\\textcircled\{[^}]*\}")


def _c5_gate_text(text: str) -> str:
    """C5 숫자 게이트가 볼 원문 — 인라인 태그와 원문자를 벗긴 것."""
    return _C5_CIRCLED_RE.sub("", _TAG_TOKEN_RE.sub("", text or ""))


# ── R13: 본문 텍스트 위험 구간 (2026-08-10) ─────────────────────────────────
# 플래그 재현율이 6.9%인 이유는 편집의 85.8%가 본문 텍스트인데 본문에 플래그가 사실상
# 없었기 때문이다(본문 요소의 11.8%만 플래그, 재현 8.8%). gold 없이 본문 오류를 짚는
# 신호를 찾아 dev+val 839쪽·32,310 본문요소를 gold 대비 셀 편집으로 라벨해 재봤다.
#
# 재보고 **기각한** 후보(temp/reports/Recall_signals.html §5):
#   · 역점역 왕복 일치도 — 순수 산문에서 길이 계층 안 AUC 0.50~0.55로 사실상 무정보.
#     (전체 AUC가 0.64로 보이는 건 길이 대리효과다. 다만 rt=1.0은 '안전' 쪽으로는
#      쓸 만해서 confidence.py의 review_grade가 이미 그 용도로 쓰고 있다.)
#   · 형태소 OOV·1음절 비율(언어모델 이상치) — AUC 0.479~0.505. 완전 무정보.
#   · 쪽 규모 대비 커버리지 — 쪽 단위로는 되지만(아래) 요소 단위 신호가 아니다.
#
# 남은 것은 **어디가 위험한지**를 내용 종류로 가르는 것뿐이었다. 실측(839쪽, 본문 32,310요소):
#   태그(테두리 등) 포함   3,182요소  수정필요 88.3%  크게틀림 58.9%  본문 편집셀의 25.5%
#   로마자 2자 이상        5,390요소  수정필요 88.6%  크게틀림 55.8%  본문 편집셀의 36.3%
#   숫자 2자 이상          7,928요소  수정필요 81.2%  크게틀림 48.1%  본문 편집셀의 41.6%
#   └ 합집합             12,303요소  수정필요 82.1%  크게틀림 48.9%  본문 편집셀의 67.6%
#   남는 순수 산문        20,007요소  수정필요 41.4%  크게틀림 19.6%  본문 편집셀의 32.4%
# 기준선은 수정필요 58.3% · 크게틀림 33.2%다. 리프트는 dev 1.52x · val 1.57x로 책이
# 달라도 안정적이다(정밀도 자체는 책의 기준율을 따라 움직인다).
#
# 임계 2자는 **한계정밀도로 골랐다**. 현행∪R13 기준으로 임계를 낮출 때 새로 붙는 플래그의
# '수정필요' 정밀도: 5→3자 80%대 유지 · 3→2자 80.2% · 2→1자 **64.6%**(기준선 58.3%에
# 근접 = 소음). 그래서 2에서 멈춘다. 전체 수치는 임계 3자→2자로 재현율(크게) 46.8→57.4%,
# 편집셀 재현 64.7→71.8%, 정밀도(수정필요)는 81.2→81.0%로 사실상 불변이다.
#
# ★ 이건 '탐지기'가 아니라 R10(표)과 같은 **등급**이다. 조건에 걸린 요소 안에서 어느
#   것이 더 위험한지는 못 가른다. 쓸 수 있는 말은 "여기는 본문 평균보다 훨씬 자주
#   고쳐야 한다"까지고, **순수 산문 32.4%의 편집셀은 여전히 무신호**다.
# ── R14: 글꼴이 거짓말한 추출 (2026-08-10) ──────────────────────────────────
# 코퍼스 PDF의 **60.2%**(수학2는 147/147 전량)가 `/Encoding`·`/ToUnicode`와 실제로 그려지는
# 글리프가 다르다. 탐지는 `pdf_analyzer.mangled_glyph_chars`가 이미 하는데 **라우팅과 경고
# 로그까지만 가고 요소 플래그로는 안 올라왔다.** 그래서 깨진 글자가 **그대로 점역돼 나간다**:
#
#   묵자  "삼각형 "#$에서 …"                    ← ABC여야 한다
#   묵자  "TJOÛ(A+B)+DPTÛA=TJOÛB+1이 성립할 때"  ← sin²(A+B)+cos²A=sin²B+1
#   점자  ⠦⠸⠹⠴⠈⠎⠝⠠⠎ …                        ← 점역사가 이걸 읽는다
#
# 기존 R1('글자 소실')은 제어문자만 보므로 이 유형을 못 잡는다. 점역사가 원본을 봐야만
# 고칠 수 있는 자리라 반드시 띄운다 — **등급이 아니라 결함**이므로 status에도 반영한다.
#
# ⚠ **못 잡는 것이 있다 — 알고 두는 것이다.** 위 예의 `"#$`(= ABC를 +31 민 것)는 안 걸린다.
#   `"`·`#`·`$`가 정상 텍스트에도 나오는 ASCII라 "교과서에 없는 코드포인트" 규칙 밖이다.
#   텍스트만으로 잡아 보려고 둘을 재보고 **둘 다 기각**했다(본문 284,711요소 실측):
#     · 한글에 바로 붙은 ASCII 기호 2자 이상 → 오탐 **8.2%**. `(가), (나)`·`(스\n웨덴,`이 걸린다.
#     · +31 하면 전부 라틴 글자가 되는 런 → 오탐 **23.3%**. `(1)`→`GPH`·`01`→`OP`처럼
#       숫자·괄호가 전부 글자로 밀린다.
#   같은 이유로 `〈`(홑화살괄호)도 못 잡는다 — 진짜 부등호와 코드가 같다.
#   **다음 사람이 같은 둘을 또 시도하지 않게 여기 적어 둔다.** 잡으려면 텍스트 밖으로 나가야
#   한다(렌더 이미지 OCR과 텍스트 레이어를 대조하는 식) — 비싸지만 결정적이다.
def _r14_reason(text: str) -> str:
    """글꼴 매핑이 깨져 추출된 흔적이 있으면 사유, 없으면 빈 문자열."""
    if not text:
        return ""
    try:
        from app.ai.preprocessor.pdf_analyzer import mangled_glyph_chars
    except Exception:                       # noqa: BLE001 — 전처리 모듈 없이도 검사는 돈다
        return ""
    layer_bad, _symbol_bad = mangled_glyph_chars(text)
    if not layer_bad:
        return ""
    top = "".join(ch for ch, _ in layer_bad.most_common(4))
    return f"원본 글꼴이 깨져 추출됨({top}) — 원본을 보고 확인해야 합니다"


_R13_LATIN_RE = re.compile(r"[A-Za-z]")
_R13_MIN_CHARS = 2


def _r13_reason(text: str) -> Optional[str]:
    """본문 텍스트 요소의 '위험 구간' 사유(없으면 None). gold 없이 원문만 본다."""
    why: list[str] = []
    if _TAG_TOKEN_RE.search(text or ""):
        why.append("테두리·점역자주 등 레이아웃 태그")
    if len(_R13_LATIN_RE.findall(text or "")) >= _R13_MIN_CHARS:
        why.append("로마자")
    # 숫자는 C5와 **같은 게이트**로 센다 — 태그 이름의 숫자(`<!상자끝2>`)를 세면
    # C5가 밟았던 오탐을 그대로 반복한다.
    if len(_C5_DIGIT_RE.findall(_c5_gate_text(text))) >= _R13_MIN_CHARS:
        why.append("아라비아 숫자")
    if not why:
        return None
    return (f"{' · '.join(why)}가 있는 본문 — 실측상 이런 본문은 82.1%가 수정이 "
            f"필요했습니다(본문 평균 56.9%). 우선 확인 권장")


# 시각자료 유형(레이아웃 type 기준) — 본문 글자를 옮기는 게 아니라 **AI가 설명을 쓴다**.
_VISUAL_TYPES = frozenset({"image", "cartoon", "chart_graph", "diagram"})

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

        # ── 요소 단위: C5 런타임 스캐너 — 원문에 숫자가 있는데 점자에 수표(⠼) 0개 ──
        # rule-based 그대로 옮기는 요소(텍스트·수식·표)만 검사. 시각자료(visual_subtype
        # 있음)는 LLM 생성 초안이라 수치가 정당하게 요약·생략될 수 있고(R5 소관) 제외.
        ext_by_id = {str(e.element_id): e for e in extracted}
        braille_by_id = {str(b.element_id): b for b in braille_outputs}
        for o in llm_outputs:
            eid = str(o.element_id)
            if eid in blocked_ids:
                continue
            gate_text = _c5_gate_text(o.corrected_text)
            if not _C5_DIGIT_RE.search(gate_text):
                continue
            ext = ext_by_id.get(eid)
            if ext is not None and ext.visual_subtype:
                continue
            b = braille_by_id.get(eid)
            if b is None or not any(ln.strip() for ln in b.braille_lines):
                continue  # 점역 출력 자체가 없으면 상위 실패 신호(C1/C2)의 소관
            # ⠼가 있기만 하면 통과시키면 안 된다 — 영어 약자 ble이 같은 점형이라
            # `possible`의 ⠼가 스캐너를 대신 만족시켜 진짜 수표 누락을 가린다(number_sign.py).
            if not has_number_sign(o.corrected_text or "", "".join(b.braille_lines)):
                criticals.append(CriticalError(
                    type="C5", element_id=eid,
                    message="수표(⠼) 누락 — 원문에 아라비아 숫자가 있으나 요소 점자에 수표 없음",
                ))
                blocked_ids.add(eid)

        # ── 요소 단위: 추출 신호 → R 플래그 ──────────────────────────────
        # 레이아웃 유형은 여기서만 알 수 있다(ExtractedContent에는 type이 없다).
        types = {str(b.element_id): b.type
                 for b in (layout_result.elements if layout_result else ())}
        n_fallback = 0        # MinerU 폴백은 쪽 전체가 같은 사정이라 쪽 단위로 한 번만 띄운다
        for e in extracted:
            eid = str(e.element_id)
            for flag in e.flags or []:
                if flag.endswith("_FALLBACK"):
                    # 폴백은 **요소마다 같은 문구**로 떠서 실측 38쪽에 2,096건이 쌓였다.
                    # 한 쪽에 55건이 같은 말을 하면 그건 신호가 아니라 소음이고, 진짜
                    # 신호(캡션 실패·표)를 화면 밖으로 밀어낸다. 아래에서 쪽 1건으로 낸다.
                    n_fallback += 1
                    continue
                mapped = _FLAG_TO_REVIEW.get(flag)
                if mapped is None and _GENERIC_R_FLAG.match(flag):
                    mapped = (flag, f"검토 권고 플래그 {flag}")
                if mapped:
                    reviews.append(ReviewFlag(type=mapped[0], element_id=eid, message=mapped[1]))
            # 시각자료 설명은 **AI가 쓴 글**이다 — 캡셔닝이 성공해도 검토를 빼면 안 된다.
            # 종전엔 CAPTION_FAILED(=설명 없음)일 때만 R11이 떴다. 2026-08-10 빈 캡션
            # 371건을 복구하자 그 플래그가 그대로 꺼졌는데, 복구된 설명은 눈검사 3건 중
            # 2건이 내용 오류였다(누락·지어냄). "설명이 있다"는 "맞다"가 아니다.
            # 실측 리프트: 시각 요소는 크게 틀릴 확률이 80~94%(쪽 평균 33%)로 가장 높다.
            if (eid not in blocked_ids and types.get(eid) in _VISUAL_TYPES
                    and "CAPTION_FAILED" not in (e.flags or [])):
                reviews.append(ReviewFlag(
                    type="R11", element_id=eid,
                    message="AI가 쓴 시각자료 설명 — 원본 그림과 대조가 필요합니다",
                ))
            # 표는 조판 재량이 크고(도서지침 "점역자에 따라서 표기") 실측 편집량이 본문 다음으로
            # 많다(전체 편집셀의 11.2%, 요소의 1.1%). 실측 839쪽: 표 요소의 98.7%가 편집이
            # 필요했고 53.9%는 크게 틀렸다(쪽 평균 33.2%). 지금까지 표에는 플래그가 사실상
            # 안 붙었다(0.8%) — 점역사에게 본문과 같은 안전도로 보였다는 뜻이다.
            if eid not in blocked_ids and types.get(eid) == "table":
                reviews.append(ReviewFlag(
                    type="R10", element_id=eid,
                    message="표 — 전개 방식이 점역사 재량이라 초안과 다를 수 있습니다",
                ))
            # 본문 텍스트 위험 구간 — 근거·한계는 위 _r13_reason 주석.
            if eid not in blocked_ids and types.get(eid) == "text":
                r13 = _r13_reason(e.corrected_text or "")
                if r13:
                    reviews.append(ReviewFlag(type="R13", element_id=eid, message=r13))
            # 글꼴이 거짓말한 추출 — 등급이 아니라 결함이다(위 _r14_reason 주석).
            if eid not in blocked_ids:
                r14 = _r14_reason(e.corrected_text or "")
                if r14:
                    reviews.append(ReviewFlag(type="R14", element_id=eid, message=r14))
            if eid not in blocked_ids and e.ocr_confidence < R1_CONFIDENCE_THRESHOLD:
                reviews.append(ReviewFlag(
                    type="R1", element_id=eid,
                    message=f"OCR 신뢰도 미달 ({e.ocr_confidence:.2f} < {R1_CONFIDENCE_THRESHOLD})",
                ))
            # 글자 소실(폰트 cmap 파손) — 위 상수 주석 참조. 신뢰도와 무관하게 발화한다:
            # 이 요소들은 ocr_confidence가 높게 잡혀 R1 임계에 안 걸린다.
            lost = _LOST_GLYPH_RE.findall(e.corrected_text or "")
            if eid not in blocked_ids and lost:
                reviews.append(ReviewFlag(
                    type="R1", element_id=eid,
                    message=(f"글자 소실 의심 {len(lost)}자 — 원본 PDF의 폰트 매핑이 깨져 "
                             f"해당 자리가 비어 나갑니다. 원본과 대조가 필요합니다."),
                ))
            # R2: 세분류 신뢰도 미달 (경계 파일에 SUBTYPE_UNCERTAIN 플래그가 이미 있으면
            # 위 플래그 매핑이 R2를 냈으므로 중복 발화하지 않는다)
            if (
                eid not in blocked_ids
                and e.subtype_confidence is not None
                and e.subtype_confidence < R2_SUBTYPE_CONFIDENCE_THRESHOLD
                and "SUBTYPE_UNCERTAIN" not in (e.flags or [])
            ):
                reviews.append(ReviewFlag(
                    type="R2", element_id=eid,
                    message=(
                        f"시각자료 세분류 신뢰도 미달 "
                        f"({e.subtype_confidence:.2f} < {R2_SUBTYPE_CONFIDENCE_THRESHOLD})"
                    ),
                ))

        # ── 페이지 단위 ───────────────────────────────────────────────────
        # ⚠ 미해결 구멍(2026-08-10 실측): **추출이 빈약한 쪽**에 아무 플래그도 없다. MinerU가
        # 한 쪽에서 6요소만 내면(EBS-E26-004 p0198 — 정답 1,484셀 중 8%만 덮음) 아래 C1에도
        # 안 걸려 플래그 0개 COMPLETED로 나간다(839쪽 중 3쪽이 'COMPLETED인데 gold 커버리지<0.7').
        # 여기서 못 고친 이유: "적다"를 판정하려면 **쪽 규모 기준**(원본 PDF 쪽·이미지)이
        # 있어야 하는데 check()는 그걸 안 받는다. 요소 수·글자 수만으로 임계를 잡으면 정상적으로
        # 짧은 쪽과 구별되지 않는다(단위 테스트 12건이 그 자리에서 깨졌다). pipeline.py 배선 사안.
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

        if n_fallback:
            reviews.append(ReviewFlag(
                type="R1", element_id="page",
                message=(f"MinerU 추출 실패로 텍스트레이어 폴백 — 표·그림 구조가 소실된 채 "
                         f"본문만 살렸습니다({n_fallback}요소). 원본과 대조가 필요합니다."),
            ))

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
        # R13은 **결함 탐지가 아니라 등급**이다 — 본문의 26%에 붙으므로 status에 넣으면
        # 거의 모든 쪽이 NEEDS_REVIEW가 된다(실측 839쪽: COMPLETED 255→9). 쪽 판정이
        # 무정보해지면 지금 그나마 있는 신호(status가 CER을 가르는 AUC 0.651)까지 잃는다.
        # 요소 화면에는 그대로 뜨고, 쪽 판정만 종전과 동일하게 둔다.
        if criticals or any(r.type != "R13" for r in reviews):
            return "NEEDS_REVIEW"
        return "COMPLETED"
