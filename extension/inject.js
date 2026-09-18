// Page-world script. Runs as the page, so it sees the page's own fetch/XHR
// traffic; a content script in the isolated world would not.
(() => {
  // Guard against duplicate injection.
  if (window.__readerIndexerLoaded) return;
  window.__readerIndexerLoaded = true;

  const CHANNEL = 'reader-indexer';

  // Timeline reads worth indexing. Anything fetched here was on screen or
  // about to be; the dwell filter in content.js decides what counts as read.
  const READ_OPS = /\/graphql\/[^/]+\/(HomeTimeline|HomeLatestTimeline|TweetDetail|Bookmarks|Likes|SearchTimeline|UserTweets|UserTweetsAndReplies|ListLatestTweetsTimeline|BookmarkSearchTimeline)/;
  // Explicit engagement. These are mutations, so the tweet id is in the request.
  const ENGAGE_OPS = /\/graphql\/[^/]+\/(FavoriteTweet|CreateBookmark)/;

  const send = (kind, payload) =>
    window.postMessage({ source: CHANNEL, kind, payload }, window.location.origin);

  // X's timeline JSON nests tweets differently per endpoint and reshapes them
  // regularly. Walking for __typename is stable across all of them.
  function collectTweets(node, out = [], depth = 0) {
    if (!node || typeof node !== 'object' || depth > 30) return out;
    if (Array.isArray(node)) {
      for (const v of node) collectTweets(v, out, depth + 1);
      return out;
    }
    if (node.__typename === 'Tweet' && node.rest_id && node.legacy) out.push(node);
    for (const k in node) {
      if (k === 'quoted_status_result') continue; // captured with its parent
      collectTweets(node[k], out, depth + 1);
    }
    return out;
  }

  function userOf(t) {
    const u = t.core?.user_results?.result || {};
    return {
      user_id: u.rest_id || null,
      screen_name: u.core?.screen_name || u.legacy?.screen_name || null,
      name: u.core?.name || u.legacy?.name || null,
    };
  }

  function normalize(t) {
    const leg = t.legacy || {};
    // note_tweet holds the untruncated body of long posts.
    const note = t.note_tweet?.note_tweet_results?.result?.text;
    const q = t.quoted_status_result?.result;
    return {
      id: t.rest_id,
      created_at: leg.created_at || null,
      text: note || leg.full_text || '',
      is_long: !!note,
      lang: leg.lang || null,
      ...userOf(t),
      urls: (leg.entities?.urls || []).map((u) => u.expanded_url).filter(Boolean),
      hashtags: (leg.entities?.hashtags || []).map((h) => h.text),
      symbols: (leg.entities?.symbols || []).map((s) => s.text),
      media: (leg.extended_entities?.media || leg.entities?.media || []).map((m) => ({
        type: m.type,
        url: m.media_url_https,
      })),
      favorite_count: leg.favorite_count ?? null,
      retweet_count: leg.retweet_count ?? null,
      reply_count: leg.reply_count ?? null,
      bookmark_count: leg.bookmark_count ?? null,
      view_count: t.views?.count ? Number(t.views.count) : null,
      conversation_id: leg.conversation_id_str || null,
      in_reply_to: leg.in_reply_to_status_id_str || null,
      quoted: q?.rest_id
        ? { id: q.rest_id, ...userOf(q), text: q.note_tweet?.note_tweet_results?.result?.text || q.legacy?.full_text || '' }
        : null,
    };
  }

  function handleResponse(url, bodyText) {
    if (!READ_OPS.test(url)) return;
    let json;
    try { json = JSON.parse(bodyText); } catch { return; }
    const posts = collectTweets(json).map(normalize).filter((p) => p.id);
    if (!posts.length) return;
    const op = url.match(/\/graphql\/[^/]+\/([^?]+)/)?.[1] || 'unknown';
    // Bookmarks/Likes endpoints are themselves proof of engagement.
    const tier = op === 'Bookmarks' || op === 'BookmarkSearchTimeline' ? 'bookmarked'
      : op === 'Likes' ? 'liked'
      : 'fetched';
    send('posts', { op, tier, posts });
  }

  function handleEngagement(url, reqBody) {
    if (!ENGAGE_OPS.test(url)) return;
    let id = null;
    try { id = JSON.parse(reqBody)?.variables?.tweet_id || null; } catch {}
    if (!id) return;
    const op = url.match(/\/graphql\/[^/]+\/([^?]+)/)?.[1];
    send('engaged', { id, tier: op === 'CreateBookmark' ? 'bookmarked' : 'liked' });
  }

  // Observe only requests made by the X page. Never retain session headers,
  // read cookies, or issue background requests to X.
  const origFetch = window.fetch;
  window.fetch = async function (...args) {
    const req = args[0];
    const url = typeof req === 'string' ? req : req?.url || '';
    const init = args[1] || {};
    if (init.body) handleEngagement(url, init.body);
    const resp = await origFetch.apply(this, args);
    if (READ_OPS.test(url)) {
      resp.clone().text().then(t => handleResponse(url, t)).catch(() => {});
    }
    return resp;
  };
  const OpenXHR = XMLHttpRequest.prototype.open;
  const SendXHR = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__url = String(url);
    return OpenXHR.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function (body) {
    const url = this.__url || '';
    if (body) handleEngagement(url, body);
    if (READ_OPS.test(url)) {
      this.addEventListener('load', () => {
        try { handleResponse(url, this.responseText); } catch {}
      });
    }
    return SendXHR.call(this, body);
  };
  send('ready', {});
})();
