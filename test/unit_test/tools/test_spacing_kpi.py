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


def test_ruler_arms_actually_differ():
    """A/B 두 팔이 **진짜로 갈리는지**. 스위치가 안 읽히면 같은 값이 나와 라운드가 무효다.

    2026-09-08 실측 사고: 이 자의 `RULER` A/B 한 판이 스위치 없는 옛 판을 돌려
    두 팔의 수치가 소수점까지 같았다. 사람이 표를 보고서야 알았다.
    갈리는 것은 제29항 로마자표 ⠴ 하나뿐이다(`translate_plain` 의 `force_roman=True`).
    """
    spec = importlib.util.spec_from_file_location("spacing_kpi", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    body, plain = mod.pick_translate("body"), mod.pick_translate("plain")
    s = "www.ebsi.co.kr"                       # 한글이 없는 줄 = force_roman 이 발동하는 자리
    assert plain(s) != body(s)
    assert plain(s) == "⠴" + body(s)
