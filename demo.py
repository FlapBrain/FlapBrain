"""
Demo mode for the live viewer: replay a recorded dry run.

No brain is loaded, no browser is opened, nothing touches flap.sh or the
chain. The page at / is the same web/live.html the rigs serve; /neurons and
/status come from files, and the START button replays a websocket recording
made by scratch tooling during a real dry run, message for message, at the
original timing. It exists so the stream layout (OBS, fonts, panel sizes)
can be arranged days before launch without running anything real.

  py demo.py                        replays build/demo/dryrun.json on :4653
  py demo.py --take build/demo/x.json --speed 2

To make a recording: run flaplive.py, then drive one episode with
  py tools/drive.py 4652 "description" --save dryrun
"""
import argparse
import asyncio
import json
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response

ROOT = Path(__file__).parent
DEMO = ROOT / "build" / "demo"

app = FastAPI()
CFG = {"take": DEMO / "dryrun.json", "speed": 1.0, "loop": False}


@app.get("/")
async def index():
    return HTMLResponse((ROOT / "web" / "live.html").read_text(encoding="utf-8"))


@app.get("/neurons")
async def neurons():
    data = (DEMO / "neurons.bin").read_bytes()
    count = (DEMO / "neurons.count").read_text().strip()
    return Response(content=data, media_type="application/octet-stream",
                    headers={"X-Count": count})


@app.get("/status")
async def status():
    try:
        st = json.loads((DEMO / "status.json").read_text())
    except Exception:
        st = {"wallet": None, "sol": 0, "unit": "BNB"}
    st.update({"venue": "DEMO - replaying a recorded dry run",
               "live": False, "armed": True, "demo": True})
    return st


@app.websocket("/run")
async def run(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            if msg.get("action") != "start":
                continue
            take = json.loads(Path(CFG["take"]).read_text(encoding="utf-8"))
            msgs = take["messages"]
            while True:
                t0 = time.time()
                for item in msgs:
                    due = t0 + item["at"] / CFG["speed"]
                    delay = due - time.time()
                    if delay > 0:
                        await asyncio.sleep(delay)
                    await ws.send_text(json.dumps(item["m"]))
                if not CFG["loop"]:
                    break
                await asyncio.sleep(3)
    except WebSocketDisconnect:
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4653)
    ap.add_argument("--take", default=str(CFG["take"]))
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--loop", action="store_true", help="replay again when it ends")
    a = ap.parse_args()
    CFG.update(take=Path(a.take), speed=a.speed, loop=a.loop)
    if not Path(a.take).exists():
        raise SystemExit(f"no recording at {a.take} - make one with tools/drive.py --save")
    n = len(json.loads(Path(a.take).read_text(encoding="utf-8"))["messages"])
    print(f"\n  demo mode - {n} recorded messages from {a.take}\n"
          f"  open http://localhost:{a.port} and press START\n")
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")
