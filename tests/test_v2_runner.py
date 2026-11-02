"""Orchestration fixtures intentionally use invented .example pages, not real candidates."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from talent_pipeline.store import Store


class FixtureFetcher:
    approved_origins = {'https://a.example', 'https://b.example', 'https://alice.example'}
    delay_seconds = 0.0
    timeout = 15.0
    max_bytes = 2_000_000
    max_redirects = 5

    def __init__(self):
        self.calls = []

    def fetch(self, url, **kwargs):
        self.calls.append(url)
        return {'status': 'ok', 'url': url, 'body': b'fixture page', 'status_code': 200,
                'content_type': 'text/html', 'reason': None, 'policy': [], 'redirects': []}


def roster_fixture(html, url):
    return {'candidates': [{'name': 'Alice Example', 'profile_url': 'https://alice.example/',
                           'section': 'Alumni', 'relationship': 'alumni',
                           'evidence_text': 'Alice Example', 'locator': 'li:1'}],
            'links': [], 'review': []}


def profile_fixture(html, url, expected_name):
    return {'identity_status': 'name_matched', 'claims': [{'kind': 'employment',
            'value': {'raw': 'I work at Example Lab.'}, 'evidence_text': 'I work at Example Lab.',
            'locator': 'p:1', 'verification_status': 'self_declared'}], 'review': []}


class OrchestrationTests(unittest.TestCase):
    def test_retry_then_success_retains_each_attempt_and_finishes(self):
        from talent_pipeline.runner import collect, Config
        from talent_pipeline.export import export_bundle, verify_bundle

        class RetryFetcher(FixtureFetcher):
            def fetch(self, url, **kwargs):
                result = super().fetch(url, **kwargs)
                if len(self.calls) == 1:
                    return {**result, 'status': 'failed', 'reason': 'timeout',
                            'body': b'', 'status_code': 0}
                return result

        seed = {'faculty_name': 'Faculty A', 'faculty_institution': 'Example University',
                'faculty_homepage': 'https://a.example/', 'terms_approved': True,
                'scope_path': '/'}
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp)) as store:
            run = collect(store, [seed], RetryFetcher(), Config(max_attempts=2),
                          roster_parser=roster_fixture, profile_parser=profile_fixture)
            root = next(row for row in store.rows('jobs', run) if row['kind'] == 'roster')
            policies = [row for row in store.rows('observations', run)
                        if row['job_id'] == root['id'] and row['kind'] == 'policy']
            self.assertEqual((root['status'], root['attempts']), ('done', 2))
            self.assertEqual(sorted(row['payload']['attempt'] for row in policies), [1, 2])
            self.assertEqual(len({row['snapshot_id'] for row in policies}), 2)
            self.assertEqual(root['snapshot_id'], next(
                row['snapshot_id'] for row in policies if row['payload']['attempt'] == 2))
            self.assertEqual(verify_bundle(export_bundle(store, run))['status'], 'complete')

    def test_retry_then_failure_terminates_without_stuck_running_job(self):
        from talent_pipeline.runner import collect, Config

        class FailingFetcher(FixtureFetcher):
            def fetch(self, url, **kwargs):
                result = super().fetch(url, **kwargs)
                return {**result, 'status': 'failed', 'reason': 'timeout',
                        'body': b'', 'status_code': 0}

        seed = {'faculty_name': 'Faculty A', 'faculty_institution': 'Example University',
                'faculty_homepage': 'https://a.example/', 'terms_approved': True,
                'scope_path': '/'}
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp)) as store:
            run = collect(store, [seed], FailingFetcher(), Config(max_attempts=2,
                          max_pages_per_seed=2), roster_parser=roster_fixture,
                          profile_parser=profile_fixture)
            job = store.rows('jobs', run)[0]
            policies = [row for row in store.rows('observations', run)
                        if row['kind'] == 'policy']
            self.assertEqual((job['status'], job['attempts']), ('failed', 2))
            self.assertEqual(sorted(row['payload']['attempt'] for row in policies), [1, 2])
            self.assertEqual(len({row['snapshot_id'] for row in policies}), 2)
            self.assertNotEqual(job['status'], 'running')

    def test_empty_roster_self_links_and_known_link_cycles_need_review(self):
        from talent_pipeline.runner import collect
        from talent_pipeline.export import export_bundle, verify_bundle
        for cycle in [False, True]:
            class HtmlFetcher(FixtureFetcher):
                def fetch(self, url, **kwargs):
                    result = super().fetch(url, **kwargs)
                    target = '/students' if cycle and url.endswith('/people') else '/people'
                    return {**result, 'body': ('<nav><a href="' + target + '">People</a></nav><main><div id="app"></div></main>').encode()}
            seed = {'faculty_name': 'Faculty A', 'faculty_institution': 'Example University',
                    'faculty_homepage': 'https://a.example/people', 'terms_approved': True, 'scope_path': '/'}
            with self.subTest(cycle=cycle), tempfile.TemporaryDirectory() as tmp, Store(Path(tmp)) as store:
                fetcher = HtmlFetcher()
                run = collect(store, [seed], fetcher)
                self.assertEqual(len(fetcher.calls), 2 if cycle else 1)
                observations = store.rows('observations', run)
                self.assertTrue(any(r['kind'] == 'review' and r['payload']['reason'] == 'no_supported_roster' for r in observations))
                manifest = verify_bundle(export_bundle(store, run))
                self.assertEqual(manifest['counts']['candidates'], 0)
                self.assertEqual(manifest['status'], 'needs_review')


    def test_failed_fetches_consume_the_same_page_budget_as_successes(self):
        from talent_pipeline.runner import collect, Config
        class FailingFetcher(FixtureFetcher):
            def fetch(self, url, **kwargs):
                result = super().fetch(url, **kwargs)
                return {**result, 'status': 'failed', 'reason': 'timeout', 'body': b''}
        seed = {'faculty_name': 'Faculty A', 'faculty_institution': 'Example University',
                'faculty_homepage': 'https://a.example/', 'terms_approved': True, 'scope_path': '/'}
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp)) as store:
            fetcher = FailingFetcher()
            run = collect(store, [seed], fetcher, Config(max_pages_per_seed=1),
                          roster_parser=roster_fixture, profile_parser=profile_fixture)
            self.assertEqual(len(fetcher.calls), 1)
            self.assertEqual(store.rows('jobs', run)[0]['status'], 'budget')

    def test_budgeted_retry_does_not_refund_previous_failed_attempts(self):
        from talent_pipeline.runner import collect, Config
        class MixedFetcher(FixtureFetcher):
            def fetch(self, url, **kwargs):
                result = super().fetch(url, **kwargs)
                return {**result, 'status': 'failed', 'reason': 'timeout'} if url.endswith('/one') else result
        def linked_roster(html, url):
            return {'candidates': [], 'review': [], 'links': ['https://a.example/one', 'https://a.example/two']}
        seed = {'faculty_name': 'Faculty A', 'faculty_institution': 'Example University',
                'faculty_homepage': 'https://a.example/', 'terms_approved': True, 'scope_path': '/'}
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp)) as store:
            fetcher = MixedFetcher()
            collect(store, [seed], fetcher, Config(max_pages_per_seed=2),
                    roster_parser=linked_roster, profile_parser=profile_fixture)
            self.assertEqual(fetcher.calls, ['https://a.example/', 'https://a.example/one'])

    def test_changed_transport_limits_do_not_silently_resume_an_old_run(self):
        from talent_pipeline.runner import collect, Config
        seed = {'faculty_name': 'Faculty A', 'faculty_institution': 'Example University',
                'faculty_homepage': 'https://a.example/', 'terms_approved': True, 'scope_path': '/'}
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp)) as store:
            fetcher = FixtureFetcher()
            fetcher.max_bytes = 1000
            first = collect(store, [seed], fetcher, Config(), roster_parser=roster_fixture, profile_parser=profile_fixture)
            fetcher.max_bytes = 2000
            second = collect(store, [seed], fetcher, Config(), roster_parser=roster_fixture, profile_parser=profile_fixture)
            self.assertNotEqual(first, second)

    def test_equal_text_two_faculty_sources_keep_separate_provenance_and_resume(self):
        self.assertIsNotNone(importlib.util.find_spec('talent_pipeline.runner'), 'v2 runner must exist')
        from talent_pipeline.runner import collect, Config
        seeds = [{'faculty_name': name, 'faculty_institution': 'Example University',
                  'faculty_homepage': f'https://{host}.example/', 'terms_approved': True, 'scope_path': '/'}
                 for name, host in [('Faculty A', 'a'), ('Faculty B', 'b')]]
        with tempfile.TemporaryDirectory() as tmp:
            with Store(Path(tmp)) as store:
                fetcher = FixtureFetcher()
                run = collect(store, seeds, fetcher, Config(), roster_parser=roster_fixture, profile_parser=profile_fixture)
                observations = store.rows('observations', run)
                candidates = [r for r in observations if r['kind'] == 'candidate']
                claims = [r for r in observations if r['kind'] == 'claim']
                self.assertEqual(len(candidates), 2)
                self.assertEqual(len(claims), 2)
                self.assertEqual(len({r['payload']['subject_id'] for r in candidates}), 2)
                self.assertEqual({r['payload']['faculty_name'] for r in candidates}, {'Faculty A', 'Faculty B'})
                self.assertEqual({r['payload']['subject_id'] for r in candidates}, {r['payload']['subject_id'] for r in claims})
                self.assertTrue(all(r['snapshot_id'] for r in observations))
                before = list(fetcher.calls)
                self.assertEqual(collect(store, seeds, fetcher, Config(), roster_parser=roster_fixture, profile_parser=profile_fixture), run)
                self.assertEqual(fetcher.calls, before)

    def test_candidate_extraction_cap_marks_job_and_bundle_partial(self):
        from talent_pipeline.runner import collect, Config
        from talent_pipeline.export import export_bundle, verify_bundle
        seed = {'faculty_name': 'Faculty A', 'faculty_institution': 'Example University',
                'faculty_homepage': 'https://a.example/', 'terms_approved': True, 'scope_path': '/'}

        def oversized_roster(html, url):
            return {'links': [], 'review': [], 'candidates': [
                {'name': name, 'profile_url': profile, 'section': 'People', 'relationship': 'postdoc',
                 'evidence_text': name, 'locator': f'li:{index}'}
                for index, (name, profile) in enumerate([
                    ('Alice Example', 'https://alice.example/'),
                    ('Other Example', 'https://other.example/'),
                ], 1)
            ]}

        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp)) as store:
            run = collect(store, [seed], FixtureFetcher(), Config(max_candidates_per_page=1),
                          roster_parser=oversized_roster, profile_parser=profile_fixture)
            jobs = store.rows('jobs', run)
            observations = store.rows('observations', run)
            self.assertEqual(len([row for row in observations if row['kind'] == 'candidate']), 1)
            self.assertEqual(len([row for row in jobs if row['kind'] == 'profile']), 1)
            self.assertTrue(any(row['status'] == 'budget' and row['reason'] == 'extraction_budget_exhausted'
                                for row in jobs))
            self.assertTrue(any(row['kind'] == 'review' and row['payload']['reason'] == 'extraction_budget_exhausted'
                                for row in observations))
            self.assertEqual(verify_bundle(export_bundle(store, run))['status'], 'partial')

    def test_link_extraction_cap_retains_bounded_child_and_marks_partial(self):
        from talent_pipeline.runner import collect, Config
        from talent_pipeline.export import export_bundle, verify_bundle
        seed = {'faculty_name': 'Faculty A', 'faculty_institution': 'Example University',
                'faculty_homepage': 'https://a.example/', 'terms_approved': True, 'scope_path': '/'}

        def oversized_links(html, url):
            if url == seed['faculty_homepage']:
                return {'candidates': [], 'review': [],
                        'links': ['https://a.example/one', 'https://a.example/two']}
            return {'candidates': [], 'links': [],
                    'review': [{'reason': 'fixture_end', 'evidence_text': 'end', 'locator': 'document'}]}

        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp)) as store:
            fetcher = FixtureFetcher()
            run = collect(store, [seed], fetcher, Config(max_links_per_page=1),
                          roster_parser=oversized_links, profile_parser=profile_fixture)
            jobs = store.rows('jobs', run)
            observations = store.rows('observations', run)
            self.assertEqual({row['url'] for row in jobs}, {'https://a.example/', 'https://a.example/one'})
            self.assertEqual(fetcher.calls, ['https://a.example/', 'https://a.example/one'])
            self.assertTrue(any(row['status'] == 'budget' and row['reason'] == 'extraction_budget_exhausted'
                                for row in jobs))
            self.assertTrue(any(row['kind'] == 'review' and row['payload']['reason'] == 'extraction_budget_exhausted'
                                for row in observations))
            self.assertEqual(verify_bundle(export_bundle(store, run))['status'], 'partial')
