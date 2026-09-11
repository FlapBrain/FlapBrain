"""
The Flap Portal, as calldata.

Everything the rig needs to talk to Portal.newTokenV6 without a web page in
between: the ABI tuple in the order IPortal.sol declares it, a builder for a
plain non-tax token, the selector, and a decoder for the custom errors the
Portal reverts with (so "0x1a2b3c4d..." becomes "RateLimitExceeded").

Addresses and enum values are from docs/flap.md. Nothing here signs or sends;
it only produces bytes.
"""
import json

import requests
from eth_abi import encode, decode
from eth_utils import keccak, to_checksum_address

from flapsalt import PORTAL, TOKEN_IMPL_V2, TOKEN_IMPL_TAXED_V3, predict

ZERO = "0x0000000000000000000000000000000000000000"
ZERO32 = b"\x00" * 32

# enum values, IPortal.sol
DEX_THRESH = {"TWO_THIRDS": 0, "FOUR_FIFTHS": 1, "HALF": 2,
              "_95_PERCENT": 3, "_81_PERCENT": 4, "_1_PERCENT": 5}
MIGRATOR = {"V3_MIGRATOR": 0, "V2_MIGRATOR": 1, "V4_UNI_MIGRATOR": 2,
            "PCS_INFINITY_CL_MIGRATOR": 3}
DEX_ID = {"DEX0": 0, "DEX1": 1, "DEX2": 2}
LP_FEE = {"STANDARD": 0, "LOW": 1, "HIGH": 2}
TOKEN_VERSION = {"TOKEN_V2_PERMIT": 2, "TOKEN_TAXED_V3": 6}

# NewTokenV6Params, field order as declared - this IS the ABI
V6_FIELDS = [
    ("name", "string"), ("symbol", "string"), ("meta", "string"),
    ("dexThresh", "uint8"), ("salt", "bytes32"), ("migratorType", "uint8"),
    ("quoteToken", "address"), ("quoteAmt", "uint256"),
    ("beneficiary", "address"), ("permitData", "bytes"),
    ("extensionID", "bytes32"), ("extensionData", "bytes"),
    ("dexId", "uint8"), ("lpFeeProfile", "uint8"),
    ("buyTaxRate", "uint16"), ("sellTaxRate", "uint16"),
    ("taxDuration", "uint64"), ("antiFarmerDuration", "uint64"),
    ("mktBps", "uint16"), ("deflationBps", "uint16"),
    ("dividendBps", "uint16"), ("lpBps", "uint16"),
    ("minimumShareBalance", "uint256"), ("dividendToken", "address"),
    ("commissionReceiver", "address"), ("tokenVersion", "uint8"),
]
V6_TUPLE = "(" + ",".join(t for _, t in V6_FIELDS) + ")"
V6_SIGNATURE = f"newTokenV6({V6_TUPLE})"
V6_SELECTOR = keccak(text=V6_SIGNATURE)[:4]

# NewTokenV7Params - the TokenV3 non-tax path (TOKEN_V3_PERMIT, suffix 8888,
# PCS_INFINITY_CL_MIGRATOR on BNB). feeConfigs replaces beneficiary + the
# four bps fields with four fixed FeeConfig slots.
FEE_TYPE = {"NONE": 0, "MARKETING_OR_VAULT": 1, "DIVIDEND": 2,
            "DEFLATION": 3, "LP_BPS": 4}
FEE_CONFIG_TUPLE = "(uint8,uint16,address,address,uint256)"
V7_FIELDS = [
    ("name", "string"), ("symbol", "string"), ("meta", "string"),
    ("dexThresh", "uint8"), ("salt", "bytes32"), ("migratorType", "uint8"),
    ("quoteToken", "address"), ("quoteAmt", "uint256"),
    ("permitData", "bytes"), ("extensionID", "bytes32"),
    ("extensionData", "bytes"), ("dexId", "uint8"),
    ("buyTaxRate", "uint16"), ("sellTaxRate", "uint16"),
    ("taxDuration", "uint64"), ("antiFarmerDuration", "uint64"),
    ("commissionReceiver", "address"), ("tokenVersion", "uint8"),
    ("feeConfigs", FEE_CONFIG_TUPLE + "[4]"),
]
V7_TUPLE = "(" + ",".join(t for _, t in V7_FIELDS) + ")"
V7_SIGNATURE = f"newTokenV7({V7_TUPLE})"
V7_SELECTOR = keccak(text=V7_SIGNATURE)[:4]
TOKEN_VERSION["TOKEN_V3_PERMIT"] = 7
TOKEN_IMPL_V3 = "0x88881b6f03090462a969eC7f48385744Eeb63333"   # BNB, suffix 8888

# custom errors we want to name when the Portal reverts
ERRORS = {
    "MetaAlreadyUsedByOtherToken(string)": ["string"],
    "InsufficientCreationFee(uint256,uint256)": ["uint256", "uint256"],
    "InsufficientFee(uint256,uint256)": ["uint256", "uint256"],
    "RateLimitExceeded(address,uint256)": ["address", "uint256"],
    "SpammerBlocked(address)": ["address"],
    "InvalidMigratorType()": [],
    "FeatureDisabled()": [],
    "InvalidDexThresholdType(uint8)": ["uint8"],
    "UnsupportedTokenVersion(uint8)": ["uint8"],
    "NewTokenV7RuleViolation(uint8)": ["uint8"],
    "UnsupportedV7TokenV3PermitFeeType(uint8)": ["uint8"],
    "InvalidFeeConfig()": [],
    "MinimumShareBalanceTooLow()": [],
    "Error(string)": ["string"],
    "Panic(uint256)": ["uint256"],
}
ERROR_BY_SELECTOR = {keccak(text=sig)[:4].hex(): (sig.split("(")[0], types)
                     for sig, types in ERRORS.items()}


def _b32(x):
    if isinstance(x, bytes):
        return x
    return bytes.fromhex(x.replace("0x", ""))


def _bytes(x):
    if isinstance(x, bytes):
        return x
    return bytes.fromhex(x.replace("0x", "")) if x and x != "0x" else b""


def standard_token_params(name, symbol, meta, salt, beneficiary,
                          quote_amt_wei=0, anti_farmer_s=0,
                          dex_thresh="FOUR_FIFTHS"):
    """
    NewTokenV6Params for a plain TOKEN_V2_PERMIT token quoted in native BNB.

    Every tax field is zero and commissionReceiver is the zero address, which
    is what the dispatch table requires for a non-tax token. The salt must
    already produce an address ending in 8888 against TOKEN_IMPL_V2.
    """
    return {
        "name": name, "symbol": symbol, "meta": meta,
        "dexThresh": DEX_THRESH[dex_thresh],
        "salt": _b32(salt),
        "migratorType": MIGRATOR["V2_MIGRATOR"],
        "quoteToken": ZERO, "quoteAmt": int(quote_amt_wei),
        "beneficiary": to_checksum_address(beneficiary),
        "permitData": b"", "extensionID": ZERO32, "extensionData": b"",
        "dexId": DEX_ID["DEX0"], "lpFeeProfile": LP_FEE["STANDARD"],
        "buyTaxRate": 0, "sellTaxRate": 0, "taxDuration": 0,
        "antiFarmerDuration": int(anti_farmer_s),
        "mktBps": 0, "deflationBps": 0, "dividendBps": 0, "lpBps": 0,
        "minimumShareBalance": 0, "dividendToken": ZERO,
        "commissionReceiver": ZERO,
        "tokenVersion": TOKEN_VERSION["TOKEN_V2_PERMIT"],
    }


def standard_token_v7_params(name, symbol, meta, salt, beneficiary,
                             quote_amt_wei=0, anti_farmer_s=0,
                             dex_thresh="FOUR_FIFTHS"):
    """
    NewTokenV7Params for a TOKEN_V3_PERMIT (non-tax) token on BNB.

    The docs' public rollout: PCS_INFINITY_CL_MIGRATOR, zero taxes, zero
    commissionReceiver, and exactly one active fee slot - MARKETING_OR_VAULT
    at 10000 bps with the beneficiary as marketingAddress.
    """
    empty = (FEE_TYPE["NONE"], 0, ZERO, ZERO, 0)
    return {
        "name": name, "symbol": symbol, "meta": meta,
        "dexThresh": DEX_THRESH[dex_thresh],
        "salt": _b32(salt),
        "migratorType": MIGRATOR["PCS_INFINITY_CL_MIGRATOR"],
        "quoteToken": ZERO, "quoteAmt": int(quote_amt_wei),
        "permitData": b"", "extensionID": ZERO32, "extensionData": b"",
        "dexId": DEX_ID["DEX0"],
        "buyTaxRate": 0, "sellTaxRate": 0, "taxDuration": 0,
        "antiFarmerDuration": int(anti_farmer_s),
        "commissionReceiver": ZERO,
        "tokenVersion": TOKEN_VERSION["TOKEN_V3_PERMIT"],
        "feeConfigs": [(FEE_TYPE["MARKETING_OR_VAULT"], 10000,
                        to_checksum_address(beneficiary), ZERO, 0),
                       empty, empty, empty],
    }


def encode_new_token_v7(params):
    """0x-prefixed calldata for Portal.newTokenV7(params)."""
    values = tuple(params[k] for k, _ in V7_FIELDS)
    return "0x" + (V7_SELECTOR + encode([V7_TUPLE], [values])).hex()


def decode_new_token_v7(data):
    raw = _bytes(data)
    if raw[:4] != V7_SELECTOR:
        return None
    (vals,) = decode([V7_TUPLE], raw[4:])
    out = dict(zip((k for k, _ in V7_FIELDS), vals))
    out["salt"] = "0x" + out["salt"].hex()
    out["extensionID"] = "0x" + out["extensionID"].hex()
    out["permitData"] = "0x" + out["permitData"].hex()
    out["extensionData"] = "0x" + out["extensionData"].hex()
    return out


def decode_launch(data):
    """Whichever of the two launch calls this calldata is, or None."""
    d = decode_new_token_v6(data)
    if d is not None:
        return "newTokenV6", d
    d = decode_new_token_v7(data)
    if d is not None:
        return "newTokenV7", d
    return None, None


def encode_new_token_v6(params):
    """0x-prefixed calldata for Portal.newTokenV6(params)."""
    values = tuple(params[k] for k, _ in V6_FIELDS)
    return "0x" + (V6_SELECTOR + encode([V6_TUPLE], [values])).hex()


def decode_new_token_v6(data):
    """The inverse, for checking what a page asked the wallet to send."""
    raw = _bytes(data)
    if raw[:4] != V6_SELECTOR:
        return None
    (vals,) = decode([V6_TUPLE], raw[4:])
    out = dict(zip((k for k, _ in V6_FIELDS), vals))
    out["salt"] = "0x" + out["salt"].hex()
    out["extensionID"] = "0x" + out["extensionID"].hex()
    out["permitData"] = "0x" + out["permitData"].hex()
    out["extensionData"] = "0x" + out["extensionData"].hex()
    return out


def impl_for(token_version):
    if token_version == TOKEN_VERSION["TOKEN_TAXED_V3"]:
        return TOKEN_IMPL_TAXED_V3
    if token_version == TOKEN_VERSION["TOKEN_V3_PERMIT"]:
        return TOKEN_IMPL_V3
    return TOKEN_IMPL_V2


def predicted_address(params):
    """Where this token will live, from its salt and version."""
    return predict(params["salt"], impl_for(params["tokenVersion"]), PORTAL)


def decode_error(err):
    """
    Name a JSON-RPC revert.

    Takes the "error" object from an eth_call / eth_estimateGas response and
    returns (name, args). Unknown selectors come back as the raw hex so nothing
    is hidden.
    """
    if not err:
        return ("unknown", [])
    data = None
    if isinstance(err, dict):
        data = err.get("data")
        if isinstance(data, dict):
            data = data.get("data") or data.get("originalError", {}).get("data")
        if not data:
            msg = str(err.get("message", ""))
            # some nodes put the revert hex in the message; an address in an
            # "insufficient funds for 0xabc..." message is not revert data
            for tok in msg.replace(",", " ").replace(")", " ").split():
                if tok.startswith("0x") and (len(tok) - 10) % 64 == 0:
                    data = tok
                    break
            if not data:
                return (msg[:160] or "unknown", [])
    if not isinstance(data, str) or not data.startswith("0x") or len(data) < 10:
        return (str(data)[:120], [])
    sel = data[2:10]
    name, types = ERROR_BY_SELECTOR.get(sel, (None, None))
    if name is None:
        return ("0x" + sel, [data])
    try:
        args = list(decode(types, bytes.fromhex(data[10:]))) if types else []
    except Exception:
        args = [data]
    return (name, args)


def rpc(url, method, params):
    r = requests.post(url, json={"jsonrpc": "2.0", "id": 1,
                                 "method": method, "params": params},
                      timeout=30).json()
    if "error" in r:
        raise RuntimeError(json.dumps(r["error"])[:300])
    return r.get("result")


def simulate(url, tx):
    """
    eth_call the transaction the rig is about to send.

    Returns {"ok": True, "token": address} when the Portal would accept it,
    or {"ok": False, "error": "<named revert>"} otherwise. Nothing is sent.
    """
    call = {"from": tx["from"], "to": tx["to"], "value": hex(int(tx.get("value", 0))),
            "data": tx["data"]}
    r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                                 "params": [call, "latest"]}, timeout=30).json()
    if "error" in r:
        name, args = decode_error(r["error"])
        return {"ok": False, "error": f"{name} {args}" if args else name,
                "raw": json.dumps(r["error"])[:300]}
    res = r.get("result") or ""
    token = to_checksum_address("0x" + res[-40:]) if len(res) >= 66 else res
    return {"ok": True, "token": token}


UPLOAD_API = "https://funcs.flap.sh/api/upload"
UPLOAD_MUTATION = ("mutation Create($file: Upload!, $meta: MetadataInput!) "
                   "{ create(file: $file, meta: $meta) }")


def upload_meta(image_path, description, twitter=None, telegram=None,
                website=None, timeout=60):
    """
    Pin the image and the metadata JSON through Flap's API; returns the CID.

    The multipart body is the graphql-multipart-request-spec shape from the
    docs: an `operations` JSON with the file variable null, a `map` pointing
    part "0" at variables.file, and the file itself as part "0". `creator`
    is the zero address, as documented. No key, no login, nothing signed.
    """
    import mimetypes
    from pathlib import Path

    p = Path(image_path)
    ctype = mimetypes.guess_type(p.name)[0] or "image/png"
    operations = json.dumps({
        "query": UPLOAD_MUTATION,
        "variables": {"file": None,
                      "meta": {"description": description or "",
                               "twitter": twitter or None,
                               "telegram": telegram or None,
                               "website": website or None,
                               "creator": ZERO}}})
    files = [
        ("operations", (None, operations, "application/json")),
        ("map", (None, json.dumps({"0": ["variables.file"]}), "application/json")),
        ("0", (p.name, p.read_bytes(), ctype)),
    ]
    r = requests.post(UPLOAD_API, files=files, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"upload HTTP {r.status_code}: {r.text[:200]}")
    body = r.json()
    if body.get("errors"):
        raise RuntimeError(f"upload rejected: {json.dumps(body['errors'])[:200]}")
    cid = (body.get("data") or {}).get("create")
    if not cid:
        raise RuntimeError(f"upload returned no CID: {json.dumps(body)[:200]}")
    return cid


def token_name_symbol(url, addr):
    """name() and symbol() of an ERC-20, for reporting a launch."""
    def _dec(x):
        if not x or len(x) < 130:
            return ""
        n = int(x[66:130], 16)
        try:
            return bytes.fromhex(x[130:130 + n * 2]).decode("utf-8", "replace")
        except Exception:
            return ""
    nm = _dec(rpc(url, "eth_call", [{"to": addr, "data": "0x06fdde03"}, "latest"]))
    sy = _dec(rpc(url, "eth_call", [{"to": addr, "data": "0x95d89b41"}, "latest"]))
    return nm, sy


if __name__ == "__main__":
    print("newTokenV6 selector", "0x" + V6_SELECTOR.hex())
    p = standard_token_params("t", "T", "cid", "0x" + "11" * 32, ZERO)
    d = encode_new_token_v6(p)
    assert decode_new_token_v6(d)["symbol"] == "T"
    print("round trip ok,", len(d) // 2 - 1, "bytes")
    for sel, (n, _) in ERROR_BY_SELECTOR.items():
        print(f"  {sel}  {n}")
