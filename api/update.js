export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', 'https://www.rewe.de');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') return res.status(204).end();
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const token = process.env.GITHUB_TOKEN;
  if (!token) return res.status(500).json({ error: 'No token configured' });

  const owner = 'thesolofoundr';
  const repo  = 'rewe-sticker-map';
  const path  = 'public/availability.json';
  const api   = `https://api.github.com/repos/${owner}/${repo}/contents/${path}`;
  const headers = {
    Authorization: `Bearer ${token}`,
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    'Content-Type': 'application/json',
  };

  // Get current file SHA
  const getRes = await fetch(api, { headers });
  if (!getRes.ok && getRes.status !== 404) {
    return res.status(502).json({ error: 'GitHub GET failed', status: getRes.status });
  }
  const sha = getRes.ok ? (await getRes.json()).sha : undefined;

  // Encode new content
  const content = Buffer.from(JSON.stringify(req.body, null, 2), 'utf8').toString('base64');

  const body = {
    message: `chore: update availability ${new Date().toISOString().slice(11, 16)} UTC`,
    content,
    ...(sha ? { sha } : {}),
  };

  const putRes = await fetch(api, { method: 'PUT', headers, body: JSON.stringify(body) });
  if (!putRes.ok) {
    const err = await putRes.text();
    return res.status(502).json({ error: 'GitHub PUT failed', status: putRes.status, detail: err });
  }

  return res.status(200).json({ ok: true });
}
