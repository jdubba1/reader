// Isolated-world bridge: relays page-world captures to the service worker and
// owns dwell tracking (which needs the rendered DOM, not the JSON).
(() => {
  if (window.__readerContentLoaded) return;
  window.__readerContentLoaded = true;

  const CHANNEL = 'reader-indexer';
  const DWELL_MS = 1800; // read, not scrolled past
  const VISIBLE_FRACTION = 0.5;

  const relay = (type, payload) => {
    try { chrome.runtime.sendMessage({ type, payload }); } catch {}
  };

  window.addEventListener('message', (e) => {
    if (e.source !== window || e.data?.source !== CHANNEL) return;
    const { kind, payload } = e.data;
    if (typeof kind !== 'string' || !payload) return;
    if (kind === 'posts') relay('posts', payload);
    else if (kind === 'engaged') relay('signal', { id: payload.id, tier: payload.tier });
  });

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg?.type === 'ping') {
      sendResponse({ ok: true }); // popup uses this to detect a stale tab
    }
  });

  // Dwell tracking. An article enters view, we start a clock; if it survives
  // DWELL_MS at half visibility it counts as viewed.
  const timers = new WeakMap();
  const marked = new Set();

  const idOf = (article) => {
    for (const a of article.querySelectorAll('a[href*="/status/"]')) {
      const m = a.getAttribute('href')?.match(/^\/[^/]+\/status\/(\d+)$/);
      if (m) return m[1];
    }
    return null;
  };

  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        const el = entry.target;
        if (entry.isIntersecting && entry.intersectionRatio >= VISIBLE_FRACTION) {
          if (timers.has(el)) continue;
          timers.set(el, setTimeout(() => {
            const id = idOf(el);
            if (id && !marked.has(id)) {
              marked.add(id);
              relay('signal', { id, tier: 'viewed' });
            }
          }, DWELL_MS));
        } else {
          clearTimeout(timers.get(el));
          timers.delete(el);
        }
      }
    },
    { threshold: [VISIBLE_FRACTION] }
  );

  const scan = () => {
    for (const a of document.querySelectorAll('article[data-testid="tweet"]')) {
      if (!a.__readerObserved) { a.__readerObserved = true; observer.observe(a); }
    }
  };

  new MutationObserver(scan).observe(document.documentElement, { childList: true, subtree: true });
  scan();
})();
