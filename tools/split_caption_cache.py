"""옛 캡션 캐시를 kind 로 가른다 (재구조화 3-c, 한 번만 돌린다).

`CAPTION_CACHE_DIR` 한 디렉터리에 **캡션과 분류 라벨이 섞여** 있다. 실측 3,242건 =
캡션 1,961 + 라벨 1,281. 자리만으로는 둘을 구분할 수 없어, 이 캐시를 쓸어 담는 스크립트가
라벨을 캡션 자리로 넣으면 초안에 `그림: chart` 가 나온다. 실제로 관찰된 현상이다.

가르는 잣대는 **내용**이다. 라벨은 `image·cartoon·chart·diagram` 넷 중 한 단어뿐이고,
캡션은 유형 제시어(`그림:`·`만화:`)로 연다. 실측 3,242건에서 겹치는 항목이 없다.

    python tools/split_caption_cache.py <캐시경로>            # 셈만 한다
    python tools/split_caption_cache.py <캐시경로> --apply    # 옮긴다

⚠ **공용 캐시에 함부로 돌리지 마라.** 옮기고 나면 옛 코드(평평한 뿌리만 보는 판)는 캐시를
  통째로 잃는다. 그 코드가 도는 워크트리·서버가 없을 때만 돌린다. 되돌리기는 `--undo`.
"""
import sys
from pathlib import Path

LABELS = frozenset(("image", "cartoon", "chart", "diagram"))
KINDS = ("caption", "classify")


def kind_of(text: str) -> str:
    return "classify" if text.strip() in LABELS else "caption"


def main(root: Path, apply: bool, undo: bool) -> int:
    if undo:
        moved = [(f, root / f.name) for k in KINDS for f in (root / k).glob("*.txt")]
    else:
        moved = [(f, root / kind_of(f.read_text(encoding="utf-8")) / f.name)
                 for f in sorted(root.glob("*.txt"))]
    counts = {}
    for _, dst in moved:
        counts[dst.parent.name] = counts.get(dst.parent.name, 0) + 1
    print(f"{root} · 옮길 것 {len(moved)}건 · " +
          " · ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    if not apply:
        print("셈만 했다. 실제로 옮기려면 --apply.")
        return 0
    for src, dst in moved:
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
    print(f"옮겼다 {len(moved)}건.")
    return 0


def _demo() -> None:
    """자기검사 — 라벨과 캡션이 제 자리로 가는가."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "a.txt").write_text("chart", encoding="utf-8")
        (root / "b.txt").write_text("그림: 막대그래프이다.", encoding="utf-8")
        main(root, apply=True, undo=False)
        assert (root / "classify" / "a.txt").exists()
        assert (root / "caption" / "b.txt").exists()
        assert not list(root.glob("*.txt"))
        main(root, apply=True, undo=True)              # 되돌리기
        assert {p.name for p in root.glob("*.txt")} == {"a.txt", "b.txt"}
    print("ok")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        _demo()
    else:
        raise SystemExit(main(Path(sys.argv[1]).expanduser().resolve(),
                              "--apply" in sys.argv, "--undo" in sys.argv))
