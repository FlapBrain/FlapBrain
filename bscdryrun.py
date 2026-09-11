"""
Prove the BNB Chain transaction path without spending anything.

The Robinhood Chain rig had rhdryrun.py for this; this is the same check
against BNB Chain and the Flap Portal, plus one thing the docs could not
settle: whether the Portal charges a creation fee. The interface declares
InsufficientCreationFee but the docs put msg.value = quoteAmt and nothing
else, so the last step here asks the chain directly with an eth_call of a
real newTokenV6 payload.

  1. RPC reachable, chain id is 56
  2. nonce and gas price come back
  3. a real (self-send) transaction is assembled and signed locally
  4. the signature is recovered and checked against the wallet address
  5. a real newTokenV6 payload is built and simulated with eth_call at
     value = 0 - the Portal's answer is the creation fee question settled

Nothing is broadcast. There is no code path here that can send.

  py bscdryrun.py
  py bscdryrun.py --no-sim        skip the newTokenV6 simulation
"""
import argparse
import json
import os

import requests
from eth_account import Account
from eth_utils import to_hex, keccak

from envcfg import load_env
from bscwallet import account, rpc_url, CHAIN_ID, LAUNCH_FEE_BNB, GAS_RESERVE_BNB
from flapsalt import PORTAL, find_salt, SUFFIX_STANDARD
from flapportal import (encode_new_token_v7, standard_token_v7_params,
                        decode_error, FEE_TYPE, ZERO, TOKEN_IMPL_V3)


def rpc(method, params, url):
    r = requests.post(url, json={"jsonrpc": "2.0", "id": 1,
                                 "method": method, "params": params},
                      timeout=30).json()
    if "error" in r:
        return None, r["error"]
    return r.get("result"), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-sim", action="store_true")
    a = ap.parse_args()

    env = load_env()
    acct = account(env)
    url = rpc_url(env)
    print(f"wallet  {acct.address}")
    print(f"rpc     {url}\n")

    # 1. chain reachable and correct
    cid, err = rpc("eth_chainId", [], url)
    chain_ok = bool(cid) and int(cid, 16) == CHAIN_ID
    print(f"chain id        {int(cid, 16) if cid else err} "
          f"{'ok' if chain_ok else 'UNEXPECTED'}")
    bal, _ = rpc("eth_getBalance", [acct.address, "latest"], url)
    wei = int(bal, 16) if bal else 0
    print(f"balance         {wei/1e18:.6f} BNB")

    # 2. the fields send_transaction needs
    nonce, e1 = rpc("eth_getTransactionCount", [acct.address, "pending"], url)
    gas_price, e2 = rpc("eth_gasPrice", [], url)
    blk, _ = rpc("eth_getBlockByNumber", ["latest", False], url)
    base_fee = blk.get("baseFeePerGas") if blk else None
    print(f"nonce           {int(nonce,16) if nonce else e1}")
    print(f"gas price       {int(gas_price,16)/1e9:.4f} gwei"
          if gas_price else f"gas price       {e2}")
    if base_fee:
        print(f"base fee        {int(base_fee,16)/1e9:.4f} gwei")
    gp = int(gas_price, 16) if gas_price else 10**9

    # 3. assemble and sign a real transaction (self-send, zero value).
    # BNB Chain accepts type-2 transactions since the Berlin/London forks;
    # rhprovider.send_transaction uses the same shape.
    tx = {
        "from": acct.address, "to": acct.address, "value": 0,
        "data": "0x", "chainId": CHAIN_ID,
        "nonce": int(nonce, 16) if nonce else 0,
        "gas": 21000,
        "maxFeePerGas": int(gp * 2),
        "maxPriorityFeePerGas": min(gp, 10**9),
        "type": 2,
    }
    signed = acct.sign_transaction(tx)
    raw = signed.raw_transaction
    print(f"\nsigned tx       {len(raw)} bytes, hash {to_hex(signed.hash)[:20]}...")

    # 4. does the signature actually belong to this wallet?
    recovered = Account.recover_transaction(raw)
    ok = recovered.lower() == acct.address.lower()
    print(f"recovered from  {recovered}  {'MATCHES' if ok else 'MISMATCH'}")

    # a plain self-send estimate, as rhdryrun does
    est, err = rpc("eth_estimateGas", [{
        "from": acct.address, "to": acct.address, "value": "0x0"}], url)
    if est:
        print(f"estimateGas     {int(est,16)} units (self-send)")
    else:
        print(f"estimateGas     rejected: {json.dumps(err)[:200]}")

    # 5. simulate a real launch, value 0, nothing sent
    fee_note = None
    if not a.no_sim:
        # The docs' newTokenV6 + TOKEN_V2_PERMIT shape reverts FeatureDisabled
        # on BNB mainnet (probed 2026-09-11). What the Portal accepts for a
        # non-tax token is newTokenV7 + TOKEN_V3_PERMIT with one DIVIDEND fee
        # slot and minimumShareBalance >= 10,000 tokens - docs/flap.md.
        print("\nsimulating newTokenV7 on the Portal (eth_call, value 0) ...")
        salt, predicted, n, secs = find_salt(SUFFIX_STANDARD, TOKEN_IMPL_V3)
        # a meta string nobody has used: the contract rejects duplicates
        meta = "dryrun-" + keccak(os.urandom(16)).hex()[:32]
        params = standard_token_v7_params(
            name="dryrun", symbol="DRY", meta=meta, salt=salt,
            beneficiary=acct.address, quote_amt_wei=0)
        params["feeConfigs"] = [(FEE_TYPE["DIVIDEND"], 10000, ZERO, ZERO, 10_000 * 10**18)] + \
                               [(FEE_TYPE["NONE"], 0, ZERO, ZERO, 0)] * 3
        data = encode_new_token_v7(params)
        print(f"  salt {salt[:18]}... -> {predicted}  ({n:,} iterations, {secs:.2f}s)")
        print(f"  calldata {len(data)//2 - 1} bytes, selector {data[:10]}")
        call = {"from": acct.address, "to": PORTAL, "value": "0x0", "data": data}
        res, err = rpc("eth_call", [call, "latest"], url)
        if res is not None:
            token = "0x" + res[-40:] if len(res) >= 66 else res
            print(f"  eth_call        ok - Portal would return token {token}")
            print(f"  creation fee    none required at value 0 "
                  f"(predicted {predicted}, {'suffix ok' if token.lower() == predicted.lower() else 'ADDRESS MISMATCH'})")
            fee_note = 0
        else:
            name, args = decode_error(err)
            print(f"  eth_call        reverted: {name} {args}")
            if name == "InsufficientCreationFee":
                fee_note = args[0] / 1e18
                print(f"  creation fee    {fee_note:.6f} BNB required by the Portal")
            else:
                print(f"  raw error       {json.dumps(err)[:300]}")
        g, gerr = rpc("eth_estimateGas", [call], url)
        if g:
            print(f"  estimateGas     {int(g,16):,} units "
                  f"(~{int(g,16) * gp / 1e18:.6f} BNB at {gp/1e9:.2f} gwei)")
        else:
            print(f"  estimateGas     rejected: {decode_error(gerr)[0]}")

    fee = LAUNCH_FEE_BNB if fee_note is None else fee_note
    print(f"\nrough cost to launch: {fee:.6f} BNB fee + gas; "
          f"preflight asks for {GAS_RESERVE_BNB} BNB in the wallet")
    print("\nNothing was broadcast.")
    if ok and chain_ok:
        print("Signing, nonce and fee lookup all work on BNB Chain.")
    else:
        print("Something above is wrong - do not fund until it is fixed.")


if __name__ == "__main__":
    main()
