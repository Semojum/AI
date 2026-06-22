"""로컬 단일 파일 테스트 러너.

서버 없이 파이프라인을 직접 실행하거나,
실행 중인 서버에 gRPC 요청을 보내 결과를 출력한다.

입력 파일: PDF (권장) 또는 PNG/JPG (자동으로 단일 페이지 PDF로 변환)

사용법:
    # 파이프라인 직접 실행 (서버 불필요)
    python test/local_runner.py --file path/to/page.pdf --mode c

    # 실행 중인 서버에 gRPC 요청
    python test/local_runner.py --file path/to/page.pdf --mode c --server localhost:50051

    # PNG 이미지도 허용 (자동 변환)
    python test/local_runner.py --file path/to/page.png --mode a --server localhost:50051
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tiff", ".bmp"}


def _read_as_pdf(file_path: str) -> bytes:
    """파일을 단일 페이지 PDF bytes로 읽는다.

    PDF 파일이면 그대로 반환.
    PNG/JPG 등 이미지 파일이면 Pillow로 단일 페이지 PDF로 변환.
    """
    p = Path(file_path)
    if not p.exists():
        print(f"[ERROR] 파일 없음: {file_path}")
        sys.exit(1)

    if p.suffix.lower() == ".pdf":
        return p.read_bytes()

    if p.suffix.lower() in _IMAGE_SUFFIXES:
        try:
            from PIL import Image
            import io
            print(f"[local_runner] 이미지 → PDF 변환: {p.name}")
            img = Image.open(p).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="PDF", resolution=300)
            return buf.getvalue()
        except ImportError:
            print("[ERROR] Pillow 미설치. `pip install Pillow` 후 재시도")
            sys.exit(1)

    print(f"[ERROR] 지원하지 않는 파일 형식: {p.suffix}  (지원: .pdf, .png, .jpg, .jpeg)")
    sys.exit(1)


async def run_direct(file_path: str, mode: str, job_id: str, load_models: bool = False, pipeline_timeout: float | None = None) -> None:
    """서버 없이 pipeline.run() 직접 호출."""
    from app.schemas.task import PageTask
    from app.core import pipeline

    if load_models:
        import asyncio as _asyncio
        from app.core.model_manager import model_manager
        print("[local_runner] HCXT 모델 로드 중…")
        await _asyncio.to_thread(model_manager._load_hcxt)
        print(f"[local_runner] 모델 상태: {model_manager.get_status()}")

    pdf_data = _read_as_pdf(file_path)
    task = PageTask(
        job_id=job_id,
        page_no=1,
        total_pages=1,
        pdf_data=pdf_data,
        mode=mode,
    )

    print(f"[local_runner] 직접 실행 — mode={mode} job_id={job_id} size={len(pdf_data):,} bytes")
    if pipeline_timeout is not None:
        import asyncio as _asyncio2
        from app.core import pipeline as _pipeline_mod
        result = await _asyncio2.wait_for(_pipeline_mod._run_pipeline(task), timeout=pipeline_timeout)
    else:
        result = await pipeline.run(task)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def run_grpc(file_path: str, mode: str, job_id: str, server_addr: str) -> None:
    """실행 중인 서버에 gRPC 요청."""
    try:
        from protos.generated import braille_service_pb2, braille_service_pb2_grpc
    except ImportError:
        print("[ERROR] proto 빌드 파일 없음 — `bash setup.sh` 실행 후 재시도")
        sys.exit(1)

    import grpc

    pdf_data = _read_as_pdf(file_path)
    channel = grpc.insecure_channel(server_addr)
    stub = braille_service_pb2_grpc.BrailleServiceStub(channel)

    request = braille_service_pb2.BrailleRequest(
        job_id=job_id,
        page_no=1,
        total_pages=1,
        pdf_data=pdf_data,
        mode=mode,
    )

    print(f"[local_runner] gRPC 요청 → {server_addr}  mode={mode} job_id={job_id} size={len(pdf_data):,} bytes")
    try:
        response = stub.ProcessPage(request, timeout=200)
        from google.protobuf.json_format import MessageToDict
        result = MessageToDict(response, preserving_proto_field_name=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except grpc.RpcError as e:
        print(f"[ERROR] gRPC 오류: {e.code()} — {e.details()}")
        sys.exit(1)
    finally:
        channel.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Semojum V2 AI 로컬 테스트 러너")
    parser.add_argument(
        "--file", required=True,
        help="입력 파일 경로 (PDF 권장, PNG/JPG는 자동 변환)"
    )
    parser.add_argument(
        "--mode", default="c", choices=["a", "b", "c"],
        help="처리 모드 (a: 텍스트 추출, b: 점자 변환, c: 통합)"
    )
    parser.add_argument("--job-id", default=None,
                        help="job_id (미지정 시 job_local_월일시분초_해시 자동 생성)")
    parser.add_argument(
        "--server", default=None,
        help="gRPC 서버 주소 (예: localhost:50051). 미지정 시 직접 실행."
    )
    parser.add_argument(
        "--load-models", action="store_true",
        help="직접 실행 시 HCXT 모델 로드 (실제 GPU 모델 E2E 테스트용)"
    )
    parser.add_argument(
        "--pipeline-timeout", type=float, default=None,
        help="파이프라인 타임아웃(초). 기본값은 config PAGE_TIMEOUT_SECONDS(180s). E2E GPU 테스트 시 증가 권장."
    )
    args = parser.parse_args()

    # 로컬 직접 실행 job_id = job_local_월일시분초_해시(미지정 시). 서버 경유는 grpc_server가 부여.
    job_id = args.job_id
    if job_id is None:
        from app.utils.job_id import generate
        job_id = generate("local")

    if args.server:
        run_grpc(args.file, args.mode, job_id, args.server)
    else:
        asyncio.run(run_direct(
            args.file, args.mode, job_id,
            load_models=args.load_models,
            pipeline_timeout=args.pipeline_timeout,
        ))


if __name__ == "__main__":
    main()
