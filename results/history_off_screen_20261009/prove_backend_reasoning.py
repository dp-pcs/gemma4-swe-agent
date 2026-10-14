import argparse
import hashlib
import json
import urllib.request
from pathlib import Path


def digest(content):
    return hashlib.sha256(content).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--api-base', default='http://127.0.0.1:8000/v1')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.output.absolute()
    root.mkdir(parents=True, exist_ok=False)
    base = args.api_base.rstrip('/')
    server = base.removesuffix('/v1')
    evidence = []

    def save(name, value, kind):
        path = root / name
        path.write_text(json.dumps(value, indent=2) + '\n')
        evidence.append({'path': name, 'sha256': digest(path.read_bytes()), 'kind': kind})
        return name

    def call(url, body=None):
        payload = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json', 'Authorization': 'Bearer EMPTY'})
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.load(response)

    version = call(server + '/version')
    save('version.json', version, 'backend_effective_config')
    if version.get('version') != '0.19.1':
        raise RuntimeError('Backend is not the pinned current vLLM version')
    info = call(server + '/server_info')
    info_structured = call(server + '/server_info?config_format=json')
    save('server_info.json', info, 'backend_effective_config')
    save('server_info_structured.json', info_structured, 'backend_effective_config')
    config = info_structured['vllm_config']
    if config['model_config']['max_model_len'] != 32768:
        raise RuntimeError('Backend context is not 32768')
    reasoning_config = config.get('reasoning_config') or {}
    if reasoning_config.get('reasoning_start_str') != '<|channel>' or reasoning_config.get('reasoning_end_str') != '<channel|>':
        raise RuntimeError('Backend lacks actual Gemma4 budget-enforcement delimiters')
    models = call(base + '/models')
    save('models.json', models, 'backend_effective_config')
    if not {'main_lora', 'tool_lora'}.issubset({model['id'] for model in models['data']}):
        raise RuntimeError('Both frozen adapter aliases must be served')
    problem = 'Find the least positive integer x satisfying x = 17 modulo 97, x = 31 modulo 101, and x = 43 modulo 103. Return x with a concise justification.'
    response_rows = []
    for alias in ('main_lora', 'tool_lora'):
        body = {'model': alias, 'messages': [{'role': 'user', 'content': problem}], 'temperature': 0.2, 'top_p': 0.95, 'seed': 0, 'max_completion_tokens': 2048, 'thinking_token_budget': 4096, 'chat_template_kwargs': {'enable_thinking': True}, 'return_token_ids': True}
        request_path = save(alias + '_request.json', body, 'model_request')
        response = call(base + '/chat/completions', body)
        response_path = save(alias + '_response.json', response, 'model_response')
        message = response['choices'][0]['message']
        reasoning = message.get('reasoning_content') or message.get('reasoning')
        if response.get('model') != alias or not isinstance(reasoning, str) or not reasoning.strip():
            raise RuntimeError('Live adapter response did not contain actual reasoning')
        response_rows.append({'model': alias, 'source': 'live_model', 'raw_request_path': request_path, 'raw_response_path': response_path, 'reasoning_sha256': digest(reasoning.encode())})

    # Exercise the actual backend clamp, rather than trusting accepted request keys.
    delimiters = {}
    for name, marker in (('start', '<|channel>'), ('end', '<channel|>')):
        body = {'model': 'main_lora', 'prompt': marker, 'add_special_tokens': False}
        save('tokenize_' + name + '_request.json', body, 'model_request')
        response = call(server + '/tokenize', body)
        save('tokenize_' + name + '_response.json', response, 'backend_effective_config')
        tokens = response['tokens']
        if len(tokens) != 1:
            raise RuntimeError('Gemma4 reasoning delimiter is not a single tokenizer token')
        delimiters[name] = tokens[0]
    body = {'model': 'main_lora', 'messages': [{'role': 'user', 'content': problem}], 'temperature': 0.2, 'top_p': 0.95, 'seed': 0, 'max_completion_tokens': 2048, 'thinking_token_budget': 16, 'chat_template_kwargs': {'enable_thinking': True}, 'return_token_ids': True}
    save('budget16_request.json', body, 'model_request')
    response = call(base + '/chat/completions', body)
    save('budget16_response.json', response, 'model_response')
    tokens = response['choices'][0].get('token_ids')
    if not isinstance(tokens, list):
        raise RuntimeError('Backend omitted actual generated token IDs needed for clamp proof')
    start = tokens.index(delimiters['start'])
    end = tokens.index(delimiters['end'], start + 1)
    generated_thinking_tokens = end - start - 1
    if generated_thinking_tokens != 16:
        raise RuntimeError(f'Probe did not exercise termination at the actual configured cap: {generated_thinking_tokens}')
    baseline_choice = json.loads((root / 'main_lora_response.json').read_text())['choices'][0]
    baseline_tokens = baseline_choice['token_ids']
    baseline_start = baseline_tokens.index(delimiters['start'])
    baseline_truncated = delimiters['end'] not in baseline_tokens[baseline_start + 1:]
    if baseline_truncated:
        if baseline_choice['finish_reason'] != 'length' or baseline_choice['message'].get('content'):
            raise RuntimeError('Missing baseline reasoning delimiter is not a pure reasoning output-limit truncation')
        baseline_end = len(baseline_tokens)
    else:
        baseline_end = baseline_tokens.index(delimiters['end'], baseline_start + 1)
    if baseline_end - baseline_start - 1 <= 16:
        raise RuntimeError('Unclamped live response did not exceed the small probe cap')
    clamp = {'requested_thinking_budget': 16, 'actual_generated_tokens_between_delimiters': generated_thinking_tokens, 'actual_start_token_index': start, 'actual_end_token_index': end, 'token_ids_source': 'budget16_response.json', 'baseline4096_generated_thinking_tokens': baseline_end - baseline_start - 1, 'baseline4096_thinking_tokens_are_lower_bound': baseline_truncated, 'limit_observed': True, 'comparison': 'Same live main adapter, input, seed and sampling; only the probe thinking budget changes from4096 to16.'}
    save('budget16_observation.json', clamp, 'backend_effective_config')
    proof = {'api_base': base, 'version': '0.19.1', 'max_model_len': 32768, 'thinking_budget': 4096, 'enable_thinking': True, 'backend_enforcement_verified': True, 'server_info_object_sha256': digest(json.dumps(info, sort_keys=True, separators=(',', ':')).encode()), 'evidence': evidence, 'responses': response_rows, 'budget_probe': clamp, 'interpretation': 'Actual current backend configuration, live reasoning for both aliases, and observed small-budget generation. No fixture responses, fabricated token metadata, or solving-rate claim.'}
    path = root / 'reasoning_proof.json'
    path.write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps({'proof': str(path), 'sha256': digest(path.read_bytes()), 'live_adapter_responses': len(response_rows), 'budget16_observation': clamp}, indent=2))


if __name__ == '__main__':
    main()
