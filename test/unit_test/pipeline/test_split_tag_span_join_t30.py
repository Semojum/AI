"""T30 — 강조가 줄마다 닫히고 열려 낱말 가운데 갈림이 태그 뒤에 숨던 것.

`…통해 가<!/강조>\\n<!강조>출 동기…` 를 판정기가 태그 글자 탓에 어절 경계로 읽어
안 잇거나(`가‖출`) 빈칸으로 이었다(`주춧돌 을`). 2027 사회문화 dv-013 p056 · 언어와 매체 dv-004 p220.
"""
from app.core.pipeline import _join_split_tag_spans


def test_낱말_안이면_강조_한_덩이로_잇는다():
    src = "㉠ <!강조>질문을 통해 가<!/강조>\n<!강조>출 동기 및 가출 횟수 등을 조사하였다<!/강조>."
    assert _join_split_tag_spans(src) == "㉠ <!강조>질문을 통해 가출 동기 및 가출 횟수 등을 조사하였다<!/강조>."
    assert _join_split_tag_spans("세우는 방식에는 주춧돌<!/강조>\n<!강조>을 정교하게") == "세우는 방식에는 주춧돌을 정교하게"


def test_어절_경계면_그대로():
    src = "이슬람<!/강조>\n<!강조>세계의 확장"
    assert _join_split_tag_spans(src) == src


def test_다른_태그_쌍은_안_건드린다():
    src = "제목<!/상자>\n<!상자끝>본문"
    assert _join_split_tag_spans(src) == src
    src2 = "가<!/강조>\n<!밑줄>출"
    assert _join_split_tag_spans(src2) == src2
