// Loads inject.js against a stubbed page and asserts the capture path:
// fetch → GraphQL response → normalized posts on postMessage.
//   node extension/test/capture.test.js
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const vm = require('vm');

const messages = [];

const tweet = (id, text, extra = {}) => ({
  __typename: 'Tweet',
  rest_id: id,
  core: { user_results: { result: { rest_id: 'u1', core: { screen_name: 'example_reader', name: 'Example Reader' } } } },
  legacy: {
    created_at: 'Fri Jul 31 03:27:20 +0000 2026',
    full_text: text,
    lang: 'en',
    favorite_count: 1200,
    bookmark_count: 40,
    entities: { urls: [{ expanded_url: 'https://example.com/a' }], hashtags: [{ text: 'ai' }], symbols: [{ text: 'AMZN' }] },
    extended_entities: { media: [{ type: 'photo', media_url_https: 'https://pbs.twimg.com/x.jpg' }] },
  },
  views: { count: '99000' },
  ...extra,
});

// Shaped like a real Bookmarks response: instructions → entries → itemContent.
const fixture = {
  data: {
    bookmark_timeline_v2: {
      timeline: {
        instructions: [
          {
            type: 'TimelineAddEntries',
            entries: [
              { entryId: 'tweet-1', content: { itemContent: { tweet_results: { result: tweet('1', 'short post') } } } },
              {
                entryId: 'tweet-2',
                content: {
                  itemContent: {
                    tweet_results: {
                      result: tweet('2', 'truncated body…', {
                        // Long posts carry the real body here, not in full_text.
                        note_tweet: { note_tweet_results: { result: { text: 'the full untruncated body' } } },
                        quoted_status_result: { result: tweet('3', 'the quoted post') },
                      }),
                    },
                  },
                },
              },
              { entryId: 'cursor-bottom-9', content: { value: 'CURSOR_ABC', cursorType: 'Bottom' } },
            ],
          },
        ],
      },
    },
  },
};

class FakeXHR {
  open() {}
  send() {}
  addEventListener(name, callback) { this.onLoad = callback; }
}
FakeXHR.prototype.open = function () {};
FakeXHR.prototype.send = function () {};

const listeners = [];
const win = {
  location: { origin: 'https://x.com', href: 'https://x.com/i/bookmarks' },
  postMessage: (m) => messages.push(m),
  addEventListener: (t, fn) => listeners.push(fn),
  fetch: async () => ({
    clone() { return this; },
    async text() { return JSON.stringify(fixture); },
  }),
  XMLHttpRequest: FakeXHR,
};
win.window = win;

const ctx = vm.createContext({ ...win, XMLHttpRequest: FakeXHR, setTimeout, console });
ctx.window = ctx;
vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'inject.js'), 'utf8'), ctx);

(async () => {
  await ctx.window.fetch('https://x.com/i/api/graphql/fixture/Bookmarks?variables=%7B%7D');
  await new Promise((r) => setTimeout(r, 20));

  const posted = messages.find((m) => m.kind === 'posts');
  assert.ok(posted, 'expected a posts message');
  const { posts, tier, op } = posted.payload;

  assert.strictEqual(op, 'Bookmarks');
  assert.strictEqual(tier, 'bookmarked', 'Bookmarks endpoint implies engagement');

  // Arrays cross a vm realm boundary, so compare by value, not prototype.
  const ids = Array.from(posts, (p) => p.id).sort().join(',');
  // Quoted tweets must not be indexed as separately-read posts.
  assert.strictEqual(ids, '1,2', 'quoted tweet must not become its own post');

  const long = posts.find((p) => p.id === '2');
  assert.strictEqual(long.text, 'the full untruncated body', 'note_tweet must win over truncated full_text');
  assert.strictEqual(long.is_long, true);
  assert.strictEqual(long.quoted.id, '3');
  assert.strictEqual(long.quoted.text, 'the quoted post');

  const short = posts.find((p) => p.id === '1');
  assert.strictEqual(short.screen_name, 'example_reader');
  assert.strictEqual(short.created_at, 'Fri Jul 31 03:27:20 +0000 2026');
  assert.strictEqual(Array.from(short.symbols).join(), 'AMZN', 'cashtags are preserved');
  assert.strictEqual(Array.from(short.urls).join(), 'https://example.com/a');
  assert.strictEqual(short.media.length, 1);
  assert.strictEqual(short.view_count, 99000);

  // Engagement mutations carry the id in the request body, not the response.
  await ctx.window.fetch('https://x.com/i/api/graphql/fixture/CreateBookmark', {
    body: JSON.stringify({ variables: { tweet_id: '777' } }),
    headers: { authorization: 'Bearer test', 'x-csrf-token': 'ct0test' },
  });
  const eng = messages.find((m) => m.kind === 'engaged');
  assert.ok(eng, 'expected an engaged message');
  assert.strictEqual(eng.payload.id, '777');
  assert.strictEqual(eng.payload.tier, 'bookmarked');

  // A non-timeline endpoint must not produce captures.
  const before = messages.length;
  await ctx.window.fetch('https://x.com/i/api/graphql/abc/UserPreferences');
  await new Promise((r) => setTimeout(r, 20));
  assert.strictEqual(messages.length, before, 'unrelated endpoints must be ignored');

  const xhr = new ctx.XMLHttpRequest();
  xhr.open('GET', 'https://x.com/i/api/graphql/example/Likes');
  xhr.send();
  xhr.responseText = JSON.stringify(fixture);
  xhr.onLoad();
  assert.strictEqual(messages.at(-1).payload.tier, 'liked', 'XHR responses preserve engagement tiers');
  console.log('capture.test.js: all assertions passed');
})();
