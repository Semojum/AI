"""캡션 캐시 판 번호 열쇠 (재구조화 3-c).

열쇠 = `sha256(kind | 입력 | 모델 | prompt_id | 판 번호)`. 프롬프트 전문은 뺐다.
확인하는 것 넷:
  · 프롬프트 문안을 고쳐도 열쇠가 안 갈린다(그게 이 단계의 목적이다)
  · 입력·모델·유형·판 번호가 갈리면 열쇠도 갈린다
  · 옛 자리(전문 키) 항목을 여전히 읽는다 — 3,242건을 버리지 않는다
  · **히트에도 `_finish` 를 건다** — 새 가드가 옛 캐시본에도 닿는다
"""

import pytest

from app.ai.captioning import captioner
from app.utils import llm_cache


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPTION_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("CAPTION_MATERIAL", raising=False)
    return tmp_path


def _new(raw=b"img", prompt_id="image", context=""):
    return captioner._cache_new_file("caption", raw, prompt_id, context)


def test_off_when_no_dir(monkeypatch):
    monkeypatch.delenv("CAPTION_CACHE_DIR", raising=False)
    assert _new() is None


def test_prompt_text_no_longer_splits_the_key(cache_dir):
    """문안을 고쳐도 열쇠는 그대로 — 전량 미스를 물지 않는다."""
    a = captioner._cache_file(b"img", "image", "프롬프트 첫 판")
    b = captioner._cache_file(b"img", "image", "프롬프트 둘째 판")
    assert a != b                                   # 옛 열쇠는 갈렸다
    assert _new() == _new()                         # 새 열쇠는 문안을 안 본다


@pytest.mark.parametrize("kw", [
    {"raw": b"other-image"},
    {"prompt_id": "cartoon"},
    {"prompt_id": "image+material"},
    {"context": "이웃 본문이 다르다"},
])
def test_inputs_still_split_the_key(cache_dir, kw):
    """입력이 갈리면 캡션도 갈려야 한다 — 이건 열쇠에 남겼다."""
    assert _new(**kw) != _new()


def test_model_splits_the_key(cache_dir, monkeypatch):
    base = _new()
    monkeypatch.setenv("CAPTION_MODEL", "gpt-4o")
    assert _new() != base


def test_version_bump_splits_the_key(cache_dir):
    base = _new()
    llm_cache.PROMPT_VER["caption"] += 1
    try:
        assert _new() != base
    finally:
        llm_cache.PROMPT_VER["caption"] -= 1
    assert _new() == base


def test_caption_and_label_go_to_different_directories(cache_dir):
    """★ 캡션과 분류 라벨을 kind 로 가른다.

    한 자리에 섞여 있으면 옮기거나 쓸어 담을 때 라벨이 캡션 자리로 들어가
    `그림: chart` 가 나온다(3,242건 = 캡션 1,961 + 라벨 1,281, 실제로 관찰됨).
    """
    cap = captioner._cache_new_file("caption", b"img", "image")
    lab = captioner._cache_new_file("classify", b"img", "classify")
    assert cap.parent.name == "caption" and lab.parent.name == "classify"
    assert cap.parent != lab.parent


# ── 읽기: 옛 자리 · 히트에도 가드 ──────────────────────────────────────────────
_AI_VOICE = "그림: 막대그래프이다.\n해상도가 낮아 축의 값은 읽을 수 없습니다."


def test_legacy_entry_is_still_found(cache_dir):
    old = captioner._cache_file(b"img", "image", "옛 프롬프트")
    old.write_text("그림: 옛 캐시본이다.", encoding="utf-8")
    assert captioner._cache_read("caption", _new(), old, "image") == "그림: 옛 캐시본이다."


def test_guard_runs_on_a_cache_hit(cache_dir):
    """★ 히트에도 `_finish`. 옛 캐시본이 새 가드를 비켜 가지 않는다."""
    old = captioner._cache_file(b"img", "image", "옛 프롬프트")
    old.write_text(_AI_VOICE, encoding="utf-8")
    assert captioner._cache_read("caption", _new(), old, "image") == "그림: 막대그래프이다."


def test_guard_runs_on_a_new_entry_too(cache_dir):
    p = _new()
    captioner._cache_write(p, _AI_VOICE, captioner._finish(_AI_VOICE, "image"))
    assert p.read_text(encoding="utf-8") == _AI_VOICE          # 담기는 것은 원응답 raw
    assert captioner._cache_read("caption", p, None, "image") == "그림: 막대그래프이다."


def test_empty_answer_is_not_cached(cache_dir):
    p = _new()
    captioner._cache_write(p, "  ", "")
    assert not p.exists()


def test_miss_is_none(cache_dir):
    assert captioner._cache_read("caption", _new(), None, "image") is None
