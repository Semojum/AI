"""추출을 바꾸는 스위치는 전부 경계 판 지문(`_EXTRACT_ENV`)에 든다 (T39 S5).

MINERU_MATH_FONT_GUARD 가 지문에 없어 운영에서 바꿔도 옛 경계를 재사용했다(eval 09-30 실측: 경계 8쪽 중
4쪽이 바뀌는 스위치). 전수로 보니 캡션을 통째로 끄는 SEMOJUM_NO_CAPTION 등 열여덟이 빠져 있었다.
추출 단계 모듈이 읽는 환경변수는 지문에 넣거나, 아래 표에 **왜 경계와 무관한지** 적어야 한다.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.core import pipeline  # noqa: E402

ROOT = Path(__file__).parents[3]
# 경계 파일(`_extract_with_hyunju` 까지)을 만드는 모듈. 경계 뒤(opt · 점역 · 조판)는 대상이 아니다.
EXTRACT_MODULES = [
    "app/ai/parser/mineru_runner.py", "app/ai/parser/mineru_service.py", "app/ai/parser/figure_detect.py",
    "app/ai/parser/opus_fallback.py", "app/ai/parser/crop_reask.py", "app/ai/parser/extraction_losses.py",
    "app/ai/captioning/captioner.py", "app/ai/captioning/classifier.py", "app/ai/builder/result_builder.py",
    "app/ai/preprocessor/pdf_analyzer.py", "app/ai/preprocessor/line_join.py", "app/ai/gates.py",
    "app/utils/llm_cache.py", "app/core/pipeline.py",
]
# 경계 내용과 무관한 스위치 — 이유를 같이 적는다.
NOT_BOUNDARY = {
    "MINERU_RETRIES": "재시도 횟수(같은 출력)", "MINERU_CLIENT": "MinerU 를 부르는 길(같은 모델)",
    "MINERU_API_URL": "MinerU 서버 주소", "MINERU_API_PORT": "서버 포트", "MINERU_API_LOG_MAX_MB": "로그 크기",
    "MINERU_API_LOG": "로그 경로",
    "MINERU_GPU_MEM_UTIL": "GPU 메모리 몫", "MINERU_LD_LIBRARY_PATH": "라이브러리 경로",
    "MINERU_MAX_RESTARTS": "서버 재기동", "MINERU_PERSISTENT": "서버 상주", "MINERU_RESTART_COOLDOWN": "서버 재기동",
    "MINERU_RESTART_WAIT": "서버 재기동", "PATH": "실행 경로", "CAPTION_CONCURRENCY": "동시 호출 수",
    "LLM_CACHE_DIR": "캐시 자리(같은 응답)", "_CACHE_DEMO": "자체 점검용",
    "BOUNDARY_REUSE": "재사용 스위치 자체(T39 S2)", "MINERU_RAW_REUSE": "재사용 스위치 자체(T39 S3)",
    "READING_ORDER_MODE": "경계 뒤 읽기순서(`_parse_txt_result`)", "READING_ORDER_LLM": "경계 뒤 읽기순서",
    "KEEP_PAGE_IMAGE": "QA 쪽 이미지 보관",
}
_ENV_RE = re.compile(r"""(?:os\.environ\.get|os\.getenv|os\.environ\.setdefault)\(\s*["']([A-Z0-9_]+)["']|os\.environ\[\s*["']([A-Z0-9_]+)["']\s*\]""")


def _env_names(rel: str) -> set[str]:
    return {a or b for a, b in _ENV_RE.findall((ROOT / rel).read_text(encoding="utf-8"))}


@pytest.mark.parametrize("rel", EXTRACT_MODULES)
def test_추출_스위치는_지문에_들거나_무관_사유가_있다(rel):
    missing = sorted(n for n in _env_names(rel) if n not in pipeline._EXTRACT_ENV and n not in NOT_BOUNDARY)
    assert not missing, f"{rel}: 경계 판 지문(_EXTRACT_ENV)에 넣거나 NOT_BOUNDARY 에 사유를 적어라 → {missing}"


def test_S5_수식_글꼴_가드와_캡션_끄기가_지문에_든다(monkeypatch):
    for name in ("MINERU_MATH_FONT_GUARD", "SEMOJUM_NO_CAPTION"):
        monkeypatch.delenv(name, raising=False)
        a = pipeline._extract_env_fp()
        monkeypatch.setenv(name, "0" if name == "MINERU_MATH_FONT_GUARD" else "1")
        assert pipeline._extract_env_fp() != a, name
        monkeypatch.delenv(name)


def test_캡션_키는_값이_아니라_있고_없음만_싣는다(monkeypatch):
    monkeypatch.setattr(pipeline.config, "anthropic_api_key", "sk-a")
    a = pipeline._extract_env_fp()
    monkeypatch.setattr(pipeline.config, "anthropic_api_key", "sk-b")
    assert pipeline._extract_env_fp() == a                      # 값이 바뀌어도 같다
    monkeypatch.setattr(pipeline.config, "anthropic_api_key", "")
    assert pipeline._extract_env_fp() != a                      # 없으면 다르다
