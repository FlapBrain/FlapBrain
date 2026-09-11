# Flap (flap.sh) on BNB Chain — what the rig needs to know

Distilled on 2026-09-11 from the official developer docs and Flap's own
launch skill. Sources, in the order they were read:

- https://docs.flap.sh/flap/developers/token-launcher-developers/launch-token-through-portal.md
- https://docs.flap.sh/flap/developers/deployed-contract-addresses.md
  (the `token-launcher-developers/deployed-contract-addresses.md` URL is a
  one-line redirect to this page)
- https://docs.flap.sh/flap/llms-full.txt
- https://github.com/flap-sh/flap-skills/tree/main/launch-bnb-token-on-flap
  (`SKILL.md`, `references/meta-upload.md`, `salt-finding.md`,
  `construct-tx.md`, `preflight.md`)

Where the docs and the skill disagree or leave a gap, that is said explicitly
below rather than papered over.

## 1. Chain and contracts (BNB Chain mainnet, chain id 56)

| name | address | note |
|---|---|---|
| Portal | `0xe2cE6ab80874Fa9Fa2aAE65D277Dd6B8e65C9De0` | v5.14.16, the launch entry point |
| Standard Token Impl (`tokenImplV2`) | `0x8b4329947e34b6d56d71a3385cac122bade7d78d` | `TOKEN_V2_PERMIT`, vanity suffix **8888** |
| Tax Token V3 Impl (`tokenImplTaxedV3`) | `0x024f18294970B5c76c0691b87f138A0317156422` | `TOKEN_TAXED_V3`, vanity suffix **7777** |
| Tax Token V1 Impl | `0x29e6383F0ce68507b5A72a53c2B118a118332aA8` | legacy, do not use |
| Tax Token V2 Impl | `0xae562c6A05b798499507c6276C6Ed796027807BA` | legacy, do not use |
| Standard Token V3 Impl | `0x88881b6f03090462a969eC7f48385744Eeb63333` | only via `newTokenV7`, suffix 8888 |
| VaultPortal | `0x90497450f2a706f1951b5bdda52B4E5d16f34C06` | tax tokens with vaults; not used here |

Explorer: https://bscscan.com. Token page after launch:
`https://flap.sh/bnb/<tokenAddress>`.

BNB testnet (chain id 97) has its own Portal `0x5bEacaF7ABCbB3aB280e80D007FD31fcE26510e9`,
standard impl `0x87D5f292ba33011997641C7a7Bd2b17799aaA814`, tax V3 impl
`0xE6Ff967a887084c16D0fD71548CF709542cc1557` — the salt must be recomputed
against whichever Portal and impl the launch actually targets.

## 2. The launch flow — three steps, no backend login

Confirmed: the flow is exactly **upload metadata → get an IPFS CID → find a
salt → one `newTokenV6` call**. There is no sign-in, no SIWE, no bearer
token and no backend-issued signature anywhere in it:

- The upload endpoint takes an anonymous multipart GraphQL request. The
  `creator` field in the metadata is documented as the zero address.
- `newTokenV6` is `external payable` on a public contract. The only
  authorisation is the wallet paying gas.
- The only "login" in the whole doc set is the Binance Agentic Wallet
  tutorial, which is about how an agent gets a signer, not about Flap.

The frontend at flap.sh is one client of that contract; nothing in the
protocol requires going through it.

## 3. Metadata upload — `https://funcs.flap.sh/api/upload`

A GraphQL multipart upload (the `graphql-multipart-request-spec` shape):

```
POST https://funcs.flap.sh/api/upload
Content-Type: multipart/form-data

operations = {"query": "mutation Create($file: Upload!, $meta: MetadataInput!) { create(file: $file, meta: $meta) }",
              "variables": {"file": null,
                            "meta": {"description": "...",
                                     "twitter": "<handle or null>",
                                     "telegram": "<handle or null>",
                                     "website": "<url or null>",
                                     "creator": "0x0000000000000000000000000000000000000000"}}}
map        = {"0": ["variables.file"]}
0          = <the image file, e.g. image.png, image/png>
```

Response: `{"data": {"create": "<IPFS CID>"}}`. The CID string goes into
`NewTokenV6Params.meta` as-is. The docs insist on this endpoint: the Flap
indexer and partner terminals only read through Flap's gateway, and the
upload warms their CDN.

`name` and `symbol` are **not** in the upload — they go on-chain in the
`newTokenV6` params. The skill's field table lists them as required only
because the skill needs them for the transaction.

## 4. `newTokenV6` — the unified launch call

```solidity
function newTokenV6(NewTokenV6Params calldata params) external payable returns (address token);
```

Field order as declared in `IPortal.sol` (this is the ABI tuple order):

| # | field | type | standard (non-tax) token value |
|---|---|---|---|
| 1 | name | string | token name |
| 2 | symbol | string | ticker |
| 3 | meta | string | the IPFS CID from the upload |
| 4 | dexThresh | uint8 (DexThreshType) | `1` = FOUR_FIFTHS (the skill's choice; TWO_THIRDS=0, HALF=2, _95_PERCENT=3, _81_PERCENT=4, _1_PERCENT=5) |
| 5 | salt | bytes32 | from flapsalt.py; address must end in 8888 |
| 6 | migratorType | uint8 (MigratorType) | `1` = V2_MIGRATOR (V3_MIGRATOR=0, V4_UNI=2, PCS_INFINITY_CL=3) |
| 7 | quoteToken | address | `0x0` = native BNB |
| 8 | quoteAmt | uint256 | initial buy in wei; `0` = skip |
| 9 | beneficiary | address | the launcher's wallet |
| 10 | permitData | bytes | `0x` |
| 11 | extensionID | bytes32 | 32 zero bytes |
| 12 | extensionData | bytes | `0x` |
| 13 | dexId | uint8 (DEXId) | `0` = DEX0 = PancakeSwap on BSC |
| 14 | lpFeeProfile | uint8 (V3LPFeeProfile) | `0` = LP_FEE_PROFILE_STANDARD |
| 15 | buyTaxRate | uint16 | `0` |
| 16 | sellTaxRate | uint16 | `0` |
| 17 | taxDuration | uint64 | `0` |
| 18 | antiFarmerDuration | uint64 | seconds; the site's form exposes it in days |
| 19 | mktBps | uint16 | `0` |
| 20 | deflationBps | uint16 | `0` |
| 21 | dividendBps | uint16 | `0` |
| 22 | lpBps | uint16 | `0` |
| 23 | minimumShareBalance | uint256 | `0` |
| 24 | dividendToken | address | `0x0` |
| 25 | commissionReceiver | address | `0x0` (must be zero for TOKEN_V2_PERMIT) |
| 26 | tokenVersion | uint8 (TokenVersion) | `2` = TOKEN_V2_PERMIT (TOKEN_TAXED_V3 = `6`) |

`TokenVersion` enum: 0 and 1 legacy, 2 `TOKEN_V2_PERMIT`, 3 `TOKEN_GOPLUS`,
4 `TOKEN_TAXED`, 5 `TOKEN_TAXED_V2`, 6 `TOKEN_TAXED_V3`, 7 `TOKEN_V3_PERMIT`
(7 is only reachable through `newTokenV7`).

The JSON ABI fragment used by the rig (one function, one tuple input):

```json
{"type":"function","name":"newTokenV6","stateMutability":"payable",
 "inputs":[{"name":"params","type":"tuple","components":[
   {"name":"name","type":"string"},{"name":"symbol","type":"string"},
   {"name":"meta","type":"string"},{"name":"dexThresh","type":"uint8"},
   {"name":"salt","type":"bytes32"},{"name":"migratorType","type":"uint8"},
   {"name":"quoteToken","type":"address"},{"name":"quoteAmt","type":"uint256"},
   {"name":"beneficiary","type":"address"},{"name":"permitData","type":"bytes"},
   {"name":"extensionID","type":"bytes32"},{"name":"extensionData","type":"bytes"},
   {"name":"dexId","type":"uint8"},{"name":"lpFeeProfile","type":"uint8"},
   {"name":"buyTaxRate","type":"uint16"},{"name":"sellTaxRate","type":"uint16"},
   {"name":"taxDuration","type":"uint64"},{"name":"antiFarmerDuration","type":"uint64"},
   {"name":"mktBps","type":"uint16"},{"name":"deflationBps","type":"uint16"},
   {"name":"dividendBps","type":"uint16"},{"name":"lpBps","type":"uint16"},
   {"name":"minimumShareBalance","type":"uint256"},{"name":"dividendToken","type":"address"},
   {"name":"commissionReceiver","type":"address"},{"name":"tokenVersion","type":"uint8"}]}],
 "outputs":[{"name":"token","type":"address"}]}
```

Tax tokens (`tokenVersion = 6`) additionally need at least one non-zero tax
rate, `mktBps + deflationBps + dividendBps + lpBps == 10000`, and
`migratorType = V2_MIGRATOR`. Not used by the first rig.

## 5. Cost

**There is no fixed creation fee on BNB Chain — confirmed on chain.** Both
the launch guide and the skill's `construct-tx.md` set `msg.value = quoteAmt`
— the optional initial buy — and `0` to skip it. `preflight.md` budgets
"~0.002–0.010 BNB in gas" and asks for a 0.01 BNB balance before launching.

`IPortal.sol` declares an `InsufficientCreationFee(uint256 required,
uint256 provided)` error, so the contract *can* enforce a fee. `bscdryrun.py`
therefore `eth_call`s a real launch payload with `value = 0`. Measured
2026-09-11 against the mainnet Portal, from a wallet with zero balance:

| | |
|---|---|
| `eth_call` newTokenV7, value 0 | **accepted** — returns the predicted token address |
| `eth_estimateGas` | **2,096,412** units |
| gas price at the time | 0.05 gwei (BNB Chain's floor since 2025) |
| gas cost at that price | ≈ 0.000105 BNB |
| gas cost if price spikes to 1 gwei | ≈ 0.0021 BNB |

The 0.0002 BNB figure elsewhere in the full docs is the **Trigger Service**
fee, unrelated to token creation.

## 5a. What the BNB mainnet Portal actually accepts today (probed 2026-09-11)

Every shape below was sent as `eth_call` from the fly's wallet; nothing was
broadcast. The revert names come from hashing the `error` declarations in
`IPortal.sol`.

| entry point | tokenVersion | migrator | fee mode | result |
|---|---|---|---|---|
| newTokenV6 | TOKEN_V2_PERMIT (2) | V2 / V3, any dexThresh | — | **FeatureDisabled()** |
| newTokenV6 | TOKEN_TAXED_V3 (6) | V2_MIGRATOR | mktBps 10000, 3 % / 3 % | accepted |
| newTokenV7 | TOKEN_V3_PERMIT (7) | PCS_INFINITY_CL | MARKETING_OR_VAULT 10000 | NewTokenV7RuleViolation(8) |
| newTokenV7 | TOKEN_V3_PERMIT (7) | V2_MIGRATOR | DIVIDEND 10000 | NewTokenV7RuleViolation(7) |
| newTokenV7 | TOKEN_V3_PERMIT (7) | PCS_INFINITY_CL | DIVIDEND 10000, minimumShareBalance < 10,000 tokens | MinimumShareBalanceTooLow() |
| newTokenV7 | TOKEN_V3_PERMIT (7) | PCS_INFINITY_CL | DIVIDEND 10000, dividendToken = quote (0x0), **minimumShareBalance ≥ 10,000 × 1e18** | **accepted** |

So the documented "standard token via newTokenV6" path is switched off on
BNB mainnet, exactly as the docs say it is on Robinhood Chain, and Flap's own
skill notes that "standard (non-tax) token launches are no longer supported"
through it. The live non-tax path is `newTokenV7` in the dividend mode — which
is what the site's own banner describes: "Flap non-tax tokens use DEX LP fees
to reward holders in the quote token". The threshold sits between 1,000 and
10,000 tokens; the rig uses 10,000 (`FLY_FLAP_MIN_SHARE`).

The `newTokenV7` ABI tuple, in declaration order:
`name string, symbol string, meta string, dexThresh uint8, salt bytes32,
migratorType uint8, quoteToken address, quoteAmt uint256, permitData bytes,
extensionID bytes32, extensionData bytes, dexId uint8, buyTaxRate uint16,
sellTaxRate uint16, taxDuration uint64, antiFarmerDuration uint64,
commissionReceiver address, tokenVersion uint8, feeConfigs (uint8 feeType,
uint16 bps, address marketingAddress, address dividendToken, uint256
minimumShareBalance)[4]`. Selector `0x87ef5b30`. `newTokenV6` is `0x8cb5772c`.
The salt for TOKEN_V3_PERMIT is computed against the **Standard Token V3
Impl** `0x88881b6f03090462a969eC7f48385744Eeb63333`, suffix 8888.

Selectors seen: `ac5f6092 FeatureDisabled`, `16fba6af NewTokenV7RuleViolation`,
`6b9099a1 MinimumShareBalanceTooLow`, `df3a6581 MetaAlreadyUsedByOtherToken`,
`a7382e9b RateLimitExceeded`, `273cc575 InsufficientCreationFee`.

## 6. CREATE2 address prediction and the salt

The Portal deploys each token as an EIP-1167 minimal proxy through CREATE2.
Init code is

```
3d602d80600a3d3981f3363d3d373d3d3d363d73 <impl, 20 bytes> 5af43d82803e903d91602b57fd5bf3
```

and the address is `keccak(0xff ++ Portal ++ salt ++ keccak(initcode))[12:]`.
The deployer is **always the Portal**, even for VaultPortal launches. Search:
`salt = keccak(seed)`, then `salt = keccak(salt)` until the predicted address
ends in `8888` (standard) or `7777` (tax). Any 32-byte random seed works; the
docs use a throwaway private key only as a convenient random value.

`flapsalt.py` implements this. Measured on this machine: ~130,000 keccak/s in
pure Python, average ~72,000 iterations → **about 0.5 s per salt**, worst of
ten runs 1.3 s.

`lockSalt(salt, tokenVersion)` can reserve a predicted address for a fee
(`SALT_LOCK_FEE`); the site calls it "保留 CA". Not needed for a launch.

## 7. Contract-side limits that affect testing

- `MetaAlreadyUsedByOtherToken(string meta)` — the same CID cannot be used
  twice. Since the CID is a content hash of the image plus metadata JSON, the
  **description (or image) must differ for every test launch**.
- `RateLimitExceeded(address user, uint256 lastCreationTime)` — one wallet
  cannot create tokens back to back. The interval is **not stated** in the
  docs or the interface (there is no getter), so leave a generous gap between
  launches from one wallet; the rig refuses a second live launch inside a
  configurable cooldown.
- `SpammerBlocked(address user)` — a wallet the team has flagged is blocked
  permanently. Do not probe the rate limit to find its edge.
- `InsufficientCreationFee` / `InsufficientFee` — see §5.

## 8. The website's create page (observed 2026-09-11)

- URL: `https://flap.sh/create` (`?lang=en` / `?lang=zh`). `/bnb/create`
  is a 404. The header's "Create token" button opens a drawer with
  "Create no-tax token" / "Create tax token"; both land on `/create`.
- The page is **dark by default**: `<html class="dark">` with a black
  `documentElement` background; `body` itself is transparent, so a
  luma check must read `document.documentElement`, not `body`.
- Form fields have stable ids and no placeholders: `#image` (file),
  `#name`, `#symbol`, `#description` (textarea), `#creator-purchase-amount`
  (the initial buy, placeholder `0`), `#antiFarmerDays`, `#telegram`,
  `#twitter`, `#github`, `#youtube`, `#debox`, `#website`.
- The submit is a single `button[type=submit]` (label "Create token" /
  "創建代幣"), full-width-ish (240 px) at the bottom of the form. There is a
  quote-token selector (BNB / USDT / USD1 / BTCB / SOL / ETH ...) defaulting
  to BNB, and no terms gate on the create page.
- Wallet: the site discovers the injected provider over EIP-6963 and lists it
  under "installed" in its wallet dialog; with the provider present at page
  load it **auto-connects** and shows the address in the header. The connect
  makes only `eth_chainId`, `eth_accounts`, `wallet_requestPermissions` and
  `eth_requestAccounts` — **no `personal_sign`, no login**.
- One trap: with `isMetaMask: true` on the provider, the page freezes a
  headless Chromium renderer ~6 s after load (bisected: the flag plus the
  6963 announcement; either alone is fine). `rhprovider.attach(...,
  is_metamask=False)` avoids it and the site still connects.
- After `set_input_files` on `#image` the site opens an **"Adjust image"**
  crop dialog; "Use This Image" must be clicked or every later click lands
  on the dialog.
- The page scrolls an inner container, not the window, so `window.scrollTo`
  does nothing; the rig scrolls the nearest `overflow-y: auto` ancestor.

## 9. What is different from pons, in one list

| pons (rhlive.py) | Flap (flaplive.py) |
|---|---|
| terms / privacy / jurisdiction gate | none seen |
| theme toggle that had to be measured and flipped | dark by default |
| paired-asset menu, 57 tokenised equities | quote-token buttons, BNB default, left alone |
| "Advanced" panel with creator tax | no-tax token: nothing to open |
| placeholder-only field handles | stable element ids |
| launch fee 0.0005 ETH + gas | no fixed fee documented; gas only (see §5) |
| site button → one `eth_sendTransaction` | same, if the site sees the injected wallet; else direct `newTokenV6` |
