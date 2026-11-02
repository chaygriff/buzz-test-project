"""V2 regression tests. Network fixtures are local test data, never live findings."""
import importlib.util
import tempfile
import unittest
from pathlib import Path


class EvidenceStoreTests(unittest.TestCase):
    def test_failed_snapshot_write_never_publishes_a_raw_object(self):
        from unittest.mock import patch
        from talent_pipeline.store import Store
        with tempfile.TemporaryDirectory() as tmp:
            with Store(Path(tmp)) as store:
                with patch('os.fsync', side_effect=OSError('disk failure')):
                    with self.assertRaises(OSError):
                        store.snapshot('https://lab.example/', b'partial', 200, 'text/html')
                self.assertEqual(store.count('snapshots'), 0)
                self.assertEqual(list((Path(tmp) / 'raw').rglob('*.bin')), [])

    def test_evidence_metadata_is_append_only(self):
        import sqlite3
        from talent_pipeline.store import Store
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp)) as store:
            snap = store.snapshot('https://lab.example/', b'original', 200, 'text/html')
            with self.assertRaises(sqlite3.IntegrityError):
                store.db.execute('UPDATE snapshots SET url=? WHERE id=?', ('https://other.example/', snap['id']))

    def test_snapshot_is_content_addressed_and_persists_after_reopen(self):
        self.assertIsNotNone(importlib.util.find_spec('talent_pipeline'), 'v2 package must exist')
        from talent_pipeline.store import Store
        with tempfile.TemporaryDirectory() as tmp:
            with Store(Path(tmp)) as store:
                first = store.snapshot('https://lab.example/people', b'<h1>People</h1>', 200, 'text/html')
                second = store.snapshot('https://lab.example/people', b'<h1>People</h1>', 200, 'text/html')
                self.assertEqual(first['sha256'], second['sha256'])
                self.assertEqual((Path(tmp) / first['path']).read_bytes(), b'<h1>People</h1>')
            with Store(Path(tmp)) as store:
                self.assertEqual(store.count('snapshots'), 2)


class DurableRunTests(unittest.TestCase):
    def test_second_writer_is_rejected_without_corrupting_first(self):
        from talent_pipeline.store import Store
        with tempfile.TemporaryDirectory() as tmp:
            with Store(Path(tmp)):
                with self.assertRaisesRegex(RuntimeError, 'writer'):
                    Store(Path(tmp))
            with Store(Path(tmp)) as store:
                self.assertEqual(store.count('snapshots'), 0)

    def test_resume_keeps_completed_jobs_and_recovers_interrupted_jobs(self):
        from talent_pipeline.store import Store
        with tempfile.TemporaryDirectory() as tmp:
            with Store(Path(tmp)) as store:
                self.assertTrue(hasattr(store, 'open_run'), 'durable runs must be implemented')
                run = store.open_run({'seeds': ['faculty-a'], 'budget': 3})
                a = store.enqueue(run, 'faculty-a', 'roster', 'https://lab.example/')
                b = store.enqueue(run, 'faculty-a', 'roster', 'https://lab.example/people')
                self.assertEqual(store.claim(run)['id'], a)
                snap = store.snapshot('https://lab.example/', b'done', 200, 'text/html')
                store.finish(a, 'done', snapshot_id=snap['id'])
                self.assertEqual(store.claim(run)['id'], b)
            with Store(Path(tmp)) as store:
                self.assertEqual(store.open_run({'seeds': ['faculty-a'], 'budget': 3}), run)
                store.recover(run)
                recovered = store.claim(run)
                self.assertEqual(recovered['id'], b)
                self.assertEqual(recovered['attempts'], 2)
                self.assertNotEqual(store.open_run({'seeds': ['faculty-a'], 'budget': 3}, new_run=True), run)


import pytest
import json
import hashlib


def _valid_inputs(homepage, name='Faculty Example', institution='Example University'):
    from dataclasses import asdict
    from talent_pipeline.runner import Config
    from talent_pipeline.store import stable_id
    seed = {'faculty_name': name, 'faculty_institution': institution,
            'faculty_homepage': homepage, 'terms_approved': True, 'scope_path': '/'}
    from talent_pipeline.network import origin
    inputs = {'seeds': [seed], 'config': asdict(Config()),
              'approved_origins': [origin(homepage)], 'pipeline_version': 2,
              'transport': {'delay_seconds': 0.0, 'timeout': 15.0, 'max_bytes': 2_000_000,
                            'max_redirects': 5}}
    return inputs, stable_id(name, institution, homepage)


def _bundle_with_raw(tmp_path):
    from talent_pipeline.store import Store
    from talent_pipeline.export import export_bundle
    with Store(tmp_path) as store:
        inputs, seed_id = _valid_inputs('https://a.example/')
        run = store.open_run(inputs)
        job = store.enqueue(run, seed_id, 'roster', 'https://a.example/')
        store.claim(run)
        snap = store.snapshot('https://a.example/', b'original', 200, 'text/html')
        store.finish(job, 'done', snapshot_id=snap['id'],
                     observations=[('policy', _policy(snap))])
        return export_bundle(store, run), snap['path']


def _rehash(bundle, relative):
    path = bundle / relative
    data = path.read_bytes()
    manifest_path = bundle / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['files'][relative] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
    manifest_path.write_text(json.dumps(manifest))


def _policy(snapshot, request_url=None, attempt=1):
    request_url = request_url or snapshot['url']
    return {'source_url': snapshot['url'], 'request_url': request_url,
            'result_url': snapshot['url'], 'attempt': attempt, 'outcome': 'ok',
            'reason': None, 'policy': [],
            'redirects': [] if request_url == snapshot['url'] else [snapshot['url']]}


@pytest.mark.parametrize('target', ['candidates.csv', 'jobs.jsonl', 'raw', 'all'])
@pytest.mark.parametrize('damage', ['omit', 'delete', 'corrupt'])
def test_inventory_cannot_hide_missing_or_damaged_required_files(tmp_path, target, damage):
    from talent_pipeline.export import verify_bundle
    bundle, raw = _bundle_with_raw(tmp_path)
    manifest_path = bundle / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    targets = list(manifest['files']) if target == 'all' else [raw if target == 'raw' else target]
    for relative in targets:
        manifest['files'].pop(relative)
        if damage == 'delete':
            (bundle / relative).unlink()
        elif damage == 'corrupt':
            (bundle / relative).write_text('damaged')
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        verify_bundle(bundle)


def test_unmanifested_regular_file_is_rejected(tmp_path):
    from talent_pipeline.export import verify_bundle
    bundle, _ = _bundle_with_raw(tmp_path)
    (bundle / 'unmanifested.txt').write_text('not in inventory')
    with pytest.raises(ValueError, match='Exact bundle inventory mismatch'):
        verify_bundle(bundle)


@pytest.mark.parametrize('target_kind', ['file', 'directory'])
def test_symlinks_anywhere_in_bundle_are_rejected(tmp_path, target_kind):
    from talent_pipeline.export import verify_bundle
    bundle, _ = _bundle_with_raw(tmp_path)
    target = bundle / ('candidates.csv' if target_kind == 'file' else 'raw')
    (bundle / 'unexpected-link').symlink_to(target, target_is_directory=target_kind == 'directory')
    with pytest.raises(ValueError, match='Symlink'):
        verify_bundle(bundle)


def test_unexpected_empty_directory_is_rejected(tmp_path):
    from talent_pipeline.export import verify_bundle
    bundle, _ = _bundle_with_raw(tmp_path)
    (bundle / '.staging-metadata').mkdir()
    with pytest.raises(ValueError, match='directory inventory'):
        verify_bundle(bundle)


@pytest.mark.parametrize('key,value', [
    ('schema_version', 1), ('schema_version', True), ('files', []), ('counts', []),
    ('inputs', []), ('run_id', 42), ('created_at', None), ('fingerprint', 4), ('status', []),
    ('files', {'candidates.csv': []}), ('files', {'candidates.csv': {'sha256': 5, 'bytes': '2'}}),
])
def test_manifest_structural_types_are_rejected(tmp_path, key, value):
    from talent_pipeline.export import verify_bundle
    bundle, _ = _bundle_with_raw(tmp_path)
    path = bundle / 'manifest.json'
    manifest = json.loads(path.read_text())
    manifest[key] = value
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        verify_bundle(bundle)


@pytest.mark.parametrize('key', ['schema_version', 'files', 'counts', 'inputs', 'run_id', 'created_at', 'fingerprint', 'status'])
def test_manifest_required_keys_are_validated(tmp_path, key):
    from talent_pipeline.export import verify_bundle
    bundle, _ = _bundle_with_raw(tmp_path)
    path = bundle / 'manifest.json'
    manifest = json.loads(path.read_text())
    del manifest[key]
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        verify_bundle(bundle)


def test_manifest_rejects_unknown_top_level_field(tmp_path):
    from talent_pipeline.export import verify_bundle
    bundle, _ = _bundle_with_raw(tmp_path)
    path = bundle / 'manifest.json'
    manifest = json.loads(path.read_text())
    manifest['unexpected'] = True
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='manifest keys'):
        verify_bundle(bundle)


@pytest.mark.parametrize('change', ['run_id', 'inputs', 'fingerprint'])
def test_manifest_run_attribution_is_cryptographically_bound(tmp_path, change):
    from talent_pipeline.export import verify_bundle
    bundle, _ = _bundle_with_raw(tmp_path)
    path = bundle / 'manifest.json'
    manifest = json.loads(path.read_text())
    if change == 'run_id':
        manifest['run_id'] = 'f' * 32
    elif change == 'inputs':
        manifest['inputs']['seeds'] = ['attacker']
    else:
        manifest['fingerprint'] = '0' * 64
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        verify_bundle(bundle)


@pytest.mark.parametrize('table', ['jobs', 'observations'])
def test_export_rows_must_belong_to_manifest_run(tmp_path, table):
    from talent_pipeline.export import verify_bundle
    bundle, _ = _bundle_with_raw(tmp_path)
    path = bundle / (table + '.jsonl')
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if not rows:
        pytest.skip('fixture has no rows for this table')
    rows[0]['run_id'] = 'f' * 32
    path.write_text(''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows))
    _rehash(bundle, table + '.jsonl')
    with pytest.raises(ValueError, match='run'):
        verify_bundle(bundle)


@pytest.mark.parametrize('field,value', [
    ('seed_id', 'substituted-seed'),
    ('kind', 'profile'),
    ('url', 'https://attacker.example/'),
    ('payload', {'subject_id': 'substituted-subject'}),
])
def test_job_rows_must_match_their_deterministic_ids(tmp_path, field, value):
    from talent_pipeline.export import verify_bundle
    bundle, _ = _bundle_with_raw(tmp_path)
    path = bundle / 'jobs.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0][field] = value
    path.write_text(''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows))
    _rehash(bundle, 'jobs.jsonl')
    with pytest.raises(ValueError, match='Deterministic job ID mismatch'):
        verify_bundle(bundle)


def test_job_payload_must_be_an_object(tmp_path):
    from talent_pipeline.export import verify_bundle
    bundle, _ = _bundle_with_raw(tmp_path)
    path = bundle / 'jobs.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]['payload'] = []
    path.write_text(''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows))
    _rehash(bundle, 'jobs.jsonl')
    with pytest.raises(ValueError, match='Invalid job payload'):
        verify_bundle(bundle)


@pytest.mark.parametrize('field,value', [
    ('status', 'unknown'), ('status', 1), ('attempts', -1), ('attempts', True),
    ('reason', 4), ('snapshot_id', 'not-an-id'), ('updated_at', ''), ('updated_at', '   '),
    ('url', 'ftp://a.example/'), ('kind', 'other'),
])
def test_job_state_and_domain_are_fully_validated(tmp_path, field, value):
    from talent_pipeline.export import verify_bundle
    bundle, _ = _bundle_with_raw(tmp_path)
    path = bundle / 'jobs.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0][field] = value
    if field in {'url', 'kind'}:
        from talent_pipeline.store import stable_id
        row = rows[0]
        row['id'] = stable_id(row['run_id'], row['seed_id'], row['kind'], row['url'],
                              row['payload'].get('subject_id'))
    path.write_text(''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows))
    _rehash(bundle, 'jobs.jsonl')
    with pytest.raises(ValueError, match='job'):
        verify_bundle(bundle)


@pytest.mark.parametrize('change', ['missing_key', 'extra_key'])
def test_job_schema_is_exact_even_after_rehash(tmp_path, change):
    from talent_pipeline.export import verify_bundle
    bundle, _ = _bundle_with_raw(tmp_path)
    path = bundle / 'jobs.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if change == 'missing_key':
        del rows[0]['updated_at']
    else:
        rows[0]['attacker'] = True
    path.write_text(''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows))
    _rehash(bundle, 'jobs.jsonl')
    with pytest.raises(ValueError, match='job'):
        verify_bundle(bundle)


@pytest.mark.parametrize('payload', [
    {'subject_id': 'valid'},
    {'subject_id': 'valid', 'name': '   '},
    {'subject_id': 'valid', 'name': 'Jane Doe', 'extra': True},
])
def test_profile_job_requires_exact_subject_payload(tmp_path, payload):
    from talent_pipeline.export import verify_bundle
    from talent_pipeline.store import stable_id
    bundle, _ = _bundle_with_raw(tmp_path)
    path = bundle / 'jobs.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    payload['subject_id'] = stable_id(payload['subject_id'])
    profile = dict(rows[0], kind='profile', url='https://a.example/person',
                   payload=payload, snapshot_id=None)
    profile['id'] = stable_id(profile['run_id'], profile['seed_id'], profile['kind'],
                              profile['url'], profile['payload']['subject_id'])
    rows.append(profile)
    path.write_text(''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows))
    manifest_path = bundle / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['counts']['jobs'] += 1
    manifest_path.write_text(json.dumps(manifest))
    _rehash(bundle, 'jobs.jsonl')
    with pytest.raises(ValueError, match='profile job payload'):
        verify_bundle(bundle)


def test_every_seed_requires_exactly_one_homepage_roster_root(tmp_path):
    from talent_pipeline.export import verify_bundle
    from talent_pipeline.store import stable_id
    bundle, _ = _bundle_with_raw(tmp_path)
    manifest_path = bundle / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    second = {'faculty_name': 'Second Faculty', 'faculty_institution': 'Example University',
              'faculty_homepage': 'https://second.example/', 'terms_approved': True,
              'scope_path': '/'}
    manifest['inputs']['seeds'].append(second)
    manifest['inputs']['seeds'].sort(key=lambda seed: stable_id(
        seed['faculty_name'], seed['faculty_institution'], seed['faculty_homepage']))
    manifest['inputs']['approved_origins'].append('https://second.example')
    manifest['inputs']['approved_origins'].sort()
    manifest['fingerprint'] = stable_id(json.dumps(manifest['inputs'], sort_keys=True,
                                                   ensure_ascii=False, allow_nan=False))
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='roster root'):
        verify_bundle(bundle)


def test_jobs_cannot_reference_unknown_manifest_seed(tmp_path):
    from talent_pipeline.export import verify_bundle
    from talent_pipeline.store import stable_id
    bundle, _ = _bundle_with_raw(tmp_path)
    path = bundle / 'jobs.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]['seed_id'] = stable_id('unknown seed')
    rows[0]['id'] = stable_id(rows[0]['run_id'], rows[0]['seed_id'], rows[0]['kind'],
                              rows[0]['url'], None)
    path.write_text(''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows))
    _rehash(bundle, 'jobs.jsonl')
    with pytest.raises(ValueError, match='unknown seed'):
        verify_bundle(bundle)


def test_duplicate_homepage_roster_root_is_rejected(tmp_path):
    from talent_pipeline.export import verify_bundle
    bundle, _ = _bundle_with_raw(tmp_path)
    path = bundle / 'jobs.jsonl'
    row = json.loads(path.read_text().splitlines()[0])
    path.write_text(path.read_text() + json.dumps(row, sort_keys=True) + '\n')
    manifest_path = bundle / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['counts']['jobs'] += 1
    manifest_path.write_text(json.dumps(manifest))
    _rehash(bundle, 'jobs.jsonl')
    with pytest.raises(ValueError):
        verify_bundle(bundle)


@pytest.mark.parametrize('damage', ['pipeline_version', 'seed_terms', 'seed_field', 'seed_blank'])
def test_manifest_inputs_require_v2_pipeline_seed_schema(tmp_path, damage):
    from talent_pipeline.export import verify_bundle
    from talent_pipeline.store import stable_id
    bundle, _ = _bundle_with_raw(tmp_path)
    path = bundle / 'manifest.json'
    manifest = json.loads(path.read_text())
    if damage == 'pipeline_version':
        manifest['inputs']['pipeline_version'] = 1
    elif damage == 'seed_terms':
        manifest['inputs']['seeds'][0]['terms_approved'] = False
    elif damage == 'seed_blank':
        manifest['inputs']['seeds'][0]['faculty_name'] = '   '
    else:
        del manifest['inputs']['seeds'][0]['scope_path']
    manifest['fingerprint'] = stable_id(json.dumps(manifest['inputs'], sort_keys=True,
                                                   ensure_ascii=False, allow_nan=False))
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='inputs'):
        verify_bundle(bundle)


@pytest.mark.parametrize('damage', [
    'pipeline_float', 'pipeline_bool', 'config_extra', 'config_missing', 'config_bool',
    'config_range', 'parser_version', 'transport_extra', 'delay_bool', 'delay_nan',
    'timeout_zero', 'max_bytes_float', 'redirects_negative', 'origin_path',
    'origin_duplicate', 'origin_unsorted', 'origin_missing_seed', 'homepage_noncanonical',
    'homepage_query', 'scope_nondirectory', 'scope_outside', 'seed_unsorted',
])
def test_manifest_inputs_are_exact_canonical_and_domain_validated(damage):
    import copy
    from talent_pipeline.export import _validate_inputs
    from talent_pipeline.store import stable_id

    inputs, _ = _valid_inputs('https://a.example/lab/person')
    inputs['seeds'][0]['scope_path'] = '/lab/'
    if damage == 'pipeline_float':
        inputs['pipeline_version'] = 2.0
    elif damage == 'pipeline_bool':
        inputs['pipeline_version'] = True
    elif damage == 'config_extra':
        inputs['config']['extra'] = 1
    elif damage == 'config_missing':
        del inputs['config']['max_attempts']
    elif damage == 'config_bool':
        inputs['config']['max_attempts'] = True
    elif damage == 'config_range':
        inputs['config']['max_pages_per_seed'] = 1001
    elif damage == 'parser_version':
        inputs['config']['parser_version'] = ''
    elif damage == 'transport_extra':
        inputs['transport']['extra'] = 1
    elif damage == 'delay_bool':
        inputs['transport']['delay_seconds'] = False
    elif damage == 'delay_nan':
        inputs['transport']['delay_seconds'] = float('nan')
    elif damage == 'timeout_zero':
        inputs['transport']['timeout'] = 0
    elif damage == 'max_bytes_float':
        inputs['transport']['max_bytes'] = 10.0
    elif damage == 'redirects_negative':
        inputs['transport']['max_redirects'] = -1
    elif damage == 'origin_path':
        inputs['approved_origins'] = ['https://a.example/']
    elif damage == 'origin_duplicate':
        inputs['approved_origins'] *= 2
    elif damage == 'origin_unsorted':
        inputs['approved_origins'] = ['https://z.example', 'https://a.example']
    elif damage == 'origin_missing_seed':
        inputs['approved_origins'] = ['https://other.example']
    elif damage == 'homepage_noncanonical':
        inputs['seeds'][0]['faculty_homepage'] = 'https://A.EXAMPLE/lab/person'
    elif damage == 'homepage_query':
        inputs['seeds'][0]['faculty_homepage'] += '?view=full'
    elif damage == 'scope_nondirectory':
        inputs['seeds'][0]['scope_path'] = '/lab'
    elif damage == 'scope_outside':
        inputs['seeds'][0]['scope_path'] = '/other/'
    elif damage == 'seed_unsorted':
        second = copy.deepcopy(inputs['seeds'][0])
        second.update(faculty_name='Second Faculty', faculty_homepage='https://b.example/')
        inputs['approved_origins'].append('https://b.example')
        inputs['approved_origins'].sort()
        inputs['seeds'].append(second)
        inputs['seeds'].sort(key=lambda seed: stable_id(
            seed['faculty_name'], seed['faculty_institution'], seed['faculty_homepage']), reverse=True)
    with pytest.raises(ValueError, match='inputs'):
        _validate_inputs(inputs)


def test_observation_rows_must_match_their_deterministic_ids(tmp_path):
    from talent_pipeline.export import verify_bundle
    bundle, _ = _bundle_with_raw(tmp_path)
    changed = None
    for name in ('observations', 'policies'):
        path = bundle / (name + '.jsonl')
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]['payload']['receipt'] = 'substituted'
        changed = rows[0]
        path.write_text(''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows))
        _rehash(bundle, name + '.jsonl')
    assert changed is not None
    with pytest.raises(ValueError, match='Deterministic observation ID mismatch'):
        verify_bundle(bundle)


def test_observation_schema_is_exact_even_after_rehash(tmp_path):
    from talent_pipeline.export import verify_bundle
    bundle, _ = _bundle_with_raw(tmp_path)
    for name in ('observations', 'policies'):
        path = bundle / (name + '.jsonl')
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]['attacker'] = True
        path.write_text(''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows))
        _rehash(bundle, name + '.jsonl')
    with pytest.raises(ValueError, match='observation'):
        verify_bundle(bundle)


def test_observation_cannot_be_cross_rebound_to_another_jobs_valid_snapshot(tmp_path):
    from talent_pipeline.export import export_bundle, verify_bundle
    from talent_pipeline.store import Store, stable_id
    with Store(tmp_path) as store:
        inputs, seed_id = _valid_inputs('https://a.example/')
        run = store.open_run(inputs)
        roster_job = store.enqueue(run, seed_id, 'roster', 'https://a.example/')
        profile_job = store.enqueue(run, seed_id, 'profile', 'https://a.example/person', {
            'subject_id': stable_id('person'), 'name': 'Example Person',
        })
        roster_snapshot = store.snapshot('https://a.example/', b'roster', 200, 'text/html')
        profile_snapshot = store.snapshot(
            'https://a.example/person', b'profile', 200, 'text/html')
        store.claim(run)
        store.finish(roster_job, 'done', snapshot_id=roster_snapshot['id'],
                     observations=[('policy', _policy(roster_snapshot))])
        store.claim(run)
        store.finish(profile_job, 'done', snapshot_id=profile_snapshot['id'],
                     observations=[('policy', _policy(profile_snapshot))])
        bundle = export_bundle(store, run)

    for name in ('observations', 'policies'):
        path = bundle / (name + '.jsonl')
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        target = next(row for row in rows if row['job_id'] == roster_job)
        target['snapshot_id'] = profile_snapshot['id']
        path.write_text(''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows))
        _rehash(bundle, name + '.jsonl')

    with pytest.raises(ValueError, match='snapshot.*job|job.*snapshot|source URL provenance'):
        verify_bundle(bundle)


def test_store_rejects_observation_source_url_forged_away_from_snapshot(tmp_path):
    from talent_pipeline.store import Store, stable_id

    with Store(tmp_path) as store:
        inputs, seed_id = _valid_inputs('https://a.example/')
        run = store.open_run(inputs)
        job = store.enqueue(run, seed_id, 'roster', 'https://a.example/')
        store.claim(run)
        snap = store.snapshot('https://a.example/', b'roster', 200, 'text/html')
        policy = {'source_url': snap['url'], 'request_url': 'https://a.example/',
                  'result_url': snap['url'], 'attempt': 1, 'outcome': 'ok',
                  'reason': None, 'policy': [], 'redirects': []}
        candidate = {'subject_id': stable_id('person'), 'name': 'Example Person',
                     'source_url': 'https://attacker.example/',
                     'evidence_text': 'Example Person', 'locator': 'li:nth-of-type(1)'}
        with pytest.raises(ValueError, match='source URL provenance'):
            store.finish(job, 'done', snapshot_id=snap['id'],
                         observations=[('policy', policy), ('candidate', candidate)])
        row = store.db.execute('SELECT status,snapshot_id FROM jobs WHERE id=?', (job,)).fetchone()
        assert tuple(row) == ('running', None)
        assert store.db.execute('SELECT count(*) FROM observations').fetchone()[0] == 0


def test_bundle_rejects_rehashed_forged_candidate_source_url(tmp_path):
    from talent_pipeline.export import verify_bundle, _candidate_csv
    from talent_pipeline.store import stable_id

    bundle = _bundle_with_candidate(tmp_path)
    changed = None
    for name in ('observations', 'candidates'):
        path = bundle / (name + '.jsonl')
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]['payload']['source_url'] = 'https://attacker.example/'
        rows[0]['id'] = stable_id(rows[0]['job_id'], rows[0]['kind'],
                                  json.dumps(rows[0]['payload'], sort_keys=True,
                                             ensure_ascii=False, allow_nan=False))
        changed = rows[0]
        path.write_text(''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows))
        _rehash(bundle, name + '.jsonl')
    assert changed is not None
    candidates = [json.loads(line) for line in (bundle / 'candidates.jsonl').read_text().splitlines()]
    (bundle / 'candidates.csv').write_bytes(_candidate_csv(candidates))
    _rehash(bundle, 'candidates.csv')
    with pytest.raises(ValueError, match='source URL provenance'):
        verify_bundle(bundle)


@pytest.mark.parametrize('attempt', [0, 2, True, '1'])
def test_policy_provenance_requires_current_positive_integer_attempt(tmp_path, attempt):
    from talent_pipeline.store import Store

    with Store(tmp_path) as store:
        inputs, seed_id = _valid_inputs('https://a.example/')
        run = store.open_run(inputs)
        job = store.enqueue(run, seed_id, 'roster', 'https://a.example/')
        store.claim(run)
        snap = store.snapshot('https://a.example/', b'roster', 200, 'text/html')
        with pytest.raises(ValueError, match='source URL provenance'):
            store.finish(job, 'done', snapshot_id=snap['id'],
                         observations=[('policy', _policy(snap, attempt=attempt))])


def test_redirected_snapshot_provenance_binds_request_and_final_urls(tmp_path):
    from talent_pipeline.export import export_bundle, verify_bundle
    from talent_pipeline.store import Store

    with Store(tmp_path) as store:
        inputs, seed_id = _valid_inputs('https://a.example/')
        run = store.open_run(inputs)
        job = store.enqueue(run, seed_id, 'roster', 'https://a.example/')
        store.claim(run)
        snap = store.snapshot('https://a.example/people', b'roster', 200, 'text/html')
        policy = {'source_url': snap['url'], 'request_url': 'https://a.example/',
                  'result_url': snap['url'], 'attempt': 1, 'outcome': 'ok',
                  'reason': None, 'policy': [], 'redirects': [snap['url']]}
        store.finish(job, 'done', snapshot_id=snap['id'], observations=[('policy', policy)])
        assert verify_bundle(export_bundle(store, run))['status'] == 'needs_review'


def test_pending_attempt_evidence_survives_reopen_before_successful_retry(tmp_path):
    from talent_pipeline.store import Store

    inputs, seed_id = _valid_inputs('https://a.example/')
    with Store(tmp_path) as store:
        run = store.open_run(inputs)
        job = store.enqueue(run, seed_id, 'roster', 'https://a.example/')
        claimed = store.claim(run)
        assert claimed is not None and claimed['attempts'] == 1
        first = store.snapshot('https://a.example/', b'failure', 0, 'application/json')
        failed_policy = _policy(first)
        failed_policy.update(outcome='failed', reason='timeout')
        store.finish(job, 'pending', 'timeout', first['id'], [('policy', failed_policy)])

    with Store(tmp_path) as store:
        store.recover(run)
        claimed = store.claim(run)
        assert claimed is not None and claimed['attempts'] == 2
        second = store.snapshot('https://a.example/', b'success', 200, 'text/html')
        store.finish(job, 'done', snapshot_id=second['id'],
                     observations=[('policy', _policy(second, attempt=2))])
        attempts = store.db.execute(
            'SELECT attempt,snapshot_id FROM job_snapshots WHERE job_id=? ORDER BY attempt',
            (job,),
        ).fetchall()
        assert [(row['attempt'], row['snapshot_id']) for row in attempts] == [
            (1, first['id']), (2, second['id']),
        ]
        observations = store.rows('observations', run)
        assert {row['snapshot_id'] for row in observations} == {first['id'], second['id']}


def test_snapshot_table_must_exactly_match_referenced_evidence(tmp_path):
    from talent_pipeline.export import verify_bundle
    bundle, _ = _bundle_with_raw(tmp_path)
    snapshots = bundle / 'snapshots.jsonl'
    rows = [json.loads(line) for line in snapshots.read_text().splitlines()]
    extra = dict(rows[0])
    extra['id'] = 'f' * 32
    rows.append(extra)
    snapshots.write_text(''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows))
    manifest_path = bundle / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['counts']['snapshots'] += 1
    manifest_path.write_text(json.dumps(manifest))
    _rehash(bundle, 'snapshots.jsonl')
    with pytest.raises(ValueError, match='Snapshot'):
        verify_bundle(bundle)


@pytest.mark.parametrize('damage', [
    'not_object', 'extra', 'missing', 'id', 'url', 'hash', 'path', 'status_bool', 'status_range',
    'content_type', 'time_invalid', 'time_naive',
])
def test_snapshot_schema_and_domains_are_exact(tmp_path, damage):
    from talent_pipeline.export import verify_bundle
    bundle, _ = _bundle_with_raw(tmp_path)
    path = bundle / 'snapshots.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    row = rows[0]
    if damage == 'not_object':
        rows[0] = []
    elif damage == 'extra':
        row['authority'] = 'unexpected'
    elif damage == 'missing':
        del row['content_type']
    elif damage == 'id':
        row['id'] = 'A' * 32
    elif damage == 'url':
        row['url'] = 'https://A.EXAMPLE/'
    elif damage == 'hash':
        row['sha256'] = 'A' * 64
    elif damage == 'path':
        row['path'] = f"raw/00/{row['sha256']}.bin"
    elif damage == 'status_bool':
        row['status'] = True
    elif damage == 'status_range':
        row['status'] = 600
    elif damage == 'content_type':
        row['content_type'] = ''
    elif damage == 'time_invalid':
        row['retrieved_at'] = 'not-a-time'
    else:
        row['retrieved_at'] = '2026-01-01T00:00:00'
    path.write_text(''.join(json.dumps(item, sort_keys=True) + '\n' for item in rows))
    _rehash(bundle, 'snapshots.jsonl')
    with pytest.raises(ValueError, match='snapshot schema'):
        verify_bundle(bundle)


def test_snapshot_status_42_is_not_an_http_or_no_response_status(tmp_path):
    from talent_pipeline.export import verify_bundle
    bundle, _ = _bundle_with_raw(tmp_path)
    path = bundle / 'snapshots.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]['status'] = 42
    path.write_text(''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows))
    _rehash(bundle, 'snapshots.jsonl')
    with pytest.raises(ValueError, match='snapshot schema'):
        verify_bundle(bundle)


@pytest.mark.parametrize('status', [42, 99, 600, -1, True])
def test_snapshot_store_rejects_unsupported_status_domain(tmp_path, status):
    from talent_pipeline.store import Store
    with Store(tmp_path) as store, pytest.raises(ValueError, match='status'):
        store.snapshot('https://a.example/', b'body', status, 'text/html')


@pytest.mark.parametrize('status', [0, 100, 599])
def test_snapshot_store_accepts_no_response_and_http_status_boundaries(tmp_path, status):
    from talent_pipeline.store import Store
    with Store(tmp_path) as store:
        assert store.snapshot('https://a.example/', b'body', status, 'text/html')['status'] == status


def test_done_job_cannot_reference_no_response_snapshot(tmp_path):
    from talent_pipeline.export import verify_bundle
    bundle, _ = _bundle_with_raw(tmp_path)
    path = bundle / 'snapshots.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]['status'] = 0
    path.write_text(''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows))
    _rehash(bundle, 'snapshots.jsonl')
    with pytest.raises(ValueError, match='status'):
        verify_bundle(bundle)


def test_bundle_rejects_done_job_without_snapshot_even_when_observation_snapshot_exists(tmp_path):
    from talent_pipeline.export import verify_bundle
    bundle, _ = _bundle_with_raw(tmp_path)
    path = bundle / 'jobs.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]['snapshot_id'] = None
    path.write_text(''.join(json.dumps(row, sort_keys=True) + '\n' for row in rows))
    _rehash(bundle, 'jobs.jsonl')
    with pytest.raises(ValueError, match='Done job requires'):
        verify_bundle(bundle)


@pytest.mark.parametrize('snapshot_case', ['missing', 'unknown', 'non_success'])
def test_store_rejects_done_job_without_valid_successful_snapshot(tmp_path, snapshot_case):
    from talent_pipeline.store import Store
    with Store(tmp_path) as store:
        run = store.open_run({'fixture': snapshot_case})
        job = store.enqueue(run, 'seed', 'roster', 'https://a.example/')
        snapshot_id = None
        if snapshot_case == 'unknown':
            snapshot_id = 'f' * 32
        elif snapshot_case == 'non_success':
            snapshot_id = store.snapshot('https://a.example/', b'not found', 404,
                                         'text/html')['id']
        with pytest.raises(ValueError, match='done job.*2xx snapshot'):
            store.finish(job, 'done', snapshot_id=snapshot_id,
                         observations=[('policy', {'receipt': 'must roll back'})])
        row = store.db.execute('SELECT status,snapshot_id FROM jobs WHERE id=?',
                               (job,)).fetchone()
        assert tuple(row) == ('pending', None)
        assert store.db.execute('SELECT count(*) FROM observations').fetchone()[0] == 0


@pytest.mark.parametrize('snapshot_status', [None, 404])
def test_sqlite_guards_done_job_snapshot_invariant(tmp_path, snapshot_status):
    import sqlite3
    from talent_pipeline.store import Store
    with Store(tmp_path) as store:
        run = store.open_run({'fixture': snapshot_status})
        job = store.enqueue(run, 'seed', 'roster', 'https://a.example/')
        snapshot_id = None
        if snapshot_status is not None:
            snapshot_id = store.snapshot('https://a.example/', b'failure', snapshot_status,
                                         'text/html')['id']
        with pytest.raises(sqlite3.IntegrityError, match='done job requires successful snapshot'):
            store.db.execute("UPDATE jobs SET status='done',snapshot_id=? WHERE id=?",
                             (snapshot_id, job))


@pytest.mark.parametrize('operation', ['insert_observation', 'rebind_job', 'rebind_job_to_null'])
def test_sqlite_guards_exact_observation_job_snapshot_binding(tmp_path, operation):
    import sqlite3
    from talent_pipeline.store import Store, stable_id
    with Store(tmp_path) as store:
        run = store.open_run({'fixture': operation})
        job = store.enqueue(run, 'seed', 'roster', 'https://a.example/')
        store.claim(run)
        first = store.snapshot('https://a.example/', b'first', 200, 'text/html')
        second = store.snapshot('https://a.example/', b'second', 200, 'text/html')
        store.finish(job, 'failed' if operation == 'rebind_job_to_null' else 'done',
                     snapshot_id=first['id'], observations=[('policy', _policy(first))])
        with pytest.raises(sqlite3.IntegrityError, match='observation snapshot must match job'):
            if operation == 'insert_observation':
                payload = json.dumps({'receipt': 'second'}, sort_keys=True)
                store.db.execute('INSERT INTO observations VALUES (?,?,?,?,?,?)', (
                    stable_id(job, 'policy', payload), run, job, second['id'], 'policy', payload,
                ))
            elif operation == 'rebind_job':
                store.db.execute('UPDATE jobs SET snapshot_id=? WHERE id=?', (second['id'], job))
            else:
                store.db.execute('UPDATE jobs SET snapshot_id=NULL WHERE id=?', (job,))


def test_zero_candidate_bundle_never_claims_complete(tmp_path):
    from talent_pipeline.export import verify_bundle
    bundle, _ = _bundle_with_raw(tmp_path)
    assert verify_bundle(bundle)['status'] == 'needs_review'


def _bundle_with_candidate(tmp_path):
    from talent_pipeline.store import Store
    from talent_pipeline.export import export_bundle
    with Store(tmp_path) as store:
        from talent_pipeline.store import stable_id
        inputs, seed_id = _valid_inputs('https://csv.example/')
        run = store.open_run(inputs)
        job = store.enqueue(run, seed_id, 'roster', 'https://csv.example/')
        store.claim(run)
        snap = store.snapshot('https://csv.example/', b'csv fixture', 200, 'text/html')
        store.finish(job, 'done', snapshot_id=snap['id'], observations=[
            ('policy', _policy(snap)), ('candidate', {
            'subject_id': stable_id('candidate-1'), 'name': '=SUM(1,2)', 'faculty_name': 'Renée, Faculty',
            'faculty_institution': 'Université\nExample', 'profile_url': '+https://example.test',
            'relationship': '@postdoc', 'source_url': snap['url'],
            'evidence_text': '-formula evidence, quoted "value"', 'locator': 'li:nth-of-type(1)',
        })])
        return export_bundle(store, run)


@pytest.mark.parametrize('damage', ['extra_column', 'extra_row', 'missing_row', 'altered_value'])
def test_candidates_csv_must_exactly_match_candidate_observations(tmp_path, damage):
    from talent_pipeline.export import verify_bundle
    bundle = _bundle_with_candidate(tmp_path)
    assert verify_bundle(bundle)['status'] == 'complete'
    path = bundle / 'candidates.csv'
    data = path.read_bytes()
    text = data.decode('utf-8')
    assert text.startswith('subject_id,name,faculty_name,faculty_institution,profile_url,relationship,source_url,evidence_text,locator\r\n')
    assert text.count('\r\n') == 2
    assert 'Renée, Faculty' in text and 'Université\nExample' in text
    assert "'=SUM(1,2)" in text and "'+https://example.test" in text
    if damage == 'extra_column':
        text = text.replace('\r\n', ',attacker\r\n', 1)
    elif damage == 'extra_row':
        text += text.split('\r\n', 1)[1]
    elif damage == 'missing_row':
        text = text.split('\r\n', 1)[0] + '\r\n'
    else:
        text = text.replace("'=SUM(1,2)", "'=SUM(9,9)")
    path.write_bytes(text.encode('utf-8'))
    _rehash(bundle, 'candidates.csv')
    with pytest.raises(ValueError, match='candidates.csv'):
        verify_bundle(bundle)


def test_nonvisible_roster_items_cannot_escape_during_li_repair():
    from talent_pipeline.extract import extract_roster
    result = extract_roster('<h2>People</h2><li style="display:none"><a href="/fake">Fake Person</a><li><a href="/other">Other Person</a></li></li>', 'https://lab.example/')
    assert result['candidates'] == []
    assert any('Other Person' in r['evidence_text'] for r in result['review'])


class ExportTests(unittest.TestCase):
    def test_failed_export_keeps_previous_bundle_and_cleans_staging(self):
        from unittest.mock import patch
        from talent_pipeline.store import Store
        from talent_pipeline.export import export_bundle, verify_bundle, _write_rows
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp)) as store:
            inputs, seed_id = _valid_inputs('https://a.example/')
            run = store.open_run(inputs)
            job = store.enqueue(run, seed_id, 'roster', 'https://a.example/')
            store.claim(run)
            snap = store.snapshot('https://a.example/', b'fixture', 200, 'text/html')
            store.finish(job, 'done', snapshot_id=snap['id'])
            first = export_bundle(store, run)
            calls = []
            def fail_after_one(path, rows):
                calls.append(path)
                if len(calls) > 1:
                    raise OSError('injected disk failure')
                return _write_rows(path, rows)
            with patch('talent_pipeline.export._write_rows', fail_after_one):
                with self.assertRaises(OSError):
                    export_bundle(store, run)
            self.assertEqual(verify_bundle(first)['run_id'], run)
            self.assertEqual(list((Path(tmp) / 'exports').iterdir()), [first])

    def test_corrupted_raw_evidence_prevents_export_publication(self):
        from talent_pipeline.store import Store
        from talent_pipeline.export import export_bundle
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp)) as store:
            inputs, seed_id = _valid_inputs('https://a.example/')
            run = store.open_run(inputs)
            job = store.enqueue(run, seed_id, 'roster', 'https://a.example/')
            snap = store.snapshot('https://a.example/', b'original', 200, 'text/html')
            store.finish(job, 'done', snapshot_id=snap['id'])
            (Path(tmp) / snap['path']).write_bytes(b'corrupted')
            with self.assertRaisesRegex(ValueError, 'Snapshot checksum'):
                export_bundle(store, run)
            self.assertEqual(list((Path(tmp) / 'exports').iterdir()), [])

    def test_export_is_self_contained_with_verified_counts_and_raw_evidence(self):
        from talent_pipeline.store import Store
        self.assertIsNotNone(importlib.util.find_spec('talent_pipeline.export'), 'atomic export must exist')
        from talent_pipeline.export import export_bundle, verify_bundle
        with tempfile.TemporaryDirectory() as tmp:
            with Store(Path(tmp)) as store:
                from talent_pipeline.store import stable_id
                inputs, seed_id = _valid_inputs('https://lab.example/people')
                run = store.open_run(inputs)
                job = store.enqueue(run, seed_id, 'roster', 'https://lab.example/people')
                store.claim(run)
                snap = store.snapshot('https://lab.example/people', b'<li>Alice Example</li>', 200, 'text/html')
                store.finish(job, 'done', snapshot_id=snap['id'], observations=[
                    ('policy', _policy(snap)), ('candidate', {
                    'subject_id': stable_id('alice-a'), 'name': 'Alice Example', 'evidence_text': 'Alice Example',
                    'locator': 'li:1', 'source_url': snap['url']})])
                bundle = export_bundle(store, run)
                manifest = verify_bundle(bundle)
                self.assertEqual(manifest['status'], 'complete')
                self.assertEqual(manifest['counts']['candidates'], 1)
                self.assertTrue((bundle / snap['path']).exists())
                self.assertNotEqual(export_bundle(store, run), bundle)


if __name__ == '__main__':
    unittest.main()
