# FlapBrain — a fruit fly brain on BNB Chain / flap.sh

A real fruit fly brain, simulated neuron by neuron, filling in the
[flap.sh](https://flap.sh) token launchpad on BNB Chain.

165,122 neurons. 10,228,000 signed synaptic connections. Every one of them
measured from an actual male *Drosophila melanogaster* by electron
microscopy — not invented, not sampled from a distribution, not a neural
network "inspired by" a brain.

This is a fork of [fruitflydev/flycoinrh](https://github.com/fruitflydev/flycoinrh)
(MIT), which launched the same brain on Robinhood Chain through pons. The
brain — `flysim.py`, `flyeye.py`, `mushroom.py`, `roam.py` — is theirs and is
untouched here; the launch layer is what changed. Their README is the best
account of how the brain works; this one is about the port.

## What it does

Press START and a real Chromium opens flap.sh/create. Its screenshots are
sampled through the fly's **892 retinotopic hex columns** into L1 and L2, the
lamina monopolar cells that are the direct postsynaptic targets of
photoreceptors R1–R6. 165,122 neurons integrate. The cursor comes back out of
the descending neurons a fly actually walks with:

| neuron | what it does in a fly | what it does here |
|---|---|---|
| **DNa02** left vs right | steering | cursor x |
| **DNa01** | forward walking | cursor y |
| **MDN** | the Moonwalker descending neuron — walking backwards | reverse |
| **DNp09** | stopping | the click |

A click that lands inside an empty field types into it. When the fly's turn
is over, the rig completes whatever it missed, confirms the image crop, and
presses the site's own **Create Token** button. The page uploads the metadata
to Flap's IPFS gateway and asks the injected wallet for exactly one
transaction — `Portal.newTokenV7` — which is signed in Python and broadcast.
The private key never enters the page.

## The rails

Two flags in `.env`, both off by default, gate everything:

- `FLY_ALLOW_BROWSER=1` — before a browser will open against a real site at all.
- `FLY_RH_LIVE=1` — before any transaction is signed. This is the **one**
  switch for every rig in the repo. Funding the wallet does not arm anything.

With `FLY_RH_LIVE=0` the rig stops on the Create button. With
`FLY_FLAP_PROBE=1` it presses the button anyway so the transaction the page
asks for can be seen and decoded — and refuses it before anything is signed.
The rig also refuses a transaction whose `to` is not the Flap Portal, a
second transaction in one run, and any launch inside a cooldown of the
previous one from the same wallet.

## Running it

```bash
pip install -r requirements.txt
python -m playwright install chromium

# the connectome - 1.1 GB, CC-BY, no account and no key. Note the
# flat-connectome/ segment, which the upstream README omits:
#   https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/flat-connectome/
#     body-annotations-male-cns-v1.0-minconf-0.5.feather   -> data/body-annotations.feather
#     body-neurotransmitters-male-cns-v1.0.feather         -> data/body-neurotransmitters.feather
#     connectome-weights-male-cns-v1.0-minconf-0.5.feather -> data/connectome-weights.feather
py build_graph.py                 # -> build/graph.npz, 165,122 neurons, 10,228,000 edges
cp assets/gains_ui.npz build/
cp .env.example .env              # then FLY_ALLOW_BROWSER=1

py bscwallet.py new               # the launch wallet; prints only the address
py bscdryrun.py                   # signing path + a simulated launch, nothing sent
py flapsalt.py                    # a vanity salt (address ending 8888), ~0.5 s
py flaplive.py                    # http://localhost:4652, press START (dry)
py record.py --port 4652          # record a run to build/recordings/
py demo.py                        # replay a recorded run, no brain, no browser
py roam.py                        # the fly loose on the internet, :4660
py voice.py --once --dry          # one journal entry, nothing posted
```

`docs/launch-runbook.md` is the launch-day procedure, every command of which
has been executed in dry mode. `docs/readiness.md` is the checklist.
`docs/flap.md` is everything learned about Flap's contracts and site,
including what the BNB mainnet Portal actually accepts today (which is not
quite what its docs say).

## The launch, as it will be

| | |
|---|---|
| chain | BNB Chain, id 56 |
| venue | flap.sh, non-tax token |
| contract call | `Portal.newTokenV7`, `TOKEN_V3_PERMIT`, PancakeSwap Infinity CL migrator, LP fees paid to holders as dividends |
| address | CREATE2, ends in `8888`, known before the transaction is sent |
| creation fee | none — confirmed by `eth_call` at value 0 |
| gas | ~2.1 M units; ≈0.0001 BNB at BNB Chain's 0.05 gwei floor |
| wallet | a fresh keypair made by `bscwallet.py new`, funded by a person on the day |

## What is NOT real, stated plainly

- **The fly does not fill the whole form.** The upstream author reports
  2 of 3 fields on pons in dark mode. On flap.sh, across the dry runs
  recorded for this port, the fly filled **0 of 3**: its cursor wanders
  left and down from wherever it starts and, in 18 steps, did not enter a
  field. The rig completes what it misses, and the live log labels which
  field was which — `by FLY: … · by rig: …`. The numbers are in
  `docs/readiness.md`, not smoothed.
- **The rig frames the page.** It sets nothing in the brain, but it does
  choose where the mouse starts (above the form, centred on it), scrolls the
  form into view, confirms the image crop dialog, and presses Create. Those
  are decisions a person made about the stage, not the fly.
- **It cannot read.** 892 columns is roughly a 30×30 pixel view. Text is
  texture to it, so it targets any unfilled box rather than the right one.
- **Light mode blinds it.** flap.sh is dark by default, which is why it was
  chosen; the rig checks and re-applies dark if the site remembers otherwise.
- **The launch is one signature, and a person arms it.** The launchpad asks
  for a single `eth_sendTransaction`; the rig signs it only when a human has
  funded the wallet and set `FLY_RH_LIVE=1` by hand.
- **The reward signal is invented.** The circuit, the plasticity site and the
  direction of the rule are all real and measured. A fly is rewarded by sugar,
  not by reaching a web page — novelty stands in for it here, and that is a
  choice a person made.
- **The voice is a narrator.** Every journal entry is written by a language
  model handed the fly's telemetry and the numbers from its token page, and
  checked against them. The neurons, the pages and the fees are real. The
  words are the narrator's.
- **The test tokens are tests.** Anything named `test (TEST)` from this
  wallet was launched to prove the path. It is not a project and nobody
  should buy it.

## Credits and licences

Code: MIT, © the original authors at
[fruitflydev/flycoinrh](https://github.com/fruitflydev/flycoinrh) and the
contributors to this fork; see `LICENSE`.

Connectome data © HHMI Janelia FlyEM, the Cambridge Connectomics Group and
Google Research, released **CC-BY** — see `NOTICE`. The connectome is not
ours to license and stays CC-BY wherever it goes; keep the attribution, it is
the whole reason any of this is real. Simulation approach after Shiu et al.
2024 and Lappalainen et al. 2024. Not affiliated with any of them, nor with
Flap or Binance.
