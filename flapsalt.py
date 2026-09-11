"""
Vanity salt for a Flap token, found the way the Flap docs describe it.

Flap's Portal deploys every token as an EIP-1167 minimal proxy through CREATE2,
so the token address is known before the transaction is sent - and the Portal
insists on a vanity suffix: a standard (non-tax) token must end in 8888, a tax
token in 7777. The salt is found by hashing a random seed until the predicted
address has the right suffix. Two hex digits either side of a four-digit
target is 1 in 65,536 per try, so a search takes tens of thousands of keccaks
and well under a second in Python.

The prediction follows section 4 of "Launch token through Portal":

    proxy bytecode = 3d602d80600a3d3981f3363d3d373d3d3d363d73 <impl> 5af43d82803e903d91602b57fd5bf3
    address        = keccak(0xff ++ portal ++ salt ++ keccak(bytecode))[12:]

The deployer in the CREATE2 formula is always the Portal, even for launches
that go through VaultPortal (it delegates the deployment to Portal).

  py flapsalt.py                 standard token (suffix 8888)
  py flapsalt.py --tax           tax token (suffix 7777)
  py flapsalt.py --seed <hex>    deterministic, for tests

Nothing here touches a key, a wallet or the network.
"""
import argparse
import os
import time

from eth_utils import keccak, to_checksum_address

# BNB Chain mainnet, from docs.flap.sh "Deployed Contract Addresses"
PORTAL = "0xe2cE6ab80874Fa9Fa2aAE65D277Dd6B8e65C9De0"
TOKEN_IMPL_V2 = "0x8b4329947e34b6d56d71a3385cac122bade7d78d"        # standard, 8888
TOKEN_IMPL_TAXED_V3 = "0x024f18294970B5c76c0691b87f138A0317156422"  # tax V3, 7777

SUFFIX_STANDARD = "8888"
SUFFIX_TAX = "7777"


def proxy_bytecode(impl):
    """EIP-1167 minimal proxy init code pointing at `impl`."""
    impl = impl.lower().replace("0x", "")
    if len(impl) != 40:
        raise ValueError("implementation address must be 20 bytes")
    return bytes.fromhex("3d602d80600a3d3981f3363d3d373d3d3d363d73" + impl
                         + "5af43d82803e903d91602b57fd5bf3")


def predict(salt, impl, portal=PORTAL):
    """CREATE2 address of the proxy the Portal would deploy for `salt`."""
    if isinstance(salt, str):
        salt = bytes.fromhex(salt.replace("0x", ""))
    if len(salt) != 32:
        raise ValueError("salt must be 32 bytes")
    deployer = bytes.fromhex(portal.lower().replace("0x", ""))
    init_hash = keccak(proxy_bytecode(impl))
    return to_checksum_address(keccak(b"\xff" + deployer + salt + init_hash)[12:])


def find_salt(suffix, impl, portal=PORTAL, seed=None, max_iter=5_000_000):
    """
    Hash a seed until the predicted address ends in `suffix`.

    Returns (salt_hex, address, iterations, seconds). The seed can be anything
    32 bytes long - the docs use a throwaway private key only because it is a
    convenient random value; os.urandom does the same job with no key involved.
    """
    if len(suffix) != 4:
        raise ValueError("suffix must be exactly 4 hex characters")
    suffix = suffix.lower()
    seed = seed if seed is not None else os.urandom(32)
    deployer = bytes.fromhex(portal.lower().replace("0x", ""))
    init_hash = keccak(proxy_bytecode(impl))
    salt = keccak(seed)
    t0 = time.perf_counter()
    for i in range(max_iter):
        addr = keccak(b"\xff" + deployer + salt + init_hash)[12:]
        if addr.hex().endswith(suffix):
            return ("0x" + salt.hex(), to_checksum_address(addr), i,
                    time.perf_counter() - t0)
        salt = keccak(salt)
    raise RuntimeError(f"no salt with suffix {suffix} in {max_iter} iterations")


def find_standard_salt(seed=None):
    return find_salt(SUFFIX_STANDARD, TOKEN_IMPL_V2, seed=seed)


def find_tax_salt(seed=None):
    return find_salt(SUFFIX_TAX, TOKEN_IMPL_TAXED_V3, seed=seed)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tax", action="store_true", help="tax token: suffix 7777")
    ap.add_argument("--seed", help="32-byte hex seed for a repeatable search")
    ap.add_argument("--runs", type=int, default=1, help="repeat to average timing")
    a = ap.parse_args()

    impl = TOKEN_IMPL_TAXED_V3 if a.tax else TOKEN_IMPL_V2
    suffix = SUFFIX_TAX if a.tax else SUFFIX_STANDARD
    seed = bytes.fromhex(a.seed.replace("0x", "")) if a.seed else None
    print(f"portal   {PORTAL}")
    print(f"impl     {impl}  ({'tax V3' if a.tax else 'standard'})")
    print(f"suffix   {suffix}\n")

    total_i, total_s = 0, 0.0
    for r in range(a.runs):
        salt, addr, n, secs = find_salt(suffix, impl, seed=seed)
        total_i += n
        total_s += secs
        # the prediction is recomputed independently of the search loop
        assert predict(salt, impl) == addr
        print(f"run {r + 1}: salt {salt}")
        print(f"       address {addr}")
        print(f"       {n:,} iterations in {secs:.3f}s "
              f"({n / secs if secs else 0:,.0f} keccak/s)")
    if a.runs > 1:
        print(f"\naverage {total_i / a.runs:,.0f} iterations, "
              f"{total_s / a.runs:.3f}s per salt")


if __name__ == "__main__":
    main()
