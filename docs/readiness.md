# Readiness — BNB Chain / flap.sh launch

Checked 2026-09-11 on the launch machine. `FLY_RH_LIVE=0` throughout; nothing
was signed, broadcast or funded. Status per item: **通过** / **未通过** /
**需要你决定**.

## 一、后端：发币流程彩排

**1. 连续干跑 — 通过（对标作者水平 — 未通过）**

Eight dry runs against the real flap.sh create page. Runs 1–3 hit rig bugs
that were fixed as they appeared (crop dialog, inner-container scrolling, the
Create button has no `type`); runs 4–8 are the rehearsal proper and all
reach the same endpoint.

| run | seconds | filled by fly | filled by rig | outcome | tx requests | stuck |
|---|---|---|---|---|---|---|
| 1 | 79.1 | 0/3 | 3/3 | error (create button not found) | 0 | no |
| 2 | 52.7 | 0/3 | 3/3 | error (create button not found) | 0 | no |
| 3 | 52.7 | 0/3 | 3/3 | error (create button not found) | 0 | no |
| 4 | 95.3 | 0/3 | 3/3 | probed | 1 | no |
| 5 | 64.5 | 0/3 | 3/3 | probed | 1 | no |
| 6 | 67.1 | 0/3 | 3/3 | probed | 1 | no |
| 7 | 70.9 | 0/3 | 3/3 | probed | 1 | no |
| 8 | 64.3 | 0/3 | 3/3 | probed | 1 | no |

The fly filled **0 of 3** fields in every run; the upstream author reports
2 of 3 on pons in dark mode. What was measured: the click signal (DNp09 ≥
330 Hz with low forward drive) fired on 6–8 of 18 steps per run, but the
cursor never entered a field — it drifts left and down from wherever it
starts (x 240–757, y 111–527 across runs) and the flap.sh fields are
227×42 px, right of centre. Rig-side framing that was tried, all of it
disclosed in the README: scroll the form into view, start the mouse above
the form centred on its column. Not tried, because they are the fly's, not
the rig's: any gain, threshold or step count. **需要你决定** whether to allow
more than 18 steps (a rig parameter the viewer sends; the author used 18).

**2. 终点一致 — 通过.** Runs 4–8, decoded from the page's own
`eth_sendTransaction`:

| field | every run |
|---|---|
| `to` | `0xe2ce6ab80874fa9fa2aae65d277dd6b8e65c9de0` = the Flap Portal |
| `value` | 0 BNB (creation fee is zero; no initial buy) |
| calldata | **`newTokenV7`**, `tokenVersion` 7 (TOKEN_V3_PERMIT), migrator 3 (PCS Infinity CL), dexThresh 1 |
| `name` / `symbol` | `test` / `TEST`, as sent from the viewer |
| `meta` | a fresh IPFS CID each run (the description carries a timestamp) |
| predicted address | ends in `8888`, from the salt the site chose |
| log line | `page asked to send #1: {...}` then `transaction requests: 1, refused (FLY_RH_LIVE=0)` |

Note: the site calls `newTokenV7`, not `newTokenV6`. That is correct — on
BNB mainnet `newTokenV6` with a standard token reverts `FeatureDisabled()`
(docs/flap.md §5a). The rig decodes both and checks the Portal address on
either.

**3. 回退路线 — 通过.** `funcs.flap.sh/api/upload` with the test image and a
timestamped test description returned CID
`bafkreihl6q5a7rtfwhusnfcv5qdfllxvo3ffc2a3jy3sr4drufpyqibjkm` in 4.1 s;
`flapsalt.py` found a salt in 0.22 s (address `…e5d78888`); `flapportal.py`
encoded `newTokenV7` (1,540 bytes), decoded it back, and `eth_call` on the
Portal returned the same address. The tax-token `newTokenV6` shape was also
encoded, decoded and its address predicted (`…6a377777`). Nothing sent.

**4. voice.py / xpost.py — 通过.** `voice.py --once --dry` with the stub
model, reading `/state` from the local roamer and BNB Chain, wrote:
*"Day 1. There is no coin yet. The narrator says I am rehearsing a form on a
page called flap.sh… 40,255 of my 165,122 neurons fired this second."*
`xpost.py --check`: `enabled False`, no X keys set. Unit tests: 57 pass, 1
pre-existing failure (`test_xpost.py::test_cap_reads_env_default` expects
the cap to be 12 when unset; `.env.example` sets it to 8 — upstream
inconsistency, not touched).

## 二、录制

**5. record.py — 通过.** `py record.py --port 4652 --dry` recorded one full
dry run: `build/recordings/flybrain-20260911-163741.mp4` (H.264, **1600×900,
25 fps, 80.4 s**, 17.3 MB) plus the `.webm` (8.9 MB). Frames checked: the
flap.sh page with the fly-shaped cursor, the neuron scatter at measured soma
coordinates, the DNa02/DNa01/MDN/DNp09 bars and the log lines `by FLY: none
· by rig: name, ticker, desc` and `page asked to send #1` are all legible.
Recordings are gitignored (`build/`, `*.mp4`, `*.webm`).

**6. 演示模式 — 通过.** `demo.py` replays a recorded run into the same
`web/live.html`, with no brain, no browser and no site. Start:

```bash
py demo.py                                    # replays build/demo/dryrun.json on :4653
py demo.py --take build/demo/dryrun5.json --loop --speed 1
```

then open http://localhost:4653 and press START. Recordings are made with
`py tools/drive.py 4652 "description" --save <label>` while `flaplive.py`
runs; eight are in `build/demo/` (dryrun1–8.json, ~35–50 MB each, gitignored).

**7. 1920×1080 — 通过.** Checked in a 1920×1080 viewport: dark ground
(`rgb(6,7,10)`), no page scroll (document height 1080), the log at 16 px,
neuron rates at 17 px, telemetry values at 28 px (a `@media (min-width:1800px)`
block added to live.html), the right-hand readouts and the log fully inside
the frame.

## 三、公开直播站

**8. 已部署 — 前端 通过，漫游服务 需要你决定.** The front end is live on
your Vercel account (project `flybrain`, team `poplamarks-projects`):
**https://flybrain-bsc.vercel.app** (also
`flybrain-poplamarks-projects.vercel.app`). `/api/state` answers from BNB
Chain (`launched: false`), `live.json` is served, and Vercel Authentication
was switched off on the project so the page is public. Redeploy with
`vercel --cwd site --prod` from this machine; `site/.vercel/` holds the link
and is gitignored.

`flybrain.online` and `flybrain.vercel.app` are **the upstream author's**
deployments and show the Robinhood token — not ours to change.

The roaming picture is streamed **from this machine** through a Cloudflare
quick tunnel (verified live: the page's socket connects, 2 fps, the fly on
Wikimedia Commons). Two processes have to stay up for it:

```bash
py roam.py                                  # the fly, :4660
py tools/publish_live.py                    # tunnel :4660 -> *.trycloudflare.com,
                                            # writes site/web/live.json, pushes
```

`publish_live.py` runs cloudflared itself (from `~/.claude/tools/cloudflared/`)
and pushes the address only when it changes; on a restart the address
changes and it pushes again. Stop it with Ctrl-C and it publishes "offline".
roam.py's own tunnel code is not used: on current cloudflared it mistakes
`api.trycloudflare.com` for the tunnel, and it would push to the upstream
repo. For a picture that survives this PC being off, `site/server/` and the
Dockerfile are ready for Railway or any container host — **需要你决定**.

**9. 未发射状态 — 通过（本地）.** With `FLY_TOKEN` unset the state service
answers `launched: false, token: null` and the page shows "not launched yet"
for the contract, `BNB` / `0 %` / `1,000,000,000 at launch`, a working
block number, and no error. Checked at desktop and 375 px mobile widths, no
horizontal overflow.

**10. 发射中横幅 — 通过（本地，未打开）.** `site/web/live.json` →
`launch.state`: `not_launched` (hidden), `launching` (sticky yellow banner
"THE FLY IS LAUNCHING ITS TOKEN — watch it live" with a link to
`launch.url`), `launched` (quiet green line). Verified on both states;
committed as `not_launched` with `url` empty for you to fill.

**11. CC-BY 与"什么不是真的" — 通过.** Both kept in `site/web/index.html`,
`README.md` and `NOTICE`; the "not real" list rewritten for this venue and
this port's measured numbers.

## 四、钱包与参数

**12. 发射钱包 — 通过（需要你决定是否再换一个）.** `py bscwallet.py new`
created `0xa972c0F0778afA6C35b35c445b3754Beca2Eb672` (chain id 56). The
secret went straight into `.env` (`FLY_BSC_SECRET`) and was never printed;
this file and the terminal only ever showed the address. It has never signed
anything for the network — every rehearsal ended in a refused request or an
`eth_call` — and holds 0 BNB. If you want the launch to come from a wallet
that has not even been used for dry runs, delete the `FLY_BSC_SECRET=` line
and run `py bscwallet.py new` again (the script refuses to overwrite).
Unrelated but noted: a separate session flagged the **Robinhood** wallet
(`FLY_RH_SECRET`) as exposed in a transcript; it is not used here — do not
fund it.

**13. 转入金额 — 通过.** 0.01 BNB. Creation fee 0 (confirmed by `eth_call`),
gas 2,096,412 units × 0.05 gwei = 0.000105 BNB, ×3 = 0.00032 BNB; at a 1 gwei
spike ×3 = 0.0063 BNB; no initial buy. Details in the runbook §1.

**14. 正式代币参数 — 通过（待你填）.** `launch/token.example.json` is
committed; `launch/token.json` and `launch/token.png` are gitignored
placeholders (currently the test text and the test image). They are read
only when `FLY_FLAP_COIN=launch` is in `.env`, so no rehearsal can upload
them. **需要你填**: name, ticker, description, image, and `x` (your handle
without `@`) — `FLY_FLAP_X` is empty by default and nothing else is typed
into that field.

## 五、发射日 runbook

**15. docs/launch-runbook.md — 通过.** Every command in it ran today in dry
mode: `bscwallet.py show`, `bscdryrun.py`, `flapsalt.py`, `flaplive.py`
(site mode, dry and probe), `tools/drive.py`, `record.py --port 4652 --dry`,
`demo.py`, `voice.py --once --dry`, `xpost.py --check`, `tools/site_dev.py`.
The direct-mode fallback was exercised piecewise (upload, salt, encode,
simulate) — item 3 — not as a full `FLY_FLAP_MODE=direct` episode.

**16. 本清单 — 通过.**

## 六、GitHub

**17. .gitignore / git status — 通过.** Ignored: `.env`, `.env.*`, `data/`,
`build/` (recordings, demo takes, graph), `.venv/`, `*.mp4`, `*.webm`,
`*.log`, `launch/token.json`, `launch/*.png|jpg`, `__pycache__/`. The push
script greps the tree for 64-hex secrets and for `FLY_*_SECRET=` before
committing; the commit list and the file list are in the final report.

**18. README — 通过.** Rewritten for the BSC / flap.sh fork; keeps the
attribution to fruitflydev/flycoinrh (MIT), the CC-BY credit (and `NOTICE`
untouched), and the "what is NOT real" section with this port's numbers.

**19. Commits / push — 通过** (four commits; see the final report for the
list and the URL `https://github.com/FlapBrain/flycoinrh`).

## Open decisions, in one place

1. Deploy the site under your Vercel account now, and where to host the
   roamer (Railway needs your account).
2. Your X handle for `launch/token.json` and `FLY_FLAP_X`.
3. Keep the BSC wallet made today or rotate it before funding.
4. Allow the fly more than 18 steps, or accept 0/3 as the honest number.
5. Your own BNB Chain RPC for `FLY_BSC_RPC` — the public Binance node is
   still the fallback in `.env`.
