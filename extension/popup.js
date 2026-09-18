async function render() {
  try {
    const stats = await chrome.runtime.sendMessage({type: 'get-stats'});
    document.getElementById('capture').textContent = stats.deletePending ? 'Deletion unfinished. Open data controls to retry.' : stats.enabled ? 'Capture enabled on X.' : 'Capture paused. Open setup to enable it.';
    document.getElementById('queue').textContent = `${stats.queuedPosts} posts + ${stats.queuedSignals} signals queued.` + (stats.dropped ? ` ${stats.dropped} items dropped (queue full).` : '');
    const response = await fetch('http://127.0.0.1:8787/stats', {signal: AbortSignal.timeout(3000), cache: 'no-store'});
    if (!response.ok) throw Error();
    const data = await response.json();
    document.getElementById('connection').textContent = data.service === 'reader' && data.api_version === 1 ? `Connected. ${data.posts} posts archived.` : 'Companion update needed. Open setup.';
  } catch { document.getElementById('connection').textContent = 'Disconnected. Open setup to start Reader.'; }
}
document.getElementById('open').onclick = () => chrome.tabs.create({url: chrome.runtime.getURL('library.html')});
render();
