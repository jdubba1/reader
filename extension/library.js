const $ = id => document.getElementById(id);
const BASE = 'http://127.0.0.1:8787';
let enabled = false, consented = false, offset = 0, generation = 0, current = {q: '', tier: ''};
async function message(type, extra = {}) {
  const result = await chrome.runtime.sendMessage({type, ...extra});
  if (result?.error) throw Error(result.error);
  return result;
}
async function api(path, timeout = 5000) {
  const response = await fetch(BASE + path, {cache: 'no-store', signal: AbortSignal.timeout(timeout)});
  if (!response.ok) throw Error(`Companion request failed (${response.status}). Restart it and try again.`);
  return response.json();
}
function error(e) { $('error').textContent = e.message || String(e); }
async function status() {
  try {
    const stats = await message('get-stats');
    enabled = stats.enabled === true; consented = stats.consented === true;
    $('toggle').disabled = Boolean(stats.deletePending);
    $('toggle').textContent = enabled ? 'Pause capture' : consented ? 'Resume capture' : 'Enable local capture';
    $('capture').textContent = stats.deletePending ? 'Deletion unfinished. Reconnect, then retry Delete X data below.' : enabled ? 'Capture enabled on X.' + (stats.lastCapture ? ` Last post captured: ${new Date(stats.lastCapture).toLocaleString()}.` : ' No posts captured yet. Reload X and scroll a timeline.') : 'Capture paused. Enable it to save posts loaded by X, authors, and reading, like, and bookmark activity locally.';
    $('queue').textContent = `${stats.queuedPosts} posts and ${stats.queuedSignals} signals waiting to sync.` + (stats.dropped ? ` ${stats.dropped} items dropped because the queue was full.` : '') + (stats.lastError ? ' Last sync failed; queued items will retry.' : '') + (stats.lastFlush ? ` Last sync: ${new Date(stats.lastFlush).toLocaleString()}.` : '');
    try {
      const health = await api('/stats');
      if (health.service !== 'reader' || health.api_version !== 1) throw Error('Update the companion from the Reader source, then restart it.');
      $('connection').textContent = `Companion connected. ${health.posts.toLocaleString()} posts archived.`;
    } catch (e) { $('connection').textContent = e.message.startsWith('Update') ? e.message : 'Companion disconnected. Start Reader, then check connection.'; }
  } catch (e) { error(e); }
}
function postCard(post) {
  const card = document.createElement('article');
  const meta = document.createElement('div'); meta.className = 'meta';
  const author = document.createElement('strong'); author.textContent = post.author ? `@${post.author}` : 'Unknown author';
  const link = document.createElement('a'); link.textContent = 'Open original'; link.href = `https://x.com/i/status/${encodeURIComponent(post.id)}`; link.target = '_blank'; link.rel = 'noreferrer';
  meta.append(author, link);
  const body = document.createElement('p'); body.textContent = post.text || 'No text was available for this post.';
  card.append(meta, body);
  if (post.quoted_text) { const quote = document.createElement('blockquote'); quote.textContent = post.quoted_text; card.append(quote); }
  return card;
}
async function search(reset = true) {
  if (reset) { current = {q: $('query').value.trim().replace(/^@/, ''), tier: $('tier').value}; offset = 0; generation++; $('results').replaceChildren(); }
  const run = generation, pageOffset = offset;
  $('more').hidden = true; $('result-status').textContent = 'Searching your local archive…';
  try {
    const result = await api('/search?' + new URLSearchParams({...current, offset: pageOffset}));
    if (run !== generation) return;
    for (const post of result.posts) $('results').append(postCard(post));
    offset += result.posts.length;
    $('result-status').textContent = offset ? `${offset} posts shown, most recently captured first.` : current.q || current.tier ? 'No matching posts. Try fewer words or choose All captured.' : 'Your archive is empty. Start the companion, enable capture, and scroll X. Then sync.';
    $('more').hidden = !result.has_more;
  } catch (e) {
    if (run !== generation) return;
    $('result-status').textContent = 'Search unavailable. Start or update the companion, then try Search again. Your queued captures are kept in Chrome.';
  }
}
$('search').addEventListener('submit', e => { e.preventDefault(); search(); });
$('more').onclick = () => search(false);
$('toggle').onclick = async () => { try { await message('set-enabled', {enabled: !enabled}); await status(); } catch (e) { error(e); } };
$('retry').onclick = async () => { $('error').textContent = ''; $('retry').disabled = true; try { await message('flush'); await status(); await search(); } catch (e) { error(e); } finally { $('retry').disabled = false; } };
$('export').onclick = async () => {
  $('export').disabled = true; $('error').textContent = '';
  try {
    const data = await api('/export', 120000);
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'}));
    const link = document.createElement('a'); link.href = url; link.download = 'reader-x-export.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    $('notice').textContent = 'Export download started. It includes the companion archive; unsynced captures are not included.';
  } catch (e) { error(e); } finally { $('export').disabled = false; }
};
$('delete-open').onclick = () => { $('delete-confirm').hidden = false; $('confirmation').focus(); };
$('cancel').onclick = () => { $('delete-confirm').hidden = true; $('confirmation').value = ''; };
$('delete').onclick = async () => {
  if ($('confirmation').value !== 'DELETE') { error(Error('Type DELETE to confirm.')); return; }
  $('delete').disabled = true; $('error').textContent = '';
  try {
    await message('delete'); $('delete-confirm').hidden = true; $('confirmation').value = '';
    $('notice').textContent = 'X archive and queue deleted. Capture remains paused.'; await search();
  } catch (e) { error(Error('Queue cleared and capture paused. Start the companion, then retry deletion to clear the archive.')); }
  finally { $('delete').disabled = false; await status(); }
};
status(); search(); setInterval(status, 5000);
