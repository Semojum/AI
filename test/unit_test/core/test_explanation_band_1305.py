"""대표 기출 쪽 해설 띠 차례(#1305) — 곁단 '정답과 해설' 덩이를 같은 높이 띠의 문제 바로 뒤로.

gold 차례: 대표 기출문제 → … → ⑤ → [정답과 해설] → 닮은꼴 문제 → … → ⑤ → [정답과 해설](세계사 body p0077 ·
동아시아사 body p0094). 좌표는 그 두 쪽 응답의 bbox 에서 해설 덩이 가운데 줄을 뺀 것(쪽 1167×1474 픽셀).
"""
from uuid import uuid4

from app.ai.braille.regulations import make_rule
from app.core.pipeline import _band_explanations
from app.schemas.content import ExtractedContent
from app.schemas.layout import BBoxItem

H = 1474


def _page(*specs):
    items, ext = [], {}
    for k, (etype, bbox, text) in enumerate(specs, start=1):
        eid = uuid4()
        items.append(BBoxItem(element_id=eid, type=etype, bbox=bbox, reading_order=k))
        ext[eid] = ExtractedContent(element_id=eid, corrected_text=text)
    return items, ext


def _texts(items, ext):
    return [ext[it.element_id].corrected_text for it in sorted(items, key=lambda b: b.reading_order)]


# 홀수 쪽: 문제 단 왼쪽(x 140~770) · 해설 단 오른쪽(x 816~1078). 지금 차례 = 문제1 → 문제2 → 해설1 → 해설2 → 꼬리말.
ODD = [
    ("title", (146, 80, 273, 119), "대표 기출"),
    ("title", (144, 147, 247, 171), "대표 기출문제"),
    ("text", (141, 186, 547, 211), "밑줄 친 ‘종교적 타협’에 대한 설명으로 가장 적절한 것은?"),
    ("text", (141, 517, 356, 544), "① 낭트 칙령을 반포하였다."),
    ("text", (140, 637, 496, 665), "⑤ 콘스탄츠 공의회를 개최하기로 결정하였다."),
    ("title", (152, 815, 239, 839), "닮은꼴 문제"),
    ("text", (155, 905, 770, 1169), "바르트부르크성에서 (가)이/가 숨어 지내고"),
    ("text", (140, 1315, 558, 1343), "⑤ 신학대전을 통해 신앙과 이성의 조화를 강조하였다."),
    ("title", (818, 164, 902, 187), "정답과 해설"),
    ("text", (1025, 165, 1078, 186), "정답  ③"),
    ("text", (816, 189, 1078, 355), "정답 해설 ▶ 자료에서 비텐베르크에서"),
    ("text", (816, 357, 1078, 430), "⑤ 로마 가톨릭교회는 실추된 교황권을"),
    ("title", (822, 833, 900, 855), "정답과 해설"),
    ("text", (1025, 833, 1076, 855), "정답  ④"),
    ("text", (816, 858, 1078, 977), "정답 해설 ▶ 자료에서 바르트부르크성에서"),
    ("text", (816, 979, 1078, 1050), "⑤ 토마스 아퀴나스는"),
    ("text", (882, 1396, 1040, 1415), "07. 유럽 세계의 형성과 변화"),
]


def test_홀수_쪽_해설을_같은_띠_문제_뒤로(monkeypatch):
    monkeypatch.delenv("EXPL_BAND_ORDER", raising=False)
    items, ext = _page(*ODD)
    _band_explanations(items, ext, H)
    t = _texts(items, ext)
    assert t == [ODD[i][2] for i in (0, 1, 2, 3, 4, 8, 9, 10, 11, 5, 6, 7, 12, 13, 14, 15, 16)]
    labels = [e for e in ext.values() if e.corrected_text == "정답과 해설"]
    assert [e.layout_rules for e in labels] == [["NLD-2.2.5"], ["NLD-2.2.5"]]
    assert sum(bool(e.layout_rules) for e in ext.values()) == 2
    assert make_rule("NLD-2.2.5").source == "점자 도서 제작 지침"     # 댕글링 rule_id 아님


# 짝수 쪽: 해설 단 왼쪽(x 84~348) · 문제 단 오른쪽(x 378~840). 넓은 쪽 머리 제목(x 110~636)이 해설 단 위에 걸치고,
# 문제2 의 ⑤ 가 해설2 덩이 아래(1318 > 1010)에 있다.
EVEN = [
    ("text", (110, 77, 636, 119), "대표 기출  확인하기 | 동아시아의 근대"),
    ("title", (382, 147, 485, 171), "대표 기출문제"),
    ("text", (379, 183, 840, 214), "밑줄 친 ‘조약’에 대한 탐구 활동으로 옳은 것은?"),
    ("text", (378, 517, 840, 544), "① 미국의 중재로 체결되었다."),
    ("text", (378, 640, 840, 668), "⑤ 러시아가 주도하는 삼국 간섭의 원인이 되었다."),
    ("title", (390, 760, 477, 785), "닮은꼴 문제"),
    ("text", (379, 800, 840, 830), "다음 탐구 활동으로 가장 적절한 것은?"),
    ("text", (378, 1318, 840, 1346), "⑤ 서양 외교관의 베이징 주재 허용이 갖는 의미"),
    ("title", (88, 164, 174, 187), "정답과 해설"),
    ("text", (292, 165, 348, 186), "정답  ②"),
    ("text", (85, 189, 348, 379), "정답 해설 ▶ 자료에서 임칙서가"),
    ("text", (84, 382, 348, 450), "⑤ 청일 전쟁의 결과 1895년"),
    ("title", (88, 769, 172, 792), "정답과 해설"),
    ("text", (294, 771, 345, 792), "정답  ②"),
    ("text", (85, 793, 348, 937), "정답 해설 ▶ 자료에서 청의 도광제가"),
    ("text", (84, 939, 348, 1010), "⑤ 청은 제2차 아편 전쟁의 결과"),
]


def test_짝수_쪽_넓은_제목과_해설보다_아래인_선지(monkeypatch):
    monkeypatch.delenv("EXPL_BAND_ORDER", raising=False)
    items, ext = _page(*EVEN)
    _band_explanations(items, ext, H)
    t = _texts(items, ext)
    assert t == [EVEN[i][2] for i in (0, 1, 2, 3, 4, 8, 9, 10, 11, 5, 6, 7, 12, 13, 14, 15)]


def test_표지가_하나면_그대로(monkeypatch):
    monkeypatch.delenv("EXPL_BAND_ORDER", raising=False)
    specs = [s for k, s in enumerate(ODD) if k not in (12, 13, 14, 15)]
    items, ext = _page(*specs)
    before = _texts(items, ext)
    _band_explanations(items, ext, H)
    assert _texts(items, ext) == before
    assert not any(e.layout_rules for e in ext.values())


def test_해설_덩이_사이에_다른_요소면_그대로(monkeypatch):
    monkeypatch.delenv("EXPL_BAND_ORDER", raising=False)
    specs = ODD[:12] + [("text", (300, 700, 600, 720), "본문 단 요소")] + ODD[12:]
    items, ext = _page(*specs)
    before = _texts(items, ext)
    _band_explanations(items, ext, H)
    assert _texts(items, ext) == before


def test_해설_몸이_없으면_그대로(monkeypatch):
    monkeypatch.delenv("EXPL_BAND_ORDER", raising=False)
    specs = [(t, b, "보충 설명" if txt.startswith("정답") and txt != "정답과 해설" else txt) for t, b, txt in ODD]
    items, ext = _page(*specs)
    before = _texts(items, ext)
    _band_explanations(items, ext, H)
    assert _texts(items, ext) == before


def test_본문_단이_없으면_그대로(monkeypatch):
    """해설 단이 이미 쪽 맨 앞(동아시아사 p0014) — 첫 표지 앞에 본문이 없다."""
    monkeypatch.delenv("EXPL_BAND_ORDER", raising=False)
    specs = ODD[8:16] + ODD[:8] + ODD[16:]
    items, ext = _page(*specs)
    before = _texts(items, ext)
    _band_explanations(items, ext, H)
    assert _texts(items, ext) == before


def test_끈_스위치는_그대로(monkeypatch):
    monkeypatch.setenv("EXPL_BAND_ORDER", "0")
    items, ext = _page(*ODD)
    before = _texts(items, ext)
    _band_explanations(items, ext, H)
    assert _texts(items, ext) == before
    assert not any(e.layout_rules for e in ext.values())


def test_문제_머리표가_표지보다_높이_있어도_해설은_머리표_앞(monkeypatch):
    """세계사 p0105: '닮은꼴 문제'(y 743) · 문항 코드(y 759)가 둘째 표지(y 811)보다 68px 위다. 표지 − 3% 로만 띠를 끊으면
    머리표가 띠 1 로 들어가 해설1 이 '닮은꼴 문제' 뒤에 붙는다."""
    monkeypatch.delenv("EXPL_BAND_ORDER", raising=False)
    specs = [
        ("title", (144, 147, 247, 171), "대표 기출문제"),
        ("text", (141, 183, 516, 214), "밑줄 친 ‘짐’의 재위 시기에 있었던 사실로 옳은 것은?"),
        ("text", (140, 628, 470, 656), "⑤ 3월 혁명으로 메테르니히가 실각되었다."),
        ("title", (152, 743, 239, 768), "닮은꼴 문제"),
        ("text", (710, 759, 787, 781), "26016-0136"),
        ("text", (141, 781, 547, 808), "밑줄 친 ㉠ 시기에 볼 수 있는 모습으로 가장 적절한 것은?"),
        ("text", (155, 833, 770, 1175), "위대한 왕국을 건설하였던 군주들이"),
        ("text", (140, 1318, 596, 1346), "⑤ 부패 선거구 폐지 등 제1차 선거법 개정에 합의하는 의원"),
        ("title", (818, 164, 904, 187), "정답과 해설"),
        ("text", (1025, 165, 1078, 186), "정답  ④"),
        ("text", (815, 189, 1078, 355), "정답 해설 ▶ 자료에서 프랑스 국민"),
        ("title", (818, 811, 902, 833), "정답과 해설"),
        ("text", (1025, 811, 1078, 833), "정답  ③"),
        ("text", (815, 837, 1078, 1051), "정답 해설 ▶ 자료에서 약 60년 전"),
    ]
    items, ext = _page(*specs)
    _band_explanations(items, ext, H)
    assert _texts(items, ext) == [specs[i][2] for i in (0, 1, 2, 8, 9, 10, 3, 4, 5, 6, 7, 11, 12, 13)]
