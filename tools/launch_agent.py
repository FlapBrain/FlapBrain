"""
The launch agent: makes the /admin "launch" button work from this machine.

The web page cannot run the rig - the brain, the browser and the key are
here. So the button only writes a command into live.json, and this agent,
running on the launch PC, polls for it through the admin API and does the
work:

  rehearse   a dry run: FLY_RH_LIVE must be 0. Starts flaplive.py, records
             it with record.py, reports steps and the refused transaction.
  launch     the real thing: FLY_RH_LIVE must be 1, FLY_FLAP_COIN must be
             "launch", the wallet must hold gas. Same flow; on a mined
             receipt it writes the contract, tx and block back to live.json,
             flips the banner to "launched", and sets FLY_RH_LIVE back to 0.

The agent refuses and reports the reason if any check fails. It never edits
FLY_RH_LIVE in either direction - a person does that, by hand, in .env.

  py tools/launch_agent.py            poll every 5 s, forever
  py tools/launch_agent.py --once     handle one pending command and exit

Needs site/.admin-token (the same password /admin uses).
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
SITE = "https://www.flapbrain.com"
TOKEN_FILE = ROOT / "site" / ".admin-token"
LOG_DIR = ROOT / "build" / "agent"
PORT = 4652

sys.path.insert(0, str(ROOT))
from envcfg import load_env  # noqa: E402


def say(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def api(action, **kw):
    tok = TOKEN_FILE.read_text(encoding="utf-8").strip()
    r = requests.post(f"{SITE}/api/admin", json={"action": action, **kw},
                      headers={"x-admin-token": tok}, timeout=30)
    return r.json()


def report(**launch):
    """Write agent status (and anything else) into live.json - one commit."""
    try:
        j = api("save", patch={"launch": launch}, note="agent")
        if not j.get("ok"):
            say("report failed:", j.get("error"))
    except Exception as e:
        say("report failed:", e)


def balance_bnb(env):
    from bscwallet import account, rpc_url
    acct = account(env)
    r = requests.post(rpc_url(env), json={"jsonrpc": "2.0", "id": 1, "method": "eth_getBalance",
                                          "params": [acct.address, "latest"]}, timeout=20).json()
    return int(r.get("result", "0x0"), 16) / 1e18, acct.address


def set_live(value):
    p = ROOT / ".env"
    lines = p.read_text(encoding="utf-8").splitlines()
    out = [f"FLY_RH_LIVE={value}" if l.strip().startswith("FLY_RH_LIVE=") else l for l in lines]
    p.write_text("\n".join(out) + "\n", encoding="utf-8")


def preflight(cmd):
    env = load_env()
    live = env.get("FLY_RH_LIVE", "0") == "1"
    if cmd == "launch":
        if not live:
            return "拒绝：FLY_RH_LIVE=0，未武装。在 .env 里改成 1 再按。"
        if env.get("FLY_FLAP_COIN") != "launch":
            return "拒绝：.env 里没有 FLY_FLAP_COIN=launch，会用测试参数。"
        bnb, addr = balance_bnb(env)
        if 0 < bnb < 0.002:
            return f"拒绝：钱包 {addr[:6]}…{addr[-4:]} 只有 {bnb:.5f} BNB，不够 gas，先转 0.01 BNB。"
        if bnb == 0:
            # nothing can be spent from an empty wallet: let the path run all
            # the way to the node, which will refuse the broadcast
            report(agent=f"警告：钱包 {addr[:6]}…{addr[-4:]} 是 0 BNB。会签名并尝试广播，节点会以 insufficient funds 拒绝——只能验证路径，不会创建代币。")
    else:
        if live:
            return "拒绝：彩排要求 FLY_RH_LIVE=0，现在是 1。"
    return None


RIG_LOG = LOG_DIR / "flaplive.log"


def rig_status():
    # /status asks the chain for the balance and the rig is single-threaded,
    # so while a run is on it can take several seconds to answer
    try:
        return requests.get(f"http://127.0.0.1:{PORT}/status", timeout=20).json()
    except Exception:
        return None


def kill_rig():
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and "
                    "$_.CommandLine -like '*flaplive.py*' } | ForEach-Object { Stop-Process -Id "
                    "$_.ProcessId -Force -ErrorAction SilentlyContinue }"], capture_output=True)


def ensure_rig():
    """
    flaplive.py on :4652 - started here if nobody has, and left running
    afterwards so it can be watched (and driven) at http://localhost:4652.
    A rig started before .env changed (mode, tax, coin, the LIVE switch) is
    stale - it read .env once at import - so it is replaced, but only when
    it is idle.
    """
    st = rig_status()
    if st:
        env = load_env()
        want = {"live": env.get("FLY_RH_LIVE", "0") == "1",
                "mode": env.get("FLY_FLAP_MODE", "site"),
                "token_kind": env.get("FLY_FLAP_TOKEN", "std"),
                "coin": "launch" if env.get("FLY_FLAP_COIN") == "launch" else "test"}
        stale = any(st.get(k) != v for k, v in want.items())
        if not stale:
            say("rig already up on :4652, reusing it")
            return True
        for _ in range(100):
            if not (rig_status() or {}).get("running"):
                break
            time.sleep(6)
        say("rig is stale (.env changed) - restarting it")
        kill_rig()
        time.sleep(3)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    say(f"starting flaplive.py -> {RIG_LOG.name}")
    fh = open(RIG_LOG, "a", encoding="utf-8")
    subprocess.Popen([PY, "-u", "flaplive.py", "--port", str(PORT)],
                     cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT)
    for _ in range(90):
        if rig_status():
            return True
        time.sleep(2)
    return False


def run_episode(cmd):
    if not ensure_rig():
        report(agent="失败：flaplive.py 没有启动（看 build/agent/flaplive.log）", command="")
        return
    # one fly, one run: if someone pressed START at localhost:4652, wait
    for _ in range(100):
        st = rig_status() or {}
        if not st.get("running"):
            break
        report(agent="rig 上已有一次运行在进行（有人在 localhost:4652 按了 START），等它结束…")
        time.sleep(6)
    log = RIG_LOG
    mark = len(log.read_text(encoding="utf-8", errors="replace")) if log.exists() else 0
    report(state="launching" if cmd == "launch" else "not_launched",
           agent=("发射中：大脑已加载，开始录像并按 START" if cmd == "launch"
                  else "彩排中：大脑已加载，开始录像并按 START"), step="", command="")
    rec = subprocess.Popen([PY, "-u", "record.py", "--port", str(PORT), "--timeout", "420"]
                           + (["--dry"] if cmd != "launch" else []),
                           cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    seen, done = set(), {}
    t0 = time.time()
    try:
        while rec.poll() is None and time.time() - t0 < 480:
            time.sleep(3)
            txt = log.read_text(encoding="utf-8", errors="replace")[mark:]
            for n in (1, 6, 12, 18):
                m = re.search(rf"step {n-1:02d} ", txt)
                if m and n not in seen:
                    seen.add(n)
                    report(step=str(n), agent=f"果蝇在页面上，第 {n}/18 步")
            if "page asked to send #1" in txt and "asked" not in seen:
                seen.add("asked"); report(agent="网站发出了那一笔交易请求")
            m = re.search(r"broadcast (0x[0-9a-fA-F]{64})", txt)
            if m and "tx" not in done:
                done["tx"] = m.group(1); report(tx=done["tx"], agent="已签名并广播，等待回执")
            m = re.search(r"receipt block (\d+) status (SUCCESS|REVERTED)", txt)
            if m and "block" not in done:
                done["block"] = m.group(1); done["status"] = m.group(2)
            m = re.search(r"token .* at (0x[0-9a-fA-F]{40})", txt)
            if m and "contract" not in done:
                done["contract"] = m.group(1)
            if "DONE" in txt and "finish" not in seen:
                seen.add("finish"); break
        # record.py still has to finalise the webm and transcode the mp4;
        # give it as long as it needs rather than tearing anything down
        try:
            rec.wait(timeout=900)
        except subprocess.TimeoutExpired:
            say("record.py is still transcoding; leaving it")
        txt = log.read_text(encoding="utf-8", errors="replace")[mark:]
        outcome = re.search(r"DONE (\w+)", txt)
        outcome = outcome.group(1) if outcome else "unknown"
        if cmd == "launch" and done.get("contract") and done.get("status") == "SUCCESS":
            report(state="launched", contract=done["contract"], block=done.get("block", ""),
                   tx=done.get("tx", ""), url=f"https://flap.sh/bnb/{done['contract']}",
                   token_page=f"https://flap.sh/bnb/{done['contract']}", step="",
                   agent=f"已发射。结果 {outcome}。FLY_RH_LIVE 保持为 1（按你的要求不自动关）。")
        elif cmd == "launch":
            report(agent=f"发射未完成：{outcome}"
                         + (f"，tx {done.get('tx')}" if done.get("tx") else "")
                         + "。FLY_RH_LIVE 仍为 1，看 build/agent 日志。", step="")
        else:
            asked = "page asked to send #1" in txt
            report(state="not_launched", step="",
                   agent=f"彩排结束：{outcome}" + ("，网站发出了 1 笔交易请求并被拒签。" if asked else "。")
                         + " 录像在 build/recordings/。rig 仍在 localhost:4652 运行。")
    except Exception as e:
        say("episode error:", e)
        report(agent=f"出错：{str(e)[:120]}（看 build/agent/flaplive.log）", step="")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--every", type=int, default=5)
    a = ap.parse_args()
    say("launch agent up; watching /admin for a command")
    report(agent="待命：本机代理在线，等指令。" if not a.once else "待命")
    while True:
        try:
            j = api("get")
            cmd = ((j.get("live") or {}).get("launch") or {}).get("command") or ""
            if cmd in ("launch", "rehearse"):
                say("command:", cmd)
                why = preflight(cmd)
                if why:
                    say(why); report(command="", agent=why)
                else:
                    report(command="", agent=("收到发射指令，预检通过，启动中…" if cmd == "launch"
                                              else "收到彩排指令，启动中…"))
                    run_episode(cmd)
                if a.once:
                    return
            elif cmd:
                report(command="", agent=f"未知指令 {cmd!r}，已清除")
        except Exception as e:
            say("poll error:", str(e)[:120])
        if a.once:
            return
        time.sleep(a.every)


if __name__ == "__main__":
    main()
