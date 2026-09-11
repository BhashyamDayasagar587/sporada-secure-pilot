#!/usr/bin/env python3
"""OCR/plate quality study from traffic:analytics 'plate_read' events.
Per-(camera,track) read sequences -> instability, garbage, format, plate px size."""
import json, re, collections, statistics as st
import redis

r = redis.Redis(port=6379, decode_responses=True)
entries = r.xrange("traffic:analytics", "-", "+", count=20000)
VALID = re.compile(r"^[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{3,4}$")

def find_plate_text(ev):
    # plate_text can be nested (subject.attributes / details); search recursively
    stack=[ev]
    while stack:
        x=stack.pop()
        if isinstance(x, dict):
            if "plate_text" in x and isinstance(x["plate_text"], str):
                return x["plate_text"].strip()
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x)
    return ""

reads = collections.defaultdict(list)   # (cam,track) -> [(text,conf,w,h)]
n_ev = 0
for _id, f in entries:
    try: m = json.loads(f["payload"])
    except Exception: continue
    cam = m.get("camera", {}).get("id", "?")
    for ev in m.get("events", []) or []:
        if ev.get("type") != "plate_read" and ev.get("event_type") != "plate_read":
            continue
        n_ev += 1
        txt = find_plate_text(ev)
        if not txt: continue
        subj = ev.get("subject", {})
        conf = subj.get("confidence", ev.get("confidence", 0))
        bb = subj.get("bbox", {})
        reads[(cam, ev.get("object_id"))].append((txt, conf, bb.get("width",0), bb.get("height",0)))

all_reads = [x for v in reads.values() for x in v]
texts = [t for t,_,_,_ in all_reads]
print(f"plate_read events: {n_ev} | with text: {len(all_reads)} | tracks: {len(reads)}")

# format / garbage
valid = [t for t in texts if VALID.match(t)]
def maxrun(s):
    b=run=1
    for i in range(1,len(s)): run=run+1 if s[i]==s[i-1] else 1; b=max(b,run)
    return b
runny = [t for t in texts if maxrun(t)>=3]
print(f"\n=== FORMAT/GARBAGE ===")
print(f"valid Indian format: {len(valid)}/{len(texts)} = {100*len(valid)/max(1,len(texts)):.1f}%")
print(f"length dist: {dict(sorted(collections.Counter(len(t) for t in texts).items()))}")
print(f">=3 repeated chars: {100*len(runny)/max(1,len(texts)):.0f}%  e.g. {runny[:10]}")

# plate pixel size (OCR feasibility)
ws=[w for _,_,w,h in all_reads if w]; hs=[h for _,_,w,h in all_reads if h]
if ws:
    print(f"\n=== PLATE CROP SIZE (px) ===")
    print(f"width:  p10={int(st.quantiles(ws,n=10)[0])} median={int(st.median(ws))} p90={int(st.quantiles(ws,n=10)[8])}")
    print(f"height: p10={int(st.quantiles(hs,n=10)[0])} median={int(st.median(hs))} p90={int(st.quantiles(hs,n=10)[8])}")
    print(f"plates <16px wide (too small for OCR): {100*sum(1 for w in ws if w<16)/len(ws):.0f}%")

# per-track instability
multi = {k:v for k,v in reads.items() if len(v)>=3}
if multi:
    distinct=[len(set(t for t,_,_,_ in v)) for v in multi.values()]
    flips=[sum(1 for i in range(1,len(v)) if v[i][0]!=v[i-1][0])/(len(v)-1) for v in multi.values()]
    print(f"\n=== PER-TRACK STABILITY ({len(multi)} tracks w/ >=3 reads) ===")
    print(f"distinct plate_text/track: mean={st.mean(distinct):.1f} median={st.median(distinct)} max={max(distinct)}")
    print(f"frame-to-frame flip rate: mean={100*st.mean(flips):.0f}%  (tracks that NEVER repeat a read: {100*sum(1 for d,v in zip(distinct,multi.values()) if d==len(v))/len(multi):.0f}%)")
    worst=sorted(multi.items(), key=lambda kv:len(set(t for t,_,_,_ in kv[1])), reverse=True)[:6]
    print("worst fast-changing tracks:")
    for (cam,tid),v in worst:
        ts=[t for t,_,_,_ in v]
        print(f"  {cam} #{tid}: {len(set(ts))} distinct/{len(ts)} reads -> {ts[:9]}")
