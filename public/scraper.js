(async function () {
  if (document.getElementById('rws-ov')) return;

  const ov = document.createElement('div');
  ov.id = 'rws-ov';
  Object.assign(ov.style, {
    position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
    background: 'rgba(0,0,0,0.88)', color: '#fff', zIndex: 999999,
    padding: '20px', fontFamily: 'monospace', fontSize: '13px',
    overflowY: 'auto', whiteSpace: 'pre-wrap', lineHeight: '1.5',
  });
  ov.innerHTML =
    '<button onclick="document.getElementById(\'rws-ov\').remove()" ' +
    'style="float:right;background:#cc0000;color:#fff;border:none;padding:6px 14px;cursor:pointer;border-radius:4px;font-size:14px">✕</button>' +
    '<b>🔍 REWE Sticker Scraper</b>\n\n';
  document.body.appendChild(ov);

  const log = t => { ov.innerHTML += t + '\n'; ov.scrollTop = ov.scrollHeight; };

  const PRODUCTS = {
    '9444915': { name: 'Einzelpacket (7 Sticker)',          url: '/produkte/panini-fifa-world-cup-2026-stickerpacket/9444915' },
    '9446617': { name: 'Multipack (5 Tüten + 6 Sticker)',   url: '/produkte/panini-fifa-world-cup-2026-sammelsticker-multipack-5-tueten-6-sticker/9446617' },
    '7353919': { name: 'Mini-Multipack (4 Tüten + 4 Sticker)', url: '/produkte/panini-fifa-world-cup-2026-sammelsticker-mini-multipack-4-tueten-4-sticker/7353919' },
    '9443316': { name: 'Eco Blister (6 Tüten + 1 DFB)',     url: '/produkte/panini-fifa-world-cup-2026-sammelsticker-eco-blister-6-tueten-1-dfb-sticker/9443316' },
  };
  const AVAIL_RE = /availability:\s*"([^"]+)"/;

  log('Lade Filialen...');
  let stores;
  try {
    stores = await fetch(
      'https://raw.githubusercontent.com/thesolofoundr/rewe-sticker-map/main/public/stores.json'
    ).then(r => r.json());
  } catch (e) {
    log('❌ Konnte Filialen nicht laden: ' + e); return;
  }
  log(stores.length + ' Filialen geladen. Starte...\n');

  const results = [];
  let inStock = 0;
  const t0 = Date.now();

  for (let i = 0; i < stores.length; i++) {
    const store = stores[i];

    const sm = await fetch('/api/wksmarketselection/userselections', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ selectedService: 'STATIONARY', customerZipCode: null, wwIdent: store.id }),
    }).catch(() => null);

    const productAvail = {};
    if (sm && sm.ok) {
      for (const [pid, info] of Object.entries(PRODUCTS)) {
        try {
          const r = await fetch(info.url, { credentials: 'include' });
          if (r.ok) {
            const html = await r.text();
            const m = html.match(AVAIL_RE);
            productAvail[pid] = m ? m[1] === 'true' : null;
          } else {
            productAvail[pid] = null;
          }
        } catch { productAvail[pid] = null; }
      }
    } else {
      for (const pid of Object.keys(PRODUCTS)) productAvail[pid] = null;
    }

    const anyInStock = Object.values(productAvail).some(v => v === true);
    if (anyInStock) {
      inStock++;
      const names = Object.entries(productAvail)
        .filter(([, v]) => v === true)
        .map(([id]) => PRODUCTS[id].name);
      log('✅ [' + (i + 1) + '/' + stores.length + '] ' + (store.address || store.id) + ': ' + names.join(', '));
    } else if ((i + 1) % 20 === 0) {
      const elapsed = Math.round((Date.now() - t0) / 1000);
      const eta = Math.round((elapsed / (i + 1)) * (stores.length - i - 1));
      log('⏳ [' + (i + 1) + '/' + stores.length + '] läuft... (~' + eta + 's verbleibend)');
    }

    results.push({ ...store, available: anyInStock, products: productAvail });
  }

  const elapsed = Math.round((Date.now() - t0) / 1000);
  log('\n✅ Fertig in ' + elapsed + 's! ' + inStock + '/' + stores.length + ' Filialen mit Stickern vorrätig.');
  log('Speichere Ergebnisse...\n');

  const output = {
    updated: new Date().toISOString(),
    products: Object.fromEntries(Object.entries(PRODUCTS).map(([k, v]) => [k, v.name])),
    stores: results,
  };

  // 1) Try Vercel endpoint (has GITHUB_TOKEN server-side)
  let saved = false;
  try {
    const r = await fetch('https://rewe-sticker-map.vercel.app/api/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(output),
    });
    let d = {};
    try { d = await r.json(); } catch {}
    if (r.ok && d.ok) {
      log('✅ Gespeichert via Vercel! Karte aktualisiert sich in ~1 Minute.');
      saved = true;
    } else {
      log('⚠️  Vercel-Endpunkt: HTTP ' + r.status + ' – ' + JSON.stringify(d));
    }
  } catch (e) {
    log('⚠️  Vercel-Fetch fehlgeschlagen: ' + e);
  }

  // Fallback: download the file
  if (!saved) {
    const blob = new Blob([JSON.stringify(output, null, 2)], { type: 'application/json' });
    const a = Object.assign(document.createElement('a'), {
      href: URL.createObjectURL(blob),
      download: 'availability.json',
    });
    document.body.appendChild(a);
    a.click();
    a.remove();
    log('📁 availability.json heruntergeladen.');
    log('→ github.com/thesolofoundr/rewe-sticker-map → public/availability.json');
    log('→ Stift-Icon (Edit) → Inhalt ersetzen → "Commit changes"');
  }
}());
