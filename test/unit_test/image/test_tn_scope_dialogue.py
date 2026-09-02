"""점역자 주는 **장면까지**만 감싼다 — 대사는 주 밖이다.

점역자 주는 "원본과 달라진 내용"을 담는 자리인데(NLD-1.2.6), 그림 속 대사는 원본에
있는 말이라 점역자가 지어낸 게 아니다. gold 실측: `화자: 발화` 줄이
**주 밖 49 : 안 21**(70%가 밖). 종전에는 설명 전체를 감싸 대사까지 주 안에 들어갔다.
"""
from app.ai.llm.visual_drafts import _SPEAKER_LINE


def _wrap(lines):
    tn_from, tn_to = 0, len(lines) - 1
    while tn_to > tn_from and _SPEAKER_LINE.match(lines[tn_to].strip()):
        tn_to -= 1
    out = list(lines)
    out[tn_from] = f"<!주>{out[tn_from]}"
    out[tn_to] = f"{out[tn_to]}<!/주>"
    return out


def test_대사는_주_밖으로():
    out = _wrap(["만화: 후보자 3명이 토론회를 한다.",
                 "후보자 1: 조약을 감시하겠습니다.",
                 "후보자 2: 교복을 인하하겠습니다."])
    assert out[0] == "<!주>만화: 후보자 3명이 토론회를 한다.<!/주>"
    assert not out[1].startswith("<!") and "<!/주>" not in out[1]
    assert "<!" not in out[2]


def test_대사가_없으면_전체를_감싼다():
    out = _wrap(["그림: 세포막 구조", "안쪽에 핵산이 있다.", "바깥은 단백질 껍질이다."])
    assert out[0].startswith("<!주>") and out[-1].endswith("<!/주>")


def test_이름_설명_줄은_대사가_아니다():
    # `가랑잎벌레: 나뭇잎과 비슷하다` 는 설명 본체다 — 주 밖으로 빼면 안 된다.
    out = _wrap(["그림: 의태 사례", "가랑잎벌레: 나뭇잎과 비슷하게 생겼다."])
    assert out[-1].endswith("<!/주>")


def test_한_줄뿐이면_그_줄을_감싼다():
    assert _wrap(["사진: 쑨원"]) == ["<!주>사진: 쑨원<!/주>"]
