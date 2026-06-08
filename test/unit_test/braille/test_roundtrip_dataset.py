"""역점역 데이터셋 회귀 — 유형별 묵자↔점자 쌍 round-trip 정확도 측정·고정.

규정/지침 기반 build/test(7:3) 쌍으로 `decode(braille)==korean` 정확도를 측정한다.
유형별 floor(아래 _FLOORS) 이상이어야 통과 → 디코더 개선은 정확도를 올리고,
회귀(악화)는 floor를 깨 잡아낸다.

  · 한글 음절: braillify 문맥 축약으로 per-음절 역맵은 ~90% 천장 → 측정·고정만(태민 결정).
  · 숫자·로마자·문장부호 등: 결정적이라 floor를 높게(거의 1.0) 잡아 실제 버그를 고정.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.utils.braille_back import decode

_DATA_DIR = Path(__file__).parent.parent.parent / "test_data" / "roundtrip_pairs"

# 유형별 split 정확도 하한(측정값보다 약간 아래로 고정 — 회귀 감지, 개선 허용).
_FLOORS: dict[str, dict[str, float]] = {
    "hangul": {"build": 0.85, "test": 0.88},   # 현재 build 0.87 / test 0.94 (문맥 축약 천장)
}


def _load(type_name: str) -> dict:
    path = _DATA_DIR / f"{type_name}.json"
    if not path.exists():
        pytest.skip(f"{type_name}.json 미생성 (etc/build_roundtrip_pairs.py)")
    return json.loads(path.read_text(encoding="utf-8"))


def _accuracy(pairs: list[dict], split: str) -> tuple[int, int, list]:
    rows = [p for p in pairs if p["split"] == split]
    ok, fails = 0, []
    for p in rows:
        if decode(p["braille_unicode"]).replace(" ", "") == p["korean"].replace(" ", ""):
            ok += 1
        else:
            fails.append(p["korean"])
    return ok, len(rows), fails


@pytest.mark.parametrize("type_name", list(_FLOORS))
class TestRoundtripAccuracy:
    def test_split_비율_7_3(self, type_name):
        d = _load(type_name)
        b, t = d["counts"]["build"], d["counts"]["test"]
        ratio = t / max(b + t, 1)
        assert 0.22 <= ratio <= 0.38, f"{type_name} test 비율 {ratio:.2f} (목표 0.3)"

    @pytest.mark.parametrize("split", ["build", "test"])
    def test_역점역_정확도_floor(self, type_name, split):
        d = _load(type_name)
        ok, n, fails = _accuracy(d["pairs"], split)
        acc = ok / max(n, 1)
        floor = _FLOORS[type_name][split]
        assert acc >= floor, (
            f"{type_name}/{split} 정확도 {acc:.3f} < floor {floor} "
            f"({ok}/{n}); 실패 예: {fails[:8]}"
        )
