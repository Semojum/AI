from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
from functools import lru_cache
from pathlib import Path

# ── 로그 파일 (T2, 2026-08-23) ──────────────────────────────────────────────
# 종전에는 stdout 핸들러 하나뿐이라 **서버를 재시작하면 이전 로그가 사라졌다.**
# tmux 스크롤백이 유일한 기록이었다. 두 갈래로 남긴다.
#   · `semojum.log`      사람이 읽는 것. 터미널에 뜨는 그 형식 그대로.
#   · `semojum.jsonl`    기계가 읽는 것. 관리자 웹이 파싱한다(한 줄 = 한 레코드).
# stdout 은 **그대로 둔다** — 사람이 터미널로 보는 경로를 없애지 않는다.
#
# ★ 로그가 파이프라인을 죽이면 안 된다(`req_log._never_raises` 와 같은 원칙).
#   파일을 못 열면 stdout 만으로 계속 간다.
_LOG_DIR = Path(os.getenv("SEMOJUM_LOG_DIR", "storage/logs"))
_LOG_MAX_BYTES = int(os.getenv("SEMOJUM_LOG_MAX_BYTES", 20 * 1024 * 1024))   # 20MB
_LOG_BACKUPS = int(os.getenv("SEMOJUM_LOG_BACKUPS", 5))                      # 총 120MB 상한
_TEXT_FILE = "semojum.log"
_JSON_FILE = "semojum.jsonl"


def _build_formatter() -> logging.Formatter:
    return logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


class _JsonFormatter(logging.Formatter):
    """한 줄 = 한 레코드. 관리자 웹이 파싱한다.

    사람용 텍스트와 **같은 줄에 욱여넣지 않는다** — 파일을 따로 낸다.
    `job_id`·`page`·`stage`·`ms`·`code` 는 호출부가 `extra=` 로 실으면 그대로 나간다
    (`req_log` 가 이미 들고 있는 값들이다). 없으면 필드가 빠질 뿐 줄은 나간다.
    ⚠ 파일 내용·개인정보는 싣지 않는다. 식별자와 수치까지다.
    """

    _EXTRA = ("job_id", "page", "stage", "ms", "code", "status", "guard", "iou", "std")

    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for k in self._EXTRA:
            v = getattr(record, k, None)
            if v is not None:
                out[k] = v
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)[-800:]
        return json.dumps(out, ensure_ascii=False)


@lru_cache(maxsize=1)
def _file_handlers() -> tuple[logging.Handler, ...]:
    """회전 파일 핸들러 둘. 한 번만 만든다. 못 만들면 빈 튜플(= stdout 만)."""
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        text = logging.handlers.RotatingFileHandler(
            _LOG_DIR / _TEXT_FILE, maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUPS, encoding="utf-8")
        text.setFormatter(_build_formatter())
        text.setLevel(logging.INFO)
        js = logging.handlers.RotatingFileHandler(
            _LOG_DIR / _JSON_FILE, maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUPS, encoding="utf-8")
        js.setFormatter(_JsonFormatter())
        js.setLevel(logging.INFO)
        # ★ 루트에도 붙인다(T2, 2026-08-24). `get_logger` 를 안 거치고
        #   `logging.getLogger(__name__)` 를 직접 쓰는 모듈이 있다(translator·layout_braille·
        #   isolation·opus_fallback). 그 로거들은 전파로만 나가므로 루트에 핸들러가 없으면
        #   **파일에 한 줄도 안 남는다** — 서버는 `main.py` 가 `setup_root_logging` 을 부르니
        #   가려졌고, 러너로 검증하자 드러났다.
        #   ⚠ 중복 기록은 없다 — `get_logger` 가 만든 로거는 `propagate=False` 라 루트로 안 간다.
        root = logging.getLogger()
        if not any(getattr(h, "_semojum_file", False) for h in root.handlers):
            for h in (text, js):
                h._semojum_file = True          # 재부착 방지 표시
                root.addHandler(h)
            if root.level == logging.NOTSET or root.level > logging.INFO:
                root.setLevel(logging.INFO)     # 핸들러가 INFO 를 받게. 화면은 각 핸들러 레벨이 가른다
        return (text, js)
    except Exception as exc:  # noqa: BLE001 — 로그가 서버를 죽이면 안 된다
        print(f"[logger] 파일 기록 비활성(stdout 만 씁니다): {exc}", file=sys.stderr)
        return ()


@lru_cache
def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_build_formatter())
        # 화면은 종전대로 — 루트 레벨을 따른다(러너에서는 WARNING 위만 뜬다).
        handler.setLevel(logging.getLogger().level or logging.WARNING)
        logger.addHandler(handler)
        for h in _file_handlers():
            logger.addHandler(h)
    # 자체 핸들러로 출력하므로 루트로 전파하지 않는다(전파 시 루트 핸들러가 한 번 더
    # 찍어 모든 로그가 2번 출력되던 문제 방지).
    logger.propagate = False
    # ★ 파일에는 INFO 부터 남긴다(T2, 2026-08-24).
    #   종전에는 NOTSET 이라 실효 레벨을 루트에서 물려받았고, 파이썬 루트 기본이 WARNING 이다.
    #   `setup_root_logging(INFO)` 를 부르는 곳은 `app/core/main.py` 하나뿐이라 **서버로 뜰 때만**
    #   INFO 가 켜졌다. 코퍼스 러너처럼 그걸 안 부르는 진입점에서는 단계·요청 로그(전부 INFO)가
    #   **로거 단계에서 통째로 버려졌다** — 실측: 2쪽 실행에 남은 4줄이 전부 WARNING 이었다.
    #   그래서 **로거 레벨을 INFO 로 내리고**, 화면이 시끄러워지지 않게 **stdout 핸들러만**
    #   종전 동작(루트 레벨을 따름)을 유지한다. 파일은 조용히 다 받는다 — 저장이 목적이다.
    logger.setLevel(logging.INFO)
    return logger


# 루트 설정 — main.py에서 1회 호출
def setup_root_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_build_formatter())
        root.addHandler(handler)
        for h in _file_handlers():
            root.addHandler(h)
    root.setLevel(level)
