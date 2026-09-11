"""
The fly's BNB Chain wallet.

A copy of rhwallet.py with the chain swapped: BNB Chain is EVM, secp256k1,
gas in BNB, chain id 56. It is a separate keypair in a separate .env entry
(FLY_BSC_SECRET), so it can never be confused with the Robinhood Chain wallet
or the Solana one.

Same rule as the other two: the secret is generated here, written straight
into .env (gitignored), and never printed. Only the address is shown.

  py bscwallet.py new       create the fly's BNB Chain wallet
  py bscwallet.py show      address, balance, chain

The RPC comes from FLY_BSC_RPC in .env; the public Binance node is only the
fallback. Set your own node there.
"""
import sys
from pathlib import Path

import requests
from eth_account import Account

from envcfg import load_env

ROOT = Path(__file__).parent
ENV = ROOT / ".env"

CHAIN_ID = 56
RPC = "https://bsc-dataseed.binance.org"          # public fallback only
EXPLORER = "https://bscscan.com"

# Flap charges no fixed creation fee on BNB Chain: the docs and Flap's own
# launch skill put msg.value = quoteAmt (the optional initial buy, 0 to skip)
# and budget the launch at ~0.002-0.010 BNB of gas. The Portal interface does
# carry an InsufficientCreationFee error, so bscdryrun.py simulates the call
# rather than trusting this constant.
LAUNCH_FEE_BNB = 0.0
GAS_RESERVE_BNB = 0.01       # what preflight.md says to hold before launching


def _write_env_key(key, value):
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    out, done = [], False
    for line in lines:
        if line.strip().startswith(f"{key}="):
            out.append(f"{key}={value}")
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f"{key}={value}")
    ENV.write_text("\n".join(out) + "\n")


def rpc_call(method, params=None, rpc=None):
    r = requests.post(rpc or RPC, json={"jsonrpc": "2.0", "id": 1,
                                        "method": method,
                                        "params": params or []}, timeout=25)
    return r.json()


def rpc_url(env=None):
    env = env or load_env()
    return env.get("FLY_BSC_RPC") or RPC


def new():
    env = load_env()
    if env.get("FLY_BSC_SECRET"):
        print("FLY_BSC_SECRET is already set in .env - refusing to overwrite.")
        print("Delete that line by hand first if you really want a new wallet.")
        return
    Account.enable_unaudited_hdwallet_features()
    acct = Account.create()
    _write_env_key("FLY_BSC_SECRET", acct.key.hex())
    if not env.get("FLY_BSC_RPC"):
        _write_env_key("FLY_BSC_RPC", RPC)
    _write_env_key("FLY_RH_LIVE", env.get("FLY_RH_LIVE", "0"))
    print("created the fly's BNB Chain wallet\n")
    print(f"  address   {acct.address}")
    print(f"  chain     BNB Chain (id {CHAIN_ID})")
    print(f"  secret    written to .env (gitignored), not shown here")
    print(f"\nFund it with BNB, then:  py bscwallet.py show")
    print(f"Flap charges no fixed creation fee; hold ~{GAS_RESERVE_BNB} BNB for gas.")
    print(f"Explorer: {EXPLORER}/address/{acct.address}")


def account(env=None):
    env = env or load_env()
    sec = env.get("FLY_BSC_SECRET")
    if not sec:
        print("no BNB Chain wallet yet - run: py bscwallet.py new")
        sys.exit(1)
    return Account.from_key(sec)


def balance(env=None, quiet=False):
    env = env or load_env()
    acct = account(env)
    rpc = rpc_url(env)
    wei = 0
    chain = None
    try:
        r = rpc_call("eth_getBalance", [acct.address, "latest"], rpc)
        wei = int(r.get("result", "0x0"), 16)
        c = rpc_call("eth_chainId", [], rpc)
        chain = int(c.get("result", "0x0"), 16)
    except Exception as e:
        if not quiet:
            print(f"  rpc error: {str(e)[:120]}")
    bnb = wei / 1e18
    if not quiet:
        print(f"  address   {acct.address}")
        print(f"  rpc       {rpc}")
        print(f"  chain id  {chain}  ({'ok' if chain == CHAIN_ID else 'UNEXPECTED'})")
        print(f"  balance   {bnb:.6f} BNB")
        print(f"  live      {'ARMED' if env.get('FLY_RH_LIVE') == '1' else 'no (FLY_RH_LIVE=0)'}")
        if bnb < GAS_RESERVE_BNB:
            print(f"\n  below the {GAS_RESERVE_BNB} BNB gas reserve preflight.md asks for")
        print(f"\n  {EXPLORER}/address/{acct.address}")
    return bnb


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd == "new":
        new()
    elif cmd in ("show", "balance"):
        balance()
    else:
        print(__doc__)
