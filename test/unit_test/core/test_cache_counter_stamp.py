"""재구조화 3-a — 계수기·경계 stamp·캐시 절대경로.

이 셋이 재는 것은 하나다: **A/B 두 팔이 같은 자리를 보고, 끈 팔은 정말 안 불렀나.**
"""
import json
import os
from pathlib import Path

from app.utils.llm_cache import resolve_dir
from app.utils.req_log import llm_counter_line, record_cache, record_llm, start_request

_ROOT = Path(__file__).resolve().parents[3]      # …/code/AI


class Test캐시경로:
    def test_상대경로는_저장소_루트_기준(self, monkeypatch):
        monkeypatch.setenv("CAPTION_CACHE_DIR", "storage/cap")
        monkeypatch.chdir("/tmp")                # cwd 가 달라도 같은 자리를 봐야 한다
        assert resolve_dir("CAPTION_CACHE_DIR") == _ROOT / "storage" / "cap"

    def test_절대경로는_그대로(self, monkeypatch):
        monkeypatch.setenv("CAPTION_CACHE_DIR", "/tmp/x/y")
        assert resolve_dir("CAPTION_CACHE_DIR") == Path("/tmp/x/y")

    def test_값이_없으면_None(self, monkeypatch):
        monkeypatch.delenv("CAPTION_CACHE_DIR", raising=False)
        assert resolve_dir("CAPTION_CACHE_DIR") is None


class Test계수기:
    def test_아무것도_안_불렀으면_call0_이_찍힌다(self):
        # 줄이 아예 없으면 "안 불렀다"와 "로그를 안 남겼다"를 못 가른다.
        start_request()
        assert llm_counter_line().startswith("LLM계수 call=0")

    def test_kind별_호출과_적중이_한_줄에(self):
        start_request()
        record_llm("캡셔닝", "claude-sonnet-5", 10, 5)
        record_cache("캡셔닝", True)
        record_cache("캡셔닝", False)
        line = llm_counter_line()
        assert "call=1" in line and "캡셔닝 call=1 hit=1 miss=1" in line

    def test_통계가_없어도_안_죽는다(self):
        # gRPC 밖(테스트·스크립트)에서 부르면 contextvar 가 비어 있다.
        import app.utils.req_log as rl
        rl._stats.set(None)
        assert "call=0" in llm_counter_line()


class Test경계stamp:
    def test_경계파일_옆에_지문이_남는다(self, tmp_path, monkeypatch):
        from app.core import pipeline
        from app.schemas.task import PageTask

        monkeypatch.chdir(tmp_path)
        task = PageTask(job_id="stampjob", page_no=7, total_pages=1, mode="a",
                        pdf_data=b"%PDF-1.4\n")
        pipeline._write_txt_result(task, {"meta": {"extraction_method": "OCR"}, "elements": []})

        d = tmp_path / "storage/jobs/stampjob/temp/page_007/data"
        stamp = json.loads((d / "007_extract_stamp.json").read_text(encoding="utf-8"))
        assert len(stamp["extract_sha"]) == 12 and len(stamp["prompt_sha"]) == 12
        assert stamp["method"] == "OCR"
        # ★ 경계 파일 자체는 안 건드린다 — 재현 diff 가 판 지문을 재면 안 된다.
        body = (d / "007_txt_result.json").read_text(encoding="utf-8")
        assert "extract_sha" not in body
        # ★ 코퍼스 러너의 `*_txt_result.json` glob 에 걸리면 안 된다.
        assert [f.name for f in sorted(d.glob("*_txt_result.json"))] == ["007_txt_result.json"]

    def test_스위치가_바뀌면_env지문이_바뀐다(self, monkeypatch):
        from app.core import pipeline
        fp = lambda: __import__("hashlib").sha256(  # noqa: E731
            "|".join(f"{k}={os.environ.get(k, '')}" for k in pipeline._EXTRACT_ENV).encode()
        ).hexdigest()[:12]
        before = fp()
        monkeypatch.setenv("FIGURE_DETECT", "0")
        assert fp() != before


class Test경계재사용:
    """재구조화 3-d — stamp 를 읽어 재사용/재파생을 가른다."""

    def _task(self, tmp_path, monkeypatch):
        from app.schemas.task import PageTask
        monkeypatch.chdir(tmp_path)
        return PageTask(job_id="verdictjob", page_no=3, total_pages=1, mode="a",
                        pdf_data=b"%PDF-1.4\n")

    def _write(self, task, tier="STANDARD"):
        from app.core import pipeline
        from app.schemas.layout import DocumentMeta
        pipeline._write_txt_result(
            task, {"meta": {"extraction_method": "OCR"}, "elements": []},
            DocumentMeta(pdf_confidence=0.5, routing_tier=tier, scan_only=True))

    def test_같은_판이면_재사용(self, tmp_path, monkeypatch):
        from app.core import pipeline
        task = self._task(tmp_path, monkeypatch)
        self._write(task)
        assert pipeline._stamp_verdict(task)[0] is None

    def test_판을_올리면_prompt_ver_무효(self, tmp_path, monkeypatch):
        from app.core import pipeline
        from app.utils import llm_cache
        task = self._task(tmp_path, monkeypatch)
        self._write(task)
        monkeypatch.setitem(llm_cache.PROMPT_VER, "caption",
                            llm_cache.PROMPT_VER["caption"] + 1)
        assert pipeline._stamp_verdict(task)[0] == "prompt_ver"

    def test_opt단계_판번호는_경계를_안_건드린다(self, tmp_path, monkeypatch):
        # ★ 이것이 이 단계의 핵심 안전장치다. 본문 프롬프트 판을 올렸다고 재파생하면
        #   element_id(uuid4)가 갈려 점역사 피드백의 요소 참조가 끊긴다.
        from app.core import pipeline
        from app.utils import llm_cache
        task = self._task(tmp_path, monkeypatch)
        self._write(task)
        for kind in ("text", "formula", "table", "visual"):
            monkeypatch.setitem(llm_cache.PROMPT_VER, kind,
                                llm_cache.PROMPT_VER[kind] + 1)
        assert pipeline._stamp_verdict(task)[0] is None

    def test_스위치가_바뀌면_env_fp_무효(self, tmp_path, monkeypatch):
        from app.core import pipeline
        task = self._task(tmp_path, monkeypatch)
        self._write(task)
        monkeypatch.setenv("FIGURE_DETECT", "0")
        assert pipeline._stamp_verdict(task)[0] == "env_fp"

    def test_stamp_이_없으면_재파생(self, tmp_path, monkeypatch):
        from app.core import pipeline
        task = self._task(tmp_path, monkeypatch)
        self._write(task)
        pipeline._stamp_path(task).unlink()
        assert pipeline._stamp_verdict(task)[0] == "no_stamp"

    def test_doc_meta_가_그대로_돌아온다(self, tmp_path, monkeypatch):
        from app.core import pipeline
        from app.schemas.layout import DocumentMeta
        task = self._task(tmp_path, monkeypatch)
        self._write(task, tier="QUALITY")
        dm = DocumentMeta(**pipeline._stamp_verdict(task)[1]["doc_meta"])
        assert dm.routing_tier == "QUALITY" and dm.scan_only is True

    def test_원자_쓰기라_임시파일이_안_남는다(self, tmp_path, monkeypatch):
        from app.core import pipeline
        task = self._task(tmp_path, monkeypatch)
        self._write(task)
        d = tmp_path / "storage/jobs/verdictjob/temp/page_003/data"
        assert not list(d.glob("*.tmp"))
        assert sorted(f.name for f in d.iterdir()) == [
            "003_extract_stamp.json", "003_txt_result.json"]
