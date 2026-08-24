# -*- coding: utf-8 -*-
"""가드4 — 배지·장식을 그림으로 잡은 캡션 차단 (원장 C-70).

근거: fable VLM 전수 대조(코퍼스 1,511쪽·생물 제외, 2026-08-24).
발동 58건 전수가 배지·정답 원문자·로고·아이콘·화살표류였고 콘텐츠 오격발 0건.
면적 임계 방식은 유물 사진·인물 삽화를 같이 죽여 기각(같은 실측).
"""
import pytest

from app.ai.captioning.captioner import _reject_decoration


@pytest.mark.parametrize("cap", [
    "그림: 숫자 04",
    "그림: 원 안에 숫자 06",
    "그림: 숫자 12가 적힌 원형 배지",
    "그림: 답 ⑤",
    "그림: 2부",
    "그림: 알파벳 L과 t를 합친 로고",
    "그림: 알파벳 대문자 L",
    "그림: 한글 낱자 '가'",
    "그림: QR코드",
    "그림: 화살표",
    "그림: 오른쪽을 가리키는 화살표",
    "그림: 스크랩 아이콘",
])
def test_장식_캡션은_비운다(cap):
    assert _reject_decoration(cap) == ""


@pytest.mark.parametrize("cap", [
    # 실코퍼스에서 같은 크기 구간에 있던 진짜 콘텐츠들 — 절대 걸리면 안 된다
    "그림: 받침돌 위에 놓인 동굴 모양 바위",     # 동아시아사 금인(유물 사진)
    "그림: 교사",                                # 문항 인물 삽화
    "그림: 항아리로 보임",
    "도표: 계층 구조 피라미드",
    "그림: 학생들이 실험하는 모습",
    "그림: 12개의 화살표가 순환하는 구조",        # '화살표'가 내용 중간이면 통과
    "그림: 회사 로고가 박힌 간판 아래에서 사람들이 이야기함",
])
def test_콘텐츠_캡션은_보존한다(cap):
    assert _reject_decoration(cap) == cap


def test_빈_입력은_빈_문자열():
    assert _reject_decoration("") == ""
    assert _reject_decoration(None) == ""
