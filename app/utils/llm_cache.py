"""LLM 응답 캐시 — 내용주소 저장소(CAS). (재구조화 3-a 경로 · 3-b 저장소)

캐시 디렉터리를 **절대경로로** 굳힌다. 종전 `CAPTION_CACHE_DIR` 은 상대경로를 그대로
`Path()` 에 넘겼는데, 러너는 `code/AI` 에서 돌고 서버는 systemd `WorkingDirectory` 에서
돈다. 같은 문자열이 두 자리를 가리켜 **A/B 두 팔이 서로 다른 캐시를 봤다.**
여기서 한 번 풀어 두면 진입점이 달라도 같은 자리를 본다(원장 "진입점마다 검증하라").
"""
from __future__ import annotations

import contextvars
import hashlib
import os
import re
from pathlib import Path

from app.utils.logger import get_logger

logger = get_logger(__name__)

_ROOT = Path(__file__).resolve().parents[2]      # …/code/AI


def resolve_dir(env_name: str, default: str | None = None) -> Path | None:
    """환경변수의 캐시 경로 → 절대 Path. 값이 없고 기본값도 없으면 None(= 캐시 끔).

    상대경로는 저장소 루트(`code/AI`) 기준으로 푼다. `cwd` 기준이 아니다 — `cwd` 로 풀면
    진입점마다 다른 자리를 보게 되어 고치려던 문제가 그대로 남는다.

    ★ **빈 문자열은 "끔"이다**(재구조화 3-e). 기본값이 생긴 뒤로는 `LLM_CACHE_DIR=` 한 줄이
      되돌리는 길이라, 빈 값을 기본값으로 되돌리면 그 길이 막힌다.
    """
    raw = os.environ.get(env_name)
    if raw is None:
        raw = default
    if not raw:
        return None
    p = Path(raw).expanduser()
    return p if p.is_absolute() else (_ROOT / p).resolve()


# ── 내용주소 저장소 (재구조화 3-b) ────────────────────────────────────────────
# **원응답 raw 만** 담는다. 파싱·가드는 읽을 때 다시 건다(설계 2-3 저장 정책 통일).
# 그래야 가드를 넓혔을 때 캐시에 남은 옛 응답이 그 판정을 비켜 가지 않는다.
#
# 켜는 조건은 `LLM_CACHE_DIR` 하나. 없으면 통째로 꺼진다 — 운영 기본은 지금도 꺼짐이고
# 켜는 것은 3-e 다. 즉 이 단계의 운영 동작 변화는 0 이다.
#
# `LLM_CACHE_MODE`
#   rw(기본) 읽고 쓴다 · ro 읽기만, **미스면 예외** · off 끔
#   ★ ro 는 "이 팔에서 외부 호출 0" 을 강제하는 장치다. 미스를 조용히 호출로 흘리면
#     A/B 두 팔의 조건이 갈린다. 부르는 쪽은 예외를 이미 잡아 규칙 경로로 되돌린다.


class CacheMiss(RuntimeError):
    """`LLM_CACHE_MODE=ro` 인데 캐시에 없다. 부르는 쪽이 잡아 규칙 경로로 간다."""


# ── 격리 열쇠 (재구조화 3-e · 대표 결재 2026-09-08 "(B) 고객별 격리") ─────────
# > "운영 서버는 B가 맞아. 같은 책을 다른 유저가 올리면 따로 계산하는 게 맞지."
#
# 그래서 열쇠는 **내용 해시만으로는 안 된다.** 내용 해시만 쓰면 같은 교과서를 올린 두 고객이
# 서로의 캡션·회수·순서 응답을 나눠 쓴다 — 결재와 정반대다.
#
# ⚠ **AI 서버에는 고객 식별자가 안 들어온다**(2026-09-08 진입점 실측).
#   `braille_service.proto` `BrailleRequest` = job_id·page_no·total_pages·pdf_data·mode·
#   source_text·advanced_ai 일곱뿐이고, gRPC 메타데이터도 안 읽는다(`grpc_server.py`).
#   그래서 지금 쓸 수 있는 **가장 고운 격리 단위가 `job_id`** 다. job 격리는 고객 격리보다
#   좁으므로 결재를 어기지 않는다(고객 사이에 절대 안 샌다).
#   ※ 한때 `customer_id`(필드 8)를 받았는데 **되돌렸다**(#788, 대표 지시). 그 필드가 이득을
#     주는 경우는 같은 고객이 같은 책을 **다른 job_id 로** 다시 올릴 때 하나뿐인데, BE 가
#     업로드마다 새 job_id 를 발급하는지를 확인하지 않고 계약부터 늘렸다. 번호 8 은
#     `reserved` 로 비워 뒀다 — "새로 발급한다" 는 답이 오면 그때 되살린다.
#
# ★ 비어 있으면 **캐시를 끈다**(fail closed). 컨텍스트가 스레드로 안 넘어간 자리에서
#   조용히 격리 없는 열쇠를 쓰느니, 그 자리만 캐시를 안 쓰는 쪽이 안전하다.
_scope: contextvars.ContextVar[str] = contextvars.ContextVar("llm_cache_scope", default="")


def set_scope(value: str) -> None:
    """이 요청의 격리 열쇠를 건다. 파이프라인 진입점(`pipeline.run`)이 부른다."""
    _scope.set((value or "").strip())


def scope() -> str:
    """지금 걸린 격리 열쇠. 비면 캐시를 안 쓴다."""
    return _scope.get()


def _mode() -> str:
    return os.environ.get("LLM_CACHE_MODE", "rw").strip().lower()


def root() -> Path | None:
    """`cas/llm` 뿌리. `LLM_CACHE_DIR` 이 **빈 값**이면 None = 캐시 끔.

    ★ 기본값은 `Settings.llm_cache_dir`(재구조화 3-e, 운영 기본 켬)에서 온다. 되돌리는 길은
      `.env` 에 `LLM_CACHE_DIR=` 한 줄이다.
    """
    from app.core.config import config      # 지연 import — 모듈 최상단이면 순환이다
    d = resolve_dir("LLM_CACHE_DIR", config.llm_cache_dir)
    return (d / "cas" / "llm") if d else None


def key(*parts: str | bytes) -> str:
    """내용주소. 길이를 앞에 붙여 이어 붙이기 모호성을 없앤다.

    ⚠ 요소 목록을 직렬화해 키로 쓰면 안 된다 — `element_id` 가 uuid4 라 다른 job 은
      **항상 미스**다. 프롬프트 문자열처럼 내용만 든 것으로 잡는다(설계 2-3 깨뜨리기 #4).

    ★ 맨 앞에 **격리 열쇠**가 붙는다(3-e). 그래서 같은 내용이라도 다른 고객(지금은 다른 job)
      이면 다른 열쇠다.
    """
    h = hashlib.sha256()
    for part in (_scope.get(), *parts):
        b = part if isinstance(part, bytes) else str(part).encode()
        h.update(len(b).to_bytes(8, "big"))
        h.update(b)
    return h.hexdigest()


# ── 프롬프트 판 번호 (재구조화 3-c) ───────────────────────────────────────────
# 열쇠 = `sha256(kind | 입력 | 모델 | prompt_id | 판 번호)`. 프롬프트 **전문은 키에서 뺀다** —
# 전문 키면 문안을 한 글자만 손봐도 전량 미스라 프롬프트 정리(S2)를 아예 못 한다.
# 대신 문안을 고친 사람이 여기 번호를 올린다. 안 올리면 지문 게이트가 경고를 낸다.
#
# ★★ 이 표의 값은 **열쇠를 만드는 자리 밖으로 나가지 않는다.**
#     `key_for()` 안에서만 읽는다. **프롬프트 문자열에 절대 넣지 마라.** 모델이 번호를 보면
#     캡션에 그대로 따라 쓴다 — 2026-09-07 에 프롬프트 문구가 점자로 나간 것과 같은 부류다.
#     못 본 것은 따라 쓸 수도 없다. 어기면 `test_prompt_ver_leak.py` 가 빨간불을 낸다.
PROMPT_VER = {
    "caption": 4,      # app/ai/captioning/captioner.py  _COMMON·_PROMPTS
                       #   (4: 세부 줄 — 두 칸 들여쓴 관측 한 줄 #808)
    "classify": 1,     # app/ai/captioning/classifier.py SYSTEM_PROMPT
    "subtype": 2,      # app/ai/captioning/classifier.py _SUBTYPE_PROMPT
                       #   (1: #784 §6.6 세분류 · 2: §6.6.7 화면 이미지 제거 #793)
    "figure": 1,       # app/ai/parser/figure_detect.py  _ASK
    "order": 1,        # app/ai/parser/llm_order.py      _SYS
    "visual": 1,       # app/ai/llm/visual_drafts.py
    "opus": 1,         # app/ai/parser/opus_fallback.py
    "text": 3,         # app/ai/llm/text_opt.py  (3: 본문 OCR 교정 프롬프트 삭제 #788)
    "formula": 1,      # app/ai/llm/formula_opt.py
    "table": 1,        # app/ai/llm/table_opt.py
}

# 지문 게이트(3-c). 위 판 번호가 **어느 문안에 대한 번호였는지** 적어 둔다.
# 문안을 고치고 번호를 안 올리면 `/health` 가 경고한다(`health_check.prompt_ver_drift`).
# 번호를 올릴 때 여기 값도 새 값으로 적는다 — 값은 `prompt_sha_by_kind()` 가 준다.
# ⚠ `_PROMPT_SOURCES` 가 여섯 자리라 게이트도 여섯이다. classify·figure·order 는
#    프롬프트가 그 모듈 안에만 있어 지문 대상이 아니다(0-c 결정).
PROMPT_SHA = {
    "caption": "3b81b8beb97e",
    "visual": "3fb25cd311f8",
    "opus": "41bba1c2b41d",
    "text": "baa6a31f4221",
    "formula": "d831be6fa57a",
    "table": "347b251a5e77",
}

# 판 번호가 **글로 샜을 때**의 꼴. `#pv3#` — 교과서 본문·캡션에 나올 수 없는 모양으로 잡았다.
# 맨 숫자(`3`)나 `v3` 로 잡으면 본문의 평범한 숫자를 먹는다. 가드5 가 이 꼴만 지운다.
VER_TAG_RE = re.compile(r"#pv\d{1,4}#")


def ver_tag(kind: str) -> str:
    """판 번호의 **유일한** 글 꼴. 로그·지문 표시용이지 프롬프트용이 아니다."""
    return f"#pv{PROMPT_VER.get(kind, 0)}#"


def strip_ver_tags(text: str) -> str:
    """혹시라도 샌 판 번호를 걷는다(가드5 셋째 겹). 그 꼴만 지우고 글자는 남긴다."""
    return VER_TAG_RE.sub("", text) if text else text


def key_for(kind: str, *parts: str | bytes) -> str:
    """열쇠. **판 번호는 이 함수 안에서만 붙는다** — 부르는 쪽은 번호를 보지 않는다.

    parts 는 설계 §2-3 의 `input_sha | model | prompt_id` 순서로 준다.
    """
    return key(kind, *parts, str(PROMPT_VER.get(kind, 0)))


def _path(kind: str, k: str) -> Path | None:
    if not _scope.get():        # 격리 열쇠가 없으면 안 쓴다(3-e, fail closed)
        return None
    r = root()
    return (r / kind / f"{k}.txt") if r else None


def get(kind: str, k: str) -> str | None:
    """원응답 raw. 없으면 None(ro 모드면 `CacheMiss`)."""
    p = _path(kind, k)
    if p is None or _mode() == "off":
        return None
    hit = p.exists()
    from app.utils.req_log import record_cache
    record_cache(kind, hit)
    if hit:
        return p.read_text(encoding="utf-8")
    if _mode() == "ro":
        raise CacheMiss(f"{kind} 캐시 미스 · LLM_CACHE_MODE=ro (key={k[:12]})")
    return None


def put(kind: str, k: str, text: str) -> None:
    """원응답 raw 저장. ro·off·꺼짐이면 아무것도 안 한다. 실패해도 쪽은 나가야 한다."""
    p = _path(kind, k)
    if p is None or _mode() != "rw":
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")          # 같은 쪽을 두 프로세스가 돌아도 반쪽 파일이 안 남는다
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(p)
    except OSError as exc:
        logger.warning("LLM 캐시 저장 실패(진행): %s", exc)


def _demo() -> None:
    os.environ["_CACHE_DEMO"] = "storage/x"
    assert resolve_dir("_CACHE_DEMO") == _ROOT / "storage" / "x"
    os.environ["_CACHE_DEMO"] = "/tmp/abs"
    assert resolve_dir("_CACHE_DEMO") == Path("/tmp/abs")
    del os.environ["_CACHE_DEMO"]
    assert resolve_dir("_CACHE_DEMO") is None
    assert resolve_dir("_CACHE_DEMO", "storage/y") == _ROOT / "storage" / "y"

    import tempfile
    with tempfile.TemporaryDirectory() as d:
        os.environ["LLM_CACHE_DIR"] = ""                            # 빈 값 = 끔(되돌리는 길)
        os.environ.pop("LLM_CACHE_MODE", None)
        set_scope("job1")
        assert get("order", key("a")) is None and root() is None
        os.environ["LLM_CACHE_DIR"] = d

        # 격리 — 열쇠가 없으면 캐시를 안 쓰고, 열쇠가 다르면 다른 자리다
        set_scope("")
        assert _path("order", key("a")) is None
        set_scope("job1")
        k1 = key("order", "같은입력")
        set_scope("job2")
        assert key("order", "같은입력") != k1                        # 다른 고객 = 다른 열쇠
        set_scope("job1")

        k = key("order", "m", "sys", "prompt")
        assert get("order", k) is None
        put("order", k, '{"order": [1, 0]}')
        assert get("order", k) == '{"order": [1, 0]}'
        os.environ["LLM_CACHE_MODE"] = "ro"
        put("order", key("other"), "x")                            # ro 는 안 쓴다
        assert get("order", k) == '{"order": [1, 0]}'
        try:
            get("order", key("other"))
            raise AssertionError("ro 미스는 CacheMiss 여야 한다")
        except CacheMiss:
            pass
        os.environ["LLM_CACHE_MODE"] = "off"
        assert get("order", k) is None                              # off 는 적중도 안 준다
        os.environ.pop("LLM_CACHE_MODE"), os.environ.pop("LLM_CACHE_DIR")
        set_scope("")
    print("ok")


if __name__ == "__main__":
    _demo()
