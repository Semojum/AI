"""gRPC 서버 — PART 1 / PART 12.

BrailleServiceServicer가 BE의 BrailleRequest를 수신하여
pipeline.run()에 위임하고, 결과를 BrailleResponse proto로 직렬화해 반환한다.
"""

from __future__ import annotations

import grpc

from app.ai.braille.translator import translate_plain
from app.core.config import config
from app.core import pipeline
from app.schemas.task import PageTask
from app.utils import job_id as job_id_util
from app.utils.logger import get_logger

logger = get_logger(__name__)

try:
    from protos.generated import braille_service_pb2, braille_service_pb2_grpc
except ImportError as e:
    raise ImportError(
        "proto 빌드 파일을 찾을 수 없습니다. 먼저 `bash setup.sh` 또는 "
        "`bash protos/build.sh` 를 실행하세요."
    ) from e


def _dict_to_processing_meta(d: dict):
    meta = braille_service_pb2.ProcessingMeta()
    meta.processing_time_ms = d.get("processing_time_ms", 0)
    meta.pdf_layer_confidence = d.get("pdf_layer_confidence", 0.0)
    meta.routing_tier_used = d.get("routing_tier_used", "")
    meta.scan_only = d.get("scan_only", False)
    return meta


def _dict_to_quality_report(d: dict):
    qr = braille_service_pb2.QualityReport()
    qr.ocr_confidence_avg = d.get("ocr_confidence_avg", 0.0)
    for ce in d.get("critical_errors", []):
        err = qr.critical_errors.add()
        err.type = ce.get("type", "")
        err.element_id = str(ce.get("element_id", ""))
        err.message = ce.get("message", "")
    for rf in d.get("review_flags", []):
        flag = qr.review_flags.add()
        flag.type = rf.get("type", "")
        flag.element_id = str(rf.get("element_id", ""))
        flag.message = rf.get("message", "")
    return qr


def _dict_to_text_element(d: dict):
    elem = braille_service_pb2.TextElement()
    elem.id = str(d.get("id", ""))
    elem.type = d.get("type", "")
    elem.order = d.get("order", 0)
    elem.heading_level = d.get("heading_level", 0)
    elem.ocr_confidence = d.get("ocr_confidence", 0.0)
    elem.tn_text = d.get("tn_text", "")
    elem.is_blocked = d.get("is_blocked", False)
    elem.render_mode = d.get("render_mode", "")
    elem.visual_subtype = d.get("visual_subtype", "")
    elem.subtype_confidence = d.get("subtype_confidence", 0.0)
    elem.latex_string = d.get("latex_string", "")
    for c in d.get("contents", []):
        elem.contents.append(c)
    for rt in d.get("rule_trail", []):
        trail = elem.rule_trail.add()
        trail.rule_id = rt.get("rule_id", "")
        trail.source = rt.get("source", "")
        trail.section = rt.get("section", "")
        trail.title = rt.get("title", "")
        trail.excerpt = rt.get("excerpt", "")
        trail.priority = rt.get("priority", "primary")
        trail.line_no = rt.get("line_no", -1)
        trail.col_start = rt.get("col_start", 0)
        trail.col_end = rt.get("col_end", 0)
        trail.tag = rt.get("tag", "")
    # 시각 요소 복수 초안. BE proto §Draft대로 초안마다 자기 점자 줄(contents)을 싣는다.
    # 상위 elem.contents == drafts[selected_idx].contents (같은 값 — BE는 타입 구분 없이
    # 항상 elem.contents로 렌더하고, 피커를 붙이는 FE만 drafts를 추가로 읽는다).
    elem.selected_idx = d.get("selected_idx", 0)
    for dr in d.get("drafts", []):
        draft = elem.drafts.add()
        draft.text = dr.get("text", "")
        draft.label = dr.get("label", "")
        for c in dr.get("contents", []):
            draft.contents.append(c)
    return elem


def _dict_to_bounding_box(d: dict):
    bb = braille_service_pb2.BoundingBox()
    bb.id = str(d.get("id", ""))
    bb.x = d.get("x", 0)
    bb.y = d.get("y", 0)
    bb.x2 = d.get("x2", 0)
    bb.y2 = d.get("y2", 0)
    bb.type = d.get("type", "")
    bb.heading_level = d.get("heading_level", 0)
    bb.caption_ref = d.get("caption_ref", "")
    for flag in d.get("flags", []):
        bb.flags.append(flag)
    return bb


def _dump_response(task, resp) -> None:
    """디버그 모드: BE에 보낸 BrailleResponse를 storage에 JSON으로 저장(BE 대조용).
    경로: storage/jobs/{job}/temp/page_{no:03d}/response_sent.json
    """
    if not config.is_debug:
        return
    try:
        import json
        from pathlib import Path

        from google.protobuf.json_format import MessageToDict
        d = Path(f"storage/jobs/{task.job_id}/temp/page_{task.page_no:03d}")
        d.mkdir(parents=True, exist_ok=True)
        (d / "response_sent.json").write_text(
            json.dumps(MessageToDict(resp, preserving_proto_field_name=True),
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001 — 덤프 실패가 응답을 막지 않게
        logger.warning("응답 덤프 실패(무시): %s", exc)


def _build_error_response(job_id: str, page_no: int, message: str):
    resp = braille_service_pb2.BrailleResponse()
    resp.job_id = job_id
    resp.status = "BLOCKED"
    resp.page_number = page_no
    resp.quality_report.ocr_confidence_avg = 0.0
    err = resp.quality_report.critical_errors.add()
    err.type = "C1"
    err.element_id = "page"
    err.message = message
    return resp


def _build_proto_response(result: dict):
    resp = braille_service_pb2.BrailleResponse()
    resp.job_id = result.get("job_id", "")
    resp.status = result.get("status", "BLOCKED")
    resp.page_number = result.get("page_number", 0)

    if "processing_meta" in result:
        resp.processing_meta.CopyFrom(_dict_to_processing_meta(result["processing_meta"]))

    if "quality_report" in result:
        resp.quality_report.CopyFrom(_dict_to_quality_report(result["quality_report"]))

    # mode a, c: image dimensions(BE 협의본은 "WIDTHxHEIGHT" 문자열 단일 필드) + bounding boxes
    # 2026-08-05: image_resolution(문자열 합침)에서 int 두 필드로 복원 — proto 주석 참조.
    resp.image_width = int(result.get("image_width", 0))
    resp.image_height = int(result.get("image_height", 0))
    for bb in result.get("bounding_box_list", []):
        resp.bounding_box_list.append(_dict_to_bounding_box(bb))

    for te in result.get("text_list", []):
        resp.text_list.append(_dict_to_text_element(te))

    for te in result.get("braille_text_list", []):
        resp.braille_text_list.append(_dict_to_text_element(te))

    # 사용량. BLOCKED에도 싣는다 — 막혔어도 자원은 썼다.
    resp.usage_report.CopyFrom(_dict_to_usage_report(result.get("usage") or {}))

    return resp


_PB = braille_service_pb2
_LAYOUT = {"text": _PB.PAGE_LAYOUT_TEXT, "formula": _PB.PAGE_LAYOUT_FORMULA,
           "table": _PB.PAGE_LAYOUT_TABLE, "visual": _PB.PAGE_LAYOUT_VISUAL}


def _dict_to_usage_report(c: dict):
    """`req_log.usage_report()` dict → proto. 사용량은 관측값이라 무슨 일이 있어도
    응답을 막지 않는다 — 빈 dict가 오면 0으로 채운 메시지를 돌려준다.

    ★ **금액은 나가지 않는다**(BE 협의 2026-08-18). AI는 측정값(토큰·GPU 시간·쪽 유형)만
    싣고, 단가표·환율·카드 수수료·크레딧 배율은 BE의 관리 변수다. 관리자 페이지에서
    수시로 바뀌는 값을 AI가 재컴파일해야 바뀌는 자리에 두지 않기 위해서다.
    AI 쪽 원가 추정치는 메트릭 JSONL에만 남는다(우리 관측용, 정본 아님).
    """
    r = _PB.UsageReport()
    if not c:
        return r
    r.layout_type = _LAYOUT.get(c.get("layout_type", ""), _PB.PAGE_LAYOUT_UNSPECIFIED)
    r.gpu_time_ms = int(c.get("gpu_time_ms", 0))
    for m in c.get("models", []):
        pm = r.models.add()
        pm.model = str(m.get("model", ""))
        pm.calls = int(m.get("calls", 0))
        pm.input_tokens = int(m.get("input_tokens", 0))
        pm.output_tokens = int(m.get("output_tokens", 0))
    return r


# 배압(M2, 2026-08-02) — admission 카운터. asyncio 단일 스레드 협조 스케줄링이라
# 증감 사이 await가 없는 한 락 불필요. maximum_concurrent_rpcs(config.max_queued_rpcs)는
# 넉넉하게 열어 두고, 실제 처리 상한은 여기서 강제해 초과분을 큐잉 대신 즉시 거절한다.
_in_flight = 0

# 꼬리말은 32칸 안에 들어가는 짧은 문자열이다. 본문을 이 RPC로 보내는 오용을 막되,
# 잘라내지 않고 거절한다 — 조용히 자르면 BE가 잘린 줄 모른다.
_TRANSLATE_TEXT_MAX = 200


class BrailleServiceServicer(braille_service_pb2_grpc.BrailleServiceServicer):
    async def ProcessPage(
        self,
        request: braille_service_pb2.BrailleRequest,
        context: grpc.aio.ServicerContext,
    ) -> braille_service_pb2.BrailleResponse:
        global _in_flight
        if _in_flight >= config.max_concurrent_pages:
            logger.warning(
                "동시 처리 상한(%d) 초과 — RESOURCE_EXHAUSTED 즉시 거절 job=%s page=%d",
                config.max_concurrent_pages,
                getattr(request, "job_id", "?"), getattr(request, "page_no", 0),
            )
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                f"AI 서버 동시 처리 상한({config.max_concurrent_pages}페이지) 초과 — 잠시 후 재시도",
            )
            return  # context.abort()가 예외를 던져 실제로는 도달하지 않음

        _in_flight += 1
        try:
            return await self._process_page(request, context)
        finally:
            _in_flight -= 1

    async def TranslateText(
        self,
        request: braille_service_pb2.TranslateTextRequest,
        context: grpc.aio.ServicerContext,
    ) -> braille_service_pb2.TranslateTextReply:
        """짧은 묵자 → 점자. 꼬리말 입력·수정 때 BE가 1회 호출한다(조판 가이드 §6).

        본문과 **같은 rule-based 경로**를 타고 LLM·MinerU를 거치지 않으므로 즉시 끝난다.
        그래서 `_in_flight` 배압에 넣지 않는다 — GPU도 안 쓰는 호출을 페이지 상한에 태우면
        점역 처리량만 깎인다.

        32칸 조판은 하지 않는다. 페이지행 배치는 BE·FE가 braille-assist `page_row`로 한다.
        """
        text = (request.text or "").strip()
        if not text:
            return braille_service_pb2.TranslateTextReply(braille="")
        if len(text) > _TRANSLATE_TEXT_MAX:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                f"TranslateText는 짧은 묵자 전용이다 — {_TRANSLATE_TEXT_MAX}자 이하 "
                f"(받은 길이 {len(text)}). 본문 점역은 ProcessPage를 쓸 것",
            )
        try:
            braille = translate_plain(text)
        except Exception as exc:
            logger.exception("TranslateText 실패 text=%r: %s", text[:40], exc)
            await context.abort(
                grpc.StatusCode.INTERNAL, f"점역 실패: {type(exc).__name__}: {exc}"
            )
            return
        logger.info("TranslateText peer=%s %d자 → %d셀", context.peer(), len(text), len(braille))
        return braille_service_pb2.TranslateTextReply(braille=braille)

    async def _process_page(
        self,
        request: braille_service_pb2.BrailleRequest,
        context: grpc.aio.ServicerContext,
    ) -> braille_service_pb2.BrailleResponse:
        try:
            task = PageTask.from_proto(request)
        except Exception as exc:
            logger.exception("from_proto failed job=%s: %s", getattr(request, "job_id", "?"), exc)
            return _build_error_response(
                job_id=getattr(request, "job_id", ""),
                page_no=getattr(request, "page_no", 0),
                message=f"요청 파싱 실패: {type(exc).__name__}: {exc}",
            )

        # job_id는 BE가 보낸 값을 정본으로 그대로 사용한다.
        # BE는 이 job_id로 요청·응답을 상관(correlation)·멱등 판단하므로 절대 바꾸면 안 된다.
        # (예전엔 출처 구분용으로 새로 생성·덮어썼으나, 응답 job_id가 달라져 BE가
        #  완료를 인지 못하고 같은 페이지를 무한 재전송하는 버그가 있었다.)
        # BE가 job_id를 비워 보낸 경우(로컬 직접 호출 등)에만 출처를 붙여 새로 생성한다.
        if not task.job_id:
            source = job_id_util.source_from_peer(context.peer())
            task.job_id = job_id_util.generate(source)

        logger.info(
            "grpc request received peer=%s job=%s page=%d/%d mode=%s",
            context.peer(), task.job_id, task.page_no, task.total_pages, task.mode,
        )

        try:
            result = await pipeline.run(task)
            resp = _build_proto_response(result)
            _dump_response(task, resp)   # 디버그 시 BE에 보낸 응답을 storage에 저장
            return resp
        except Exception as exc:
            logger.exception(
                "pipeline error job=%s page=%d: %s", task.job_id, task.page_no, exc
            )
            return _build_error_response(
                job_id=task.job_id,
                page_no=task.page_no,
                message=f"파이프라인 오류: {type(exc).__name__}: {exc}",
            )


async def serve() -> None:
    # maximum_concurrent_rpcs는 실제 처리 상한(max_concurrent_pages)보다 넉넉히 잡는다.
    # 여기를 처리 상한과 같이 두면 초과 요청이 gRPC 레이어에서 "조용히" 큐잉되어
    # BrailleServiceServicer의 RESOURCE_EXHAUSTED 거절 코드에 아예 도달하지 못한다.
    # 실제 admission 제어는 ProcessPage의 _in_flight 카운터가 한다(배압, 2026-08-02).
    server = grpc.aio.server(
        maximum_concurrent_rpcs=config.max_queued_rpcs,
        options=[
            ("grpc.max_receive_message_length", config.max_grpc_message_bytes),
            ("grpc.max_send_message_length", config.max_grpc_message_bytes),
        ]
    )
    logger.info(
        "동시 처리 상한: %d페이지 (gRPC 큐 상한 %d)",
        config.max_concurrent_pages, config.max_queued_rpcs,
    )
    braille_service_pb2_grpc.add_BrailleServiceServicer_to_server(
        BrailleServiceServicer(), server
    )
    listen_addr = f"[::]:{config.grpc_port}"
    if config.tls_enabled:
        with open(config.tls_cert_path, "rb") as f:
            cert = f.read()
        with open(config.tls_key_path, "rb") as f:
            key = f.read()
        credentials = grpc.ssl_server_credentials([(key, cert)])
        server.add_secure_port(listen_addr, credentials)
        logger.info("gRPC server listening on %s (TLS)", listen_addr)
    else:
        server.add_insecure_port(listen_addr)
        logger.info("gRPC server listening on %s (insecure)", listen_addr)
    await server.start()
    await server.wait_for_termination()
