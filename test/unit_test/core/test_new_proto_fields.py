"""2026-09-08 신설 필드 계약 회귀 — 값이 있는데 안 실리던 자리를 다시 막지 않게.

  ProcessingMeta.caption_disabled
  TextElement.review_grade / .round_trip

★ **빈 값일 때는 종전과 바이트가 같아야 한다.** BE 가 아직 안 읽으므로 그게 평상 상태다.
  proto3 는 기본값을 직렬화하지 않으므로 "기본값이면 바이트 0" 을 그대로 잰다.

★ 철회한 번호 둘은 `reserved` 로 비어 있어야 한다(#788). 다른 뜻으로 재사용하면 그 필드를
  실어 보내던·읽던 클라이언트가 있을 때 조용히 오독한다.
  · `BrailleRequest.customer_id`(8) — 캐시 격리는 `job_id` 단위로 돌고 고객 사이엔 안 샌다.
  · `ProcessingMeta.advanced_ai_applied`(6) — "켰는데 안 돌았다" 는 보고할 상태가 아니라
    **결함**이다. 필드로 알리지 않고 그 자리에서 실패로 알린다
    (`test_advanced_ai_fails_loud.py`).
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "protos" / "generated"))

import pytest  # noqa: E402

import braille_service_pb2 as pb  # noqa: E402

from app.core.grpc_server import _dict_to_processing_meta, _dict_to_text_element  # noqa: E402
from app.schemas.task import PageTask  # noqa: E402
from app.utils.req_log import review_signal_line  # noqa: E402


class TestFieldNumbers:
    """번호는 BE·FE 와의 약속이다. 바꾸면 옛 클라이언트가 다른 뜻으로 읽는다."""

    def test_번호가_약속대로다(self):
        got = {m.DESCRIPTOR.name: {f.name: f.number for f in m.DESCRIPTOR.fields}
               for m in (pb.BrailleRequest, pb.ProcessingMeta, pb.TextElement)}
        assert got["ProcessingMeta"]["caption_disabled"] == 5
        assert got["TextElement"]["review_grade"] == 17
        assert got["TextElement"]["round_trip"] == 18

    @pytest.mark.parametrize("msg, 이름, 번호", [
        (pb.BrailleRequest, "customer_id", 8),
        (pb.ProcessingMeta, "advanced_ai_applied", 6),
    ])
    def test_철회한_번호는_비고_예약돼_있다(self, msg, 이름, 번호):
        assert 이름 not in {f.name for f in msg.DESCRIPTOR.fields}
        assert 번호 not in {f.number for f in msg.DESCRIPTOR.fields}
        # ※ 런타임 Descriptor 는 예약 범위를 안 드러낸다 — 서술자 proto 로 되돌려 본다.
        from google.protobuf import descriptor_pb2
        dp = descriptor_pb2.DescriptorProto()
        msg.DESCRIPTOR.CopyToProto(dp)
        assert any(r.start <= 번호 < r.end for r in dp.reserved_range)

    def test_task가_철회한_값을_안_들고_있다(self):
        assert "customer_id" not in PageTask.model_fields
        assert "advanced_ai_applied" not in PageTask.model_fields


class TestCarried:
    """만들어 놓고 버리던 값이 실제로 실리는가."""

    def test_processing_meta가_캡션_상태를_싣는다(self):
        assert _dict_to_processing_meta({"caption_disabled": True}).caption_disabled

    def test_text_element가_검수신호를_싣는다(self):
        e = _dict_to_text_element({"id": "x", "review_grade": "high",
                                   "round_trip": 0.947})
        assert e.review_grade == "high" and round(e.round_trip, 3) == 0.947


class TestEmptyIsByteIdentical:
    """BE 가 안 읽는 평상 상태 = 새 필드가 바이트를 한 개도 안 늘린다."""

    def test_기본값이면_직렬화에_안_나온다(self):
        base = _dict_to_processing_meta({"routing_tier_used": "ZERO"})
        assert base.SerializeToString(deterministic=True) == \
            _dict_to_processing_meta({"routing_tier_used": "ZERO",
                                      "caption_disabled": False}
                                     ).SerializeToString(deterministic=True)
        el = _dict_to_text_element({"id": "x"})
        assert el.SerializeToString(deterministic=True) == \
            _dict_to_text_element({"id": "x", "review_grade": "", "round_trip": 0.0}
                                  ).SerializeToString(deterministic=True)


class TestJobScope:
    """캐시 격리 열쇠는 `job_id` 다. 고객 사이엔 절대 안 샌다."""

    def test_파이프라인이_job으로_가른다(self, tmp_path, monkeypatch):
        from app.core import pipeline
        from app.utils import llm_cache
        monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))
        monkeypatch.setenv("SEMOJUM_NO_CAPTION", "1")

        async def scope_of(job_id: str) -> str:
            # ★ 열쇠는 contextvar 라 **같은 task 안에서** 읽어야 한다. asyncio.run 을
            #   따로 돌리면 컨텍스트가 갈려 늘 빈 값으로 보인다.
            await pipeline.run(PageTask(job_id=job_id, page_no=1, mode="b",
                                        source_text="가나다라 마바사."))
            return llm_cache.scope()

        assert asyncio.run(scope_of("job-A")) == "job-A"
        assert asyncio.run(scope_of("job-B")) == "job-B"
        # 같은 입력이라도 job 이 다르면 다른 자리다(= 서로의 응답을 못 본다)
        llm_cache.set_scope("job-A")
        k = llm_cache.key("caption", "같은 그림")
        llm_cache.set_scope("job-B")
        assert llm_cache.key("caption", "같은 그림") != k


class TestReviewSignalLine:
    """검수 신호는 BE 가 아니라 **우리 로그**로 본다(#788). 쪽당 한 줄이어야 한다."""

    def test_등급별_개수와_왕복최저를_한_줄로(self):
        line = review_signal_line([
            {"review_grade": "high", "round_trip": 0.98},
            {"review_grade": "high", "round_trip": 0.41},
            {"review_grade": "low", "round_trip": 0.12},
            {"review_grade": "medium"},          # 왕복 못 잰 요소
        ])
        assert "\n" not in line                   # ★ 요소마다 한 줄씩 쏟으면 안 된다
        assert "요소=4" in line and "high=2" in line and "low=1" in line
        assert "0.12 0.41 0.98" in line and "측정 3" in line

    def test_요소가_없어도_줄은_남는다(self):
        # 줄이 없는 것과 0인 것을 구별 못 하면 확인이 안 된다.
        assert "요소=0" in review_signal_line([])

    def test_로그가_페이지를_죽이지_않는다(self):
        # 성공 로그 안에서 불린다 — 여기서 예외가 나면 다 끝난 점역이 C1 으로 뒤집힌다.
        assert review_signal_line(["요소가 아닌 것"]) == ""   # el.get 이 터지는 입력
