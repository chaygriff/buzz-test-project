"""Operator CLI; deliberately separate from the historical v1 entry points."""
import argparse
import csv
import json
import posixpath
import sys
from pathlib import Path
from urllib.parse import urlsplit
from talent_pipeline.export import export_bundle, verify_bundle
from talent_pipeline.network import canonical_url
from talent_pipeline.runner import Config, collect
from talent_pipeline.store import Store


def load_seeds(path):
    seeds = []
    seen = set()
    with Path(path).open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        required = {'faculty_name', 'faculty_institution', 'faculty_homepage', 'terms_approved'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('Seed CSV requires ' + ', '.join(sorted(required)))
        for line, row in enumerate(reader, 2):
            if len(seeds) >= 250:
                raise ValueError('Seed limit is 250 per invocation')
            if row.get('terms_approved') != 'true':
                raise ValueError(f'Line {line}: terms_approved must explicitly be true after operator review')
            if any(not isinstance(row.get(key), str) or not row[key].strip() for key in required):
                raise ValueError(f'Line {line}: empty required field')
            raw_url = row['faculty_homepage']
            parsed = urlsplit(raw_url)
            if raw_url != raw_url.strip() or parsed.query or parsed.fragment:
                raise ValueError(f'Line {line}: invalid public seed URL')
            try:
                url = canonical_url(raw_url)
            except ValueError:
                raise ValueError(f'Line {line}: invalid public seed URL') from None
            parsed = urlsplit(url)
            path = parsed.path
            scope = row.get('scope_path') or (path if path.endswith('/') else posixpath.dirname(path).rstrip('/') + '/')
            normalized_scope = posixpath.normpath(scope)
            normalized_scope = '/' if normalized_scope == '/' else normalized_scope.rstrip('/') + '/'
            normalized_path = posixpath.normpath(path)
            if (not scope.startswith('/') or scope != normalized_scope
                    or normalized_path != scope.rstrip('/') and not normalized_path.startswith(scope)):
                raise ValueError(f'Line {line}: scope_path must be an absolute directory path')
            key = (row['faculty_name'], row['faculty_institution'], url)
            if key in seen:
                raise ValueError(f'Line {line}: duplicate faculty seed')
            seen.add(key)
            seeds.append({'faculty_name': row['faculty_name'], 'faculty_institution': row['faculty_institution'],
                          'faculty_homepage': url, 'terms_approved': True, 'scope_path': scope})
    if not seeds:
        raise ValueError('Seed CSV is empty')
    return seeds


def main(argv=None):
    parser = argparse.ArgumentParser(description='Evidence-first talent collection pipeline v2')
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('run', help='Start/resume bounded discovery and linked-profile enrichment')
    run.add_argument('--seeds', type=Path, required=True)
    run.add_argument('--state', type=Path, required=True)
    run.add_argument('--approve-origin', action='append', default=[], help='Additional profile origin whose terms the operator has reviewed')
    run.add_argument('--new-run', action='store_true', help='Explicit refresh; keeps previous evidence and runs')
    run.add_argument('--max-pages-per-seed', type=int, default=8)
    run.add_argument('--max-profiles-per-seed', type=int, default=10)
    run.add_argument('--max-attempts', type=int, default=2)
    run.add_argument('--delay-seconds', type=float, default=1.0)
    run.add_argument('--timeout', type=float, default=15.0)
    run.add_argument('--max-bytes', type=int, default=2_000_000)
    verify = commands.add_parser('verify', help='Validate an exported bundle without network requests')
    verify.add_argument('bundle', type=Path)
    export = commands.add_parser('export', help='Export an existing run without network requests')
    export.add_argument('--state', type=Path, required=True)
    export.add_argument('--run-id', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'verify':
            manifest = verify_bundle(args.bundle)
            print(json.dumps({'verified': True, 'run_id': manifest['run_id'], 'status': manifest['status'], 'counts': manifest['counts']}, sort_keys=True))
            return 0
        if args.command == 'run':
            from talent_pipeline.network import Fetcher, origin
            seeds = load_seeds(args.seeds)
            approved = {origin(s['faculty_homepage']) for s in seeds}
            for value in args.approve_origin:
                if value.rstrip('/') != origin(value):
                    raise ValueError('--approve-origin requires an origin, not a path or query')
                approved.add(origin(value))
            config = Config(max_pages_per_seed=args.max_pages_per_seed,
                            max_profiles_per_seed=args.max_profiles_per_seed, max_attempts=args.max_attempts)
            fetcher = Fetcher(approved, delay_seconds=args.delay_seconds, timeout=args.timeout, max_bytes=args.max_bytes)
            with Store(args.state) as store:
                run_id = collect(store, seeds, fetcher, config, new_run=args.new_run)
                bundle = export_bundle(store, run_id)
        else:
            with Store(args.state) as store:
                bundle = export_bundle(store, args.run_id)
        manifest = verify_bundle(bundle)
        print(json.dumps({'bundle': str(bundle.resolve()), 'run_id': manifest['run_id'],
                          'status': manifest['status'], 'counts': manifest['counts']}, sort_keys=True))
        return 2 if manifest['status'] == 'partial' else 0
    except (ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({'error': str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
