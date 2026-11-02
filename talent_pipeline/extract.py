"""Conservative source-local extraction from static HTML and inline styles.

This does not emulate browser-computed CSS. Static HTML has no reliable source
attribute for the runtime ``:popover-open`` state, so native popovers and other
unsupported visibility remain review-only.
"""
import json
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from bs4.element import Comment, NavigableString, Tag


def _css_without_comments(css):
    """Remove CSS comments without interpreting markers inside strings."""
    output = []
    index = 0
    quote = None
    while index < len(css):
        char = css[index]
        if quote is not None:
            output.append(char)
            if char == '\\':
                index += 1
                if index >= len(css):
                    raise ValueError('unterminated CSS escape')
                output.append(css[index])
            elif char == quote:
                quote = None
            elif char in '\r\n\f':
                raise ValueError('unterminated CSS string')
        elif char in {'"', "'"}:
            quote = char
            output.append(char)
        elif css.startswith('/*', index):
            end = css.find('*/', index + 2)
            if end < 0:
                raise ValueError('unterminated CSS comment')
            output.append(' ')
            index = end + 1
        else:
            output.append(char)
        index += 1
    if quote is not None:
        raise ValueError('unterminated CSS string')
    return ''.join(output)


def _css_split(css, delimiter):
    """Split on one CSS delimiter only when outside a quoted string."""
    parts = []
    start = 0
    quote = None
    index = 0
    while index < len(css):
        char = css[index]
        if quote is not None:
            if char == '\\':
                index += 1
            elif char == quote:
                quote = None
        elif char in {'"', "'"}:
            quote = char
        elif char == delimiter:
            parts.append(css[start:index])
            start = index + 1
        index += 1
    parts.append(css[start:])
    return parts


def _css_rules(css):
    """Parse flat CSS rules; nested rules and at-rules are unsupported."""
    rules = []
    index = 0
    while index < len(css):
        while index < len(css) and css[index].isspace():
            index += 1
        if index == len(css):
            break
        selector_start = index
        quote = None
        while index < len(css):
            char = css[index]
            if quote is not None:
                if char == '\\':
                    index += 1
                elif char == quote:
                    quote = None
            elif char in {'"', "'"}:
                quote = char
            elif char == '{':
                break
            elif char in '}@':
                raise ValueError('unsupported CSS rule')
            index += 1
        if index == len(css) or not css[selector_start:index].strip():
            raise ValueError('malformed CSS rule')
        selector = css[selector_start:index]
        index += 1
        declarations_start = index
        quote = None
        while index < len(css):
            char = css[index]
            if quote is not None:
                if char == '\\':
                    index += 1
                elif char == quote:
                    quote = None
            elif char in {'"', "'"}:
                quote = char
            elif char == '}':
                break
            elif char in '{@':
                raise ValueError('unsupported CSS rule')
            index += 1
        if index == len(css):
            raise ValueError('malformed CSS rule')
        rules.append((selector, css[declarations_start:index]))
        index += 1
    return rules


def _style_visibility_reason(style):
    try:
        style = _css_without_comments(style).lower()
    except ValueError:
        return 'ambiguous_visibility'
    if any(token in style for token in '{}'):
        return 'ambiguous_visibility'
    reason = None
    zero_size = False
    clipped_overflow = False
    for declaration in _css_split(style, ';'):
        if not declaration.strip():
            continue
        parts = _css_split(declaration, ':')
        if len(parts) < 2:
            return 'ambiguous_visibility'
        key = parts[0].strip()
        value = ':'.join(parts[1:]).strip()
        value = re.sub(r'\s*!\s*important\s*$', '', value).strip()
        if (key == 'display' and value == 'none' or key == 'visibility' and value in {'hidden', 'collapse'}
                or key == 'content-visibility' and value == 'hidden' or key == 'opacity' and value in {'0', '0.0'}):
            return 'hidden_visibility'
        if (key == 'clip' and value not in {'auto', 'none', 'initial'}
                or key == 'clip-path' and value not in {'none', 'initial'}):
            return 'hidden_visibility'
        if key in {'width', 'height'} and re.fullmatch(r'[+-]?(?:0+(?:\.0*)?|\.0+)(?:px|em|rem|%|vh|vw|vmin|vmax)?', value):
            zero_size = True
        if key in {'overflow', 'overflow-x', 'overflow-y'} and value in {'hidden', 'clip'}:
            clipped_overflow = True
        supported = {
            'display': {'block', 'inline', 'inline-block', 'flex', 'inline-flex', 'grid', 'inline-grid',
                        'contents', 'flow-root', 'list-item', 'table', 'inline-table', 'table-row',
                        'table-cell', 'table-row-group', 'table-header-group', 'table-footer-group',
                        'table-column', 'table-column-group', 'table-caption', 'initial'},
            'visibility': {'visible', 'initial'},
            'content-visibility': {'visible', 'initial'},
        }
        if key in supported and value not in supported[key]:
            reason = 'ambiguous_visibility'
        if key == 'opacity':
            if not re.fullmatch(r'(?:\d+(?:\.\d*)?|\.\d+)%?', value):
                reason = 'ambiguous_visibility'
            elif float(value.rstrip('%')) == 0:
                return 'hidden_visibility'
    return 'hidden_visibility' if zero_size and clipped_overflow else reason


def _visibility_reason(node):
    stylesheet_reason = node.__dict__.get('_stylesheet_visibility_reason')
    if stylesheet_reason is not None:
        return stylesheet_reason
    if (node.name in {'template', 'noscript'}
            or any(node.has_attr(key) for key in ('hidden', 'inert', 'popover'))
            or str(node.get('aria-hidden', '')).strip().lower() == 'true'):
        return 'hidden_visibility'
    return _style_visibility_reason(str(node.get('style', '')))


def _mark_stylesheet_reason(node, reason):
    current = node.__dict__.get('_stylesheet_visibility_reason')
    if current != 'hidden_visibility':
        node.__dict__['_stylesheet_visibility_reason'] = reason


def _prepare_stylesheet_visibility(soup):
    """Resolve a deliberately small static CSS subset, otherwise fail closed."""
    globally_ambiguous = any(
        'stylesheet' in {str(token).casefold() for token in link.get('rel', [])}
        for link in soup.find_all('link')
    )
    for sheet in soup.find_all('style'):
        try:
            css = _css_without_comments(sheet.get_text())
            rules = _css_rules(css)
        except ValueError:
            globally_ambiguous = True
            continue
        relevant = bool(re.search(
            r'(?i)(?:display|visibility|content-visibility|opacity|clip|clip-path|width|height|overflow|overflow-x|overflow-y)\s*:',
            css,
        ))
        if not relevant:
            continue
        for selector_text, declarations in rules:
            reason = _style_visibility_reason(declarations)
            if reason is None:
                continue
            targets = []
            for selector in selector_text.split(','):
                selector = selector.strip()
                match = re.fullmatch(r'([.#])([A-Za-z_][A-Za-z0-9_-]*)', selector)
                if match is None:
                    globally_ambiguous = True
                    targets = []
                    break
                if match[1] == '.':
                    targets.extend(soup.find_all(class_=match[2]))
                else:
                    targets.extend(soup.find_all(id=match[2]))
            for target in targets:
                _mark_stylesheet_reason(target, reason)
    if globally_ambiguous:
        roots = [node for node in soup.find_all(True, recursive=False)
                 if node.name not in {'style', 'link'}]
        for root in roots:
            _mark_stylesheet_reason(root, 'ambiguous_visibility')


def _closed_details(node):
    """Return the closed details element hiding node, excluding its summary."""
    child = node
    for ancestor in node.parents:
        if ancestor.name == 'details' and not ancestor.has_attr('open'):
            summaries = ancestor.find_all('summary', recursive=False)
            if not summaries or child is not summaries[0]:
                return ancestor
        child = ancestor
    return None


def _closed_dialog(node):
    """Return the outermost closed dialog containing node."""
    closed = None
    for ancestor in [node, *node.parents]:
        if ancestor.name == 'dialog' and not ancestor.has_attr('open'):
            closed = ancestor
    return closed


def _visibility(node):
    if _closed_details(node) is not None or _closed_dialog(node) is not None:
        return 'hidden_visibility'
    return next((reason for ancestor in [node, *node.parents]
                 if (reason := _visibility_reason(ancestor))), None)


def _visibility_reviews(soup):
    reviews = [dict(reason=_visibility_reason(node), evidence_text=' '.join(
        str(text).strip() for text in node.find_all(string=True)
        if not isinstance(text, Comment)), locator=_locator(node))
        for node in soup.find_all(True) if _visibility_reason(node)
        and not any(_visibility_reason(parent) for parent in node.parents)]
    reviews.extend(dict(reason='hidden_visibility', evidence_text=' '.join(
        str(text).strip() for text in node.find_all(string=True)
        if not isinstance(text, Comment) and _closed_details(text.parent) is node),
        locator=_locator(node))
        for node in soup.find_all('details') if not node.has_attr('open')
        and _closed_details(node) is None)
    reviews.extend(dict(reason='hidden_visibility', evidence_text=' '.join(
        str(text).strip() for text in node.find_all(string=True)
        if not isinstance(text, Comment) and _closed_dialog(text.parent) is node),
        locator=_locator(node))
        for node in soup.find_all('dialog') if not node.has_attr('open')
        and not any(parent.name == 'dialog' and not parent.has_attr('open') for parent in node.parents)
        and _closed_details(node) is None)
    return reviews


def _text(node):
    return ' '.join(' '.join(
        str(text) for text in node.find_all(string=True)
        if text.__class__.__name__ not in {'Comment', 'Doctype'}
        and not any(parent.name in {'script', 'style'} for parent in text.parents)
        and _visibility(text.parent) is None
    ).split())


def _locator(node):
    original = node.__dict__.get('_evidence_locator')
    if original is not None:
        return original
    parts = []
    while node and node.name != '[document]':
        index = 1 + sum(s.name == node.name for s in node.previous_siblings if getattr(s, 'name', None))
        parts.append(f'{node.name}:nth-of-type({index})')
        node = node.parent
    return ' > '.join(reversed(parts))


_SECTIONS = {'group': None, 'phd students': 'PhD', 'current students': 'student', 'affiliates': 'affiliate', 'people': None, 'students': 'student', 'alumni': 'alumni', 'postdocs': 'postdoc', 'visitors': 'visitor', 'team': 'member', 'members': 'member', 'students supervised': 'student', 'former students': 'alumni'}


def _role(text, section):
    for pattern, role in [(r'\bph\.?d\b', 'PhD'), (r'\b(?:msc|m\.?s\.?|master)(?!\w)', 'MSc'), (r'\bpostdoc(?:toral)?\b', 'postdoc'), (r'\bvisitor\b', 'visitor'), (r'\balumni\b', 'alumni'), (r'\bstudent\b', 'student'), (r'\bmember\b', 'member')]:
        if re.search(pattern, text, re.I):
            return role
    return _SECTIONS.get(section.lower())


def _is_name(text):
    words = text.split()
    return 2 <= len(words) <= 5 and all(
        word[0].isupper() and all(c.isalpha() or c in "-'.’" for c in word)
        for word in words
    )


def _review(node, reason, section=None):
    return dict(reason=reason, evidence_text=_text(node), locator=_locator(node), section=section)


def _card(node):
    return bool(set(node.get('class', [])) & {'card', 'member-card', 'person-card', 'team-member', 'person', 'member'})


def _url(href, source_url):
    if not isinstance(href, str) or not href.strip() or re.search(r'[\x00-\x20\\]', href):
        return None
    try:
        parsed = urlsplit(urljoin(source_url, href))
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            return None
        parsed.port  # Validate malformed ports too.
        if re.search(r'\.(?:pdf|zip|gz|tar|jpg|jpeg|png|gif|svg|webp|ico|mp4|mp3|docx?|xlsx?|pptx?|exe|bin)(?:$|/)', parsed.path, re.I):
            return None
        return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, parsed.query, ''))
    except ValueError:
        return None


def _origin(url):
    p = urlsplit(url)
    return p.scheme, p.hostname, p.port or (443 if p.scheme == 'https' else 80)


def extract_roster(html: str, source_url: str) -> dict:
    soup = BeautifulSoup(html, 'html.parser')
    _prepare_stylesheet_visibility(soup)
    # HTML permits omitted </li>; html.parser nests those sibling items.
    # Repair only directly nested li (not real sublists), retaining the
    # original parse-tree locator for replay against the raw source.
    items = soup.find_all('li')
    for item in items:
        item.__dict__['_evidence_locator'] = _locator(item)
    for item in items:
        if item.parent is not None and item.parent.name == 'li' and not _visibility(item):
            parent = item.parent
            parent.insert_after(item.extract())
    result = dict(candidates=[], links=[], review=_visibility_reviews(soup))
    base = _url(source_url, source_url)
    for anchor in soup.find_all('a', href=True):
        target = _url(anchor.get('href'), source_url)
        if not _visibility(anchor) and target and base and _origin(target) == _origin(base) and re.search(r'\b(?:people|team|students|alumni|members|postdocs|visitors)\b', _text(anchor) + ' ' + urlsplit(target).path, re.I):
            if target not in result['links']:
                result['links'].append(target)
    section = None
    section_owner = None
    consumed = set()
    for node in soup.descendants:
        if isinstance(node, NavigableString):
            text = ' '.join(str(node).split())
            parent = node.parent
            in_scope = section_owner is not None and any(p is section_owner for p in node.parents)
            if parent is not None and text and section and in_scope and not isinstance(node, Comment) and not _non_owned(parent) and not re.fullmatch(r'h[1-6]', parent.name) and not any(id(p) in consumed for p in node.parents):
                index = next(i for i, child in enumerate(parent.contents, 1) if child is node)
                result['review'].append(dict(reason='unsupported_roster_text', evidence_text=text, locator=(_locator(parent) or 'document') + f'::node({index})', section=section))
            continue
        if not isinstance(node, Tag) or _non_owned(node):
            continue
        if any(id(parent) in consumed for parent in node.parents):
            continue
        if section_owner is not None and node is not section_owner and not any(parent is section_owner for parent in node.parents):
            section = None
        explicit_title = (node.name == 'div' and 'title' in node.get('class', [])
                          and not node.find(['div', 'p', 'li', 'ul', 'table']) and section is not None)
        if re.fullmatch(r'h[1-6]', node.name) or explicit_title:
            section = _text(node) if _text(node).lower() in _SECTIONS else None
            section_owner = node.parent
            if explicit_title:
                consumed.add(id(node))
            continue
        if section and node.name == 'dl':
            consumed.add(id(node))
            if _text(node):
                result['review'].append(_review(node, 'unsupported_roster_structure', section))
            continue
        leaf_block = node.name in {'div', 'span', 'article', 'section'} and not node.find(['div', 'p', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
        if not section or not (node.name in {'li', 'tr', 'p'} or _card(node) or leaf_block):
            continue
        consumed.add(id(node))
        anchors = node.find_all('a', href=True)
        text = _text(node)
        name = None
        profile_url = None
        named = [a for a in anchors if _is_name(_text(a))]
        coadvisor_spans = list(re.finditer(r'\([^()]*\bwith\b[^()]*\)', text))
        if len(named) > 1 and text.startswith(_text(named[0])):
            extras = [_text(a) for a in named[1:]]
            if all(text.count(label) == 1 and any(span.start() <= text.index(label) < span.end()
                       for span in coadvisor_spans) for label in extras):
                named = named[:1]
        if len(named) == 1:
            name = _text(named[0])
            profile_url = _url(named[0].get('href'), source_url)
            if profile_url is None:
                name = None
        elif not anchors:
            match = re.fullmatch(r'(.+?)\s+(?:—|–|-)\s+(.+)', text)
            if match and _is_name(match[1]) and _role(match[2], 'People'):
                name = match[1]
        ambiguity_text = re.sub(r'\([^()]*\bwith\b[^()]*\)', '', text)
        # Preserve destination prose as evidence, never as another person's
        # name and never as a verified current employment claim.
        destination = re.search(r',\s*(?:Research Scientist|Research Engineer|Assistant Professor|Associate Professor|Professor|Member of Technical Staff|Co-Founder|Founder|Chief Scientist|Engineer)\b', ambiguity_text)
        if destination:
            ambiguity_text = ambiguity_text[:destination.start()]
        if name and not re.search(r'\b(?:and|with)\s+[A-Z]|,\s*[A-Z][a-z]+\s+[A-Z]|[&;]', ambiguity_text):
            result['candidates'].append(dict(name=name, profile_url=profile_url, section=section, relationship=_role(text, section), evidence_text=text, locator=_locator(node)))
        elif text:
            result['review'].append(_review(node, 'ambiguous_or_unsupported_roster_block', section))
    return result


def _claim(kind, value, node):
    return dict(kind=kind, value=value, evidence_text=_text(node), locator=_locator(node), verification_status='self_declared')


_NON_OWNER = re.compile(r'\b(?:publications?|papers?|coauthors?|collaborators?|references?|bibliography)\b', re.I)


def _non_owned(node):
    for ancestor in [node, *node.parents]:
        if ancestor.name in {'nav', 'footer', 'header', 'script', 'style'} or _visibility(ancestor):
            return True
        if _NON_OWNER.search(' '.join(ancestor.get('class', [])) + ' ' + str(ancestor.get('id', ''))):
            return True
    if node.parent and node.parent.name in {'p', 'li', 'tr'} and _NON_OWNER.search(_text(node.parent)):
        return True
    if re.fullmatch(r'h[1-6]', node.name):
        return False
    heading = node.find_previous(re.compile(r'^h[1-6]$'))
    return bool(heading and _NON_OWNER.search(_text(heading)))


def _link_kind(target, label):
    p = urlsplit(target)
    label = re.sub(r'^my\s+', '', label.lower()).strip()
    if label == 'github' and p.hostname in {'github.com', 'www.github.com'} and re.fullmatch(r'/[A-Za-z0-9-]+/?', p.path):
        return 'github_url'
    if label == 'linkedin' and p.hostname in {'linkedin.com', 'www.linkedin.com'} and re.fullmatch(r'/in/[^/]+/?', p.path):
        return 'linkedin_url'
    if label in {'google scholar', 'scholar'} and p.hostname == 'scholar.google.com' and p.path == '/citations' and re.search(r'(?:^|&)user=[^&]+', p.query):
        return 'google_scholar_url'
    if label in {'personal website', 'personal homepage', 'website', 'homepage'}:
        return 'personal_website_url'
    return None


def _persons(data):
    if isinstance(data, list):
        for item in data:
            yield from _persons(item)
    elif isinstance(data, dict):
        types = data.get('@type', [])
        if types == 'Person' or isinstance(types, list) and 'Person' in types:
            yield data
        if '@graph' in data:
            yield from _persons(data['@graph'])


_OWNERSHIP_REGIONS = {'section', 'article', 'main', 'aside', 'div'}
_OWNERSHIP_ROLES = {'region', 'group'}
_PRESENTATIONAL_ROLES = {'presentation', 'none'}


def _semantic_heading(node):
    return (bool(re.fullmatch(r'h[1-6]', node.name or ''))
            and not {token.casefold() for token in str(node.get('role', '')).split()}
            & _PRESENTATIONAL_ROLES)


def _accessible_person_label(region):
    roles = {token.casefold() for token in str(region.get('role', '')).split()}
    if region.name not in _OWNERSHIP_REGIONS and not roles & _OWNERSHIP_ROLES:
        return None
    label = ' '.join(str(region.get('aria-label', '')).split())
    if _is_name(label):
        return 'person', label
    if region.has_attr('aria-label'):
        return None
    references = str(region.get('aria-labelledby', '')).split()
    if not references:
        return None
    if len(references) != len(set(references)):
        return 'unknown', None
    root = region
    while root.parent is not None:
        root = root.parent
    labels = []
    for reference in references:
        matches = root.find_all(id=reference)
        if len(matches) != 1:
            return 'unknown', None
        labelled_by = matches[0]
        reference_roles = {token.casefold() for token in str(labelled_by.get('role', '')).split()}
        if (_visibility(labelled_by) is not None
                or reference_roles & _PRESENTATIONAL_ROLES
                or labelled_by.name in {'script', 'style', 'template', 'noscript'}):
            return 'unknown', None
        labels.append(_text(labelled_by))
    label = ' '.join(' '.join(labels).split())
    if _is_name(label):
        return 'person', label
    return None


def _ownership_reason(node, expected):
    # The nearest explicitly person-labelled semantic region is the ownership
    # boundary. Generic accessibility labels do not establish ownership.
    for ancestor in [node, *node.parents]:
        ownership = _accessible_person_label(ancestor)
        if ownership is not None:
            kind, label = ownership
            if kind == 'unknown':
                return 'ownership_unknown'
            return 'other_person_owner' if label != expected else None
    # Named containers own their nested blocks as well.
    for ancestor in node.parents:
        if ancestor.name in {'section', 'article', 'div', 'li'}:
            headings = ancestor.find_all(re.compile(r'^h[1-6]$'), recursive=False)
            if any(_semantic_heading(h) and _is_name(_text(h)) and _text(h) != expected
                   and not _non_owned(h) for h in headings):
                return 'other_person_owner'
    rank = 7
    for heading in node.find_all_previous(re.compile(r'^h[1-6]$')):
        level = int(heading.name[1])
        if level >= rank or not _semantic_heading(heading) or _non_owned(heading):
            continue
        if not any(parent is heading.parent for parent in node.parents):
            continue
        rank = level
        if _is_name(_text(heading)):
            return 'other_person_owner' if _text(heading) != expected else None
    return None


def extract_profile(html: str, source_url: str, expected_name: str) -> dict:
    soup = BeautifulSoup(html, 'html.parser')
    _prepare_stylesheet_visibility(soup)
    expected = ' '.join(expected_name.split())
    matched = bool(expected) and any(
        expected == part.strip()
        for node in soup.find_all(['title', 'h1'])
        if not _non_owned(node) and (node.name == 'title' or _semantic_heading(node))
        for part in (re.split(r'\s+[|–—-]\s+|\s*\|\s*', _text(node)) if node.name == 'title' else [_text(node)])
    )
    primary_names = {part.strip() for node in soup.find_all(['title', 'h1'])
                     if not _non_owned(node) and (node.name == 'title' or _semantic_heading(node))
                     for part in (re.split(r'\s+[|–—-]\s+|\s*\|\s*', _text(node)) if node.name == 'title' else [_text(node)])
                     if _is_name(part.strip())}
    conflict = bool(primary_names - {expected})
    matched = matched and not conflict
    result: dict = dict(identity_status='name_matched' if matched else 'unresolved', claims=[], review=_visibility_reviews(soup))
    if not matched:
        result['review'].append(dict(reason='conflicting_primary_identity' if conflict else 'expected_full_name_not_matched', evidence_text=' '.join(_text(n) for n in soup.find_all(['title', 'h1'])), locator='document'))
        return result
    for script in soup.find_all('script', type='application/ld+json'):
        if _visibility(script):
            continue
        raw = str(script.string or '')
        if reason := _ownership_reason(script, expected):
            result['review'].append(dict(reason=reason, evidence_text=raw, locator=_locator(script)))
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            result['review'].append(dict(reason='invalid_jsonld', evidence_text=' '.join(raw.split()), locator=_locator(script)))
            continue
        for person in _persons(data):
            name = person.get('name')
            if not isinstance(name, str) or ' '.join(name.split()) != expected:
                continue
            value = {key: person[key] for key in ('worksFor', 'jobTitle') if person.get(key)}
            if value:
                result['claims'].append(dict(kind='employment', value=value, evidence_text=' '.join(raw.split()), locator=_locator(script), verification_status='self_declared'))
    for paragraph in soup.find_all('p'):
        text = _text(paragraph)
        if reason := _ownership_reason(paragraph, expected):
            result['review'].append(_review(paragraph, reason))
            continue
        if not _non_owned(paragraph) and re.fullmatch(
            r"I (?:work (?:at|for) .+|am affiliated with .+|am (?:a|an) (?:research (?:scientist|engineer)|researcher|scientist|engineer|professor|assistant professor|associate professor|postdoc|student) at .+)[.!]?",
            text,
        ):
            result['claims'].append(_claim('employment', {'raw': text}, paragraph))
    for anchor in soup.find_all('a', href=True):
        target = _url(anchor.get('href'), source_url)
        kind = _link_kind(target, _text(anchor)) if target else None
        if kind and (reason := _ownership_reason(anchor, expected)):
            result['review'].append(_review(anchor, reason))
            continue
        if kind and not _non_owned(anchor):
            result['claims'].append(_claim(kind, target, anchor))
    return result
