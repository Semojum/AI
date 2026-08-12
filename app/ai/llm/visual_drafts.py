"""시각자료 대체텍스트 6안 생성 (이미지·만화·차트·도표 공통).

점역사가 고를 6가지 대체텍스트. 각 안은 그 자체로 완결된 대체텍스트다:
  0) 생략     : 점자 규정(§6.3.4(2)②)에 맞춘 생략 표기 — 결정적, LLM 미사용.
  1) 짧은 제목: 인쇄 캡션이 있으면 그대로, 없으면 LLM이 짧은 제목 생성.
  2) 개조식   : 위계 있는 개조식 + 짧은 설명 — 구조가 있으면 rule-based 전사, 없으면 LLM.
  3) 줄글     : 자세한 줄글 설명 — 구조가 있으면 rule-based, 없으면 LLM.
  4) 유형만   : `,'그림,'` — 설명 없이 유형만. 무-LLM.
  5) 별책 참조: `,'그림 20-4 참조,'` — 시각 자료를 별책으로 뺐을 때. 무-LLM.

4·5안은 2026-08-10에 붙였다(원장 C-28). 정답 실측에서 이 두 형식이 23%였고, 어느 형식을
쓸지는 그림이 아니라 **책·권 단위 편집 방침**이라 우리가 못 고른다 — 안으로 내주고 고르게 한다.

성능·안정성: 0·1·4·5안은 무-LLM(또는 캡션 전사)이라 **항상** 나온다. 2·3안 중 LLM이 필요한
부분만 **1회 호출**로 함께 생성한다(방식별 N회 호출 → 1회로 축소, 페이지 타임아웃 완화).
LLM 파싱이 실패해도 캡션 폴백으로 6안이 보장된다(구 3안 포맷 미준수 문제 해소).

기본 선택(selected_idx): 장식용이면 0(생략), 그 외엔 2(개조식)를 기본 초안으로 둔다.
"""

from __future__ import annotations

import os
import re
import time

from app.ai.llm.base_opt import decide_tier_timeout, generate_with_retry
from app.ai.braille import tn_notices as _TN_NOTICES
from app.core.config import config
from app.schemas.content import Draft
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 시각자료 감싸기 스타일 A/B (2026-07-13 설계 재검토용 스위치, 기본=현행):
#   tn  = 점역자주 ⠠⠄ 감싸기(현행 설계, 지침 §6.3.4(1))
#   box = 글상자 테두리 ⠿⠛…/⠿⠶… 감싸기(실험용).
# ⚠ box 근거였던 "정답 BRL ⠿ 95%"는 오독 — 정답의 ⠿(17,981회)는 전부 한글 약자 '옹'(동·통·종 등)이고
#   테두리형 줄(⠿+단일 채움 반복)은 정답 1131p 전체에서 0줄. A/B에서도 box는 악화(cell_ns 0.709→0.682).
#   → 기본 tn 유지. 스위치는 후속 실험 대비용으로만 남김.
_WRAP_STYLE = os.environ.get("VISUAL_WRAP_STYLE", "tn")

# 6안 라벨(FE 피커 표시) — 순서 = option 1..6
#
# ★ 4→6 (2026-08-10, 원장 C-28). 정답 도서 2,917쪽의 점역자주 1,297건을 세니 시각 자료
#   처리가 다섯 갈래였다: 설명 45.1% · 유형만 13.6% · 생략 고지 11.5% · 별책 참조 9.3% ·
#   점자 그래픽. 그런데 이건 **그림의 성질이 아니라 책·권 단위 편집 방침**이다
#   (009 본책 별책참조 100% / 004 본책 생략고지 74% / 001 본책 설명 82%).
#   그림만 보고는 못 고르니 우리가 정하지 않는다 — 안으로 내주고 점역사가 고른다.
#   기존 0~3의 순번은 그대로 둔다(BE·FE 계약 유지). 새 안은 뒤에 붙인다.
LABELS = ("생략", "짧은 제목", "개조식 설명", "줄글 설명", "유형만", "별책 참조")
OMIT_IDX, TITLE_IDX, OUTLINE_IDX, PROSE_IDX, TYPEONLY_IDX, VOLREF_IDX = 0, 1, 2, 3, 4, 5

# 개조식 들여쓰기(칸): 제목 5칸(§6.3.3(1)), 유형/설명 점역자주 0칸, 전사 항목 level0=3칸(+2/단계).
# ⚠ 원장 C-15 — 정답 도서에는 3칸 줄이 **0.0%**다(dev+val 2027 각 200쪽 줄머리 실측:
#   0칸 66.4% · 2칸 32.0% · 4칸 1.3% · 3칸 0.0%). 규정(§6.3.4(2)①·§6.6.1(3))은 3칸·5칸을
#   말한다 — 규정 우선 원칙으로 3을 유지하되 점역사 자문 대상이다.
# ★ 2026-08-10 정정 — 5는 **칸 번호**였다. 이 값은 `" " * indent`로 쓰이니 **앞 빈칸 수**다.
#   §6.3.3(1) "제목 5칸에서 시작" = 앞 빈칸 4. 같은 조항을 쓰는 `diagram_opt._TITLE_INDENT`는
#   이미 4인데 여기만 5로 남아 축끼리 어긋나 있었다(도표는 4칸, 시각 3안은 5칸으로 나갔다).
#   정답 258건 첫 줄 앞 빈칸 분포: 4가 68건 · 5는 4건(17배 차).
_TITLE_INDENT = 4
_OUTLINE_BASE = 3
_OUTLINE_STEP = 2
_NOTE_INDENT = 2          # 형식 안내 점역자 주 3칸 (정본 예6-19·6-22·6-23·6-24)

# 최적화 프롬프트 — GPT-4o가 만든 캡션(묘사)을 HCXT가 점자 초안용으로 '다듬는다'(재생성 금지).
# 짧은 제목은 캡션 첫 문장(rule-based)이라 LLM은 개조식·줄글 두 형식만 담당 → 토큰↓·속도↑.
_PROMPT = """당신은 시각장애 학생용 점자 교과서 점역 전문가입니다.
아래 '설명'은 한 시각자료({label})에 대한 묘사입니다. 이 설명을 점자 초안용으로 **다듬어**
두 형식으로만 출력하세요. 설명에 없는 정보·수치·추측을 새로 만들지 말고, 주어진 내용만 간결히
재구성합니다. "그림은/이미지는"으로 시작하지 마세요. 아래 태그를 각각 한 번씩만 출력합니다.

[개조식] 핵심을 위계 있는 개조식으로. 큰 항목은 줄 맨 앞, 하위 항목은 앞에 "- ". 3~5줄.
[줄글] 1~3문장으로 간결히.

점자 독자를 위한 규칙 — 어기면 그만큼 점역사가 지웁니다.
1. **결론을 맨 앞에** 한 문장으로 쓰세요. 점자는 훑어보기가 어려워 되돌아가지 못합니다.
2. **같은 내용을 두 번 쓰지 마세요.** 좌우·A/B가 같은 구조면 "같은 장치 둘"처럼 한 번만 쓰고
   다른 점만 적습니다. 끝에 '공통 구성'을 또 붙이지 마세요.
3. **색·음영·장식은 쓰지 마세요.** 진한 음영/중간 음영, 별표·아이콘·버튼(최소화·닫기),
   테두리 모양은 문제 풀이에 안 쓰입니다. 그 자체가 정보일 때만 예외입니다.
4. **그림에 없는 설명을 덧붙이지 마세요.** 기관의 기능, 배경 지식, 일반론은 본문 몫입니다.
5. **한 면이 32칸 25줄입니다.** 설명이 길수록 학생이 읽을 본문이 줄어듭니다. 짧게 쓰세요.

설명: {caption}"""

_PREFILL = "[개조식]\n"

_SECTION_RE = re.compile(r"\[(제목|개조식|줄글)\]\s*(.*)")


_TYPE_DUP_RE = None  # 지연 컴파일


# 캡션이 자기 유형을 이미 말하는 경우 그 말을 라벨로 쓴다.
# 분류기가 chart_graph로 넘기면 라벨이 무조건 "그래프"가 되는데(chart_graph_opt._label),
# 실제로는 모식도·구조도가 많다. 판정 실측(2026-08-07 Opus 판정 8건): **유형라벨 2.0/5**로
# 최약축이었고 "모식도인데 그래프라 부르고 자기모순"이라는 지적이 반복됐다.
_TYPE_WORDS = ("모식도", "구조도", "개념도", "흐름도", "계통도", "분포도", "지도",
               "도식", "삽화", "사진", "그래프", "그림")
_TYPE_HEAD_RE = re.compile(r"^\s*(" + "|".join(_TYPE_WORDS) + r")\s*[:：,]?\s*")


def resolve_label(label: str, *texts: str) -> str:
    """캡션·제목이 유형을 말하면 그 말을 쓴다. 없으면 넘어온 라벨 그대로."""
    for t in texts:
        m = _TYPE_HEAD_RE.match(t or "")
        if m:
            return m.group(1)
    return label


def _strip_dup_type(text: str, label: str) -> str:
    """캡션이 이미 유형 제시어로 시작하면 떼서 라벨 이중화를 막는다.

    captioner._ensure_type_word(§6.3.4 rule-based)가 붙인 '그래프: …'에 여기서 또
    라벨을 붙이면 '그래프: 그래프: …'가 된다(2026-07-17 dev 캡셔닝 첫 실행 실측).
    """
    t = (text or "").strip()
    t = re.sub(rf"^{re.escape(label)}\s*[:：]\s*", "", t)
    # 라벨과 **다른** 유형어가 앞에 남아 있으면 그것도 뗀다("그래프: 모식도, …" 꼴).
    return _TYPE_HEAD_RE.sub("", t, count=1) if _TYPE_HEAD_RE.match(t) else t


def _oneline(text: str) -> str:
    """점역자주 한 덩이는 **논리 줄 하나**다 — 줄바꿈·빈 줄을 공백으로 접는다.

    QA 2026-08-07 14번("캡셔닝 안에 불필요한 빈 줄"). 근거 두 겹:
      · BBPG 제3장 9)(1)② — 만화의 컷과 컷 사이에는 빈 줄을 두지 않는다.
      · 「제작 지침」 §6.3.4(1) — 시각 자료 설명은 점역자 주표 **안**에 넣는 한 덩이다.
    실측(대표님 QA 실행분): 캡션 34건 중 **27건(79%)** 이 캡션 안에 빈 줄을 갖고 있었고,
    그게 그대로 점역자주 안으로 들어가 조판까지 흘렀다.
    그리고 구조적 버그가 하나 더 붙어 있었다 — `_outline_text_indents`는 head를 `lines` 한
    항목으로 세어 `indents`를 만드는데 head 안에 줄바꿈이 있으면 실제 줄 수가 늘어나
    **line_indents가 본문과 어긋난다**(job_260807160446 p2: 줄 17개 vs 들여쓰기 5개).
    여기서 접으면 둘 다 한 번에 사라진다.
    """
    return " ".join((text or "").split())


def _tn(text: str) -> str:
    """시각자료 감싸기 — tn(현행): 점역자주 / box(A/B): 글상자 테두리."""
    text = _oneline(text)
    if _WRAP_STYLE == "box":
        return (f"<!상자><!/상자>\n{text}\n<!상자끝><!/상자끝>")
    return f"<!주>{text}<!/주>"


def _shorten(text: str, limit: int = 45) -> str:
    """긴 캡션(MinerU 캡셔너의 장문 설명)을 '짧은 제목'용으로 줄인다.

    짧은 인쇄 캡션은 그대로(요건 "캡션 있으면 그대로"), 장문 AI 설명만 첫 문장/limit자로 축약.

    ★ 줄바꿈이 첫 번째 경계다(2026-08-09). 캡셔너 프롬프트는 "전체 윤곽을 한 줄로 먼저,
      그 다음 부분을 나누어"(지침 §6.1.4(4))라고 지시하므로 **첫 줄이 곧 제목**이다.
      그런데 종전 `" ".join(text.split())`이 줄 구조를 먼저 뭉개고 45자에서 잘라,
      제목이 둘째 줄 데이터 한가운데서 끊겼다 — val 실측 50건 중 **29건(58%)**이
      '…연령별 비율(%) 전체: 7.6% 1~2세: 6.8%…' 꼴이었다. 첫 줄을 먼저 취한다.
    """
    head = (text or "").split("\n", 1)[0]
    t = " ".join(head.split()) or " ".join((text or "").split())
    if len(t) <= limit:
        return t
    m = re.search(r"[.。!?]\s|[.。!?]$", t)          # 첫 문장 경계
    if m and m.start() + 1 <= int(limit * 1.6):
        return t[: m.start() + 1]
    return t[:limit].rsplit(" ", 1)[0] + "…"


def _outline_text_indents(
    label: str, title: str, desc: str, items: list[tuple[int, str]], kind: str = ""
) -> tuple[str, list[int]]:
    """개조식 → (텍스트, 줄별 들여쓰기). §6.3 규정 배치:
      제목(5칸, 점역자주 밖·§6.3.3(1)) → 유형+짧은 설명(점역자주·§6.3.4(1)) → 전사 항목(위계 들여).
    """
    lines: list[str] = []
    indents: list[int] = []
    title = (title or "").strip()
    desc = (desc or "").strip()
    desc = _strip_dup_type(desc, label)
    head = f"{label}: {desc}" if (desc and desc != title) else label
    if _WRAP_STYLE == "box":
        # box(A/B): 블록 전체를 글상자로 — 제목은 위 테두리 안(BBPG-1.2.5), 유형/설명은 첫 줄.
        lines.append(f"<!상자>{title}<!/상자>"); indents.append(0)
        lines.append(head); indents.append(0)
    else:
        if title:
            lines.append(title); indents.append(_TITLE_INDENT)      # §6.3.3(1) 제목 5칸(plain)
        lines.append(_tn(head)); indents.append(0)                   # §6.3.4(1) 유형/설명 점역자주
    # ★ 2026-08-12 — 항목에 **위계가 있으면** 들여쓰기 칸 수를 독자에게 밝힌다.
    #   점자에는 선·상자·글머리 기호가 없어 위계가 들여쓰기로만 남는다. 몇 칸이 한
    #   단계인지 말해 주지 않으면 독자는 빈칸을 세도 단계를 못 센다.
    #   정본 자료지침 예6-22가 조직도에서 같은 말을 쓴다("하위에 속한 기구를 2칸씩
    #   들여 쓰기함"). 위계가 없는 평평한 나열에는 붙이지 않는다 — 없는 구조를
    #   있다고 알리는 꼴이 되고, 32칸 지면만 먹는다.
    # ⚠ 만화는 제외한다. 만화의 장면(5칸)·대사(3칸) 들여쓰기는 **§5.3.3(1)(2)가 정한
    #   규정 형식**이지 우리가 임의로 고른 것이 아니다. 거기에 "임의로 정했다"는 뜻의
    #   고지를 붙이면 규정 형식을 우리 재량인 것처럼 알리는 꼴이 된다.
    #   정본 만화 예5-4·5-5에도 그런 고지가 없다(2026-08-12 실측 — 이 가드가 없어
    #   테스트_이미지 p2·p5 만화에 잘못 붙었다).
    if kind != "만화" and any(lv > 0 for lv, tx in items if (tx or "").strip()):
        lines.append(_tn(_TN_NOTICES.indent_hierarchy(_OUTLINE_STEP)))
        indents.append(_NOTE_INDENT)
    for level, text in items:
        text = (text or "").strip()
        if not text:
            continue
        lines.append(text); indents.append(_OUTLINE_BASE + _OUTLINE_STEP * max(0, level))  # 전사 §6.3.4(2)①
    if _WRAP_STYLE == "box":
        lines.append("<!상자끝><!/상자끝>"); indents.append(0)
    return "\n".join(lines), indents


def omission_draft(label: str) -> Draft:
    """0안: 생략 표기(§6.3.4(2)②). 장식용·중요도 낮은 자료용.

    ★ 이 주석은 **점수를 내주고 사는 것**이다 — 빼지 마라(2026-08-09 대표 결정).
      정답 도서는 그림을 대체로 **말없이** 뺀다(gold 400개 표본에서 '생략' 표기 3.5%).
      우리는 그림마다 이 16셀을 달아서, 캡션이 없는 조건에서는 이게 시각자료 축 과잉의
      거의 전부다(val 담당 gold 847셀에 우리 1,652셀 → 축 −95.0%).

      그래도 유지한다. 주석을 빼면 **점역사도 학생도 거기 그림이 있었다는 사실 자체를
      모른다.** 같은 이유로 Step0에서 빈 캡션 가드를 넣었다(요소를 통째로 버리지 않게).
      점수는 대리지표이고 최종 KPI는 점역사 수정 시간이다 — 없는 걸 알아채는 비용이
      16셀을 지우는 비용보다 크다.

      ⚠ 시각자료 축이 음수인 것을 보고 "과잉이니 빼자"로 되돌리지 말 것. 이건 결함이 아니라
        선택이다. 바꾸려면 점역사 자문을 먼저 받아라.

      ★ 2026-08-10 정정(원장 C-27 철회 · C-28 신설) — 위 "말없이 뺀다"는 **측정이 틀렸다.**
        정답 BRF는 BRF-ASCII라 점역자주표가 `,'`인데 유니코드 `⠠⠄`로 세서 0이 나왔다.
        바르게 세면 정답도 점역자주를 단다(10쪽에서 gold 29건 : 우리 시각요소 26개).

        진짜 사정은 **책·권마다 처리 방식이 다르다**는 것이다(gold 2,917쪽·1,297건 실측):
        설명 45.1% / 유형만 13.6% / 생략 고지 11.5% / 별책 참조 9.3%, 그리고 점자 그래픽.
        009 body는 별책참조 100%, 004 body는 생략고지 74%, 001 body는 설명 82%다.
        개별 그림의 성질이 아니라 **편집 방침**이다 — 그래서 그림만 보고는 못 고른다.

        위 "유지한다" 결정은 그대로 유효하다(없는 걸 알아채는 비용 > 16셀 지우는 비용).
    """
    return Draft(option=1, text=_tn(f"{label} 생략"), render_mode="narrative", label=LABELS[OMIT_IDX])


def title_draft(label: str, title: str) -> Draft:
    """1안: 짧은 제목(캡션 그대로 또는 생성).

    ★ 재료가 없을 때 `f"{label} 생략"`으로 떨어뜨리지 않는다(2026-08-12 대표 지시).
      '생략'은 **0안의 몫**이다. 여기서 같은 문구를 내면 점역사 피커에 같은 선택지가
      두 번 뜨고, 6안을 둔 목적(설명 방식을 **고르게** 한다)이 무너진다.
      실측: 캡션이 없는 조건의 코퍼스 job에서 2안의 41.3%가 "…생략"이었고,
      4안 중 서로 다른 것이 4개인 요소는 10%뿐이었다.
      재료가 없으면 유형만 남긴다 — 그리고 그렇게 겹친 안은 `_dedupe`가 접는다.
    """
    title = _strip_dup_type(title, label)      # "그래프: 그래프: …" 중복 방지
    body = f"{label}: {title}".strip().rstrip(":") if title else label
    return Draft(option=2, text=_tn(body), render_mode="narrative", label=LABELS[TITLE_IDX])


def outline_draft(
    label: str, title: str, desc: str, items: list[tuple[int, str]], kind: str = ""
) -> tuple[Draft, list[int]]:
    """2안: 위계 개조식(제목 5칸 + 유형/설명 점역자주 + 전사 항목). 반환 (Draft, line_indents)."""
    text, indents = _outline_text_indents(label, title, desc, items, kind)
    return Draft(option=3, text=text, render_mode="narrative", label=LABELS[OUTLINE_IDX]), indents


def prose_draft(label: str, prose: str) -> Draft:
    """3안: 줄글 자세한 설명. 재료 없으면 유형만(‘생략’은 0안 몫 — `title_draft` 주석)."""
    body = (prose or "").strip()
    body = _strip_dup_type(body, label)
    return Draft(option=4, text=_tn(f"{label}: {body}" if body else label),
                 render_mode="narrative", label=LABELS[PROSE_IDX])


def typeonly_draft(label: str) -> Draft:
    """4안: 유형만(`,'그림,'`) — 설명 없이 거기 무엇이 있었는지만 알린다.

    「점자 도서 제작 지침」 [예 3-30] '내용을 설명하기 어려운 시각 자료'가 이 형식이다.
    정답 실측 176건(13.6%)이고 014·015 본책은 이게 최빈(51~54%)이다.
    """
    return Draft(option=5, text=_tn(label), render_mode="narrative",
                 label=LABELS[TYPEONLY_IDX], type_label=label)


def _dedupe(drafts: list[Draft], selected_idx: int) -> tuple[list[Draft], int]:
    """문구가 똑같아진 안을 접는다. 반환 (남은 안, 옮겨진 selected_idx).

    재료가 **조금** 있을 때도 형식끼리 같아질 수 있다. 캡션이 한 문장이면 짧은 제목(첫
    문장)과 줄글(전문)이 같은 글이고, 개조식도 항목이 없으면 같은 한 줄이다 — 세 칸에
    똑같은 줄이 선다. 점역사는 셋 다 읽어 보고서야 같은 것임을 안다.

    ⚠ `selected_idx`는 리스트 인덱스다. 접힌 만큼 다시 매기지 않으면 상위
      `drafts[selected_idx]`가 엉뚱한 안을 가리킨다.
    """
    seen: dict[str, int] = {}
    kept: list[Draft] = []
    new_idx = 0
    for i, d in enumerate(drafts):
        key = " ".join((d.text or "").split())
        if key in seen:
            if i == selected_idx:
                new_idx = seen[key]
            continue
        seen[key] = len(kept)
        if i == selected_idx:
            new_idx = len(kept)
        kept.append(d)
    return kept, new_idx


def _no_material(*parts: str) -> bool:
    """캡셔닝이 실패했거나 인쇄 캡션이 없다 — 설명을 지어낼 재료가 하나도 없는 자리."""
    return not any((p or "").strip() for p in parts)


def extra_drafts(label: str, ref: str = "") -> list[Draft]:
    """4·5안(유형만·별책 참조). 공통 빌더와 도표 골격 경로가 같이 쓴다."""
    return [typeonly_draft(label), volume_ref_draft(label, ref)]


def volume_ref_draft(label: str, ref: str = "") -> Draft:
    """5안: 별책 참조(`,'그림 20-4 참조,'`) — 시각 자료를 별책으로 분권했을 때.

    「점자 자료 제작 지침」 (3)(3): 시각 자료만 별책으로 분권하면 본문의 해당 위치마다
    별책 위치를 점역자 주로 알려 참조하게 한다. 정답 실측 120건(9.3%)이고
    009 본책은 **85건 전부**가 이 형식이다(`그림 4-1 참조`·`그림 20-4 참조`).

    ref는 '묵자쪽-그 쪽에서의 순번'이라 요소 하나만 봐서는 못 만든다. 여기서는 빈 채로
    두고 `pipeline._number_volume_refs`가 페이지 단위로 채운다.
    """
    body = f"{label} {ref} 참조" if ref else f"{label} 참조"
    return Draft(option=6, text=_tn(body), render_mode="narrative",
                 label=LABELS[VOLREF_IDX], type_label=label)


def _parse_sections(response: str) -> dict[str, object]:
    """LLM 응답 → {제목:str, 개조식:list[(level,text)], 줄글:str}."""
    title = ""
    outline: list[tuple[int, str]] = []
    prose_lines: list[str] = []
    cur = None
    for raw in (response or "").splitlines():
        line = raw.rstrip()
        m = _SECTION_RE.match(line.strip())
        if m:
            cur = m.group(1)
            rest = m.group(2).strip()
            if cur == "제목" and rest:
                title = rest
            elif cur == "개조식" and rest:
                outline.append(_outline_item(rest))
            elif cur == "줄글" and rest:
                prose_lines.append(rest)
            continue
        if not line.strip():
            continue
        if cur == "개조식":
            outline.append(_outline_item(line))
        elif cur == "줄글":
            prose_lines.append(line.strip())
        elif cur == "제목" and not title:
            title = line.strip()
    return {"제목": title, "개조식": outline, "줄글": " ".join(prose_lines).strip()}


def _outline_item(line: str) -> tuple[int, str]:
    """개조식 한 줄 → (level, text). 선행 공백/'- '로 위계 판정."""
    indent = len(line) - len(line.lstrip(" \t"))
    body = line.strip()
    level = 0
    if body.startswith(("- ", "* ", "· ")):
        body = body[2:].strip()
        level = 1
    elif indent >= 2:
        level = 1
    return level, body


async def build_visual_drafts(
    ext,
    routing_tier: str,
    *,
    label: str,
    caption: str,
    title: str = "",
    kind: str,
    struct_outline: list[tuple[int, str]] | None = None,
    struct_prose: str | None = None,
    decorative: bool = False,
) -> tuple[list[Draft], int, list[int] | None, str]:
    """4안(생략·제목·개조식·줄글) 생성. 반환 (drafts, selected_idx, line_indents, tier).

    title = 자료 제목(짧은 제목 초안·개조식 머리줄). caption = 인쇄 캡션/설명(개조식 항목·줄글).
    struct_outline/struct_prose가 오면 그 파트는 rule-based 전사(LLM 미사용). 나머지(제목·개조식·
    줄글 중 빠진 것)만 비ZERO에서 LLM 1회로 채운다.
    """
    caption = (caption or "").strip()
    title = (title or "").strip()
    tier = routing_tier
    _t0 = time.monotonic()   # 시각요소별 4안 생성 소요시간(줄글 LLM 포함) 로깅용

    # LLM이 채워야 할 파트: 제목·캡션 다 없으면 제목, 구조 없으면 개조식/줄글.
    need_title = not (title or caption)
    need_outline = struct_outline is None
    need_prose = struct_prose is None
    has_seed = bool(title or caption)
    use_llm = (routing_tier != "ZERO") and has_seed and (need_title or need_outline or need_prose)

    llm_title, llm_outline, llm_prose = "", [], ""
    if use_llm:
        # 시각 최적화는 캡션 재구성(무거운 생성) → QUALITY 상한을 쓴다(요소당 상한이지만 페이지
        # 누적 예산이 총량을 막으므로 안전). 티어 라벨은 신뢰도 기준(decide_tier_timeout).
        t2, _ = decide_tier_timeout(ext.ocr_confidence)
        timeout = config.hcxt_quality_timeout_seconds
        # 출력은 [개조식]+[줄글] 두 섹션을 한 번에 담는다 → 캡션의 0.9배(구 180 상한)로는
        # 위계 개조식이 예산을 먹고 줄글이 문장 중간에 잘렸다(A/B에서 확인). 두 섹션 합계를
        # 고려해 캡션의 ~1.6배로 잡고 상한을 320으로 올린다(vLLM 46tok/s면 ~7s, QUALITY 상한 내).
        src = caption or title
        mnt = min(320, max(140, int(len(src) * 1.6)))
        # ★ 4안 보장(D-02)은 **예외까지** 막아야 한다. generate_with_retry는 자체 재시도·폴백을
        #   갖지만 그게 모두 실패하면 예외를 올린다. 종전에는 그 예외가 여기서 안 잡혀 위로
        #   전파됐고, isolation이 요소를 통째로 플레이스홀더로 만들어 **drafts가 0개**가 됐다
        #   (= BE에 "대체 텍스트 1개"로 보이는 실제 경로). 캡션 폴백은 "응답이 이상할 때"만
        #   막았지 "예외"는 못 막았다. 2026-07-28 회귀 테스트로 재현해 확인.
        #   여기서 삼키면 llm_* 가 빈 채로 남고 아래 캡션·구조 폴백이 4안을 채운다.
        try:
            response, used_fb = await generate_with_retry(
                _PROMPT.format(label=label, caption=src),
                timeout=timeout, element_id=ext.element_id, kind=kind,
                prefill=_PREFILL, max_new_tokens=mnt, fallback_max_tokens=mnt,
            )
            tier = "FALLBACK" if used_fb else t2
            sec = _parse_sections(response)
            llm_title, llm_outline, llm_prose = sec["제목"], sec["개조식"], sec["줄글"]
        except Exception as exc:  # noqa: BLE001 — 4안 보장이 개별 추론 실패보다 우선
            logger.warning("    4안 LLM 실패(폴백으로 계속) %s %s: %s: %s",
                           kind, str(ext.element_id)[:8], type(exc).__name__, exc)
            tier = "FALLBACK"

    # 그림 안에서 뽑아 낸 원본 글자(struct_outline). 종전에는 **개조식에만** 넘어가서,
    # 캡션이 없고 원본 글자만 있는 그림에서 개조식만 살고 짧은 제목·줄글은 빈손이 됐다
    # (실측 안별 붕괴율: 개조식 0.0% vs 짧은 제목·줄글 각 41.3%). 같은 재료를 셋이 나눠 쓴다.
    struct_text = " ".join(t for _lv, t in (struct_outline or []) if t).strip()

    # 짧은 제목: 인쇄 캡션 우선(요건 — "캡션 있으면 그대로"), 단 장문 AI 캡션은 짧게 축약. 없으면 제목/LLM.
    short_title = _shorten(caption) or title or llm_title or _shorten(struct_text) or ""
    # 개조식: 5칸 제목줄 = 구조적 표제(title), 점역자주 설명 = 캡션/생성 설명.
    outline_items = struct_outline if struct_outline is not None else llm_outline
    # ※ 항목이 비면 캡션 여러 줄이 `_tn()`의 `_oneline`에 접혀 한 줄 점역자주가 된다
    #   (실측 diagram 127건 중 109건). 캡션 줄을 그대로 개조식 항목으로 올리는 안(갈래 A)을
    #   2026-08-08 dev-2027 200쪽에서 재 봤으나 **CER·시각자료 축이 한 셀도 안 움직였고**
    #   들여쓰기 분포만 정답에서 멀어졌다(3칸 줄 0.0%→1.4%, 정답 3칸 0.0%). 그래서 안 넣는다.
    #   도표는 갈래 B(캡션→structure→§6.6 골격, `diagram_structure`)가 대신 처리한다.
    # ★ 머리줄은 §6.3.4(1) '유형 + **짧은** 설명'이다(이 함수 docstring도 그렇게 적혀 있었다).
    #   그런데 캡션 **전문**을 넣고 그 아래 같은 내용을 개조식으로 또 깔았다 → 대표님 QA 13번
    #   "그 이후에 그림을 전체적으로 또 설명하고 있어서 내용이 중복됨"의 실제 코드 위치다
    #   (실측 job_260807160446 p2: 점역자주 안 13줄 + 밖 4줄이 같은 내용).
    #   항목이 있으면 머리줄은 줄이고 세부는 항목이 진다. 항목이 없으면 머리줄이 유일한
    #   내용이므로 그대로 둔다(축약이 곧 정보 손실).
    outline_desc = caption or llm_title or ""
    if outline_items:
        outline_desc = _shorten(outline_desc)
    prose = (struct_prose if struct_prose is not None
             else (llm_prose or caption or title or struct_text))

    d_omit = omission_draft(label)
    d_title = title_draft(label, short_title)
    d_outline, indents = outline_draft(label, title, outline_desc, outline_items, kind)
    d_prose = prose_draft(label, prose)
    drafts = [d_omit, d_title, d_outline, d_prose, *extra_drafts(label)]

    selected_idx = OMIT_IDX if decorative else OUTLINE_IDX

    # ★ 재료가 하나도 없으면 **생략 한 안만** 낸다 (2026-08-12 대표 지시).
    #   캡션·제목·원본 글자가 다 없으면 짧은 제목·개조식·줄글은 낼 게 없어 전부
    #   '유형만'이나 '…생략'과 같은 문구가 된다 — 여섯 칸에 같은 줄을 세우면 점역사는
    #   여섯 개를 다 읽고서야 고를 게 없다는 걸 안다. 규정상 정답도 생략 표기다(§6.3.4(2)②).
    #   ⚠ 이 자리가 자주 나오면 그건 **캡셔닝이 실패하고 있다는 신호**지 초안 문제가 아니다.
    #     경계 파일의 CAPTION_FAILED와 품질검사 R11이 그 사실을 따로 알린다.
    if _no_material(caption, title, struct_text, struct_prose or "",
                    llm_title, llm_prose, " ".join(t for _l, t in (llm_outline or []))):
        return [d_omit], 0, None, tier, caption_source(
            OMIT_IDX, used_llm=False, has_print_caption=False, has_struct=False)

    # 재료가 조금이라도 있으면 6안을 내되, 문구가 똑같아진 안은 접는다.
    drafts, selected_idx = _dedupe(drafts, selected_idx)
    line_indents = indents if drafts[selected_idx] is d_outline else None
    logger.info("    4안 %s %s: %.1fs (tier=%s%s)", kind, str(ext.element_id)[:8],
                time.monotonic() - _t0, tier, ", LLM" if use_llm else "")
    return drafts, selected_idx, line_indents, tier, caption_source(
        selected_idx, used_llm=bool(llm_title or llm_outline or llm_prose),
        has_print_caption=bool(caption), has_struct=struct_outline is not None,
    )


def visual_trail(rule_id: str, drafts: list[Draft], selected_idx: int, source: str):
    """시각자료 근거 한 줄 — 규정 조항 + **어느 안을 왜 골랐는지**(Step17).

    대체텍스트는 100% 우리 재량이다(대표 지시 (A) 전형). 종전에는 조항 하나만 달려서
    점역사가 "이 문구가 어떻게 나온 건지" 알 방법이 rule_trail에 없었다.
    tag = "개조식 설명·AI 생성" 처럼 [선택된 안]·[출처]로 적는다.
    """
    from app.ai.braille.regulations import make_rule

    label = drafts[selected_idx].label if 0 <= selected_idx < len(drafts) else ""
    return [make_rule(rule_id, tag=f"{label}·{source}".strip("·"))]


def caption_source(
    selected_idx: int, *, used_llm: bool, has_print_caption: bool, has_struct: bool
) -> str:
    """선택된 대체텍스트가 **어디서 왔는지** 한 마디로 (Step17, 2026-08-08 대표 지시).

    점역사가 시각자료 초안을 볼 때 제일 먼저 판단해야 하는 것은 "이 문장을 믿어도 되는가"다.
    인쇄 캡션을 옮긴 것이면 원본 대조로 끝나지만, AI가 만든 문구면 그림과 하나하나 맞춰
    봐야 한다 — 확인 비용이 다르다. 지금까지 이 구분이 rule_trail 어디에도 없었다.
    """
    if selected_idx == OMIT_IDX:
        return "생략(장식용 판정)"
    if has_struct:
        return "구조 전사(무-LLM)"
    if used_llm:
        return "AI 생성"
    return "인쇄 캡션 전사" if has_print_caption else "제목 전사"
