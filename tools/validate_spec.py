"""Validate documentation/contracts/reference arithmetic, not a RenoLedger app."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS = []


def check(condition, message):
    if not condition:
        ERRORS.append(message)


def walk(value):
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def resolve(root, pointer):
    value = root
    for segment in pointer[2:].split('/'):
        value = value[segment.replace('~1', '/').replace('~0', '~')]
    return value


def subset_validate(schema, value, path='$'):
    """Portable validation of constructs used by the extraction contract."""
    if 'anyOf' in schema:
        alternatives = []
        for alternative in schema['anyOf']:
            before = len(ERRORS)
            subset_validate(alternative, value, path)
            problems = ERRORS[before:]
            del ERRORS[before:]
            alternatives.append(problems)
        check(any(not problems for problems in alternatives), path + ': no anyOf branch matches')
        return
    if 'const' in schema:
        check(value == schema['const'], path + ': const mismatch')
    if 'enum' in schema:
        check(value in schema['enum'], path + ': enum mismatch')
    types = schema.get('type', [])
    types = [types] if isinstance(types, str) else types
    predicates = {'object': lambda x: isinstance(x, dict), 'array': lambda x: isinstance(x, list),
                  'string': lambda x: isinstance(x, str), 'integer': lambda x: type(x) is int,
                  'number': lambda x: type(x) in (int, float), 'boolean': lambda x: type(x) is bool,
                  'null': lambda x: x is None}
    if types:
        matches = any(predicates[t](value) for t in types)
        check(matches, path + ': wrong type')
        if not matches:
            return
    if isinstance(value, dict):
        props = schema.get('properties', {})
        check(all(k in value for k in schema.get('required', [])), path + ': missing required property')
        if schema.get('additionalProperties') is False:
            check(not (set(value) - set(props)), path + ': unknown property')
        for key, item in value.items():
            if key in props:
                subset_validate(props[key], item, path + '.' + key)
    if isinstance(value, list):
        check(len(value) >= schema.get('minItems', 0), path + ': short array')
        check(len(value) <= schema.get('maxItems', float('inf')), path + ': long array')
        for index, item in enumerate(value):
            subset_validate(schema.get('items', {}), item, path + f'[{index}]')
    if type(value) in (int, float):
        check(value >= schema.get('minimum', -float('inf')), path + ': below minimum')
        check(value <= schema.get('maximum', float('inf')), path + ': above maximum')
    if isinstance(value, str) and 'pattern' in schema:
        check(re.search(schema['pattern'], value) is not None, path + ': pattern mismatch')


def main():
    md_paths = [ROOT / 'README.md', *sorted((ROOT / 'docs').glob('*.md'))]
    for path in md_paths:
        text = path.read_text(encoding='utf-8')
        check('\ufffd' not in text, str(path) + ': replacement character')
        check(text.count('```') % 2 == 0, str(path) + ': unmatched code fence')
        for link in re.findall(r'(?<!!)\[[^\]]+\]\(([^)]+)\)', text):
            if link.startswith(('http:', 'https:', '#', 'mailto:')):
                continue
            target = link.split('#')[0]
            check((path.parent / target).exists(), f'{path.name}: broken link {link}')
    api = json.loads((ROOT / 'contracts/openapi.json').read_text(encoding='utf-8'))
    check(api['openapi'] == '3.1.0', 'OpenAPI version')
    ops = []
    for path, methods in api['paths'].items():
        names = set(re.findall(r'\{([^}]+)\}', path))
        for method, op in methods.items():
            ops.append(op['operationId'])
            declared = {p['name'] for p in op.get('parameters', []) if p['in'] == 'path' and p.get('required')}
            check(names == declared, f'{method} {path}: path parameters')
            security = op.get('security', api.get('security'))
            check(bool(security) or path == '/demo', f'{method} {path}: missing security')
            check('default' in op['responses'], f'{method} {path}: no structured error')
    check(len(ops) == len(set(ops)), 'Duplicate operation id')
    for item in walk(api):
        if isinstance(item, dict) and '$ref' in item:
            try:
                resolve(api, item['$ref'])
            except (KeyError, TypeError):
                check(False, 'Unresolved reference ' + item['$ref'])
        if isinstance(item, dict) and 'properties' in item:
            check(set(item.get('required', [])) <= set(item['properties']), 'Required property missing schema')

    schema = json.loads((ROOT / 'contracts/extraction.schema.json').read_text(encoding='utf-8'))
    example = json.loads((ROOT / 'fixtures/extraction_example.json').read_text(encoding='utf-8'))
    subset_validate(schema, example)
    evidence_ids = {e['id'] for e in example['evidence']}
    for candidate in example['candidates']:
        for field in candidate['fields']:
            check(set(field['evidence_ids']) <= evidence_ids, 'Unknown extraction evidence')

    standards = []
    try:
        from jsonschema import Draft202012Validator, FormatChecker
    except ImportError:
        standards.append('jsonschema not installed: portable subset checks only')
    else:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(example)
        for component in api['components']['schemas'].values():
            Draft202012Validator.check_schema(component)
        standards.append('JSON Schema Draft 2020-12 schema and fixture validation passed')
    try:
        from openapi_spec_validator import validate
    except ImportError:
        standards.append('OpenAPI full validator not installed: local references/paths/security checked')
    else:
        validate(api)
        standards.append('OpenAPI standards validation passed')

    fixtures = json.loads((ROOT / 'fixtures/ledger_cases.json').read_text(encoding='utf-8'))
    check(len(fixtures['cases']) == 16, 'Expected 16 financial scenarios')
    ids = []
    for case in fixtures['cases']:
        ids.append(case['id'])
        check(case['synthetic'] is True, case['id'] + ': synthetic marker')
        n, expected = case['normalized'], case['expected']
        c = None if n['commitment_terms_cents'] is None else sum(n['commitment_terms_cents'])
        p = sum(n['completed_cash_cents'])
        r = None if c is None else c - p
        check(expected == {'commitment_total_cents': c, 'net_paid_cents': p, 'remaining_commitment_cents': r},
              case['id'] + ': expected arithmetic')
        for value in (n['commitment_terms_cents'] or []) + n['completed_cash_cents']:
            check(type(value) is int, case['id'] + ': money must be integer cents')
    check(len(ids) == len(set(ids)), 'Duplicate scenario id')
    rules = (ROOT / 'docs/04_LEDGER_RULES.md').read_text(encoding='utf-8')
    check(all(case_id in rules for case_id in ids), 'Scenario not documented')
    if ERRORS:
        print('\n'.join('FAIL: ' + e for e in ERRORS))
        raise SystemExit(1)
    print(f'PASS: {len(md_paths)} source Markdown files, {len(ops)} API operations, 16 financial reference cases, extraction example.')
    for note in standards:
        print(note)
    print('Scope: specification integrity/reference arithmetic only; run the separate application tests for ledger behavior. OCR/LLM is not evaluated here.')


if __name__ == '__main__':
    main()
