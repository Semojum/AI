"""
test.pdf 전체 페이지 파이프라인 실행 스크립트.
usage: python run_all_pages.py [pdf_path] [job_id] [total_pages]
"""
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

PDF_PATH    = sys.argv[1] if len(sys.argv) > 1 else "test/samples/test.pdf"
JOB_ID      = sys.argv[2] if len(sys.argv) > 2 else "test-job-001"
TOTAL_PAGES = int(sys.argv[3]) if len(sys.argv) > 3 else 10

errors = []

for page_no in range(1, TOTAL_PAGES + 1):
    print(f"\n{'='*60}", flush=True)
    print(f"[PAGE {page_no}/{TOTAL_PAGES}]", flush=True)
    print('='*60, flush=True)

    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, "run_pipeline.py", PDF_PATH, JOB_ID, str(page_no), "--debug"],
        text=True,
    )
    elapsed = time.time() - t0

    if proc.returncode != 0:
        errors.append(page_no)
        print(f"[ERROR] page {page_no} 실패", flush=True)
        continue

    result_path = Path(f"storage/jobs/{JOB_ID}/temp/page_{page_no:03d}/data/001_txt_result.json")
    if not result_path.exists():
        errors.append(page_no)
        print(f"[ERROR] 결과 파일 없음: {result_path}", flush=True)
        continue

    data = json.loads(result_path.read_text(encoding="utf-8"))
    elements = data["elements"]
    counts = Counter(e["type"] for e in elements)

    print(f"  완료 ({elapsed:.0f}s)", flush=True)
    print(f"  extraction_method : {data['meta']['extraction_method']}", flush=True)
    print(f"  총 요소            : {len(elements)}개", flush=True)
    for t, c in sorted(counts.items()):
        print(f"    {t:<16}: {c}", flush=True)

    captions = [(e["type"], e["content"]) for e in elements
                if e["type"] in ("image", "cartoon", "chart")]
    if captions:
        print(f"  캡셔닝 결과:", flush=True)
        for img_type, content in captions:
            snippet = content[:100].replace("\n", " ")
            print(f"    [{img_type}] {snippet}...", flush=True)

print(f"\n{'='*60}", flush=True)
if errors:
    print(f"오류 페이지: {errors}", flush=True)
    sys.exit(1)
else:
    print(f"전체 {TOTAL_PAGES}페이지 완료.", flush=True)
