"""요청 낱값 `choices_one_per_line`(BrailleRequest 12, 이슈 #1238) 배선: proto 번호 · 비운 직렬화 · PageTask · run → 조판 풀.

합치기 동작 자체는 `test/unit_test/braille/test_choice_combine_1238.py`(지침 [예 3-68] 점자 줄 대조)에 있다.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

from app.ai.braille.constants import CHOICES_ONE_PER_LINE
from app.core import limits, pipeline
from app.schemas.task import PageTask
from protos.generated import braille_service_pb2 as pb


def test_번호와_빈_값():
    assert pb.BrailleRequest.DESCRIPTOR.fields_by_name["choices_one_per_line"].number == 12
    old = pb.BrailleRequest(job_id="j", page_no=3, mode="c")
    assert old.SerializeToString() == pb.BrailleRequest(job_id="j", page_no=3, mode="c",
                                                        choices_one_per_line=False).SerializeToString()
    assert PageTask.from_proto(pb.BrailleRequest(job_id="j", page_no=1, choices_one_per_line=True)).choices_one_per_line
    assert not PageTask.from_proto(old).choices_one_per_line


def test_run_이_조판_풀까지_값을_넘긴다():
    """조판(flatten · layout)도 `run_braille` 로 돈다. 동시 요청끼리, 이어 돈 쪽끼리 안 섞인다."""
    seen: dict = {}

    async def fake(task):
        seen[task.job_id] = await limits.run_braille(CHOICES_ONE_PER_LINE.get)
        await asyncio.sleep(0.01)
        return {"status": "OK", "processing_meta": {}, "braille_text_list": []}

    async def go():
        await asyncio.gather(pipeline.run(PageTask(job_id="on", page_no=1, mode="c", choices_one_per_line=True)),
                             pipeline.run(PageTask(job_id="off", page_no=1, mode="c")))
        await pipeline.run(PageTask(job_id="after", page_no=1, mode="c"))

    with patch.object(pipeline, "_run_pipeline", fake), \
         patch.object(pipeline, "_record_metrics", lambda *a, **k: None):
        asyncio.run(go())
    assert seen == {"on": True, "off": False, "after": False}
