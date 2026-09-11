"""
Live state for the flybrain site - BNB Chain edition.

Everything here is read straight off BNB Chain over JSON-RPC: eth_call,
eth_getBalance and eth_getLogs, which any reader can repeat against the same
public node. Before the launch FLY_TOKEN is empty and the token block of the
answer says so, so the page can show placeholders instead of an error.

Nothing is written, no key is loaded, and there is no code path here that can
sign anything. The site is a window, not a control panel.

Environment:
  FLY_BSC_RPC       BNB Chain JSON-RPC (default: the public Binance node)
  FLY_WALLET        the fly's launch wallet, for the budget readout
  FLY_TOKEN         the token contract once launched; empty until then
  FLY_TOKEN_BLOCK   the launch block, so the log scan does not start at 0
"""
import os
import time

import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

RPC = os.environ.get("FLY_BSC_RPC", "https://bsc-dataseed.binance.org")
CHAIN_ID = 56
CHAIN_NAME = "BNB Chain"
WALLET = os.environ.get("FLY_WALLET", "")
TOKEN = os.environ.get("FLY_TOKEN", "").strip().lower()
BIRTH_BLOCK = int(os.environ.get("FLY_TOKEN_BLOCK", "0") or 0)
# gas only: Flap charges no fixed creation fee on BNB Chain (docs/flap.md)
LAUNCH_COST_BNB = float(os.environ.get("FLY_LAUNCH_COST_BNB", "0.001"))

TRANSFER = ("0xddf252ad1be2c89b69c2b068fc378daa"
            "952ba7f163c4a11628f55a4df523b3ef")

app = FastAPI(title="flybrain")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["GET"],
    allow_headers=["*"])

_cache = {"at": 0.0, "data": None}
TTL = 20.0
_hold = {"at": 0.0, "val": (None, None)}
HOLD_TTL = 300.0


def _holders_cached(token):
    now = time.time()
    if now - _hold["at"] < HOLD_TTL:
        return _hold["val"]
    v = holders(token)
    if v[0] is not None:
        _hold.update(at=now, val=v)
        return v
    return _hold["val"]


def rpc(method, params):
    r = requests.post(RPC, json={"jsonrpc": "2.0", "id": 1,
                                 "method": method, "params": params},
                      timeout=15).json()
    if "error" in r:
        raise RuntimeError(str(r["error"])[:200])
    return r.get("result")


def as_int(v, default=0):
    if v is None:
        return default
    return int(v, 16) if str(v).startswith("0x") else int(v)


def call_str(to, selector):
    """Decode an ABI-encoded string return, e.g. name() or symbol()."""
    x = rpc("eth_call", [{"to": to, "data": selector}, "latest"])
    if not x or len(x) < 130:
        return ""
    n = int(x[66:130], 16)
    try:
        return bytes.fromhex(x[130:130 + n * 2]).decode("utf-8", "replace")
    except Exception:
        return ""


def holders(token):
    """Unique addresses that have ever received the token, from Transfer logs."""
    try:
        logs = rpc("eth_getLogs", [{"address": token,
                                    "fromBlock": hex(BIRTH_BLOCK),
                                    "toBlock": "latest",
                                    "topics": [TRANSFER]}])
        seen = set()
        for lg in logs or []:
            t = lg.get("topics") or []
            if len(t) >= 3:
                seen.add("0x" + t[2][-40:])
        seen.discard("0x" + "0" * 40)
        return len(seen), len(logs or [])
    except Exception:
        return None, None


def state():
    now = time.time()
    if _cache["data"] and now - _cache["at"] < TTL:
        return _cache["data"]

    out = {"chain": {"name": CHAIN_NAME, "id": CHAIN_ID, "rpc": RPC},
           "ok": True, "error": None, "launched": bool(TOKEN)}
    try:
        out["chain"]["block"] = as_int(rpc("eth_blockNumber", []))
        out["chain"]["gas_gwei"] = round(as_int(rpc("eth_gasPrice", [])) / 1e9, 4)

        if WALLET:
            bal = as_int(rpc("eth_getBalance", [WALLET, "latest"]))
            out["wallet"] = {
                "address": WALLET, "bnb": bal / 1e18,
                "launches_left": int(bal / 1e18 / LAUNCH_COST_BNB),
            }
        else:
            out["wallet"] = None

        if TOKEN:
            sup = as_int(rpc("eth_call", [{"to": TOKEN, "data": "0x18160ddd"},
                                          "latest"]))
            h, transfers = _holders_cached(TOKEN)
            out["token"] = {
                "address": TOKEN,
                "name": call_str(TOKEN, "0x06fdde03"),
                "symbol": call_str(TOKEN, "0x95d89b41"),
                "supply": sup / 1e18,
                "addresses_touched": h,
                "transfers": transfers,
                "pair": "BNB",
                "creator_tax_pct": 0,
                "url": f"https://flap.sh/bnb/{TOKEN}",
                "explorer": f"https://bscscan.com/token/{TOKEN}",
            }
        else:
            out["token"] = None
    except Exception as exc:
        out["ok"] = False
        out["error"] = str(exc)[:200]

    out["updated"] = int(now)
    _cache.update(at=now, data=out)
    return out


@app.get("/api/state")
def api_state():
    return state()


@app.get("/api/health")
def health():
    return {"ok": True, "t": int(time.time())}


@app.get("/")
def root():
    return {"service": "flybrain", "see": "/api/state"}
