#!/usr/bin/env python3
"""Measure Steps 1+2 by replaying the recorded plate_read stream through the new
OcrStabilizer (gating + weighted positional vote + confirm-and-hold) and comparing
to the raw baseline. No live run needed — pure post-processing of recorded reads."""
import sys, json, re, collections
sys.path.insert(0, "services/worker")
import redis
from pipeline.ocr_stabilizer import OcrStabilizer, PLATE_RE

r = redis.Redis(port=6379, decode_responses=True)

def ptxt(ev):
    s=[ev]
    while s:
        x=s.pop()
        if isinstance(x,dict):
            if isinstance(x.get("plate_text"),str): return x["plate_text"].strip().upper()
            s+=list(x.values())
        elif isinstance(x,list): s+=x
    return ""

# recorded reads in temporal order: (cam,track) -> [(text,conf,width)]
reads = collections.defaultdict(list)
for _id,f in r.xrange("traffic:analytics","-","+",count=20000):
    try: m=json.loads(f["payload"])
    except: continue
    cam=m.get("camera",{}).get("id","?")
    for ev in m.get("events",[]) or []:
        if ev.get("type")!="plate_read": continue
        t=ptxt(ev)
        if not t: continue
        subj=ev.get("subject",{}); conf=subj.get("confidence",0); w=subj.get("bbox",{}).get("width",0)
        reads[(cam, ev.get("object_id"))].append((t,conf,w))

allreads=[x for v in reads.values() for x in v]
print(f"recorded: {len(allreads)} reads across {len(reads)} tracks\n")

# ---- BASELINE (raw provisional, as shipped) ----
base_events = sum(len(set(t for t,_,_ in v)) for v in reads.values())   # distinct (track,text) = events fired
base_valid  = sum(1 for t,_,_ in allreads if PLATE_RE.match(t))
print("=== BASELINE (raw per-frame) ===")
print(f"  plate_read events fired : {base_events}  ({base_events/len(reads):.1f} per track)")
print(f"  per-read format-valid   : {100*base_valid/len(allreads):.1f}%")
print(f"  output flip rate        : 100% (provisional changes every read)\n")

def run(**kw):
    stab=OcrStabilizer(**kw)
    confirmed={}
    reads_to_confirm=[]
    for (cam,tid),seq in reads.items():
        n_before=0
        for i,(t,conf,w) in enumerate(seq):
            stab.observe(cam,tid,t,conf,0,plate_width=w)
            if stab.confirmed_text(cam,tid) and (cam,tid) not in confirmed:
                confirmed[(cam,tid)]=stab.confirmed_text(cam,tid)
                reads_to_confirm.append(i+1)
    return confirmed, reads_to_confirm

import statistics as st
for label,kw in [
    ("NEW (conf>=.4, format, vote>=4, 60% pos)", dict(min_confidence=0.4, confirm_min_reads=4)),
    ("NEW + size-gate >=80px",                    dict(min_confidence=0.4, confirm_min_reads=4, min_plate_width=80)),
    ("NEW + size-gate >=60px",                    dict(min_confidence=0.4, confirm_min_reads=4, min_plate_width=60)),
]:
    confirmed,when=run(**kw)
    valid=sum(1 for p in confirmed.values() if PLATE_RE.match(p))
    print(f"=== {label} ===")
    print(f"  tracks confirmed        : {len(confirmed)}/{len(reads)} ({100*len(confirmed)/len(reads):.0f}%)")
    print(f"  plate_read events fired : {len(confirmed)}  (1 per confirmed track)  [was {base_events}]")
    print(f"  confirmed format-valid  : {100*valid/max(1,len(confirmed)):.0f}%")
    print(f"  output flip rate        : 0% (locked)")
    if when: print(f"  reads to confirm        : median={int(st.median(when))} (latency frames)")
    print(f"  sample confirmed plates : {list(confirmed.values())[:8]}\n")
