// The admin API behind /admin.
//
// Everything the site shows about the launch lives in site/web/live.json in
// the public repo: the token contract, the launch state and banner, the
// stream address. This function reads and writes that one file through the
// GitHub API, and can ask Vercel to redeploy through a deploy hook. It holds
// no chain key and cannot sign anything.
//
// Environment (set on the Vercel project):
//   ADMIN_TOKEN       the password typed into /admin
//   GITHUB_TOKEN      a token with contents:write on the repo below
//   GITHUB_REPO       owner/name, default FlapBrain/FlapBrain
//   DEPLOY_HOOK_URL   the project's deploy hook (main branch)

import { timingSafeEqual, createHmac } from 'node:crypto';
import { verifyMessage } from 'ethers';

const REPO = process.env.GITHUB_REPO || 'FlapBrain/FlapBrain';
const PATH = 'site/web/live.json';
const API = `https://api.github.com/repos/${REPO}/contents/${PATH}`;

// Two ways in: the ADMIN_TOKEN password, or a session minted by signing a
// message with the launch wallet (ADMIN_WALLET). Sessions are stateless:
// HMAC(address|expiry) keyed with ADMIN_TOKEN, valid for 12 hours.
const SESSION_H = 12 * 3600 * 1000;
const NONCE_MS = 5 * 60 * 1000;

function hmac(s) { return createHmac('sha256', process.env.ADMIN_TOKEN || 'x').update(s).digest('hex'); }
function safeEq(a, b) {
  const A = Buffer.from(String(a)), B = Buffer.from(String(b));
  return A.length === B.length && timingSafeEqual(A, B);
}

function authed(req) {
  const want = process.env.ADMIN_TOKEN || '';
  const got = String(req.headers['x-admin-token'] || '');
  if (!want) return false;
  if (safeEq(want, got)) return true;
  // session: "s.<address>.<exp>.<sig>"
  const m = /^s\.(0x[0-9a-f]{40})\.(\d+)\.([0-9a-f]{64})$/i.exec(got);
  if (!m) return false;
  const [, addr, exp, sig] = m;
  if (Number(exp) < Date.now()) return false;
  if (addr.toLowerCase() !== String(process.env.ADMIN_WALLET || '').toLowerCase()) return false;
  return safeEq(sig, hmac(`session|${addr.toLowerCase()}|${exp}`));
}

// The message the wallet signs. Includes a server-issued nonce (an HMAC of
// the timestamp, so nothing has to be stored) and expires in five minutes.
function loginMessage(addr, ts, nonce) {
  return `FlapBrain admin login\n\nwallet: ${addr}\ntime: ${ts}\nnonce: ${nonce}\n\nSigning this costs nothing and sends no transaction.`;
}

async function gh(method, body) {
  const r = await fetch(API + '?ref=main', {
    method,
    headers: {
      Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
      Accept: 'application/vnd.github+json',
      'Content-Type': 'application/json',
      'User-Agent': 'flybrain-admin',
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(`${method} ${r.status}: ${(j.message || '').slice(0, 160)}`);
  return j;
}

async function readLive() {
  const j = await gh('GET');
  const text = Buffer.from(j.content, 'base64').toString('utf8');
  return { sha: j.sha, data: JSON.parse(text) };
}

const ADDR = /^0x[0-9a-fA-F]{40}$/;
const STATES = new Set(['not_launched', 'launching', 'launched']);

function merge(cur, patch) {
  const out = { ...cur, launch: { ...(cur.launch || {}) } };
  if ('stream' in patch) out.stream = patch.stream ? String(patch.stream).trim() : null;
  if ('stream' in patch) out.at = out.stream ? Math.floor(Date.now() / 1000) : 0;
  const L = patch.launch || {};
  if ('contract' in L) {
    const c = String(L.contract || '').trim();
    if (c && !ADDR.test(c)) throw new Error('contract must be a 0x… address (40 hex)');
    out.launch.contract = c ? c.toLowerCase() : '';
  }
  if ('block' in L) {
    const b = String(L.block || '').trim();
    if (b && !/^\d+$/.test(b) && !/^0x[0-9a-fA-F]+$/.test(b)) throw new Error('block must be a number');
    out.launch.block = b;
  }
  if ('state' in L) {
    if (!STATES.has(L.state)) throw new Error('state must be not_launched | launching | launched');
    out.launch.state = L.state;
  }
  if ('banner' in L) out.launch.banner = String(L.banner || '').slice(0, 160);
  if ('url' in L) out.launch.url = String(L.url || '').trim().slice(0, 300);
  if ('token_page' in L) out.launch.token_page = String(L.token_page || '').trim().slice(0, 300);
  if ('tx' in L) {
    const t = String(L.tx || '').trim();
    if (t && !/^0x[0-9a-fA-F]{64}$/.test(t)) throw new Error('tx must be a 0x… transaction hash (64 hex)');
    out.launch.tx = t;
  }
  if ('step' in L) {
    const st = String(L.step || '').trim();
    if (st && !/^\d{1,2}$/.test(st)) throw new Error('step must be a number');
    out.launch.step = st;
  }
  // the launch button writes a command; the agent on the launch PC clears
  // it and writes back what it did
  if ('command' in L) {
    const c = String(L.command || '');
    if (!['', 'launch', 'rehearse'].includes(c)) throw new Error('command must be launch | rehearse');
    out.launch.command = c;
    if (c) out.launch.command_at = Math.floor(Date.now() / 1000);
  }
  if ('agent' in L) { out.launch.agent = String(L.agent || '').slice(0, 200); out.launch.agent_at = Math.floor(Date.now() / 1000); }
  return out;
}

export default async function handler(req, res) {
  res.setHeader('Cache-Control', 'no-store');
  if (req.method !== 'POST') return res.status(405).json({ ok: false, error: 'POST only' });
  const body = typeof req.body === 'string' ? JSON.parse(req.body || '{}') : (req.body || {});
  const action = body.action;

  // --- wallet login, no token needed for these two ------------------------
  if (action === 'nonce') {
    const addr = String(body.address || '').toLowerCase();
    if (!/^0x[0-9a-f]{40}$/.test(addr)) return res.status(200).json({ ok: false, error: 'address?' });
    const ts = Date.now();
    const nonce = hmac(`nonce|${addr}|${ts}`).slice(0, 16);
    return res.status(200).json({ ok: true, ts, nonce, message: loginMessage(addr, ts, nonce),
      wallet: String(process.env.ADMIN_WALLET || '').toLowerCase() });
  }
  if (action === 'login') {
    try {
      const addr = String(body.address || '').toLowerCase();
      const ts = Number(body.ts), nonce = String(body.nonce || '');
      if (!/^0x[0-9a-f]{40}$/.test(addr)) throw new Error('address?');
      if (!(Date.now() - ts < NONCE_MS && Date.now() - ts >= 0)) throw new Error('login expired, try again');
      if (!safeEq(nonce, hmac(`nonce|${addr}|${ts}`).slice(0, 16))) throw new Error('bad nonce');
      const want = String(process.env.ADMIN_WALLET || '').toLowerCase();
      if (!want) throw new Error('ADMIN_WALLET is not set on the project');
      if (addr !== want) throw new Error(`this wallet (${addr.slice(0, 6)}…${addr.slice(-4)}) is not the launch wallet`);
      const recovered = verifyMessage(loginMessage(addr, ts, nonce), String(body.signature || '')).toLowerCase();
      if (recovered !== addr) throw new Error('signature does not match the wallet');
      const exp = Date.now() + SESSION_H;
      const token = `s.${addr}.${exp}.${hmac(`session|${addr}|${exp}`)}`;
      return res.status(200).json({ ok: true, token, exp, address: addr });
    } catch (e) {
      return res.status(200).json({ ok: false, error: String(e.message || e).slice(0, 160) });
    }
  }

  if (!authed(req)) return res.status(401).json({ ok: false, error: 'bad token' });
  try {
    if (action === 'get') {
      const { data } = await readLive();
      return res.status(200).json({ ok: true, live: data, repo: REPO,
        deploy_hook: !!process.env.DEPLOY_HOOK_URL });
    }
    if (action === 'save') {
      const { sha, data } = await readLive();
      const next = merge(data, body.patch || {});
      const content = Buffer.from(JSON.stringify(next, null, 1) + '\n', 'utf8').toString('base64');
      const who = body.note ? ` (${String(body.note).slice(0, 60)})` : '';
      const j = await gh('PUT', {
        message: `admin: update live.json${who}`,
        content, sha, branch: 'main',
      });
      return res.status(200).json({ ok: true, live: next, commit: j.commit && j.commit.sha });
    }
    if (action === 'deploy') {
      // Preferred: a Vercel deploy hook, if the project is git-connected.
      const hook = process.env.DEPLOY_HOOK_URL;
      if (hook) {
        const r = await fetch(hook, { method: 'POST' });
        const j = await r.json().catch(() => ({}));
        return res.status(200).json({ ok: r.ok, via: 'hook', job: j.job || j });
      }
      // Otherwise: the repo's own workflow (.github/workflows/deploy.yml),
      // which runs `vercel deploy --prod` with the repo's secrets.
      const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/deploy.yml/dispatches`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
                   Accept: 'application/vnd.github+json', 'User-Agent': 'flybrain-admin',
                   'Content-Type': 'application/json' },
        body: JSON.stringify({ ref: 'main', inputs: { reason: String(body.note || 'admin button').slice(0, 60) } }),
      });
      if (r.status !== 204) {
        const j = await r.json().catch(() => ({}));
        return res.status(200).json({ ok: false, error: `dispatch ${r.status}: ${(j.message || '').slice(0, 160)}` });
      }
      return res.status(200).json({ ok: true, via: 'workflow' });
    }
    if (action === 'status') {
      const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/deploy.yml/runs?per_page=5`, {
        headers: { Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
                   Accept: 'application/vnd.github+json', 'User-Agent': 'flybrain-admin' },
      });
      const j = await r.json().catch(() => ({}));
      const runs = (j.workflow_runs || []).map(w => ({
        id: w.id, status: w.status, conclusion: w.conclusion,
        started: w.run_started_at, url: w.html_url, event: w.event }));
      return res.status(200).json({ ok: r.ok, runs });
    }
    return res.status(400).json({ ok: false, error: 'unknown action' });
  } catch (e) {
    return res.status(200).json({ ok: false, error: String(e.message || e).slice(0, 200) });
  }
}
