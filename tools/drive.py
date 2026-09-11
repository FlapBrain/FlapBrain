"""
Drive a live rig the way web/live.html does: send start, print the log.

Also records every websocket message with its arrival time into
build/demo/<label>.json (plus /neurons and /status), which demo.py can
replay without a brain or a browser.
"""
import asyncio, json, sys, time, argparse
from pathlib import Path
import requests
import websockets

ap = argparse.ArgumentParser()
ap.add_argument("port", type=int, nargs="?", default=4652)
ap.add_argument("desc", nargs="?", default="test launch by a fruit fly connectome")
ap.add_argument("--name", default="test")
ap.add_argument("--ticker", default="TEST")
ap.add_argument("--save", default=None, help="label for build/demo/<label>.json")
ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
a = ap.parse_args()
port, desc = a.port, a.desc
DEMO = Path(a.root) / "build" / "demo"


async def main():
    rec = []
    async with websockets.connect(f"ws://127.0.0.1:{port}/run", max_size=None) as ws:
        start = {"action": "start", "name": a.name, "ticker": a.ticker,
                 "desc": desc, "trained": True, "headful": False, "steps": 18}
        await ws.send(json.dumps(start))
        t0 = time.time()
        frames = 0
        kinds = {}
        last = time.time()
        summary = {"filled_by_fly": None, "filled_by_rig": None, "outcome": None,
                   "asked": None, "stuck": False, "seconds": None}
        while True:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
            except asyncio.TimeoutError:
                print(f"[{time.time()-t0:6.1f}s] (no message for 20s; frames={frames} kinds={kinds})")
                if time.time() - t0 > 480:
                    print("giving up"); summary["stuck"] = True; break
                continue
            rec.append({"at": round(time.time() - t0, 3), "m": m})
            t = m.get("type")
            if t in ("frame", "cursor", "watch"):
                frames += 1
                kinds[t] = kinds.get(t, 0) + 1
                if time.time() - last > 10:
                    last = time.time()
                    print(f"[{time.time()-t0:6.1f}s] ... {frames} frames so far {kinds} note={m.get('note','')!r}")
                continue
            if t == "step":
                print(f"[{time.time()-t0:6.1f}s] step {m['t']:02d} target={m['target']:<7} "
                      f"filled={m['filled']} click={m['click']} {m.get('note','')} "
                      f"label={m.get('create_label','')!r}")
                continue
            if t == "fields":
                summary["filled_by_fly"] = m.get("by_fly")
                summary["filled_by_rig"] = m.get("by_rig")
            body = {k: v for k, v in m.items() if k not in ('shot', 'idx')}
            print(f"[{time.time()-t0:6.1f}s] {t}: {json.dumps(body, ensure_ascii=False)[:900]}")
            if t == "done":
                summary["outcome"] = m.get("outcome")
                summary["asked"] = m.get("asked")
                break
        summary["seconds"] = round(time.time() - t0, 1)
        print(f"({frames} frame/cursor/watch messages)")
        print("SUMMARY " + json.dumps(summary, ensure_ascii=False))

    if a.save:
        DEMO.mkdir(parents=True, exist_ok=True)
        (DEMO / f"{a.save}.json").write_text(json.dumps(
            {"start": start, "recorded": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "summary": summary, "messages": rec}), encoding="utf-8")
        try:
            r = requests.get(f"http://127.0.0.1:{port}/neurons", timeout=30)
            (DEMO / "neurons.bin").write_bytes(r.content)
            (DEMO / "neurons.count").write_text(r.headers.get("X-Count", "0"))
            st = requests.get(f"http://127.0.0.1:{port}/status", timeout=30).json()
            (DEMO / "status.json").write_text(json.dumps(st))
        except Exception as e:
            print("could not save neurons/status:", e)
        print(f"saved build/demo/{a.save}.json ({len(rec)} messages)")

asyncio.run(main())
