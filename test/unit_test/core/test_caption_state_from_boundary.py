"""응답의 캡션 상태 표시(`processing_meta.caption_disabled`)는 **경계를 뜰 때의 상태**를 옮긴다.

종전에는 요청 때 env(`SEMOJUM_NO_CAPTION`)를 찍었다. 경계를 재사용·복사하면 env 와 내용이 갈린다 —
arm.py 라운드 108곳에서 캡션이 든 d8c 경계로 낸 응답에 True 가 찍혔다(code 2026-09-30 S5 점검).
표시를 읽는 순간 거꾸로 판정한다. 모르면 '모름'(None)이다 — 거짓 표시가 표시 없음보다 나쁘다.
"""
import asyncio
import sys
from pathlib import Path

import fitz
import pytest

from app.core import pipeline
from app.core.grpc_server import _dict_to_processing_meta
from app.schemas.layout import LayoutResult
from app.schemas.task import PageTask


def _pdf() -> bytes:
    d = fitz.open(); pg = d.new_page()
    for i in range(12):
        pg.insert_text((72, 72 + 18 * i), f"Line {i}: plain text layer for a zero tier page.")
    return d.tobytes()


@pytest.mark.parametrize("env, want", [("1", True), ("", False)])
def test_경계_meta_에_뜰_때의_캡션_상태가_남는다(monkeypatch, tmp_path, env, want):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SEMOJUM_NO_CAPTION", env)
    task = PageTask(job_id="capstate", page_no=1, total_pages=1, mode="a", pdf_data=_pdf())
    _, extraction = asyncio.run(pipeline._extract_with_hyunju(task))
    assert extraction["meta"]["caption_disabled"] is want


def _response(**kw):
    task = PageTask(job_id="t", page_no=1, mode="c")
    lr = LayoutResult(page_id="p", elements=[])
    return pipeline._build_response(task, "p", None, "ZERO", 0, 0, lr, [], [], [], **kw)


def test_응답은_env_가_아니라_경계_값을_옮긴다(monkeypatch):
    monkeypatch.setenv("SEMOJUM_NO_CAPTION", "1")                         # arm.py 팔의 env
    assert _response(caption_disabled=False)["processing_meta"]["caption_disabled"] is False
    assert _response(caption_disabled=None)["processing_meta"]["caption_disabled"] is None   # 옛 경계
    assert _response()["processing_meta"]["caption_disabled"] is True     # 경계 없는 모드 b 는 env


def test_모름은_proto_bool_에서_False(monkeypatch):
    assert _dict_to_processing_meta({"caption_disabled": None}).caption_disabled is False


def test_러너_job_표시는_쪽_표시를_모은다():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from corpus_runner import _job_caption_state
    assert _job_caption_state([{"caption_disabled": True}, {"caption_disabled": True}]) is True
    assert _job_caption_state([{"caption_disabled": False}, {"caption_disabled": True}]) is None
    assert _job_caption_state([{"caption_disabled": None}]) is None
    assert _job_caption_state([{"page": "1"}]) is None                    # 응답 없이 끝난 쪽만 있음
