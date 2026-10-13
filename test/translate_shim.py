"""이관 3단계 측정 shim — 경계 파일 하나만 읽어 braille 패키지(`semojum_braille`)로 점역한다(#1370).

러너 `--translate-by package` 팔에서 `pipeline._translate_by_package` 가 교열본(`NNN_translate_in.json`)을
적고 이걸 부른다. 제품 경로에는 없다. 패키지는 `PYTHONPATH` 로 braille 체크아웃을 앞에 둔다.
점역 순서는 체인과 같다: 체인 점역 → `flatten_elements` → `LayoutBraille().layout`(이 순서여야 한다.
`layout()` 이 `braille_lines` 를 조판본으로 덮는다).

★ 패키지는 엔진 문맥값을 **자기** ContextVar 로 들고 있다(AI `app.ai.braille` 와 이름이 달라 한 프로세스에
  둘 다 올라간다). 그래서 다섯 값을 여기서 다시 놓는다. 하나라도 빠지면 기본값으로 조용히 점역한다.
  `flip` 은 그 값 하나를 뒤집는다. 출력이 바뀌어야 그 값이 닿은 것이다(양성 확인).

    python test/translate_shim.py [--flip 이름] <경계 파일 ...>
"""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import semojum_braille
from semojum_braille.encoder import constants, inline_math
from semojum_braille.encoder.formula_braille import FormulaBraille
from semojum_braille.encoder.layout_braille import LayoutBraille, flatten_elements
from semojum_braille.encoder.table_braille import TableBraille
from semojum_braille.encoder.text_braille import TextBraille
from semojum_braille.encoder.visual_braille import CartoonBraille, ChartGraphBraille, DiagramBraille, ImageBraille
from semojum_braille.schemas import LLMOutput

# 체인 라벨(pipeline `_factory`) → 엔진. 표는 상자 위계를 받아 따로 만든다.
_ENGINES = {"텍스트": TextBraille, "수식": FormulaBraille, "그림": ImageBraille, "만화": CartoonBraille,
            "차트": ChartGraphBraille, "도표": DiagramBraille}
_VARS = {"math_page": inline_math.MATH_PAGE, "korean_grade1": constants.KOREAN_GRADE1,
         "english_grade1": constants.ENGLISH_GRADE1, "choices_one_per_line": constants.CHOICES_ONE_PER_LINE}
FLIPS = (*_VARS, "box_level")


def translate_file(src: Path, flip: str = "") -> Path:
    """경계 파일 → 결과 파일 `…_translate_out.json`(뒤집으면 `…_translate_out.<이름>.json`)."""
    src = Path(src)
    b = json.loads(src.read_text(encoding="utf-8"))
    ctx = dict(b["context"])
    box = {UUID(k): v for k, v in b["box_levels"].items()}
    if flip == "box_level":
        box = {}
    elif flip:
        ctx[flip] = not ctx[flip]
    tokens = [(var, var.set(bool(ctx[name]))) for name, var in _VARS.items()]
    try:
        braille = []
        for label, outs in b["chains"]:
            eng = TableBraille(box) if label == "표" else _ENGINES[label]()
            braille.extend(eng.translate([LLMOutput.model_validate(o) for o in outs]))
        layout = SimpleNamespace(elements=[SimpleNamespace(**{**e, "element_id": UUID(e["element_id"])})
                                           for e in b["elements"]])
        flat = flatten_elements(braille, layout)
        if flip:        # 뒤집은 판은 견주기만 한다. result.txt 를 쓰면 본 팔 파일을 덮는다
            LayoutBraille().render(braille, b["page_no"], layout_result=layout)
        else:
            LayoutBraille().layout(braille, b["page_no"], b["job_id"], layout_result=layout)
    finally:
        for var, tok in reversed(tokens):
            var.reset(tok)
    out = src.with_name(src.name.replace("_in.json", f"_out{'.' + flip if flip else ''}.json"))
    out.write_text(json.dumps({
        "package": semojum_braille.__version__, "flip": flip,
        "braille_outputs": [bo.model_dump(mode="json") for bo in braille],
        "flat": {str(k): {"text": fe.text, "trail": [r.model_dump(mode="json") for r in fe.trail],
                          "prefix": fe.prefix, "suffix": fe.suffix, "draft_texts": list(fe.draft_texts),
                          "breaks": list(fe.breaks), "draft_breaks": [list(x) for x in fe.draft_breaks]}
                 for k, fe in flat.items()},
    }, ensure_ascii=False), encoding="utf-8")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--flip", choices=FLIPS, default="")
    ap.add_argument("files", nargs="+")
    a = ap.parse_args()
    for f in a.files:
        print(translate_file(Path(f), a.flip))
