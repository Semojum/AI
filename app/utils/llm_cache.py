"""LLM 응답 캐시 — 경로 해석. (재구조화 3-a)

캐시 디렉터리를 **절대경로로** 굳힌다. 종전 `CAPTION_CACHE_DIR` 은 상대경로를 그대로
`Path()` 에 넘겼는데, 러너는 `code/AI` 에서 돌고 서버는 systemd `WorkingDirectory` 에서
돈다. 같은 문자열이 두 자리를 가리켜 **A/B 두 팔이 서로 다른 캐시를 봤다.**
여기서 한 번 풀어 두면 진입점이 달라도 같은 자리를 본다(원장 "진입점마다 검증하라").
"""
from __future__ import annotations

import os
from pathlib import Path

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


def _demo() -> None:
    os.environ["_CACHE_DEMO"] = "storage/x"
    assert resolve_dir("_CACHE_DEMO") == _ROOT / "storage" / "x"
    os.environ["_CACHE_DEMO"] = "/tmp/abs"
    assert resolve_dir("_CACHE_DEMO") == Path("/tmp/abs")
    del os.environ["_CACHE_DEMO"]
    assert resolve_dir("_CACHE_DEMO") is None
    assert resolve_dir("_CACHE_DEMO", "storage/y") == _ROOT / "storage" / "y"
    print("ok")


if __name__ == "__main__":
    _demo()
