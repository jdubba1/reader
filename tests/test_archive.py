import test_daemon as support
server = support.server
from urllib.parse import urlencode


class ArchiveTests(support.DaemonTests):
    def setUp(self):
        self.request('POST', '/delete', {'confirm': 'delete-reader-x'})
        self.request('POST', '/ingest', {'posts': [
            {'id': '100', 'text': 'SQLite keeps a local archive', 'screen_name': 'sample_author',
             'quoted': {'text': 'search your bookmarks', 'screen_name': 'other'}, 'tier': 'bookmarked'},
            {'id': '101', 'text': 'A second note', 'screen_name': 'second'}],
            'signals': [{'id': '101', 'tier': 'viewed'}]})

    def search(self, **args):
        return self.request(path='/search?' + urlencode(args))

    def test_search_words_author_quote_and_tiers(self):
        for query in ('sqlite', 'sample_author', 'search bookmarks', 'local archive'):
            result = self.search(q=query)
            self.assertEqual(result[0], 200)
            self.assertEqual([p['id'] for p in result[2]['posts']], ['100'])
        self.assertEqual(self.search(tier='viewed')[2]['posts'][0]['id'], '101')
        self.assertEqual(self.search(q='missing')[2]['posts'], [])
        for query in ('"', 'OR', 'NEAR(', 'a:b', '*', '" OR 1=1 --'):
            self.assertEqual(self.search(q=query)[0], 200)
        for args in ({'offset': '-1'}, {'offset': 'wrong'}, {'offset': '9'*30}, {'tier': 'arbitrary'}, {'q': 'x'*501}):
            self.assertEqual(self.search(**args)[0], 400)

    def test_pagination_export_delete_and_fts(self):
        self.request('POST', '/ingest', {'posts': [{'id': str(i), 'text': 'page fixture'} for i in range(200, 260)]})
        first = self.search()[2]
        second = self.search(offset=50)[2]
        self.assertEqual(len(first['posts']), 50)
        self.assertTrue(first['has_more'])
        self.assertFalse(second['has_more'])
        self.assertEqual(len({p['id'] for p in first['posts'] + second['posts']}), 62)
        export = self.request(path='/export')[2]
        self.assertEqual(export['format'], 'reader-x')
        self.assertEqual(len(export['posts']), 62)
        self.assertEqual(len(export['signals']), 2)
        self.assertEqual(self.request('POST', '/delete', {})[0], 400)
        self.assertEqual(self.request('POST', '/delete', {'confirm': 'delete-reader-x'})[0], 200)
        self.assertEqual(self.search(q='sqlite')[2]['posts'], [])
        for table in ('posts', 'signals', 'events', 'tags'):
            self.assertEqual(self.request(path='/export')[2][table], [])
        self.request('POST', '/ingest', {'posts': [{'id':'100', 'text':'fresh archive'}]})
        self.assertEqual(len(self.search(q='fresh')[2]['posts']), 1)

    def test_malformed_nested_capture_does_not_break_daemon(self):
        self.assertEqual(self.request('POST', '/ingest', {'posts': [{'id':'bad', 'quoted':['invalid']}]})[0], 400)
        self.assertEqual(self.request()[0], 200)

    def test_all_archive_routes_reject_web_origins(self):
        for path in ('/stats', '/search?q=private', '/export'):
            status, headers, _ = self.request(path=path, headers={'Origin':'https://x.com'})
            self.assertEqual(status, 403)
            self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(self.request('POST', '/delete', {'confirm':'delete-reader-x'}, {'Origin':'https://x.com'})[0], 403)
