"""저장된 job의 BrailleResponse(= AI가 BE에 실제로 보낸 응답)를 재구성해 출력.

gRPC 응답은 동기 req/resp라 따로 저장하지 않지만, 경계파일(txt_result.json)이 storage에
남아 있으면 그걸로 응답을 그대로 다시 만들어 BE에 보낸 것과 동일한 proto를 보여준다.
BE에 "내가 보낸 데이터가 이거다"라고 보여줄 때 사용.

사용:
    python dump_response.py <job_id> [mode=c] [page_no=1]
예:
    python dump_response.py job_local_0622184743_d1ace1 c 1
"""
import asyncio
import json
import sys

from google.protobuf.json_format import MessageToDict

from app.core import pipeline
from app.core.grpc_server import _build_proto_response
from app.schemas.task import PageTask


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    job_id = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "c"
    page_no = int(sys.argv[3]) if len(sys.argv) > 3 else 1

    out = asyncio.run(pipeline.run(PageTask(
        job_id=job_id, page_no=page_no, total_pages=1,
        pdf_data=b"", mode=mode, source_text="",
    )))
    resp = _build_proto_response(out)
    as_dict = MessageToDict(resp, preserving_proto_field_name=True)
    print(json.dumps(as_dict, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
