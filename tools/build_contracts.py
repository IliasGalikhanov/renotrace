"""Generate the versioned design contracts. This is not an application server."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(relative, value):
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def obj(properties, required=None):
    return {'type': 'object', 'additionalProperties': False, 'properties': properties,
            'required': list(properties) if required is None else required}


def ref(name):
    return {'$ref': '#/components/schemas/' + name}


def enum(*values):
    return {'type': 'string', 'enum': list(values)}


def arr(items):
    return {'type': 'array', 'items': items}


S = {'type': 'string'}
UUID = {'type': 'string', 'format': 'uuid'}
DT = {'type': 'string', 'format': 'date-time'}
DATE = {'type': 'string', 'format': 'date'}
BOOL = {'type': 'boolean'}
REV = {'type': 'integer', 'minimum': 0}
MONEY = {'type': 'integer', 'minimum': -9000000000000, 'maximum': 9000000000000}
NULL_MONEY = {'anyOf': [MONEY, {'type': 'null'}]}
NULL_S = {'type': ['string', 'null']}
KINDS = enum('agreement_base', 'commitment_adjustment', 'billing_entry',
             'payment_request', 'cash_event', 'payment_terms', 'owner_purchase')


def build_api():
    schemas = {
        'Error': obj({'code': S, 'message': S, 'request_id': S, 'retryable': BOOL,
                      'current_revision': REV}, ['code', 'message', 'request_id', 'retryable']),
        'CaseCreate': obj({'contractor_name': {'type': 'string', 'minLength': 1, 'maxLength': 200},
                           'purpose': enum('next_payment', 'final_payment'), 'cutoff_date': DATE,
                           'currency': {'const': 'USD'}}),
        'Case': obj({'id': UUID, 'contractor_name': S, 'purpose': S, 'cutoff_date': DATE,
                     'currency': {'const': 'USD'}, 'revision': REV, 'status': S,
                     'created_at': DT}),
        'CasePatch': obj({'expected_revision': REV, 'contractor_name': S, 'cutoff_date': DATE},
                         ['expected_revision']),
        'RevisionRequest': obj({'expected_revision': REV}),
        'MutationResult': obj({'case_id': UUID, 'revision': REV, 'object_id': UUID}),
        'Job': obj({'id': UUID, 'case_id': UUID,
                    'status': enum('queued', 'running', 'retry_wait', 'succeeded', 'failed', 'cancelled'),
                    'stage': S, 'attempt': REV, 'retryable': BOOL, 'error_code': NULL_S,
                    'expected_case_revision': REV}),
        'UploadIntent': obj({'expected_revision': REV, 'display_name': S,
                             'mime_type': enum('application/pdf', 'image/jpeg', 'image/png', 'text/csv'),
                             'size_bytes': {'type': 'integer', 'minimum': 1, 'maximum': 20971520},
                             'sha256': {'type': 'string', 'pattern': '^[a-f0-9]{64}$'}}),
        'UploadTicket': obj({'document_id': UUID, 'upload_id': UUID,
                             'upload_url': {'type': 'string', 'format': 'uri'},
                             'method': enum('PUT', 'POST'),
                             'required_headers': {'type': 'object', 'additionalProperties': S},
                             'expires_at': DT}),
        'UploadComplete': obj({'expected_revision': REV, 'upload_id': UUID}),
        'Document': obj({'id': UUID, 'case_id': UUID, 'version_id': UUID,
                         'display_name': S, 'mime_type': S, 'status': S,
                         'page_count': {'type': ['integer', 'null'], 'minimum': 0}}),
        'SourceAccess': obj({'url': {'type': 'string', 'format': 'uri'}, 'expires_at': DT}),
        'ProcessRequest': obj({'expected_revision': REV, 'document_ids': arr(UUID)}),
        'CsvPreviewInput': obj({'document_version_id': UUID,
                                'date_column': S, 'amount_column': S, 'description_column': S,
                                'transaction_id_column': NULL_S, 'status_column': NULL_S,
                                'date_format': S, 'decimal_separator': enum('.', ','),
                                'outgoing_sign': enum('positive', 'negative')}),
        'CsvPreview': obj({'preview_id': UUID, 'document_version_id': UUID,
                           'total_rows': REV, 'valid_rows': REV, 'invalid_rows': REV,
                           'sample': arr(obj({'source_row': REV, 'date': NULL_S,
                                              'amount_cents': NULL_MONEY, 'description': S,
                                              'issues': arr(S)})), 'mapping_hash': S}),
        'CsvCommitInput': obj({'expected_revision': REV, 'preview_id': UUID,
                               'mapping_hash': S, 'include_source_rows': arr({'type': 'integer', 'minimum': 1})}),
        'Evidence': obj({'id': UUID, 'source_type': enum('document', 'bank_record', 'user_statement'),
                         'document_version_id': {'anyOf': [UUID, {'type': 'null'}]},
                         'page': {'type': ['integer', 'null'], 'minimum': 1},
                         'csv_row': {'type': ['integer', 'null'], 'minimum': 1},
                         'quote': NULL_S}),
        'RecordFields': obj({
            'amount_cents': NULL_MONEY, 'effective_date': {'type': ['string', 'null'], 'format': 'date'},
            'billing_basis': enum('incremental_charge', 'cumulative_valuation', 'balance_statement', 'credit_note', 'unknown'),
            'cash_state': enum('completed', 'pending', 'scheduled', 'failed', 'reversed', 'unknown'),
            'payer_type': enum('owner', 'co_owner', 'lender', 'other', 'unknown'),
            'invoice_number': NULL_S, 'coverage_record_ids': arr(UUID),
            'gross_total_cents': NULL_MONEY, 'previous_billed_cents': NULL_MONEY,
            'requested_now_cents': NULL_MONEY, 'previous_paid_cents': NULL_MONEY,
            'included_adjustment_ids': arr(UUID), 'replaces_record_ids': arr(UUID),
            'condition_text': NULL_S, 'condition_satisfaction': enum('unknown', 'user_reported'),
            'stage_amount_cents': NULL_MONEY, 'due_date': {'type': ['string', 'null'], 'format': 'date'},
            'note': NULL_S}, []),
        'RecordInput': obj({'expected_revision': REV, 'kind': KINDS,
                            'fields': ref('RecordFields'), 'evidence_ids': arr(UUID),
                            'reason': S}),
        'Record': obj({'id': UUID, 'case_id': UUID, 'record_revision': REV,
                       'kind': KINDS, 'fields': ref('RecordFields'),
                       'origin': enum('document', 'bank_record', 'user_statement', 'derived'),
                       'extraction_review': enum('unreviewed', 'checked', 'corrected'),
                       'semantic_review': enum('unknown', 'user_asserted', 'reviewed_for_calculation'),
                       'lifecycle': enum('active', 'superseded', 'void', 'stale'),
                       'conflict_issue_ids': arr(UUID), 'evidence': arr(ref('Evidence'))}),
        'LinkInput': obj({'expected_revision': REV, 'from_record_id': UUID,
                          'to_record_id': UUID,
                          'kind': enum('allocation', 'supersedes', 'amends', 'includes_adjustment', 'references_payment', 'duplicate_candidate'),
                          'amount_cents': NULL_MONEY,
                          'decision': enum('accept', 'reject'), 'evidence_ids': arr(UUID), 'reason': S}),
        'Link': obj({'id': UUID, 'case_id': UUID, 'from_record_id': UUID, 'to_record_id': UUID,
                     'kind': S, 'amount_cents': NULL_MONEY,
                     'status': enum('proposed', 'accepted', 'rejected', 'invalidated'), 'basis_revision': REV}),
        'Issue': obj({'id': UUID, 'code': S, 'question': S,
                      'status': enum('open', 'resolved', 'invalidated'),
                      'priority': enum('blocking', 'money_impact', 'informational'),
                      'impact_cents': NULL_MONEY, 'affected_metrics': arr(S),
                      'record_ids': arr(UUID), 'basis_revision': REV}),
        'ResolutionInput': obj({'expected_revision': REV,
                                'decision': enum('confirm_reading', 'select_version', 'accept_link', 'reject_link', 'assert_agreement', 'unknown'),
                                'selected_record_ids': arr(UUID), 'evidence_ids': arr(UUID), 'explanation': S}),
        'Metric': obj({'amount_cents': NULL_MONEY,
                       'status': enum('known', 'provisional', 'unknown'),
                       'record_ids': arr(UUID), 'issue_ids': arr(UUID)}),
        'Summary': obj({'snapshot_id': UUID, 'case_id': UUID, 'case_revision': REV,
                        'rules_version': S, 'cutoff_date': DATE, 'currency': {'const': 'USD'},
                        'requested_now': ref('Metric'), 'commitment_total': ref('Metric'),
                        'net_paid': ref('Metric'), 'remaining_commitment': ref('Metric'),
                        'open_invoices': ref('Metric'), 'credit_balances': ref('Metric'),
                        'unallocated_paid': ref('Metric'),
                        'payment_conditions': obj({'stage_amount_cents': NULL_MONEY,
                                                   'text': NULL_S,
                                                   'satisfaction': enum('unknown', 'user_reported'),
                                                   'evidence_ids': arr(UUID)}),
                        'open_issues': arr(ref('Issue')), 'created_at': DT}),
        'ExportInput': obj({'snapshot_id': UUID, 'format': enum('pdf', 'csv')}),
        'Export': obj({'id': UUID, 'snapshot_id': UUID, 'format': enum('pdf', 'csv'),
                       'status': enum('queued', 'running', 'ready', 'failed'),
                       'download': {'anyOf': [ref('SourceAccess'), {'type': 'null'}]}}),
        'OfferInput': obj({'expected_revision': REV, 'document_version_ids': arr(UUID),
                           'cutoff_date': DATE, 'goal': S}),
        'Order': obj({'id': UUID, 'case_id': UUID, 'manifest_hash': S,
                      'document_version_ids': arr(UUID), 'cutoff_date': DATE,
                      'price_cents': MONEY, 'currency': {'const': 'USD'}, 'state': S,
                      'human_review_disclosed': BOOL, 'terms_version': S}),
        'CheckoutInput': obj({'manifest_hash': S, 'terms_version': S, 'accept_terms': {'const': True}}),
        'Checkout': obj({'order_id': UUID, 'checkout_url': {'type': 'string', 'format': 'uri'}}),
        'SupportGrantInput': obj({'operator_subject': S, 'purpose': S, 'expires_at': DT}),
        'SupportGrant': obj({'id': UUID, 'case_id': UUID, 'purpose': S, 'expires_at': DT, 'revoked': BOOL}),
        'Deletion': obj({'id': UUID, 'case_id': UUID, 'state': S, 'requested_at': DT}),
        'WebhookAck': obj({'received': {'const': True}}),
    }
    paths = {}

    def route(path, method, operation, response, *, request=None, status=200, description='', public=False, webhook=False):
        import re
        parameters = [{'name': name, 'in': 'path', 'required': True, 'schema': UUID}
                      for name in re.findall(r'\{([^}]+)\}', path)]
        if method in ('post', 'patch', 'delete') and not webhook:
            parameters.append({'name': 'Idempotency-Key', 'in': 'header', 'required': True,
                               'schema': {'type': 'string', 'minLength': 8, 'maxLength': 200}})
        op = {'operationId': operation, 'summary': description or operation, 'parameters': parameters,
              'responses': {str(status): {'description': 'Successful response',
                                         'content': {'application/json': {'schema': response}}},
                            'default': {'description': 'Structured error',
                                        'content': {'application/json': {'schema': ref('Error')}}}}}
        if request:
            op['requestBody'] = {'required': True, 'content': {'application/json': {'schema': request}}}
        if public:
            op['security'] = []
        if webhook:
            op['security'] = [{'ProviderSignature': []}]
            op['description'] = 'Verify signature against raw body using the selected provider SDK; event id deduplication and order amount/currency checks are mandatory. Body is provider-specific.'
        paths.setdefault(path, {})[method] = op

    def page(schema):
        return obj({'items': arr(schema), 'next_cursor': NULL_S})

    route('/demo', 'get', 'getDemo', ref('Summary'), public=True, description='Read the synthetic demonstration snapshot')
    route('/cases', 'post', 'createCase', ref('Case'), request=ref('CaseCreate'), status=201)
    route('/cases', 'get', 'listCases', page(ref('Case')))
    route('/cases/{case_id}', 'get', 'getCase', ref('Case'))
    route('/cases/{case_id}', 'patch', 'updateCase', ref('Case'), request=ref('CasePatch'))
    route('/cases/{case_id}', 'delete', 'deleteCase', ref('Deletion'), status=202)
    route('/cases/{case_id}/documents', 'get', 'listDocuments', page(ref('Document')))
    route('/cases/{case_id}/uploads', 'post', 'createUpload', ref('UploadTicket'), request=ref('UploadIntent'), status=201)
    route('/cases/{case_id}/documents/{document_id}/complete', 'post', 'completeUpload', ref('Job'), request=ref('UploadComplete'), status=202)
    route('/cases/{case_id}/documents/{document_id}/source', 'get', 'getDocumentSource', ref('SourceAccess'))
    paths['/cases/{case_id}/documents/{document_id}/source']['get']['parameters'].append(
        {'name': 'document_version_id', 'in': 'query', 'required': True, 'schema': UUID})
    route('/cases/{case_id}/csv-previews', 'post', 'previewCsv', ref('CsvPreview'), request=ref('CsvPreviewInput'))
    route('/cases/{case_id}/csv-imports', 'post', 'commitCsv', ref('Job'), request=ref('CsvCommitInput'), status=202)
    route('/cases/{case_id}/process', 'post', 'processDocuments', ref('Job'), request=ref('ProcessRequest'), status=202)
    route('/cases/{case_id}/jobs/{job_id}', 'get', 'getJob', ref('Job'))
    route('/cases/{case_id}/records', 'get', 'listRecords', page(ref('Record')))
    route('/cases/{case_id}/records', 'post', 'createRecord', ref('MutationResult'), request=ref('RecordInput'), status=201)
    route('/cases/{case_id}/records/{record_id}', 'patch', 'reviseRecord', ref('MutationResult'), request=ref('RecordInput'))
    route('/cases/{case_id}/links', 'get', 'listLinks', page(ref('Link')))
    route('/cases/{case_id}/links', 'post', 'createLink', ref('MutationResult'), request=ref('LinkInput'), status=201)
    route('/cases/{case_id}/links/{link_id}', 'patch', 'reviseLink', ref('MutationResult'), request=ref('LinkInput'))
    route('/cases/{case_id}/issues', 'get', 'listIssues', page(ref('Issue')))
    route('/cases/{case_id}/issues/{issue_id}/resolve', 'post', 'resolveIssue', ref('MutationResult'), request=ref('ResolutionInput'))
    route('/cases/{case_id}/calculations', 'post', 'calculateCase', ref('Job'), request=ref('RevisionRequest'), status=202)
    route('/cases/{case_id}/summary', 'get', 'getLatestSummary', ref('Summary'))
    route('/cases/{case_id}/snapshots', 'get', 'listSnapshots', page(ref('Summary')))
    route('/cases/{case_id}/snapshots/{snapshot_id}', 'get', 'getSnapshot', ref('Summary'))
    route('/cases/{case_id}/exports', 'post', 'createExport', ref('Export'), request=ref('ExportInput'), status=202)
    route('/cases/{case_id}/exports/{export_id}', 'get', 'getExport', ref('Export'))
    route('/cases/{case_id}/offers', 'post', 'createOffer', ref('Order'), request=ref('OfferInput'), status=201)
    route('/cases/{case_id}/orders/{order_id}', 'get', 'getOrder', ref('Order'))
    route('/cases/{case_id}/orders/{order_id}/checkout', 'post', 'startCheckout', ref('Checkout'), request=ref('CheckoutInput'))
    route('/cases/{case_id}/support-grants', 'post', 'grantSupportAccess', ref('SupportGrant'), request=ref('SupportGrantInput'), status=201)
    route('/cases/{case_id}/support-grants/{grant_id}', 'delete', 'revokeSupportAccess', ref('SupportGrant'))
    route('/deletions/{deletion_id}', 'get', 'getDeletionStatus', ref('Deletion'))
    route('/webhooks/payments', 'post', 'receivePaymentEvent', ref('WebhookAck'),
          request={'type': 'object', 'additionalProperties': True}, webhook=True)
    # Pagination is explicit on every cursor-based list operation.
    for methods in paths.values():
        for op in methods.values():
            if op['operationId'].startswith('list'):
                op['parameters'] += [
                    {'name': 'cursor', 'in': 'query', 'required': False, 'schema': S},
                    {'name': 'limit', 'in': 'query', 'required': False,
                     'schema': {'type': 'integer', 'minimum': 1, 'maximum': 100, 'default': 50}}]
    api = {'openapi': '3.1.0', 'info': {'title': 'RenoLedger Design API', 'version': '0.1.0',
            'description': 'Design contract only. No server is implemented. Monetary semantics and kind-specific validation are defined in the documentation.'},
           'servers': [{'url': '/api/v1'}], 'security': [{'BearerAuth': []}], 'paths': paths,
           'components': {'securitySchemes': {
               'BearerAuth': {'type': 'http', 'scheme': 'bearer', 'bearerFormat': 'JWT'},
               'ProviderSignature': {'type': 'apiKey', 'in': 'header', 'name': 'X-Provider-Signature',
                                     'description': 'Placeholder name; adapt to the selected payment provider before implementation.'}},
                          'schemas': schemas}}
    write('contracts/openapi.json', api)


def build_extraction():
    evidence = obj({'id': S, 'page': {'type': ['integer', 'null'], 'minimum': 1},
                    'csv_row': {'type': ['integer', 'null'], 'minimum': 1},
                    'quote': NULL_S,
                    'bbox': {'anyOf': [{'type': 'array', 'items': {'type': 'number', 'minimum': 0, 'maximum': 1},
                                       'minItems': 4, 'maxItems': 4}, {'type': 'null'}]}})
    field = obj({'field_name': enum('amount', 'gross_total', 'previous_billed', 'previous_paid',
                                   'requested_now', 'tax', 'discount', 'due_date', 'effective_date',
                                   'invoice_number', 'contractor_name', 'condition_text', 'stage_amount'),
                 'value_text': NULL_S, 'evidence_ids': arr(S)})
    candidate = obj({'id': S, 'kind': KINDS,
                     'billing_basis': enum('incremental_charge', 'cumulative_valuation', 'balance_statement', 'credit_note', 'unknown', 'not_applicable'),
                     'fields': arr(field), 'ambiguities': arr(S)})
    schema = {'$schema': 'https://json-schema.org/draft/2020-12/schema',
              '$id': 'urn:renoledger:extraction:0.1',
              'title': 'RenoLedger extraction candidates',
              'description': 'Untrusted extraction proposals. No accepted financial facts or legal verification. Raw monetary strings preserve source notation.',
              **obj({'schema_version': {'const': '0.1'}, 'document_version_id': UUID,
                     'language': enum('en', 'unknown', 'unsupported'),
                     'currency': enum('USD', 'unknown', 'unsupported'),
                     'evidence': arr(evidence), 'candidates': arr(candidate),
                     'warnings': arr(S)})}
    write('contracts/extraction.schema.json', schema)
    write('fixtures/extraction_example.json', {
        'schema_version': '0.1', 'document_version_id': '00000000-0000-4000-8000-000000000001',
        'language': 'en', 'currency': 'USD',
        'evidence': [{'id': 'ev1', 'page': 1, 'csv_row': None,
                      'quote': 'Balance due $5,500. Previous deposit $8,000.', 'bbox': None}],
        'candidates': [{'id': 'cand1', 'kind': 'payment_request', 'billing_basis': 'balance_statement',
                        'fields': [{'field_name': 'requested_now', 'value_text': '$5,500', 'evidence_ids': ['ev1']},
                                   {'field_name': 'previous_paid', 'value_text': '$8,000', 'evidence_ids': ['ev1']}],
                        'ambiguities': ['Deposit is mentioned in the document; completed payment is not independently established.']}],
        'warnings': ['Synthetic fixture.']})


def build_cases():
    cases = []

    def add(n, title, source_story, commitments, cash, expected, *, requested=None, stage=None,
            issues=None, excluded=None, billing=None):
        cases.append({'id': f'FIN-{n:02}', 'title': title, 'synthetic': True, 'source_story': source_story,
                      'normalized': {'commitment_terms_cents': commitments, 'completed_cash_cents': cash,
                                     'requested_now_cents': requested, 'documented_stage_cents': stage,
                                     'billing_entries_cents': billing or [], 'excluded_events': excluded or []},
                      'expected': expected, 'expected_issue_codes': issues or []})

    def expected(c, p, r):
        return {'commitment_total_cents': c, 'net_paid_cents': p, 'remaining_commitment_cents': r}

    add(1, 'Agreement change and material credit',
        'Base 12000, extra work 1500, approved reduction 800, completed payments 8000; request 5500.',
        [1200000, 150000, -80000], [500000, 300000], expected(1270000, 800000, 470000),
        requested=550000, issues=['REQUEST_DIFFERS_FROM_RECORDED_REMAINDER'])
    add(2, 'Net request already deducts deposit',
        'Total 10000; deposit 3000 completed; invoice balance due 7000. Do not deduct deposit from balance again.',
        [1000000], [300000], expected(1000000, 300000, 700000), requested=700000)
    add(3, 'Revised estimate incorporates prior change',
        'Old base 12000 and change 1500 replaced by inclusive 13500 estimate.',
        [1350000], [800000], expected(1350000, 800000, 550000),
        excluded=['superseded_base_12000', 'change_1500_already_included'])
    add(4, 'Refund of overpayment', 'Agreement 10000; paid 11000; received refund 1000.',
        [1000000], [1100000, -100000], expected(1000000, 1000000, 0))
    add(5, 'Stage request differs from contract remainder',
        'Contract 20000; paid 12000; current stage requests 3000; later completion 5000.',
        [2000000], [1200000], expected(2000000, 1200000, 800000), requested=300000,
        stage=300000, issues=['STAGE_COMPLETION_NOT_OBSERVED'])
    add(6, 'Unknown agreement baseline', 'Invoice 5500 and payment 1000 exist, accepted baseline missing.',
        None, [100000], expected(None, 100000, None), requested=550000, issues=['MISSING_AGREEMENT'])
    add(7, 'Pending payment excluded', 'Contract 10000, completed 3000 and pending 2000.',
        [1000000], [300000], expected(1000000, 300000, 700000), excluded=['pending_transfer_2000'])
    add(8, 'Overlapping CSV known transaction', 'Two CSV files contain the same bank transaction tx_1 of 3000.',
        [1000000], [300000], expected(1000000, 300000, 700000), excluded=['duplicate_tx_1_second_import'])
    add(9, 'Two genuine equal payments', 'Two separate completed transactions tx_1 and tx_2 each 3000.',
        [1000000], [300000, 300000], expected(1000000, 600000, 400000))
    add(10, 'Lender and owner payments', 'Owner paid 3000, lender paid contractor 2000; both have supporting records.',
        [1000000], [300000, 200000], expected(1000000, 500000, 500000))
    add(11, 'Cumulative billing not previous paid',
        'Previously billed 5000, paid 3000; new cumulative billed 13500, balance request 10500; incremental billing is 8500.',
        [1350000], [300000], expected(1350000, 300000, 1050000), requested=1050000,
        billing=[500000, 850000])
    add(12, 'Credit is not cash', 'Agreement 10000, approved scope reduction 1000, paid 5000, no cash refund.',
        [1000000, -100000], [500000], expected(900000, 500000, 400000))
    add(13, 'Payment assigned to contractor but not invoice',
        'Agreement 10000, completed deposit 2000 belongs to contractor; no invoice allocation.',
        [1000000], [200000], expected(1000000, 200000, 800000), issues=['UNALLOCATED_ADVANCE'])
    add(14, 'Negative remainder retained', 'Agreement 10000, payments 11000, no refund yet.',
        [1000000], [1100000], expected(1000000, 1100000, -100000), issues=['RECORDED_CREDIT_BALANCE'])
    add(15, 'Mixed personal purchase and contractor credit',
        'Owner receipt 1000 contains project materials 800 and personal items 200; contractor explicitly grants 800 reduction. Owner purchase is not payment to contractor.',
        [1000000, -80000], [500000], expected(920000, 500000, 420000),
        excluded=['personal_goods_200', 'owner_purchase_as_contractor_payment'])
    add(16, 'Unknown recipient excluded from contractor payments',
        'Agreement 10000; completed 3000 confirmed contractor payment; another 2000 transfer has unknown recipient.',
        [1000000], [300000], expected(1000000, 300000, 700000),
        excluded=['unknown_recipient_transfer_2000'], issues=['UNRESOLVED_RECIPIENT'])
    write('fixtures/ledger_cases.json', {'version': '0.1', 'currency': 'USD',
          'notice': 'Synthetic normalized reference cases, not real customer data. Expected normalization is supplied; arithmetic checks do not validate OCR or application behavior.',
          'cases': cases})


if __name__ == '__main__':
    build_api()
    build_extraction()
    build_cases()
    print('Generated OpenAPI, extraction schema, extraction example and 16 ledger cases.')
