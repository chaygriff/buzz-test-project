import unittest
from talent_pipeline import network


from unittest.mock import patch
import socket
import io


class WireSocket:
    def __init__(self, wire):
        self.wire = wire
        self.sent = b''
        self.address = None
        self.closed = False

    def settimeout(self, value):
        self.timeout = value

    def connect(self, address):
        self.address = address

    def sendall(self, data):
        self.sent += data

    def makefile(self, mode):
        return io.BytesIO(self.wire)

    def shutdown(self, how):
        self.shutdown_called = True

    def close(self):
        self.closed = True


class TransportTests(unittest.TestCase):
    def test_absolute_network_deadline_closes_slow_connection(self):
        from unittest.mock import Mock
        timer = Mock()
        expire = []
        def make_timer(seconds, callback):
            expire.append(callback)
            return timer
        sock = WireSocket(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok')
        original = sock.makefile
        def makefile(mode):
            if expire:
                expire[0]()
            return original(mode)
        sock.makefile = makefile
        f = network.Fetcher({'http://example.com'})
        record = (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 80))
        with patch.object(f, '_resolve_public', return_value=record), patch.object(network.socket, 'socket', return_value=sock), patch.object(network.threading, 'Timer', side_effect=make_timer), self.assertRaises(TimeoutError):
            f._request('http://example.com/')
        self.assertTrue(sock.closed)
        self.assertTrue(sock.shutdown_called)
        timer.cancel.assert_called_once()

    def test_wire_rejects_oversize_headers_and_ambiguous_framing(self):
        for extra in [b'Content-Length: 999\r\n', b'Content-Length: 2\r\nContent-Length: 3\r\n', b'Content-Encoding: gzip\r\n', b'Transfer-Encoding: chunked\r\nContent-Length: 2\r\n']:
            sock = WireSocket(b'HTTP/1.1 200 OK\r\n' + extra + b'\r\nok')
            f = network.Fetcher({'http://example.com'}, max_bytes=32)
            record = (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 80))
            with self.subTest(extra=extra), patch.object(f, '_resolve_public', return_value=record), patch.object(network.socket, 'socket', return_value=sock), self.assertRaises(ValueError):
                f._request('http://example.com/')
            self.assertTrue(sock.closed)

    def test_request_pins_ip_and_preserves_host_and_tls_name(self):
        from unittest.mock import Mock
        for scheme in ['http', 'https']:
            port = 443 if scheme == 'https' else 80
            sock = WireSocket(b'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 2\r\n\r\nok')
            records = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', port))]
            context = Mock()
            context.wrap_socket.return_value = sock
            with patch.object(network.socket, 'getaddrinfo', return_value=records) as dns, patch.object(network.socket, 'socket', return_value=sock), patch('ssl.create_default_context', return_value=context):
                code, headers, body = network.Fetcher({scheme + '://example.com'})._request(scheme + '://example.com/a?q=1')
            self.assertEqual((code, body), (200, b'ok'))
            self.assertEqual(sock.address, ('8.8.8.8', port))
            self.assertEqual(dns.call_count, 1)
            self.assertIn(b'Host: example.com\r\n', sock.sent)
            self.assertIn(b'User-Agent: TalentPipelineCollector/2.0\r\n', sock.sent)
            self.assertIn(b'GET /a?q=1 HTTP/1.1', sock.sent)
            self.assertTrue(sock.closed)
            if scheme == 'https':
                context.wrap_socket.assert_called_once_with(sock, server_hostname='example.com')


class AddressTests(unittest.TestCase):
    def test_dns_resolution_has_a_deadline(self):
        import threading
        release = threading.Event()
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]
        def slow_resolver(*args, **kwargs):
            release.wait(0.05)
            return records
        try:
            with patch.object(network.socket, 'getaddrinfo', side_effect=slow_resolver), self.assertRaises(TimeoutError):
                network.Fetcher({'https://example.com'}, timeout=0.005)._resolve_public('example.com', 443)
        finally:
            release.set()

    def test_every_resolved_address_must_be_public(self):
        f = network.Fetcher({'https://example.com'})
        for addresses in [[], ['127.0.0.1'], ['10.1.2.3'], ['169.254.169.254'], ['::1'], ['fc00::1'], ['::ffff:127.0.0.1'], ['8.8.8.8', '192.168.1.1']]:
            records = [(socket.AF_INET6 if ':' in a else socket.AF_INET, socket.SOCK_STREAM, 6, '', (a, 443)) for a in addresses]
            with self.subTest(addresses=addresses), patch.object(network.socket, 'getaddrinfo', return_value=records), self.assertRaises(ValueError):
                f._resolve_public('example.com', 443)
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]
        with patch.object(network.socket, 'getaddrinfo', return_value=records):
            self.assertEqual(f._resolve_public('example.com', 443), records[0])


class FakeFetcher(network.Fetcher):
    def __init__(self, responses, approved=None, **kwargs):
        super().__init__(approved or {'https://example.com'}, delay_seconds=0, **kwargs)
        self.responses = responses
        self.calls = []

    def _request(self, url):
        self.calls.append(url)
        if len(self.calls) > 20:
            raise AssertionError('unbounded request loop')
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


def test_request_rate_denies_before_content_even_in_unparsed_group():
    for robots in [b'User-agent: *\nRequest-rate: 1/60\nAllow: /',
                   b'User-agent: UnknownBot\nRequest-rate: 1/60\nAllow: /',
                   b'Request-rate: 1/60\nAllow: /']:
        fetcher = FakeFetcher({'https://example.com/robots.txt': response(body=robots),
                               'https://example.com/people': response()})
        result = fetcher.fetch('https://example.com/people')
        assert result['reason'] == 'robots_denied'
        assert fetcher.calls == ['https://example.com/robots.txt']


def response(code=200, body=b'<html>ok</html>', **headers):
    return code, {'content-type': 'text/html', **headers}, body


class FetchTests(unittest.TestCase):
    def test_robots_denial_still_updates_origin_crawl_delay(self):
        f = FakeFetcher({'https://example.com/robots.txt': response(body=b'User-agent: *\nCrawl-delay: 3\nDisallow: /')})
        with patch('time.monotonic', return_value=0), patch('time.sleep') as sleep:
            self.assertEqual(f.fetch('https://example.com/a')['status'], 'blocked')
            self.assertEqual(f.fetch('https://example.com/b')['status'], 'blocked')
        sleep.assert_called_once_with(3)

    def test_duplicate_matching_robots_groups_use_largest_delay(self):
        f = FakeFetcher({'https://example.com/robots.txt': response(body=b'User-agent: TalentPipelineCollector\nCrawl-delay: 1\nAllow: /\n\nUser-agent: TalentPipelineCollector\nCrawl-delay: 3\nAllow: /'),
                         'https://example.com/a': response()})
        with patch('time.monotonic', return_value=0), patch('time.sleep') as sleep:
            self.assertEqual(f.fetch('https://example.com/a')['status'], 'ok')
        sleep.assert_called_once_with(3)

    def test_robots_never_grants_ambiguous_disallow_paths(self):
        for rules in [b'User-agent: *\nDisallow: /private/*', b'User-agent: *\nAllow: /\nDisallow: /private']:
            f = FakeFetcher({'https://example.com/robots.txt': response(body=rules)})
            self.assertEqual(f.fetch('https://example.com/private/a')['status'], 'blocked')
        f = FakeFetcher({})
        self.assertEqual(f.fetch('https://example.com/a/../private')['status'], 'blocked')

    def test_malformed_redirects_never_escape_or_get_normalized(self):
        for location in ['http://[bad', '\r\nhttps://example.com/b', '/a\\b', '/a' + 'x' * 9000]:
            f = FakeFetcher({'https://example.com/robots.txt': response(404), 'https://example.com/a': response(302, location=location)})
            self.assertEqual(f.fetch('https://example.com/a')['status'], 'unsupported')
            self.assertEqual(len(f.calls), 2)

    def test_http_protocol_errors_are_nonthrowing(self):
        import http.client
        for at_robots in (False, True):
            f = FakeFetcher({'https://example.com/robots.txt': http.client.BadStatusLine('bad') if at_robots else response(404),
                             'https://example.com/a': http.client.IncompleteRead(b'partial')})
            r = f.fetch('https://example.com/a')
            self.assertEqual(r['status'], 'blocked' if at_robots else 'failed')
            self.assertEqual(r['body'], b'')

    def test_robots_body_limits_and_malformed_directives(self):
        for body in [b'x' * 65, b'User-agent: *\nCrawl-delay: nope', b'Disallow: /private', b'User-agent: \nDisallow: /', b'User-agent: *\nCrawl-delay: 0.5']:
            f = FakeFetcher({'https://example.com/robots.txt': response(body=body)}, max_bytes=64)
            self.assertEqual(f.fetch('https://example.com/a')['status'], 'blocked')
        f = FakeFetcher({'https://example.com/robots.txt': response(body=b'User-agent: TalentPipelineCollector\nDisallow: /a\n\nUser-agent: *\nAllow: /')})
        self.assertEqual(f.fetch('https://example.com/a')['status'], 'blocked')

    def test_throttle_includes_robots_crawl_delay_and_failures(self):
        clock = [0.0]
        sleeps = []
        def sleep(seconds):
            sleeps.append(seconds)
            clock[0] += seconds
        f = FakeFetcher({'https://example.com/robots.txt': response(body=b'User-agent: *\nCrawl-delay: 3\nAllow: /'),
                         'https://example.com/a': TimeoutError('slow')})
        f.delay_seconds = 1
        with patch('time.monotonic', side_effect=lambda: clock[0]), patch('time.sleep', side_effect=sleep):
            self.assertEqual(f.fetch('https://example.com/a')['status'], 'failed')
            self.assertEqual(f.fetch('https://example.com/a')['status'], 'failed')
        self.assertEqual(sleeps, [3, 3, 3])
        f = FakeFetcher({'https://example.com/robots.txt': TimeoutError('robots slow')})
        f.delay_seconds = 1
        sleeps.clear()
        with patch('time.monotonic', side_effect=lambda: clock[0]), patch('time.sleep', side_effect=sleep):
            f.fetch('https://example.com/a')
            f.fetch('https://example.com/a')
        self.assertEqual(sleeps, [1])

    def test_only_bounded_successful_html_is_returned(self):
        cases = [response(500), response(**{'content-type': 'application/pdf'}),
                 response(body=b'x' * 65), response(**{'content-length': '999'}),
                 response(**{'content-length': '-1'}), response(**{'content-length': 'garbage'}),
                 response(**{'content-length': '1'}), TimeoutError('slow')]
        for data in cases:
            with self.subTest(data=data):
                f = FakeFetcher({'https://example.com/robots.txt': response(404), 'https://example.com/a': data}, max_bytes=64)
                r = f.fetch('https://example.com/a')
                self.assertNotEqual(r['status'], 'ok')
                self.assertEqual(r['body'], b'')

    def test_redirect_limit_loops_and_missing_location(self):
        for location, limit, reason in [('/a', 5, 'redirect_loop'), ('/b', 0, 'redirect_limit'), ('', 5, 'redirect_location')]:
            with self.subTest(location=location):
                f = FakeFetcher({'https://example.com/robots.txt': response(404),
                                 'https://example.com/a': response(302, location=location)}, max_redirects=limit)
                r = f.fetch('https://example.com/a')
                self.assertEqual(r['status'], 'blocked')
                self.assertEqual(r['reason'], reason)
                self.assertEqual(len(f.calls), 2)

    def test_redirect_hops_are_gated_before_contact(self):
        for destination in ['https://unapproved.com/', 'https://github.com/a', 'http://127.0.0.1/', 'file:///tmp/a', '/outside']:
            with self.subTest(destination=destination):
                f = FakeFetcher({'https://example.com/robots.txt': response(404),
                                 'https://example.com/team/a': response(302, location=destination)})
                r = f.fetch('https://example.com/team/a', scope_origin='https://example.com', scope_path='/team')
                self.assertIn(r['status'], ('blocked', 'unsupported'))
                self.assertEqual(len(f.calls), 2)
        f = FakeFetcher({'https://example.com/robots.txt': response(404),
                         'https://example.com/a': response(302, location='/b'),
                         'https://example.com/b': response()})
        r = f.fetch('https://example.com/a')
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(r['url'], 'https://example.com/b')
        self.assertEqual(r['redirects'], ['https://example.com/b'])

    def test_scope_is_checked_before_robots(self):
        f = FakeFetcher({})
        for url in ['https://example.com/teamwork', 'https://example.com/team/../admin', 'https://example.com/team/%2e%2e/admin', 'https://example.com/team/%2fadmin']:
            with self.subTest(url=url):
                self.assertEqual(f.fetch(url, scope_origin='https://example.com', scope_path='/team')['status'], 'blocked')
        self.assertEqual(f.fetch('https://example.com/team', scope_origin='https://elsewhere.com')['status'], 'blocked')
        self.assertEqual(f.calls, [])

    def test_robots_malformed_or_io_failure_denies(self):
        for data in [b'<html>not robots</html>', b'User-agent: *\nDisallow', b'\xff', TimeoutError('slow'), OSError('offline')]:
            with self.subTest(data=data):
                f = FakeFetcher({'https://example.com/robots.txt': data if isinstance(data, Exception) else response(body=data)})
                r = f.fetch('https://example.com/a')
                self.assertEqual(r['status'], 'blocked')
                self.assertFalse(r['policy'][0]['allowed'])
                self.assertEqual(len(f.calls), 1)

    def test_robots_fail_closed_except_404(self):
        for code in [301, 302, 401, 403, 429, 500, 503, 204]:
            with self.subTest(code=code):
                f = FakeFetcher({'https://example.com/robots.txt': response(code)})
                r = f.fetch('https://example.com/a')
                self.assertEqual(r['status'], 'blocked')
                self.assertEqual(len(f.calls), 1)
                self.assertFalse(r['policy'][0]['allowed'])
        f = FakeFetcher({'https://example.com/robots.txt': response(404), 'https://example.com/a': response()})
        self.assertEqual(f.fetch('https://example.com/a')['status'], 'ok')

    def test_approved_html_checks_robots_and_retains_evidence(self):
        import json
        f = FakeFetcher({'https://example.com/robots.txt': response(body=b'User-agent: *\nAllow: /'),
                         'https://example.com/a': response()})
        r = f.fetch('https://example.com/a')
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(r['body'], b'<html>ok</html>')
        self.assertEqual(f.calls, ['https://example.com/robots.txt', 'https://example.com/a'])
        self.assertEqual(r['policy'][0]['body'], 'User-agent: *\nAllow: /')
        self.assertIn('timestamp', r['policy'][0])
        json.dumps(r['policy'])


class GateTests(unittest.TestCase):
    def test_oversize_request_target_is_rejected_without_contact(self):
        f = FakeFetcher({})
        r = f.fetch('https://example.com/' + 'a' * 8192)
        self.assertEqual(r['status'], 'unsupported')
        self.assertEqual(f.calls, [])

    def test_invalid_resource_limits_are_rejected(self):
        for kwargs in [{'max_bytes': -1}, {'max_bytes': 0}, {'max_bytes': 1.5}, {'timeout': 0}, {'timeout': float('nan')}, {'delay_seconds': -1}, {'max_redirects': -1}, {'max_redirects': 1.5}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                network.Fetcher({'https://example.com'}, **kwargs)

    def test_identifier_rules_use_host_boundaries(self):
        for host in ['github.com.evil.test', 'notlinkedin.com', 'scholar.google.com.evil.test']:
            f = FakeFetcher({'https://' + host + '/robots.txt': response(404), 'https://' + host + '/': response()}, approved={'https://' + host})
            self.assertEqual(f.fetch('https://' + host + '/')['status'], 'ok')
        for host in ['scholar.google.com', 'a.scholar.google.com', 'scholar.google.co.uk', 'scholar.google.org']:
            f = FakeFetcher({}, approved={'https://' + host})
            self.assertEqual(f.fetch('https://' + host + '/')['reason'], 'identifier_only')
            self.assertEqual(f.calls, [])

    def test_denied_targets_never_contact_transport(self):
        f = network.Fetcher({'https://github.com', 'https://linkedin.com', 'https://scholar.google.co.uk'})
        f._request = lambda url: self.fail('contacted denied target')
        for url in ['https://other.example/', 'https://github.com/a', 'https://sub.linkedin.com/a', 'https://scholar.google.co.uk/a', 'file:///etc/passwd']:
            with self.subTest(url=url):
                r = f.fetch(url)
                self.assertIn(r['status'], ('blocked', 'unsupported'))
                self.assertEqual(r['body'], b'')
                self.assertEqual(set(r), {'status', 'reason', 'url', 'body', 'status_code', 'content_type', 'policy', 'redirects'})


class URLTests(unittest.TestCase):
    def test_canonical_public_url_shape(self):
        self.assertEqual(network.canonical_url('HTTPS://Example.COM:443/a?q=1#x'), 'https://example.com/a?q=1')
        self.assertEqual(network.origin('https://EXAMPLE.com/a'), 'https://example.com')
        for value in ['file:///tmp/x', 'http://u:p@example.com/', 'http://example.com:81/', 'http:///a', 'https://example.com/\r\nx']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                network.canonical_url(value)
