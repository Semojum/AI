"""step3 파일 핸드오프 E2E — 현주 data/NNN_txt_result.json → 태민 파이프라인.

현주 형식(step3_hyunju_output.md)의 경계 파일을 직접 배치한 뒤
pipeline.run(mode=c)이 그 파일을 읽어 단계별 json + 최종 BRF를 생성하는지 검증.
GPU/모델 불필요 (extraction_method=TEXT_NATIVE → ZERO passthrough).
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from app.core import pipeline
from app.schemas.task import PageTask

_PAGE = 1


def _make_extraction() -> dict:
    return {
        "meta": {"job_id": "", "page_no": _PAGE, "extraction_method": "TEXT_NATIVE"},
        "elements": [
            {"id": str(uuid4()), "order": 1, "type": "title", "content": "실습 환경 구축하기"},
            {"id": str(uuid4()), "order": 2, "type": "text",
             "content": "이 책은 파이썬 3.7을 기준으로 소스코드를 제공하고 설명한다."},
            {"id": str(uuid4()), "order": 3, "type": "list_item", "content": "1. 환경 설치"},
            {"id": str(uuid4()), "order": 4, "type": "formula", "content": "\\frac{1}{2}"},
            {"id": str(uuid4()), "order": 5, "type": "header_footer",
             "content": "CHAPTER 01 · 코딩 테스트 개요"},
            {"id": str(uuid4()), "order": 6, "type": "page_number", "content": "39"},
        ],
    }


@pytest.fixture()
def job(tmp_path_factory):
    job_id = f"test-handoff-{uuid4().hex[:8]}"
    data_path = Path(f"storage/jobs/{job_id}/temp/page_{_PAGE:03d}/data/{_PAGE:03d}_txt_result.json")
    data_path.parent.mkdir(parents=True, exist_ok=True)
    extraction = _make_extraction()
    extraction["meta"]["job_id"] = job_id
    data_path.write_text(json.dumps(extraction, ensure_ascii=False, indent=2), encoding="utf-8")
    yield job_id, extraction
    shutil.rmtree(Path(f"storage/jobs/{job_id}"), ignore_errors=True)


def _page_dir(job_id: str) -> Path:
    return Path(f"storage/jobs/{job_id}/temp/page_{_PAGE:03d}")


class TestFileHandoffE2E:

    def test_existing_file_is_consumed_not_overwritten(self, job):
        job_id, extraction = job
        before = _read(job_id)
        asyncio.run(pipeline.run(PageTask(job_id=job_id, page_no=_PAGE, mode="c")))
        after = _read(job_id)
        # Phase1이 스킵되어 원본 요소 id가 보존되어야 함
        assert [e["id"] for e in after["elements"]] == [e["id"] for e in extraction["elements"]]
        assert before == after

    def test_response_completed_with_braille(self, job):
        job_id, _ = job
        result = asyncio.run(pipeline.run(PageTask(job_id=job_id, page_no=_PAGE, mode="c")))
        assert result["status"] == "COMPLETED"
        assert len(result["braille_text_list"]) == 6
        for el in result["braille_text_list"]:
            assert el["contents"], f"빈 점자 출력: {el['id']}"

    def test_stage_json_files_written(self, job):
        job_id, _ = job
        asyncio.run(pipeline.run(PageTask(job_id=job_id, page_no=_PAGE, mode="c")))
        pd = _page_dir(job_id)
        for f in ["text_ocr.json", "text_opt.json", "text_braille.json"]:
            assert (pd / "type" / "text" / f).exists(), f"누락: text/{f}"
        for f in ["formula_ocr.json", "formula_opt.json", "formula_braille.json"]:
            assert (pd / "type" / "formula" / f).exists(), f"누락: formula/{f}"

    def test_final_brf_written(self, job):
        job_id, _ = job
        asyncio.run(pipeline.run(PageTask(job_id=job_id, page_no=_PAGE, mode="c")))
        result_dir = _page_dir(job_id) / "result"
        brf = list(result_dir.glob("*_result.brf"))
        txt = list(result_dir.glob("*_result.txt"))
        assert brf, "result.brf 미생성"
        assert txt, "result.txt 미생성"
        assert brf[0].read_text(encoding="utf-8").strip(), "result.brf 비어있음"

    def test_formula_has_fraction_bar(self, job):
        job_id, _ = job
        result = asyncio.run(pipeline.run(PageTask(job_id=job_id, page_no=_PAGE, mode="c")))
        formula_el = next(e for e in result["braille_text_list"] if e["type"] == "formula")
        combined = "".join(formula_el["contents"])
        assert "⠌" in combined, f"분수표(⠌) 없음: {combined!r}"

    def test_page_number_has_numeral_sign(self, job):
        job_id, _ = job
        result = asyncio.run(pipeline.run(PageTask(job_id=job_id, page_no=_PAGE, mode="c")))
        pn = next(e for e in result["braille_text_list"] if e["type"] == "page_number")
        combined = "".join(pn["contents"])
        assert "⠼" in combined, f"수표(⠼) 없음: {combined!r}"


def _read(job_id: str) -> dict:
    p = Path(f"storage/jobs/{job_id}/temp/page_{_PAGE:03d}/data/{_PAGE:03d}_txt_result.json")
    return json.loads(p.read_text(encoding="utf-8"))
