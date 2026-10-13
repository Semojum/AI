"""이관 3단계 측정 팔(#1370) — 경계 파일에 문맥값 다섯이 실리고, shim 결과 파일이 AI 타입으로 되읽히는가.

패키지 없이 돈다. shim 자리에 경계 파일을 받아 두는 가짜를 넣는다. 코퍼스는 한글 · 영어 정자와 선택지 한 줄이
늘 거짓이라 두 팔 바이트 대조로는 이 세 값이 경계 파일에 실리는지를 못 본다. 그래서 여기서 참으로 넣어 본다.
"""
import json
import sys
import types
from uuid import uuid4

from app.core import pipeline
from app.schemas.content import BrailleOutput, ExtractedContent, LLMOutput
from app.schemas.layout import BBoxItem, LayoutResult
from app.schemas.task import PageTask


def test_스위치는_프로세스_env_로만_켜지고_기본은_pipeline(monkeypatch):
    monkeypatch.delenv("SEMOJUM_TRANSLATE_BY", raising=False)
    assert pipeline._translate_by() == "pipeline"
    monkeypatch.setenv("SEMOJUM_TRANSLATE_BY", "package")
    assert pipeline._translate_by() == "package"


def test_경계_파일에_문맥값_다섯이_실리고_결과가_AI_타입으로_돌아온다(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "storage/jobs/j/temp/page_003/data").mkdir(parents=True)
    x_id, t_id = uuid4(), uuid4()
    task = PageTask(job_id="j", page_no=3, mode="c", korean_grade1=True, choices_one_per_line=True)
    layout = LayoutResult(page_id="p", elements=[
        BBoxItem(element_id=x_id, type="text", bbox=(0, 0, 1, 1), reading_order=1),
        BBoxItem(element_id=t_id, type="table", bbox=(0, 0, 1, 1), reading_order=2)])
    chains = [
        ("텍스트", [ExtractedContent(element_id=x_id, corrected_text="가", ocr_confidence=1.0, box_level=1)],
         [LLMOutput(element_id=x_id, corrected_text="가", routing_tier="ZERO")]),
        ("표", [ExtractedContent(element_id=t_id, corrected_text="<!표>", ocr_confidence=1.0, box_level=2)],
         [LLMOutput(element_id=t_id, corrected_text="<!표>", routing_tier="ZERO")]),
    ]
    seen = {}

    def fake_translate_file(src):
        seen.update(json.loads(src.read_text(encoding="utf-8")))
        out = src.with_name(src.name.replace("_in.json", "_out.json"))
        out.write_text(json.dumps({
            "braille_outputs": [BrailleOutput(element_id=x_id, braille_lines=["⠫"]).model_dump(mode="json")],
            "flat": {str(x_id): {"text": "⠫\n", "trail": [], "prefix": "", "suffix": "\n",
                                 "draft_texts": ["⠫\n"], "breaks": [1], "draft_breaks": [[1]]}},
        }), encoding="utf-8")
        return out

    monkeypatch.setitem(sys.modules, "translate_shim", types.SimpleNamespace(translate_file=fake_translate_file))
    braille, flat = pipeline._translate_by_package(task, layout, chains, True)

    assert seen["context"] == {"math_page": True, "korean_grade1": True, "english_grade1": False,
                               "choices_one_per_line": True}
    assert seen["box_levels"] == {str(t_id): 2}     # 표 체인 것만. 글 요소의 상자 위계는 표 엔진 입력이 아니다
    assert [label for label, _ in seen["chains"]] == ["텍스트", "표"]
    assert isinstance(braille[0], BrailleOutput) and braille[0].braille_lines == ["⠫"]
    fe = flat[x_id]                                  # 열쇠는 UUID, 칸은 FlatElement 와 같은 꼴(튜플)
    assert (fe.text, fe.breaks, fe.draft_texts, fe.draft_breaks) == ("⠫\n", (1,), ("⠫\n",), ((1,),))
