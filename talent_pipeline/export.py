"""Validated self-contained export bundles, staged before atomic publication."""
import csv
import hashlib
import io
import json
import math
import os
import posixpath
import re
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from talent_pipeline.network import canonical_url, origin
from talent_pipeline.store import (now, stable_id, valid_snapshot_status,
                                   validate_observation_provenance)


_CANDIDATE_FIELDS = ['subject_id', 'name', 'faculty_name', 'faculty_institution',
                     'profile_url', 'relationship', 'source_url', 'evidence_text', 'locator']
_JOB_FIELDS = {'id', 'run_id', 'seed_id', 'kind', 'url', 'payload', 'status',
               'attempts', 'reason', 'snapshot_id', 'updated_at'}
_OBSERVATION_FIELDS = {'id', 'run_id', 'job_id', 'snapshot_id', 'kind', 'payload'}
_SEED_FIELDS = {'faculty_name', 'faculty_institution', 'faculty_homepage',
                'terms_approved', 'scope_path'}
_CONFIG_FIELDS = {'max_pages_per_seed', 'max_profiles_per_seed', 'max_attempts',
                  'max_candidates_per_page', 'max_links_per_page', 'parser_version'}
_TRANSPORT_FIELDS = {'delay_seconds', 'timeout', 'max_bytes', 'max_redirects'}
_SNAPSHOT_FIELDS = {'id', 'url', 'sha256', 'path', 'status', 'content_type',
                    'retrieved_at'}
_HEX_32 = re.compile(r'[0-9a-f]{32}')
_HEX_64 = re.compile(r'[0-9a-f]{64}')


def _http_url(value):
    if not isinstance(value, str) or not value or value != value.strip() or any(c.isspace() for c in value):
        return False
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError:
        return False
    return (parsed.scheme in {'http', 'https'} and parsed.hostname is not None
            and parsed.username is None and parsed.password is None and not parsed.fragment)


def _validate_inputs(inputs):
    if (not isinstance(inputs, dict)
            or set(inputs) != {'seeds', 'config', 'approved_origins', 'pipeline_version', 'transport'}
            or type(inputs.get('pipeline_version')) is not int or inputs['pipeline_version'] != 2
            or not isinstance(inputs.get('seeds'), list) or not inputs['seeds']
            or not isinstance(inputs.get('config'), dict) or set(inputs['config']) != _CONFIG_FIELDS
            or not isinstance(inputs.get('transport'), dict) or set(inputs['transport']) != _TRANSPORT_FIELDS
            or not isinstance(inputs.get('approved_origins'), list)):
        raise ValueError('Invalid manifest inputs')
    config = inputs['config']
    if (any(type(config[key]) is not int or not 1 <= config[key] <= 1000
            for key in _CONFIG_FIELDS - {'parser_version'})
            or type(config['parser_version']) is not str
            or not config['parser_version'].strip()):
        raise ValueError('Invalid manifest inputs config')
    transport = inputs['transport']
    if (type(transport['delay_seconds']) not in (int, float)
            or not math.isfinite(transport['delay_seconds']) or transport['delay_seconds'] < 0
            or type(transport['timeout']) not in (int, float)
            or not math.isfinite(transport['timeout']) or transport['timeout'] <= 0
            or type(transport['max_bytes']) is not int or transport['max_bytes'] <= 0
            or type(transport['max_redirects']) is not int or transport['max_redirects'] < 0):
        raise ValueError('Invalid manifest inputs transport')
    seeds = {}
    seed_ids = []
    for seed in inputs['seeds']:
        if (not isinstance(seed, dict) or set(seed) != _SEED_FIELDS
                or any(not isinstance(seed.get(key), str) or not seed[key].strip()
                       for key in ('faculty_name', 'faculty_institution', 'faculty_homepage', 'scope_path'))
                or seed.get('terms_approved') is not True):
            raise ValueError('Invalid manifest inputs seed')
        try:
            homepage = seed['faculty_homepage']
            parsed = urlsplit(homepage)
            normalized_scope = posixpath.normpath(seed['scope_path'])
            normalized_scope = '/' if normalized_scope == '/' else normalized_scope.rstrip('/') + '/'
            normalized_path = posixpath.normpath(parsed.path)
            if (homepage != canonical_url(homepage) or parsed.query or parsed.fragment
                    or seed['scope_path'] != normalized_scope
                    or normalized_path != normalized_scope.rstrip('/')
                    and not normalized_path.startswith(normalized_scope)):
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError('Invalid manifest inputs seed') from None
        seed_id = stable_id(seed['faculty_name'], seed['faculty_institution'], seed['faculty_homepage'])
        if seed_id in seeds:
            raise ValueError('Invalid manifest inputs: duplicate seed')
        seeds[seed_id] = seed
        seed_ids.append(seed_id)
    if seed_ids != sorted(seed_ids):
        raise ValueError('Invalid manifest inputs: seed order')
    approved = inputs['approved_origins']
    try:
        if (any(type(value) is not str or value != origin(value) for value in approved)
                or approved != sorted(set(approved))
                or any(origin(seed['faculty_homepage']) not in approved for seed in inputs['seeds'])):
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError('Invalid manifest inputs approved origins') from None
    return seeds


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _write_rows(path, rows):
    with path.open('x', encoding='utf-8') as handle:
        for row in rows:
            handle.write(_json(row) + '\n')
        handle.flush()
        os.fsync(handle.fileno())


def _candidate_csv(rows):
    handle = io.StringIO(newline='')
    writer = csv.DictWriter(handle, fieldnames=_CANDIDATE_FIELDS, extrasaction='ignore')
    writer.writeheader()
    for record in rows:
        row = {key: ("'" + value if isinstance(value, str)
                     and value.lstrip().startswith(('=', '+', '-', '@')) else value)
               for key, value in record['payload'].items()}
        writer.writerow(row)
    return handle.getvalue().encode('utf-8')


def _safe_path(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Unsafe bundle path')
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Bundle path escapes root')
    return path


def _disk_inventory(root):
    files = set()
    directories = set()

    def visit(directory, relative):
        with os.scandir(directory) as entries:
            for entry in entries:
                child = relative / entry.name
                label = str(child)
                if entry.is_symlink():
                    raise ValueError('Symlink is not allowed in bundle: ' + label)
                if entry.is_dir(follow_symlinks=False):
                    directories.add(label)
                    visit(entry.path, child)
                elif entry.is_file(follow_symlinks=False):
                    if child != Path('manifest.json'):
                        files.add(label)
                else:
                    raise ValueError('Non-regular bundle entry: ' + label)

    visit(root, Path())
    return files, directories


def verify_bundle(directory):
    directory = Path(directory)
    manifest_path = directory / 'manifest.json'
    if directory.is_symlink() or manifest_path.is_symlink():
        raise ValueError('Symlink is not allowed in bundle')
    if not manifest_path.is_file():
        raise ValueError('Missing bundle manifest')
    manifest = json.loads(manifest_path.read_text())
    names = ('jobs', 'snapshots', 'observations', 'candidates', 'claims', 'review', 'policies')
    required_keys = {'schema_version', 'run_id', 'created_at', 'fingerprint', 'inputs', 'status', 'counts', 'files'}
    if not isinstance(manifest, dict) or set(manifest) != required_keys:
        raise ValueError('Invalid manifest keys')
    if type(manifest['schema_version']) is not int or manifest['schema_version'] != 2:
        raise ValueError('Unsupported manifest schema version')
    if (any(not isinstance(manifest[key], str) or not manifest[key] for key in ('run_id', 'created_at', 'fingerprint', 'status'))
            or manifest['status'] not in {'complete', 'partial', 'needs_review'}
            or not isinstance(manifest['inputs'], dict)
            or not isinstance(manifest['counts'], dict) or set(manifest['counts']) != set(names)
            or any(type(count) is not int or count < 0 for count in manifest['counts'].values())
            or not isinstance(manifest['files'], dict)):
        raise ValueError('Invalid manifest field types')
    if (not re.fullmatch(r'[0-9a-f]{32}', manifest['run_id'])
            or not re.fullmatch(r'[0-9a-f]{64}', manifest['fingerprint'])):
        raise ValueError('Invalid manifest identifier format')
    expected_fingerprint = stable_id(_json(manifest['inputs']))
    if manifest['fingerprint'] != expected_fingerprint:
        raise ValueError('Manifest inputs fingerprint mismatch')
    seeds = _validate_inputs(manifest['inputs'])
    required_files = {name + '.jsonl' for name in names} | {'candidates.csv'}
    if not required_files <= manifest['files'].keys():
        raise ValueError('Incomplete bundle hash inventory')
    for relative, expected in manifest['files'].items():
        if (not isinstance(relative, str) or not relative or str(Path(relative)) != relative
                or not isinstance(expected, dict) or set(expected) != {'sha256', 'bytes'}
                or not isinstance(expected['sha256'], str) or len(expected['sha256']) != 64
                or any(c not in '0123456789abcdef' for c in expected['sha256'])
                or type(expected['bytes']) is not int or expected['bytes'] < 0):
            raise ValueError('Invalid bundle hash inventory entry')
        if not _safe_path(directory, relative).is_file():
            raise ValueError('Missing bundle file: ' + relative)
    disk_files, disk_directories = _disk_inventory(directory)
    if disk_files != set(manifest['files']):
        raise ValueError('Exact bundle inventory mismatch')
    expected_directories = set()
    for relative in manifest['files']:
        parent = Path(relative).parent
        while parent != Path('.'):
            expected_directories.add(str(parent))
            parent = parent.parent
    if disk_directories != expected_directories:
        raise ValueError('Exact bundle directory inventory mismatch')
    tables = {}
    for name in names:
        tables[name] = [json.loads(line) for line in (directory / (name + '.jsonl')).read_text().splitlines()]
        if len(tables[name]) != manifest['counts'][name]:
            raise ValueError('Manifest count mismatch: ' + name)
    for job in tables['jobs']:
        if not isinstance(job, dict) or set(job) != _JOB_FIELDS:
            raise ValueError('Invalid job schema')
        if not isinstance(job['payload'], dict):
            raise ValueError('Invalid job payload: expected object')
        if job['run_id'] != manifest['run_id']:
            raise ValueError('Export row run attribution mismatch')
        expected_id = stable_id(job['run_id'], job['seed_id'], job['kind'],
                                job['url'], job['payload'].get('subject_id'))
        if job['id'] != expected_id:
            raise ValueError('Deterministic job ID mismatch')
        if (not _HEX_64.fullmatch(job['id']) or not _HEX_32.fullmatch(job['run_id'])
                or not _HEX_64.fullmatch(job['seed_id']) or job['kind'] not in {'roster', 'profile'}
                or not _http_url(job['url'])
                or job['status'] not in {'pending', 'running', 'done', 'blocked', 'failed',
                                         'unsupported', 'budget'}
                or type(job['attempts']) is not int or job['attempts'] < 0
                or job['reason'] is not None and not isinstance(job['reason'], str)
                or job['snapshot_id'] is not None
                and (not isinstance(job['snapshot_id'], str)
                     or not _HEX_32.fullmatch(job['snapshot_id']))
                or not isinstance(job['updated_at'], str) or not job['updated_at'].strip()):
            raise ValueError('Invalid job state or domain')
        if job['kind'] == 'roster' and job['payload'] != {}:
            raise ValueError('Invalid roster job payload')
        if (job['kind'] == 'profile'
                and (set(job['payload']) != {'subject_id', 'name'}
                     or not isinstance(job['payload']['subject_id'], str)
                     or not _HEX_64.fullmatch(job['payload']['subject_id'])
                     or not isinstance(job['payload']['name'], str)
                     or not job['payload']['name'].strip())):
            raise ValueError('Invalid profile job payload')
    for observation in tables['observations']:
        if (not isinstance(observation, dict) or set(observation) != _OBSERVATION_FIELDS
                or not _HEX_64.fullmatch(observation.get('id', ''))
                or not _HEX_32.fullmatch(observation.get('run_id', ''))
                or not _HEX_64.fullmatch(observation.get('job_id', ''))
                or not _HEX_32.fullmatch(observation.get('snapshot_id', ''))
                or observation.get('kind') not in {'candidate', 'claim', 'review', 'policy'}
                or not isinstance(observation.get('payload'), dict)):
            raise ValueError('Invalid observation schema or domain')
        if observation['run_id'] != manifest['run_id']:
            raise ValueError('Export row run attribution mismatch')
    for job in tables['jobs']:
        if job['seed_id'] not in seeds:
            raise ValueError('Job references unknown seed')
    for seed_id, seed in seeds.items():
        roots = [job for job in tables['jobs']
                 if job['seed_id'] == seed_id and job['kind'] == 'roster'
                 and job['url'] == seed['faculty_homepage'] and job['payload'] == {}]
        if len(roots) != 1:
            raise ValueError('Every seed requires exactly one homepage roster root job')
    for name in names:
        if name == 'snapshots':
            continue
        ids = [r['id'] for r in tables[name]]
        if len(ids) != len(set(ids)):
            raise ValueError('Duplicate record ID: ' + name)
    for snap in tables['snapshots']:
        try:
            retrieved_at = datetime.fromisoformat(snap.get('retrieved_at', ''))
            if (not isinstance(snap, dict) or set(snap) != _SNAPSHOT_FIELDS
                    or not isinstance(snap['id'], str) or not _HEX_32.fullmatch(snap['id'])
                    or not isinstance(snap['url'], str) or snap['url'] != canonical_url(snap['url'])
                    or not isinstance(snap['sha256'], str) or not _HEX_64.fullmatch(snap['sha256'])
                    or snap['path'] != f"raw/{snap['sha256'][:2]}/{snap['sha256']}.bin"
                    or not valid_snapshot_status(snap['status'])
                    or not isinstance(snap['content_type'], str) or not snap['content_type'].strip()
                    or not isinstance(snap['retrieved_at'], str) or not snap['retrieved_at'].strip()
                    or retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None):
                raise ValueError
        except (AttributeError, KeyError, TypeError, ValueError):
            raise ValueError('Invalid snapshot schema or domain') from None
        _safe_path(directory, snap['path'])
        required_files.add(snap['path'])
    snapshot_ids = [snap['id'] for snap in tables['snapshots']]
    if len(snapshot_ids) != len(set(snapshot_ids)):
        raise ValueError('Duplicate record ID: snapshots')
    if not required_files <= manifest['files'].keys():
        raise ValueError('Incomplete raw evidence hash inventory')
    for relative, expected in manifest['files'].items():
        data = _safe_path(directory, relative).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected['sha256'] or len(data) != expected['bytes']:
            raise ValueError('Bundle checksum mismatch: ' + relative)
    jobs = {r['id']: r for r in tables['jobs']}
    snapshots = {r['id']: r for r in tables['snapshots']}
    for observation in tables['observations']:
        payload = observation.get('payload')
        if not isinstance(payload, dict):
            raise ValueError('Invalid observation payload: expected object')
        expected_id = stable_id(observation['job_id'], observation['kind'], _json(payload))
        if observation.get('id') != expected_id:
            raise ValueError('Deterministic observation ID mismatch')
    referenced_snapshots = {row['snapshot_id'] for row in tables['observations']}
    referenced_snapshots.update(row['snapshot_id'] for row in tables['jobs'] if row['snapshot_id'])
    if set(snapshots) != referenced_snapshots:
        raise ValueError('Snapshot table does not exactly match referenced evidence')
    for snap in snapshots.values():
        raw = _safe_path(directory, snap['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != snap['sha256']:
            raise ValueError('Snapshot checksum mismatch')
    for job in tables['jobs']:
        if job['status'] == 'done' and job['snapshot_id'] is None:
            raise ValueError('Done job requires a snapshot')
        if job['snapshot_id'] is not None and job['snapshot_id'] not in snapshots:
            raise ValueError('Job snapshot reference missing')
        if (job['status'] == 'done'
                and not 200 <= snapshots[job['snapshot_id']]['status'] <= 299):
            raise ValueError('Snapshot/job status mismatch')
    policy_bindings = {(obs['job_id'], obs['snapshot_id']) for obs in tables['observations']
                       if obs['kind'] == 'policy'}
    for obs in tables['observations']:
        if obs['job_id'] not in jobs or obs['snapshot_id'] not in snapshots:
            raise ValueError('Observation evidence reference missing')
        if (obs['job_id'], obs['snapshot_id']) not in policy_bindings:
            raise ValueError('Observation snapshot does not match job snapshot')
        validate_observation_provenance(jobs[obs['job_id']], snapshots[obs['snapshot_id']],
                                        obs['kind'], obs['payload'])
    candidates = {r['payload']['subject_id'] for r in tables['candidates']}
    for record in tables['candidates'] + tables['claims']:
        payload = record['payload']
        if not payload.get('evidence_text') or not payload.get('locator'):
            raise ValueError('Missing claim evidence or locator')
        if record['kind'] == 'claim' and payload.get('subject_id') not in candidates:
            raise ValueError('Claim subject reference missing')
    derived = {'candidates': 'candidate', 'claims': 'claim', 'review': 'review', 'policies': 'policy'}
    for name, kind in derived.items():
        if tables[name] != [r for r in tables['observations'] if r['kind'] == kind]:
            raise ValueError('Derived table does not match observations')
    if (directory / 'candidates.csv').read_bytes() != _candidate_csv(tables['candidates']):
        raise ValueError('candidates.csv does not match candidate observations')
    expected_status = 'complete'
    if any(j['status'] != 'done' for j in tables['jobs']):
        expected_status = 'partial'
    elif tables['review'] or not tables['candidates']:
        expected_status = 'needs_review'
    if manifest['status'] != expected_status:
        raise ValueError('Manifest completion status mismatch')
    return manifest


def export_bundle(store, run_id):
    run = store.db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
    if run is None:
        raise ValueError('Unknown run')
    tables = {'jobs': store.rows('jobs', run_id), 'observations': store.rows('observations', run_id)}
    snapshot_ids = {r['snapshot_id'] for r in tables['observations']}
    snapshot_ids.update(r['snapshot_id'] for r in tables['jobs'] if r['snapshot_id'])
    tables['snapshots'] = [dict(store.db.execute('SELECT * FROM snapshots WHERE id=?', (sid,)).fetchone())
                           for sid in sorted(snapshot_ids)]
    for name, kind in {'candidates': 'candidate', 'claims': 'claim', 'review': 'review', 'policies': 'policy'}.items():
        tables[name] = [r for r in tables['observations'] if r['kind'] == kind]
    status = 'partial' if any(j['status'] != 'done' for j in tables['jobs']) else 'needs_review' if tables['review'] or not tables['candidates'] else 'complete'
    parent = store.root / 'exports'
    parent.mkdir(exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.staging-', dir=parent))
    final = parent / (run_id + '-' + uuid.uuid4().hex)
    try:
        for name, rows in tables.items():
            _write_rows(staging / (name + '.jsonl'), rows)
        with (staging / 'candidates.csv').open('xb') as handle:
            handle.write(_candidate_csv(tables['candidates']))
            handle.flush()
            os.fsync(handle.fileno())
        for snap in tables['snapshots']:
            source = _safe_path(store.root, snap['path'])
            target = _safe_path(staging, snap['path'])
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copyfile(source, target)
        files = {}
        for path in sorted(staging.rglob('*')):
            if path.is_file():
                data = path.read_bytes()
                files[str(path.relative_to(staging))] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        manifest = {'schema_version': 2, 'run_id': run_id, 'created_at': now(),
                    'fingerprint': run['fingerprint'], 'inputs': json.loads(run['inputs']),
                    'status': status, 'counts': {k: len(v) for k, v in tables.items()}, 'files': files}
        (staging / 'manifest.json').write_text(_json(manifest) + '\n')
        verify_bundle(staging)
        staging.rename(final)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return final
