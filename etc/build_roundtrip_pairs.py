"""역점역 데이터셋 생성기 — 규정 골드(regulation_pairs)에서 유형별 묵자↔점자 쌍 추출.

유형마다(한글음절·약자·숫자·문장부호·로마자·특수기호…) 깨끗한 쌍을 모아
build:test = 7:3(안정 해시)로 나눠 `test_data/roundtrip_pairs/{type}.json`에 저장한다.

원칙
  · 골드 점자 = 검증된 `braille_ascii.ascii_to_unicode(brf_ascii)` (규정 BRF ASCII가 권위).
  · 내부 정합성: 정방향 점역기(translate_tagged_text)가 골드를 재현하는 행만 채택
    (brf_ascii 자체가 깨진 설명용 행·옛 버그 행을 자동 배제). 정합 실패는 review로 분리.
  · 분할은 hashlib(머신 무관) 기준 — 7:3, 유형 내 층화.
  · ambiguous: 같은 점형이 한글/숫자/기호로 중복되어 블라인드 복원 불가한 쌍 표시(현행 한글 우선).

실행 (작업 디렉토리 = code/AI):
    python etc/build_roundtrip_pairs.py hangul
    python etc/build_roundtrip_pairs.py --all
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

_AI_ROOT = Path(__file__).resolve().parent.parent          # code/AI
sys.path.insert(0, str(_AI_ROOT))

from app.utils.braille_ascii import ascii_to_unicode        # noqa: E402
from app.ai.braille.translator import translate_tagged_text  # noqa: E402

_PAIRS_DIR = _AI_ROOT / "test" / "test_data" / "regulation_pairs"
_OUT_DIR = _AI_ROOT / "test" / "test_data" / "roundtrip_pairs"

_HANGUL = re.compile(r"^[가-힣]+(?: [가-힣]+)*$")  # 순수 한글 단어(공백 허용)
_HAS_DIGIT = re.compile(r"[0-9]")                   # 아라비아 숫자 포함


def _strip_pad(b: str | None) -> str | None:
    """규정 BRF 행은 32칸 고정폭이라 양끝에 공백 셀(⠀)·공백이 붙는다 — 양끝만 제거."""
    return b.strip("⠀ \n") if b else b


def _build_split(korean: str) -> str:
    """머신 무관 안정 해시로 build(70%)/test(30%) 분할."""
    h = int(hashlib.md5(korean.encode("utf-8")).hexdigest(), 16)
    return "build" if (h % 10) < 7 else "test"


# 유형별 후보 필터 — (korean, brf_ascii) → 채택 여부. 정합성 검사는 공통에서.
def _is_hangul_syllable(korean: str, brf: str) -> bool:
    """한글 음절 유형: 순수 한글, 1~4어절·12자 이하, 설명행 아님."""
    if not _HANGUL.match(korean):
        return False
    if len(korean) > 12 or korean.startswith("["):
        return False
    return True


def _is_number(korean: str, brf: str) -> bool:
    """숫자 유형: 아라비아 숫자 포함(정수·소수·자릿점·범위·단위 혼용).

    로마자(영문) 포함 행은 로마자 유형으로 미루고 제외 → 숫자 decode만 깨끗이 검증.
    원문자(①)는 [0-9]가 아니라 자동 제외.
    """
    if not _HAS_DIGIT.search(korean):
        return False
    if korean.startswith("[") or len(korean) > 20:
        return False
    if re.search(r"[A-Za-z]", korean):         # 로마자 혼합 → 로마자 유형으로
        return False
    return True


_CLASSIFIERS = {
    "hangul": ("한글 음절 (받침 유무·겹받침·된소리). 규정 1~3장 + section_01~03 등.",
               _is_hangul_syllable),
    "numbers": ("아라비아 숫자 (수표·정수·소수점·자릿점·범위·단위 혼용). 규정 제6·12절 등.",
                _is_number),
}


def _collect_rows():
    """regulation_pairs 전체 행을 순회 — (korean, brf_ascii, source) 중복 제거."""
    seen: set[tuple[str, str]] = set()
    for f in sorted(_PAIRS_DIR.glob("section_*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        for p in data["pairs"]:
            kor, brf = p.get("korean", ""), p.get("brf_ascii", "")
            if not kor or not brf or (kor, brf) in seen:
                continue
            seen.add((kor, brf))
            yield kor, brf, f.stem


def build_type(type_name: str) -> dict:
    desc, accept = _CLASSIFIERS[type_name]
    pairs, review = [], []
    for kor, brf, source in _collect_rows():
        if not accept(kor, brf):
            continue
        gold = _strip_pad(ascii_to_unicode(brf))   # 규정 행의 양끝 32칸 패딩(⠀) 제거
        if "[?" in gold:                       # 변환 불가(잔존 깨짐) → 제외
            review.append({"korean": kor, "brf_ascii": brf, "reason": "ascii_broken"})
            continue
        # 내부 정합성: 정방향 점역기가 규정 골드를 재현하는가(양끝 공백 무시)
        try:
            fwd = _strip_pad(translate_tagged_text(kor))
        except Exception:
            fwd = None
        if fwd != gold:                        # brf 깨짐/옛 버그/정방향 불일치 → review
            review.append({"korean": kor, "brf_ascii": brf,
                           "gold": gold, "forward": fwd, "reason": "forward_mismatch"})
            continue
        pairs.append({
            "korean": kor,
            "brf_ascii": brf,
            "braille_unicode": gold,
            "split": _build_split(kor),
            "ambiguous": False,                # 한글 음절은 모호 없음(기본)
            "source": source,
        })
    pairs.sort(key=lambda p: (p["split"], p["korean"]))
    counts = {
        "build": sum(1 for p in pairs if p["split"] == "build"),
        "test": sum(1 for p in pairs if p["split"] == "test"),
        "review_excluded": len(review),
    }
    return {
        "type": type_name,
        "description": desc,
        "split_ratio": "build:test = 7:3 (md5 안정 해시)",
        "counts": counts,
        "pairs": pairs,
        "review": review[:50],                 # 정제 검토용 샘플
    }


def main(argv: list[str]) -> int:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = list(_CLASSIFIERS) if (argv and argv[0] == "--all") else argv
    if not targets:
        print(__doc__)
        return 0
    for t in targets:
        if t not in _CLASSIFIERS:
            print(f"미지원 유형: {t} (가능: {', '.join(_CLASSIFIERS)})")
            continue
        out = build_type(t)
        path = _OUT_DIR / f"{t}.json"
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{t}] build {out['counts']['build']} / test {out['counts']['test']} "
              f"/ 제외 {out['counts']['review_excluded']} → {path.relative_to(_AI_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
