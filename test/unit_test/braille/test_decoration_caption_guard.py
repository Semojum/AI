# -*- coding: utf-8 -*-
"""가드4 — 배지·장식을 그림으로 잡은 캡션 차단 (원장 C-70).

근거: fable VLM 전수 대조(코퍼스 1,511쪽·생물 제외, 2026-08-24).
발동 58건 전수가 배지·정답 원문자·로고·아이콘·화살표류였고 콘텐츠 오격발 0건.
면적 임계 방식은 유물 사진·인물 삽화를 같이 죽여 기각(같은 실측).
"""
import pytest

# `captioner` 는 외부 LLM SDK 를 문다. CI 의 test-fast 는 requirements.txt 만 깔아
# 그것이 없으므로 수집 단계에서 이 파일 하나 때문에 점역 게이트 전체가 죽는다
# (같은 일이 PR #233 test_table_tn_guard.py · PR #253 이 파일에서 났다).
# 없으면 이 파일만 건너뛴다 — test-full 이 그대로 돌려 준다(옆 test_caption_guards.py 와 같은 꼴).
try:
    from app.ai.captioning.captioner import _reject_decoration
except Exception:  # noqa: BLE001 — 무엇이 없든 건너뛴다
    pytest.skip("test-fast 환경에는 캡셔닝 의존성이 없다 (test-full 이 돌린다)",
                allow_module_level=True)


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
    # 2026-09-07 실측으로 늘린 얼굴 — dev·val 100쪽 표본과 캡션 캐시 1,834건에서 확인
    "그림: 답: ④",                      # 쌍점이 끼는 변이
    "사진: 숫자 5",                      # 유형 제시어가 '사진'으로 갈리는 변이
    "그림: 화살표 (오른쪽 방향)",         # 꼬리 괄호가 붙는 변이
    "그림: 오른쪽을 향한 화살표",
    "그림: 읽을 수 없는 기호",            # 배지를 모델이 못 읽은 자리
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
    # 유형 제시어를 '사진'까지 넓히면서 같이 확인한 것들
    "사진: 숫자 2 모양 오브제, 하트 모양에 '정' 글자가 적힌 오브제",   # 진짜 유물 사진
    "만화: 읽을 수 없는 기호",            # 만화 대사 안의 같은 문구는 내용이다
    "그림: 물의 순환을 나타낸 화살표 도식",
])
def test_콘텐츠_캡션은_보존한다(cap):
    assert _reject_decoration(cap) == cap


def test_빈_입력은_빈_문자열():
    assert _reject_decoration("") == ""
    assert _reject_decoration(None) == ""
