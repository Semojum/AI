"""PART 10 — 점자 조판 (텍스트 전용, 단계 2).

BrailleOutput 목록 → 32칸 × 25줄 페이지 조판 → 파일 저장.

§2.1.1: 32칸 줄바꿈, 25줄 페이지 넘김
§2.1.2: ⠼N⠲ 페이지 번호 우측 정렬 (25번째 줄)
§2.1.3: 원본 페이지 번호 없음 ⠒⠒, 페이지 변경선 ⠨⠂
§2.4.2: 단형 들여쓰기 (1/3/5칸)
§2.4.6: 밑줄 빈칸 ⠒⠂
§2.4.9: 출전 3칸 들여쓰기
§2.5.5: 글머리 기호 위계별 점형 (⠿⠒/⠿⠄/⠤)
"""

from __future__ import annotations

import re
from pathlib import Path

from app.ai.braille.kor_math_rules import _NUMBER_INDICATOR, _DIGIT_MAP
from app.schemas.content import BrailleOutput

_COLS = 32
_ROWS = 25

# ── §2.1.3 원본 페이지 표기 ────────────────────────────────────────────────
_NO_PAGE_MARKER = "⠒⠒"
_PAGE_CHANGE_MARKER = "⠨⠂"

# ── §2.4.2 단형 들여쓰기 ──────────────────────────────────────────────────
_NUMBERED_INDENT: dict[int, int] = {1: 1, 2: 3, 3: 5}

# ── §2.4.6 빈칸 ───────────────────────────────────────────────────────────
_UNDERLINE_BLANK_MARKER = "⠒⠂"

# ── §2.5.5 글머리 기호 ────────────────────────────────────────────────────
_BULLET_MARKERS: dict[int, str] = {1: "⠿⠒", 2: "⠿⠄", 3: "⠤"}


def format_no_page_marker() -> str:
    """원본 페이지 번호가 없을 때 사용하는 ⠒⠒ 마커 (§2.1.3)."""
    return _NO_PAGE_MARKER


def format_page_change_marker() -> str:
    """원본 페이지 변경선 ⠨⠂ — 길이·위치와 무관하게 항상 1개 (§2.4.5)."""
    return _PAGE_CHANGE_MARKER


def format_underline_blank(text: str) -> str:
    """밑줄 빈칸(_+)을 ⠒⠂ 1개로 치환 — 길이 무관 (§2.4.6)."""
    return re.sub(r"_+", _UNDERLINE_BLANK_MARKER, text)


def format_citation(text: str) -> str:
    """출전 정보를 다음 줄 3칸에 배치 (§2.4.9)."""
    return " " * 3 + text


def indent_numbered_item(text: str, level: int) -> str:
    """단형 들여쓰기: level 1→1칸, 2→3칸, 3+→5칸 (§2.4.2)."""
    indent = _NUMBERED_INDENT.get(min(level, 3), 5)
    return " " * indent + text


def format_bullet_item(text: str, tier: int) -> str:
    """글머리 기호: tier 1→⠿⠒, 2→⠿⠄, 3→⠤, 기호 뒤 1칸 (§2.5.5)."""
    marker = _BULLET_MARKERS.get(min(tier, 3), _BULLET_MARKERS[3])
    return f"{marker} {text}"


def _page_number_braille(n: int) -> str:
    digits = "".join(_DIGIT_MAP.get(c, c) for c in str(n))
    return f"{_NUMBER_INDICATOR}{digits}⠲"


def _right_align(text: str, width: int) -> str:
    pad = max(0, width - len(text))
    return " " * pad + text


class LayoutBraille:
    """BrailleOutput 목록 → 32칸 × 25줄 조판."""

    def layout(
        self,
        braille_outputs: list[BrailleOutput],
        page_no: int,
        job_id: str,
    ) -> list[str]:
        """조판 후 파일 저장, 전체 줄 목록 반환."""
        all_lines: list[str] = []
        for bo in braille_outputs:
            all_lines.extend(bo.braille_lines)

        pages = self._paginate(all_lines, page_no)
        self._save(pages, job_id, page_no)

        result: list[str] = []
        for page in pages:
            result.extend(page)
        return result

    def _paginate(self, lines: list[str], first_page_no: int) -> list[list[str]]:
        pages: list[list[str]] = []
        pno = first_page_no
        i = 0
        total = len(lines)

        while i < total or not pages:
            content = lines[i : i + _ROWS - 1]
            i += len(content)
            while len(content) < _ROWS - 1:
                content.append("")
            pn = _right_align(_page_number_braille(pno), _COLS)
            content.append(pn)
            pages.append(content)
            pno += 1
            if i >= total:
                break

        return pages

    def _save(self, pages: list[list[str]], job_id: str, page_no: int) -> None:
        result_dir = Path(f"storage/jobs/{job_id}/temp/page_{page_no:03d}/result")
        result_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"{page_no:03d}"
        body = "\n".join(line for page in pages for line in page)
        (result_dir / f"{prefix}_result.txt").write_text(body, encoding="utf-8")
        (result_dir / f"{prefix}_result.brf").write_text(body, encoding="utf-8")
