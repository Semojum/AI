"""추출 단계 관문 표시는 경계와 함께 다닌다(#1032).

G1 은 캡션 · 그림 회수 · 고급 점역에서 켜진다. 재요청은 경계를 재사용해 추출이 안 도니
계수기가 안 세고 "AI 문장 관문이 걷어낸 자리" 가 빠졌다. 요소 글은 같은데 검토 표시만 달라졌다.
"""
import asyncio
import json

import fitz

from app.ai import gates
from app.core import pipeline
from app.schemas.task import PageTask


def _pdf() -> bytes:
    d = fitz.open(); pg = d.new_page()
    for i in range(12):
        pg.insert_text((72, 72 + 18 * i), f"Line {i}: plain text layer for a zero tier page.")
    return d.tobytes()


def _g1(task):
    flags = asyncio.run(pipeline.run(task))["quality_report"]["review_flags"]
    return [f for f in flags if f["type"] == "G1"]


def _setup(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SEMOJUM_NO_CAPTION", "1")
    real = pipeline._extract_with_hyunju

    async def extract(task):                 # 추출 중 관문 발동 한 건(캡션 LLM 대신)
        gates.gate_hit("G1", "caption:걷어냄")
        return await real(task)
    monkeypatch.setattr(pipeline, "_extract_with_hyunju", extract)
    return PageTask(job_id="g1", page_no=1, total_pages=1, mode="c", pdf_data=_pdf())


def test_재요청에도_관문_표시가_같다(monkeypatch, tmp_path):
    task = _setup(monkeypatch, tmp_path)
    first, again = _g1(task), _g1(task)          # 둘째는 경계 재사용
    assert first and first == again


def test_키가_없는_옛_경계는_종전대로(monkeypatch, tmp_path):
    task = _setup(monkeypatch, tmp_path)
    assert _g1(task)
    p = pipeline._txt_result_path(task)
    d = json.loads(p.read_text(encoding="utf-8")); d["meta"].pop("gate_counts")
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    assert _g1(task) == []
