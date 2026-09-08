"""2026-09-08 신설 4필드 계약 회귀 — 값이 있는데 안 실리던 자리를 다시 막지 않게.

  BrailleRequest.customer_id      LLM 캐시 격리 단위. 빈 값이면 job_id
  ProcessingMeta.caption_disabled / .advanced_ai_applied
  TextElement.review_grade / .round_trip

★ **빈 값일 때는 종전과 바이트가 같아야 한다.** BE 가 아직 안 보내므로 그게 평상 상태다.
  proto3 는 기본값을 직렬화하지 않으므로 "기본값이면 바이트 0" 을 그대로 잰다.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "protos" / "generated"))

import braille_service_pb2 as pb  # noqa: E402

from app.core.grpc_server import _dict_to_processing_meta, _dict_to_text_element  # noqa: E402
from app.schemas.task import PageTask  # noqa: E402


class TestFieldNumbers:
    """번호는 BE·FE 와의 약속이다. 바꾸면 옛 클라이언트가 다른 뜻으로 읽는다."""

    def test_번호가_약속대로다(self):
        got = {m.DESCRIPTOR.name: {f.name: f.number for f in m.DESCRIPTOR.fields}
               for m in (pb.BrailleRequest, pb.ProcessingMeta, pb.TextElement)}
        assert got["BrailleRequest"]["customer_id"] == 8
        assert got["ProcessingMeta"]["caption_disabled"] == 5
        assert got["ProcessingMeta"]["advanced_ai_applied"] == 6
        assert got["TextElement"]["review_grade"] == 17
        assert got["TextElement"]["round_trip"] == 18


class TestCarried:
    """만들어 놓고 버리던 값이 실제로 실리는가."""

    def test_processing_meta가_둘을_싣는다(self):
        m = _dict_to_processing_meta({"caption_disabled": True,
                                      "advanced_ai_applied": True})
        assert m.caption_disabled and m.advanced_ai_applied

    def test_text_element가_검수신호를_싣는다(self):
        e = _dict_to_text_element({"id": "x", "review_grade": "high",
                                   "round_trip": 0.947})
        assert e.review_grade == "high" and round(e.round_trip, 3) == 0.947


class TestEmptyIsByteIdentical:
    """BE 가 안 보내는 평상 상태 = 새 필드가 바이트를 한 개도 안 늘린다."""

    def test_기본값이면_직렬화에_안_나온다(self):
        base = _dict_to_processing_meta({"routing_tier_used": "ZERO"})
        assert base.SerializeToString(deterministic=True) == \
            _dict_to_processing_meta({"routing_tier_used": "ZERO",
                                      "caption_disabled": False,
                                      "advanced_ai_applied": False}
                                     ).SerializeToString(deterministic=True)
        el = _dict_to_text_element({"id": "x"})
        assert el.SerializeToString(deterministic=True) == \
            _dict_to_text_element({"id": "x", "review_grade": "", "round_trip": 0.0}
                                  ).SerializeToString(deterministic=True)


class TestCustomerScope:
    """캐시 격리 열쇠 — 있으면 고객, 없으면 job_id. 제품 경로로 확인한다."""

    def test_요청에서_읽는다(self):
        req = pb.BrailleRequest(job_id="j", page_no=1, mode="b", customer_id="cust-A")
        assert PageTask.from_proto(req).customer_id == "cust-A"
        assert PageTask.from_proto(pb.BrailleRequest(job_id="j", page_no=1,
                                                     mode="b")).customer_id == ""

    def test_파이프라인이_고객으로_가른다(self, tmp_path, monkeypatch):
        from app.core import pipeline
        from app.utils import llm_cache
        monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))
        monkeypatch.setenv("SEMOJUM_NO_CAPTION", "1")

        async def scope_of(customer_id: str) -> str:
            # ★ 열쇠는 contextvar 라 **같은 task 안에서** 읽어야 한다. asyncio.run 을
            #   따로 돌리면 컨텍스트가 갈려 늘 빈 값으로 보인다.
            await pipeline.run(PageTask(
                job_id="job-1", page_no=1, mode="b", source_text="가나다라 마바사.",
                customer_id=customer_id))
            return llm_cache.scope()

        assert asyncio.run(scope_of("cust-A")) == "cust-A"
        assert asyncio.run(scope_of("")) == "job-1"     # BE 가 안 보내면 종전대로
        # 같은 입력이라도 고객이 다르면 다른 자리다(= 서로의 응답을 못 본다)
        llm_cache.set_scope("cust-A")
        k = llm_cache.key("caption", "같은 그림")
        llm_cache.set_scope("cust-B")
        assert llm_cache.key("caption", "같은 그림") != k
