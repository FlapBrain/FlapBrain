"""
Serve the public site locally: site/web as static files plus the Railway
state service mounted at /api/state, so index.html behaves as it does on
Vercel (same-origin proxy) without deploying anything.

  py tools/site_dev.py               http://127.0.0.1:4670

Environment (same names the deployed service reads):
  FLY_BSC_RPC, FLY_WALLET, FLY_TOKEN, FLY_TOKEN_BLOCK
"""
import argparse
import sys
from pathlib import Path

import uvicorn
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "site" / "server"))
from main import app  # noqa: E402  - the state service

# the service answers "/" with JSON; on Vercel the static index.html wins, so here too
app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") != "/"]
app.mount("/", StaticFiles(directory=str(ROOT / "site" / "web"), html=True), name="web")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4670)
    a = ap.parse_args()
    print(f"\n  site preview - open http://127.0.0.1:{a.port}\n")
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")
