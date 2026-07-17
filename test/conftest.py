"""pytest 전역 설정 및 공용 픽스처."""

from __future__ import annotations

import sys
from pathlib import Path

# 프로젝트 루트(AI/)를 sys.path 최상위에 추가
# 모든 테스트 파일에서 `from app.xxx import yyy` 가 동작하도록 한다.
sys.path.insert(0, str(Path(__file__).parent.parent))

# 1×1 흰색 PNG 더미 이미지 (테스트 공용)
DUMMY_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
    b"\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18"
    b"\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


# 단위 테스트는 실 API로 새면 안 된다(2026-07-17: 기본 backend가 anthropic으로 바뀌며
# openai 목(mock) 경로를 벗어나 실호출 5건 발생). 테스트는 목이 있는 openai 경로로 고정.
import os as _os
_os.environ.setdefault("CAPTION_BACKEND", "openai")
_os.environ["ANTHROPIC_API_KEY"] = ""
