"""칸수 일치율 계기(`tools/kpi/spacing_kpi.py`)의 자체 점검을 CI 에서 돌린다.

계기가 조용히 썩으면 A/B 판정이 통째로 거짓이 된다. 정렬·칸 세기·조항 앵커의
반례(한글 `요소`가 합집합으로, 글머리표가 제15항으로, 로마자 A 가 단위로 잡히던
과검출 3종)를 도구 안 `selftest()` 가 들고 있으므로 그대로 부른다.
"""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]      # <저장소 루트>
TOOL = ROOT / "tools" / "kpi" / "spacing_kpi.py"


def test_spacing_kpi_selftest():
    spec = importlib.util.spec_from_file_location("spacing_kpi", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.selftest() == 0
