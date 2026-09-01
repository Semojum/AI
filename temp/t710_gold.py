"""T710 — 정답이 한 쪽에 그림이 여럿일 때 번호를 붙이는가. 전수·읽기 전용."""
import collections, glob, json, os, re, sys
sys.path.insert(0,"/home/pj14/v2/code/AI")
from app.utils.braille_ascii import ascii_to_unicode
OPEN = re.compile(r"⠠⠄([^\n]{1,30}?)⠐⠂")
NUM  = re.compile(r"⠼[⠁-⠚]+")
st=collections.Counter(); heads=collections.Counter(); ex=collections.defaultdict(list)
npage=0
for rs in sorted(glob.glob("/home/pj14/v2/code/AI/storage/jobs/corpus-c16exp-*/run_state.json")):
    for rec in json.load(open(rs,encoding="utf-8"))["pages"]:
        gp=rec.get("gold")
        if not gp or not os.path.exists(gp): continue
        npage+=1
        g=ascii_to_unicode(open(gp,encoding="utf-8").read(),backtick="cell")
        found=[m.group(1).strip("⠀") for m in OPEN.finditer(g)]
        if not found: continue
        st["유형어 쪽"]+=1; st["유형어 총"]+=len(found)
        for f in found: heads[f]+=1
        cnt=collections.Counter(found); dup={k:v for k,v in cnt.items() if v>1}
        if len(found)>1:
            st["한 쪽에 둘 이상"]+=1
            if dup:
                st["같은 유형어 반복"]+=1; st["반복 건수"]+=sum(dup.values())
                st["  └ 그중 번호 붙은 것"]+=sum(1 for f in dup if NUM.search(f))
                if len(ex["dup"])<10: ex["dup"].append((rec.get("vol"),rec["page"],dict(dup)))
            else:
                st["서로 다른 유형어로 구분"]+=1
                if len(ex["diff"])<6: ex["diff"].append((rec.get("vol"),rec["page"],found[:4]))
        if any(NUM.search(f) for f in found): st["유형어에 숫자 포함"]+=1
print(f"검사 {npage}쪽")
for k,v in st.most_common(): print(f"  {k:26} {v:6,}")
print("\n-- 정답 유형어 상위 12 --")
for k,v in heads.most_common(12): print(f"   {v:5}  {k}")
print("\n-- 같은 유형어 반복 표본 --")
for e in ex["dup"]: print("  ",e)
print("\n-- 다른 유형어로 구분한 표본 --")
for e in ex["diff"]: print("  ",e)
