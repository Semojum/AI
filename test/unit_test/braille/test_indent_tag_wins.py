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
    task = PageTask(job_id="t_indent", page_no=1, total_pages=1,
                    pdf_data=b"", mode="b", source_text=SRC)
    res = asyncio.run(pipeline.run(task))
    assert _first_pads(res) == [6, 2, 4]


def test_태그가_없으면_종전대로():
    from app.ai.braille.tag_names import split_indent
    assert split_indent("본문이다") == (None, "본문이다")
    assert split_indent("<!6칸>제목") == (6, "제목")
