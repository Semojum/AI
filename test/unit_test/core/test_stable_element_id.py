"""요소 id 는 입력에서 정한다(재구조화 N5 · #1017). 같은 job · 쪽 · 자리의 요소는 늘 같은 id 다.

종전 uuid4 는 재파생마다 전부 갈렸고, 목록 쪼갬 자식은 같은 경계를 재사용해도 요청마다 갈렸다.
점역사 피드백 · 편집이 요소 id 로 요소를 가리키므로 그 참조가 끊겼다.
"""
import asyncio
import copy
from uuid import UUID

import fitz
import pytest

from app.core import pipeline
from app.schemas.task import PageTask


def _els():
    return [{"id": "a", "type": "image", "content": "그림: 캡션 1판", "bbox": [10, 10, 90, 60]},
            {"id": "b", "type": "caption", "content": "(가)", "bbox": [10, 61, 30, 66], "caption_ref": "a"},
            {"id": "c", "type": "text", "content": "본문", "bbox": [10, 70, 90, 80]},
            {"id": "d", "type": "text", "content": "본문 둘", "bbox": [10, 70, 90, 80]},    # 상자가 겹친다
            {"type": "image", "content": "그림: 회수", "bbox": None}]                        # 회수 그림(상자 없음)


def _ids(els, job="j1", page=3):
    els = copy.deepcopy(els)
    pipeline._rekey_elements(els, job, page)
    return els


def test_같은_입력이면_같은_id_이고_UUID_꼴이다():
    a, b = _ids(_els()), _ids(_els())
    assert [e["id"] for e in a] == [e["id"] for e in b]
    assert all(UUID(e["id"]) for e in a)
    assert len({e["id"] for e in a}) == len(a)              # 상자가 겹쳐도 순번으로 갈린다


def test_글이_바뀌어도_자리가_같으면_같은_id():
    """캡션을 다시 쓰거나 글자를 고쳐도 같은 요소는 같은 id 여야 피드백이 안 끊긴다."""
    e2 = _els(); e2[0]["content"] = "그림: 캡션 2판"; e2[2]["content"] = "본문(교정)"
    assert _ids(_els())[0]["id"] == _ids(e2)[0]["id"] and _ids(_els())[2]["id"] == _ids(e2)[2]["id"]


def test_job_이나_쪽이_다르면_다른_id():
    assert _ids(_els())[2]["id"] != _ids(_els(), job="j2")[2]["id"] != _ids(_els(), page=4)[2]["id"]


def test_caption_ref_도_같이_옮긴다():
    a = _ids(_els())
    assert a[1]["caption_ref"] == a[0]["id"]


def test_목록_쪼갬_자식은_요청마다_같은_id(monkeypatch):
    monkeypatch.delenv("STABLE_ELEMENT_ID", raising=False)
    el = [{"id": "p1", "type": "list_item", "content": "① 가\n② 나\n③ 다", "order": 1}]
    one, two = pipeline._split_list_marker_items(el), pipeline._split_list_marker_items(el)
    assert len(one) == 3 and [c["id"] for c in one] == [c["id"] for c in two]
    assert len({c["id"] for c in one}) == 3


def test_스위치_0_이면_종전대로(monkeypatch):
    monkeypatch.setenv("STABLE_ELEMENT_ID", "0")
    assert not pipeline._stable_ids()
    el = [{"id": "p1", "type": "list_item", "content": "① 가\n② 나", "order": 1}]
    assert all("id" not in c for c in pipeline._split_list_marker_items(el))


def _pdf() -> bytes:
    d = fitz.open(); pg = d.new_page()
    for i in range(12):
        pg.insert_text((72, 72 + 18 * i), f"Line {i}: plain text layer for a zero tier page.")
    return d.tobytes()


@pytest.mark.parametrize("env, same", [("", True), ("0", False)])
def test_같은_쪽을_두_번_뜨면_id_가_같다(monkeypatch, tmp_path, env, same):
    """재파생 두 번(실제 ZERO 쪽 추출). 종전(스위치 0)은 두 번이 다르다 — 대조군."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STABLE_ELEMENT_ID", env)
    task = PageTask(job_id="n5", page_no=1, total_pages=1, mode="a", pdf_data=_pdf())
    ids = [[e["id"] for e in asyncio.run(pipeline._extract_with_hyunju(task))[1]["elements"]] for _ in range(2)]
    assert ids[0] and (ids[0] == ids[1]) is same


@pytest.mark.parametrize("env, same", [("", True), ("0", False)])
def test_모드_b_줄도_요청마다_같은_id(monkeypatch, tmp_path, env, same):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STABLE_ELEMENT_ID", env)
    monkeypatch.setenv("SEMOJUM_NO_CAPTION", "1")
    task = PageTask(job_id="n5b", page_no=1, mode="b", source_text="가나다라 마바사.\n\n둘째 문단.")
    ids = [[x["id"] for x in asyncio.run(pipeline.run(task))["text_list"]] for _ in range(2)]
    assert ids[0] and (ids[0] == ids[1]) is same
