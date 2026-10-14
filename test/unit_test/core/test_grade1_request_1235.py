"""요청에서 한글 · 영어 정자(1급)를 고른다(이슈 #1235, 대표 결재 2026-10-08 「점역 양식 설계 4건」 1 · 4).

점역 로직은 #1191(한글) · #1189(영어)에 있고 `constants.KOREAN_GRADE1` · `ENGLISH_GRADE1` 문맥 값으로 켠다.
여기서 지키는 것은 배선이다 — ① 필드 번호 ② 비우면 지금과 바이트가 같음 ③ 요청 → PageTask → 점역 풀 스레드까지
값이 가고 동시 요청끼리 안 섞임 ④ 꼬리말(TranslateText)도 같은 값 ⑤ 동그라미 음절 캐시가 모드를 안 굳힘.
기대 점형은 `test_korean_grade1.py` 와 같다(「한국 점자 규정」 제13항 약자 ⠫ · 정자 ㄱ ⠈ + ㅏ ⠣).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.ai.braille import translator
from app.ai.braille.constants import ENGLISH_GRADE1, KOREAN_GRADE1
from app.core import grpc_server, limits, pipeline
from app.schemas.task import PageTask
from protos.generated import braille_service_pb2 as pb


# ── ① 필드 번호 · ② 비우면 지금과 같다 ──────────────────────────────────────────

def test_번호가_계약대로다():
    """V4 정본(docs/spec_v4/braille_service.proto, #1380): 급수는 정수 10 · 11, 선택지는 12, 쪽 이미지는 8 · 9."""
    req = {f.name: (f.number, f.type) for f in pb.BrailleRequest.DESCRIPTOR.fields}
    F = pb.BrailleRequest.DESCRIPTOR.fields_by_name["korean_grade"]
    assert {k: v[0] for k, v in req.items() if k in ("text_data", "image_data", "image_mime_type", "korean_grade",
                                                     "english_grade", "split_choices")} == {
        "text_data": 6, "image_data": 8, "image_mime_type": 9, "korean_grade": 10, "english_grade": 11, "split_choices": 12}
    assert req["korean_grade"][1] == req["english_grade"][1] == F.TYPE_INT32
    assert "item_code_form" not in req and "korean_grade1" not in req and "source_text" not in req
    tt = {f.name: f.number for f in pb.TranslateTextRequest.DESCRIPTOR.fields}
    assert tt == {"text": 1, "korean_grade1": 2, "english_grade1": 3}          # 꼬리말 통로는 4단계까지 그대로


def test_비우면_직렬화가_지금과_같다():
    """안 보낸 급수(0)는 서버 기본 2(약자)다. proto3 는 기본값을 안 싣는다."""
    old = pb.BrailleRequest(job_id="j", page_no=3, mode="c")
    off = pb.BrailleRequest(job_id="j", page_no=3, mode="c", korean_grade=0, english_grade=0)
    assert old.SerializeToString() == off.SerializeToString()


def test_PageTask_가_급수_세_값을_받는다():
    """1 정자 · 2 약자 · 0 = 서버 기본(2). PageTask 는 정자 여부 낱값으로 옮긴다."""
    def task(k, e):
        return PageTask.from_proto(pb.BrailleRequest(job_id="j", page_no=1, mode="c", korean_grade=k, english_grade=e))
    assert [(t.korean_grade1, t.english_grade1) for t in (task(1, 1), task(2, 2), task(0, 0), task(1, 2), task(0, 1))] \
        == [(True, True), (False, False), (False, False), (True, False), (False, True)]
    assert task(0, 0).item_code_form == ""


def test_계약_밖_급수는_요청_파싱_실패로_답한다():
    import pytest
    with pytest.raises(ValueError, match="급수"):
        PageTask.from_proto(pb.BrailleRequest(job_id="j", page_no=1, mode="c", korean_grade=3))
    resp = asyncio.run(grpc_server.BrailleServiceServicer()._process_page(
        pb.BrailleRequest(job_id="j", page_no=1, mode="c", english_grade=-1), MagicMock()))
    assert "요청 파싱 실패" in str(resp)


def test_문항코드_자리는_PageTask_로만_바꾼다():
    """C-107(2026-10-04 결재). V4 정본 proto 에는 이 칸이 없다(11 = english_grade). 요청으로는 늘 서버 기본 X 다."""
    seen = {}

    async def fake(task):
        seen[task.job_id] = pipeline._ITEM_CODE_FORM_JOB.get()
        return {"status": "OK", "processing_meta": {}, "braille_text_list": []}

    async def seq():
        await pipeline.run(PageTask(job_id="y", page_no=1, mode="c", item_code_form="y"))
        await pipeline.run(PageTask(job_id="none", page_no=1, mode="c"))

    with patch.object(pipeline, "_run_pipeline", fake), \
         patch.object(pipeline, "_record_metrics", lambda *a, **k: None):
        asyncio.run(seq())
    assert seen == {"y": "Y", "none": ""}                  # 빈 값이면 서버 기본(`_ITEM_CODE_FORM`)으로 떨어진다


# ── ③ pipeline.run → 점역 풀 스레드 · 동시 요청 ─────────────────────────────────

def _fake_pipeline(seen: dict):
    async def fake(task):
        # 점역은 `run_braille` 풀 스레드에서 돈다 — 그 스레드에서 보이는 값을 잰다.
        seen[task.job_id] = await limits.run_braille(lambda: (KOREAN_GRADE1.get(), ENGLISH_GRADE1.get()))
        await asyncio.sleep(0.01)           # 두 요청이 겹치게 한 번 양보한다
        seen[task.job_id + "/after"] = await limits.run_braille(
            lambda: (KOREAN_GRADE1.get(), ENGLISH_GRADE1.get()))
        return {"status": "OK", "processing_meta": {}, "braille_text_list": []}
    return fake


def _task(job: str, k: bool, e: bool) -> PageTask:
    return PageTask(job_id=job, page_no=1, mode="c", korean_grade1=k, english_grade1=e)


def test_run_이_점역_풀까지_값을_넘기고_동시_요청이_안_섞인다():
    seen: dict = {}

    async def both():
        await asyncio.gather(pipeline.run(_task("ko", True, False)),
                             pipeline.run(_task("en", False, True)),
                             pipeline.run(_task("off", False, False)))

    with patch.object(pipeline, "_run_pipeline", _fake_pipeline(seen)), \
         patch.object(pipeline, "_record_metrics", lambda *a, **k: None):
        asyncio.run(both())
    assert seen["ko"] == seen["ko/after"] == (True, False)
    assert seen["en"] == seen["en/after"] == (False, True)
    assert seen["off"] == seen["off/after"] == (False, False)


def test_한_문맥에서_이어_돌려도_앞_쪽_값을_안_물려받는다():
    """러너가 한 이벤트 루프 문맥에서 쪽을 차례로 돌려도(같은 task) 끈 쪽은 끈 값이다."""
    seen: dict = {}

    async def seq():
        await pipeline.run(_task("p1", True, True))
        await pipeline.run(_task("p2", False, False))

    with patch.object(pipeline, "_run_pipeline", _fake_pipeline(seen)), \
         patch.object(pipeline, "_record_metrics", lambda *a, **k: None):
        asyncio.run(seq())
    assert seen["p1"] == (True, True)
    assert seen["p2"] == (False, False)


# ── ④ 꼬리말(TranslateText) ─────────────────────────────────────────────────

def _ctx():
    ctx = MagicMock()
    ctx.abort = AsyncMock()
    ctx.peer.return_value = "ipv4:127.0.0.1:1"
    return ctx


def _tt(text: str, **kw) -> str:
    svc = grpc_server.BrailleServiceServicer.__new__(grpc_server.BrailleServiceServicer)
    return asyncio.run(svc.TranslateText(pb.TranslateTextRequest(text=text, **kw), _ctx())).braille


def test_꼬리말도_같은_값으로_적고_끝나면_되돌린다():
    assert _tt("가") == "⠫"                                  # 지금 동작(약자)
    assert _tt("가", korean_grade1=True) == "⠈⠣"            # 정자
    assert KOREAN_GRADE1.get() is False                     # 호출 밖으로 안 샌다
    assert _tt("가", english_grade1=True) == "⠫"            # 한글은 영어 값에 안 흔들린다


def test_꼬리말_영어_정자는_약자를_안_쓴다():
    """`the` 를 UEB 약자 ⠮ 대신 낱자 t ⠞ · h ⠓ · e ⠑ 로 적는다(「한국 점자 규정」 제28항 표, 재추출 1428 · 1368 · 1353행)."""
    off, on = _tt("the"), _tt("the", english_grade1=True)
    assert "⠮" in off and "⠞⠓⠑" not in off
    assert "⠞⠓⠑" in on and "⠮" not in on
    assert ENGLISH_GRADE1.get() is False


# ── ⑤ 동그라미 음절 캐시 ─────────────────────────────────────────────────────

def test_동그라미_음절이_먼저_돈_모드로_굳지_않는다():
    def circled(grade1: bool) -> str:
        tok = KOREAN_GRADE1.set(grade1)
        try:
            return translator._circled_braille("㉮")
        finally:
            KOREAN_GRADE1.reset(tok)

    assert circled(False) == "⠶⠫⠶"                     # 규정 제64항 감쌈 + 제13항 약자
    assert circled(True) == "⠶⠈⠣⠶"                     # 정자 요청이 뒤에 와도 약자로 안 굳는다
    assert circled(False) == "⠶⠫⠶"
