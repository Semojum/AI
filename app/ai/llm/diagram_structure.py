"""캡션 텍스트 → 도표 세분류(visual_subtype) + §6.6 골격 입력(structure).

**세분류는 이제 분류 콜이 직접 준다**(2026-09-08, #784). `captioning/classifier` 가
`diagram` 일 때 §6.6 하위유형 낱말을 한 개 더 받아 `visual_subtype` 으로 싣는다.
아래 `subtype_from_caption` 은 그 값이 없을 때의 **폴백**이다.

**왜 폴백을 남기나.** 앞단이 세분류를 안 줄 때가 있다(옛 경계 파일·형식 이탈 응답·
`diagram` 이 아닌 라벨로 들어온 도표). 캡션 첫 줄이 유형어를 달고 오면 그걸로도 골격이
선다. 다만 **캡션 문안에 기대면 안 된다** — 문안을 고칠 때마다 조용히 끊긴다(#646·#734가
이틀 만에 끊었고 `visual_subtype` 이 20/20 빈칸이 됐다. 실측 `temp/label46/흔들림_0908.md`).

그런데 캡셔너의 `diagram` 프롬프트(`captioning/captioner._PROMPTS`)는 이미 두 가지를 시킨다:
  (a) 첫 줄에 유형어를 쓴다("…를 나타낸 흐름도"·"가계도(계통도)") — 실측 127건 중 110건
  (b) 구성 요소를 위계 있는 줄로 적는다("1세대 / - 1: … / - 2: …") — 실측 109건이 다줄
구조를 새로 만들 필요가 없다. 그 줄들을 읽으면 된다. 추가 API 호출 0, 결정적(rule-based).

한계(ponytail: 캡션 문장 파서다). 앞단(MinerU·VLM)이 진짜 구조를 내주면 그 값이 우선하고
이 모듈은 폴백으로 내려간다 — `diagram_opt`는 `ext.structure`가 있으면 여기를 안 부른다.
"""

from __future__ import annotations

import re

# ── §6.6 도표 하위유형 여덟 (정본 목록) ──────────────────────────────────────
# 「점자 자료 제작 지침」 §6.6 도표가 정한 여덟이고 그 밖에는 없다. 조문 원문(재추출
# `braille-source/text/점자 자료 제작 지침_재추출.txt`) —
#   L3524  "여기에서는 개념도, 흐름도, 양식, 가계도, 조직도, 연대표, 발표용 슬라이드 및
#           화면 이미지 등을 점역하는 데 필요한 지침을 제시한다."
#   L3526  §6.6.1 개념도  "중심 개념에서 하위 개념으로 가지가 뻗어나간 형식"
#   L3542  §6.6.2 흐름도  "통일된 기호와 도형을 사용하여 작업과 처리 순서를 표시"
#   L3640  §6.6.3 양식    "채워야 할 빈칸이나 선택 사항이 있는 양식"
#   L3668  §6.6.4 가계도  "선조와 후손 간의 연결 관계를 도식화"
#   L3722  §6.6.5 조직도  "조직의 구조나 인적 구성 … 계급 순위나 내부 관계"
#   L3781  §6.6.6 연대표  "사건을 시간 순서에 따라 적는다"
#   L3818  §6.6.7 화면 이미지  "웹페이지의 화면 이미지"
#   L3854  §6.6.8 발표용 슬라이드  "파워포인트나 키노트 등에서 작성된 것"
#
# ★ 이 여덟이 **분류 콜이 낼 수 있는 값의 전부**다(`captioning/classifier`). 조항을 못 대는
#   낱말은 넣지 않는다 — 넣으면 §6.6 밖 자료에 없는 골격을 억지로 씌운다.
# ★ `diagram_opt._ASSEMBLERS`·`_SUBTYPE_RULE`·`_TYPE_LABEL` 의 열쇠와 **같아야 한다**.
#   어긋나면 `test_diagram_subtype_wiring.py` 가 빨간불을 낸다.
SUBTYPES: tuple[str, ...] = (
    "concept_map",   # §6.6.1 개념도
    "flowchart",     # §6.6.2 흐름도
    "form",          # §6.6.3 양식
    "family_tree",   # §6.6.4 가계도
    "org_chart",     # §6.6.5 조직도
    "timeline",      # §6.6.6 연대표
    "screen_image",  # §6.6.7 화면 이미지
    "slide",         # §6.6.8 발표용 슬라이드
)

# 첫 줄 유형어 → §6.6 하위유형. 순서 = 판정 우선순위(구체적인 말 먼저).
# ⚠ **폴백 경로다**(2026-09-08, #784). 정본은 분류 콜이 직접 주는 `visual_subtype` 이고
#   (`captioning/classifier.classify_with_confidence`), 이 정규식은 그 값이 없을 때만 쓴다.
#   캡션 문안에 유형어가 없어도 골격이 서야 한다 — 문안을 고칠 때마다 조용히 끊기던
#   자리다(#646 이 "종류 이름을 쓰지 마세요" 를 넣고 #734 가 남은 낱말을 떼자 이틀 만에
#   세분류가 20/20 빈칸이 됐다).
# 'org_chart'가 먼저인 이유: "조직도(계통도)"처럼 두 말이 같이 나오면 더 좁은 쪽이 맞다.
# ※ '지도'·'분포도'는 §6.6에 골격이 없다 — 일부러 빼서 캡션 폴백으로 보낸다(추측 금지).
_SUBTYPE_WORDS: tuple[tuple[str, str], ...] = (
    ("조직도", "org_chart"),
    ("가계도", "family_tree"),
    ("계통도", "family_tree"),      # 생물 교과의 유전 계통도 = 가계도(§6.6.4)
    ("연대표", "timeline"),
    ("연표", "timeline"),
    ("흐름도", "flowchart"),
    ("순서도", "flowchart"),
    ("공정도", "flowchart"),
    ("화면 이미지", "screen_image"),
    ("화면이미지", "screen_image"),
    ("발표용 슬라이드", "slide"),
    ("슬라이드", "slide"),
    ("양식", "form"),
    ("개념도", "concept_map"),
    ("모식도", "concept_map"),
    ("구조도", "concept_map"),
    ("도식", "concept_map"),
)

# 줄머리 표지 — 마크다운 제목(#)·글머리표(-·*··). 캡셔너에게 마크다운을 쓰지 말라고
# 했지만 실제 캡션에는 남는다(실측 '## 구성'·'- 1: …'). 표지는 위계 판정에만 쓰고 뗀다.
_HEAD_RE = re.compile(r"^(#{1,6})\s+")
_BULLET_RE = re.compile(r"^([-*·•])\s+")
# 위계 번호 — 캡셔너 diagram 프롬프트가 시킨 세 단계("큰 항목 '1.', 그 아래 '1)', 그 아래 '①'").
# 실측(조직도 크롭 재캡션): 들여쓰기 없이 이 표지만으로 위계를 적어 온다. 표지를 못 읽으면
# 12줄이 전부 같은 층으로 눌린다.
#   ★ 뒤에 **빈칸을 요구**한다 — 가계도 캡션의 '1: 정상 남자'(개체 번호)를 표지로 오인하면
#     사람 번호가 사라진다. 쌍점은 표지가 아니다.
#   ★ 2026-09-07 — 원문자 한글 `㉠~㉺`(㉠㉡㉢…)를 표지 목록에서 뺐다. 한국 교과서에서
#     이 글자는 위계 표지가 아니라 **개체 이름표**다. 문항이 `㉠이 무엇인가`를 묻는다.
#     실측 근거 셋:
#       · 캡셔너 diagram 프롬프트가 시키는 위계 표지는 `1.` `1)` `①` 셋뿐이다. `㉠`은 없다 —
#         캡션에 나온 `㉠`은 모델이 매긴 번호가 아니라 **그림 안에 적혀 있던 글자**다.
#       · 캡션 캐시 1,814건에서 줄머리 `㉠`은 25줄인데 그 아래 층이 달린 것이 **0건**이다
#         (전부 잎). 위계 부모로 쓰인 적이 없다.
#       · gold 시각자료 991건 중 115건이 `㉠~㉺`를 담고 있고 55건은 줄머리다. 정답은 지운 적이 없다.
#     떼면 `㉠ 근수축` 이 `근수축` 이 돼 문항이 가리키는 이름표가 사라졌다
#     (도표·지도 캡션 19건). `①`은 프롬프트가 3층 표지로 지정한 글자라 그대로 둔다.
_NUM_RE = re.compile(r"^(?:(\d{1,2})([.)])|([①-⑳]))\s+")
_NUM_LEVEL = {".": 0, ")": 1}
# 유형 제시어("도표: ", "그림: ") — captioner._ensure_type_word가 붙인 것.
# ★ F18(대표 지적) — 캡션 첫 줄의 **종류어**를 안 떼면 점역자 주의 유형과 두 번 나간다.
#   실물: '모식도\n개념도:\n삼각형 ABC:\n…' — 캡셔너가 첫 줄에 종류를 쓰라는 지시를 받고
#   '모식도'를 썼는데(captioner._PROMPTS["diagram"]), 종전 정규식이 콜론 붙은 여덟 낱말만
#   떼어 그 줄이 골격 **제목**으로 남았다. 유형은 §6.3.4(1)이 점역자 주로 내는 몫이므로
#   첫 줄의 종류어는 여기서 걷어낸다. 콜론이 없어도(줄 전체가 종류어여도) 뗀다.
# ★ 2026-09-07 — 그래프 세분 이름과 두 겹 제시어를 함께 잡는다.
#   실측(캡션 캐시 1,814건): 첫 줄이 `그래프: 꺾은선그래프: …`·`도표: 구조도, …` 처럼
#   제시어를 **두 겹** 붙여 오는 것이 651건(35.9%)이다. `_ensure_type_word` 가 붙인
#   제시어 위에 모델이 자기 종류어를 또 쓰기 때문이다. 한 겹만 떼면 점역자 주 머리줄이
#   `그래프: 꺾은선그래프: …` 로 나가 §6.3.4(1) 유형 표기가 두 번 찍힌다.
#   실측 둘째 낱말: 구조도 125·꺾은선그래프 111·흐름도 98·모식도 92·막대그래프 69·
#   가계도 35·지도 31·개념도 21·그래프 19·조직도 11·원그래프 8·선그래프 8·계통도 6.
#   `[가-힣]{0,4}그래프` 로 막대·꺾은선·원·선·그림·띠·혼합을 한 줄에 담는다.
#   ⚠ 뒤에 **쌍점이나 줄 끝**을 요구하는 것이 이 정규식의 안전장치다 — 그것이 없으면
#     `그림: 지도 위에 표시된 경로` 의 '지도'까지 떼어 내용이 사라진다.
_LEAD_TYPE_WORDS = (
    "도표|그림|사진|[가-힣]{0,4}그래프|삽화|만화|지도|표|산점도|분포도|수직선|기후도"
    "|모식도|구조도|개념도|흐름도|순서도|공정도|조직도|계통도|가계도"
    "|연대표|연표|양식|화면\\s*이미지|발표용\\s*슬라이드|슬라이드"
)
# ★ 쉼표도 구분자로 본다(2026-09-07). 캡셔너가 `그래프: 꺾은선그래프, 생존 곡선` 처럼
#   쌍점 대신 쉼표로 잇는 것이 실측 1,814건 중 139건이다(꺾은선 82·막대 44·원 6·선 5).
#   두 겹까지만 떼므로 `그림: 그래프, 표, 사진이 실린 지면` 같은 나열형 제목이 와도
#   피해가 두 낱말로 막힌다(실측 1,814건에 그런 머리줄 0건).
_LEAD_TYPE_RE = re.compile(rf"^\s*(?:{_LEAD_TYPE_WORDS})\s*(?:[:：,]\s*|$)")
# 연대표 날짜 — 연도(1948·기원전 57)나 '3월 1일'로 시작하고 한 칸 뒤 사건.
_DATE_RE = re.compile(r"^((?:기원전\s*)?\d{1,4}\s*(?:년|년대|세기)?(?:\s*\d{1,2}\s*월)?"
                      r"(?:\s*\d{1,2}\s*일)?)\s*[:：]?\s+(.+)$")

# 한 줄에 쉼표로 몰아 적은 연표("1911 신해혁명, 1919 5·4운동") — 날짜+빈칸+사건.
_INLINE_TL = re.compile(r"(?:^|[,;.]\s*)((?:기원전\s*)?\d{3,4}\s*년?)\s+([^,;\n]{2,40})")

_MAX_LINES = 40   # 폭주 방어 — 캡션이 이보다 길면 골격이 아니라 줄글이다


def _event(text: str) -> dict:
    """'1919년 3·1 운동' → {date, text}. 날짜 꼴이 아니면 date=""(사건만)."""
    m = _DATE_RE.match(text)
    return ({"date": m.group(1).strip(), "text": m.group(2).strip()} if m
            else {"date": "", "text": text})


def _strip_lead_type(text: str) -> str:
    """첫 줄의 유형 제시어·마크다운 표지를 뗀다. 제시어는 **두 겹까지** 뗀다(위 주석)."""
    t = (text or "").strip()
    for _ in range(2):
        t2 = _LEAD_TYPE_RE.sub("", t)
        if t2 == t:
            break
        t = t2
    return _HEAD_RE.sub("", t).strip()


def subtype_from_caption(caption: str) -> str:
    """캡션 첫 줄의 유형어 → §6.6 하위유형. 못 찾으면 "" (골격 미적용 = 캡션 폴백)."""
    head = ""
    for ln in (caption or "").split("\n"):
        if ln.strip():
            head = ln
            break
    for word, sub in _SUBTYPE_WORDS:
        if word in head:
            return sub
    return ""


def type_word_from_caption(caption: str) -> str:
    """캡션 첫 줄이 **말한 유형어 그대로**. 못 찾으면 "".

    ★ 왜 필요한가(2026-08-26, F16) — `_SUBTYPE_WORDS`는 모식도·구조도·도식을 전부
      `concept_map`으로 접는다. 골격은 §6.6.1을 같이 쓰니 그 접기가 맞다. 그런데 표시
      이름까지 `_TYPE_LABEL[concept_map]`("개념도")로 바뀌면, **캡션이 '구조도'라고
      말한 자료를 우리가 '개념도'라고 고쳐 부른다.**
      dev-2027 60쪽 실측: 유형이 배정된 29건 중 **22건이 concept_map**인데 그중 다수가
      캡션에 '모식도'·'구조도'라고 적혀 있다(`도표: 구조도, 삼각형 ABC…`).
      대표 지적 F16("삼각형 그림을 개념도로 인식")이 이 자리다.
      캡션이 유형어를 말했으면 그 말을 쓴다. 안 말했을 때만 대표 이름으로 물러난다.
    """
    head = ""
    for ln in (caption or "").split("\n"):
        if ln.strip():
            head = ln
            break
    for word, _sub in _SUBTYPE_WORDS:
        if word in head:
            return word
    return ""


def _level_text(line: str) -> tuple[int, str]:
    """캡션 한 줄 → (위계 레벨, 표지 뗀 본문). 들여쓰기 2칸 = 한 단계."""
    body = line.rstrip()
    indent = len(body) - len(body.lstrip(" \t"))
    body = body.strip()
    if _HEAD_RE.match(body):                       # '## 구성' — 마크다운 제목은 상위
        return 0, _HEAD_RE.sub("", body).strip()
    if _BULLET_RE.match(body):                     # '- 1: …' — 글머리표는 한 단계 아래
        return 1 + indent // 2, _BULLET_RE.sub("", body).strip()
    m = _NUM_RE.match(body)
    if m:                                          # '1. / 1) / ①' — 위계 번호(표지는 뗀다)
        lvl = _NUM_LEVEL.get(m.group(2), 2)
        return max(lvl, indent // 2), body[m.end():].strip()
    return indent // 2, body


def caption_outline(caption: str, *, keep_markers: bool = False,
                    limit: int | None = _MAX_LINES) -> list[tuple[int, str]]:
    """캡션 본문(첫 줄 제외) → 개조식 항목 [(level, text)].

    첫 줄은 유형 제시어를 단 머리줄이라 점역자 주(§6.3.4(1))가 가져간다 — 여기선 뺀다.

    `keep_markers=True` 는 **글머리·번호 표지를 그대로 둔다**(2026-09-07). §6.6 골격
    조립은 표지를 떼고 위계를 들여쓰기로 다시 그리지만, 그냥 전사하는 자리(§6.3.4(2)①
    이미지·차트)에서는 표지가 곧 내용이다 — `① 분수 / ② 화분에 꽂힌 꽃` 의 번호를 떼면
    문항이 묻는 `①` 이 무엇인지 알 수 없다. 도서지침 예3-45 도 `•`·`-` 를 그대로 쓴다.
    이때 위계는 **표지가 지므로** 원문 들여쓰기만 본다(표지로 단을 또 내리면 7칸까지
    밀려 gold(3칸 1,688줄 · 5칸 88줄)에서 멀어진다).

    `limit=None` 은 **줄 수 상한을 안 건다**(2026-09-08, 재구조화 4-1). 기본값
    `_MAX_LINES`(40)는 §6.6 골격 조립의 폭주 방어다 — "이보다 길면 골격이 아니라
    줄글" 이라는 판정이라 골격 경로에서는 맞다. 그런데 §6.3.4(2)① **전사** 경로
    (`keep_markers=True`)에서 같은 상한을 걸면 뒤쪽 **데이터 값 줄이 통째로 사라진다**
    (실측: 배지 개체 수 본문 46줄 → 40항목 · 세계 종교 분포 본문 55줄 → 40항목,
    잘리는 꼬리가 `20일: 8`·`불교 1.3` 같은 값 줄이다). 전사에는 상한을 안 건다.
    """
    lines = [ln for ln in (caption or "").split("\n") if ln.strip()]
    if len(lines) < 2:
        return []
    out: list[tuple[int, str]] = []
    for ln in (lines[1:] if limit is None else lines[1:limit + 1]):
        if keep_markers:
            lv = (len(ln) - len(ln.lstrip(" \t"))) // 2
            text = _HEAD_RE.sub("", ln.strip()).strip()   # 마크다운 표지만 뗀다
        else:
            lv, text = _level_text(ln)
        if text:
            out.append((lv, text))
    return out


def caption_head(caption: str) -> str:
    """캡션 첫 줄(유형 제시어·마크다운 표지 제거) — 개조식 머리줄·골격 제목용."""
    for ln in (caption or "").split("\n"):
        if ln.strip():
            return _strip_lead_type(ln)
    return ""


_GEN_RE = re.compile(r"^제?\s*(\d{1,2})\s*(?:세대|대)(?![가-힣])")


def _generation_levels(items: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """가계도 캡션이 평면일 때 줄머리의 'N세대'·'N대'로 세대 수준을 매긴다.

    §6.6.4(2)② "가장 처음 선조는 1칸에 적고, **후손 단계에 따라** 하위 수준으로 갈수록
    두 칸씩 들여쓰기 한다" — 정답 예6-21 실측도 그렇다(태조 1칸 → 진안대군 3칸 →
    의평군 5칸 → 문종 7칸). 그런데 캡션은 위계 표지 없이 한 줄씩 평면으로 온다
    (2026-09-09 실물 4건 `temp/vdemo/demo.json` f01~f04 전부 level 0) — 그래서 세대가
    전부 같은 칸에 서서 가계도가 목록과 구별되지 않았다(대표 QA 지적 3).

    ⚠ 캡션이 이미 위계를 줬으면(글머리·들여쓰기) 그쪽이 우선이다. 세대 표지가 두 줄
    미만이면 손대지 않는다 — 표지 없는 가계도(집안별로 적은 것 등)를 억지로 못 접는다.
    """
    if any(lv for lv, _ in items):
        return items
    gens = [_GEN_RE.match(t) for _lv, t in items]
    if sum(g is not None for g in gens) < 2:
        return items
    first = min(int(g.group(1)) for g in gens if g)
    out: list[tuple[int, str]] = []
    level = 0
    for (_lv, text), g in zip(items, gens):
        if g:
            level = max(0, int(g.group(1)) - first)
        out.append((level, text))
    return out


def _nest(items: list[tuple[int, str]]) -> list[dict]:
    """(level, text) 평면 목록 → nodes 트리. 레벨이 건너뛰어도 가장 가까운 부모에 붙인다."""
    roots: list[dict] = []
    stack: list[tuple[int, dict]] = []
    for lv, text in items:
        node = {"text": text, "children": []}
        while stack and stack[-1][0] >= lv:
            stack.pop()
        if stack:
            stack[-1][1]["children"].append(node)
        else:
            roots.append(node)
        stack.append((lv, node))
    return roots


def structure_from_caption(caption: str, subtype: str = "") -> dict | None:
    """캡션 → §6.6 골격 입력(structure). 만들 수 없으면 None(= 캡션 폴백 유지).

    반환 형식은 `diagram_opt._ASSEMBLERS`가 먹는 그대로다(nodes/boxes/events/items/sections).
    """
    subtype = subtype or subtype_from_caption(caption)
    if not subtype:
        return None
    items = caption_outline(caption)
    if not items:
        return None
    title = caption_head(caption)
    base = {"subtype": subtype, "title": title}

    if subtype in ("concept_map", "org_chart"):
        return {**base, "nodes": _nest(items)}
    if subtype == "family_tree":
        # 상향식 표기(§6.6.4(3))는 캡션만으로 방향을 알 수 없다 — 하향식 기본.
        return {**base, "mode": "top_down", "nodes": _nest(_generation_levels(items))}
    if subtype == "flowchart":
        # §6.6.2(4)①④ 논리 순서 번호 + 상자 한 줄에 하나. 분기(⑤⑥)는 캡션에 없어 생략.
        return {**base, "boxes": [{"no": i, "text": t} for i, (_lv, t) in enumerate(items, 1)]}
    if subtype == "timeline":
        events = [_event(t) for _lv, t in items]
        if sum(1 for e in events if e["date"]) < 2:
            # 캡션이 사건을 **한 줄에 쉼표로** 몰아 적어 오는 일이 흔하다(실측: 코퍼스 연표
            # 크롭 2건 모두 "1911 신해혁명, 1919 5·4운동, …"). 줄로 안 서면 그 줄을 훑는다.
            inline = [{"date": d.strip(), "text": t.strip()} for d, t in _INLINE_TL.findall(caption)]
            if len(inline) < 3:
                return None          # 날짜+사건 꼴이 아니면 연대표 골격을 못 세운다
            # 날짜로 안 잡힌 줄은 날짜 없는 사건으로 남긴다 — 내용을 버리지 않는다.
            events = inline + [e for e in events if not e["date"]]
            # 머리줄이 곧 사건 목록이었으므로 제목에서 그 부분을 뗀다(같은 내용 두 번 금지).
            m = _INLINE_TL.search(base["title"])
            head = base["title"][:m.start()].strip(" .,·:") if m else base["title"]
            base["title"] = "" if subtype_from_caption(head) or len(head) < 3 else head
        return {**base, "events": events}
    if subtype in ("form", "slide"):
        return {**base, "items": [{"text": t, "level": lv} for lv, t in items]}
    if subtype == "screen_image":
        sections: list[dict] = []
        for lv, t in items:
            if lv == 0 or not sections:
                sections.append({"name": t, "lines": []})
            else:
                sections[-1]["lines"].append(t)
        return {**base, "sections": sections}
    return None


def demo() -> None:
    """자체 점검 — 8종 골격 입력이 실제 캡션 모양에서 나오는지."""
    cap = ("도표: 고려의 중앙 통치 조직도\n"
           "1. 국왕\n"
           "1) 중서문하성\n"
           "1) 상서성\n"
           "① 이부\n")
    assert subtype_from_caption(cap) == "org_chart"
    st = structure_from_caption(cap)
    assert st["nodes"][0]["text"] == "국왕", st              # 위계 번호는 뗀다
    assert st["nodes"][0]["children"][1]["children"][0]["text"] == "이부", st

    cap2 = "도표: 정자 형성 과정 흐름도\n감수 1분열\n감수 2분열\n정자 4개"
    st2 = structure_from_caption(cap2)
    assert [b["no"] for b in st2["boxes"]] == [1, 2, 3], st2

    cap3 = "도표: 독립운동 연표\n1919년 3·1 운동\n1920년 청산리 대첩"
    st3 = structure_from_caption(cap3)
    assert st3["events"][0] == {"date": "1919년", "text": "3·1 운동"}, st3

    cap4 = "도표: ## 가계도(계통도)\n1세대\n- 1: 정상 남자\n- 2: 발현 여자\n2세대\n- 3: 정상 여자"
    st4 = structure_from_caption(cap4)
    assert st4["subtype"] == "family_tree" and len(st4["nodes"]) == 2, st4
    assert st4["nodes"][0]["children"][0]["text"] == "1: 정상 남자", st4   # 개체번호는 보존

    # 가계도 캡션이 **평면**으로 와도 줄머리 세대로 위계가 선다(§6.6.4(2)②, #794).
    cap4b = ("도표: 어떤 유전병에 대한 3대에 걸친 가계도이다.\n"
             "1세대 1 정상 남자 × 2 유전병 여자 →\n"
             "2세대 1 정상 여자, 2 유전병 남자\n"
             "3세대 1 정상 여자, 2 정상 남자\n"
             "2세대 5 정상 여자 × 6 정상 남자 →\n"
             "3세대 4 유전병 남자")
    st4b = structure_from_caption(cap4b, "family_tree")
    assert len(st4b["nodes"]) == 1, st4b                      # 1세대 하나가 뿌리
    kids = st4b["nodes"][0]["children"]
    assert [k["text"][:3] for k in kids] == ["2세대", "2세대"], st4b
    assert kids[0]["children"][0]["text"].startswith("3세대"), st4b
    # 세대 표지가 없으면 손대지 않는다 — 억지로 접지 않는다.
    cap4c = "도표: 두 집안 가계도이다.\n유전병 A 집안: 정상 남자 × 유전병 A 여자\n유전병 B 집안: 정상 남자"
    st4c = structure_from_caption(cap4c, "family_tree")
    assert len(st4c["nodes"]) == 2, st4c

    # 연표를 한 줄에 쉼표로 몰아 적어 온 경우 — 그래도 사건이 서고, 못 잡은 줄도 안 버린다.
    cap5 = ("도표: 연표. 1911 신해혁명, 1919 5·4운동, 1926 북벌개시.\n"
            "구간: (가) 1911~1919, (나) 1919~1926")
    st5 = structure_from_caption(cap5)
    assert [e["date"] for e in st5["events"][:3]] == ["1911", "1919", "1926"], st5
    assert st5["events"][-1]["date"] == "" and "구간" in st5["events"][-1]["text"], st5

    # 원문자 한글은 위계 표지가 아니라 개체 이름표다 — 떼지 않는다(문항이 `㉠`을 묻는다).
    cap6 = "도표: 모식도: 사람 몸의 방어 부위\n㉠ 피부\n㉡ 침\n㉢ 눈물"
    st6 = structure_from_caption(cap6)
    assert [n["text"] for n in st6["nodes"]] == ["㉠ 피부", "㉡ 침", "㉢ 눈물"], st6

    assert structure_from_caption("도표: 세계 지도\n유럽\n아시아") is None      # 골격 없는 유형
    assert structure_from_caption("도표: 조직도 한 줄뿐") is None               # 본문 없음
    assert caption_outline("한 줄뿐") == []
    print("diagram_structure demo OK")


if __name__ == "__main__":
    demo()
