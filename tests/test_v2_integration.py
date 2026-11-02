"""Whole-pipeline tests use explicitly synthetic transport receipts, not live findings."""
import contextlib
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from talent_pipeline.cli import main
from talent_pipeline.network import Fetcher
from talent_pipeline.export import verify_bundle

ROSTER = b'<h2>People</h2><ul><li><a href="https://alice.example/">Alice Example</a> postdoc</li></ul>'
PROFILE = b'<h1>Alice Example</h1><p>I work at Example Lab as a researcher.</p><a href="https://github.com/alice-example">GitHub</a>'


def test_cli_runs_real_parsers_network_policy_storage_export_and_resume():
    calls = []
    class FixtureWire(Fetcher):
        def _request(self, url):
            calls.append(url)
            if url.endswith('/robots.txt'):
                return 200, {'content-type': 'text/plain'}, b'User-agent: *\nAllow: /\n'
            return 200, {'content-type': 'text/html'}, PROFILE if url == 'https://alice.example/' else ROSTER
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        seeds = root / 'seeds.csv'
        seeds.write_text('faculty_name,faculty_institution,faculty_homepage,terms_approved\nFaculty A,Example,https://a.example/,true\nFaculty B,Example,https://b.example/,true\n')
        args = ['run', '--seeds', str(seeds), '--state', str(root / 'state'), '--approve-origin', 'https://alice.example', '--delay-seconds', '0']
        with patch('talent_pipeline.network.Fetcher', FixtureWire), contextlib.redirect_stdout(io.StringIO()) as output:
            assert main(args) == 0
        first = json.loads(output.getvalue())
        bundle = Path(first['bundle'])
        manifest = verify_bundle(bundle)
        assert manifest['status'] == 'complete'
        assert manifest['counts']['candidates'] == 2
        assert manifest['counts']['claims'] == 4
        snapshots = [json.loads(line) for line in (bundle / 'snapshots.jsonl').read_text().splitlines()]
        assert len(snapshots) == 4
        assert len({s['sha256'] for s in snapshots}) == 2
        before = list(calls)
        with patch('talent_pipeline.network.Fetcher', FixtureWire), contextlib.redirect_stdout(io.StringIO()) as output:
            assert main(args) == 0
        assert calls == before
        assert json.loads(output.getvalue())['run_id'] == first['run_id']


def test_cli_robots_denial_exports_partial_and_never_contacts_page():
    calls = []
    class DeniedWire(Fetcher):
        def _request(self, url):
            calls.append(url)
            return 429, {}, b'Too many requests'
    with tempfile.TemporaryDirectory() as tmp:
        seeds = Path(tmp) / 'seeds.csv'
        seeds.write_text('faculty_name,faculty_institution,faculty_homepage,terms_approved\nFaculty A,Example,https://a.example/,true\n')
        with patch('talent_pipeline.network.Fetcher', DeniedWire), contextlib.redirect_stdout(io.StringIO()) as output:
            code = main(['run', '--seeds', str(seeds), '--state', str(Path(tmp) / 'state')])
        result = json.loads(output.getvalue())
        assert code == 2
        assert result['status'] == 'partial'
        assert result['counts']['candidates'] == 0
        assert calls == ['https://a.example/robots.txt']
        assert verify_bundle(Path(result['bundle']))['status'] == 'partial'
