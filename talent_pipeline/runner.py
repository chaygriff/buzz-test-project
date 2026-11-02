"""Bounded orchestration: durable jobs, source-local identities and explicit outcomes."""
import json
import posixpath
from dataclasses import asdict, dataclass
from urllib.parse import urldefrag, urlsplit
from bs4 import UnicodeDammit
from talent_pipeline.store import stable_id


@dataclass(frozen=True)
class Config:
    max_pages_per_seed: int = 8
    max_profiles_per_seed: int = 10
    max_attempts: int = 2
    max_candidates_per_page: int = 200
    max_links_per_page: int = 50
    parser_version: str = '2.0.0'

    def __post_init__(self):
        for key, value in asdict(self).items():
            if key != 'parser_version' and (type(value) is not int or not 1 <= value <= 1000):
                raise ValueError(key + ' must be an integer between 1 and 1000')
        if type(self.parser_version) is not str or not self.parser_version.strip():
            raise ValueError('parser_version must be a nonempty string')


def _origin(url):
    parsed = urlsplit(url)
    return parsed.scheme.lower() + '://' + parsed.netloc.lower()


def _seed_id(seed):
    return stable_id(seed['faculty_name'], seed['faculty_institution'], seed['faculty_homepage'])


def _in_scope(url, seed):
    if _origin(url) != _origin(seed['faculty_homepage']):
        return False
    path = posixpath.normpath(urlsplit(url).path)
    scope = seed.get('scope_path', '/')
    return path == scope.rstrip('/') or path.startswith(scope)


def collect(store, seeds, fetcher, config=None, *, new_run=False, roster_parser=None, profile_parser=None):
    config = config or Config()
    if roster_parser is None or profile_parser is None:
        from talent_pipeline.extract import extract_roster, extract_profile
        roster_parser = roster_parser or extract_roster
        profile_parser = profile_parser or extract_profile
    if not seeds:
        raise ValueError('At least one seed is required')
    for seed in seeds:
        if seed.get('terms_approved') is not True:
            raise ValueError('Every faculty seed requires explicit terms approval')
    seed_by_id = {_seed_id(seed): seed for seed in seeds}
    inputs = {'seeds': sorted(seeds, key=_seed_id), 'config': asdict(config),
              'approved_origins': sorted(fetcher.approved_origins), 'pipeline_version': 2,
              'transport': {key: getattr(fetcher, key, None) for key in
                            ('delay_seconds', 'timeout', 'max_bytes', 'max_redirects')}}
    from talent_pipeline.export import _validate_inputs
    _validate_inputs(inputs)
    run_id = store.open_run(inputs, new_run=new_run)
    store.recover(run_id)
    for seed_id, seed in seed_by_id.items():
        store.enqueue(run_id, seed_id, 'roster', seed['faculty_homepage'])
    while (job := store.claim(run_id)) is not None:
        seed = seed_by_id[job['seed_id']]
        budget = config.max_pages_per_seed if job['kind'] == 'roster' else config.max_profiles_per_seed
        consumed = store.db.execute("SELECT coalesce(sum(attempts),0) FROM jobs WHERE run_id=? AND seed_id=? AND kind=?",
                                    (run_id, job['seed_id'], job['kind'])).fetchone()[0]
        if consumed > budget:
            store.db.execute('UPDATE jobs SET attempts=attempts-1 WHERE id=?', (job['id'],))
            store.finish(job['id'], 'budget', 'page_or_profile_budget_exhausted',
                         snapshot_id=job['snapshot_id'])
            continue
        if job['attempts'] > config.max_attempts:
            store.finish(job['id'], 'failed', 'attempt_budget_exhausted_after_interruption',
                         snapshot_id=job['snapshot_id'])
            continue
        kwargs = {'scope_origin': _origin(seed['faculty_homepage']), 'scope_path': seed.get('scope_path', '/')} if job['kind'] == 'roster' else {}
        result = fetcher.fetch(job['url'], **kwargs)
        body = result.get('body', b'')
        if result['status'] != 'ok':
            # Retain a policy/transport receipt even when no content can be fetched.
            body = json.dumps({k: v for k, v in result.items() if k != 'body'}, sort_keys=True, ensure_ascii=False).encode()
        snap = store.snapshot(result['url'], body, result.get('status_code') or 0,
                              result['content_type'] if result['status'] == 'ok' else 'application/json')
        policy = {'source_url': result['url'], 'request_url': job['url'],
                  'result_url': result['url'], 'attempt': job['attempts'],
                  'outcome': result['status'], 'reason': result.get('reason'),
                  'policy': result.get('policy', []), 'redirects': result.get('redirects', [])}
        observations = [('policy', policy)]
        if result['status'] != 'ok':
            status = result['status']
            if status == 'failed' and job['attempts'] < config.max_attempts:
                status = 'pending'
            store.finish(job['id'], status, result.get('reason'), snap['id'], observations)
            continue
        common = {'source_url': result['url'], 'faculty_name': seed['faculty_name'],
                  'faculty_institution': seed['faculty_institution'], 'faculty_homepage': seed['faculty_homepage'],
                  'retrieved_at': snap['retrieved_at'], 'parser_version': config.parser_version}
        children = []
        finish_status = 'done'
        finish_reason = None
        try:
            decoded = UnicodeDammit(body, is_html=True)
            if decoded.unicode_markup is None or decoded.contains_replacement_characters:
                raise ValueError('HTML decoding is ambiguous')
            html = decoded.unicode_markup
            if job['kind'] == 'roster':
                extracted = roster_parser(html, result['url'])
                candidates = extracted['candidates']
                if len(candidates) > config.max_candidates_per_page or len(extracted['links']) > config.max_links_per_page:
                    finish_status = 'budget'
                    finish_reason = 'extraction_budget_exhausted'
                    observations.append(('review', {**common, 'reason': 'extraction_budget_exhausted', 'locator': 'document'}))
                for candidate in candidates[:config.max_candidates_per_page]:
                    # Deliberately source-local: a shared name or shared evidence never merges people.
                    subject_id = stable_id(job['seed_id'], candidate['name'].casefold(),
                                           candidate.get('profile_url') or (result['url'], candidate['locator']))
                    observations.append(('candidate', {**candidate, **common, 'subject_id': subject_id,
                                                        'identity_status': 'roster_observation'}))
                    if candidate.get('profile_url'):
                        children.append({'kind': 'profile', 'url': urldefrag(candidate['profile_url'])[0],
                                         'payload': {'subject_id': subject_id, 'name': candidate['name']}})
                    else:
                        observations.append(('review', {**common, 'subject_id': subject_id,
                                                        'reason': 'missing_profile_url', 'locator': candidate['locator']}))
                known_urls = {r['url'] for r in store.rows('jobs', run_id)
                              if r['seed_id'] == job['seed_id'] and r['kind'] == 'roster'}
                known_urls.update((urldefrag(job['url'])[0], urldefrag(result['url'])[0]))
                discovered = False
                for url in extracted['links'][:config.max_links_per_page]:
                    url = urldefrag(url)[0]
                    if _in_scope(url, seed) and url not in known_urls:
                        children.append({'kind': 'roster', 'url': url})
                        known_urls.add(url)
                        discovered = True
                if not candidates and not discovered and not extracted['review']:
                    observations.append(('review', {**common, 'reason': 'no_supported_roster', 'locator': 'document'}))
            else:
                subject = job['payload']
                extracted = profile_parser(html, result['url'], subject['name'])
                if extracted['identity_status'] != 'name_matched':
                    observations.append(('review', {**common, 'subject_id': subject['subject_id'],
                                                    'reason': 'profile_identity_unresolved', 'locator': 'document'}))
                else:
                    for claim in extracted['claims']:
                        observations.append(('claim', {**claim, **common, 'subject_id': subject['subject_id'],
                                                       'identity_status': 'name_matched', 'verification_status': 'self_declared'}))
                    if not any(c['kind'] == 'employment' for c in extracted['claims']):
                        observations.append(('review', {**common, 'subject_id': subject['subject_id'],
                                                        'reason': 'employment_unknown', 'locator': 'document'}))
            observations.extend(('review', {**item, **common}) for item in extracted['review'])
        except (ValueError, UnicodeError) as exc:
            store.finish(job['id'], 'failed', 'extraction_error: ' + str(exc), snap['id'], observations)
            continue
        store.finish(job['id'], finish_status, finish_reason, snapshot_id=snap['id'],
                     observations=observations, children=children)
    return run_id
