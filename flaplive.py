"""
The live rig, BNB Chain edition: the fly on flap.sh/create.

Same brain, same streaming, same viewer as rhlive.py - a different venue and
a different wallet. Runs on its own port so the rigs can coexist. The brain
files are untouched; the generic loop (screenshot -> brain -> cursor -> click
inside a field -> type) is imported from rhlive.py, and only the venue-specific
parts are written here.

What is different from pons:

  * no terms gate, no theme toggle: flap.sh is dark by default
  * the form has stable element ids (#name, #symbol, #description, #image)
  * no paired-asset list and no Advanced panel to open
  * the wallet is the same EIP-1193 provider (rhprovider.py); flap.sh lists
    it under "installed" via EIP-6963 and connects it with no login signature
  * the launch fee is gas only; docs/flap.md has the details and the caveats

Two ways to launch, chosen by FLY_FLAP_MODE:

  site    (default) the fly and the rig fill the site's form, the rig presses
          the site's own Create button, and the page's single
          eth_sendTransaction is signed in Python - the pons path
  direct  the fly and the rig fill the form, then the rig reads the fields
          back, uploads the metadata to Flap's API, computes the vanity salt
          and calls Portal.newTokenV6 / newTokenV7 itself - the fallback for
          when the site's button cannot be trusted to produce one transaction

Both stop dead unless FLY_RH_LIVE=1. With it at 0 the site path stops on the
Create button and the direct path stops after simulating the call with
eth_call. FLY_FLAP_PROBE=1 lets a dry run press the site button anyway so
the transaction the page asks for can be seen and decoded - it is refused
before anything is signed.

  py flaplive.py                 http://localhost:4652
"""
import argparse
import asyncio
import base64
import io
import json
import os
import re
import time
from pathlib import Path

import numpy as np
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response

from envcfg import load_env
from bscwallet import account, balance, rpc_url, CHAIN_ID, GAS_RESERVE_BNB
from rhprovider import attach, send_transaction
import flapportal
from flapportal import (PORTAL, decode_launch, decode_error, predicted_address,
                        encode_new_token_v6, encode_new_token_v7,
                        standard_token_params, standard_token_v7_params,
                        upload_meta, TOKEN_VERSION, FEE_TYPE, ZERO)
from flapsalt import find_salt, SUFFIX_STANDARD, SUFFIX_TAX
# the generic loop - untouched in rhlive.py, reused here
from rhlive import (STATE, boot, say, browser_allowed, inside, smooth_scroll,
                    scroll_to_el, glide, step_brain)

ROOT = Path(__file__).parent
_E = load_env()                                    # .env plus FLY_* from the shell
URL = _E.get("FLY_FLAP_URL", "https://flap.sh/create?lang=en")
IMAGE = "assets/flycoin_square.png"
X_HANDLE = _E.get("FLY_FLAP_X", "")                # your own account, or empty
MODE = _E.get("FLY_FLAP_MODE", "site")             # site | direct
TOKEN_KIND = _E.get("FLY_FLAP_TOKEN", "std")       # std | tax (direct mode)
COOLDOWN_S = int(_E.get("FLY_FLAP_COOLDOWN_S", "3600"))
PROBE = _E.get("FLY_FLAP_PROBE", "0") == "1"
MIN_SHARE_WEI = int(float(_E.get("FLY_FLAP_MIN_SHARE", "10000")) * 10**18)
CONNECT_RE = re.compile(r"connect|连接钱包|連接錢包", re.I)
LAST = ROOT / "build" / "flap_last_launch.json"
TOKEN_PAGE = "https://flap.sh/bnb/{addr}"

app = FastAPI()


def live_flag(env=None):
    """
    One switch arms every rig in this repo: FLY_RH_LIVE=1 in .env. On launch
    day that line and a funded wallet are the only two things that change.
    """
    return (env or load_env()).get("FLY_RH_LIVE", "0") == "1"


@app.get("/")
async def index():
    return HTMLResponse((ROOT / "web" / "live.html").read_text(encoding="utf-8"))


@app.get("/neurons")
async def neurons():
    return Response(content=STATE["xyz"].tobytes() + STATE["grp"].tobytes(),
                    media_type="application/octet-stream",
                    headers={"X-Count": str(len(STATE["grp"]))})


@app.get("/status")
async def status():
    env = load_env()
    try:
        acct = account(env)
        bnb = balance(env, quiet=True)
        return {"wallet": acct.address, "sol": bnb, "unit": "BNB",
                "venue": f"flap.sh ({MODE})",
                "chain": f"BNB Chain {CHAIN_ID}",
                "live": live_flag(env), "armed": browser_allowed()}
    except SystemExit:
        return {"wallet": None, "sol": 0, "unit": "BNB", "live": False,
                "armed": browser_allowed()}


# --------------------------------------------------------------------------
# the flap.sh create page
# --------------------------------------------------------------------------
# Fields are found by id - flap.sh gives every input a stable one and no
# placeholder, the opposite of pons. The launch button is the only visible
# type=submit on the page.
DOM_JS = """() => {
  const out = {};
  const byId = (k, id) => {
    const e = document.getElementById(id);
    if (!e) return;
    const r = e.getBoundingClientRect();
    if (r.width === 0) return;
    out[k] = {x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width),
              h:Math.round(r.height), filled:(e.value||'').length>0}; };
  byId('name', 'name');
  byId('ticker', 'symbol');
  byId('desc', 'description');
  // The form's own button carries no type attribute ("Create Token", 240px
  // wide, last in the form). The header has a narrower "Create Token" too,
  // so match on text AND width.
  const rx = /create token|創建代幣|创建代币/i;
  const pick = [...document.querySelectorAll('form button, button')]
    .map(b => ({b, r: b.getBoundingClientRect()}))
    .filter(o => rx.test(o.b.textContent||'') && o.r.width > 150 && o.r.height > 30
                 && (o.b.getAttribute('type')||'submit') !== 'button')
    .sort((p, q) => q.r.y - p.r.y)[0];
  if (pick) { const r = pick.r;
    out.launch = {x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width),
                  h:Math.round(r.height), label:(pick.b.textContent||'').trim(),
                  disabled: pick.b.disabled}; }
  return out; }"""

SCROLL_JS = """() => {
  const rx = /create token|創建代幣|创建代币/i;
  const b = [...document.querySelectorAll('form button, button')]
    .find(x => rx.test(x.textContent||'') && x.getBoundingClientRect().width > 150
               && (x.getAttribute('type')||'submit') !== 'button');
  if (b) b.scrollIntoView({block:'center'}); }"""

SEL = {"name": "#name", "ticker": "#symbol", "desc": "#description",
       "x": "#twitter"}
OPTIONAL = {"x"}

# flap.sh paints the ground on <html class="dark">; body is transparent
BG_JS = "() => getComputedStyle(document.documentElement).backgroundColor"

# flap.sh scrolls an inner container, not the window: window.scrollTo does
# nothing there, so the rig eases whichever ancestor actually scrolls
SCROLLER_JS = """(a) => {
  const el = eval(a[0]); if (!el) return null;
  let s = el.parentElement;
  while (s && s !== document.body) {
    const cs = getComputedStyle(s);
    if (/(auto|scroll)/.test(cs.overflowY) && s.scrollHeight > s.clientHeight + 8) break;
    s = s.parentElement; }
  const win = !s || s === document.body;
  const r = el.getBoundingClientRect();
  const top = win ? window.scrollY : s.scrollTop;
  const vh = win ? innerHeight : s.clientHeight;
  const sTop = win ? 0 : s.getBoundingClientRect().top;
  // scrollTop that puts the element's top at a[1] * viewport height
  const target = Math.max(0, top + (r.top - sTop) - a[1] * vh);
  if (a[2] !== null) { if (win) window.scrollTo(0, a[2]); else s.scrollTop = a[2]; return null; }
  return {win, start: top, target}; }"""


async def scroll_form(page, el_js, send=None, offset=0.3, ms=1200, steps=28):
    """Ease the real scroll container until `el_js` sits `offset` down it."""
    try:
        info = await page.evaluate(SCROLLER_JS, [el_js, offset, None])
        if not info:
            return False
        for i in range(1, steps + 1):
            t = i / steps
            t = t * t * (3 - 2 * t)
            y = info["start"] + (info["target"] - info["start"]) * t
            await page.evaluate(SCROLLER_JS, [el_js, offset, y])
            await asyncio.sleep(ms / 1000.0 / steps)
        return True
    except Exception:
        return False


def _is_dark(css):
    import re
    n = re.findall("[0-9.]+", css or "")
    if len(n) < 3:
        return False
    r, g, b = (float(x) for x in n[:3])
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) < 110


async def ensure_dark(page, send=None):
    """
    flap.sh is dark by default (html.dark). Measure, and only if the site has
    remembered a light preference put the class back - the fly's retina was
    tuned against dark UI and the README says light mode breaks it.
    """
    try:
        was = await page.evaluate(BG_JS)
        if _is_dark(was):
            if send:
                await send({"type": "log", "msg": f"theme already dark ({was})"})
            return True
        await page.evaluate("""() => {
            document.documentElement.classList.add('dark');
            document.documentElement.classList.remove('light');
            try { localStorage.setItem('theme', 'dark'); } catch (e) {} }""")
        await page.wait_for_timeout(800)
        now = await page.evaluate(BG_JS)
        if send:
            await send({"type": "log", "msg": f"theme {was} -> {now}"})
        return _is_dark(now)
    except Exception as e:
        if send:
            await send({"type": "log", "msg": f"theme check failed: {str(e)[:90]}"})
        return False


async def connect_wallet(page, send=None, shot=None):
    """
    Use the site's own connect flow: the header button opens a wallet list,
    and the injected provider is on it under "installed" (EIP-6963). No
    signature is requested - measured on 2026-09-11, the connect makes only
    eth_chainId / eth_accounts / wallet_requestPermissions / eth_requestAccounts.
    """
    def note(m):
        return send and send({"type": "log", "msg": m})

    try:
        # wagmi auto-connects the injected provider a few seconds after load;
        # give it that time before reaching for the button
        already = False
        for _ in range(16):
            already = await page.evaluate(
                """() => /0x[0-9a-fA-F]{2,6}(\\.{2,3}|…)[0-9a-fA-F]{2,6}/.test(
                       document.body.innerText)""")
            if already:
                break
            await page.wait_for_timeout(500)
        if already:
            await note("wallet connected: the page shows the fly's address")
            return True
        # the header is duplicated for a mobile drawer, so the first match by
        # text is a zero-size button; pick the visible one by geometry
        box = await page.evaluate(
            """() => { const rx = /connect|连接钱包|連接錢包/i;
               const b = [...document.querySelectorAll('button')]
                 .map(b => ({b, r: b.getBoundingClientRect()}))
                 .find(o => rx.test(o.b.textContent||'') && o.r.width > 60 && o.r.height > 20);
               if (!b) return null;
               return {x: b.r.x, y: b.r.y, width: b.r.width, height: b.r.height}; }""")
        if not box:
            await note("connect button not found")
            return False
        await glide(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2,
                    send, hold=0.4)
        await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        await page.wait_for_timeout(1500)
        if shot:
            await shot("wallet list")
        rb = None
        for _ in range(16):
            rb = await page.evaluate(
                """() => { const e = [...document.querySelectorAll('*')]
                     .find(x => x.children.length === 0 && (x.textContent||'').trim() === 'FlapBrain'
                                && x.getBoundingClientRect().width > 0);
                   if (!e) return null; const r = e.getBoundingClientRect();
                   return {x: r.x, y: r.y, width: r.width, height: r.height}; }""")
            if rb:
                break
            await page.wait_for_timeout(500)
        if not rb:
            await note("the wallet list did not show FlapBrain")
            return False
        await glide(page, rb["x"] + rb["width"] / 2, rb["y"] + rb["height"] / 2,
                    send, hold=0.4)
        await page.mouse.click(rb["x"] + rb["width"] / 2, rb["y"] + rb["height"] / 2)
        await page.wait_for_timeout(2500)
        ok = await page.evaluate(
            """() => /0x[0-9a-fA-F]{2,6}(\\.{2,3}|…)[0-9a-fA-F]{2,6}/.test(
                   document.body.innerText)""")
        await note("wallet connected through the site's list" if ok
                   else "clicked Flybrain but no address appeared in the header")
        if shot:
            await shot("wallet connected" if ok else "wallet not connected")
        return bool(ok)
    except Exception as e:
        await note(f"connect step failed: {str(e)[:120]}")
        return False


def _last_launch():
    try:
        return json.loads(LAST.read_text()).get("at", 0)
    except Exception:
        return 0


def _mark_launch(info):
    try:
        LAST.parent.mkdir(exist_ok=True)
        LAST.write_text(json.dumps({"at": int(time.time()), **info}, indent=1))
    except Exception:
        pass


def record_launch(token, tx_hash, receipt, acct, coin, asked):
    """
    launch/launch.json: the launch as it sits on chain, no secrets. voice.py
    reads it for the narrator and the site reads it for the token table.
    Written once, on a mined SUCCESS receipt.
    """
    try:
        blk = int(receipt.get("blockNumber", "0x0"), 16)
        gas_used = int(receipt.get("gasUsed", "0x0"), 16)
        gas_price = int(receipt.get("effectiveGasPrice", "0x0"), 16)
        now = int(time.time())
        info = {
            "contract": token, "chain": "BNB Chain", "chain_id": CHAIN_ID,
            "venue": "flap.sh", "tx": tx_hash, "block": blk,
            "launched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "launched_unix": now, "creator": acct.address,
            "name": coin.get("name"), "ticker": coin.get("ticker"),
            "meta": asked.get("meta"), "supply": 1000000000,
            "creator_tax_pct": 0.0, "paired_with": "BNB",
            "launch_cost_bnb": gas_used * gas_price / 1e18,
            "token_page": TOKEN_PAGE.format(addr=token),
            "explorer": f"https://bscscan.com/tx/{tx_hash}",
        }
        p = ROOT / "launch" / "launch.json"
        p.parent.mkdir(exist_ok=True)
        p.write_text(json.dumps(info, indent=1), encoding="utf-8")
        say(f"wrote {p}")
    except Exception as e:
        say(f"could not write launch/launch.json: {e}")


def cooldown_left():
    """Seconds until this wallet may launch again, by the rig's own clock.
    The Portal's RateLimitExceeded window is not documented, so the rig
    keeps a conservative one of its own."""
    return max(0, _last_launch() + COOLDOWN_S - int(time.time()))


# --------------------------------------------------------------------------
# the episode
# --------------------------------------------------------------------------
async def run_episode(ws, coin, steps, seed, headful):
    from playwright.async_api import async_playwright
    from PIL import Image

    fb, pilot, remap = STATE["brain"], STATE["pilot"], STATE["remap"]
    env = load_env()
    acct = account(env)
    rpc = rpc_url(env)
    live = live_flag(env)
    bnb = balance(env, quiet=True)

    gains = None
    tag = "untrained (anatomy only)"
    p = ROOT / "build" / "gains_ui.npz"
    if p.exists():
        z = np.load(p, allow_pickle=False)
        gains = np.ones(fb.n_types, dtype=np.float32)
        gains[z["codes"]] = np.exp(z["theta"])
        tag = f"trained ({len(z['codes'])} cell types)"

    def _echo(m):
        t = m.get("type")
        if t == "step":
            say(f"  step {m['t']:02d} target={m['target']:<7} "
                f"filled={m['filled']} {m.get('note','')}")
        elif t == "done":
            say(f"DONE {m.get('outcome')} :: {str(m.get('msg') or '')[:250]}")
        elif t not in ("frame", "cursor"):
            say(f"{t.upper()}: {str(m.get('msg') or m)[:250]}")

    async def send(m):
        _echo(m)
        await ws.send_text(json.dumps(m))

    stream = {"on": False, "note": "", "n": 0}

    async def streamer():
        while stream["on"]:
            try:
                raw = await page.screenshot(type="jpeg", quality=48)
                stream["n"] += 1
                await ws.send_text(json.dumps({
                    "type": "frame", "note": stream["note"],
                    "shot": base64.b64encode(raw).decode()}))
            except Exception:
                pass
            await asyncio.sleep(0.07)

    async def shot(note=""):
        stream["note"] = note
        try:
            raw = await page.screenshot(type="jpeg", quality=48)
            await ws.send_text(json.dumps({"type": "frame", "note": note,
                                           "shot": base64.b64encode(raw).decode()}))
        except Exception:
            pass

    await send({"type": "log", "msg": f"gains: {tag}"})
    await send({"type": "log",
                "msg": f"wallet {acct.address[:10]}... {bnb:.6f} BNB on chain {CHAIN_ID}"
                       f" - mode {MODE}, live {'ARMED' if live else 'no (FLY_RH_LIVE=0)'}"})
    if live and bnb < GAS_RESERVE_BNB:
        await send({"type": "log",
                    "msg": f"balance is under the {GAS_RESERVE_BNB} BNB gas reserve"})
    if live and cooldown_left():
        await send({"type": "done", "outcome": "blocked",
                    "msg": f"rate-limit guard: last launch from this wallet was "
                           f"{COOLDOWN_S - cooldown_left()}s ago; wait {cooldown_left()}s"})
        return

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not headful)
        page = await browser.new_page(viewport={"width": 1280, "height": 720})
        page.on("pageerror", lambda e: say(f"  [page.error] {str(e)[:150]}"))

        sent = {"n": 0, "hash": None, "receipt": None, "token": None,
                "asked": []}

        async def on_send(tx):
            """The page asked the wallet to send. Decode it, then refuse or sign."""
            sent["n"] += 1
            method, dec = decode_launch(tx.get("data") or "0x")
            val = tx.get("value") or "0x0"
            val = int(val, 16) if isinstance(val, str) and val.startswith("0x") else int(val)
            info = {"to": tx.get("to"), "value_bnb": val / 1e18, "method": method}
            if dec:
                info.update(name=dec["name"], symbol=dec["symbol"], meta=dec["meta"],
                            tokenVersion=dec["tokenVersion"], salt=dec["salt"],
                            migratorType=dec["migratorType"],
                            dexThresh=dec["dexThresh"], quoteAmt=dec["quoteAmt"])
                try:
                    info["predicted"] = predicted_address(dec)
                except Exception:
                    pass
            sent["asked"].append(info)
            await send({"type": "log",
                        "msg": f"page asked to send #{sent['n']}: {json.dumps(info)[:400]}"})
            to_ok = str(tx.get("to", "")).lower() == PORTAL.lower()
            if not to_ok:
                raise RuntimeError(f"refused: target {tx.get('to')} is not the Flap Portal")
            if not live:
                raise RuntimeError("FLY_RH_LIVE=0 - transaction refused")
            if sent["n"] > 1:
                raise RuntimeError("refused: the page asked for a second transaction")
            loop = asyncio.get_running_loop()

            def note(m):
                say("  [tx] " + m)
                asyncio.run_coroutine_threadsafe(
                    send({"type": "log", "msg": m}), loop)

            try:
                h = await loop.run_in_executor(
                    None, lambda: send_transaction(acct, tx, rpc, CHAIN_ID,
                                                   say=note, wait_receipt=False))
                sent["hash"] = h
                _mark_launch({"hash": h, **info})
                return h
            except Exception as exc:
                await send({"type": "log",
                            "msg": f"TRANSACTION FAILED: {str(exc)[:200]}"})
                raise

        # is_metamask=False: with the flag on, flap.sh freezes a headless
        # renderer about six seconds after load (bisected 2026-09-11)
        await attach(page, acct, rpc, CHAIN_ID, allow_send=live,
                     on_send=on_send, log=lambda m: say("  [wallet] " + m),
                     is_metamask=False)

        await send({"type": "log", "msg": f"loading {URL}"})
        await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        stream["on"] = True
        stream_task = asyncio.create_task(streamer())

        watch = {"on": True, "n": 0}

        async def watcher():
            loop_ = asyncio.get_running_loop()
            while watch["on"]:
                try:
                    raw = await page.screenshot(type="jpeg", quality=45)
                    arr = np.asarray(Image.open(io.BytesIO(raw)).convert("L"),
                                     dtype=np.float32) / 255.0
                    _, _, _, hz, fired = await loop_.run_in_executor(
                        None, step_brain, pilot, arr, 640.0, 300.0, gains,
                        9000 + watch["n"])
                    mm = remap[fired]
                    mm = np.unique(mm[mm >= 0]).astype(np.uint16)
                    watch["n"] += 1
                    await ws.send_text(json.dumps({
                        "type": "watch",
                        "hz": {k: round(v) for k, v in hz.items()},
                        "idx": base64.b64encode(mm.tobytes()).decode()}))
                except Exception:
                    pass
                await asyncio.sleep(0.2)

        watch_task = asyncio.create_task(watcher())
        await page.wait_for_timeout(5000)
        await ensure_dark(page, send)
        await page.wait_for_timeout(1000)
        await shot("create page open")
        await asyncio.sleep(1.0)

        st = await page.evaluate(
            """() => ({connected: !!(window.ethereum && window.ethereum.selectedAddress),
                       addr: window.ethereum && window.ethereum.selectedAddress,
                       chain: window.ethereum && window.ethereum.chainId})""")
        await send({"type": "log", "msg": f"wallet in page: {st}"})
        connected = await connect_wallet(page, send, shot)
        await send({"type": "wallet", "connected": bool(connected),
                    "pubkey": st.get("addr")})
        await asyncio.sleep(1.0)

        img_p = ROOT / coin.get("image", IMAGE)
        if img_p.exists():
            try:
                drop = page.locator("label[for=image], #image").first
                try:
                    await scroll_form(page, "document.querySelector('label[for=image]')"
                                      " || document.getElementById('image')", send, offset=0.3)
                except Exception:
                    pass
                box = await page.evaluate(
                    """() => { const e = document.querySelector('label[for=image]')
                         || document.querySelector('button:has(input#image)');
                       if (!e) return null; const r = e.getBoundingClientRect();
                       return {x:r.x, y:r.y, w:r.width, h:r.height}; }""")
                if box:
                    await glide(page, box["x"] + box["w"] / 2, box["y"] + box["h"] / 2,
                                send, hold=0.5)
                    await shot("choosing the token image")
                inp = page.locator('input#image, input[type="file"]').first
                await inp.wait_for(state="attached", timeout=12000)
                await inp.set_input_files(str(img_p.resolve()), timeout=20000)
                await page.wait_for_timeout(1500)
                await shot("image chosen")
                # flap.sh opens an "adjust image" crop dialog; it has to be
                # confirmed or every later click lands on the dialog
                ok_btn = None
                for _ in range(12):
                    ok_btn = await page.evaluate(
                        """() => { const rx = /use this image|使用|確認|确认/i;
                           const b = [...document.querySelectorAll('button')]
                             .map(b => ({b, r: b.getBoundingClientRect()}))
                             .find(o => rx.test(o.b.textContent||'') && o.r.width > 40);
                           if (!b) return null;
                           return {x: b.r.x, y: b.r.y, w: b.r.width, h: b.r.height,
                                   t: (b.b.textContent||'').trim()}; }""")
                    if ok_btn:
                        break
                    await page.wait_for_timeout(500)
                if ok_btn:
                    await glide(page, ok_btn["x"] + ok_btn["w"] / 2,
                                ok_btn["y"] + ok_btn["h"] / 2, send, hold=0.5)
                    await shot("confirming the crop")
                    await page.mouse.click(ok_btn["x"] + ok_btn["w"] / 2,
                                           ok_btn["y"] + ok_btn["h"] / 2)
                    await page.wait_for_timeout(1500)
                    await send({"type": "log",
                                "msg": f"token image selected: {img_p.name} ('{ok_btn['t']}')"})
                else:
                    await send({"type": "log",
                                "msg": f"token image selected: {img_p.name} (no crop dialog seen)"})
                await shot("image selected")
                await asyncio.sleep(1.0)
            except Exception as e:
                await send({"type": "log", "msg": f"image failed: {str(e)[:110]}"})

        # Put the three text fields in the viewport before the fly gets the
        # mouse. On flap.sh the description sits just below the fold at
        # 1280x720; this is the rig framing the page, the same way it sets the
        # theme, not the rig steering the fly. The mouse starts above the form.
        await scroll_form(page, "document.getElementById('name')", send, offset=0.20)
        await page.wait_for_timeout(600)
        await shot("form in view")

        watch["on"] = False
        try:
            await asyncio.wait_for(watch_task, timeout=3)
        except Exception:
            pass
        await send({"type": "log",
                    "msg": f"fly watched the create page for {watch['n']} brain steps "
                           f"- now taking the mouse"})

        # ---- the generic loop, unchanged from rhlive.py ---------------------
        # the mouse starts above the form, centred on the form column - the
        # same "middle of the form" start rhlive uses, measured rather than
        # assumed, because flap.sh's column is right of the viewport centre
        f0 = await page.evaluate(DOM_JS)
        col = f0.get("desc") or f0.get("name") or {"x": 540, "w": 200}
        top = f0.get("name") or {"y": 160}
        cx, cy = float(col["x"] + col["w"] / 2), float(max(40, top["y"] - 60))
        await page.mouse.move(cx, cy)
        await send({"type": "log", "msg": f"mouse starts at ({cx:.0f},{cy:.0f}), above the form"})
        filled, spikes_total = set(), 0
        loop = asyncio.get_running_loop()

        for t in range(steps):
            raw = await page.screenshot(type="jpeg", quality=60)
            arr = np.asarray(Image.open(io.BytesIO(raw)).convert("L"),
                             dtype=np.float32) / 255.0
            f = await page.evaluate(DOM_JS)
            for k in ("name", "ticker", "desc"):
                if f.get(k, {}).get("filled"):
                    filled.add(k)

            open_f = [(k, v) for k, v in f.items()
                      if k in ("name", "ticker", "desc") and k not in filled]
            if open_f:
                tk, tf = min(open_f, key=lambda kv: np.hypot(
                    cx - (kv[1]["x"] + kv[1]["w"] / 2),
                    cy - (kv[1]["y"] + kv[1]["h"] / 2)))
            elif "launch" in f:
                tk, tf = "launch", f["launch"]
                if tf["y"] < 40 or tf["y"] + tf["h"] > 700:
                    await page.evaluate(SCROLL_JS)
                    await page.wait_for_timeout(700)
                    f = await page.evaluate(DOM_JS)
                    if "launch" not in f:
                        break
                    tf = f["launch"]
            else:
                break

            dx, dy, click, hz, fired = await loop.run_in_executor(
                None, step_brain, pilot, arr, cx, cy, gains, seed + t)
            m = remap[fired]
            m = np.unique(m[m >= 0]).astype(np.uint16)
            spikes_total += int(len(fired))

            cx = float(np.clip(cx + dx, 2, 1278))
            cy = float(np.clip(cy + dy, 2, 718))
            await page.mouse.move(cx, cy)

            hit = click and inside(tf, cx, cy)
            note = ""
            if hit and tk != "launch":
                await page.mouse.click(cx, cy)
                await page.keyboard.type(str(coin[tk]), delay=75)
                filled.add(tk)
                note = f"typed {tk}"

            await send({"type": "step", "t": t, "cx": cx, "cy": cy, "target": tk,
                        "hz": {k: round(v) for k, v in hz.items()},
                        "click": bool(hit), "filled": sorted(filled),
                        "clicks": len(filled), "spikes": spikes_total, "note": note,
                        "create_label": f.get("launch", {}).get("label", ""),
                        "tf": {k: tf[k] for k in ("x", "y", "w", "h")},
                        "shot": base64.b64encode(raw).decode(),
                        "idx": base64.b64encode(m.tobytes()).decode()})
            if hit and tk == "launch":
                break
            await asyncio.sleep(0.05)
        # ---------------------------------------------------------------------

        await finish(ws, page, coin, filled, live, send, shot, sent, acct, rpc)
        watch["on"] = False
        stream["on"] = False
        try:
            await asyncio.wait_for(stream_task, timeout=3)
        except Exception:
            pass
        say(f"streamed {stream['n']} frames")
        await browser.close()


async def complete_form(page, coin, filled, send, shot):
    """The rig fills whatever the fly missed and reports which was which."""
    by_fly = sorted(filled)
    by_rig = []
    before = {}
    for k, sel in SEL.items():
        try:
            before[k] = await page.input_value(sel, timeout=3000)
        except Exception:
            before[k] = "" if k in OPTIONAL else "<unreadable>"
    await send({"type": "log", "msg": f"field values before completion: {before}"})

    for k, sel in SEL.items():
        cur = before.get(k, "")
        want = str(coin.get(k, "") or "")
        if not want or cur == "<unreadable>" or cur.strip() == want.strip():
            continue
        try:
            el = page.locator(sel).first
            await scroll_form(page, f"document.querySelector({sel!r})", send, offset=0.35)
            await page.wait_for_timeout(500)
            box = await el.bounding_box()
            if box:
                await glide(page, box["x"] + box["width"] / 2,
                            box["y"] + box["height"] / 2, send, hold=0.45)
                await page.mouse.click(box["x"] + box["width"] / 2,
                                       box["y"] + box["height"] / 2)
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Delete")
            await asyncio.sleep(0.35)
            await page.keyboard.type(want, delay=105)
            await asyncio.sleep(0.9)
            await shot(f"typed {k}")
        except Exception:
            try:
                await page.fill(sel, want, timeout=4000)
            except Exception:
                if k in OPTIONAL:
                    await send({"type": "log",
                                "msg": f"optional field '{k}' is not on the form"})
                    continue
                raise
        by_rig.append(k)

    after = {}
    for k, sel in SEL.items():
        try:
            after[k] = await page.input_value(sel, timeout=3000)
        except Exception:
            after[k] = "<missing>" if k in OPTIONAL else "<unreadable>"
    await send({"type": "log", "msg": f"FINAL field values: {after}"})
    await send({"type": "fields", "by_fly": by_fly, "by_rig": by_rig})
    await shot("form complete")
    return after


async def finish(ws, page, coin, filled, live, send, shot, sent, acct, rpc):
    fields = await complete_form(page, coin, filled, send, shot)
    await asyncio.sleep(1.2)

    if MODE == "direct":
        await finish_direct(page, fields, live, send, shot, acct, rpc, coin)
        return

    # ---- site mode: the site's own button ---------------------------------
    await page.evaluate(SCROLL_JS)
    await page.wait_for_timeout(700)
    await shot("scrolled to create")
    f = await page.evaluate(DOM_JS)
    c = f.get("launch")
    if not c:
        seen = await page.evaluate(
            """() => [...document.querySelectorAll('button')]
                 .map(b => ({t:(b.textContent||'').trim().slice(0,30), type:b.type,
                             w:Math.round(b.getBoundingClientRect().width),
                             y:Math.round(b.getBoundingClientRect().y + scrollY)}))
                 .filter(o => o.w > 0)""")
        await send({"type": "log", "msg": f"visible buttons: {json.dumps(seen)[:600]}"})
        await send({"type": "done", "outcome": "error",
                    "msg": "create button not found"})
        return
    await send({"type": "log",
                "msg": f"create button '{c['label']}' at ({c['x']},{c['y']}) "
                       f"disabled={c['disabled']}"})
    await glide(page, c["x"] + c["w"] / 2, c["y"] + c["h"] / 2, send,
                steps=30, hold=1.6)
    await shot("fly on the create button")
    await asyncio.sleep(1.2)

    if not live and not PROBE:
        await send({"type": "done", "outcome": "dry",
                    "msg": f"FLY_RH_LIVE=0 - stopped on the '{c['label']}' button. "
                           f"Nothing signed, nothing sent. "
                           f"transaction requests seen: {sent['n']}"})
        return

    await send({"type": "log",
                "msg": ("FLY_RH_LIVE=1 - pressing create" if live else
                        "FLY_FLAP_PROBE=1 - pressing create to see what the page asks;"
                        " any transaction will be refused")})
    await page.mouse.click(c["x"] + c["w"] // 2, c["y"] + c["h"] // 2)
    await page.wait_for_timeout(2500)
    try:
        await page.screenshot(path=str(ROOT / "build" / "flap_after_create.png"))
    except Exception:
        pass

    state = await page.evaluate(
        """() => {
           const t = document.body.innerText;
           const line = (re) => { const m = t.match(re); return m ? m[0] : ''; };
           const bs = [...document.querySelectorAll('button')]
             .map(b => ({t:(b.textContent||'').trim().slice(0,40), d:b.disabled}))
             .filter(o => o.t && o.d !== undefined);
           return {
             url: location.href,
             err: line(/(error|failed|rejected|denied|insufficient|invalid|missing|required).{0,90}/i),
             confirm: /confirm|review|approve|sign|are you sure/i.test(t),
             buttons: bs.slice(0, 14) }; }""")
    await send({"type": "log", "msg": f"after press: {json.dumps(state)[:400]}"})

    # The site uploads the metadata and then asks the wallet directly - the
    # Create button is the whole confirmation (measured: one request, ~7 s
    # after the press). Only if nothing arrives is a confirm dialog looked for,
    # and then by its own visible button, never the header's Create Token.
    for _ in range(10):
        if sent["n"]:
            break
        await page.wait_for_timeout(1000)
    if not sent["n"] and state.get("confirm"):
        btn = await page.evaluate(
            """() => { const rx = /^(confirm|create|launch|approve|continue)$/i;
               const b = [...document.querySelectorAll('[role=dialog] button, button')]
                 .map(b => ({b, r: b.getBoundingClientRect()}))
                 .find(o => rx.test((o.b.textContent||'').trim()) && o.r.width > 60
                            && o.r.y > 70);
               if (!b) return null;
               return {x: b.r.x, y: b.r.y, w: b.r.width, h: b.r.height,
                       t: (b.b.textContent||'').trim()}; }""")
        if btn:
            await send({"type": "log", "msg": f"confirmation step: '{btn['t']}'"})
            await glide(page, btn["x"] + btn["w"] / 2, btn["y"] + btn["h"] / 2,
                        send, hold=0.6)
            await page.mouse.click(btn["x"] + btn["w"] / 2, btn["y"] + btn["h"] / 2)
            await page.wait_for_timeout(2500)

    loop_ = asyncio.get_running_loop()

    def _rpc(method, prms):
        import requests
        return requests.post(rpc, json={"jsonrpc": "2.0", "id": 1,
                                        "method": method, "params": prms},
                             timeout=20).json().get("result")

    waits = 75 if live else 12
    for i in range(waits):
        await page.wait_for_timeout(2000)
        await shot("waiting for the launch" if live else "watching the page")

        if sent["hash"] and not sent["receipt"]:
            try:
                rec = await loop_.run_in_executor(
                    None, _rpc, "eth_getTransactionReceipt", [sent["hash"]])
            except Exception:
                rec = None
            if rec:
                sent["receipt"] = rec
                ok = int(rec.get("status", "0x0"), 16) == 1
                await send({"type": "log", "msg":
                            f"receipt block {int(rec.get('blockNumber','0x0'),16)}"
                            f" status {'SUCCESS' if ok else 'REVERTED'}"})
                sent["token"] = await find_token(rec, loop_, rpc, send)
                if ok and sent["token"]:
                    record_launch(sent["token"], sent["hash"], rec, acct, coin,
                                  sent["asked"][0] if sent["asked"] else {})

        if sent["receipt"]:
            for _ in range(6):
                await page.wait_for_timeout(1500)
                await shot("launched")
                if "/bnb/0x" in (page.url or ""):
                    break
            if sent["token"] and "/bnb/0x" not in (page.url or ""):
                await show_coin_page(page, sent["token"], send, shot)
            break

        if not live and sent["n"]:
            break                                   # the probe has its answer
        if not sent["n"] and i % 4 == 0:
            msg = await page.evaluate(
                """() => { const m = document.body.innerText.match(
                     /(error|failed|rejected|denied|insufficient|pending|confirming|success|uploading).{0,80}/i);
                   return m ? m[0] : ''; }""")
            if msg:
                await send({"type": "log", "msg": f"page: {msg[:120]}"})
    try:
        await page.screenshot(path=str(ROOT / "build" / "flap_end.png"))
    except Exception:
        pass
    outcome = ("minted" if sent["hash"] else
               "probed" if (not live and sent["n"]) else "clicked")
    await send({"type": "done", "outcome": outcome, "result": page.url,
                "asked": sent["asked"],
                "msg": f"transaction requests: {sent['n']}"
                       + (f", refused (FLY_RH_LIVE=0)" if sent["n"] and not live else "")})


async def finish_direct(page, fields, live, send, shot, acct, rpc, coin):
    """
    The fallback: the form on screen is the source of truth, the rig does the
    rest itself - upload, salt, one Portal call. Simulated with eth_call
    first, and only broadcast with FLY_RH_LIVE=1.
    """
    loop_ = asyncio.get_running_loop()
    name = (fields.get("name") or "").strip()
    symbol = (fields.get("ticker") or "").strip()
    desc = (fields.get("desc") or "").strip()
    twitter = (fields.get("x") or "").strip() or None
    website = (coin.get("website") or "").strip() or None
    coin_image = coin.get("image", IMAGE)
    if not name or not symbol:
        await send({"type": "done", "outcome": "error",
                    "msg": "direct mode needs name and symbol on the form"})
        return

    await send({"type": "log", "msg": "uploading metadata to funcs.flap.sh ..."})
    try:
        cid = await loop_.run_in_executor(
            None, lambda: upload_meta(str(ROOT / coin_image), desc, twitter=twitter, website=website))
    except Exception as e:
        await send({"type": "done", "outcome": "error",
                    "msg": f"metadata upload failed: {str(e)[:200]}"})
        return
    await send({"type": "log", "msg": f"metadata CID {cid}"})

    if TOKEN_KIND == "tax":
        salt, addr, n, secs = await loop_.run_in_executor(
            None, lambda: find_salt(SUFFIX_TAX, flapportal.TOKEN_IMPL_TAXED_V3))
        params = standard_token_params(name, symbol, cid, salt, acct.address)
        params.update(tokenVersion=TOKEN_VERSION["TOKEN_TAXED_V3"],
                      buyTaxRate=int(os.environ.get("FLY_FLAP_BUY_BPS", "100")),
                      sellTaxRate=int(os.environ.get("FLY_FLAP_SELL_BPS", "100")),
                      taxDuration=365 * 86400, antiFarmerDuration=3600,
                      mktBps=10000)
        data = encode_new_token_v6(params)
        method = "newTokenV6 (TOKEN_TAXED_V3)"
    else:
        salt, addr, n, secs = await loop_.run_in_executor(
            None, lambda: find_salt(SUFFIX_STANDARD, flapportal.TOKEN_IMPL_V3))
        # the only non-tax shape the BNB Portal accepts today (probed
        # 2026-09-11, see docs/flap.md): V7, TOKEN_V3_PERMIT, PCS Infinity CL
        # migrator, one DIVIDEND slot paying the quote token to holders above
        # minimumShareBalance - which must be at least 10,000 tokens
        params = standard_token_v7_params(name, symbol, cid, salt, acct.address)
        params["feeConfigs"] = [(FEE_TYPE["DIVIDEND"], 10000, ZERO, ZERO, MIN_SHARE_WEI)] + \
                               [(FEE_TYPE["NONE"], 0, ZERO, ZERO, 0)] * 3
        data = encode_new_token_v7(params)
        method = "newTokenV7 (TOKEN_V3_PERMIT, dividend to holders)"
    await send({"type": "log",
                "msg": f"salt found in {n:,} iterations ({secs:.2f}s) -> {addr}"})
    await send({"type": "log", "msg": f"{method}, {len(data)//2 - 1} bytes of calldata"})

    tx = {"from": acct.address, "to": PORTAL, "value": 0, "data": data}
    res = await loop_.run_in_executor(None, lambda: flapportal.simulate(rpc, tx))
    if res["ok"]:
        await send({"type": "log",
                    "msg": f"eth_call ok: Portal would create {res['token']}"
                           f"{'' if res['token'].lower() == addr.lower() else ' (ADDRESS MISMATCH)'}"})
    else:
        await send({"type": "done", "outcome": "error",
                    "msg": f"Portal rejects the call: {res['error']} - nothing sent"})
        return

    if not live:
        await send({"type": "done", "outcome": "dry",
                    "msg": f"FLY_RH_LIVE=0 - simulated only. {method} would create "
                           f"{addr} with meta {cid}. Nothing signed, nothing sent."})
        return

    def note(m):
        say("  [tx] " + m)
        asyncio.run_coroutine_threadsafe(send({"type": "log", "msg": m}), loop_)

    await send({"type": "log", "msg": "FLY_RH_LIVE=1 - signing and broadcasting"})
    try:
        h = await loop_.run_in_executor(
            None, lambda: send_transaction(acct, tx, rpc, CHAIN_ID, say=note,
                                           wait_receipt=True))
    except Exception as e:
        await send({"type": "done", "outcome": "error",
                    "msg": f"broadcast failed: {str(e)[:200]}"})
        return
    _mark_launch({"hash": h, "predicted": addr, "meta": cid, "method": method})
    await show_coin_page(page, addr, send, shot)
    await send({"type": "done", "outcome": "minted", "result": TOKEN_PAGE.format(addr=addr),
                "msg": f"tx {h}"})


async def find_token(receipt, loop_, rpc, send=None):
    """The token is the log address that answers name() and symbol()."""
    try:
        for addr in dict.fromkeys(lg["address"] for lg in receipt.get("logs", [])):
            nm, sy = await loop_.run_in_executor(
                None, lambda a=addr: flapportal.token_name_symbol(rpc, a))
            if nm or sy:
                if send:
                    await send({"type": "log", "msg": f"token {nm} ({sy}) at {addr}"})
                    await send({"type": "log", "msg": TOKEN_PAGE.format(addr=addr)})
                return addr
    except Exception:
        pass
    return None


async def show_coin_page(page, addr, send=None, shot=None):
    """End on the coin. flap.sh/bnb/<address> is the token's page."""
    url = TOKEN_PAGE.format(addr=addr)
    try:
        if send:
            await send({"type": "log", "msg": f"opening the coin page: {url}"})
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(3500)
        await ensure_dark(page)
        if shot:
            await shot("the coin")
        height = await page.evaluate("document.body.scrollHeight")
        vh = await page.evaluate("innerHeight")
        for frac in (0.30, 0.60, 0.95):
            await smooth_scroll(page, max(0, (height - vh) * frac), send, ms=1500)
            await page.wait_for_timeout(900)
            if shot:
                await shot("the coin")
        await smooth_scroll(page, 0, send, ms=1400)
        await page.wait_for_timeout(1200)
        if shot:
            await shot("the coin")
    except Exception as exc:
        if send:
            await send({"type": "log",
                        "msg": f"coin page did not open: {str(exc)[:120]}"})


COIN_FILE = ROOT / "launch" / "token.json"


def pick_coin(msg):
    """
    Which token the run is for.

    Test runs use whatever the viewer form says, with a timestamp appended to
    the description so every rehearsal has a different CID (the Portal refuses
    a reused one). The real launch uses launch/token.json, untouched, when
    FLY_FLAP_COIN=launch is set in .env - the file is gitignored and is not
    read at all otherwise, so no rehearsal can upload the real text or image.
    """
    if _E.get("FLY_FLAP_COIN") == "launch":
        c = json.loads(COIN_FILE.read_text(encoding="utf-8"))
        return {"name": c["name"], "ticker": c["ticker"], "desc": c["description"],
                "x": c.get("x") or "", "website": c.get("website") or "",
                "image": c.get("image") or IMAGE, "_launch": True}
    stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    return {"name": msg.get("name") or "test",
            "ticker": msg.get("ticker") or "TEST",
            "desc": (msg.get("desc") or "launched by a fruit fly connectome")
                    + f" · {stamp}",
            "x": msg.get("x") or X_HANDLE, "website": "", "image": IMAGE}


@app.websocket("/run")
async def run(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            if msg.get("action") != "start" or STATE["running"]:
                continue
            if not browser_allowed():
                await ws.send_text(json.dumps({
                    "type": "done", "outcome": "blocked",
                    "msg": "FLY_ALLOW_BROWSER is not 1"}))
                continue
            STATE["running"] = True
            coin = pick_coin(msg)
            say(f"coin: {coin['name']} ({coin['ticker']}) from "
                f"{'launch/token.json' if coin.get('_launch') else 'the viewer form'}")
            try:
                await run_episode(ws, coin, int(msg.get("steps", 18)),
                                  int(msg.get("seed", 350)),
                                  bool(msg.get("headful")))
            except Exception as e:
                import traceback
                say("RUN FAILED:")
                traceback.print_exc()
                await ws.send_text(json.dumps({"type": "done", "outcome": "error",
                                               "msg": repr(e)}))
            finally:
                STATE["running"] = False
    except (WebSocketDisconnect, RuntimeError):
        # RuntimeError: the viewer closed the socket while a run was ending
        STATE["running"] = False


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4652)
    a = ap.parse_args()
    boot()
    print(f"\n  BNB Chain / flap.sh rig ({MODE}) - open http://localhost:{a.port}\n")
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")
