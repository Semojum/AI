"""프롬프트 판 번호가 앱 출력으로 새지 않는다 (재구조화 3-c · 대표 조건).

판 번호가 점자나 캡션에 섞여 나가면 "AI 프롬프트 문구가 출력에 껴 있음"과 같은 부류의
결함이다. 세 겹으로 막는다. 이 파일은 **둘째 겹**이고, 첫째·셋째 겹도 여기서 확인한다.

  ① 구조적 — 판 번호는 `llm_cache.key_for()` 안에서만 산다. 프롬프트 모듈은 표를 아예
     안 본다. 모델이 못 본 것은 따라 쓸 수도 없다.                → `test_prompt_modules_*`
  ② 테스트 — 프롬프트 문자열 여섯에 판 번호 꼴이 없다.            → `test_no_ver_tag_*`
  ③ 가드5 — `_strip_ai_voice` 가 ①② 를 뚫은 번호를 걷는다.       → `test_guard5_*`

★ 검사가 **실제로 잡는지** 를 같이 못 박는다(양성 대조). 검사만 있고 안 잡히면 없느니만
  못하다 — 나중에 누가 "디버깅 편하게" 번호를 끼워 넣었을 때 조용히 초록이 된다.
"""
import re
from pathlib import Path

import pytest

from app.core.health_check import _module_prompt_bytes, _PROMPT_SOURCES
from app.utils import llm_cache

# 프롬프트를 품은 모듈 전부. 여섯(_PROMPT_SOURCES) + 지문 대상이 아닌 셋.
_MODULES = [name for _, name in _PROMPT_SOURCES] + [
    "app.ai.captioning.classifier",
    "app.ai.parser.figure_detect",
    "app.ai.parser.llm_order",
]
_ROOT = Path(llm_cache.__file__).resolve().parents[2]


def _src(mod_name: str) -> str:
    return (_ROOT / (mod_name.replace(".", "/") + ".py")).read_text(encoding="utf-8")


# ── ① 구조적 차단 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("mod_name", _MODULES)
def test_prompt_modules_never_read_the_version_table(mod_name):
    """프롬프트 모듈은 판 번호 표를 읽지 않는다.

    맨 숫자(`f"판 {PROMPT_VER['caption']}"`)로 새는 길은 태그 검사로는 못 잡는다.
    표를 아예 안 보게 하는 것이 그 길을 막는 유일한 방법이다.
    """
    src = _src(mod_name)
    for banned in ("PROMPT_VER", "ver_tag", "PROMPT_SHA"):
        assert banned not in src, (
            f"{mod_name} 이 판 번호({banned})를 본다. 번호는 `llm_cache.key_for()` "
            f"안에서만 산다 — 키가 필요하면 kind 만 넘겨라.")


def test_key_for_folds_the_version_without_exposing_it():
    """열쇠에는 번호가 들어가고(판을 올리면 키가 갈린다), 부르는 쪽은 번호를 안 본다."""
    a = llm_cache.key_for("caption", "sha", "model", "image")
    llm_cache.PROMPT_VER["caption"] += 1
    try:
        b = llm_cache.key_for("caption", "sha", "model", "image")
    finally:
        llm_cache.PROMPT_VER["caption"] -= 1
    assert a != b
    assert a == llm_cache.key_for("caption", "sha", "model", "image")


# ── ② 프롬프트 문자열에 판 번호 꼴이 없다 ────────────────────────────────────
@pytest.mark.parametrize("mod_name", _MODULES)
def test_no_ver_tag_in_prompt_strings(mod_name):
    found = llm_cache.VER_TAG_RE.findall(_module_prompt_bytes(mod_name).decode(errors="replace"))
    assert not found, f"{mod_name} 프롬프트에 판 번호가 있다: {found}"


@pytest.mark.parametrize("mod_name", _MODULES)
def test_no_ver_tag_anywhere_in_prompt_module_source(mod_name):
    """상수 이름에 PROMPT 가 안 붙은 문자열로 새는 길까지 막는다(파일 전문 검사)."""
    found = llm_cache.VER_TAG_RE.findall(_src(mod_name))
    assert not found, f"{mod_name} 안에 판 번호 꼴이 있다: {found}"


def test_the_check_actually_catches_a_planted_version():
    """★ 양성 대조. 일부러 끼워 넣은 번호를 검사가 잡는가.

    실제 프롬프트에 넣어 확인한 것과 같은 자리(`_COMMON` 꼴의 문자열)를 흉내낸다.
    """
    planted = "당신은 교과서 그림을 설명한다. (프롬프트 " + llm_cache.ver_tag("caption") + ")"
    assert llm_cache.VER_TAG_RE.findall(planted), "검사가 심어 둔 판 번호를 못 잡는다"
    assert "PROMPT_VER" in "prompt += f'{PROMPT_VER[\"caption\"]}'"   # ① 쪽 양성 대조


# ── ③ 가드5 는 판 번호만 걷고 본문 숫자는 안 건드린다 ────────────────────────
def test_guard5_strips_the_tag_and_keeps_the_sentence():
    from app.ai.captioning.captioner import _strip_ai_voice
    assert _strip_ai_voice("그림: 막대그래프이다. #pv1#") == "그림: 막대그래프이다."
    assert _strip_ai_voice("#pv12#\n그림: 두 번째 줄") == "그림: 두 번째 줄"


@pytest.mark.parametrize("text", [
    "그림: 2026년 국내 총생산 그래프이다.",
    "그림: 항목 #3# 과 #1# 을 견준 표이다.",
    "그림: pv1 단자와 pv2 단자를 이은 회로도이다.",
    "만화: 학생이 '#해시태그' 를 말한다.",
    "그림: 압력-부피(PV) 곡선이다.",
])
def test_guard5_does_not_touch_ordinary_text(text):
    """오차단 방지. 판 번호 꼴은 본문에 나올 수 없는 모양이어야 한다.

    전수 확인은 따로 했다 — 캐시 3,242건 전량에 걸어 바뀐 건수 0(2026-09-08).
    """
    from app.ai.captioning.captioner import _strip_ai_voice
    assert _strip_ai_voice(text) == text


def test_ver_tag_regex_is_narrow():
    """맨 숫자·`v3`·`판 3` 은 안 잡는다(잡으면 본문을 먹는다)."""
    for benign in ("3", "v3", "판 3", "pv3", "#3#", "#pv#", "#pv12345#"):
        assert not re.fullmatch(r".*" + llm_cache.VER_TAG_RE.pattern + r".*", benign), benign
