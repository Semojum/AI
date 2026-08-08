"""규정 예문 전 절 스윕 — 14개 절 709쌍 (2026-08-06).

## 왜 이 파일이 있나

`test_regulation_examples.py`는 **4개 절**(01·02·03·06)의 `decode_ok` 단어 쌍만 돌린다.
나머지 10개 절은 아무도 돌려 본 적이 없었고, 그래서 데이터셋 결함 445건과 우리 결함
2건(숨김표 ☆·◇ 점형, 반복 `×××`)이 오래 숨어 있었다.

## 데이터 이력 — 기대값을 왜 믿어도 되나

`braille_unicode`(기대 점자)는 옛 변환기로 만들어져 **709쌍 중 445쌍이 틀렸다**.
  · 426쌍 — `[?x]` 플레이스홀더(그 시점 변환표 구멍)
  · 19쌍 — 값은 멀쩡한데 **조용히 틀림**: ⠛ 누락 · ⠗ 삽입 · **⠵→⠿ 오인**
1차 자료는 `brf_ascii`(규정 원문 전사)이고 `braille_unicode`는 파생물이므로,
현재 변환기로 다시 만들어 반영했다(2026-08-06). 우리 출력과 재생성값이 11건 표본에서
9건 일치해 재생성이 옳음을 확인했다(저장값 일치는 0건).

## 아티팩트를 왜 걸러내나

규정 PDF에서 예문을 뽑을 때 섞여 들어온 것들이다. 걸러내지 않으면 **우리 결함이 아닌 것을
고치려다 진짜 결함을 놓친다** — 실제로 거르기 전 준수율이 18.9%로 보였다.
  · 머리글 `￭한국점자규정￭` 24건
  · **표 열·행 어긋남** 43건 — 예: 절 10 로마자 이름 표가 정확히 한 행씩 밀렸다
    (묵자 '비'(=B) ↔ 기대 ⠉(=c), 13/13 전부 +1)
  · 문장 꼬리 조각 9건

## 이 테스트가 지키는 것

준수율이 **떨어지지 않는 것**. 지금 값은 목표가 아니라 실측 바닥선이다
(2026-08-06 기준 322건 중 275건 = 85.4%). 올라가면 바닥선을 올린다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.ai.braille.translator import translate_tagged_text

PAIRS = Path(__file__).parents[2] / "test_data" / "regulation_pairs"
_HANGUL = re.compile(r"[가-힣]")
_TAIL = re.compile(r"^(다\.|는다|니다\.|한다\.|된다\.|따른다|적는다)$")

# 2026-08-06 실측 바닥선. **떨어지면 회귀다.**
BASELINE_TOTAL = 322
BASELINE_PASS = 275


def _is_artifact(korean: str, expected: str) -> str | None:
    """PDF 추출 아티팩트면 그 종류, 아니면 None."""
    if "￭" in korean:
        return "머리글"
    if _TAIL.match(korean.strip()):
        return "문장 꼬리 조각"
    n = len(_HANGUL.findall(korean))
    if n >= 2 and len(expected.strip()) < n:
        return "표 열·행 어긋남"
    if not expected.strip():
        return "기대값 빈 값"
    return None


def _load() -> tuple[list[tuple[str, str, str, str]], dict[str, int]]:
    """(절, 항, 묵자, 기대점자) 목록 + 아티팩트 집계.

    문장 예문은 뺀다 — 조판·띄어쓰기가 섞여 단일 함수로 재현되지 않는다.
    """
    cases, art = [], {}
    for f in sorted(PAIRS.glob("section_*.json")):
        sec = f.name.split("_")[1]
        d = json.loads(f.read_text(encoding="utf-8"))
        for p in (d if isinstance(d, list) else d.get("pairs", [])):
            ko = p.get("korean", "") or ""
            exp = p.get("braille_unicode", "") or ""
            if not ko or not exp or " " in ko or "\n" in ko:
                continue
            kind = _is_artifact(ko, exp)
            if kind:
                art[kind] = art.get(kind, 0) + 1
                continue
            cases.append((sec, p.get("item", ""), ko, exp))
    return cases, art


CASES, ARTIFACTS = _load()


class TestDatasetIntegrity:
    """데이터셋 자체가 성한가 — 여기가 깨지면 아래 준수율은 의미가 없다."""

    def test_기대값에_플레이스홀더가_없다(self) -> None:
        """`[?x]`는 옛 변환기가 못 푼 자리다. 426쌍이 이랬다(2026-08-06 복구)."""
        bad = [(s, i, k) for s, i, k, e in CASES if "[?" in e]
        assert not bad, f"{len(bad)}쌍: {bad[:3]}"

    def test_기대값이_전부_점자다(self) -> None:
        bad = []
        for s, i, k, e in CASES:
            junk = {c for c in e if not ("⠀" <= c <= "⣿" or c in " \n")}
            if junk:
                bad.append((s, k, sorted(junk)[:4]))
        assert not bad, f"{len(bad)}쌍: {bad[:3]}"

    def test_대상_수가_유지된다(self) -> None:
        """쌍이 줄면 누가 데이터를 지운 것이다."""
        assert len(CASES) >= BASELINE_TOTAL, f"{len(CASES)} < {BASELINE_TOTAL}"

    def test_아티팩트_분류가_유지된다(self) -> None:
        """분류가 흔들리면 준수율 비교가 무의미해진다."""
        assert ARTIFACTS.get("표 열·행 어긋남", 0) >= 40, ARTIFACTS
        assert ARTIFACTS.get("머리글", 0) >= 20, ARTIFACTS


class TestCompliance:
    """전 14개 절 준수율 — 바닥선 아래로 못 내려간다."""

    @staticmethod
    def _run() -> tuple[int, list[tuple[str, str, str, str, str]]]:
        hits, fails = 0, []
        for sec, item, ko, exp in CASES:
            try:
                got = translate_tagged_text(ko)
            except Exception as exc:            # noqa: BLE001
                got = f"<예외 {type(exc).__name__}>"
            if got == exp:
                hits += 1
            else:
                fails.append((sec, item, ko, exp, got))
        return hits, fails

    def test_준수율이_안_떨어진다(self) -> None:
        hits, fails = self._run()
        assert hits >= BASELINE_PASS, (
            f"규정 준수 {hits}/{len(CASES)} < 바닥선 {BASELINE_PASS}. "
            f"새로 깨진 것 예: {fails[:3]}")

    def test_열네_절이_전부_대상에_있다(self) -> None:
        """4개 절만 보던 종전 커버리지로 되돌아가지 않게 못 박는다."""
        secs = {s for s, *_ in CASES}
        assert len(secs) >= 12, sorted(secs)


class TestKnownSections:
    """절별로 통과 수가 유지되는지 — 어느 절이 무너졌는지 바로 보이게."""

    # 2026-08-06 실측. 절 04·12는 아티팩트를 걸러내면 대상이 거의 없다.
    FLOOR = {"01": 35, "02": 27, "03": 21, "06": 128, "11": 18, "08": 18}

    @pytest.mark.parametrize("sec,floor", sorted(FLOOR.items()))
    def test_절별_바닥선(self, sec: str, floor: int) -> None:
        hits = sum(1 for s, i, ko, exp in CASES
                   if s == sec and translate_tagged_text(ko) == exp)
        assert hits >= floor, f"절 {sec}: {hits} < {floor}"
