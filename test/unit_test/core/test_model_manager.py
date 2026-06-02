"""model_manager graceful 로드 테스트 (#2 — 모델 로드 실패가 서버 기동을 막지 않음)."""
from unittest.mock import patch

from app.core.model_manager import ModelManager


class TestGracefulLoad:
    def test_qwen_로드실패_비치명적(self):
        # dev엔 Qwen 모델/awq 미탑재 → 로드 실패해도 예외 없이 None 격리
        mm = ModelManager()
        mm._load_qwen()                      # raise 안 해야 함
        assert mm._gpu0_models.get("qwen") is None
        assert mm._gpu0_models.get("qwen_processor") is None

    def test_hcxt_로드실패_비치명적(self):
        mm = ModelManager()
        with patch("transformers.AutoModelForCausalLM.from_pretrained",
                   side_effect=RuntimeError("forced load failure")):
            mm._load_hcxt()                  # raise 안 해야 함
        assert mm._gpu1_models.get("hcxt") is None
        assert mm._gpu1_models.get("hcxt_tokenizer") is None

    def test_property_미로드시_RuntimeError(self):
        # 격리된(None) 모델 접근 시 property가 RuntimeError → 호출부가 잡아 격리
        mm = ModelManager()
        mm._gpu1_models["hcxt"] = None
        import pytest
        with pytest.raises(RuntimeError):
            _ = mm.hcxt_model
