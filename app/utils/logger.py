from __future__ import annotations

import logging
import sys
from functools import lru_cache


def _build_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


@lru_cache
def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_build_formatter())
        logger.addHandler(handler)
    # 자체 핸들러로 출력하므로 루트로 전파하지 않는다(전파 시 루트 핸들러가 한 번 더
    # 찍어 모든 로그가 2번 출력되던 문제 방지).
    logger.propagate = False
    # NOTSET → 루트 로거 레벨을 상속 (setup_root_logging이 DEBUG로 설정하면 DEBUG 출력됨)
    logger.setLevel(logging.NOTSET)
    return logger


# 루트 설정 — main.py에서 1회 호출
def setup_root_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_build_formatter())
        root.addHandler(handler)
    root.setLevel(level)
