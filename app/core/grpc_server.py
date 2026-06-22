"""gRPC 서버 — PART 1 / PART 12.

BrailleServiceServicer가 BE의 BrailleRequest를 수신하여
pipeline.run()에 위임하고, 결과를 BrailleResponse proto로 직렬화해 반환한다.
"""

from __future__ import annotations

import grpc

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
    qr.line_overflow_rate = d.get("line_overflow_rate", 0.0)
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
    # 복수 초안 (단계 4 T4-2) — proto Draft/TextElement.drafts 필요(build.sh 재생성 후 동작)
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
    resp.quality_report.line_overflow_rate = 0.0
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

    # mode a, c: image dimensions + bounding boxes
    resp.image_width = result.get("image_width", 0)
    resp.image_height = result.get("image_height", 0)
    for bb in result.get("bounding_box_list", []):
        resp.bounding_box_list.append(_dict_to_bounding_box(bb))

    for te in result.get("text_list", []):
        resp.text_list.append(_dict_to_text_element(te))

    for te in result.get("braille_text_list", []):
        resp.braille_text_list.append(_dict_to_text_element(te))

    return resp


class BrailleServiceServicer(braille_service_pb2_grpc.BrailleServiceServicer):
    async def ProcessPage(
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

        # job_id 네이밍 — peer로 출처(BE 원격/로컬) 판별해 job_be_/job_local_ 부여.
        # gRPC는 동기 req/resp라 job_id를 바꿔도 BE 응답 상관관계는 유지된다(응답이 곧 답).
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
    server = grpc.aio.server(
        options=[
            ("grpc.max_receive_message_length", config.max_grpc_message_bytes),
            ("grpc.max_send_message_length", config.max_grpc_message_bytes),
        ]
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
