"""점자 조판 공용 상수.

여러 braille 모듈(translator·layout·text/table/image/… braille)에서 중복 정의하던
32칸·25줄을 한 곳으로 모은다. (BBPG 1장2절1: 32칸 줄바꿈, 25줄 페이지 넘김.)
"""

COLS = 32  # 한 줄 칸 수
ROWS = 25  # 한 페이지 줄 수
