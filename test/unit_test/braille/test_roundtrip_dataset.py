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
    "numbers": {"build": 0.95, "test": 0.90},  # 현재 1.0 (소수점·자릿점 버그 수정 후) — 결정적
    # 로마자표 ⠴·대문자단어 ⠠⠠ 런은 정상 복원. 잔여 실패는 아래첨자(B₉)·밑줄(_)·⠴없는 ⠠⠠
    # 한글충돌(TV=썰) — 천장. symbol_table 규정-교정(FIX-11/12)으로 역인덱스 충돌이 바뀌어
    # build 0.43으로 하향 → floor를 측정값에 맞춤(역점역=근사·표시용). 디코더 개선 시 상향.
    "roman": {"build": 0.40, "test": 0.45},
    # 규정-정확 줄임표 …=⠠⠠⠠(대문자단어 ⠠⠠와 충돌)·가운뎃점 ·=⠐⠆ 등은 역점역에서 내재 모호
    # → build 0.88(15/17). 역점역은 근사·표시용이라 floor를 측정값에 맞춤(회귀 감지 유지).
    "punctuation": {"build": 0.85, "test": 0.90},
    # 고유 점형 기호는 100% 복원. 점형 충돌(한글 61·기호 41·원문자 22)은 ambiguous로 floor 제외.
    "symbols": {"build": 0.95, "test": 0.95},
    # 수학식(첨자·근호·분수·연산자·그리스) — decode(math=True) 구역. 현재 build/test 1.0.
    # 문맥 인식 디코딩(P7)으로 수식 셀이 한글로 오역되던 문제 해소 → 결정적이라 floor 높게.
    "math": {"build": 0.95, "test": 0.90},
}


def _load(type_name: str) -> dict:
    path = _DATA_DIR / f"{type_name}.json"
    if not path.exists():
        pytest.skip(f"{type_name}.json 미생성 (etc/build_roundtrip_pairs.py)")
    return json.loads(path.read_text(encoding="utf-8"))


def _accuracy(pairs: list[dict], split: str) -> tuple[int, int, list]:
    # 모호(ambiguous) 쌍은 floor에서 제외 — 같은 점형이 여러 뜻이라 블라인드 복원 불가(천장).
    rows = [p for p in pairs if p["split"] == split and not p.get("ambiguous")]
    ok, fails = 0, []
    for p in rows:
        # 수식 쌍(math=True)은 요소 type=formula를 가정해 수식 구역으로 디코드.
        got = decode(p["braille_unicode"], math=p.get("math", False))
        if got.replace(" ", "") == p["korean"].replace(" ", ""):
            ok += 1
        else:
            fails.append(p["korean"])
    return ok, len(rows), fails


@pytest.mark.parametrize("type_name", list(_FLOORS))
class TestRoundtripAccuracy:
    def test_split_비율_7_3(self, type_name):
        d = _load(type_name)
        b, t = d["counts"]["build"], d["counts"]["test"]
        # 7:3은 표본이 클 때 성립(안정 해시 기대값) — 작은 데이터셋은 편차가 커 완화.
        if b + t >= 40:
            ratio = t / (b + t)
            assert 0.20 <= ratio <= 0.40, f"{type_name} test 비율 {ratio:.2f} (목표 0.3)"
        else:
            assert t >= 1 and b >= t, f"{type_name} 표본 작음(build {b}/test {t})"

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
