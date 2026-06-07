"""수치 그라운딩 공통 함수 numbers_grounded 단위 검증.

시각 opt(이미지·차트)는 설명문에 원본 수치가 누락/변조되면 R5로 표시한다 — 그 판정 함수.
유형별 R5·골격 회귀는 test_image_skeleton.py / test_cg_skeleton.py 참조.
(만화는 rule-based 전사라 수치 그라운딩 비대상 — test_cartoon_skeleton.py.)
"""
from __future__ import annotations

from app.ai.llm.base_opt import numbers_grounded


class TestNumbersGrounded:
    def test_전부_보존(self):
        assert numbers_grounded("3과 100", "값은 3, 그리고 100")

    def test_누락_검출(self):
        assert not numbers_grounded("3", "값은 5")

    def test_소수_보존(self):
        assert numbers_grounded("21.6", "비율 21.6%")

    def test_빈_원본은_항상_통과(self):
        assert numbers_grounded("수치 없는 설명", "아무 텍스트")
