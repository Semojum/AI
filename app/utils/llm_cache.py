"""LLM 응답 캐시 — 내용주소 저장소(CAS). (재구조화 3-a 경로 · 3-b 저장소)

캐시 디렉터리를 **절대경로로** 굳힌다. 종전 `CAPTION_CACHE_DIR` 은 상대경로를 그대로
`Path()` 에 넘겼는데, 러너는 `code/AI` 에서 돌고 서버는 systemd `WorkingDirectory` 에서
돈다. 같은 문자열이 두 자리를 가리켜 **A/B 두 팔이 서로 다른 캐시를 봤다.**
여기서 한 번 풀어 두면 진입점이 달라도 같은 자리를 본다(원장 "진입점마다 검증하라").
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from app.utils.logger import get_logger

logger = get_logger(__name__)

_ROOT = Path(__file__).resolve().parents[2]      # …/code/AI


def resolve_dir(env_name: str, default: str | None = None) -> Path | None:
    """환경변수의 캐시 경로 → 절대 Path. 값이 없고 기본값도 없으면 None(= 캐시 끔).

    상대경로는 저장소 루트(`code/AI`) 기준으로 푼다. `cwd` 기준이 아니다 — `cwd` 로 풀면
    진입점마다 다른 자리를 보게 되어 고치려던 문제가 그대로 남는다.
    """
    raw = os.environ.get(env_name) or default
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


def _mode() -> str:
    return os.environ.get("LLM_CACHE_MODE", "rw").strip().lower()


def root() -> Path | None:
    """`cas/llm` 뿌리. `LLM_CACHE_DIR` 이 없으면 None = 캐시 끔."""
    d = resolve_dir("LLM_CACHE_DIR")
    return (d / "cas" / "llm") if d else None


def key(*parts: str | bytes) -> str:
    """내용주소. 길이를 앞에 붙여 이어 붙이기 모호성을 없앤다.

    ⚠ 요소 목록을 직렬화해 키로 쓰면 안 된다 — `element_id` 가 uuid4 라 다른 job 은
      **항상 미스**다. 프롬프트 문자열처럼 내용만 든 것으로 잡는다(설계 2-3 깨뜨리기 #4).
    """
    h = hashlib.sha256()
    for part in parts:
        b = part if isinstance(part, bytes) else str(part).encode()
        h.update(len(b).to_bytes(8, "big"))
        h.update(b)
    return h.hexdigest()


def _path(kind: str, k: str) -> Path | None:
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
        os.environ.pop("LLM_CACHE_DIR", None)
        os.environ.pop("LLM_CACHE_MODE", None)
        assert get("order", key("a")) is None and root() is None   # 안 켜면 아무 일도 없다
        os.environ["LLM_CACHE_DIR"] = d
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
    print("ok")


if __name__ == "__main__":
    _demo()
