"""제품에서 켜지면 출력이 조용히 나빠지는 측정 · 시험 스위치는 `.env` 로 못 켠다.

`config.py` 의 `load_dotenv()` 가 `.env` 값을 `os.environ` 에 넣으므로, 그냥 읽으면 서버 `.env` 한 줄로 켜진다.
`LLM_CACHE_MODE=ro` 면 캐시에 없는 LLM 호출을 안 해 그림 회수가 경고 한 줄만 남기고 빈 목록이 된다(2026-10-08 실측).
이 스위치들은 `config.process_env` 로만 읽는다.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.core import config as config_mod  # noqa: E402
from app.utils import llm_cache  # noqa: E402

_KEYS = ("SEMOJUM_MEASURE_REUSE", "BOUNDARY_REUSE", "MINERU_RAW_REUSE", "LLM_CACHE_MODE",
         "SEMOJUM_NO_CAPTION", "DISABLE_LLM_FALLBACK", "CHAIN_SEQUENTIAL")


def test_env_에_적힌_값은_무시하고_프로세스_env_는_읽는다(monkeypatch):
    monkeypatch.setenv("LLM_CACHE_MODE", "ro")
    monkeypatch.setattr(config_mod, "_DOTENV_KEYS", frozenset({"LLM_CACHE_MODE"}))   # load_dotenv 가 넣은 값
    assert config_mod.process_env("LLM_CACHE_MODE") is None and llm_cache.mode() == "rw"
    monkeypatch.setattr(config_mod, "_DOTENV_KEYS", frozenset())                     # 프로세스가 준 값
    assert config_mod.process_env("LLM_CACHE_MODE") == "ro" and llm_cache.mode() == "ro"


@pytest.mark.parametrize("key", _KEYS)
def test_앱은_이_스위치를_os_environ_으로_직접_읽지_않는다(key):
    """새 자리에서 `os.environ.get` 으로 읽으면 `.env` 로 다시 켜진다."""
    app = Path(__file__).parents[3] / "app"
    # 읽기만 잡는다(`os.environ["K"] = …` 쓰기는 llm_cache._demo 가 자기 시험에서 한다)
    pat = re.compile(rf"""os\.(?:environ\.get|getenv)\(\s*["']{key}["']|os\.environ\[\s*["']{key}["']\s*\](?!\s*=)""")
    hits = [f"{p.relative_to(app)}:{i}" for p in app.rglob("*.py")
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if pat.search(line)]
    assert hits == []
