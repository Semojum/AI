"""재료 블록 계약 (2026-09-07 대표 지시 "재료는 많이 뽑고, 그 후에 간추려야지").

고정하는 것 넷. 넷 다 실측으로 잡은 함정이라 지우면 조용히 되돌아간다.

1. **기본은 꺼짐.** 켜면 `prompt_id` 가 `image+material` 로 갈려 캡션 캐시가 전량 미스다.
2. **재료가 없으면 종전과 같다.** 구 캡션·꺼진 실행이 `split_material` 을 지나도 원문 그대로.
3. **가드가 재료를 먹지 않는다.** `_drop_per_speech_narration` 은 대사 앞줄을 지문으로 보고
   지우므로, 재료의 `대사:` 줄들이 사슬에 들어가면 통째로 사라진다.
4. **설명이 버려지면 재료도 버린다.** 유형 제시어 없는 재료 덩이가 하류로 새면 안 된다.
"""
from __future__ import annotations

from app.ai.captioning import captioner as C


def test_기본은_꺼짐이라_프롬프트가_안_바뀐다(monkeypatch):
    monkeypatch.delenv("CAPTION_MATERIAL", raising=False)
    assert C._material_on() is False
    monkeypatch.setenv("CAPTION_MATERIAL", "1")
    assert C._material_on() is True


def test_재료_없으면_원문_그대로():
    head, facts = C.split_material("그림: 확대경\n손잡이형, 서랍식")
    assert head == "그림: 확대경\n손잡이형, 서랍식"
    assert facts == []


def test_열쇠말과_사실로_가른다():
    head, facts = C.split_material(
        "그림: 세포막\n"
        f"{C._MATERIAL_MARK}\n"
        "글자: ㉠, ㉡\n"
        "- 수치: 양반: 26.29%\n"     # 값 안의 쌍점은 사실 쪽에 남는다
        "해석: 계속 증가\n"           # 열쇠말이 아니면 버린다
        "못읽음: 오른쪽 아래 작은 글자\n"
    )
    assert head == "그림: 세포막"
    assert facts == [("글자", "㉠, ㉡"), ("수치", "양반: 26.29%"),
                     ("못읽음", "오른쪽 아래 작은 글자")]


def test_만화는_상황과_대사가_재료에서_갈린다():
    """gold 는 상황 한 문장만 점역자 주 **안**, 대사는 **밖**이다(census 27/27)."""
    _, facts = C.split_material(
        f"만화: 두 학생이 이야기한다\n{C._MATERIAL_MARK}\n"
        "상황: 교실에서 두 학생이 마주 본다\n"
        "대사: 철수: 여기가 어디야?\n"
        "대사: 영희: 도서관이야\n"
    )
    assert [k for k, _ in facts] == ["상황", "대사", "대사"]
    assert [v for k, v in facts if k == "대사"] == ["철수: 여기가 어디야?", "영희: 도서관이야"]


def test_가드가_재료_대사줄을_지우지_않는다():
    """`_drop_per_speech_narration` 이 재료에 닿으면 `대사:` 줄이 사라진다."""
    raw = (
        "만화: 두 학생이 이야기한다\n"
        "철수: 여기가 어디야?\n"
        f"{C._MATERIAL_MARK}\n"
        "상황: 교실에서 두 학생이 마주 본다\n"
        "대사: 철수: 여기가 어디야?\n"
    )
    out = C._finish(raw, "cartoon")
    _, facts = C.split_material(out)
    assert ("대사", "철수: 여기가 어디야?") in facts
    assert ("상황", "교실에서 두 학생이 마주 본다") in facts


def test_설명이_버려지면_재료도_버린다():
    """메타 응답(가드3)이면 재료만 남기지 않는다."""
    raw = f"이미지가 첨부되지 않았습니다.\n{C._MATERIAL_MARK}\n요소: 상자 2개\n"
    assert C._finish(raw, "image") == ""


def test_재료_열쇠말_고정():
    # 늘리려면 초안 조립기와 같이 봐야 한다 — 조용히 늘면 하류가 모르는 열쇠말이 생긴다.
    # 「없음」은 2026-09-07 에 「못읽음」에서 갈랐다: "있는데 못 읽음"은 §6.3.4(3)
    # L3183-3184 에 따라 알려야 하고 "아예 없음"은 아무것도 안 쓴다.
    assert C._MATERIAL_KEYS == ("글자", "요소", "관계", "축", "수치", "순서",
                                "상황", "대사", "없음", "못읽음")
