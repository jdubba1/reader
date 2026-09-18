// Service worker: buffers captures and ships them to the local daemon.
//
// MV3 terminates this worker after ~30s idle, so nothing may live only in
// memory: the queue and stats are mirrored to chrome.storage and reloaded on
// every wake, and the flush timer is an alarm rather than setInterval.
const ENDPOINT = 'http://127.0.0.1:8787/ingest';
const FLUSH_AT = 100;
const MAX_QUEUE = 5000;
const MAX_QUEUE_BYTES = 6 * 1024 * 1024;
const bytes = value => new TextEncoder().encode(JSON.stringify(value)).length;

const EMPTY = { posts: [], signals: [] };
let pending = Promise.resolve();
const serial = (work) => {
  const result = pending.then(work);
  pending = result.catch(() => {});
  return result;
};

const ZERO = { posts: 0, signals: 0, flushed: 0, lastError: null };

async function load() {
  const s = await chrome.storage.local.get(['queue', 'stats']);
  return { queue: s.queue || structuredClone(EMPTY), stats: s.stats || structuredClone(ZERO) };
}

const save = (queue, stats) => chrome.storage.local.set({ queue, stats });

async function flush() {
  const { queue, stats } = await load();
  if (!queue.posts.length && !queue.signals.length) return;

  const batch = bytes(queue) > 4 * 1024 * 1024
    ? {posts: queue.posts.slice(0, 100), signals: queue.signals.slice(0, 100)} : queue;
  // Keep the persisted batch until the daemon acknowledges it.
  try {
    const r = await fetch(ENDPOINT, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(batch),
      signal: AbortSignal.timeout(5000),
    });
    if (!r.ok) throw new Error(`daemon ${r.status}`);
    const ack = await r.json();
    if (ack.ok !== true || typeof ack.posts !== 'number') throw Error('Unexpected companion response');
    stats.flushed += batch.posts.length + batch.signals.length;
    stats.lastError = null;
    stats.lastFlush = new Date().toISOString();
    await save({posts: queue.posts.slice(batch.posts.length), signals: queue.signals.slice(batch.signals.length)}, stats);
  } catch (e) {
    stats.lastError = String(e.message || e);
    await save(queue, stats);
  }
}

async function enqueue(fn) {
  const { queue, stats } = await load();
  fn(queue, stats);
  // Stay below Chrome's storage quota even when posts contain long bodies.
  let size = bytes(queue);
  while (size > MAX_QUEUE_BYTES && (queue.posts.length || queue.signals.length)) {
    const removed = queue.posts.length ? queue.posts.shift() : queue.signals.shift();
    size -= bytes(removed); // Leave comma overhead in the estimate to stay conservative.
    stats.dropped = (stats.dropped || 0) + 1;
  }
  await save(queue, stats);
  if (queue.posts.length + queue.signals.length >= FLUSH_AT) await flush();
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (sender.id !== chrome.runtime.id) return;
  // Only our extension pages can change settings or erase data. Page scripts
  // can relay captures, but cannot impersonate the archive controls.
  const control = sender.url?.startsWith(chrome.runtime.getURL(''));
  if (msg?.type === 'get-stats') {
    Promise.all([load(), chrome.storage.local.get(['enabled', 'consented', 'deletePending'])])
      .then(([{queue, stats}, settings]) => sendResponse({...stats, ...settings,
        queuedPosts: queue.posts.length, queuedSignals: queue.signals.length}));
    return true;
  }
  if (control && ['set-enabled', 'flush', 'delete'].includes(msg?.type)) {
    serial(async () => {
      if (msg.type === 'set-enabled') {
        const {deletePending} = await chrome.storage.local.get('deletePending');
        if (deletePending) throw Error('Finish deleting your archive before resuming capture.');
        await chrome.storage.local.set({enabled: msg.enabled === true, consented: true});
      } else if (msg.type === 'flush') {
        await flush();
      } else {
        // Persist the pause and discard the queue before deleting the database.
        // A failed request stays paused and retryable across worker restarts.
        await chrome.storage.local.set({enabled: false, deletePending: true,
          queue: structuredClone(EMPTY), stats: structuredClone(ZERO)});
        const response = await fetch(ENDPOINT.replace('/ingest', '/delete'), {
          method: 'POST', headers: {'content-type': 'application/json'},
          body: JSON.stringify({confirm: 'delete-reader-x'}), signal: AbortSignal.timeout(30000),
        });
        if (!response.ok || (await response.json()).ok !== true) throw Error('Archive deletion failed. Reconnect and retry deletion.');
        await chrome.storage.local.set({deletePending: false});
      }
    }).then(() => sendResponse({ok: true}), error => sendResponse({error: String(error.message || error)}));
    return true;
  }
  if (!['posts', 'signal'].includes(msg?.type)) return;
  serial(async () => {
    const {enabled, deletePending} = await chrome.storage.local.get(['enabled', 'deletePending']);
    if (!enabled || deletePending) return;
    if (msg.type === 'posts') {
      if (!Array.isArray(msg.payload?.posts)) return;
      await enqueue((q, s) => {
        for (const p of msg.payload.posts) {
          q.posts.push({ ...p, source: 'x', tier: msg.payload.tier, op: msg.payload.op });
        }
        s.dropped = (s.dropped || 0) + Math.max(0, q.posts.length - MAX_QUEUE);
        q.posts = q.posts.slice(-MAX_QUEUE);
        s.posts += msg.payload.posts.length;
        if (msg.payload.posts.length) s.lastCapture = new Date().toISOString();
      });
    } else if (msg.type === 'signal') {
      if (!msg.payload?.id) return;
      await enqueue((q, s) => {
        q.signals.push({ ...msg.payload, source: 'x', at: new Date().toISOString() });
        s.dropped = (s.dropped || 0) + Math.max(0, q.signals.length - MAX_QUEUE);
        q.signals = q.signals.slice(-MAX_QUEUE);
        s.signals += 1;
      });
    }
  }).then(() => sendResponse({ok:true}), error => sendResponse({error:String(error)}));
  return true;
});

chrome.alarms.create('flush', { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(a => a.name === 'flush' && serial(flush));

chrome.runtime.onInstalled.addListener(({reason}) => {
  if (reason === 'install') chrome.tabs.create({url: chrome.runtime.getURL('library.html#setup')});
});
