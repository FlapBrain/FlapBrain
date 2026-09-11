"""
Put the local roamer on the public internet and tell the site where it is.

Runs a Cloudflare quick tunnel to roam.py's port, parses the tunnel address
from cloudflared's own output, writes it into site/web/live.json (keeping the
launch block the page also reads), commits and pushes - only when the
address actually changes. If the tunnel dies it is started again and the
new address is published. roam.py itself is left untouched and never gets a
token; its own tunnel logic (which mistakes cloudflared's API host for the
tunnel on current cloudflared versions) is simply not relied on.

  py tools/publish_live.py                      tunnel :4660, publish, keep going
  py tools/publish_live.py --repo <clone>       commit in a separate clone
  py tools/publish_live.py --offline            publish "no stream" and exit

cloudflared: ~/.claude/tools/cloudflared/cloudflared.exe, or on PATH.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE = Path("site/web/live.json")
CFD = (Path(os.path.expanduser("~/.claude/tools/cloudflared/cloudflared.exe"))
       if os.name == "nt" else Path(os.path.expanduser("~/.claude/tools/cloudflared/cloudflared")))
TUNNEL_RE = re.compile(r"https://([a-z0-9-]+)\.trycloudflare\.com")


def cloudflared():
    if CFD.exists():
        return str(CFD)
    p = shutil.which("cloudflared")
    if not p:
        sys.exit("cloudflared not found - put it at ~/.claude/tools/cloudflared/ or on PATH")
    return p


def write_and_push(repo, stream):
    p = repo / LIVE
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    if data.get("stream") == stream:
        return False
    data["stream"] = stream
    data["at"] = int(time.time()) if stream else 0
    data.setdefault("launch", {"state": "not_launched", "banner": "", "url": ""})
    text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
    p.write_text(text, encoding="utf-8")
    if repo != ROOT:
        (ROOT / LIVE).write_text(text, encoding="utf-8")
    msg = f"live: stream {'is ' + stream if stream else 'offline'}"
    for cmd in (["git", "add", str(LIVE)],
                ["git", "commit", "-q", "-m", msg],
                ["git", "push", "-q", "origin", "main"]):
        r = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
        if r.returncode != 0 and "nothing to commit" not in r.stdout + r.stderr:
            print("git failed:", " ".join(cmd), (r.stderr or r.stdout)[:200], flush=True)
            return False
    print(time.strftime("%H:%M:%S"), msg, flush=True)
    return True


def run_tunnel(port, found):
    """Start cloudflared; call found(url) with the real tunnel host."""
    proc = subprocess.Popen(
        [cloudflared(), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", bufsize=1)

    def watch():
        for line in proc.stdout:
            m = TUNNEL_RE.search(line)
            if m and m.group(1) != "api":       # api.trycloudflare.com is not a tunnel
                found("https://" + m.group(1) + ".trycloudflare.com")
    threading.Thread(target=watch, daemon=True).start()
    return proc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4660)
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    repo = Path(a.repo).resolve()
    if a.offline:
        write_and_push(repo, None)
        return

    state = {"url": None}

    def found(url):
        if url != state["url"]:
            state["url"] = url
            print(time.strftime("%H:%M:%S"), "tunnel:", url, flush=True)
            write_and_push(repo, url)

    proc = run_tunnel(a.port, found)
    try:
        while True:
            time.sleep(5)
            if proc.poll() is not None:
                print(time.strftime("%H:%M:%S"), "tunnel exited, restarting", flush=True)
                state["url"] = None
                time.sleep(5)
                proc = run_tunnel(a.port, found)
    except KeyboardInterrupt:
        proc.terminate()
        write_and_push(repo, None)


if __name__ == "__main__":
    main()
