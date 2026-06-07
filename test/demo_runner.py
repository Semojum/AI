"""BE 데모 러너 (T5-2 스켈레톤).

demo_set(T5-1)의 각 페이지를 파이프라인에 통과시켜 점역 결과를 출력하고,
`expected_braille`가 채워진 페이지는 출력과 대조해 일치 여부를 보고한다.
FALLBACK 사용률(<15% 목표)도 집계한다 — 실모델 대조는 --load-models 필요.

현주 파트가 미구현이므로 입력은 demo_set의 TEXT_NATIVE 핸드오프(txt_result)를 그대로
storage 경로에 써서 파이프라인이 읽게 한다(ZERO 라우팅, 모델 불필요).

사용법:
    python test/demo_runner.py                 # 전 페이지
    python test/demo_runner.py --id p01        # 특정 페이지
    python test/demo_runner.py --load-models   # 실모델 E2E(HCXT 로드, FALLBACK 의미있음)
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_DEMO_DIR = Path(__file__).parent / "test_data" / "demo_set"


def _dummy_pdf() -> bytes:
    from PIL import Image
    img = Image.new("RGB", (595, 842), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PDF")
    return buf.getvalue()


def load_pages(only_id: str | None = None) -> list[dict]:
    """demo_set/manifest.json 기준으로 페이지 JSON을 로드."""
    manifest = json.loads((_DEMO_DIR / "manifest.json").read_text(encoding="utf-8"))
    pages = []
    for entry in manifest["pages"]:
        if only_id and entry["demo_id"] != only_id:
            continue
        pages.append(json.loads((_DEMO_DIR / entry["file"]).read_text(encoding="utf-8")))
    return pages


def _write_handoff(page: dict) -> str:
    """페이지의 txt_result를 파이프라인이 읽는 storage 경로에 기록. job_id 반환."""
    job_id = page["txt_result"]["meta"]["job_id"]
    p = Path(f"storage/jobs/{job_id}/temp/page_001/data/001_txt_result.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(page["txt_result"], ensure_ascii=False, indent=2), encoding="utf-8")
    return job_id


def _braille_lines(result: dict) -> list[str]:
    """결과의 braille_text_list를 읽기순서 줄 목록으로 평탄화."""
    lines: list[str] = []
    for b in result.get("braille_text_list", []):
        lines.extend(b.get("contents") or [])
    return lines


async def run(only_id: str | None, load_models: bool) -> int:
    from app.core import pipeline
    from app.schemas.task import PageTask

    if load_models:
        from app.core.model_manager import model_manager
        print("[demo_runner] HCXT 모델 로드 중…")
        await asyncio.to_thread(model_manager._load_hcxt)

    pages = load_pages(only_id)
    if not pages:
        print(f"[demo_runner] 페이지 없음 (id={only_id})")
        return 1

    total_elems = fallback_elems = 0
    compared = matched = 0
    pdf = _dummy_pdf()

    for page in pages:
        job_id = _write_handoff(page)
        task = PageTask(job_id=job_id, page_no=1, total_pages=1, pdf_data=pdf, mode="c")
        result = await pipeline.run(task)

        # FALLBACK 집계(요소 단위 routing_tier가 있으면 — 실모델에서만 의미)
        for b in result.get("braille_text_list", []):
            total_elems += 1
            if b.get("routing_tier") == "FALLBACK":
                fallback_elems += 1

        got = _braille_lines(result)
        expected = page.get("expected_braille")
        status = result.get("status")
        if expected:
            compared += 1
            ok = got == expected
            matched += int(ok)
            mark = "일치" if ok else "불일치"
            print(f"[{page['demo_id']}] {status} · {page['title']} — 기대대조 {mark} ({len(got)}줄)")
        else:
            print(f"[{page['demo_id']}] {status} · {page['title']} — 기대점역 미입력, 출력 {len(got)}줄")

    print("\n── 요약 ──")
    print(f"페이지 {len(pages)}개 처리")
    fb_rate = (fallback_elems / total_elems * 100) if total_elems else 0.0
    print(f"FALLBACK 사용률 {fb_rate:.1f}% ({fallback_elems}/{total_elems})  목표 < 15%"
          + ("" if load_models else "  ※ ZERO 실행이라 0 — 실모델은 --load-models"))
    if compared:
        print(f"기대점역 대조 {matched}/{compared} 일치")
    else:
        print("기대점역(expected_braille) 미입력 — 점역사 검토 기준 작성 필요(T5-1)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="BE 데모 러너 (T5-2 스켈레톤)")
    parser.add_argument("--id", default=None, help="특정 demo_id만 실행 (예: p01)")
    parser.add_argument("--load-models", action="store_true", help="HCXT 실모델 로드 E2E")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.id, args.load_models)))


if __name__ == "__main__":
    main()
