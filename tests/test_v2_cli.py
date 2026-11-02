import importlib.util
import tempfile
import unittest
from pathlib import Path

import pytest


class SeedContractTests(unittest.TestCase):
    def test_file_homepage_defaults_scope_to_single_root_slash(self):
        from talent_pipeline.cli import load_seeds
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'seeds.csv'
            source.write_text('faculty_name,faculty_institution,faculty_homepage,terms_approved\nFaculty A,Example,https://lab.example/index.html,true\n')
            self.assertEqual(load_seeds(source)[0]['scope_path'], '/')

    def test_seed_csv_requires_explicit_terms_approval_before_collection(self):
        self.assertIsNotNone(importlib.util.find_spec('talent_pipeline.cli'), 'v2 CLI must exist')
        from talent_pipeline.cli import load_seeds
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'seeds.csv'
            source.write_text('faculty_name,faculty_institution,faculty_homepage,terms_approved\nFaculty A,Example,https://lab.example/~a/,false\n')
            with self.assertRaisesRegex(ValueError, 'terms'):
                load_seeds(source)
            source.write_text(source.read_text().replace(',false', ',true'))
            seeds = load_seeds(source)
            self.assertEqual(seeds[0]['scope_path'], '/~a/')
            self.assertIs(seeds[0]['terms_approved'], True)


def _write_seeds(tmp_path, rows, extra_header=''):
    source = tmp_path / 'seeds.csv'
    source.write_text('faculty_name,faculty_institution,faculty_homepage,terms_approved'
                      + extra_header + '\n' + '\n'.join(rows) + '\n')
    return source


def test_seed_homepage_is_canonicalized_before_storage_and_identity(tmp_path):
    from talent_pipeline.cli import load_seeds
    source = _write_seeds(
        tmp_path,
        ['Faculty A,Example,https://A.EXAMPLE:443,true'],
    )
    assert load_seeds(source) == [{
        'faculty_name': 'Faculty A', 'faculty_institution': 'Example',
        'faculty_homepage': 'https://a.example/', 'terms_approved': True,
        'scope_path': '/',
    }]


@pytest.mark.parametrize('homepage', [
    'https://a.example/?view=full',
    'https://a.example/#bio',
])
def test_seed_homepage_rejects_query_and_fragment(tmp_path, homepage):
    from talent_pipeline.cli import load_seeds
    source = _write_seeds(tmp_path, [f'Faculty A,Example,{homepage},true'])
    with pytest.raises(ValueError, match='invalid public seed URL'):
        load_seeds(source)


def test_semantically_duplicate_canonical_seed_is_rejected(tmp_path):
    from talent_pipeline.cli import load_seeds
    source = _write_seeds(tmp_path, [
        'Faculty A,Example,https://a.example,true',
        'Faculty A,Example,https://A.EXAMPLE/,true',
    ])
    with pytest.raises(ValueError, match='duplicate faculty seed'):
        load_seeds(source)


@pytest.mark.parametrize('scope', ['/lab/../other/', '/other/', '//lab/'])
def test_explicit_seed_scope_is_normalized_and_contains_homepage(tmp_path, scope):
    from talent_pipeline.cli import load_seeds
    source = _write_seeds(
        tmp_path, [f'Faculty A,Example,https://a.example/lab/person,true,{scope}'],
        ',scope_path',
    )
    with pytest.raises(ValueError, match='scope_path'):
        load_seeds(source)
