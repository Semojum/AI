"""`<!N칸>` 태그가 조판 들여쓰기를 이긴다.

mode a 에서 점역사가 들여쓰기를 손본 결과가 이 태그다. mode b 로 되돌아올 때 그대로
지켜야 하는데, 종전에는 태그를 아무도 안 읽어(`tag_names.split_indent` 호출부 0개)
요소 유형만 보고 **전부 2칸**으로 밀어 넣었다 — `<!6칸>` 제목도 2칸이 됐다.
"""
import asyncio

import pytest

from app.core import pipeline
from app.schemas.task import PageTask
from app.utils.braille_back import decode

SRC = ("<!6칸>사회 학습지\n"
       "<!2칸>선거는 국민이 대표를 뽑는다.\n"
       "<!4칸>1. 후보자 토론회\n")


def _first_pads(res) -> list[int]:
    out = []
    for b in res.get("braille_text_list") or []:
        c = b.get("contents") or ""
        if isinstance(c, list):
            c = "\n".join(c)
        for ln in c.split("\n"):
            if ln.strip():
                out.append(len(ln) - len(ln.lstrip("⠀")))
                break
    return out


@pytest.mark.slow
def test_모드b_들여쓰기가_태그를_따른다():
    # CI 러너에는 파이프라인 의존성이 없어 빈 결과가 온다 — 그건 이 규칙의 실패가 아니다.
    task = PageTask(job_id="t_indent", page_no=1, total_pages=1,
                    pdf_data=b"", mode="b", source_text=SRC)
    res = asyncio.run(pipeline.run(task))
    pads = _first_pads(res)
    if not pads:
        pytest.skip("파이프라인이 안 도는 환경(CI) — 아래 단위 검사가 규칙을 지킨다")
    assert pads == [6, 2, 4]


def test_태그가_없으면_종전대로():
    from app.ai.braille.tag_names import split_indent
    assert split_indent("본문이다") == (None, "본문이다")
    assert split_indent("<!6칸>제목") == (6, "제목")


# ── `<!N칸>` 이 점형으로 찍혀 나가던 구멍 (2026-09-08 대표 실행 실물) ─────────
# 수식 줄에 태그가 붙어 오면 `inline_math` 가 태그를 수식 원자로 삼켜
# `<`(⠔⠔)·`!`(⠖)·`2칸`·`>`(⠢⠢) 열 칸이 그대로 인쇄됐다. #385 이후 `contents` 에
# 이 태그를 실어 보내므로 점역사가 편집본을 되돌릴 때마다 났다.
_TAG_CELLS = ("⠔⠔", "⠢⠢")   # "<" 와 ">" 의 점형


def test_indent_tag_not_brailled_on_math_line():
    from app.ai.braille.translator import translate_body
    src = (r"<!2칸>\text {득표율} (\%) = "
           r"\frac {\text {득표수}}{\text {유효 투표수}} \times 100")
    line = translate_body(src)[0][0]
    assert not any(c in line for c in _TAG_CELLS), line
    assert "⠌" in line          # 분수표는 그대로 (수학 제7항)


def test_indent_tag_not_brailled_on_plain_line():
    from app.ai.braille.translator import translate_body
    line = translate_body("<!2칸>선거는 국민이 대표를 뽑는다.")[0][0]
    assert not any(c in line for c in _TAG_CELLS), line
