"""PART 10 — 점자 조판 (텍스트 전용, 단계 2).

BrailleOutput 목록 → 32칸 × 25줄 페이지 조판 → 파일 저장.

§2.1.1: 32칸 줄바꿈, 25줄 페이지 넘김
§2.1.2: ⠼N⠲ 페이지 번호 우측 정렬 (25번째 줄)
"""

from __future__ import annotations

from pathlib import Path

from app.ai.braille.kor_math_rules import _NUMBER_INDICATOR, _DIGIT_MAP
from app.schemas.content import BrailleOutput

_COLS = 32
_ROWS = 25


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
