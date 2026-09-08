"""재구조화 3-b — figure·order 내용주소 캐시.

재는 것: **같은 쪽이면 같은 답**. 그리고 캐시가 판정 우회로가 되지 않는다.
"""
import json
from types import SimpleNamespace

import pytest

from app.utils import llm_cache


@pytest.fixture(autouse=True)
def scope():
    """캐시는 격리 열쇠가 걸려 있을 때만 돈다(3-e, 대표 결재 "(B) 고객별 격리")."""
    llm_cache.set_scope("job-A")
    yield
    llm_cache.set_scope("")


@pytest.fixture
def cas(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("LLM_CACHE_MODE", raising=False)
    return tmp_path / "cas" / "llm"


class Test순서캐시:
    def _items(self, n=5):
        return [SimpleNamespace(element_id=f"id{i}", bbox=(i, i, i + 1, i + 1), type="text")
                for i in range(n)]

    def test_키에_element_id가_안_들어간다(self):
        """uuid4 가 섞이면 다른 job 은 항상 미스다 — 그래서 프롬프트 문자열로 잡는다."""
        from app.ai.parser.llm_order import _prompt
        a = self._items()
        b = [SimpleNamespace(element_id="딴판", bbox=x.bbox, type=x.type) for x in a]
        texts_a = {"id0": "가나다"}
        texts_b = {"딴판": "가나다"}          # 같은 자리·같은 글, id 만 다름
        assert _prompt(a, texts_a).splitlines()[2] == _prompt(b, texts_b).splitlines()[2]
        for x in a:
            assert x.element_id not in _prompt(a, texts_a)

    def test_두번째_호출은_LLM을_안_탄다(self, cas, monkeypatch):
        from app.ai.parser import llm_order

        calls = []

        def fake_create(**kw):
            calls.append(kw)
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text=json.dumps({"order": [1, 0, 2, 3, 4]}))],
                usage=SimpleNamespace(input_tokens=10, output_tokens=3))

        monkeypatch.setattr("anthropic.Anthropic",
                            lambda **kw: SimpleNamespace(messages=SimpleNamespace(create=fake_create)))
        monkeypatch.setattr(llm_order.config, "anthropic_api_key", "sk-test", raising=False)

        prompt = llm_order._prompt(self._items(), {})
        assert llm_order._ask(prompt) == ([1, 0, 2, 3, 4], 10, 3)
        assert llm_order._ask(prompt) == ([1, 0, 2, 3, 4], 0, 0)   # 적중 = 토큰 0
        assert len(calls) == 1
        assert list((cas / "order").glob("*.txt"))

    def test_깨진_응답은_안_굳는다(self, cas, monkeypatch):
        from app.ai.parser import llm_order

        monkeypatch.setattr(
            "anthropic.Anthropic",
            lambda **kw: SimpleNamespace(messages=SimpleNamespace(create=lambda **k: SimpleNamespace(
                content=[SimpleNamespace(type="text", text="사고만 하고 본문이 비었다")],
                usage=SimpleNamespace(input_tokens=1, output_tokens=0)))))
        monkeypatch.setattr(llm_order.config, "anthropic_api_key", "sk-test", raising=False)
        with pytest.raises(Exception):
            llm_order._ask("아무 프롬프트")
        assert not list((cas / "order").glob("*.txt"))

    @pytest.mark.asyncio
    async def test_적중분에도_안전판이_걸린다(self, cas, monkeypatch):
        # 읽기순서 LLM 기본값이 2026-09-08 에 끔으로 바뀌었다(속도). 이 시험은
        # 켜진 상태의 동작을 보는 것이라 명시로 켠다.
        monkeypatch.setenv("READING_ORDER_LLM", "1")
        """캐시는 결정성 장치이지 판정 우회로가 아니다."""
        from app.ai.parser import llm_order

        items = [SimpleNamespace(element_id=f"id{i}", bbox=(i, i, i + 1, i + 1),
                                 type="text", reading_order=i + 1) for i in range(5)]
        layout = SimpleNamespace(elements=items)
        k = llm_cache.key("order", llm_order.MODEL, llm_order._SYS,
                          llm_order._prompt(sorted(items, key=lambda b: b.reading_order), {}))
        llm_cache.put("order", k, json.dumps({"order": [4, 3, 2, 1, 0]}))   # 이동비율 0.8
        monkeypatch.setattr(llm_order.config, "anthropic_api_key", "sk-test", raising=False)

        out = await llm_order.apply(layout, {}, 0)
        assert out["called"] and out["reverted"] and out["reason"] == "안전판"
        assert [b.reading_order for b in items] == [1, 2, 3, 4, 5]          # 규칙 순서 그대로


    @pytest.mark.asyncio
    async def test_ro_미스는_쪽을_안_죽이고_규칙순서로_간다(self, cas, monkeypatch):
        # 읽기순서 LLM 기본값이 2026-09-08 에 끔으로 바뀌었다(속도). 이 시험은
        # 켜진 상태의 동작을 보는 것이라 명시로 켠다.
        monkeypatch.setenv("READING_ORDER_LLM", "1")
        """`LLM_CACHE_MODE=ro` 팔의 계약 — 외부 호출 0, 쪽은 그대로 나간다."""
        from app.ai.parser import llm_order

        monkeypatch.setenv("LLM_CACHE_MODE", "ro")
        monkeypatch.setattr(llm_order.config, "anthropic_api_key", "sk-test", raising=False)
        monkeypatch.setattr("anthropic.Anthropic", lambda **kw: pytest.fail("ro 인데 불렀다"))
        items = [SimpleNamespace(element_id=f"id{i}", bbox=(i, i, i + 1, i + 1),
                                 type="text", reading_order=i + 1) for i in range(5)]

        out = await llm_order.apply(SimpleNamespace(elements=items), {}, 0)
        assert not out["called"] and out["reason"].startswith("실패 CacheMiss")
        assert [b.reading_order for b in items] == [1, 2, 3, 4, 5]


class Test그림회수캐시:
    def test_두번째_호출은_LLM을_안_탄다(self, cas, monkeypatch):
        import fitz

        from app.ai.parser import figure_detect

        doc = fitz.open()
        doc.new_page(width=200, height=300)
        pdf = doc.tobytes()
        doc.close()

        calls = []

        def fake_create(**kw):
            calls.append(kw)
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text='{"figures":[{"kind":"그래프",'
                                         '"x0":10,"y0":10,"x1":90,"y1":90,"what":"수요곡선"}]}')],
                usage=SimpleNamespace(input_tokens=5, output_tokens=2))

        monkeypatch.setattr("anthropic.Anthropic",
                            lambda **kw: SimpleNamespace(messages=SimpleNamespace(create=fake_create)))
        monkeypatch.setattr(figure_detect.config, "anthropic_api_key", "sk-test", raising=False)

        first = figure_detect.detect(pdf, 1)
        second = figure_detect.detect(pdf, 1)
        assert first == second == [{"kind": "그래프", "x0": 10, "y0": 10, "x1": 90, "y1": 90,
                                    "what": "수요곡선"}]
        assert len(calls) == 1


class Test모드:
    def test_빈_값이면_아무_일도_없다(self, monkeypatch, tmp_path):
        """3-e 로 기본이 켬이 됐다 — 되돌리는 길은 `.env` 의 `LLM_CACHE_DIR=` 한 줄이다."""
        monkeypatch.setenv("LLM_CACHE_DIR", "")
        assert llm_cache.root() is None
        assert llm_cache.get("order", "k") is None
        llm_cache.put("order", "k", "x")            # 조용히 아무것도 안 한다

    def test_기본은_켬이다(self, monkeypatch):
        """운영 기본 켬(3-e). 환경변수를 안 줘도 `Settings.llm_cache_dir` 로 돈다."""
        monkeypatch.delenv("LLM_CACHE_DIR", raising=False)
        assert llm_cache.root() is not None

    def test_ro_미스는_예외다(self, cas, monkeypatch):
        """A/B 끄기 팔에서 '조용히 호출로 흐르는' 길을 막는다."""
        monkeypatch.setenv("LLM_CACHE_MODE", "ro")
        with pytest.raises(llm_cache.CacheMiss):
            llm_cache.get("order", llm_cache.key("없는키"))


class Test고객격리:
    """대표 결재 2026-09-08 — "같은 책을 다른 유저가 올리면 따로 계산하는 게 맞다"."""

    def test_열쇠가_다르면_자리도_다르다(self, cas):
        llm_cache.set_scope("고객A")
        a = llm_cache.key("order", "같은 프롬프트")
        llm_cache.set_scope("고객B")
        assert llm_cache.key("order", "같은 프롬프트") != a

    def test_다른_고객은_적중을_못_가져간다(self, cas):
        llm_cache.set_scope("고객A")
        k = llm_cache.key("order", "같은 프롬프트")
        llm_cache.put("order", k, "고객A 응답")
        assert llm_cache.get("order", k) == "고객A 응답"

        llm_cache.set_scope("고객B")
        assert llm_cache.get("order", llm_cache.key("order", "같은 프롬프트")) is None

    def test_열쇠가_없으면_캐시를_안_쓴다(self, cas):
        """fail closed — 컨텍스트가 안 넘어간 자리에서 격리 없이 쓰느니 안 쓴다."""
        llm_cache.set_scope("")
        llm_cache.put("order", llm_cache.key("order", "x"), "샐 뻔한 응답")
        assert llm_cache.get("order", llm_cache.key("order", "x")) is None
        assert not list(cas.rglob("*.txt"))
