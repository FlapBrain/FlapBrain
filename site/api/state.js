// Same-origin proxy to a BNB Chain node.
//
// The page talks only to its own origin; this runs server-side where CORS
// does not apply, and reads. There is no key here and no method in the
// allowlist that writes.
//
// Before the launch FLY_TOKEN is unset: the answer then carries
// `launched: false` and `token: null`, and the page shows placeholders.

const RPC = process.env.FLY_BSC_RPC || 'https://bsc-dataseed.binance.org';
const TOKEN = (process.env.FLY_TOKEN || '').trim().toLowerCase();
const WALLET = process.env.FLY_WALLET || '';
const BIRTH = process.env.FLY_TOKEN_BLOCK || '0x0';
const TRANSFER = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef';
// gas only: Flap charges no fixed creation fee on BNB Chain (docs/flap.md)
const LAUNCH_COST_BNB = Number(process.env.FLY_LAUNCH_COST_BNB || '0.001');

let holdersCache = { at: 0, holders: null, transfers: null };
const HOLD_TTL = 120000;

async function rpc(method, params) {
  const r = await fetch(RPC, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }),
  });
  const j = await r.json();
  if (j.error) throw new Error(j.error.message || 'rpc error');
  return j.result;
}

const int = (h) => (h ? parseInt(h, 16) : 0);

function abiString(x) {
  if (!x || x.length < 130) return '';
  const n = parseInt(x.slice(66, 130), 16);
  let out = '';
  for (let i = 0; i < n; i++) out += String.fromCharCode(parseInt(x.substr(130 + i * 2, 2), 16));
  return out;
}

async function holders() {
  const now = Date.now();
  if (holdersCache.holders != null && now - holdersCache.at < HOLD_TTL) return holdersCache;
  try {
    const logs = await rpc('eth_getLogs', [{
      address: TOKEN, fromBlock: BIRTH, toBlock: 'latest', topics: [TRANSFER],
    }]);
    const seen = new Set();
    for (const l of logs) if (l.topics.length >= 3) seen.add('0x' + l.topics[2].slice(-40));
    seen.delete('0x' + '0'.repeat(40));
    holdersCache = { at: now, holders: seen.size, transfers: logs.length };
  } catch (e) { /* keep the last good numbers */ }
  return holdersCache;
}

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 's-maxage=15, stale-while-revalidate=60');
  try {
    const blk = await rpc('eth_blockNumber', []);
    const out = {
      ok: true,
      chain: { name: 'BNB Chain', id: 56 },
      block: int(blk),
      launched: !!TOKEN,
      wallet: null,
      token: null,
      updated: Math.floor(Date.now() / 1000),
    };
    if (WALLET) {
      const bal = await rpc('eth_getBalance', [WALLET, 'latest']);
      const bnb = int(bal) / 1e18;
      out.wallet = { address: WALLET, bnb, launches_left: Math.floor(bnb / LAUNCH_COST_BNB) };
    }
    if (TOKEN) {
      const [sup, sym, nm] = await Promise.all([
        rpc('eth_call', [{ to: TOKEN, data: '0x18160ddd' }, 'latest']),
        rpc('eth_call', [{ to: TOKEN, data: '0x95d89b41' }, 'latest']),
        rpc('eth_call', [{ to: TOKEN, data: '0x06fdde03' }, 'latest']),
      ]);
      const h = await holders();
      out.token = {
        address: TOKEN,
        name: abiString(nm),
        symbol: abiString(sym),
        supply: Number(BigInt(sup)) / 1e18,
        holders: h.holders,
        transfers: h.transfers,
        pair: 'BNB',
        creator_tax_pct: 0,
        url: 'https://flap.sh/bnb/' + TOKEN,
        explorer: 'https://bscscan.com/token/' + TOKEN,
      };
    }
    res.status(200).json(out);
  } catch (e) {
    res.status(200).json({ ok: false, error: String(e.message || e).slice(0, 160) });
  }
}
