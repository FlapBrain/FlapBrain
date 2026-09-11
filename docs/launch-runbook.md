# Launch-day runbook — BNB Chain / flap.sh

Every command below was executed on 2026-09-11 in dry mode (`FLY_RH_LIVE=0`),
on this machine, against the real flap.sh create page and the real BNB Chain
Portal. On launch day you do two things by hand: **transfer BNB to the
wallet** and **set `FLY_RH_LIVE=1`**. Everything else is a command from this
file.

All commands run from the project directory with the venv's Python:

```bash
cd D:\project\fly\flycoinrh-main\flycoinrh-main
.venv\Scripts\python.exe --version        # 3.12.10
```

`py` below means `.venv\Scripts\python.exe`.

---

## 0. The day before

| step | command | expect |
|---|---|---|
| 0.1 | `py bscwallet.py show` | your launch wallet's address, chain id **56 ok**, balance 0, `live no (FLY_RH_LIVE=0)` |
| 0.2 | `py bscdryrun.py` | `chain id 56 ok`, `recovered from 0x… MATCHES`, `eth_call ok - Portal would return token 0x…8888`, `creation fee none required`, `Nothing was broadcast.` |
| 0.3 | `py flapsalt.py --runs 3` | three salts, each address ending `8888`, ~0.5 s each |
| 0.4 | `py flaplive.py --port 4652` then, in another shell, `py tools/drive.py 4652 "rehearsal" --save rehearsal` | `SUMMARY {... "outcome": "dry" ...}` — stops on the Create button, `transaction requests seen: 0` |
| 0.5 | same, with `FLY_FLAP_PROBE=1` in the shell that starts flaplive.py | `outcome: "probed"`, `page asked to send #1: {"to": "0xe2ce…9de0", "value_bnb": 0.0, "method": "newTokenV7", … "predicted": "0x…8888"}`, `refused (FLY_RH_LIVE=0)` |
| 0.6 | `py voice.py --once --dry` (with `FLY_VOICE_MODEL=stub`, `FLY_STREAM=http://127.0.0.1:4660` while `roam.py` runs) | one journal line printed, `dry:` |
| 0.7 | `py xpost.py --check` | `enabled False` — X stays off |
| 0.8 | fill `launch/token.json` (gitignored) from `launch/token.example.json`: name, ticker, description, `image` path, `x` handle, website | file exists; **do not** set `FLY_FLAP_COIN` yet |

Stop the rig with Ctrl-C (or `taskkill /PID <pid> /T /F`) between steps.

## 1. Fund the wallet (you)

Address: `py bscwallet.py show` prints it. Send **0.01 BNB** on BNB Chain
(chain id 56). Why 0.01:

| item | value |
|---|---|
| Flap creation fee | **0** — confirmed by `eth_call` at value 0 (docs/flap.md §5) |
| gas for `newTokenV7` | 2,096,412 units (measured `eth_estimateGas`) |
| at today's 0.05 gwei | 0.000105 BNB |
| ×3 margin | 0.00032 BNB |
| if gas spikes to 1 gwei, ×3 | 0.0063 BNB |
| initial buy (`quoteAmt`) | 0 — the form's "creator purchase" is left at 0 |
| **transfer** | **0.01 BNB** (covers ×3 up to ~1.5 gwei; Flap's own preflight asks for 0.01) |

Then:

```bash
py bscwallet.py show
```

expect `balance 0.010000 BNB` (or whatever you sent). If the balance is
still 0 after a minute, the transfer went to the wrong chain or address — do
not continue.

## 2. Point the rig at the real token

In `.env` add one line (the file is gitignored):

```
FLY_FLAP_COIN=launch
```

Rehearse **once more, still dry**, with the real parameters on screen:

```bash
py flaplive.py --port 4652
```

open http://localhost:4652 and press START (or `py tools/drive.py 4652`).
Expect the real name / ticker / description in the log's `FINAL field
values`, `outcome: dry`, `transaction requests seen: 0`. Nothing is uploaded
in this mode — the run stops before the Create button is pressed. Stop the
rig.

## 3. Arm (you)

In `.env` change

```
FLY_RH_LIVE=0
```

to

```
FLY_RH_LIVE=1
```

This is the only switch. Both `flaplive.py` and `bscwallet.py show` report it
as `ARMED`. The rig **must be restarted** after editing `.env`.

## 4. Launch

**The one-click way.** Keep the agent running on this machine:

```bash
py tools/launch_agent.py
```

then open https://www.flapbrain.com/admin, log in with the launch
wallet, and press **发射代币** (type `LAUNCH` to confirm). The agent checks
`FLY_RH_LIVE=1`, `FLY_FLAP_COIN=launch` and the balance, refuses with the
reason written back to the page if any fails, and otherwise starts
`flaplive.py`, records with `record.py`, and reports every stage to the
page: steps 1/6/12/18, the transaction request, the broadcast hash, the
receipt, the contract. On success it flips the banner to `launched`, fills
the CA, and sets `FLY_RH_LIVE` back to 0 by itself. **彩排（干跑）** runs the
same flow with `FLY_RH_LIVE=0` (rehearsed 2026-09-11: refused launch while
disarmed, then a full recorded dry run reported step by step).

The launch profile in `.env` (set 2026-09-11): `FLY_FLAP_MODE=direct`,
`FLY_FLAP_TOKEN=tax`, `FLY_FLAP_BUY_BPS=300`, `FLY_FLAP_SELL_BPS=300` — a
3 % / 3 % tax token whose beneficiary is the launch wallet itself
(`newTokenV6`, `TOKEN_TAXED_V3`, address ending 7777; simulated OK). For a
non-tax token instead: `FLY_FLAP_MODE=site` and remove the three tax lines.

**The manual way**, if the page is unavailable:

Terminal 1 — the rig:

```bash
py flaplive.py --port 4652
```

Terminal 2 — the recording, which also presses START:

```bash
py record.py --port 4652
```

(Or press START at http://localhost:4652 yourself and have OBS capture that
page; `docs/readiness.md` §6 says how to lay it out.)

What the log shows, in order, with the times measured in rehearsal:

| t | line | meaning |
|---|---|---|
| 2 s | `wallet 0x… 0.0100 BNB on chain 56 - mode site, live ARMED` | armed and funded |
| 10 s | `wallet connected: the page shows the fly's address` | flap.sh auto-connected the injected wallet |
| 17 s | `token image selected: … ('Use This Image')` | image uploaded, crop confirmed |
| 20–29 s | `step 00 … step 17` | the fly has the mouse |
| 29 s | `field values before completion: {...}` then `FINAL field values: {...}` and `by FLY: … · by rig: …` | which fields the fly got, which the rig completed |
| 53 s | `create button 'Create Token' at (…) disabled=False` | on the button |
| 57 s | `FLY_RH_LIVE=1 - pressing create` | the press |
| ~64 s | `page asked to send #1: {"to": "0xe2ce…9de0", "value_bnb": 0.0, "method": "newTokenV7", "name": …, "symbol": …, "predicted": "0x…8888"}` | the one transaction. **Check `to` is the Portal and `predicted` ends in 8888** |
| +1 s | `signing tx to 0xe2cE6ab808... value 0.000000 ETH gas …` then `broadcast 0x…` | signed in Python, sent |
| +3–10 s | `receipt block N status SUCCESS gas used …` | mined |
| then | `token <name> (<ticker>) at 0x…8888` and `https://flap.sh/bnb/0x…` | the coin; the rig opens its page and ends there |
| then | `wrote launch/launch.json` | the on-chain record for the site and the narrator |

The run refuses on its own if: the page asks for a transaction whose `to` is
not the Portal; the page asks for a **second** transaction; or a launch from
this wallet happened less than `FLY_FLAP_COOLDOWN_S` (3600 s) ago.

## 5. Immediately after

1. In `.env` set `FLY_RH_LIVE=0` again. Restart nothing — the rig is done.
2. `py bscwallet.py show` — the balance is lower by the gas (≈0.0001–0.002 BNB).
3. Open `https://bscscan.com/tx/<hash>` from the log. Status **Success**.
4. Site: open **https://www.flapbrain.com/admin**, enter the admin
   token (the file `site/.admin-token` on this machine; it is the
   `ADMIN_TOKEN` env on the Vercel project), press 载入当前状态, then:
   - paste the contract into 合约地址 CA, the block into 发射区块,
   - set 状态 to `launched` and the 横幅链接 to the flap.sh token page,
   - press 保存到仓库.

   That commits `site/web/live.json` to the repo; the page and `/api/state`
   read it within a minute — **no redeploy needed for a CA change**. The
   部署到生产 button is only for code changes: it runs the repo's
   `deploy site` workflow (`vercel deploy --prod`, about 50 s) and shows the
   run's progress. Before the launch, the same page with 状态 `launching`
   and the stream link turns the banner on.

   Command-line equivalent, if the page is unavailable: edit
   `site/web/live.json` by hand, `git add site/web/live.json
   launch/launch.json && git commit -m "launch" && git push`.
5. `py voice.py --once --dry` — the narrator now reads the coin from chain.

## 6. If it goes wrong

**"BROADCAST REJECTED"** in the log — the node refused the raw transaction.
Nothing left the wallet (a rejected broadcast is never mined). Set
`FLY_RH_LIVE=0`, run `py bscdryrun.py`, read the error, fix, re-arm.

**`receipt … status REVERTED`** — the transaction was mined and reverted.
**Gas was spent** (the receipt's `gasUsed × effectiveGasPrice`), nothing
else: no token, the CID is still unused, the rate limit was not consumed.
Read the revert name in the log (`MetaAlreadyUsedByOtherToken`,
`RateLimitExceeded`, `MinimumShareBalanceTooLow`, …; docs/flap.md §5a/§7).
Set `FLY_RH_LIVE=0` before touching anything else.

**No receipt after 60 s** — the log says `no receipt after 60s - still
pending`. Open the wallet on bscscan
(`https://bscscan.com/address/<wallet>`): if the transaction is there and
pending, wait; if it is not there, it was never broadcast. Do not re-arm
until you know which.

**The page asked for nothing** (`transaction requests: 0` after pressing) —
the form was rejected by the site (a field it did not like, a changed DOM).
Nothing was signed. `build/flap_after_create.png` shows what the page said.

**To confirm no money moved:** `py bscwallet.py show` before and after; the
only legitimate change is the gas of one mined transaction.

**To disarm at any moment:** `FLY_RH_LIVE=0` in `.env` and stop the rig
(Ctrl-C). A run already past `broadcast 0x…` cannot be recalled — that is why
the arm step is last.

## 7. Fallback: direct Portal call

If the site's button stops producing exactly one transaction (a redesign, a
second "approve" step, a wrong `to`), the rig can launch without the button:

```
FLY_FLAP_MODE=direct
```

in `.env`. The fly and the rig still fill the form on screen; the rig then
uploads the metadata itself (`funcs.flap.sh/api/upload` → CID), finds the
salt (`flapsalt.py`), builds `newTokenV7` (`flapportal.py`), simulates it
with `eth_call`, and only with `FLY_RH_LIVE=1` signs and broadcasts. Dry
output: `FLY_RH_LIVE=0 - simulated only. newTokenV7 (...) would create
0x…8888 with meta bafk…`. Rehearsed 2026-09-11: upload, salt, encode,
decode and simulation all pass.
