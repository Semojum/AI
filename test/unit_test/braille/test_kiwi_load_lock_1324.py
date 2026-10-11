"""#1324 — 역점역 낱말 판정기(kiwi)를 두 스레드가 처음 동시에 불러도 한 번만 올린다."""
import sys
import threading
import time
import types

from app.utils import braille_back as B


def test_두_스레드가_처음_동시에_불러도_판정기는_한_번만_올린다(monkeypatch):
    made = []

    class _Tok:
        tag, score, form = "NNG", -5.0, "사과"

    class _Kiwi:
        def __init__(self):
            made.append(1)
            time.sleep(0.2)              # 올리는 동안 다른 스레드가 들어올 틈

        def analyze(self, run):
            return [([_Tok()], -5.0)]

    monkeypatch.setitem(sys.modules, "kiwipiepy", types.SimpleNamespace(Kiwi=_Kiwi))
    monkeypatch.setattr(B, "_KIWI", None)
    ts = [threading.Thread(target=B._is_real_korean, args=("사과",)) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(made) == 1
