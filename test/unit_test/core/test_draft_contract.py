"""대체 초안 계약 — mode a는 묵자만, mode c는 묵자+점자 (2026-08-06).

## 왜 이 파일이 있나

BE·FE 와이어프레임은 대체 초안을 **묵자와 점자를 나란히** 보여 준다. 그런데 셋이 어긋나 있었다.

  1. **mode a에 초안이 아예 없었다** — 표 초안이 *점역* 단계에서만 만들어지는데
     mode a는 그 단계를 안 탄다(`include_braille = mode == "c"`).
     묵자 초안은 점역 **전** 산출물이므로 opt 단계에서 만든다.
  2. **표 초안 4개의 묵자가 전부 같았다** — 전부 `text=원문`이라 피커에서 무엇을 고르는지
     알 수 없었다. 배치마다 묵자를 따로 만든다(`table_braille.print_layout`).
  3. **묵자에 내부 태그가 섞여 나갔다** — `<!주>…<!/주>` 는 점역기가 마커
     점형으로 바꾸는 기계 표식이지 사람이 읽을 글자가 아니다.

## 계약

| | `text_list[].drafts` | `braille_text_list[].drafts` |
|---|---|---|
| mode a | 묵자 (`contents` 빈 배열) | 없음 |
| mode b | 텍스트뿐이라 초안 없음 | 텍스트뿐이라 초안 없음 |
| mode c | 묵자 (`contents` 빈 배열) | 묵자 + 점자 |

`selected_idx`가 기본 선택 번호이고, 상위 `contents == drafts[selected_idx].contents`다.
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

AI = Path(__file__).resolve().parents[3]
TABLE = "구분 | t년 | t+50년\n인구 | 100 | 120\n비율 | 3.2 | 4.1"


def _run(mode: str, content: str = TABLE, etype: str = "table") -> dict:
    job = f"test-draft-{mode}-{uuid4().hex[:6]}"
    d = AI / f"storage/jobs/{job}/temp/page_001/data/001_txt_result.json"
    d.parent.mkdir(parents=True, exist_ok=True)
    d.write_text(json.dumps({
        "meta": {"job_id": job, "page_no": 1, "extraction_method": "TEXT_NATIVE"},
        "elements": [{"id": str(uuid4()), "order": 1, "type": etype, "content": content}],
    }, ensure_ascii=False), encoding="utf-8")
    try:
        return asyncio.run(pipeline.run(PageTask(job_id=job, page_no=1, mode=mode)))
    finally:
        shutil.rmtree(AI / f"storage/jobs/{job}", ignore_errors=True)


@pytest.fixture(scope="module")
def mode_a() -> dict:
    return _run("a")


@pytest.fixture(scope="module")
def mode_c() -> dict:
    return _run("c")


class TestModeA:
    """묵자만 — 점역을 하지 않으므로 점자가 없다."""

    def test_초안이_있다(self, mode_a: dict) -> None:
        """종전에는 여기가 0이었다 — 표 초안이 점역 단계에서만 만들어졌다."""
        assert len(mode_a["text_list"][0]["drafts"]) == 4

    def test_점자는_안_싣는다(self, mode_a: dict) -> None:
        for d in mode_a["text_list"][0]["drafts"]:
            assert d["contents"] == []

    def test_묵자가_비어있지_않다(self, mode_a: dict) -> None:
        for d in mode_a["text_list"][0]["drafts"]:
            assert d["text"].strip()

    def test_점역_목록은_비어있다(self, mode_a: dict) -> None:
        assert not mode_a.get("braille_text_list")


class TestModeC:
    """묵자 + 점자 둘 다."""

    def test_원문_목록에_묵자_초안(self, mode_c: dict) -> None:
        ds = mode_c["text_list"][0]["drafts"]
        assert len(ds) == 4
        assert all(d["contents"] == [] for d in ds)

    def test_점역_목록에_묵자와_점자(self, mode_c: dict) -> None:
        ds = mode_c["braille_text_list"][0]["drafts"]
        assert len(ds) == 4
        for d in ds:
            assert d["text"].strip(), "묵자가 비었다"
            assert d["contents"] and d["contents"][0].strip(), "점자가 비었다"

    def test_불변식(self, mode_c: dict) -> None:
        el = mode_c["braille_text_list"][0]
        assert el["contents"] == el["drafts"][el["selected_idx"]]["contents"]


class TestDistinctLayouts:
    """배치가 다르면 묵자도 달라야 한다 — 피커가 무엇을 고르는지 보여야 하므로."""

    def test_표_초안_묵자가_서로_다르다(self, mode_c: dict) -> None:
        """종전에는 4개가 전부 원문이라 똑같았다."""
        ts = [d["text"] for d in mode_c["braille_text_list"][0]["drafts"]]
        assert len(set(ts)) >= 3, ts

    def test_표_초안_점자가_서로_다르다(self, mode_c: dict) -> None:
        cs = [d["contents"][0] for d in mode_c["braille_text_list"][0]["drafts"]]
        assert len(set(cs)) == 4, "배치 4안의 점자가 겹친다"

    def test_전치안은_점역자_주를_밝힌다(self, mode_c: dict) -> None:
        t = [d for d in mode_c["braille_text_list"][0]["drafts"]
             if d["label"] == "행열 바꿈"][0]["text"]
        assert "행과 열을 바꾸어" in t


class TestNoInternalTags:
    """묵자는 사람이 읽는 값이다 — 기계 표식이 새어 나가면 안 된다."""

    def test_초안_묵자에_태그가_없다(self, mode_c: dict) -> None:
        for src in (mode_c["text_list"], mode_c["braille_text_list"]):
            for el in src:
                for d in el.get("drafts") or []:
                    assert "<!" not in d["text"], d["text"][:60]

    def test_태그_제거_함수(self) -> None:
        from app.core.pipeline import _draft_print_text

        assert _draft_print_text("<!주>그래프 생략<!/주>") == "그래프 생략"
        assert _draft_print_text("평범한 텍스트") == "평범한 텍스트"
        assert _draft_print_text("") == ""

    def test_줄바꿈은_보존한다(self) -> None:
        """줄바꿈은 배치다 — 지우면 피커가 배치를 못 보여 준다."""
        from app.core.pipeline import _draft_print_text

        assert _draft_print_text("<!주>가\n\n나<!/주>") == "가\n\n나"


class TestTextElementsHaveNoDrafts:
    """텍스트·수식은 단일안이다 — 빈 배열이 정상이고, 그게 바뀌면 계약이 흔들린 것이다."""

    def test_텍스트는_초안_없음(self) -> None:
        r = _run("c", content="인공지능 기술은 우리 삶을 바꾼다.", etype="text")
        for el in r["braille_text_list"]:
            assert (el.get("drafts") or []) == []


class TestBBoxCoordSpace:
    """경계 bbox 좌표계 통일 — BE·FE 하이라이트가 맞는 자리에 찍히나.

    경계 파일의 좌표계는 경로마다 다르다(`result_builder` 2026-07-19):
      MinerU = 0~1000 정규화 / ZERO = 2x 렌더 픽셀
    BE·FE는 `image_width/height`에 대한 비율로 매핑하므로 응답은 픽셀로 통일해야 한다.
    안 하면 MinerU 쪽 하이라이트가 실제 위치의 77%·65% 자리에 찍힌다(사회문화 p80 실측).
    """

    @staticmethod
    def _parse(method: str, bbox: list[int], **meta):
        from app.core.pipeline import _parse_txt_result
        lr, _, _ = _parse_txt_result({
            "meta": {"extraction_method": method, "image_width": 1000, "image_height": 2000,
                     **meta},
            "elements": [{"id": "e1", "order": 1, "type": "text", "content": "가", "bbox": bbox}],
        }, "p1")
        return lr.elements[0].bbox

    def test_MinerU는_정규화를_픽셀로_되돌린다(self) -> None:
        assert self._parse("OCR", [100, 100, 500, 500]) == (100, 200, 500, 1000)

    def test_ZERO는_이미_픽셀이라_그대로(self) -> None:
        assert self._parse("TEXT_NATIVE", [100, 100, 500, 500]) == (100, 100, 500, 500)

    def test_폴백_픽셀은_method가_OCR이어도_안_늘린다(self) -> None:
        """MinerU 실패 → 텍스트레이어 폴백은 픽셀 bbox인데 method는 "OCR"로 남는다.

        method로 좌표계를 유추하던 종전 코드는 여기서 픽셀을 한 번 더 확대해
        요소가 아래로 밀렸다(job_260807140040 p1 실측: y2 1422px → 2096px, 쪽 밖).
        생산자가 적어 주는 `bbox_space`를 읽으면 그대로 둔다.
        """
        assert self._parse("OCR", [100, 100, 500, 500], bbox_space="pixel") == (100, 100, 500, 500)

    def test_bbox_space가_명시되면_그걸_따른다(self) -> None:
        assert self._parse("TEXT_NATIVE", [100, 100, 500, 500],
                           bbox_space="norm1000") == (100, 200, 500, 1000)

    def test_페이지_크기를_모르면_손대지_않는다(self) -> None:
        from app.core.pipeline import _parse_txt_result
        lr, _, _ = _parse_txt_result({
            "meta": {"extraction_method": "OCR"},
            "elements": [{"id": "e1", "order": 1, "type": "text", "content": "가",
                          "bbox": [10, 20, 30, 40]}],
        }, "p1")
        assert lr.elements[0].bbox == (10, 20, 30, 40)
