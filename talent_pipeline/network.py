"""Fail-closed public HTTP collection with explicit operator eligibility.

``approved_origins`` is the operator's terms-eligibility gate, not a claim
that robots permission grants terms consent. Each target and redirect must
pass that gate and scope checks before its robots or page can be contacted.
``_request`` is the single-hop transport seam for deterministic offline tests.

Conservative limitations: one serial caller per Fetcher; throttling is local
to that instance (not distributed). Robots is re-fetched for every hop; matching
disallows are combined conservatively, wildcard/end-anchor rules and fractional
crawl delays deny rather than risk granting access. Only identity HTTP content
encoding is accepted. libc DNS cannot be cancelled: a timed-out daemon resolver
may finish later, but cannot open an HTTP socket. No cookies, auth, proxies,
JavaScript, retries, or automatic redirects are used. Timeouts apply per network
request, not to the entire fetch including polite sleeps and redirect hops.
"""
from urllib.parse import urlsplit, urlunsplit, unquote, urljoin
import posixpath
import socket
import ipaddress
import http.client
import ssl
import time
import re
import math
import threading
import queue
from urllib.robotparser import RobotFileParser
from datetime import datetime, timezone


def canonical_url(url):
    if not isinstance(url, str) or any(ord(c) <= 32 or ord(c) == 127 for c in url) or '\\' in url:
        raise ValueError('unsafe URL')
    try:
        if len(url.encode('utf-8')) > 8192:
            raise ValueError('request target too long')
        p = urlsplit(url)
        if p.scheme not in ('http', 'https') or not p.hostname or p.username is not None or p.password is not None:
            raise ValueError('unsafe URL')
        if p.port not in (None, 443 if p.scheme == 'https' else 80):
            raise ValueError('nondefault port')
        host = p.hostname.encode('idna').decode('ascii').lower().rstrip('.')
        if not host or '%' in host:
            raise ValueError('unsafe host')
        authority = '[' + host + ']' if ':' in host else host
        return urlunsplit((p.scheme, authority, p.path or '/', p.query, ''))
    except (ValueError, UnicodeError) as exc:
        raise ValueError('unsafe URL') from exc


def origin(url):
    p = urlsplit(canonical_url(url))
    return p.scheme + '://' + p.netloc


class Fetcher:
    def __init__(self, approved_origins: set[str], delay_seconds=1.0, timeout=15.0, max_bytes=2_000_000, max_redirects=5):
        if type(max_bytes) is not int or max_bytes <= 0 or type(max_redirects) is not int or max_redirects < 0:
            raise ValueError('invalid size or redirect limit')
        if not math.isfinite(timeout) or timeout <= 0 or not math.isfinite(delay_seconds) or delay_seconds < 0:
            raise ValueError('invalid timing limit')
        self.approved_origins = {origin(u) for u in approved_origins}
        self.delay_seconds = delay_seconds
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self._last = {}
        self._delays = {}

    def _polite_request(self, url):
        key = origin(url)
        delay = max(self.delay_seconds, self._delays.get(key, 0))
        if key in self._last:
            wait = self._last[key] + delay - time.monotonic()
            if wait > 0:
                time.sleep(wait)
        try:
            return self._request(url)
        finally:
            self._last[key] = time.monotonic()

    def _request(self, url):
        """Single hop seam: resolve once, connect to that literal IP, never proxy."""
        deadline = time.monotonic() + self.timeout
        p = urlsplit(canonical_url(url))
        port = 443 if p.scheme == 'https' else 80
        family, kind, proto, name, address = self._resolve_public(p.hostname, port)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('request_timeout')
        conn = http.client.HTTPConnection(p.hostname, port, timeout=remaining)
        sock = socket.socket(family, kind, proto)
        expired = threading.Event()
        def expire():
            expired.set()
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        watchdog = threading.Timer(remaining, expire)
        watchdog.daemon = True
        watchdog.start()
        try:
            sock.settimeout(remaining)
            sock.connect(address)
            if p.scheme == 'https':
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=p.hostname)
            conn.sock = sock
            conn.request('GET', urlunsplit(('', '', p.path, p.query, '')),
                         headers={'Host': p.netloc, 'User-Agent': 'TalentPipelineCollector/2.0', 'Accept': 'text/html, application/xhtml+xml, text/plain',
                                  'Accept-Encoding': 'identity', 'Connection': 'close'})
            response = conn.getresponse()
            pairs = response.getheaders()
            headers = {k.lower(): v for k, v in pairs}
            for key in ('content-length', 'content-type', 'content-encoding', 'transfer-encoding', 'location'):
                if sum(k.lower() == key for k, v in pairs) > 1:
                    raise ValueError('duplicate_header')
            length = headers.get('content-length')
            if length is not None and (not length.isascii() or not length.isdecimal() or int(length) > self.max_bytes):
                raise ValueError('invalid_or_oversize_content_length')
            if headers.get('content-encoding', 'identity').lower() != 'identity':
                raise ValueError('unsupported_content_encoding')
            if 'transfer-encoding' in headers and (length is not None or headers['transfer-encoding'].lower() != 'chunked'):
                raise ValueError('ambiguous_transfer_encoding')
            body = response.read(self.max_bytes + 1)
            if expired.is_set() or time.monotonic() >= deadline:
                raise TimeoutError('request_timeout')
            return response.status, headers, body
        finally:
            watchdog.cancel()
            conn.close()
            sock.close()

    def _resolve_public(self, host, port):
        # libc DNS cannot be cancelled; a daemon may finish after timeout but
        # never owns a socket or performs the HTTP request.
        results = queue.Queue(maxsize=1)
        def resolve():
            try:
                results.put(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))
            except OSError as exc:
                results.put(exc)
        threading.Thread(target=resolve, daemon=True).start()
        try:
            records = results.get(timeout=self.timeout)
        except queue.Empty as exc:
            raise TimeoutError('dns_timeout') from exc
        if isinstance(records, OSError):
            raise records
        if not records:
            raise ValueError('no_public_addresses')
        for family, kind, proto, name, address in records:
            ip = ipaddress.ip_address(address[0])
            if not ip.is_global or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
                raise ValueError('nonpublic_address')
        return records[0]

    def _in_scope(self, url, scope_origin, scope_path):
        try:
            if scope_origin is not None and origin(url) != origin(scope_origin):
                return False
            path = urlsplit(url).path
            if not scope_path.startswith('/') or '?' in scope_path or '#' in scope_path:
                return False
            # Reject ambiguous encodings rather than trusting server-specific decoding.
            decoded = unquote(path)
            if any(segment in ('.', '..') for segment in decoded.split('/')):
                return False
            if decoded != path and ('%' in decoded or decoded.count('/') != path.count('/')):
                return False
            if '\\' in decoded or any(ord(c) < 32 for c in decoded):
                return False
            normalized = posixpath.normpath(decoded)
            prefix = posixpath.normpath(scope_path)
            return prefix == '/' or normalized == prefix or normalized.startswith(prefix.rstrip('/') + '/')
        except ValueError:
            return False

    def _validate_body(self, headers, body):
        if len(body) > self.max_bytes:
            raise ValueError('body_too_large')
        length = headers.get('content-length')
        if length is not None and (not length.isascii() or not length.isdecimal() or int(length) != len(body)):
            raise ValueError('invalid_content_length')

    def _robots(self, robots_url, target):
        code, text, parser = None, '', RobotFileParser()
        try:
            code, headers, body = self._polite_request(robots_url)
            text = body[:self.max_bytes].decode('utf-8', errors='replace')
            self._validate_body(headers, body)
            if code == 404:
                return code, text, True, 'robots_missing', parser
            if code != 200:
                return code, text, False, 'robots_status', parser
            body.decode('utf-8-sig', errors='strict')
            agent_seen = False
            for line in text.lstrip('\ufeff').splitlines():
                line = line.split('#', 1)[0].strip()
                if not line:
                    continue
                if ':' not in line or line.startswith('<') or '\x00' in line:
                    raise ValueError('malformed robots')
                key, value = (part.strip() for part in line.split(':', 1))
                key = key.lower()
                if key == 'user-agent':
                    if not value:
                        raise ValueError('empty user agent')
                    agent_seen = True
                if key in ('allow', 'disallow', 'crawl-delay', 'request-rate') and not agent_seen:
                    raise ValueError('rule before user agent')
                if key in ('allow', 'disallow') and any(c in value for c in '*$'):
                    raise ValueError('unsupported robots pattern')
                if key == 'request-rate':
                    # Unsupported in this serial transport: reject before parsing
                    # groups rather than silently losing a rate restriction.
                    raise ValueError('unsupported request rate')
                if key == 'crawl-delay' and (not value.isascii() or not value.isdecimal()):
                    raise ValueError('unsupported crawl delay')
            parser.parse(text.lstrip('\ufeff').splitlines())
            # Conservatively combine matching disallows. stdlib's first-match
            # semantics can otherwise let an early Allow: / bypass restrictions.
            path = unquote(urlunsplit(('', '', urlsplit(target).path, urlsplit(target).query, '')))
            entries = parser.entries + ([parser.default_entry] if parser.default_entry else [])
            denied = any(not rule.allowance and path.startswith(unquote(rule.path))
                         for entry in entries if entry.applies_to('TalentPipelineCollector')
                         for rule in entry.rulelines)
            return code, text, not denied and parser.can_fetch('TalentPipelineCollector', target), 'robots_rules', parser
        except (OSError, ValueError, http.client.HTTPException):
            return code, text, False, 'robots_unavailable_or_malformed', parser

    def _gate(self, url, scope_origin, scope_path):
        host = urlsplit(url).hostname
        scholar = re.search(r'(?:^|\.)scholar\.google\.(?:[a-z]{2,63}|(?:co|com)\.[a-z]{2})$', host)
        if host == 'github.com' or host.endswith('.github.com') or host == 'linkedin.com' or host.endswith('.linkedin.com') or scholar:
            return 'identifier_only'
        if origin(url) not in self.approved_origins:
            return 'origin_not_approved'
        if not self._in_scope(url, scope_origin, scope_path):
            return 'outside_scope'
        return None

    def fetch(self, url: str, *, scope_origin: str | None = None, scope_path: str = '/') -> dict:
        result: dict = dict(status='blocked', reason=None, url=url, body=b'', status_code=None, content_type='', policy=[], redirects=[])
        seen = set()
        while True:
            try:
                url = canonical_url(url)
            except ValueError:
                result.update(status='unsupported', reason='unsafe_url')
                return result
            result['url'] = url
            if url in seen:
                result['reason'] = 'redirect_loop'
                return result
            seen.add(url)
            reason = self._gate(url, scope_origin, scope_path)
            if reason:
                result['reason'] = reason
                return result
            robots_url = origin(url) + '/robots.txt'
            code, text, allowed, robots_reason, parser = self._robots(robots_url, url)
            result['policy'].append(dict(url=robots_url, status_code=code, body=text, allowed=allowed,
                                         reason=robots_reason, timestamp=datetime.now(timezone.utc).isoformat()))
            entries = parser.entries + ([parser.default_entry] if parser.default_entry else [])
            crawl_delay = max((entry.delay or 0 for entry in entries if entry.applies_to('TalentPipelineCollector')), default=0)
            self._delays[origin(url)] = max(self._delays.get(origin(url), 0), crawl_delay)
            if not allowed:
                result['reason'] = 'robots_denied'
                return result
            try:
                code, headers, body = self._polite_request(url)
                self._validate_body(headers, body)
            except (OSError, ValueError, http.client.HTTPException) as exc:
                result.update(status='failed', reason=str(exc) or 'request_failed')
                return result
            result.update(status_code=code, content_type=headers.get('content-type', ''))
            if code in (301, 302, 303, 307, 308):
                if not headers.get('location'):
                    result['reason'] = 'redirect_location'
                    return result
                if len(result['redirects']) >= self.max_redirects:
                    result['reason'] = 'redirect_limit'
                    return result
                try:
                    location = headers['location']
                    if len(location.encode('utf-8')) > 8192 or '\\' in location or any(ord(c) <= 32 or ord(c) == 127 for c in location):
                        raise ValueError('unsafe redirect')
                    url = canonical_url(urljoin(url, location))
                except ValueError:
                    result.update(status='unsupported', reason='unsafe_redirect')
                    return result
                result['redirects'].append(url)
                continue
            if not 200 <= code < 300:
                result.update(status='failed', reason='http_status')
                return result
            if result['content_type'].split(';', 1)[0].strip().lower() not in ('text/html', 'application/xhtml+xml'):
                result.update(status='unsupported', reason='not_html')
                return result
            result.update(status='ok', reason=None, body=body)
            return result
