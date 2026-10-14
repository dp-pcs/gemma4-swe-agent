#!/usr/bin/env python3
"""Bounded live vLLM transport observation, never a solving-rate experiment.

After backend admission: --api-base http://127.0.0.1:8000/v1 --model-root MODEL
--output NEW_DIR. Existing output is refused. Fourteen frozen sequential requests
(no retries), two real native SDK declarations, both adapter aliases, exact HTTP
bytes, returned generation token IDs, local tokenizer-only raw decoding, actual
SDK response conversion, and installed vLLM pure-parser source/replay are retained.
Twelve auto-choice observations and two explicitly diagnostic-only forced-choice
controls never change the candidate or evaluation sampling. No tool is executed.
No weights are loaded, no packages installed, and tokenizer access is local-only.
Attribution is conservative: raw evidence is required before blaming a parser;
forced-choice JSON observations cannot prove an auto Gemma parser defect.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
import hashlib
import importlib.metadata
import inspect
import itertools
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import traceback
import urllib.parse

os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['PYTHONNOUSERSITE'] = '1'
VERSIONS = {'vllm': '0.19.1', 'swegemma': '0.2.11', 'adk-submission': '0.2.13',
            'adk-eval-core': '0.1.0', 'google-adk': '1.36.1'}
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_REQUESTS = 14
REQUEST_TIMEOUT_SECONDS = 30
TOTAL_TIMEOUT_SECONDS = 600
STRING_DELIM = '<|"|>'
PAYLOADS = [
    ('flat', ['--root', '/workspace', 'locate', 'empty']),
    ('multiline_quote', ['--root', '/workspace', 'literal', 'line one\r\nline two\n"double" and \'single\' quotes\\backslash\nliteral `backticks` and ""doubled quotes""']),
    ('unicode_control', ['--root', '/workspace', 'literal', 'café Straße Ω λ 雪\t\r\ncontrol:\x01']),
]

# A killed subprocess gives the whole exchange a hard wall-clock bound, unlike
# a socket read timeout that a continuously trickling response could extend.
# send() captures the actual plaintext HTTP request bytes before socket/TLS
# transport. The response body is retained byte-for-byte, not model-reconstructed.
HTTP_EXCHANGE = r'''
import hashlib, http.client, json, sys
from pathlib import Path
from urllib.parse import urlsplit
endpoint, directory, stem, timeout, maximum = sys.argv[1:]
output = Path(directory)
url = urlsplit(endpoint)
base = http.client.HTTPSConnection if url.scheme == 'https' else http.client.HTTPConnection
class CapturingConnection(base):
    def send(self, data):
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError('Expected concrete HTTP bytes')
        with (output / (stem + '_HTTP_request_plaintext.raw')).open('ab') as capture:
            capture.write(data)
        return super().send(data)
connection = CapturingConnection(url.hostname, port=url.port, timeout=float(timeout))
try:
    body = sys.stdin.buffer.read()
    connection.request('POST', url.path, body=body,
                       headers={'Content-Type': 'application/json', 'Authorization': 'Bearer EMPTY'})
    response = connection.getresponse()
    raw = response.read(int(maximum) + 1)
    (output / (stem + '_response.raw')).write_bytes(raw)
    metadata = dict(status=response.status, reason=response.reason, headers=response.getheaders(),
                    body_artifact=stem + '_response.raw', body_sha256=hashlib.sha256(raw).hexdigest())
    (output / (stem + '_HTTP_response.json')).write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps(metadata))
finally:
    connection.close()
'''


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


@contextmanager
def no_connections():
    original, original_ex = socket.socket.connect, socket.socket.connect_ex
    def blocked(*args, **kwargs):
        raise RuntimeError('Unexpected SDK/tokenizer network connection forbidden')
    socket.socket.connect = socket.socket.connect_ex = blocked
    try:
        yield
    finally:
        socket.socket.connect, socket.socket.connect_ex = original, original_ex


def compact(value):
    """Independent canonical serialization used only to compare known literals."""
    if isinstance(value, str):
        if STRING_DELIM in value:
            raise ValueError('Case contains reserved Gemma string delimiter')
        return STRING_DELIM + value + STRING_DELIM
    if isinstance(value, list):
        return '[' + ','.join(compact(item) for item in value) + ']'
    if isinstance(value, dict):
        return ','.join(key + ':' + compact(item) for key, item in value.items())
    raise TypeError(type(value).__name__)


def raw_calls(text):
    """Lossless brace scanner: never interpret/coerce values from model text."""
    calls = []
    for match in re.finditer(r'<\|tool_call>call:([\w.\-]+)\{', text):
        start = match.end()
        depth, index, in_string = 1, start, False
        while index < len(text):
            if text.startswith(STRING_DELIM, index):
                in_string = not in_string
                index += len(STRING_DELIM)
                continue
            if not in_string:
                if text[index] == '{':
                    depth += 1
                elif text[index] == '}':
                    depth -= 1
                    if depth == 0:
                        break
            index += 1
        complete = depth == 0 and text.startswith('<tool_call|>', index + 1)
        calls.append(dict(name=match.group(1), raw_arguments=text[start:index], complete=complete,
                          start=match.start(), end=index + 1))
    return calls


def exact_raw_arguments(call, expected):
    # Keys may be emitted in a different order; literal string bytes are never
    # whitespace-normalized. Unrecognized variants remain unattributed.
    return call['complete'] and any(call['raw_arguments'] == compact(dict(items))
                                    for items in itertools.permutations(expected.items()))


def json_objects(text):
    """Independent JSON observations for forced choice; not a Gemma parser."""
    decoder = json.JSONDecoder()
    found = []
    for match in re.finditer(r'\{', text):
        try:
            value, consumed = decoder.raw_decode(text[match.start():])
        except ValueError:
            continue
        if isinstance(value, dict) and ('command' in value or ('args' in value and 'skill_name' in value)):
            found.append(dict(start=match.start(), end=match.start() + consumed, arguments=value))
    return found


def parsed_api_calls(response):
    calls = []
    for call in response['choices'][0].get('message', {}).get('tool_calls') or []:
        function = call.get('function', {})
        raw = function.get('arguments')
        observation = dict(name=function.get('name'), raw_arguments=raw)
        try:
            observation['arguments'] = json.loads(raw)
        except (ValueError, TypeError) as error:
            observation['parse_error'] = repr(error)
        calls.append(observation)
    return calls


def extract_parser(output):
    """Extract only the actual installed three pure functions, without vLLM import."""
    distribution = importlib.metadata.distribution('vllm')
    source = Path(distribution.locate_file('vllm/tool_parsers/gemma4_tool_parser.py'))
    data = source.read_bytes()
    text = data.decode('utf-8')
    tree = ast.parse(text, filename=str(source))
    names = {'_parse_gemma4_value', '_parse_gemma4_args', '_parse_gemma4_array'}
    definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in definitions} != names:
        raise RuntimeError('Installed pinned vLLM parser pure functions differ')
    delimiters = [node for node in tree.body if isinstance(node, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == 'STRING_DELIM' for t in node.targets)]
    if len(delimiters) != 1 or ast.literal_eval(delimiters[0].value) != STRING_DELIM:
        raise RuntimeError('Installed Gemma parser delimiter differs')
    segments = [ast.get_source_segment(text, delimiters[0])] + [ast.get_source_segment(text, node) for node in definitions]
    extracted = '\n\n'.join(segments) + '\n'
    (output / 'installed_gemma4_tool_parser.py').write_bytes(data)
    (output / 'extracted_gemma4_pure_functions.py').write_text(extracted)
    namespace = {}
    exec(compile(extracted, str(source) + ':pure-functions-only', 'exec'), namespace)
    provenance = dict(installed_path=str(source), installed_source_sha256=digest(data),
                      extracted_source_sha256=digest(extracted.encode()), functions=sorted(names),
                      scope='Actual installed nonstreaming argument functions, not server streaming/request dispatch.')
    return namespace['_parse_gemma4_args'], provenance


def attribute(expected_name, expected, calls, independent_json, replay, api, sdk, choice_mode):
    api_values = [dict(name=c['name'], arguments=c.get('arguments')) for c in api]
    expected_values = [dict(name=expected_name, arguments=expected)]
    raw_valid = len(calls) == 1 and calls[0]['name'] == expected_name and exact_raw_arguments(calls[0], expected)
    json_valid = any(item['arguments'] == expected for item in independent_json)
    outcome = dict(api_arguments_match_expected=api_values == expected_values,
                   sdk_arguments_match_api=sdk == api_values if sdk is not None else None,
                   independently_exact_valid_gemma_raw=raw_valid,
                   independently_valid_json_raw=json_valid,
                   attribution='unattributed', parser_defect_proven=False)
    if sdk is not None and sdk != api_values:
        outcome['attribution'] = 'observed_SDK_conversion_changed_API_arguments'
    elif raw_valid and api_values != expected_values:
        if choice_mode == 'auto' and replay == expected_values:
            outcome['attribution'] = 'API_extraction_changed_valid_raw_arguments; specific_server_stage_unproven'
        elif choice_mode == 'auto' and replay != expected_values:
            outcome['attribution'] = 'installed_pure_parser_changed_independently_valid_raw_arguments'
            outcome['parser_defect_proven'] = True
        else:
            outcome['attribution'] = 'forced_choice_transport_differs_from_valid_raw; not_auto_parser_evidence'
    elif choice_mode == 'forced' and json_valid and api_values != expected_values:
        outcome['attribution'] = 'forced_choice_API_transport_changed_valid_JSON; not_auto_parser_evidence'
    elif api_values == expected_values and sdk == api_values:
        outcome['attribution'] = 'observed_API_and_SDK_arguments_preserved; raw_match_' + str(raw_valid or json_valid)
    elif expected_name == 'run_skill_script' and len(calls) == 1 and calls[0]['name'] == expected_name and calls[0]['complete']:
        shape = re.search(r'(?:^|,)\s*args\s*:\s*(\{|<\|"\|>|\[\s*\[)', calls[0]['raw_arguments'])
        if shape:
            outcome['attribution'] = 'model_raw_emitted_nonflat_shape_for_requested_flat_list'
            outcome['raw_shape_evidence'] = shape.group(0)
    elif len(independent_json) == 1 and expected_name == 'run_skill_script':
        emitted = independent_json[0]['arguments'].get('args')
        if not isinstance(emitted, list) or any(not isinstance(item, str) for item in emitted):
            outcome['attribution'] = 'model_raw_JSON_emitted_nonflat_shape_for_requested_flat_list'
            outcome['raw_shape_evidence'] = emitted
    outcome['limits'] = ('No tool execution. A correct API shape alone cannot prove the raw model shape. '
                         'Installed pure parser replay does not prove that server dispatch used it. '
                         'Noncanonical/missing/truncated raw calls and forced JSON routing remain unattributed.')
    return outcome


def main(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = dict(status='incomplete', complete=False, diagnostic_only=True, model_requests_attempted=0,
                  requests=[], assertions=[], attribution_limits=[
                      'Transport observations only; no solving-rate, candidate-improvement, or model instruction-following claim.',
                      'run_skill_script is a separate declaration diagnostic, not present in the evaluated candidate.',
                      'Forced tool choice and token-ID return are diagnostic-only; evaluation settings are untouched.',
                      'Only generated token IDs returned by the live server are raw-generation evidence; never retokenized API text.',
                      'SDK conversion is a real offline conversion of the exact live response, not another generation.',
                      'Canonical parser inputs are explicitly synthetic CPU inputs, never fabricated model outputs.',
                      'No streaming observation; installed parser source may not independently prove loaded server source identity.'
                  ], bounds=dict(max_requests=MAX_REQUESTS, per_request_timeout_seconds=REQUEST_TIMEOUT_SECONDS,
                                 total_request_deadline_seconds=TOTAL_TIMEOUT_SECONDS, max_completion_tokens=1024,
                                 response_bytes=MAX_RESPONSE_BYTES, retries=0))
    failure = None
    start = time.monotonic()

    def require(condition, name, details=None):
        report['assertions'].append(dict(name=name, passed=bool(condition), details=details))
        if not condition:
            raise AssertionError(name + ': ' + repr(details))

    try:
        (output / 'transport_diagnostic.py').write_bytes(Path(__file__).read_bytes())
        url = urllib.parse.urlsplit(args.api_base)
        require(url.scheme in {'http', 'https'} and bool(url.hostname) and not url.username and not url.password
                and not url.query and not url.fragment, 'explicit HTTP API endpoint', args.api_base)
        api_base = args.api_base.rstrip('/')
        if not api_base.endswith('/v1'):
            api_base += '/v1'
        report.update(api_base=api_base, model_root=str(args.model_root.resolve()))
        report['versions'] = {name: importlib.metadata.version(name) for name in VERSIONS}
        require(report['versions'] == VERSIONS, 'exact installed diagnostic SDK/vLLM versions', report['versions'])
        with no_connections():
            from google.adk.tools.skill_toolset import RunSkillScriptTool, SkillToolset
            from google.adk.tools.function_tool import FunctionTool
            from google.adk.models.lite_llm import (_function_declaration_to_tool_param,
                                                    _model_response_to_generate_content_response)
            from swegemma.tools.execution import make_run_command
            from litellm import ModelResponse
            from transformers import AutoTokenizer
            tokenizer = AutoTokenizer.from_pretrained(str(args.model_root.resolve()), local_files_only=True,
                                                       trust_remote_code=False)
            declarations = {
                'run_skill_script': RunSkillScriptTool(SkillToolset(skills=[]))._get_declaration(),
                'run_command': FunctionTool(make_run_command(None))._get_declaration(),
            }
            native_tools = {name: _function_declaration_to_tool_param(declaration)
                            for name, declaration in declarations.items()}
        save(output / 'native_function_declarations.json', {name: declaration.model_dump(exclude_none=True, mode='json')
                                                           for name, declaration in declarations.items()})
        save(output / 'native_openai_tools.json', native_tools)
        report['native_declaration_provenance'] = []
        for index, obj in enumerate([RunSkillScriptTool, FunctionTool, make_run_command,
                                    _function_declaration_to_tool_param, _model_response_to_generate_content_response]):
            path = Path(inspect.getsourcefile(obj))
            artifact = f'sdk_source_{index:02d}_{path.name}'
            data = path.read_bytes()
            (output / artifact).write_bytes(data)
            report['native_declaration_provenance'].append(dict(installed_path=str(path), artifact=artifact, sha256=digest(data)))
        tokenizer_files = [path for path in args.model_root.iterdir() if path.is_file() and (
            path.name.startswith('tokenizer') or path.name in {'special_tokens_map.json', 'added_tokens.json', 'chat_template.jinja', 'config.json'})]
        tokenizer_dir = output / 'tokenizer_evidence'
        tokenizer_dir.mkdir()
        report['tokenizer'] = dict(type=type(tokenizer).__module__ + '.' + type(tokenizer).__qualname__, local_only=True, weights_loaded=False, files=[])
        for path in sorted(tokenizer_files):
            data = path.read_bytes()
            (tokenizer_dir / path.name).write_bytes(data)
            report['tokenizer']['files'].append(dict(path=str(path), artifact='tokenizer_evidence/' + path.name, sha256=digest(data), bytes=len(data)))
        parse_args, report['parser_provenance'] = extract_parser(output)
        canonical = []
        for name, arguments in PAYLOADS:
            expected = dict(skill_name='transport-diagnostic', file_path='scripts/never_executed.py', args=arguments)
            serialized = compact(expected)
            parsed = parse_args(serialized)
            canonical.append(dict(case=name, synthetic_cpu_input=True, raw_arguments=serialized,
                                  expected=expected, observed=parsed, preserved=parsed == expected))
        nested = dict(skill_name='transport-diagnostic', file_path='scripts/never_executed.py', args=[PAYLOADS[0][1]])
        serialized = compact(nested)
        parsed = parse_args(serialized)
        canonical.append(dict(case='nested_list_negative_shape_control', synthetic_cpu_input=True,
                              requested_flat_shape=False, raw_arguments=serialized, expected=nested,
                              observed=parsed, preserved=parsed == nested))
        (output / 'HTTP_exchange_worker.py').write_text(HTTP_EXCHANGE)
        save(output / 'canonical_CPU_parser_cases.json', canonical)
        report['canonical_CPU_parser_cases'] = canonical

        cases = []
        for model in ['main_lora', 'tool_lora']:
            for case_name, arguments in PAYLOADS:
                for surface in ['run_skill_script', 'run_command']:
                    cases.append((model, case_name, arguments, surface, 'auto'))
        # Explicit controls, not candidate/evaluation changes or retries.
        for surface in ['run_skill_script', 'run_command']:
            cases.append(('main_lora', PAYLOADS[1][0], PAYLOADS[1][1], surface, 'forced'))
        require(len(cases) == MAX_REQUESTS, 'frozen sequential request count', len(cases))
        for index, (model, case_name, arguments, surface, mode) in enumerate(cases):
            record = dict(index=index, model=model, case=case_name, surface=surface, choice_mode=mode, status='incomplete')
            report['requests'].append(record)
            stem = f'{index:02d}_{model}_{case_name}_{surface}_{mode}'
            try:
                remaining = TOTAL_TIMEOUT_SECONDS - (time.monotonic() - start)
                require(remaining > 0, 'total diagnostic deadline remains', remaining)
                if surface == 'run_skill_script':
                    expected = dict(skill_name='transport-diagnostic', file_path='scripts/never_executed.py', args=arguments)
                else:
                    # Same complete argv strings, now represented by a literal
                    # Python heredoc in the actual native command:string field.
                    command = "python3 - <<'TRANSPORT_LITERAL'\nimport json\nargs = " + repr(arguments) + "\nprint(json.dumps(args, ensure_ascii=False))\nTRANSPORT_LITERAL"
                    expected = dict(command=command)
                record['expected_arguments'] = expected
                request = dict(model=model, messages=[
                    dict(role='system', content='Transport-only diagnostic. Call the provided function exactly once with the literal values supplied. Do not solve, edit, or execute anything. Preserve every string and use args as a flat list of strings where requested.'),
                    dict(role='user', content='Call ' + surface + ' with EXACT arguments from this JSON object (decode JSON escapes into the literal string values; do not stringify arrays or turn them into objects):\n' + json.dumps(expected, ensure_ascii=False)),
                ], tools=[native_tools[surface]], tool_choice='auto' if mode == 'auto' else dict(type='function', function=dict(name=surface)),
                    temperature=.2, top_p=.95, seed=0, max_completion_tokens=1024,
                    thinking_token_budget=64, chat_template_kwargs=dict(enable_thinking=True),
                    return_token_ids=True, skip_special_tokens=False, stream=False)
                request_bytes = json.dumps(request, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
                (output / (stem + '_request.json')).write_bytes(request_bytes)
                record['request_sha256'] = digest(request_bytes)
                endpoint = api_base + '/chat/completions'
                save(output / (stem + '_HTTP_request.json'), dict(method='POST', url=endpoint,
                    headers={'Content-Type': 'application/json', 'Authorization': 'Bearer EMPTY'}, body_artifact=stem + '_request.json'))
                report['model_requests_attempted'] += 1
                began = time.monotonic()
                try:
                    worker = subprocess.run([sys.executable, '-c', HTTP_EXCHANGE, endpoint, str(output), stem,
                                             str(min(REQUEST_TIMEOUT_SECONDS, remaining)), str(MAX_RESPONSE_BYTES)],
                                            input=request_bytes, capture_output=True,
                                            timeout=min(REQUEST_TIMEOUT_SECONDS, remaining), check=False)
                except subprocess.TimeoutExpired as error:
                    (output / (stem + '_HTTP_worker.stderr')).write_bytes(error.stderr or b'')
                    raise
                (output / (stem + '_HTTP_worker.stderr')).write_bytes(worker.stderr)
                require(worker.returncode == 0, stem + ': bounded actual HTTP worker completed',
                        dict(returncode=worker.returncode, stderr=worker.stderr.decode('utf-8', errors='replace')))
                metadata = json.loads(worker.stdout)
                http_status = metadata['status']
                raw_response = (output / (stem + '_response.raw')).read_bytes()
                record['elapsed_seconds'] = time.monotonic() - began
                record.update(http_status=http_status, response_sha256=digest(raw_response))
                require(len(raw_response) <= MAX_RESPONSE_BYTES, stem + ': bounded complete HTTP body')
                require(http_status == 200, stem + ': actual live HTTP success', http_status)
                payload = json.loads(raw_response)
                choice = payload['choices'][0]
                ids = choice.get('token_ids')
                require(isinstance(ids, list) and bool(ids) and all(isinstance(value, int) and not isinstance(value, bool) for value in ids),
                        stem + ': actual generated token IDs returned')
                raw_text = tokenizer.decode(ids, skip_special_tokens=False, clean_up_tokenization_spaces=False)
                (output / (stem + '_generated_raw.txt')).write_bytes(raw_text.encode('utf-8'))
                save(output / (stem + '_generated_token_ids.json'), ids)
                record.update(generated_token_count=len(ids), raw_text_sha256=digest(raw_text.encode()),
                              finish_reason=choice.get('finish_reason'), stop_reason=choice.get('stop_reason'))
                calls = raw_calls(raw_text)
                replay = [dict(name=call['name'], arguments=parse_args(call['raw_arguments'])) for call in calls if call['complete']]
                independent_json = json_objects(raw_text)
                api_calls = parsed_api_calls(payload)
                sdk_calls = None
                sdk_record = {}
                try:
                    with no_connections():
                        converted = _model_response_to_generate_content_response(ModelResponse(**payload))
                    sdk_record['response'] = converted.model_dump(exclude_none=True, mode='json')
                    sdk_calls = [dict(name=part.function_call.name, arguments=part.function_call.args)
                                 for part in (converted.content.parts if converted.content else []) if part.function_call]
                    sdk_record['function_calls'] = sdk_calls
                except Exception as error:
                    sdk_record.update(error=repr(error), traceback=traceback.format_exc())
                observed = dict(raw_tool_calls=calls, installed_pure_parser_replay=replay,
                                independently_decoded_JSON_objects=independent_json,
                                parsed_API_calls=api_calls, actual_SDK_conversion=sdk_record)
                save(output / (stem + '_observations.json'), observed)
                record['attribution'] = attribute(surface, expected, calls, independent_json, replay,
                                                   api_calls, sdk_calls, mode)
                record['status'] = 'complete'
            except Exception as error:
                failure = error
                record.update(error=repr(error), traceback=traceback.format_exc())
                # Continue the frozen sequence after a case failure; no retry.
            save(output / 'transport_report.json', report)
        report['complete'] = len(report['requests']) == MAX_REQUESTS and all(r['status'] == 'complete' for r in report['requests'])
        report['status'] = 'complete' if report['complete'] else 'incomplete'
    except Exception as error:
        failure = error
        report.update(error=repr(error), traceback=traceback.format_exc())
    finally:
        report['elapsed_seconds'] = time.monotonic() - start
        report['artifacts'] = [{'path': str(path.relative_to(output)), 'sha256': digest(path.read_bytes()), 'bytes': path.stat().st_size}
                               for path in sorted(output.rglob('*')) if path.is_file() and path.name != 'transport_report.json']
        save(output / 'transport_report.json', report)
        print(json.dumps(dict(status=report['status'], complete=report['complete'], model_requests_attempted=report['model_requests_attempted'], output=str(output))), flush=True)
    if failure is not None or not report['complete']:
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--api-base', required=True)
    parser.add_argument('--model-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args())
