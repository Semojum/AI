"""
전체 파이프라인 실행 스크립트.
usage: python run_pipeline.py [pdf_path] [job_id] [page_no]
"""
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.ai.preprocessor.pdf_analyzer import analyze_pdf
from app.ai.parser.mineru_runner import run as mineru_run
from app.ai.builder.result_builder import build


def _smi_snapshot() -> dict | None:
    """nvidia-smi에서 GPU0 메모리(MiB) 스냅샷 반환."""
    try:
        out = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=index,name,memory.used,memory.free,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        ).stdout.strip().splitlines()
        results = []
        for line in out:
            idx, name, used, free, total, util = [s.strip() for s in line.split(",")]
            results.append({
                "idx": idx, "name": name,
                "used": int(used), "free": int(free),
                "total": int(total), "util": int(util),
            })
        return results
    except Exception:
        return None


def _torch_snapshot() -> dict:
    try:
        import torch
        if torch.cuda.is_available():
            return {
                "allocated_gb": torch.cuda.memory_allocated() / 1024 ** 3,
                "reserved_gb":  torch.cuda.memory_reserved()  / 1024 ** 3,
            }
    except ImportError:
        pass
    return {"allocated_gb": None, "reserved_gb": None}


def _print_snapshot(label: str, torch_snap: dict, smi_snaps: list | None) -> None:
    print(f"\n--- VRAM [{label}] ---")
    if torch_snap["allocated_gb"] is not None:
        print(f"  torch.cuda.memory_allocated : {torch_snap['allocated_gb']:.3f} GB  "
              f"(reserved: {torch_snap['reserved_gb']:.3f} GB)")
    else:
        print("  torch.cuda: 현재 프로세스 미사용 (MinerU는 별도 subprocess)")
    if smi_snaps:
        for g in smi_snaps:
            print(f"  nvidia-smi GPU{g['idx']} ({g['name']}): "
                  f"used={g['used']} MiB / total={g['total']} MiB, "
                  f"free={g['free']} MiB, util={g['util']}%")
    else:
        print("  nvidia-smi: 조회 실패")
    print()


class _VramPoller:
    """MinerU subprocess 실행 중 nvidia-smi를 2초마다 폴링해 피크를 기록."""

    def __init__(self, interval: float = 2.0):
        self._interval = interval
        self._stop = threading.Event()
        self._samples: list[list] = []
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()

    def _loop(self) -> None:
        while not self._stop.is_set():
            snap = _smi_snapshot()
            if snap:
                self._samples.append(snap)
            self._stop.wait(self._interval)

    def peak(self) -> list | None:
        if not self._samples:
            return None
        gpus = len(self._samples[0])
        peak = []
        for i in range(gpus):
            best = max(self._samples, key=lambda s: s[i]["used"])
            peak.append({**best[i]})
        return peak


PDF_PATH = sys.argv[1] if len(sys.argv) > 1 else "test/samples/test.pdf"
JOB_ID   = sys.argv[2] if len(sys.argv) > 2 else "test-job-001"
PAGE_NO  = int(sys.argv[3]) if len(sys.argv) > 3 else 1
DEBUG    = "--debug" in sys.argv

print(f"[pipeline] PDF={PDF_PATH}, job_id={JOB_ID}, page_no={PAGE_NO}")

extraction_method = analyze_pdf(PDF_PATH, PAGE_NO)
print(f"[pipeline] extraction_method={extraction_method}")

before_torch = _torch_snapshot()
before_smi   = _smi_snapshot()
_print_snapshot("MinerU 실행 전", before_torch, before_smi)

poller = _VramPoller(interval=2.0)
poller.start()
merged_layout = mineru_run(PDF_PATH, PAGE_NO, JOB_ID, extraction_method, debug=DEBUG)
poller.stop()

after_torch = _torch_snapshot()
after_smi   = _smi_snapshot()
peak_smi    = poller.peak()

_print_snapshot("MinerU 실행 중 (피크)", before_torch, peak_smi)
_print_snapshot("MinerU 실행 후",       after_torch,  after_smi)

result = build(merged_layout, JOB_ID, PAGE_NO, extraction_method, debug=DEBUG, pdf_path=PDF_PATH)
print(f"[pipeline] 완료: {len(result['elements'])}개 요소")
