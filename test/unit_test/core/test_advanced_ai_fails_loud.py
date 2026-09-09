"""유료 옵션이 못 돌면 **실패로 알린다** — 조용히 MinerU 로 되돌아가지 않는다 (#788).

대표 결정 2026-09-08 「고급 점역의 정의」(+ 같은 날 정정):
  · 고급 점역 = **지면을 LLM 이 직접 읽는다.** 켜면 **쉬운 쪽이든 어려운 쪽이든 모든 쪽**의
    OCR 추출을 LLM 이 한다. **티어로 건너뛰지 않는다** — "이 쪽은 이미 깨끗하니 안 해도
    된다" 는 우리 판단이지 고객 판단이 아니다.
  · 못 쓰면(모델 없음·지면 렌더 실패·둘 다 못 읽음) 조용히 되돌리지 말고 실패로 알린다.
    값을 치른 것과 다른 것이 **멀쩡한 척** 나가면 안 된다. 티어 무엇이든 마찬가지다.
  · 조용히 무시하던 자리가 **둘**이었다 — 티어 게이트(`routing_tier != "ZERO"`)와
    **경계 재사용**(MinerU 로 만든 경계를 고급 점역 요청에 그대로 쓰던 것).

새 체계는 안 만들었다. 예외를 올리면 `pipeline.run` 이 이미 `status="BLOCKED"` +
`CriticalError(C1)` 로 옮긴다(`_build_exception_response`).
"""
import asyncio

import pytest

from app.core import pipeline
from app.schemas.layout import DocumentMeta
from app.schemas.task import PageTask


def _arrange(monkeypatch, tier, *, available=True, image=True, els=None):
    """`analyze_pdf` 만 갈아 끼우면 고급 점역 갈래까지 그대로 온다 — 그 앞은 아무것도 안 탄다."""
    from app.ai.parser import opus_fallback
    from app.ai.preprocessor import pdf_analyzer

    monkeypatch.setattr(pdf_analyzer, "analyze_pdf",
                        lambda *a, **kw: (DocumentMeta(pdf_confidence=0.1, routing_tier=tier,
                                                       scan_only=True), ""))
    monkeypatch.setattr(opus_fallback, "advanced_available", lambda: available)
    monkeypatch.setattr(pipeline, "_page_image_path", lambda t: "p.jpg" if image else None)
    monkeypatch.setattr(opus_fallback, "extract_advanced", lambda p: (els, "sonnet-5" if els else ""))

    async def _mnr(task, meta):
        return [], 0, 0, "pixel"
    monkeypatch.setattr(pipeline, "_extract_via_models", _mnr)
    return PageTask(job_id="adv", page_no=1, total_pages=1, mode="c",
                    pdf_data=b"%PDF-", advanced_ai=True)


@pytest.mark.parametrize("tier", ["ZERO", "STANDARD", "QUALITY"])
@pytest.mark.parametrize("kw, 이유", [
    ({"available": False}, "모델 키가 없다"),
    ({"image": False}, "지면 이미지를 못 만들었다"),
    ({"els": None}, "두 모델 다 지면을 못 읽었다"),
])
def test_못_쓰면_티어_무엇이든_실패한다(monkeypatch, tier, kw, 이유):
    """★ ZERO 가 이 목록에 있는 것이 정정의 핵심이다 — 종전에는 조용히 넘어갔다."""
    task = _arrange(monkeypatch, tier, **kw)
    with pytest.raises(RuntimeError) as e:
        asyncio.run(pipeline._extract_with_hyunju(task))
    assert "고급 점역을 쓸 수 없다" in str(e.value) and 이유 in str(e.value)


@pytest.mark.parametrize("tier", ["ZERO", "STANDARD", "QUALITY"])
def test_켜면_티어_무엇이든_LLM_이_읽는다(monkeypatch, tier):
    """쉬운 지면(ZERO)도 LLM 이 읽는다. 종전에는 여기서 MinerU 로 갔다."""
    task = _arrange(monkeypatch, tier, els=[{"type": "text", "content": "LLM 이 읽은 글자"}])
    out = asyncio.run(pipeline._extract_with_hyunju(task))[1]
    assert out["meta"]["extraction_method"] == "LLM_VISION"


def test_안_켜면_티어대로_간다(monkeypatch):
    """평상 경로 — `advanced_ai=false` 는 아무것도 안 바뀐다."""
    task = _arrange(monkeypatch, "ZERO", available=False)
    task.advanced_ai = False
    try:
        asyncio.run(pipeline._extract_with_hyunju(task))
    except Exception as exc:            # noqa: BLE001
        # 뒤쪽 추출에서 막히는 것은 이 테스트의 관심사가 아니다.
        assert "고급 점역을 쓸 수 없다" not in str(exc)


class Test경계_재사용도_고급_점역을_안_무시한다:
    """조용히 무시하던 **두 번째** 자리 — 경계 지문에는 `advanced_ai` 가 없다(#788).

    MinerU 로 만든 경계가 옆에 있으면 고급 점역 요청도 그걸 그대로 읽어, 유료 옵션이
    한 번도 안 돌고 응답만 멀쩡히 나갔다. 원하는 추출이 아니면 재파생해야 한다.
    """

    class _재파생함(RuntimeError):
        pass

    def _boundary(self, monkeypatch, tmp_path, method):
        """MinerU(또는 LLM_VISION) 로 만든 경계 파일 + 지문을 깔아 둔다."""
        monkeypatch.chdir(tmp_path)
        task = PageTask(job_id="reuse", page_no=1, total_pages=1, mode="c", pdf_data=b"%PDF-")
        pipeline._write_txt_result(
            task,
            {"meta": {"extraction_method": method, "image_width": 100, "image_height": 100},
             "elements": []},
            DocumentMeta(pdf_confidence=0.99, routing_tier="ZERO"),
        )

        async def _재파생(t):
            raise self._재파생함("재파생했다")
        monkeypatch.setattr(pipeline, "_extract_with_hyunju", _재파생)
        return task

    def test_MinerU_경계는_고급_점역_요청에_재파생된다(self, monkeypatch, tmp_path):
        task = self._boundary(monkeypatch, tmp_path, "OCR")
        task.advanced_ai = True
        with pytest.raises(self._재파생함):
            asyncio.run(pipeline._run_pipeline(task))

    def test_고급_점역_경계는_그대로_재사용한다(self, monkeypatch, tmp_path):
        """이미 LLM 이 읽은 경계면 다시 부르지 않는다 — 값은 이미 치러졌다."""
        task = self._boundary(monkeypatch, tmp_path, "LLM_VISION")
        task.advanced_ai = True
        try:
            asyncio.run(pipeline._run_pipeline(task))
        except self._재파생함:
            pytest.fail("이미 고급 점역으로 만든 경계인데 다시 불렀다")
        except Exception:                # noqa: BLE001 — 뒤쪽 체인은 이 테스트 관심사가 아니다
            pass

    def test_안_켜면_종전대로_재사용한다(self, monkeypatch, tmp_path):
        task = self._boundary(monkeypatch, tmp_path, "OCR")
        try:
            asyncio.run(pipeline._run_pipeline(task))
        except self._재파생함:
            pytest.fail("고급 점역을 안 켰는데 재파생했다")
        except Exception:                # noqa: BLE001
            pass


class Test크롭_모드:
    """`ADVANCED_EXTRACT_MODE=crop` — 쪽 전체를 안 읽고 MinerU 뒤에 깨진 요소만 잘라 되묻는다(2026-09-10).
    `both` 는 쪽 전체 이식 뒤에 한 번 더 건다. 실측은 `crop_reask` 도크스트링."""

    def _crop(self, monkeypatch, mode, *, mnr_els, reask):
        from app.ai.parser import crop_reask
        monkeypatch.setenv("ADVANCED_EXTRACT_MODE", mode)
        calls = []

        def _reask(els, img):
            calls.append(list(els))
            return reask
        monkeypatch.setattr(crop_reask, "reask_crops", _reask)
        task = _arrange(monkeypatch, "STANDARD", els=[{"type": "text", "content": "LLM 이 읽은 글자"}])

        async def _mnr(t, meta):
            return mnr_els, 1000, 1000, "norm1000"
        monkeypatch.setattr(pipeline, "_extract_via_models", _mnr)
        monkeypatch.setattr(pipeline, "_graft_text", lambda els, llm, img=None: 0)
        return task, calls

    def test_crop_은_MinerU_요소를_되묻고_LLM_VISION_으로_나간다(self, monkeypatch):
        from app.ai.parser import opus_fallback
        monkeypatch.setattr(opus_fallback, "extract_advanced",
                            lambda p: (_ for _ in ()).throw(AssertionError("쪽 전체를 읽었다")))
        mnr = [{"type": "text", "content": "⑦에 의하여", "bbox": [1, 1, 9, 9]}]
        task, calls = self._crop(monkeypatch, "crop", mnr_els=mnr, reask=1)
        out = asyncio.run(pipeline._extract_with_hyunju(task))[1]
        assert out["meta"]["extraction_method"] == "LLM_VISION" and calls == [mnr]

    def test_crop_에서_되묻기가_죽으면_실패로_알린다(self, monkeypatch):
        task, _ = self._crop(monkeypatch, "crop", mnr_els=[{"type": "text", "content": "x", "bbox": [1, 1, 9, 9]}],
                             reask=None)
        with pytest.raises(RuntimeError, match="크롭 되묻기가 실패했다"):
            asyncio.run(pipeline._extract_with_hyunju(task))

    def test_crop_에서_MinerU_가_비면_실패로_알린다(self, monkeypatch):
        task, _ = self._crop(monkeypatch, "crop", mnr_els=[], reask=0)
        with pytest.raises(RuntimeError, match="MinerU 가 지면을 못 읽었다"):
            asyncio.run(pipeline._extract_with_hyunju(task))

    def test_both_는_이식_뒤에_한_번_더_되묻는다(self, monkeypatch):
        mnr = [{"type": "text", "content": "⑦에 의하여", "bbox": [1, 1, 9, 9]}]
        task, calls = self._crop(monkeypatch, "both", mnr_els=mnr, reask=1)
        out = asyncio.run(pipeline._extract_with_hyunju(task))[1]
        assert out["meta"]["extraction_method"] == "LLM_VISION" and len(calls) == 1

    def test_page_기본은_되묻기를_안_건다(self, monkeypatch):
        task, calls = self._crop(monkeypatch, "page", mnr_els=[{"type": "text", "content": "x", "bbox": [1, 1, 9, 9]}],
                                 reask=1)
        asyncio.run(pipeline._extract_with_hyunju(task))
        assert calls == []
