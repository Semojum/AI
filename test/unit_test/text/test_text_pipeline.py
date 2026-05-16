"""PART 4-1~4-3 — 텍스트 파이프라인 단위 테스트 (단계 2 구현 예정).

QwenOCR, TextOpt, TextBraille 연결 흐름 검증.
"""

import pytest

pytestmark = pytest.mark.skip(reason="QwenOCR, TextOpt GPU 모델 필요 — GPU 환경에서 활성화")

# TODO [단계 2 GPU 테스트]
# class TestQwenOCR:
#     def test_zero_tier_no_qwen_call(self): ...
#     def test_vertical_text_flag(self): ...
#
# class TestTextOptIntegration:
#     def test_standard_tier_corrects_text(self): ...
#     def test_fallback_after_3_failures(self): ...
#
# class TestTextBrailleEndToEnd:
#     def test_hangul_sentence(self): ...
#     def test_rule_trail_not_empty(self): ...
