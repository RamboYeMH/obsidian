#!/usr/bin/env python3
"""Thin benchmark MCP client. No business verdicts or automatic mutation retries."""
import argparse
import json
import os
import re
from pathlib import Path
import sys
import tempfile
import time
import urllib.request
import uuid

TERMINAL = {'succeeded', 'failed', 'stopped', 'timed_out', 'budget_exceeded'}

SECRET_KEYS = {'password', 'passwd', 'authorization', 'cookie', 'setcookie', 'privatekey',
               'jwt', 'jwttoken', 'accesstoken', 'refreshtoken', 'idtoken', 'token', 'secret',
               'fastloginsecret', 'apikey', 'clientsecret', 'signature', 'prototext'}
SECRET_TEXT = re.compile(r'(?i)((?:access[_-]?token|refresh[_-]?token|password|secret|authorization|api[_-]?key)\s*[=:]\s*)[^\s,;]+')
JWT_TEXT = re.compile(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b')
BEARER_TEXT = re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*')
URL_CREDENTIALS = re.compile(r'(https?://)[^\s/@:]+:[^\s/@]+@')


def redact(value):
    """Redact persisted evidence and displayed values without modifying live requests."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            field = re.sub(r'[^a-z0-9]', '', key.rsplit('.', 1)[-1].lower())
            sensitive = field in SECRET_KEYS or field.endswith(('token', 'secret', 'password', 'privatekey', 'apikey', 'masterkey'))
            result[key] = '[REDACTED]' if sensitive else redact(item)
        return result
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        # MCP content[].text can contain a second JSON copy of the response.
        if value.lstrip().startswith(('{', '[')):
            try:
                return json.dumps(redact(json.loads(value)), ensure_ascii=False)
            except ValueError:
                pass
        value = BEARER_TEXT.sub('Bearer [REDACTED]', value)
        value = URL_CREDENTIALS.sub(r'\1[REDACTED]@', value)
        return JWT_TEXT.sub('[REDACTED]', SECRET_TEXT.sub(r'\1[REDACTED]', value))
    return value


class ClientError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ClientError('HTTP redirect refused')


class Evidence:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def save(self, value):
        name = uuid.uuid4().hex + '.json'
        path = self.root / name
        with path.open('x', encoding='utf-8') as f:
            os.chmod(path, 0o600)
            json.dump(redact(value), f, ensure_ascii=False)
        return name

    def run_path(self, run_id):
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,160}', run_id):
            raise ClientError('invalid run id')
        return self.root / 'runs' / (run_id + '.json')

    def run_manifest(self, run_id):
        path = self.run_path(run_id)
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {'run_id': run_id, 'state_evidence': [], 'pages': []}

    def save_run_manifest(self, run_id, manifest):
        path = self.run_path(run_id)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.parent.is_symlink():
            raise ClientError('run index directory must not be a symlink')
        fd, tmp_name = tempfile.mkstemp(prefix='.run-', suffix='.tmp', dir=path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(redact(manifest), stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def cleanup_candidates(self, older_than_days):
        cutoff = time.time() - older_than_days * 86400
        protected = set()
        runs_dir = self.root / 'runs'
        if runs_dir.exists():
            for path in runs_dir.glob('*.json'):
                try:
                    manifest = json.loads(path.read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    continue
                incomplete = (manifest.get('status') not in TERMINAL
                              or manifest.get('collection_complete') is not True)
                if incomplete:
                    protected.update(ref for ref in (manifest.get('startup_evidence'),
                                                       manifest.get('request_ref')) if ref)
                    protected.update(manifest.get('state_evidence', []))
                    protected.update(page.get('evidence_ref') for page in manifest.get('pages', []))
        candidates = []
        for path in self.root.rglob('*.json'):
            if path.parent == self.root / 'runs' or path.is_symlink() or not path.is_file():
                continue
            try:
                if path.stat().st_mtime < cutoff and path.name not in protected:
                    candidates.append(path)
            except OSError:
                continue
        return candidates

    def read(self, ref):
        path = (self.root / ref).resolve()
        if path.parent != self.root or path.suffix != '.json':
            raise ClientError('evidence reference outside store')
        return json.loads(path.read_text(encoding='utf-8'))


def decode_response(body, request_id):
    try:
        values = [json.loads(body)]
    except ValueError:
        values, data = [], []
        for line in (body.replace('\r\n', '\n') + '\n\n').split('\n'):
            if line.startswith('data:'):
                data.append(line[5:].lstrip(' '))
            elif not line and data:
                values.append(json.loads('\n'.join(data)))
                data = []
    for value in values:
        if isinstance(value, dict) and value.get('id') == request_id:
            return value
    raise ClientError('response missing matching JSON-RPC id')


class MCP:
    def __init__(self, url, timeout, evidence):
        if not url or not url.startswith(('http://', 'https://')):
            raise ClientError('set --url or BENCHMARK_MCP_URL')
        self.url, self.timeout, self.evidence = url, timeout, evidence
        self.session, self.version = None, '2025-03-26'
        self.opener = urllib.request.build_opener(NoRedirect())

    def rpc(self, method, params, notification=False):
        rid = uuid.uuid4().hex
        message = {'jsonrpc': '2.0', 'method': method, 'params': params}
        if not notification:
            message['id'] = rid
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
                   'MCP-Protocol-Version': self.version}
        if self.session:
            headers['Mcp-Session-Id'] = self.session
        token = os.environ.get('BENCHMARK_MCP_TOKEN')
        if token:
            headers['Authorization'] = 'Bearer ' + token
        req = urllib.request.Request(self.url, json.dumps(message).encode(), headers)
        with self.opener.open(req, timeout=self.timeout) as resp:
            self.session = resp.headers.get('Mcp-Session-Id', self.session)
            body = resp.read(16 * 1024 * 1024 + 1)
        if len(body) > 16 * 1024 * 1024:
            raise ClientError('response exceeds 16 MiB; evidence incomplete')
        if notification:
            return None
        return decode_response(body.decode(), rid)

    def initialize(self):
        response = self.rpc('initialize', {'protocolVersion': self.version, 'capabilities': {},
                                         'clientInfo': {'name': 'benchmark-local-client', 'version': '1'}})
        if 'error' in response:
            raise ClientError('MCP initialize failed')
        self.version = response['result'].get('protocolVersion', self.version)
        self.rpc('notifications/initialized', {}, notification=True)

    def call(self, name, args):
        started = time.monotonic()
        response = self.rpc('tools/call', {'name': name, 'arguments': args})
        try:
            ref = self.evidence.save({'tool': name, 'elapsed_seconds': time.monotonic() - started,
                                      'response': response})
        except OSError:
            ref = None
        if 'error' in response:
            error = response['error']
            return None, {'kind': 'rpc_error', 'evidence_ref': ref,
                          'message': redact(str(error.get('message', 'RPC error')))[:1000],
                          'error_code': error.get('code')}
        result = response.get('result', {})
        if result.get('isError'):
            details = result.get('structuredContent') or {}
            texts = [c.get('text', '') for c in result.get('content', []) if c.get('type') == 'text']
            meta = {'kind': 'tool_error', 'evidence_ref': ref,
                    'message': redact(str(details.get('message') or '\n'.join(texts)))[:1000]}
            for key in ('error_code', 'retry_after_seconds', 'next_allowed_at'):
                if key in details:
                    meta[key] = details[key]
            return None, meta
        value = result.get('structuredContent')
        if value is None:
            texts = [c.get('text', '') for c in result.get('content', []) if c.get('type') == 'text']
            try:
                value = json.loads(texts[0])
            except (ValueError, IndexError):
                return None, {'kind': 'unrecognized_response', 'evidence_ref': ref}
        if not isinstance(value, dict):
            return None, {'kind': 'unrecognized_response', 'evidence_ref': ref}
        return value, ({'evidence_ref': ref} if ref else {'kind': 'evidence_save_failed'})


def trace_index_complete(manifest):
    pages = {page.get('after', ''): page for page in manifest.get('pages', [])}
    cursor, visited = '', set()
    while cursor in pages and cursor not in visited:
        visited.add(cursor)
        page = pages[cursor]
        cursor = page.get('next_after', cursor)
        if not page.get('has_more'):
            return len(visited) == len(pages)
    return False


def collect(client, args, run_id):
    store = client.evidence
    manifest = store.run_manifest(run_id)
    if args.after is None:
        cursor = manifest.get('next_after', '')
    else:
        cursor = args.after
    scope_after = cursor
    deadline = time.monotonic() + args.observe_seconds
    refs, status, delay = [], manifest.get('status'), 1
    state_error = None
    run_truncated = bool(manifest.get('trace_truncated'))
    facts, steps, step_count = manifest.get('run_facts', {}), [], 0
    assertions = {'passed': 0, 'failed': 0}
    protocol_errors = []
    execution_status = None
    def fetch(name, params):
        try:
            value, meta = client.call(name, params)
        except Exception as exc:
            return None, {'kind': 'observation_transport_error', 'error_type': type(exc).__name__}
        if meta.get('kind') == 'evidence_save_failed':
            return None, meta
        return value, meta
    while True:
        value, meta = fetch('get_block_test_run', {'run_id': run_id})
        refs.append(meta)
        if meta.get('evidence_ref'):
            manifest['state_evidence'] = (manifest.get('state_evidence', []) + [meta['evidence_ref']])[-20:]
        if value is None:
            state_error = meta['kind']
            break
        facts = {key: value.get(key) for key in ('current_state', 'error', 'stop_reason', 'budget')}
        status = value.get('status')
        run_truncated = run_truncated or bool(value.get('trace_truncated'))
        manifest.update(status=status, run_facts=facts, trace_truncated=run_truncated,
                        state_evidence=manifest.get('state_evidence', []))
        store.save_run_manifest(run_id, manifest)
        if status in TERMINAL or time.monotonic() >= deadline:
            break
        time.sleep(min(delay, max(0, deadline - time.monotonic())))
        delay = min(delay * 2, 8)
    skip_trace = args.after is None and manifest.get('collection_complete') is True
    has_more = bool(manifest.get('has_more', False)) if skip_trace else True
    truncated, count, embedded_missing = run_truncated or bool(manifest.get('truncated')), 0, False
    for _ in range(0 if skip_trace else args.max_pages):
        value, meta = fetch('get_block_test_trace', {'run_id': run_id, 'after': cursor, 'limit': args.page_size})
        refs.append(meta)
        if value is None:
            state_error = state_error or meta['kind']
            break
        events = value.get('events') or []
        page_after = cursor
        def missing(v):
            if isinstance(v, dict):
                return v.get('truncated') is True or any(missing(x) for x in v.values())
            return isinstance(v, list) and any(missing(x) for x in v)
        embedded_missing = embedded_missing or missing(events)
        truncated = truncated or bool(value.get('truncated'))
        has_more = bool(value.get('has_more'))
        next_cursor = value.get('next_after', cursor)
        if has_more and next_cursor == cursor:
            state_error = 'trace_cursor_not_advancing'
            break
        ref = meta.get('evidence_ref')
        if ref:
            manifest['pages'] = [page for page in manifest.get('pages', []) if page.get('after') != page_after]
            manifest['pages'].append({'after': page_after, 'next_after': next_cursor,
                                      'has_more': has_more, 'truncated': bool(value.get('truncated')),
                                      'evidence_ref': ref})
        cursor = next_cursor
        trace_complete = trace_index_complete(manifest)
        manifest.update(next_after=cursor, has_more=has_more,
                        truncated=bool(manifest.get('truncated')) or truncated,
                        collection_complete=status in TERMINAL and trace_complete and not has_more and not truncated
                        and not embedded_missing and not state_error)
        store.save_run_manifest(run_id, manifest)
        if not has_more:
            break
    # Build counters from every uniquely indexed page, including earlier resume calls.
    all_events = []
    for page in manifest.get('pages', []):
        try:
            saved = store.read(page['evidence_ref'])
            response = saved.get('response', {})
            result = response.get('result', {})
            page_value = result.get('structuredContent')
            if page_value is None:
                texts = [c.get('text', '') for c in result.get('content', []) if c.get('type') == 'text']
                page_value = json.loads(texts[0]) if texts else {}
            all_events.extend(page_value.get('events') or [])
        except (OSError, ValueError, KeyError, TypeError):
            state_error = state_error or 'indexed_evidence_unreadable'
    count = len(all_events)
    embedded_missing = any(missing(all_events)) if all_events else False
    truncated = truncated or bool(manifest.get('truncated')) or run_truncated
    for event in all_events:
        if event.get('type') == 'report':
            execution_status = (event.get('observations') or {}).get('execution_status')
        if event.get('type') == 'assertion' and event.get('status') in ('success', 'failed'):
            assertions['passed' if event['status'] == 'success' else 'failed'] += 1
        if event.get('type') == 'error' and not event.get('state') and len(protocol_errors) < 20:
            protocol_errors.append({key: event.get(key) for key in ('cursor', 'protocol', 'detail')})
        if event.get('type') in ('action_result', 'assertion', 'error'):
            step_count += 1
            step = {key: event.get(key) for key in
                    ('cursor', 'type', 'state', 'protocol', 'status', 'summary', 'detail')}
            login = event.get('protocol') in ('AuthReq', 'CharacterLoginReq', 'CharacterCreateReq') or event.get('state') in ('LoginChoice', 'CallLogin', 'AuthChoice', 'ChangeNameChoice', 'VerifyLogin')
            priority = 2 if event.get('status') == 'failed' else (0 if login else 1)
            steps.append((priority, step_count, step))
            steps = sorted(steps, key=lambda item: (item[0], item[1]), reverse=True)[:20]
    refs = [{'evidence_ref': ref} for ref in
            manifest.get('state_evidence', []) + [p['evidence_ref'] for p in manifest.get('pages', [])]]
    trace_complete = trace_index_complete(manifest)
    collection_complete = status in TERMINAL and trace_complete and not (
        has_more or truncated or embedded_missing or state_error)
    manifest.update(status=status, run_facts=facts, trace_truncated=run_truncated,
                    has_more=has_more, truncated=truncated,
                    embedded_evidence_truncated=embedded_missing,
                    collection_complete=collection_complete)
    store.save_run_manifest(run_id, manifest)
    return {'run_id': run_id, 'status': status, 'terminal': status in TERMINAL,
            'observation_budget_exhausted': status not in TERMINAL and state_error is None,
            'next_after': cursor, 'has_more': has_more, 'truncated': truncated,
            'embedded_evidence_truncated': embedded_missing,
            'resume_from': scope_after, 'indexed_pages': len(manifest.get('pages', [])),
            'indexed_events': count,
            'collection_complete': collection_complete,
            'error': state_error, 'evidence': refs,
            'run_manifest': str(store.run_path(run_id).relative_to(store.root)),
            'startup_evidence': manifest.get('startup_evidence'),
            'request_ref': manifest.get('request_ref'),
            'business_verdict': 'agent_required', 'run_facts': facts,
            'execution_status': execution_status,
            'assertion_results': dict(assertions, available=sum(assertions.values()) > 0,
                                     scope='all indexed pages; consult collection_complete'),
            'protocol_errors': protocol_errors,
            'step_sample': [item[2] for item in sorted(steps, key=lambda item: item[1])],
            'step_sample_omitted': max(0, step_count - len(steps))}


def run(args):
    store = Evidence(args.store)
    if args.command == 'read-evidence':
        value = redact(store.read(args.ref))
        if args.pointer:
            if not args.pointer.startswith('/'):
                raise ClientError('JSON pointer must start with /')
            for part in args.pointer[1:].split('/'):
                part = part.replace('~1', '/').replace('~0', '~')
                value = value[int(part)] if isinstance(value, list) else value[part]
        if args.state or args.event_type:
            if not isinstance(value, list):
                raise ClientError('state/type filters require a JSON pointer to an event array')
            value = [v for v in value if isinstance(v, dict)
                     and (not args.state or v.get('state') == args.state)
                     and (not args.event_type or v.get('type') == args.event_type)]
        if args.fields:
            fields = [field.strip() for field in args.fields.split(',') if field.strip()]
            def project(v):
                if not isinstance(v, dict):
                    raise ClientError('field projection requires an object or an array of objects')
                return {key: v[key] for key in fields if key in v}
            value = [project(v) for v in value] if isinstance(value, list) else project(value)
        out = {'evidence_ref': args.ref, 'pointer': args.pointer, 'truncated': False}
        if isinstance(value, list):
            total = len(value)
            value = value[args.offset:args.offset + args.limit]
            out.update(total_items=total, next_offset=args.offset + len(value),
                       has_more=args.offset + len(value) < total)
        encoded = json.dumps(value, ensure_ascii=False)
        if len(encoded.encode()) > args.max_bytes:
            # Return an explicitly marked text fragment, never pretend it is intact JSON.
            out.update(truncated=True, json_fragment=encoded.encode()[:args.max_bytes].decode('utf-8', 'ignore'))
        else:
            out['value'] = value
        return out
    if args.command == 'cleanup':
        candidates = store.cleanup_candidates(args.older_than_days)
        output = {'dry_run': not args.confirm, 'older_than_days': args.older_than_days,
                  'candidate_count': len(candidates),
                  'candidates': [str(p.relative_to(store.root)) for p in candidates[:100]],
                  'omitted': max(0, len(candidates) - 100)}
        if args.confirm:
            removed = 0
            for path in candidates:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
            output.update(removed_count=removed, dry_run=False)
        return output
    client = MCP(args.url, args.timeout, store)
    client.initialize()
    if args.command == 'collect':
        return collect(client, args, args.run_id)
    payload = json.loads(Path(args.input).read_text())
    if not isinstance(payload, dict):
        raise ClientError('input must be a JSON object')
    if args.command == 'apply-draft':
        if not all(k in payload for k in ('id', 'expected_revision', 'operations')):
            raise ClientError('id, expected_revision and operations required')
        tool = 'edit_block_draft'
    elif args.command == 'create-draft':
        tool = 'create_block_draft'
    else:
        if payload.get('confirm') is not True:
            raise ClientError('run input requires confirm=true')
        tool = 'run_block_draft'
    request_ref = store.save({'tool': tool, 'arguments': payload, 'phase': 'before_dispatch'})
    try:
        value, meta = client.call(tool, payload)
    except Exception as exc:
        return {'kind': 'mutation_outcome_unknown', 'request_ref': request_ref,
                'error_type': type(exc).__name__, 'retry_allowed': False}
    if value is None:
        return dict(meta, request_ref=request_ref, retry_allowed=False)
    if args.command == 'run':
        run_id = value.get('run_id')
        if not run_id:
            return dict(meta, kind='startup_outcome_unknown', request_ref=request_ref, retry_allowed=False)
        try:
            store.save_run_manifest(run_id, {'run_id': run_id, 'draft_id': payload.get('draft_id'),
                                             'startup_evidence': meta.get('evidence_ref'), 'request_ref': request_ref,
                                             'state_evidence': [], 'pages': [], 'status': value.get('status')})
            manifest_ref = str(store.run_path(run_id).relative_to(store.root))
        except OSError:
            manifest_ref = None
        print(json.dumps({'phase': 'started', 'run_id': run_id,
                          'startup_evidence': meta, 'request_ref': request_ref,
                          'run_manifest': manifest_ref}), flush=True)
        store.save_run_manifest(run_id, {'run_id': run_id, 'draft_id': payload.get('draft_id'),
                                         'startup_evidence': meta.get('evidence_ref'), 'request_ref': request_ref,
                                         'state_evidence': [], 'pages': [], 'status': value.get('status')})
        try:
            observed = collect(client, args, run_id)
        except Exception as exc:
            observed = {'run_id': run_id, 'collection_complete': False,
                        'run_manifest': str(store.run_path(run_id).relative_to(store.root)),
                        'error_type': type(exc).__name__, 'resume': 'collect',
                        'retry_start_allowed': False}
        return dict(observed, startup_evidence=meta, request_ref=request_ref)
    draft, validation = value.get('draft', {}), value.get('validation', {})
    diagnostics = validation.get('diagnostics', [])
    return dict(meta, request_ref=request_ref, draft_id=draft.get('id'), revision=draft.get('revision'),
                valid=validation.get('valid'), diagnostic_count=len(diagnostics),
                diagnostics=diagnostics[:5], diagnostics_truncated=len(diagnostics) > 5,
                operation_count=len(payload.get('operations', [])))


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default=os.environ.get('BENCHMARK_MCP_URL', 'http://127.0.0.1:28082/mcp'))
    parser.add_argument('--store', default=os.environ.get('BENCHMARK_EVIDENCE_DIR', '~/.cache/benchmark-agent/evidence'))
    parser.add_argument('--timeout', type=float, default=30)
    subs = parser.add_subparsers(dest='command', required=True)
    for name in ('create-draft', 'apply-draft', 'run', 'collect', 'read-evidence', 'cleanup'):
        p = subs.add_parser(name)
        if name in ('create-draft', 'apply-draft', 'run'):
            p.add_argument('--input', required=True)
        if name in ('run', 'collect'):
            if name == 'collect':
                p.add_argument('--run-id', required=True)
            p.add_argument('--after', default='' if name == 'run' else None)
            p.add_argument('--observe-seconds', type=float, default=100)
            p.add_argument('--max-pages', type=int, default=10)
            p.add_argument('--page-size', type=int, default=200)
        if name == 'read-evidence':
            p.add_argument('--ref', required=True)
            p.add_argument('--pointer', default='')
            p.add_argument('--offset', type=int, default=0)
            p.add_argument('--limit', type=int, default=20)
            p.add_argument('--max-bytes', type=int, default=6000)
            p.add_argument('--state')
            p.add_argument('--event-type')
            p.add_argument('--fields', help='comma-separated top-level fields to retain')
        if name == 'cleanup':
            p.add_argument('--older-than-days', type=int, default=30)
            p.add_argument('--confirm', action='store_true', help='delete the displayed eligible files; default is preview only')
    args = parser.parse_args()
    for key in ('timeout', 'max_pages', 'page_size', 'limit', 'max_bytes'):
        if hasattr(args, key) and getattr(args, key) <= 0:
            parser.error(key + ' must be positive')
    for key in ('observe_seconds', 'offset'):
        if hasattr(args, key) and getattr(args, key) < 0:
            parser.error(key + ' must be nonnegative')
    if args.command == 'cleanup' and args.older_than_days < 1:
        parser.error('older-than-days must be at least 1')
    try:
        result = run(args)
    except Exception as exc:
        result = {'kind': 'client_error', 'error_type': type(exc).__name__,
                  'message': str(exc)[:400] if isinstance(exc, ClientError) else 'See command inputs and connection settings'}
    # Bound stdout without losing the full local result.
    failed = bool(result.get('kind') or result.get('error') or result.get('error_type'))
    result = redact(result)
    encoded = json.dumps(result, ensure_ascii=False)
    if len(encoded.encode()) > 12000:
        ref = Evidence(args.store).save(result)
        result = {'summary_truncated': True, 'result_ref': ref}
    print(json.dumps(result, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
