import pytest

from talent_pipeline.extract import extract_roster


def test_implicit_list_item_end_tags_keep_each_roster_observation():
    result = extract_roster('<h2>Postdocs</h2><ul><li><a href="/james">James Adams</a><li><a href="/jane">Jane Doe</a></ul>', 'https://lab.example/')
    assert [r['name'] for r in result['candidates']] == ['James Adams', 'Jane Doe']
    assert result['review'] == []


@pytest.mark.parametrize('tail', [
    '(with <a href="/advisor">Other Advisor</a>)',
    '(PhD 2025, with <a href="/advisor">Other Advisor</a>), Research Scientist, Example Lab',
    '(PhD 2025), Research Scientist, Example Lab',
])
def test_roster_primary_person_is_not_confused_with_explicit_coadvisor_or_job_title(tail):
    result = extract_roster('<h2>Alumni</h2><li><a href="/jane">Jane Doe</a> ' + tail + '</li>', 'https://lab.example/')
    assert [r['name'] for r in result['candidates']] == ['Jane Doe']
    assert result['candidates'][0]['profile_url'] == 'https://lab.example/jane'


def test_group_heading_with_explicit_title_subsections_from_faculty_layout():
    html = '''<div><h3>Group</h3><div class="title">Postdocs</div>
    <ul><li><a href="/james">James Adams</a></li></ul>
    <div class="title">PhD Students</div><ul><li><a href="/jane">Jane Doe</a></li></ul>
    <div class="title">Alumni</div><ul><li><a href="/john">John Roe</a></li></ul></div>
    <h3>Publications</h3><li><a href="/coauthor">Other Author</a></li>'''
    result = extract_roster(html, 'https://lab.example/')
    assert [(r['name'], r['section'], r['relationship']) for r in result['candidates']] == [
        ('James Adams', 'Postdocs', 'postdoc'), ('Jane Doe', 'PhD Students', 'PhD'), ('John Roe', 'Alumni', 'alumni')]
    assert result['review'] == []


@pytest.mark.parametrize('section,descriptor,role', [('Postdocs', 'postdoc', 'postdoc'), ('Students', 'MSc student', 'MSc'), ('Alumni', '', 'alumni'), ('People', '', None), ('Visitors', '', 'visitor'), ('Team', '', 'member'), ('Members', '', 'member'), ('Students Supervised', '', 'student'), ('Former Students', '', 'alumni')])
def test_roster_sections_and_whole_token_roles(section, descriptor, role):
    result = extract_roster(f'<h2>{section}</h2><ul><li><a href="/james">James Adams</a> {descriptor}</li></ul>', 'https://lab.example/')
    assert result['candidates'][0]['relationship'] == role
    assert result['candidates'][0]['name'] == 'James Adams'


@pytest.mark.parametrize('block', [
    '<li><a href="/jane">Jane Doe</a> and <a href="/john">John Roe</a></li>',
    '<p>Several students are listed in the attached document.</p>',
    '<li>Jane Doe</li>',
    '<li><a href="/project">Research project</a></li>',
    '<li><a href="/jane">Jane Doe</a> and John Roe — students</li>',
    '<li><a href="/jane">Jane Doe</a>, John Roe — students</li>',
])
def test_ambiguous_roster_blocks_are_reviewed(block):
    result = extract_roster('<h2>People</h2>' + block, 'https://lab.example/')
    assert result['candidates'] == []
    assert len(result['review']) == 1
    assert result['review'][0]['evidence_text']
    assert result['review'][0]['locator']


@pytest.mark.parametrize('block', [
    '<table><tr><td><a href="/jane">Jane Doe</a></td><td>postdoc</td></tr></table>',
    '<div class="member-card"><h3><a href="/jane">Jane Doe</a></h3><p>postdoc</p></div>',
    '<li>Jane Doe — postdoc</li>',
])
def test_structured_roster_units(block):
    result = extract_roster('<h2>People</h2>' + block, 'https://lab.example/')
    assert len(result['candidates']) == 1
    assert result['candidates'][0]['name'] == 'Jane Doe'
    assert result['candidates'][0]['relationship'] == 'postdoc'
    assert result['review'] == []


def test_roster_scope_excludes_boilerplate_and_keeps_unsupported_content():
    html = '''<nav><h2>People</h2><li><a href="/fake">Fake Person</a></li></nav>
    <section><h2>People</h2><div>Unsupported roster text</div><li><a href="/real">Real Person</a><script>PhD</script></li></section>
    <li><a href="/outside">Outside Person</a></li>
    <h2>Publications</h2><li><a href="/author">Other Author</a></li>
    <footer><h2>Team</h2><li><a href="/footer">Footer Person</a></li></footer>'''
    result = extract_roster(html, 'https://lab.example/')
    assert [c['name'] for c in result['candidates']] == ['Real Person']
    assert result['candidates'][0]['relationship'] is None
    assert result['candidates'][0]['evidence_text'] == 'Real Person'
    assert [r['evidence_text'] for r in result['review']] == ['Unsupported roster text']


@pytest.mark.parametrize('href', ['javascript:alert(1)', 'https://user:pass@lab.example/jane', '/jane.pdf', 'data:text/plain,Jane', 'mailto:jane@example.com', 'http://[bad', 'https://lab.example/a.zip'])
def test_unsafe_roster_urls_reviewed(href):
    result = extract_roster(f'<h2>People</h2><li><a href="{href}">Jane Doe</a></li>', 'https://lab.example/')
    assert result['candidates'] == []
    assert result['review']


def test_relevant_same_origin_links_only():
    html = '''<nav><a href="/people#top">People</a><a href="/students">Students</a>
    <a href="https://other.example/team">Team</a><a href="/alumni.pdf">Alumni</a>
    <a href="javascript:alert(1)">Members</a><a href="/publications">Papers</a>
    <a href="/lab-members">Lab Members</a><a href="/team">Team</a></nav>'''
    assert extract_roster(html, 'https://lab.example/')['links'] == ['https://lab.example/people', 'https://lab.example/students', 'https://lab.example/lab-members', 'https://lab.example/team']


def test_profile_name_match_promotes_only_self_declared_link():
    from talent_pipeline.extract import extract_profile
    result = extract_profile('<title>Jane Doe | Research</title><h1>Jane Doe</h1><a href="https://github.com/jane#readme">GitHub</a>', 'https://jane.example/', 'Jane Doe')
    assert result['identity_status'] == 'name_matched'
    assert result['claims'] == [dict(kind='github_url', value='https://github.com/jane', evidence_text='GitHub', locator='a:nth-of-type(1)', verification_status='self_declared')]
    assert result['review'] == []


@pytest.mark.parametrize('heading', ['Jane Doerr', 'Other Person', 'Jane Doe Smith', 'Dr Jane Doe'])
def test_profile_other_name_not_substring_match(heading):
    from talent_pipeline.extract import extract_profile
    result = extract_profile(f'<title>{heading} | Research</title><h1>{heading}</h1><a href="https://github.com/jane">GitHub</a>', 'https://jane.example/', 'Jane Doe')
    assert result['identity_status'] == 'unresolved'
    assert result['claims'] == []
    assert result['review']


@pytest.mark.parametrize('href,label,kind', [
    ('https://www.linkedin.com/in/jane', 'LinkedIn', 'linkedin_url'),
    ('https://scholar.google.com/citations?user=abc', 'Google Scholar', 'google_scholar_url'),
    ('https://jane.example/about', 'Personal website', 'personal_website_url'),
    ('https://github.com/jane', 'My GitHub', 'github_url'),
])
def test_labelled_owned_profile_links(href, label, kind):
    from talent_pipeline.extract import extract_profile
    result = extract_profile(f'<h1>Jane Doe</h1><a href="{href}">{label}</a>', 'https://lab.example/jane', 'Jane Doe')
    assert [c['kind'] for c in result['claims']] == [kind]
    assert result['claims'][0]['verification_status'] == 'self_declared'


@pytest.mark.parametrize('block', [
    '<h2>Publications</h2><a href="https://github.com/other">GitHub</a>',
    '<section class="collaborators"><a href="https://github.com/other">GitHub</a></section>',
    '<p>Collaborator: <a href="https://github.com/other">GitHub</a></p>',
    '<nav><a href="https://github.com/lab">GitHub</a></nav>',
    '<a href="https://github.com.evil.test/jane">GitHub</a>',
    '<a href="https://linkedin.com.evil.test/in/jane">LinkedIn</a>',
    '<a href="https://github.com/other">Other Person</a>',
    '<a href="https://github.com/jane/research">GitHub</a>',
    '<style>PhD</style><script>Jane Doe works at Big Corp</script>',
])
def test_non_owned_or_spoofed_links_not_promoted(block):
    from talent_pipeline.extract import extract_profile
    result = extract_profile('<h1>Jane Doe</h1>' + block, 'https://lab.example/jane', 'Jane Doe')
    assert result['claims'] == []


@pytest.mark.parametrize('person', [
    {'@type': 'Person', 'name': 'Jane Doe', 'worksFor': {'@type': 'Organization', 'name': 'Example University'}, 'jobTitle': 'Researcher'},
    {'@type': 'Person', 'name': 'Jane Doe', 'jobTitle': 'Researcher'},
])
def test_exact_person_jsonld_employment_preserves_assertion(person):
    import json
    from talent_pipeline.extract import extract_profile
    raw = json.dumps({'@graph': [person, {'@type': 'Person', 'name': 'Other Person', 'worksFor': 'Wrong Org'}]})
    result = extract_profile(f'<h1>Jane Doe</h1><script type="application/ld+json">{raw}</script>', 'https://jane.example/', 'Jane Doe')
    assert len(result['claims']) == 1
    claim = result['claims'][0]
    assert claim['kind'] == 'employment'
    assert claim['value'] == {key: person[key] for key in ('worksFor', 'jobTitle') if key in person}
    assert claim['verification_status'] == 'self_declared'
    assert claim['evidence_text'] == raw
    assert claim['locator'] == 'script:nth-of-type(1)'


@pytest.mark.parametrize('sentence', ['I work at Example University as a researcher.', 'I am a research scientist at Example Lab.', 'I am affiliated with Example Institute.'])
def test_first_person_affiliation_kept_raw(sentence):
    from talent_pipeline.extract import extract_profile
    result = extract_profile(f'<h1>Jane Doe</h1><p>{sentence}</p>', 'https://jane.example/', 'Jane Doe')
    assert result['claims'] == [dict(kind='employment', value={'raw': sentence}, evidence_text=sentence, locator='p:nth-of-type(1)', verification_status='self_declared')]


@pytest.mark.parametrize('sentence', ['Jane works at Example University.', 'I study interesting problems.', 'I am interested in working at Example Lab.', 'My collaborator says: I work at Example University.', 'I used to work at Example University.'])
def test_non_explicit_affiliation_not_promoted(sentence):
    from talent_pipeline.extract import extract_profile
    assert extract_profile(f'<h1>Jane Doe</h1><p>{sentence}</p>', 'https://jane.example/', 'Jane Doe')['claims'] == []


def test_roster_ignores_publication_and_coauthor_containers():
    html = '<h2>People</h2><section class="publications"><li><a href="/other">Other Person</a></li></section><div id="coauthors"><li><a href="/other">Other Person</a></li></div><li><a href="/james">James Adams</a> postdoc</li>'
    result = extract_roster(html, 'https://lab.example/')
    assert [c['name'] for c in result['candidates']] == ['James Adams']
    assert result['review'] == []


def test_roster_can_resume_after_publications_heading():
    html = '<h2>Publications</h2><li><a href="/other">Other Person</a></li><h2>People</h2><li><a href="/jane">Jane Doe</a></li>'
    assert [c['name'] for c in extract_roster(html, 'https://lab.example/')['candidates']] == ['Jane Doe']


def test_unsupported_roster_definition_list_is_reviewed():
    result = extract_roster('<h2>People</h2><dl><dt>Jane Doe</dt><dd>Member bio</dd></dl>', 'https://lab.example/')
    assert result['candidates'] == []
    assert result['review']
    assert result['review'][0]['evidence_text'] == 'Jane Doe Member bio'


def test_source_local_results_never_deduplicate_across_calls():
    html = '<h2>People</h2><li><a href="https://jane.example/">Jane Doe</a> postdoc</li>'
    observations = [extract_roster(html, source)['candidates'][0] for source in ('https://one.example/', 'https://two.example/')]
    assert len(observations) == 2
    assert observations[0] == observations[1]
    assert observations[0] is not observations[1]
    assert 'identity_id' not in observations[0]


@pytest.mark.parametrize('hidden', ['<div hidden><h1>Jane Doe</h1></div>', '<script><h1>Jane Doe</h1></script>', '<style>Jane Doe</style>'])
def test_hidden_or_script_name_cannot_unlock_claims(hidden):
    from talent_pipeline.extract import extract_profile
    result = extract_profile(hidden + '<a href="https://github.com/jane">GitHub</a>', 'https://jane.example/', 'Jane Doe')
    assert result['identity_status'] == 'unresolved'
    assert result['claims'] == []


@pytest.mark.parametrize('descriptor', ['msearch', 'msculpture', 'phdynamics'])
def test_degree_substrings_are_not_roles(descriptor):
    result = extract_roster(f'<h2>People</h2><li><a href="/james">James Adams</a> {descriptor}</li>', 'https://lab.example/')
    assert result['candidates'][0]['relationship'] is None


def test_locators_refer_to_original_dom_and_evidence_excludes_hidden_text():
    html = '<h2>People</h2><ul><li hidden>Hidden Person</li><li><a href="/jane">Jane Doe</a><span hidden>PhD</span> postdoc</li></ul>'
    result = extract_roster(html, 'https://lab.example/')
    assert result['candidates'][0]['locator'] == 'ul:nth-of-type(1) > li:nth-of-type(2)'
    assert result['candidates'][0]['evidence_text'] == 'Jane Doe postdoc'
    assert result['candidates'][0]['relationship'] == 'postdoc'


def test_card_one_named_link_with_social_link_is_unambiguous():
    html = '<h2>People</h2><div class="card"><a href="/jane">Jane Doe</a> postdoc <a href="https://github.com/jane">GitHub</a></div>'
    result = extract_roster(html, 'https://lab.example/')
    assert [c['name'] for c in result['candidates']] == ['Jane Doe']
    assert result['candidates'][0]['profile_url'] == 'https://lab.example/jane'
    assert result['review'] == []


def test_bare_roster_text_is_preserved_for_review():
    result = extract_roster('<h2>People</h2>Jane Doe, unknown formatting<br>John Roe', 'https://lab.example/')
    assert result['candidates'] == []
    assert [r['evidence_text'] for r in result['review']] == ['Jane Doe, unknown formatting', 'John Roe']
    assert all(r['locator'] for r in result['review'])


def test_navigation_discovery_uses_visible_label_even_for_generic_path():
    html = '<nav><a href="/index.html">People</a></nav>'
    assert extract_roster(html, 'https://lab.example/')['links'] == ['https://lab.example/index.html']


@pytest.mark.parametrize('wrapper', [
    '<template>{}</template>', '<noscript>{}</noscript>', '<div inert>{}</div>',
    '<div style="display:none">{}</div>',
    '<div style=" DISPLAY : NONE !important ">{}</div>',
    '<div style="visibility: hidden ! IMPORTANT">{}</div>',
    '<div style="visibility:collapse">{}</div>',
    '<div style="display:var(--display)">{}</div>',
    '<div style="visibility:var(--visible)">{}</div>',
    '<div style="visibility:unknown">{}</div>',
    '<div style="display:n\\\\6f ne">{}</div>',
    '<div style="opacity:0%">{}</div>',
    '<div style="content-visibility:hidden">{}</div>',
    '<div style="clip:rect(0, 0, 0, 0)">{}</div>',
    '<div style="clip-path:inset(50%)">{}</div>',
    '<div style="width:0; overflow:hidden">{}</div>',
    '<div style="height:0; overflow:clip">{}</div>',
])
def test_nonvisible_evidence_is_review_only(wrapper):
    from talent_pipeline.extract import extract_profile
    roster = extract_roster('<h2>People</h2>' + wrapper.format('<li><a href="/fake">Fake Person</a> postdoc</li>'), 'https://lab.example/')
    assert roster['candidates'] == []
    assert any('Fake Person' in r['evidence_text'] and 'visibility' in r['reason'] for r in roster['review'])
    profile = extract_profile(wrapper.format('<h1>Jane Doe</h1>') + '<p>I work at Wrong Org.</p>', 'https://lab.example/jane', 'Jane Doe')
    assert profile['identity_status'] == 'unresolved'
    assert profile['claims'] == []
    assert any('Jane Doe' in r['evidence_text'] for r in profile['review'])
    claims = extract_profile('<h1>Jane Doe</h1>' + wrapper.format('<p>I work at Wrong Org.</p><a href="https://github.com/wrong">GitHub</a>'), 'https://lab.example/jane', 'Jane Doe')
    assert claims['claims'] == []
    assert any('Wrong Org' in r['evidence_text'] for r in claims['review'])


@pytest.mark.parametrize('primary', [
    '<title>Jane Doe</title><h1>John Roe</h1>',
    '<title>John Roe | Research</title><h1>Jane Doe</h1>',
    '<h1>Jane Doe</h1><h1>John Roe</h1>',
])
def test_conflicting_primary_identity_cannot_unlock_claims(primary):
    from talent_pipeline.extract import extract_profile
    result = extract_profile(primary + '<p>I work at Other Org.</p><script type="application/ld+json">{"@type":"Person","name":"Jane Doe","worksFor":"Other Org"}</script>', 'https://lab.example/jane', 'Jane Doe')
    assert result['identity_status'] == 'unresolved'
    assert result['claims'] == []
    assert any('conflict' in r['reason'] for r in result['review'])


@pytest.mark.parametrize('block', [
    '<section><h2>John Roe</h2><p>I work at Other Org.</p><a href="https://github.com/john">GitHub</a></section>',
    '<h2>John Roe</h2><p>I work at Other Org.</p><a href="https://github.com/john">GitHub</a>',
])
def test_separately_identified_person_claims_are_review_only(block):
    from talent_pipeline.extract import extract_profile
    result = extract_profile('<h1>Jane Doe</h1><p>I work at Jane Org.</p>' + block, 'https://lab.example/jane', 'Jane Doe')
    assert result['identity_status'] == 'name_matched'
    assert [c['value'] for c in result['claims']] == [{'raw': 'I work at Jane Org.'}]
    assert any('Other Org' in r['evidence_text'] and 'owner' in r['reason'] for r in result['review'])


def test_people_list_keeps_visible_evidence():
    result = extract_roster('<h2>People</h2><ul><li><a href="/jane#bio">Jane Doe</a> — PhD student</li></ul>', 'https://lab.example/people')
    assert result['candidates'] == [dict(name='Jane Doe', profile_url='https://lab.example/jane', section='People', relationship='PhD', evidence_text='Jane Doe — PhD student', locator='ul:nth-of-type(1) > li:nth-of-type(1)')]
    assert result['review'] == []


@pytest.mark.parametrize('markup', [
    '<details><li><a href="/fake">Fake Person</a> postdoc</li></details>',
    '<details><summary>People</summary><li><a href="/fake">Fake Person</a> postdoc</li></details>',
    '<details open><details><li><a href="/fake">Fake Person</a> postdoc</li></details></details>',
    '<details><li><a href="/fake">Fake Person</a><li><a href="/other">Other Person</a></li></li></details>',
])
def test_closed_details_roster_content_is_review_only(markup):
    result = extract_roster('<h2>People</h2>' + markup, 'https://lab.example/')
    assert result['candidates'] == []
    assert result['links'] == []
    assert any('Fake Person' in row['evidence_text'] and row['reason'] == 'hidden_visibility'
               and row['locator'] for row in result['review'])


@pytest.mark.parametrize('open_attribute', ['open', 'OPEN', 'open=""', 'open="false"'])
def test_open_details_roster_content_is_processed(open_attribute):
    result = extract_roster(
        f'<h2>People</h2><details {open_attribute}><li><a href="/jane">Jane Doe</a> postdoc</li></details>',
        'https://lab.example/',
    )
    assert [row['name'] for row in result['candidates']] == ['Jane Doe']


def test_closed_details_profile_identity_and_claim_are_review_only_but_open_is_processed():
    from talent_pipeline.extract import extract_profile
    closed = extract_profile(
        '<title>Jane Doe</title><details><h1>Jane Doe</h1><p>I work at Hidden Org.</p></details>',
        'https://lab.example/jane', 'Jane Doe',
    )
    assert closed['identity_status'] == 'name_matched'
    assert closed['claims'] == []
    assert any('Hidden Org' in row['evidence_text'] and row['reason'] == 'hidden_visibility'
               and row['locator'] for row in closed['review'])

    opened = extract_profile(
        '<title>Jane Doe</title><details OPEN><h1>Jane Doe</h1><p>I work at Visible Org.</p></details>',
        'https://lab.example/jane', 'Jane Doe',
    )
    assert [row['value'] for row in opened['claims']] == [{'raw': 'I work at Visible Org.'}]


def test_closed_outer_details_hides_nested_open_details_profile_content():
    from talent_pipeline.extract import extract_profile
    result = extract_profile(
        '<h1>Jane Doe</h1><details><summary>More</summary><details open>'
        '<p>I work at Hidden Org.</p></details></details>',
        'https://lab.example/jane', 'Jane Doe',
    )
    assert result['claims'] == []
    assert any('Hidden Org' in row['evidence_text'] for row in result['review'])


def test_closed_dialog_profile_content_is_review_only_and_cannot_supply_identity():
    from talent_pipeline.extract import extract_profile
    hidden_claims = extract_profile(
        '<h1>Jane Doe</h1><dialog><p>I work at Wrong Org.</p>'
        '<a href="https://github.com/wrong">GitHub</a></dialog>',
        'https://lab.example/jane', 'Jane Doe',
    )
    assert hidden_claims['claims'] == []
    assert any(row['reason'] == 'hidden_visibility' and 'Wrong Org' in row['evidence_text']
               and row['locator'] for row in hidden_claims['review'])
    hidden_identity = extract_profile(
        '<dialog><h1>Jane Doe</h1></dialog><p>I work at Wrong Org.</p>',
        'https://lab.example/jane', 'Jane Doe',
    )
    assert hidden_identity['identity_status'] == 'unresolved'
    assert hidden_identity['claims'] == []


@pytest.mark.parametrize('open_attribute', ['open', 'OPEN', 'open=""', 'open="false"'])
def test_open_dialog_profile_content_is_processed(open_attribute):
    from talent_pipeline.extract import extract_profile
    result = extract_profile(
        f'<h1>Jane Doe</h1><dialog {open_attribute}><p>I work at Visible Org.</p></dialog>',
        'https://lab.example/jane', 'Jane Doe',
    )
    assert [row['value'] for row in result['claims']] == [{'raw': 'I work at Visible Org.'}]


def test_closed_dialog_hides_nested_open_dialog_and_malformed_roster_items():
    profile = __import__('talent_pipeline.extract', fromlist=['extract_profile']).extract_profile(
        '<h1>Jane Doe</h1><dialog><dialog open><p>I work at Hidden Org.</p></dialog></dialog>',
        'https://lab.example/jane', 'Jane Doe',
    )
    assert profile['claims'] == []
    roster = extract_roster(
        '<h2>People</h2><dialog><li><a href="/fake">Fake Person</a>'
        '<li><a href="/other">Other Person</a></li></li></dialog>',
        'https://lab.example/',
    )
    assert roster['candidates'] == []
    assert roster['links'] == []
    assert any('Fake Person' in row['evidence_text'] and row['locator'] for row in roster['review'])


@pytest.mark.parametrize('region', [
    '<section aria-label="John Roe">{}</section>',
    '<article aria-label="John Roe">{}</article>',
    '<main aria-label="John Roe">{}</main>',
    '<aside aria-label="John Roe">{}</aside>',
    '<div aria-label="John Roe">{}</div>',
    '<section aria-labelledby="john-label"><h2 id="john-label">John Roe</h2>{}</section>',
])
def test_different_person_accessible_region_is_review_only(region):
    from talent_pipeline.extract import extract_profile
    content = '<p>I work at Wrong Org.</p><a href="https://github.com/wrong">GitHub</a>'
    result = extract_profile('<h1>Jane Doe</h1>' + region.format(content),
                             'https://lab.example/jane', 'Jane Doe')
    assert result['claims'] == []
    assert any(row['reason'] == 'other_person_owner' and row['locator']
               for row in result['review'])


@pytest.mark.parametrize('label_attribute', [
    'aria-label="Jane Doe"',
    'aria-labelledby="jane-label"',
    'aria-label="Research"',
    'aria-label="About"',
    'aria-label="Profile"',
    'aria-label="Publications"',
])
def test_expected_or_generic_accessible_region_does_not_create_other_owner(label_attribute):
    from talent_pipeline.extract import extract_profile
    label = '<h2 id="jane-label">Jane Doe</h2>' if 'labelledby' in label_attribute else ''
    result = extract_profile(
        f'<h1>Jane Doe</h1><section {label_attribute}>{label}'
        '<p>I work at Right Org.</p></section>',
        'https://lab.example/jane', 'Jane Doe',
    )
    assert [row['value'] for row in result['claims']] == [{'raw': 'I work at Right Org.'}]


def test_accessible_person_regions_use_nearest_visible_owner_boundary():
    from talent_pipeline.extract import extract_profile
    result = extract_profile(
        '<h1>Jane Doe</h1><section aria-label="John Roe">'
        '<p>I work at Wrong Org.</p><div aria-label="Jane Doe">'
        '<p>I work at Right Org.</p></div></section>'
        '<section aria-label="Jane Doe"><div aria-label="John Roe">'
        '<a href="https://github.com/wrong">GitHub</a></div></section>',
        'https://lab.example/jane', 'Jane Doe',
    )
    assert [row['value'] for row in result['claims']] == [{'raw': 'I work at Right Org.'}]
    assert sum(row['reason'] == 'other_person_owner' for row in result['review']) == 2


def test_hidden_aria_labelledby_heading_cannot_override_visible_owner():
    from talent_pipeline.extract import extract_profile
    result = extract_profile(
        '<h1>Jane Doe</h1><section aria-label="John Roe"><div aria-labelledby="jane-label">'
        '<h2 id="jane-label" hidden>Jane Doe</h2><p>I work at Wrong Org.</p></div></section>',
        'https://lab.example/jane', 'Jane Doe',
    )
    assert result['claims'] == []
    assert any(row['reason'] == 'ownership_unknown' and 'Wrong Org' in row['evidence_text']
               for row in result['review'])


def test_accessible_region_label_never_establishes_primary_identity():
    from talent_pipeline.extract import extract_profile
    result = extract_profile(
        '<section aria-label="Jane Doe"><p>I work at Wrong Org.</p></section>',
        'https://lab.example/jane', 'Jane Doe',
    )
    assert result['identity_status'] == 'unresolved'
    assert result['claims'] == []


@pytest.mark.parametrize('attribute', ['popover', 'popover=""', 'popover="auto"',
                                       'popover="manual"', 'popover="hint"',
                                       'popover="custom"'])
def test_static_popover_roster_content_is_review_only(attribute):
    html = (f'<h2>People</h2><div {attribute}><li><a href="/fake">Fake Person</a>'
            '<li><a href="/other">Other Person</a></li></li>'
            '<a href="/team">Team</a></div>')
    result = extract_roster(html, 'https://lab.example/')
    assert result['candidates'] == []
    assert result['links'] == []
    reviews = [row for row in result['review'] if 'Fake Person' in row['evidence_text']]
    assert len(reviews) == 1
    assert reviews[0]['reason'] == 'hidden_visibility'
    assert reviews[0]['locator'] == 'div:nth-of-type(1)'


def test_nested_popovers_and_popover_inside_hidden_ancestor_have_one_outer_review():
    result = extract_roster(
        '<h2>People</h2><div popover><span popover><li><a href="/fake">Fake Person</a>'
        '</li></span></div><section hidden><div popover><li><a href="/other">Other Person</a>'
        '</li></div></section>',
        'https://lab.example/',
    )
    assert result['candidates'] == []
    assert len([row for row in result['review'] if 'Fake Person' in row['evidence_text']]) == 1
    assert len([row for row in result['review'] if 'Other Person' in row['evidence_text']]) == 1


def test_static_popover_profile_identity_claim_and_link_are_review_only():
    from talent_pipeline.extract import extract_profile
    hidden_identity = extract_profile(
        '<div popover><h1>Jane Doe</h1></div><p>I work at Wrong Org.</p>',
        'https://lab.example/jane', 'Jane Doe',
    )
    assert hidden_identity['identity_status'] == 'unresolved'
    assert hidden_identity['claims'] == []
    result = extract_profile(
        '<h1>Jane Doe</h1><div popover="manual"><p>I work at Wrong Org.</p>'
        '<a href="https://github.com/wrong">GitHub</a></div>',
        'https://lab.example/jane', 'Jane Doe',
    )
    assert result['claims'] == []
    assert len([row for row in result['review'] if 'Wrong Org' in row['evidence_text']]) == 1


def test_data_popover_is_not_treated_as_native_popover():
    result = extract_roster(
        '<h2>People</h2><div data-popover><li><a href="/jane">Jane Doe</a> postdoc</li></div>',
        'https://lab.example/',
    )
    assert [row['name'] for row in result['candidates']] == ['Jane Doe']
    assert result['review'] == []


@pytest.mark.parametrize('region', [
    '<ul role="region" aria-label="John Roe">{}</ul>',
    '<span role="GROUP" aria-label="John Roe">{}</span>',
    '<ul role="banner   ReGiOn complementary" aria-label="John Roe">{}</ul>',
    '<span role="group" aria-labelledby="john-owner"><em id="john-owner">John Roe</em>{}</span>',
])
def test_role_owned_other_person_content_is_review_only_for_any_tag(region):
    from talent_pipeline.extract import extract_profile
    content = '<p>I work at Wrong Org.</p><a href="https://github.com/wrong">GitHub</a>'
    result = extract_profile('<h1>Jane Doe</h1>' + region.format(content),
                             'https://lab.example/jane', 'Jane Doe')
    assert result['claims'] == []
    assert any(row['reason'] == 'other_person_owner' for row in result['review'])


@pytest.mark.parametrize('owner', [
    '<ul role="region" aria-label="Jane Doe">{}</ul>',
    '<span role="group" aria-label="Research">{}</span>',
])
def test_expected_or_generic_role_label_does_not_create_other_owner(owner):
    from talent_pipeline.extract import extract_profile
    markup = '<p>I work at Right Org.</p>'
    result = extract_profile('<h1>Jane Doe</h1>' + owner.format(markup),
                             'https://lab.example/jane', 'Jane Doe')
    assert [row['value'] for row in result['claims']] == [{'raw': 'I work at Right Org.'}]


def test_nearest_role_owner_wins_and_arbitrary_labelled_anchor_is_not_owner():
    from talent_pipeline.extract import extract_profile
    result = extract_profile(
        '<h1>Jane Doe</h1><ul role="region" aria-label="John Roe">'
        '<li><span role="group" aria-label="Jane Doe"><p>I work at Right Org.</p></span></li>'
        '</ul><a aria-label="John Roe"><p>I work at Also Right Org.</p></a>',
        'https://lab.example/jane', 'Jane Doe',
    )
    assert [row['value'] for row in result['claims']] == [
        {'raw': 'I work at Right Org.'}, {'raw': 'I work at Also Right Org.'},
    ]


def test_claim_node_itself_is_an_accessible_ownership_boundary():
    from talent_pipeline.extract import extract_profile
    result = extract_profile(
        '<h1>Jane Doe</h1><p role="region" aria-label="John Roe">I work at Wrong Org.</p>'
        '<p role="region" aria-label="Jane Doe">I work at Right Org.</p>',
        'https://lab.example/jane', 'Jane Doe',
    )
    assert [row['value'] for row in result['claims']] == [{'raw': 'I work at Right Org.'}]
    assert any(row['reason'] == 'other_person_owner' and 'Wrong Org' in row['evidence_text']
               for row in result['review'])


@pytest.mark.parametrize('ids', ['first last', 'last first'])
def test_aria_labelledby_uses_the_combined_accessible_name_in_token_order(ids):
    from talent_pipeline.extract import extract_profile
    result = extract_profile(
        f'<h1>Jane Doe</h1><span id="first">John</span><span id="last">Roe</span>'
        f'<p role="region" aria-labelledby="{ids}">I work at Wrong Org.</p>',
        'https://lab.example/jane', 'Jane Doe',
    )
    assert result['claims'] == []
    assert any(row['reason'] == 'other_person_owner' for row in result['review'])


def test_combined_aria_labelledby_expected_name_authorizes_claim():
    from talent_pipeline.extract import extract_profile
    result = extract_profile(
        '<h1>Jane Doe</h1><span id="first">Jane</span><span id="last">Doe</span>'
        '<p role="region" aria-labelledby="first last">I work at Right Org.</p>',
        'https://lab.example/jane', 'Jane Doe',
    )
    assert [row['value'] for row in result['claims']] == [{'raw': 'I work at Right Org.'}]


@pytest.mark.parametrize('ids', ['first missing', 'first hidden', 'first first'])
def test_incomplete_hidden_or_duplicate_aria_labelledby_is_not_authoritative(ids):
    from talent_pipeline.extract import extract_profile
    result = extract_profile(
        f'<h1>Jane Doe</h1><span id="first">Jane</span><span id="hidden" hidden>Doe</span>'
        f'<p role="region" aria-labelledby="{ids}">I work at Uncertain Org.</p>',
        'https://lab.example/jane', 'Jane Doe',
    )
    assert result['claims'] == []
    assert any(row['reason'] == 'ownership_unknown' for row in result['review'])


def test_presentational_headings_cannot_establish_identity_or_ownership():
    from talent_pipeline.extract import extract_profile
    unresolved = extract_profile(
        '<h1 role="presentation">Jane Doe</h1><p>I work at Wrong Org.</p>',
        'https://lab.example/jane', 'Jane Doe',
    )
    assert unresolved['identity_status'] == 'unresolved'
    assert unresolved['claims'] == []

    owned = extract_profile(
        '<h1>Jane Doe</h1><h2 role="none">John Roe</h2><p>I work at Right Org.</p>',
        'https://lab.example/jane', 'Jane Doe',
    )
    assert [row['value'] for row in owned['claims']] == [{'raw': 'I work at Right Org.'}]


@pytest.mark.parametrize('selector,attribute', [
    ('.hidden', 'class="hidden"'),
    ('#fake', 'id="fake"'),
])
def test_embedded_stylesheet_hidden_roster_evidence_is_review_only(selector, attribute):
    result = extract_roster(
        f'<style>{selector} {{ display: none; }}</style><h2>People</h2>'
        f'<li {attribute}><a href="/fake">Fake Person</a> postdoc</li>',
        'https://lab.example/',
    )
    assert result['candidates'] == []
    assert any(row['reason'] == 'hidden_visibility' and 'Fake Person' in row['evidence_text']
               for row in result['review'])


@pytest.mark.parametrize('declarations', [
    'clip: rect(0 0 0 0)',
    'clip-path: inset(50%)',
    'width: 0px; overflow: hidden',
    'height: 0; overflow-y: clip',
])
def test_embedded_stylesheet_common_clipping_is_review_only(declarations):
    result = extract_roster(
        f'<style>.hidden {{ {declarations}; }}</style><h2>People</h2>'
        '<li class="hidden"><a href="/fake">Fake Person</a> postdoc</li>',
        'https://lab.example/',
    )
    assert result['candidates'] == []
    assert any(row['reason'] == 'hidden_visibility' and 'Fake Person' in row['evidence_text']
               for row in result['review'])


@pytest.mark.parametrize('stylesheet', [
    '.uncertain { display: var(--display); }',
    'li.hidden { display: none; }',
    '@media (max-width: 1000px) { .uncertain { display: none; } }',
    '@import url("/site.css");',
])
def test_ambiguous_embedded_stylesheet_cannot_promote_roster_evidence(stylesheet):
    result = extract_roster(
        f'<style>{stylesheet}</style><h2>People</h2>'
        '<li class="uncertain hidden"><a href="/fake">Fake Person</a> postdoc</li>',
        'https://lab.example/',
    )
    assert result['candidates'] == []
    assert any(row['reason'] == 'ambiguous_visibility' and 'Fake Person' in row['evidence_text']
               for row in result['review'])


@pytest.mark.parametrize('stylesheet', [
    '.hidden { --open: "/*"; display: none; --close: "*/"; }',
    ".hidden { --open: '/*'; display: none; --close: '*/'; }",
    '.hidden { --escaped: "quote\\\"/*"; display: none; }',
    '.hidden { /* real comment */ display: none; }',
])
def test_css_comment_markers_inside_strings_do_not_hide_real_visibility_declarations(stylesheet):
    result = extract_roster(
        f'<style>{stylesheet}</style><h2>People</h2>'
        '<li class="hidden"><a href="/fake">Fake Person</a> postdoc</li>',
        'https://lab.example/',
    )
    assert result['candidates'] == []
    assert any(row['reason'] == 'hidden_visibility' and 'Fake Person' in row['evidence_text']
               for row in result['review'])


@pytest.mark.parametrize('stylesheet', [
    '.hidden { display: none; /* unterminated',
    '.hidden { --value: "unterminated; display: none; }',
    '.hidden { --value: "escaped at end\\',
])
def test_malformed_css_strings_and_comments_fail_closed_to_review(stylesheet):
    result = extract_roster(
        f'<style>{stylesheet}</style><h2>People</h2>'
        '<li class="hidden"><a href="/fake">Fake Person</a> postdoc</li>',
        'https://lab.example/',
    )
    assert result['candidates'] == []
    assert any(row['reason'] == 'ambiguous_visibility' and 'Fake Person' in row['evidence_text']
               for row in result['review'])


@pytest.mark.parametrize('style', [
    '--open: "/*"; display: none; --close: "*/";',
    'display: none; /* real comment */',
])
def test_inline_css_comment_scanning_is_string_aware(style):
    result = extract_roster(
        f'<h2>People</h2><li style=\'{style}\'><a href="/fake">Fake Person</a></li>',
        'https://lab.example/',
    )
    assert result['candidates'] == []
    assert any(row['reason'] == 'hidden_visibility' and 'Fake Person' in row['evidence_text']
               for row in result['review'])


@pytest.mark.parametrize('style', ['display: none; /*', '--value: "unterminated'])
def test_malformed_inline_css_fails_closed_to_review(style):
    result = extract_roster(
        f'<h2>People</h2><li style=\'{style}\'><a href="/fake">Fake Person</a></li>',
        'https://lab.example/',
    )
    assert result['candidates'] == []
    assert any(row['reason'] == 'ambiguous_visibility' and 'Fake Person' in row['evidence_text']
               for row in result['review'])


def test_unresolved_linked_stylesheet_cannot_promote_roster_evidence():
    result = extract_roster(
        '<link rel="stylesheet" href="/site.css"><h2>People</h2>'
        '<li><a href="/fake">Fake Person</a> postdoc</li>',
        'https://lab.example/',
    )
    assert result['candidates'] == []
    assert any(row['reason'] == 'ambiguous_visibility' and 'Fake Person' in row['evidence_text']
               for row in result['review'])


@pytest.mark.parametrize('labels', [
    '<span id="owner">Jane Doe</span><span id="owner">John Roe</span>',
    '<span id="owner">John Roe</span><span id="owner">Jane Doe</span>',
])
def test_duplicate_global_aria_labelledby_ids_fail_closed_in_any_order(labels):
    from talent_pipeline.extract import extract_profile
    result = extract_profile(
        '<h1>Jane Doe</h1><section aria-label="Jane Doe">' + labels
        + '<p role="region" aria-labelledby="owner">I work at Uncertain Org.</p></section>',
        'https://lab.example/jane', 'Jane Doe',
    )
    assert result['claims'] == []
    assert any(row['reason'] == 'ownership_unknown' and 'Uncertain Org' in row['evidence_text']
               for row in result['review'])


@pytest.mark.parametrize('label_node', [
    '',
    '<span id="owner" hidden>Jane Doe</span>',
    '<span id="owner" role="presentation">Jane Doe</span>',
])
def test_unresolved_nearest_aria_owner_cannot_fall_through_to_expected_outer_owner(label_node):
    from talent_pipeline.extract import extract_profile
    result = extract_profile(
        '<h1>Jane Doe</h1><section aria-label="Jane Doe">' + label_node
        + '<p role="region" aria-labelledby="owner">I work at Uncertain Org.</p></section>',
        'https://lab.example/jane', 'Jane Doe',
    )
    assert result['claims'] == []
    assert any(row['reason'] == 'ownership_unknown' and 'Uncertain Org' in row['evidence_text']
               for row in result['review'])
