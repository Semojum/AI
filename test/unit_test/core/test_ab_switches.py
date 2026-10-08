"""4단계 A/B 의 전제 스위치 (T39 S1~S4). 기본 동작은 그대로이고, 끈 팔은 계수기로 확인된다.

S1 캡션 · 분류 · 세분류 캐시가 `LLM_CACHE_MODE`(rw · ro · off)를 따른다. ro 는 "이 팔에서 외부 호출 0".
S2 `BOUNDARY_REUSE=never` 면 경계를 늘 다시 뜬다.
S3 `MINERU_RAW_REUSE=never` 면 캐시된 MinerU 출력을 안 쓴다.
S4 분류 · 세분류 캐시 적중 · 미스가 계수기 줄에 선다.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.captioning import captioner  # noqa: E402
from app.core import pipeline  # noqa: E402
from app.ai.parser import mineru_runner  # noqa: E402
from app.utils import llm_cache  # noqa: E402
from app.utils.req_log import llm_counter_line, start_request  # noqa: E402


@pytest.fixture(autouse=True)
def _measure_reuse(monkeypatch):
    """이 시험들은 측정 러너의 재사용 동작을 본다. 제품 기본은 재사용을 끈다(#1212)."""
    monkeypatch.setenv("SEMOJUM_MEASURE_REUSE", "1")


@pytest.fixture
def cap_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPTION_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("LLM_CACHE_MODE", raising=False)
    llm_cache.set_scope("job-s1")
    start_request()
    yield tmp_path
    llm_cache.set_scope("")


class TestS1_캐시_모드:
    def test_rw_기본은_종전대로_읽고_쓴다(self, cap_cache):
        p = captioner._cache_new_file("classify", b"img", "classify")
        assert captioner._cache_lookup("classify", p) is None       # 미스 → 호출로 간다
        captioner._cache_put(p, "chart")
        assert captioner._cache_lookup("classify", p) == "chart"

    def test_ro_미스는_호출_대신_CacheMiss(self, cap_cache, monkeypatch):
        monkeypatch.setenv("LLM_CACHE_MODE", "ro")
        p = captioner._cache_new_file("caption", b"img", "image")
        with pytest.raises(llm_cache.CacheMiss):
            captioner._cache_lookup("caption", p)

    def test_ro_는_안_쓴다(self, cap_cache, monkeypatch):
        monkeypatch.setenv("LLM_CACHE_MODE", "ro")
        p = captioner._cache_new_file("caption", b"img", "image")
        captioner._cache_put(p, "그림: 새 캡션")
        assert not p.exists()

    def test_ro_적중은_그대로_읽는다(self, cap_cache, monkeypatch):
        p = captioner._cache_new_file("caption", b"img", "image")
        captioner._cache_put(p, "그림: 스냅숏")                      # rw 로 담아 둔 것
        monkeypatch.setenv("LLM_CACHE_MODE", "ro")
        assert captioner._cache_lookup("caption", p) == "그림: 스냅숏"

    def test_off_는_캐시_자리가_없다(self, cap_cache, monkeypatch):
        monkeypatch.setenv("LLM_CACHE_MODE", "off")
        assert captioner._cache_new_file("caption", b"img", "image") is None

    def test_세분류_ro_미스는_골격_없이_물러난다(self, cap_cache, monkeypatch):
        """세분류는 못 받아도 라벨은 살았다 — 콜 실패와 같게 "" 로 물러나고 호출은 안 나간다."""
        from app.ai.captioning import classifier
        monkeypatch.setenv("LLM_CACHE_MODE", "ro")

        def _no_call(*a, **kw):
            raise AssertionError("ro 에서 API 를 불렀다")
        monkeypatch.setattr("anthropic.Anthropic", _no_call)
        assert classifier._subtype("aW1n", "image/png", b"img") == ""


class TestS4_계수기:
    def test_분류_세분류_적중_미스가_줄에_선다(self, cap_cache):
        p = captioner._cache_new_file("classify", b"img", "classify")
        captioner._cache_lookup("classify", p)                        # 미스
        captioner._cache_put(p, "diagram")
        captioner._cache_lookup("classify", p)                        # 적중
        q = captioner._cache_new_file("subtype", b"img", "subtype")
        captioner._cache_lookup("subtype", q)                         # 미스
        line = llm_counter_line()
        assert "분류 call=0 hit=1 miss=1" in line and "세분류 call=0 hit=0 miss=1" in line


class TestS2_경계_재파생:
    @pytest.mark.parametrize("env, reason, want", [
        ("", None, None),                       # 지문이 맞으면 그대로 쓴다(기본)
        ("", "extract_sha", "extract_sha"),     # 지문이 틀리면 다시 뜬다(기본)
        ("always", "extract_sha", None),        # 되돌리는 길
        ("always", "no_doc_meta", "no_doc_meta"),
        ("never", None, "never"),               # ★ 지문이 맞아도 다시 뜬다
        ("never", "extract_sha", "never"),
    ])
    def test_BOUNDARY_REUSE(self, monkeypatch, env, reason, want):
        monkeypatch.setenv("BOUNDARY_REUSE", env)
        assert pipeline._boundary_reuse(reason) == want


class TestS3_MinerU_원출력_재사용:
    def _seed(self, d: Path):
        d.mkdir(parents=True, exist_ok=True)
        (d / "p_content_list.json").write_text("[]", encoding="utf-8")

    def test_기본은_있으면_쓴다(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MINERU_RAW_REUSE", raising=False)
        self._seed(tmp_path / "mineru_raw")
        assert mineru_runner._raw_dir(tmp_path, None) == (tmp_path / "mineru_raw", True)

    def test_never_면_이_쪽_폴더를_비워_새로_받는다(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MINERU_RAW_REUSE", "never")
        self._seed(tmp_path / "mineru_raw")
        given = tmp_path / "given_cache"
        self._seed(given)
        raw, reused = mineru_runner._raw_dir(tmp_path, str(given))
        assert (raw, reused) == (tmp_path / "mineru_raw", False)
        assert not raw.exists() and (given / "p_content_list.json").exists()   # 주어진 캐시는 안 건드린다
