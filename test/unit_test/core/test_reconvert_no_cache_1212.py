"""같은 job 쪽을 다시 변환해도 매번 다시 추출한다(대표 결정 2026-10-08, #1212).

제품 기본은 경계 파일 · MinerU 원출력 · 캡션/분류 캐시 재사용을 끈다. 측정 러너만 프로세스 env
`SEMOJUM_MEASURE_REUSE=1` 로 재사용을 켜고, `.env` 에 적힌 값으로는 못 켠다. LLM 응답 캐시는 대표 결재
대기라 `llm_cache.LLM_CACHE_IN_PRODUCT` 한 줄로 가른다.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.captioning import captioner  # noqa: E402
from app.ai.parser import mineru_runner  # noqa: E402
from app.core import config as config_mod  # noqa: E402
from app.core import pipeline  # noqa: E402
from app.utils import llm_cache  # noqa: E402


@pytest.fixture
def product(monkeypatch):
    """제품: 측정 스위치 없음(`.env` 에도 없음)."""
    monkeypatch.delenv("SEMOJUM_MEASURE_REUSE", raising=False)
    monkeypatch.setattr(config_mod, "_DOTENV_KEYS", frozenset())


def _seed(d: Path):
    d.mkdir(parents=True, exist_ok=True)
    (d / "p_content_list.json").write_text("[]", encoding="utf-8")


def test_측정_스위치는_프로세스_env_로만_켠다(product, monkeypatch):
    assert config_mod.measure_reuse() is False
    monkeypatch.setenv("SEMOJUM_MEASURE_REUSE", "1")
    assert config_mod.measure_reuse() is True
    # `.env` 에 적힌 값이면(load_dotenv 가 os.environ 에 넣은 것) 무시한다
    monkeypatch.setattr(config_mod, "_DOTENV_KEYS", frozenset({"SEMOJUM_MEASURE_REUSE"}))
    assert config_mod.measure_reuse() is False


def test_제품은_지문이_맞는_경계도_다시_뜬다(product, monkeypatch):
    monkeypatch.setenv("BOUNDARY_REUSE", "always")          # 세부 스위치가 있어도 제품은 다시 뜬다
    assert pipeline._boundary_reuse(None) == "reconvert"
    monkeypatch.setenv("SEMOJUM_MEASURE_REUSE", "1")
    assert pipeline._boundary_reuse(None) is None


def test_제품은_MinerU_원출력을_비우고_다시_받는다(product, monkeypatch, tmp_path):
    monkeypatch.delenv("MINERU_RAW_REUSE", raising=False)
    _seed(tmp_path / "mineru_raw")
    assert mineru_runner._raw_dir(tmp_path, None) == (tmp_path / "mineru_raw", False)
    assert not (tmp_path / "mineru_raw").exists()
    monkeypatch.setenv("SEMOJUM_MEASURE_REUSE", "1")
    _seed(tmp_path / "mineru_raw")
    assert mineru_runner._raw_dir(tmp_path, None) == (tmp_path / "mineru_raw", True)


def test_제품은_캡션_분류_캐시를_안_쓴다(product, monkeypatch, tmp_path):
    monkeypatch.setenv("CAPTION_CACHE_DIR", str(tmp_path))
    llm_cache.set_scope("job-1212")
    try:
        assert captioner._cache_new_file("caption", b"img", "image") is None
        monkeypatch.setenv("SEMOJUM_MEASURE_REUSE", "1")
        assert captioner._cache_new_file("caption", b"img", "image") is not None
    finally:
        llm_cache.set_scope("")


def test_LLM_캐시는_한_줄로_가른다(product, monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))
    assert llm_cache.root() is not None                      # 대표 결재 전: 제품에서도 지금대로
    monkeypatch.setattr(llm_cache, "LLM_CACHE_IN_PRODUCT", False)
    assert llm_cache.root() is None                          # 결재로 끄면 제품에서 꺼진다
    monkeypatch.setenv("SEMOJUM_MEASURE_REUSE", "1")
    assert llm_cache.root() is not None                      # 측정 러너는 그대로
