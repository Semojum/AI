"""캡셔닝 설정성 오류는 **실행 단위로** 잠근다 (2026-08-12).

전 job 실측: 시각요소 11,483개 중 6,892개(60.0%)가 CAPTION_FAILED인데 job별로는
실패율 100%가 152개 · 0%가 215개로 갈렸다. 그림이 아니라 API 접근 문제라는 뜻이다.

★ 기본 백엔드는 **anthropic**(claude-sonnet-5)이지 GPT-4o가 아니다. 키가 없으면
  클라이언트 생성자는 통과하고 첫 호출에서 `TypeError: Could not resolve
  authentication method…`가 난다 — 이름만 보면 코드 버그와 구분이 안 되므로
  메시지로 가른다. 이 테스트가 그 판별을 못박는다.
"""
from __future__ import annotations

import pytest

from app.ai.builder import result_builder as rb


@pytest.fixture(autouse=True)
def _reset():
    rb.reset_caption_fatal()
    yield
    rb.reset_caption_fatal()


class TestIsFatal:
    def test_키없음_TypeError는_설정오류다(self) -> None:
        exc = TypeError("Could not resolve authentication method. Expected one of "
                        "api_key, auth_token, or credentials to be set.")
        assert rb._is_fatal(exc)

    def test_그냥_TypeError는_코드버그다(self) -> None:
        """인증과 무관한 TypeError까지 잠그면 진짜 버그를 캡셔닝 장애로 오진한다."""
        assert not rb._is_fatal(TypeError("unsupported operand type(s) for +: 'int' and 'str'"))

    @pytest.mark.parametrize("name", [
        "AnthropicError", "OpenAIError", "AuthenticationError",
        "PermissionDeniedError", "NotFoundError",
    ])
    def test_인증_권한_예외는_설정오류다(self, name: str) -> None:
        assert rb._is_fatal(type(name, (Exception,), {})("boom"))

    @pytest.mark.parametrize("name", ["RateLimitError", "APITimeoutError", "APIConnectionError"])
    def test_일시장애는_잠그지_않는다(self, name: str) -> None:
        """쿼터·타임아웃은 다시 하면 될 수 있다 — 잠그면 멀쩡한 실행을 죽인다."""
        assert not rb._is_fatal(type(name, (Exception,), {})("boom"))


class TestLatch:
    def test_한_번_잠기면_API를_다시_안_부른다(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        img = tmp_path / "a.jpg"
        img.write_bytes(b"x")
        calls = {"n": 0}

        def _boom(_path):
            calls["n"] += 1
            raise TypeError("Could not resolve authentication method. Expected one of api_key…")

        monkeypatch.setattr(rb, "classify_with_confidence", _boom)
        el = {"image_path": str(img), "type": "image", "element_id": "e1"}

        assert rb._do_caption(el)[2] is False
        assert calls["n"] == 1, "설정성 오류인데 재시도했다"
        assert rb.caption_fatal_reason(), "래치가 안 걸렸다"

        # 다음 요소는 API를 아예 안 부른다 — 200요소 페이지에서 같은 실패를 200번 반복하던 자리
        assert rb._do_caption(dict(el, element_id="e2"))[2] is False
        assert calls["n"] == 1, "잠긴 뒤에도 API를 불렀다"

    def test_사유가_플래그로_나간다(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        """사후에 '왜 실패했나'를 알 수 있어야 한다 — 로그는 파일로 안 남는다."""
        img = tmp_path / "a.jpg"
        img.write_bytes(b"x")
        monkeypatch.setattr(rb, "classify_with_confidence",
                            lambda _p: (_ for _ in ()).throw(
                                type("AuthenticationError", (Exception,), {})("401")))
        rb._do_caption({"image_path": str(img), "type": "image", "element_id": "e1"})
        assert rb.caption_fatal_reason().startswith("AuthenticationError")


def test_백엔드_상태에_키값은_안_실린다() -> None:
    """진단용이라 유무만 본다 — 값이 로그·보고서로 새면 안 된다."""
    from app.ai.captioning.captioner import backend_status

    st = backend_status()
    assert set(st) == {"backend", "model", "key_env", "key_present"}
    assert isinstance(st["key_present"], bool)
    assert st["backend"] in ("anthropic", "openai") or st["backend"]


class TestResetOnNewJob:
    """잠금은 job 경계에서 풀린다 (2026-09-08, 재구조화 0-e).

    푸는 자리가 없던 시절엔 키가 잠깐 흔들려 한 번 잠기면 서버를 재시작할 때까지
    **그 뒤 다른 job 까지** 시각 요소가 통째로 '생략'으로 나갔다.
    """

    @staticmethod
    def _run(job_id: str, page_no: int = 1):
        import asyncio

        from app.core import pipeline
        from app.schemas.task import PageTask
        task = PageTask(job_id=job_id, page_no=page_no, total_pages=1,
                        pdf_data=b"", mode="b", source_text="가")
        asyncio.run(pipeline.run(task))

    def test_다음_job_이_오면_풀린다(self):
        from app.core import pipeline
        pipeline._last_job_id = None
        self._run("job-A")
        rb._caption_fatal = "AuthenticationError: 401"
        self._run("job-B")
        assert rb.caption_fatal_reason() is None

    def test_같은_job_안에서는_안_풀린다(self):
        from app.core import pipeline
        pipeline._last_job_id = None
        self._run("job-A", 1)
        rb._caption_fatal = "AuthenticationError: 401"
        self._run("job-A", 2)
        assert rb.caption_fatal_reason() == "AuthenticationError: 401"


# ── 일시장애가 내리 이어지면 = 망이 끊긴 것 (#852) ───────────────────────────
class TestTransientStreak:
    """한 요소의 실패와 망이 끊긴 것을 가른다.

    `APIConnectionError` 는 fatal 이 아니라 요소마다 재시도만 태우고 넘어갔다. 그래서
    망이 끊기면 실행이 안 멈추고 빈 캡션만 쌓였다(2026-08-06 816쪽·3.5시간).
    """

    @pytest.fixture(autouse=True)
    def _clean(self, monkeypatch: pytest.MonkeyPatch):
        rb.reset_caption_counters()
        monkeypatch.setattr(rb, "_CAPTION_RETRIES", 0)   # 백오프 대기 없이 재현
        yield
        rb.reset_caption_counters()

    @staticmethod
    def _img(tmp_path):
        p = tmp_path / "a.jpg"
        p.write_bytes(b"x")
        return {"image_path": str(p), "type": "image", "element_id": "e"}

    @staticmethod
    def _raise(name: str):
        def _f(_p):
            raise type(name, (Exception,), {})("Connection error.")
        return _f

    def test_내리_이어지면_잠근다(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        monkeypatch.setattr(rb, "classify_with_confidence", self._raise("APIConnectionError"))
        el = self._img(tmp_path)
        for _ in range(rb._CAP_STREAK_LIMIT):
            assert rb._do_caption(el)[2] is False
        assert rb.caption_fatal_reason(), "망이 끊겼는데 안 잠겼다"
        assert "APIConnectionError" in rb.caption_fatal_reason()
        assert rb.caption_counters() == (0, rb._CAP_STREAK_LIMIT)

    def test_한둘_실패로는_안_잠근다(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        monkeypatch.setattr(rb, "classify_with_confidence", self._raise("APIConnectionError"))
        el = self._img(tmp_path)
        for _ in range(rb._CAP_STREAK_LIMIT - 1):
            rb._do_caption(el)
        assert rb.caption_fatal_reason() is None, "산발 실패로 멀쩡한 실행을 죽였다"

    def test_사이에_성공이_끼면_연속이_끊긴다(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        """실패가 섞여 나는 것은 망 문제가 아니다 — 잠그면 정상 실행이 죽는다."""
        monkeypatch.setattr(rb, "classify_with_confidence", self._raise("APIConnectionError"))
        el = self._img(tmp_path)
        for _ in range(rb._CAP_STREAK_LIMIT - 1):
            rb._do_caption(el)
        rb._note_caption_result(True)                    # 한 건 성공
        for _ in range(rb._CAP_STREAK_LIMIT - 1):
            rb._do_caption(el)
        assert rb.caption_fatal_reason() is None


class TestRunnerSummary:
    """러너 요약에 캡션 실패 수가 뜬다 (#852).

    종전 요약은 `COMPLETED n NEEDS_REVIEW m BLOCKED 0` 뿐이라, 캡션이 전부 비어도
    `BLOCKED 0` 을 보고 정상으로 읽었다.
    """

    PROG = {"ok": 7, "review": 3, "blocked": 0, "fail": 0, "to": 0}

    @pytest.fixture(autouse=True)
    def _clean(self):
        rb.reset_caption_counters()
        yield
        rb.reset_caption_counters()

    def test_캡션이_실패하면_요약에_수가_뜬다(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        from test import corpus_runner as cr

        monkeypatch.setattr(rb, "_CAPTION_RETRIES", 0)
        monkeypatch.setattr(rb, "classify_with_confidence",
                            lambda _p: (_ for _ in ()).throw(
                                type("APIConnectionError", (Exception,), {})("Connection error.")))
        img = tmp_path / "a.jpg"
        img.write_bytes(b"x")
        for _ in range(3):
            rb._do_caption({"image_path": str(img), "type": "image", "element_id": "e"})

        line = cr.summary_line(self.PROG, 10, 32.0)
        assert "CAPTION_FAILED3" in line, line
        assert "BLOCKED0" in line   # 종전에는 이것만 보고 정상으로 읽었다

    def test_실패가_없으면_0으로_조용하다(self) -> None:
        from test import corpus_runner as cr

        assert "CAPTION_FAILED0" in cr.summary_line(self.PROG, 10, 32.0)

    def test_상태바가_도는_중에_보여준다(self, capsys: pytest.CaptureFixture) -> None:
        """런이 끝나야 아는 건 늦다 — 816쪽 사고는 3.5시간 뒤에나 알 수 있었다."""
        from test import corpus_runner as cr

        cr.bar(1, 10, ok=1, review=0, blocked=0, fail=0, to=0, eta=0, label="x", capfail=12)
        assert "cap✗12" in capsys.readouterr().out
        cr.bar(1, 10, ok=1, review=0, blocked=0, fail=0, to=0, eta=0, label="x")
        assert "cap✗" not in capsys.readouterr().out   # 0이면 조용하다
