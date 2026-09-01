"""캡션 텍스트 → 도표 세분류(visual_subtype) + §6.6 골격 입력(structure).

**왜 캡션을 파싱하나.** 앞단은 도표의 내부 구조를 내지 않는다 — 분류기는
image/cartoon/chart/diagram 넉 자만 내고(`captioning/classifier.LABELS`), 경계 JSON의
`structure`·`visual_subtype` 칸은 비어 있다(실측 2026-08-08: 코퍼스 시각요소 3,315건 전부
0건). 그래서 `diagram_opt._ASSEMBLERS`의 §6.6 골격 8종이 **한 번도 돈 적이 없다**.

그런데 캡셔너의 `diagram` 프롬프트(`captioning/captioner._PROMPTS`)는 이미 두 가지를 시킨다:
  (a) 첫 줄에 유형어를 쓴다("…를 나타낸 흐름도"·"가계도(계통도)") — 실측 127건 중 110건
  (b) 구성 요소를 위계 있는 줄로 적는다("1세대 / - 1: … / - 2: …") — 실측 109건이 다줄
구조를 새로 만들 필요가 없다. 그 줄들을 읽으면 된다. 추가 API 호출 0, 결정적(rule-based).

한계(ponytail: 캡션 문장 파서다). 앞단(MinerU·VLM)이 진짜 구조를 내주면 그 값이 우선하고
이 모듈은 폴백으로 내려간다 — `diagram_opt`는 `ext.structure`가 있으면 여기를 안 부른다.
"""

from __future__ import annotations

import re

# 첫 줄 유형어 → §6.6 하위유형. 순서 = 판정 우선순위(구체적인 말 먼저).
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
_NUM_RE = re.compile(r"^(?:(\d{1,2})([.)])|([①-⑳])|([㉠-㉺]))\s+")
_NUM_LEVEL = {".": 0, ")": 1}
# 유형 제시어("도표: ", "그림: ") — captioner._ensure_type_word가 붙인 것.
# ★ F18(대표 지적) — 캡션 첫 줄의 **종류어**를 안 떼면 점역자 주의 유형과 두 번 나간다.
#   실물: '모식도\n개념도:\n삼각형 ABC:\n…' — 캡셔너가 첫 줄에 종류를 쓰라는 지시를 받고
#   '모식도'를 썼는데(captioner._PROMPTS["diagram"]), 종전 정규식이 콜론 붙은 여덟 낱말만
#   떼어 그 줄이 골격 **제목**으로 남았다. 유형은 §6.3.4(1)이 점역자 주로 내는 몫이므로
#   첫 줄의 종류어는 여기서 걷어낸다. 콜론이 없어도(줄 전체가 종류어여도) 뗀다.
_LEAD_TYPE_WORDS = (
    "도표|그림|사진|그래프|삽화|만화|지도|표"
    "|모식도|구조도|개념도|흐름도|순서도|공정도|조직도|계통도|가계도"
    "|연대표|연표|양식|화면\\s*이미지|발표용\\s*슬라이드|슬라이드"
)
_LEAD_TYPE_RE = re.compile(rf"^\s*(?:{_LEAD_TYPE_WORDS})\s*(?:[:：]\s*|$)")
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
    """첫 줄의 유형 제시어·마크다운 표지를 뗀다."""
    t = _LEAD_TYPE_RE.sub("", (text or "").strip())
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


def caption_outline(caption: str) -> list[tuple[int, str]]:
    """캡션 본문(첫 줄 제외) → 개조식 항목 [(level, text)].

    첫 줄은 유형 제시어를 단 머리줄이라 점역자 주(§6.3.4(1))가 가져간다 — 여기선 뺀다.
    """
    lines = [ln for ln in (caption or "").split("\n") if ln.strip()]
    if len(lines) < 2:
        return []
    out = [_level_text(ln) for ln in lines[1:_MAX_LINES + 1]]
    return [(lv, t) for lv, t in out if t]


def caption_head(caption: str) -> str:
    """캡션 첫 줄(유형 제시어·마크다운 표지 제거) — 개조식 머리줄·골격 제목용."""
    for ln in (caption or "").split("\n"):
        if ln.strip():
            return _strip_lead_type(ln)
    return ""


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
        return {**base, "mode": "top_down", "nodes": _nest(items)}
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

    # 연표를 한 줄에 쉼표로 몰아 적어 온 경우 — 그래도 사건이 서고, 못 잡은 줄도 안 버린다.
    cap5 = ("도표: 연표. 1911 신해혁명, 1919 5·4운동, 1926 북벌개시.\n"
            "구간: (가) 1911~1919, (나) 1919~1926")
    st5 = structure_from_caption(cap5)
    assert [e["date"] for e in st5["events"][:3]] == ["1911", "1919", "1926"], st5
    assert st5["events"][-1]["date"] == "" and "구간" in st5["events"][-1]["text"], st5

    assert structure_from_caption("도표: 세계 지도\n유럽\n아시아") is None      # 골격 없는 유형
    assert structure_from_caption("도표: 조직도 한 줄뿐") is None               # 본문 없음
    assert caption_outline("한 줄뿐") == []
    print("diagram_structure demo OK")


if __name__ == "__main__":
    demo()
