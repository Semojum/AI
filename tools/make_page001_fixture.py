"""`test/test_data/page_001` 의 MinerU · 경계 파일 픽스처를 우리가 만든 합성 쪽에서 다시 뽑는다(#1257).

예전 픽스처는 바깥 자료(시험지) 1쪽을 뽑은 것이라 지웠다. 이 스크립트는
  1) 글자층이 있는 합성 쪽 하나(머리말 · 제목 · 문단 · 그림 · 목록 · 표 · 쪽 번호)를 fitz 로 만들고
  2) 실제 파이프라인 `run_pipeline.py` 로 MinerU 산출물과 경계 파일을 뽑아(캡션은 끔, SEMOJUM_NO_CAPTION=1)
  3) `merged_layout.json` · `mineru_raw/` · `data/001_txt_result.json` 을 page_001 로 옮긴다(그림 경로를 고쳐 적는다).

    MINERU_BIN=<mineru 실행 파일> [KOREAN_TTF=<한글 TTF>] python tools/make_page001_fixture.py

같은 폴더의 `layout/` · `type/` 목은 손대지 않는다. MinerU 가 그림 · 표를 잡지 못하면 멈춘다.
★ 한글 글꼴은 **파일을 박아 넣는다**(기본 나눔고딕, OFL). fitz 내장 CJK 글꼴(`korea`)은 PDF 에 안 박혀
  MinerU 가 쪽을 그릴 때 한글이 빈칸으로 나왔다(2026-10-09 1차: 글 요소 0, 표 칸이 비었다).
"""
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
DST = ROOT / "test" / "test_data" / "page_001"
JOB = "test-job-001"
OUT = ROOT / "storage" / "jobs" / JOB / "temp" / "page_001"
FONT = "ng"
FONT_FILE = os.environ.get("KOREAN_TTF") or str(Path.home() / ".fonts" / "NanumGothic.ttf")

PARAGRAPH = ("물은 온도에 따라 고체, 액체, 기체로 상태가 바뀐다. 얼음이 녹아 물이 되는 것을 융해라고 하고, "
             "물이 끓어 수증기가 되는 것을 기화라고 한다. 아래 그림은 얼음이 든 비커를 가열하는 모습이다.")
ITEMS = ["① 얼음이 녹는 동안에는 온도가 일정하게 유지된다.",
         "② 물이 끓는 동안에도 가한 열은 상태를 바꾸는 데 쓰인다.",
         "③ 수증기가 다시 물이 되는 것을 액화라고 한다."]
TABLE = [["상태 변화", "열의 출입", "예"],
         ["융해", "흡수", "얼음이 녹는다"],
         ["응고", "방출", "물이 언다"]]


def _picture() -> bytes:
    """비커 그림(얼음 · 물 · 불꽃 · 수증기). 글자와 축은 넣지 않는다.

    축이 있는 꺾은선은 MinerU 가 `chart` 로 잡아(2026-10-09 2차) 옛 픽스처와 갈래가 달라졌다. 그래서 그림으로 그린다.
    """
    im = Image.new("RGB", (900, 600), "white")
    d = ImageDraw.Draw(im)
    d.rectangle([330, 470, 570, 520], fill="#777777")                         # 버너 받침
    d.polygon([(420, 470), (450, 400), (470, 440), (490, 390), (520, 470)], fill="#f08a24")   # 불꽃
    d.polygon([(445, 470), (465, 425), (480, 470)], fill="#f5d142")
    d.rectangle([340, 360, 560, 380], fill="#999999")                         # 삼발이 판
    d.line([(350, 380), (330, 470)], fill="#555555", width=8)
    d.line([(550, 380), (570, 470)], fill="#555555", width=8)
    d.rounded_rectangle([360, 130, 540, 360], radius=24, outline="#334455", width=8)   # 비커
    d.rectangle([368, 230, 532, 352], fill="#9cc8f0")                         # 물
    for x, y in ((385, 205), (440, 215), (492, 200)):                         # 얼음
        d.rectangle([x, y, x + 38, y + 38], fill="#f4fbff", outline="#7aa7c7", width=4)
    for x in (400, 450, 500):                                                 # 수증기
        d.arc([x - 20, 60, x + 20, 110], 200, 340, fill="#aaaaaa", width=5)
        d.arc([x - 20, 90, x + 20, 140], 20, 160, fill="#aaaaaa", width=5)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def make_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()                                     # A4 595×842pt
    page.insert_font(fontname=FONT, fontfile=FONT_FILE)
    page.insert_text((72, 48), "통합과학 연습 자료", fontname=FONT, fontsize=9, color=(0.4, 0.4, 0.4))
    page.insert_text((72, 100), "1. 물의 상태 변화", fontname=FONT, fontsize=17)
    page.insert_textbox(fitz.Rect(72, 118, 523, 200), PARAGRAPH, fontname=FONT, fontsize=11, lineheight=1.6)
    page.insert_image(fitz.Rect(122, 205, 472, 415), stream=_picture())
    y = 445
    for it in ITEMS:
        page.insert_text((80, y), it, fontname=FONT, fontsize=11)
        y += 22
    top, row_h, xs = 530, 30, (90, 230, 350, 505)
    for r in range(len(TABLE) + 1):
        page.draw_line(fitz.Point(xs[0], top + r * row_h), fitz.Point(xs[-1], top + r * row_h), width=0.8)
    for x in xs:
        page.draw_line(fitz.Point(x, top), fitz.Point(x, top + len(TABLE) * row_h), width=0.8)
    for r, row in enumerate(TABLE):
        for c, cell in enumerate(row):
            page.insert_text((xs[c] + 8, top + r * row_h + 20), cell, fontname=FONT, fontsize=10.5)
    page.insert_text((292, 805), "3", fontname=FONT, fontsize=9)
    doc.save(path)
    doc.close()


def main() -> None:
    if not os.environ.get("MINERU_BIN"):
        sys.exit("MINERU_BIN 을 주십시오(MinerU 실행 파일 경로).")
    pdf = ROOT / "storage" / "page001_sample.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    make_pdf(pdf)
    if OUT.exists():
        shutil.rmtree(OUT)
    env = dict(os.environ, SEMOJUM_NO_CAPTION="1")
    subprocess.run([sys.executable, "run_pipeline.py", str(pdf), JOB, "1", "--debug"],
                   cwd=ROOT, env=env, check=True)        # --debug 라야 merged_layout.json 을 쓴다

    layout = json.loads((OUT / "merged_layout.json").read_text(encoding="utf-8"))
    kinds = {e["type"] for e in layout}
    if not {"image", "table"} <= kinds:
        sys.exit(f"MinerU 가 그림 · 표를 다 잡지 못했다: {sorted(kinds)}")
    old = str(OUT.relative_to(ROOT)) + "/"
    new = str(DST.relative_to(ROOT)) + "/"
    for name in ("mineru_raw", "data"):
        if (DST / name).exists():
            shutil.rmtree(DST / name)
    shutil.copytree(OUT / "mineru_raw", DST / "mineru_raw")
    (DST / "data").mkdir()
    for src, dst in ((OUT / "merged_layout.json", DST / "merged_layout.json"),
                     (OUT / "data" / "001_txt_result.json", DST / "data" / "001_txt_result.json")):
        dst.write_text(src.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    print("요소:", sorted(kinds), "→", DST)


if __name__ == "__main__":
    main()
