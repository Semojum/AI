"""T30 — 강조가 줄마다 닫히고 열려 낱말 가운데 갈림이 태그 뒤에 숨던 것.

`…통해 가<!/강조>\\n<!강조>출 동기…` 를 판정기가 태그 글자 탓에 어절 경계로 읽어
안 잇거나(`가‖출`) 빈칸으로 이었다(`주춧돌 을`). 2027 사회문화 dv-013 p056 · 언어와 매체 dv-004 p220.
"""
from app.core.pipeline import _join_split_tag_spans


def test_낱말_안이면_강조_한_덩이로_잇는다():
    src = "㉠ <!강조>질문을 통해 가<!/강조>\n<!강조>출 동기 및 가출 횟수 등을 조사하였다<!/강조>."
    assert _join_split_tag_spans(src) == "㉠ <!강조>질문을 통해 가출 동기 및 가출 횟수 등을 조사하였다<!/강조>."
    assert _join_split_tag_spans("세우는 방식에는 주춧돌<!/강조>\n<!강조>을 정교하게") == "세우는 방식에는 주춧돌을 정교하게"


def test_어절_경계면_태그만_걷고_줄바꿈은_남긴다(monkeypatch):
    """#1164 — 인쇄 줄바꿈 사이로 갈린 강조는 어절 경계여도 gold 가 한 강조다(dev 142 · val 103 대 0).
    줄바꿈은 남겨 뒤의 줄 잇기가 띄어쓰기를 정한다. 종전 이 시험은 '그대로'를 지켜 강조가 줄마다 끊겼다."""
    monkeypatch.delenv("EMPH_LINE_JOIN", raising=False)
    assert _join_split_tag_spans("<!강조>이슬람<!/강조>\n<!강조>세계의 확장<!/강조>") == "<!강조>이슬람\n세계의 확장<!/강조>"


def test_같은_줄_빈칸_사이_강조는_따로_둔다(monkeypatch):
    """언어와 매체 문법 예문의 낱말별 밑줄 — gold 도 두 강조다(dev body p0061)."""
    monkeypatch.delenv("EMPH_LINE_JOIN", raising=False)
    src = "㉠ 엄마는 <!강조>매끼를<!/강조> <!강조>새 밥으로<!/강조> 차려\n주셨었다."
    assert _join_split_tag_spans(src) == src


def test_끈_스위치는_어절_경계를_그대로(monkeypatch):
    monkeypatch.setenv("EMPH_LINE_JOIN", "0")
    src = "이슬람<!/강조>\n<!강조>세계의 확장"
    assert _join_split_tag_spans(src) == src


def test_다른_태그_쌍은_안_건드린다():
    src = "제목<!/상자>\n<!상자끝>본문"
    assert _join_split_tag_spans(src) == src
    src2 = "가<!/강조>\n<!밑줄>출"
    assert _join_split_tag_spans(src2) == src2
