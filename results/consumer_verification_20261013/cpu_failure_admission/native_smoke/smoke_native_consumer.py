#!/usr/bin/env python3
"""CPU-only native SDK consumer before/after proof on fresh restored snapshots.

Run with --archive ZIP --expected-sha256 SHA --data-root DATA --image sha256:ID
--output NEW_DIR [--baseline-archive ZIP]. Requires the already-installed pinned
SDK, local Docker, and an already-present immutable framework image. Never
installs packages, contacts a model, applies test_patch, or writes a repository
probe. The trusted task.patch is fixture/reference setup, not a candidate repair.
Compilation/tool invocation evidence is NOT evidence of model instruction following.
Existing output is refused. SDK_smoke.json and its hashed artifacts survive failure.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import dataclasses
import hashlib
import io
import importlib.metadata
import inspect
import json
import os
from pathlib import Path, PurePosixPath
import re
import tarfile
import socket
import stat
import traceback
import zipfile

os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
os.environ['PYTHONNOUSERSITE'] = '1'
CANDIDATE_SHA = 'e7db4e441ab80d3282f43f9fe76267380457779468d3a091d7e248b52cb750de'
BASELINE_SHA = '75387e03e97b50b3816ba683e88cdce71a9762023e65a5ba79f8b192c6c03142'
VERSIONS = {'swegemma': '0.2.11', 'adk-submission': '0.2.13',
            'adk-eval-core': '0.1.0', 'google-adk': '1.36.1'}
BUDGET = dict(timeout_seconds=90, max_tool_calls=40, max_time_minutes=4, max_turns=100)
ROOT_TOOLS = {'run_command', 'read_file', 'edit_file', 'write_file', 'get_status',
              'submit_patch', 'get_code_neighbors', 'search_similar_code',
              'get_code_subgraph', 'code_analyzer_agent'}
CHILD_TOOLS = {'read_file', 'search_similar_code', 'get_code_neighbors', 'get_code_subgraph'}

# Identical literal consumer command in both phases; no repo files are created.
GUARD = '''import importlib, json
from pathlib import Path
for name in MODULES:
    module = importlib.import_module(name)
    origin = str(Path(module.__file__).resolve())
    print("IMPORT_GUARD " + json.dumps({"module": name, "origin": origin}), flush=True)
    assert origin.startswith("/workspace/"), (name, origin)
'''
RICH_PROBE = GUARD.replace('MODULES', "['rich', 'rich.text', 'rich.console']") + '''from rich.text import Text
from rich.console import Console
text = Text().append_tokens([
    ("long text that will be wrapped with a control code \\r\\n", "red"),
])
console = Console()
with console.capture() as capture:
    console.print(text, width=40)
output = capture.get()
reference = Text("long text that will be wrapped with a control code \\r\\n", style="red")
with console.capture() as reference_capture:
    console.print(reference, width=40)
expected_output = reference_capture.get()
print("CONSUMER_RESULT " + json.dumps({"output": output, "expected_output": expected_output}), flush=True)
assert output == expected_output, (output, expected_output)
'''
FASTAPI_PROBE = GUARD.replace('MODULES', "['fastapi', 'fastapi.dependencies.utils', 'fastapi.routing', 'fastapi.testclient']") + '''from typing import Annotated
from typing_extensions import TypeAliasType
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
async def some_value() -> int:
    return 123
DependedValue = TypeAliasType('DependedValue', Annotated[int, Depends(some_value)], type_params=())
app = FastAPI()
@app.get('/')
async def get_with_dep(value: DependedValue) -> str:
    return f"value: {value}"
response = TestClient(app).get('/')
print("CONSUMER_RESULT " + json.dumps({"status_code": response.status_code, "response_text": response.text}), flush=True)
assert response.status_code == 200, (response.status_code, response.text)
assert response.text == '"value: 123"', response.text
'''
SCENARIOS = [('rich_3471', RICH_PROBE, 'IndexError', {'rich/text.py'}),
             ('fastapi_13920', FASTAPI_PROBE, '422', {'fastapi/dependencies/utils.py'})]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe(value):
    if dataclasses.is_dataclass(value):
        return safe(dataclasses.asdict(value))
    if hasattr(value, 'model_dump'):
        return safe(value.model_dump(exclude_none=True, mode='json'))
    if isinstance(value, dict):
        return {str(k): safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def save(path, value):
    path.write_text(json.dumps(safe(value), indent=2, ensure_ascii=False) + '\n')


@contextmanager
def no_connections():
    original, original_ex = socket.socket.connect, socket.socket.connect_ex
    def blocked(*args, **kwargs):
        raise RuntimeError('Network/model connection forbidden during CPU compilation')
    socket.socket.connect = socket.socket.connect_ex = blocked
    try:
        yield
    finally:
        socket.socket.connect, socket.socket.connect_ex = original, original_ex


def extract(path, destination):
    destination.mkdir()
    with zipfile.ZipFile(path) as archive:
        names = []
        for member in archive.infolist():
            name = PurePosixPath(member.filename)
            if name.is_absolute() or '..' in name.parts or '\\' in member.filename or stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError('Unsafe ZIP member: ' + member.filename)
            if not member.is_dir():
                names.append(member.filename)
        if len(names) != 10 or len(set(names)) != 10:
            raise ValueError('Expected exactly 10 distinct file members')
        archive.extractall(destination)
    return {name: digest((destination / name).read_bytes()) for name in names}


def source_patch_paths(patch):
    old = re.findall(r'^--- a/(.+)$', patch, re.M)
    new = re.findall(r'^\+\+\+ b/(.+)$', patch, re.M)
    if not old or old != new:
        raise ValueError('Reference patch must change existing source paths only')
    for name in new:
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or not name.endswith('.py') or any(
                part.lower().startswith(('test', 'repro')) for part in path.parts):
            raise ValueError('Non-source reference patch path: ' + name)
    return set(new)


async def main(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = dict(status='running', trusted=False, model_calls=0, assertions=[], scenarios=[], fixture_snapshots=[],
                  archive=str(args.archive.resolve()), expected_archive_sha256=args.expected_sha256,
                  budget_contract=BUDGET, container_cleanup='not_started',
                  interpretation='Actual native SDK/tool CPU proof only. No model following, solving-rate, or evaluation parity claim.')
    failure = None
    managers = []
    contexts = []

    def require(condition, name, details=None):
        report['assertions'].append(dict(name=name, passed=bool(condition), details=safe(details)))
        if not condition:
            raise AssertionError(name + ': ' + repr(details))

    try:
        (output / 'smoke_native_consumer.py').write_bytes(Path(__file__).read_bytes())
        report['archive_sha256'] = digest(args.archive.read_bytes())
        require(args.expected_sha256 == CANDIDATE_SHA and report['archive_sha256'] == CANDIDATE_SHA,
                'exact frozen candidate SHA256', report['archive_sha256'])
        require(re.fullmatch(r'sha256:[0-9a-f]{64}', args.image) is not None, 'immutable Docker image ID', args.image)
        report['versions'] = {name: importlib.metadata.version(name) for name in VERSIONS}
        require(report['versions'] == VERSIONS, 'exact actual SDK versions', report['versions'])
        from adk_submission import ModelRegistry, discover_adapters, compile_submission
        from adk_submission.discovery import discover_declared_models
        from google.adk.models.lite_llm import LiteLlm
        from google.adk.agents.invocation_context import InvocationContext
        from google.adk.models.llm_request import LlmRequest
        from google.adk.sessions import InMemorySessionService
        from google.adk.tools.agent_tool import AgentTool
        from google.adk.tools.base_tool import BaseTool
        from google.adk.tools.base_toolset import BaseToolset
        from google.adk.tools.function_tool import FunctionTool
        from google.adk.tools.tool_context import ToolContext
        from swegemma import EvalConfig
        from swegemma.context import SwegemmaContext
        from swegemma.deduplication import resolve_task_snapshot_paths
        from swegemma.harness.agent_runner import resolve_swegemma_adapter
        from swegemma.models import load_tasks
        from swegemma.sandbox import AdkSandboxCodeExecutor
        from swegemma.sandbox.docker import ContainerConfig, ContainerManager
        from swegemma.tools.execution import make_run_command

        sources_dir = output / 'sdk_sources'
        sources_dir.mkdir()
        for index, obj in enumerate([compile_submission, SwegemmaContext, resolve_task_snapshot_paths,
                                    resolve_swegemma_adapter, make_run_command, ContainerManager,
                                    FunctionTool, LiteLlm]):
            path = Path(inspect.getsourcefile(obj))
            name = f'{index:02d}-{path.name}'
            (sources_dir / name).write_bytes(path.read_bytes())
            report.setdefault('sdk_source_provenance', []).append(dict(original=str(path), artifact='sdk_sources/' + name,
                                                                      sha256=digest(path.read_bytes())))
        baseline_path = args.baseline_archive
        if baseline_path is None:
            choices = [Path(__file__).resolve().parent / 'baseline.zip',
                       Path(__file__).resolve().parents[2] / 'submission_build/source_only_20261008/submission.zip']
            baseline_path = next((p for p in choices if p.is_file()), choices[0])
        require(digest(baseline_path.read_bytes()) == BASELINE_SHA, 'exact frozen baseline SHA256')
        sources = {}
        members = {}
        for arm, archive in [('baseline', baseline_path), ('candidate', args.archive)]:
            (output / (arm + '.zip')).write_bytes(archive.read_bytes())
            sources[arm] = output / (arm + '_source')
            members[arm] = extract(archive, sources[arm])
        require(set(members['baseline']) == set(members['candidate']), 'identical member names')
        require([name for name in members['baseline'] if members['baseline'][name] != members['candidate'][name]] == ['prompts/system.md'],
                'prompt-only archive delta', members)
        report['archive_members'] = members
        tasks_path = args.data_root / 'tasks.jsonl'
        report['tasks_file_sha256'] = digest(tasks_path.read_bytes())
        tasks = {task.instance_id: task for task in load_tasks(tasks_path)}

        def registered(source):
            registry = ModelRegistry()
            adapters = discover_adapters(source)
            require(set(adapters.adapters) == {'main_lora', 'tool_lora'}, 'both actual adapters discovered')
            declared = [name.strip() for name in discover_declared_models(source)]
            require(declared == ['gemma-4-31b-it-qat-w4a16-ct'], 'actual base model declaration', declared)
            for name in declared:
                registry.register(name, LiteLlm(model='openai/' + name, api_base='http://127.0.0.1:8000/v1', api_key='EMPTY', num_retries=5))
            for name in adapters.adapters:
                model = LiteLlm(model='openai/' + name, api_base='http://127.0.0.1:8000/v1', api_key='EMPTY', num_retries=5)
                registry.register(name, model)
                registry.register('adapter:' + name, model)
            return registry, adapters

        async def contract(agent):
            sessions = InMemorySessionService()
            session = await sessions.create_session(app_name='consumer_smoke', user_id='cpu')
            records, root_tools, root_context = [], None, None
            seen = set()
            async def visit(node, root=False):
                nonlocal root_tools, root_context
                if id(node) in seen:
                    return
                seen.add(id(node))
                invocation = InvocationContext(invocation_id='consumer_' + session.id, agent=node,
                    session=session, session_service=sessions)
                tool_context = ToolContext(invocation)
                tools = []
                request = LlmRequest()
                for entry in node.tools:
                    require(not isinstance(entry, BaseToolset), 'native tools only; no SkillToolset/toolset')
                    tool = entry if isinstance(entry, BaseTool) else FunctionTool(entry)
                    tools.append(tool)
                    await tool.process_llm_request(tool_context=tool_context, llm_request=request)
                declarations = [safe(d) for t in (request.config.tools or []) for d in (t.function_declarations or [])]
                names = [t.name for t in tools]
                expected = ROOT_TOOLS if root else CHILD_TOOLS
                require(len(names) == len(expected) and set(names) == expected, 'actual native tool names', names)
                require({d['name'] for d in declarations} == expected, 'actual bound native declarations')
                model = node.model
                config = node.generate_content_config
                extra = model._additional_args.get('extra_body', {})
                require(isinstance(model, LiteLlm) and model.model == ('openai/main_lora' if root else 'openai/tool_lora'),
                        'actual native adapter binding', model.model)
                require(config.temperature == .2 and config.top_p == .95 and config.max_output_tokens == 16384
                        and config.model_dump(exclude_none=True).get('thinking_config') == {'thinking_budget': 4096, 'include_thoughts': True}
                        and extra.get('thinking_token_budget') == 4096
                        and extra.get('chat_template_kwargs', {}).get('enable_thinking') is True
                        and model.__dict__.get('_adk_include_thoughts') is True, 'unchanged actual sampling/thinking/history bridge')
                records.append(dict(agent=node.name, model=model.model, tools=names, declarations=declarations,
                                    generation=safe(config), extra_body=safe(extra)))
                require(not node.sub_agents, 'analyzer is native AgentTool, not transfer subagent')
                if root:
                    root_tools, root_context = {t.name: t for t in tools}, tool_context
                for tool in tools:
                    if isinstance(tool, AgentTool):
                        require(root and tool.name == 'code_analyzer_agent', 'only actual analyzer AgentTool')
                        await visit(tool.agent)
            await visit(agent, True)
            require(len(records) == 2, 'exact root and analyzer agent tree')
            return records, root_tools, root_context

        for task_id, probe, expected_before, allowed_paths in SCENARIOS:
            scenario = dict(task_id=task_id, phases=[], setup_and_observation=[])
            report['scenarios'].append(scenario)
            manager = None
            try:
                task = tasks[task_id]
                require(source_patch_paths(task.patch) == allowed_paths, task_id + ': trusted reference is source-only')
                task_record = dict(instance_id=task.instance_id, repo=task.repo, base_commit=task.base_commit, patch=task.patch)
                save(output / (task_id + '_reference.json'), task_record)
                (output / (task_id + '_reference.patch')).write_text(task.patch)
                scenario['reference_patch_sha256'] = digest(task.patch.encode())
                scenario['test_patch_used'] = False
                snapshot, base, restore_patch = resolve_task_snapshot_paths(args.data_root / 'snapshots', task_id, task.repo)
                scenario['snapshot'] = dict(path=str(snapshot), sha256=digest(snapshot.read_bytes()),
                    base_path=str(base) if base else None, restore_patch_sha256=digest(restore_patch.read_bytes()) if restore_patch else None)
                manager = ContainerManager(ContainerConfig(image=args.image, network_mode='none'))
                managers.append(manager)
                # Refuse missing images rather than allowing the manager to pull one.
                require(manager.client.images.get(args.image).id == args.image, task_id + ': immutable image already local')
                manager.initialize()
                container = manager.client.containers.get(manager._default_container_id)
                container.reload()
                scenario.update(container_id=container.id, image_id=container.attrs['Image'],
                                network_mode=container.attrs['HostConfig']['NetworkMode'])
                report['image_id'] = scenario['image_id']
                require(scenario['image_id'] == args.image and scenario['network_mode'] == 'none', task_id + ': offline immutable container')
                require(manager.extract_archive_to_container(manager._default_container_id, snapshot), task_id + ': fresh snapshot restored')

                def setup(command, label):
                    response = manager.run_command(command, timeout=90)
                    scenario['setup_and_observation'].append(dict(label=label, command=command, response=safe(response)))
                    require(response.exit_code == 0 and not response.timed_out, task_id + ': ' + label, response)
                    return response.stdout

                if restore_patch is not None:
                    manager.write_file('/tmp/consumer-snapshot.patch', restore_patch.read_bytes())
                    (output / (task_id + '_snapshot_restore.patch')).write_bytes(restore_patch.read_bytes())
                    setup('git apply /tmp/consumer-snapshot.patch', 'deduplicated snapshot restore patch')
                scenario['restored_head'] = setup('git rev-parse HEAD', 'restored snapshot HEAD observation').strip()
                scenario['restored_status'] = setup('git status --porcelain --untracked-files=all', 'restored snapshot status observation')
                # Deduplicated snapshot deltas may legitimately leave the base
                # archive's HEAD unchanged. Freeze the restored bytes as the
                # fixture baseline, as the native harness does; no source edit.
                setup('git add -A && git -c user.name=ConsumerSmoke -c user.email=consumer@example.invalid '
                      'commit --allow-empty -qm consumer-snapshot-baseline', 'freeze restored snapshot baseline')
                scenario['fixture_baseline_commit'] = setup('git rev-parse HEAD', 'fixture baseline HEAD').strip()
                require(not setup('git status --porcelain --untracked-files=all', 'clean fixture baseline').strip(),
                        task_id + ': no baseline repository modifications')
                report['fixture_snapshots'].append(dict(task_id=task_id, repo=task.repo,
                    task_base_commit=task.base_commit, restored=True, fresh_container=True,
                    container_id=container.id, image_id=scenario['image_id'], network_mode='none',
                    restored_head=scenario['restored_head'], fixture_baseline_commit=scenario['fixture_baseline_commit'],
                    **scenario['snapshot']))
                context = SwegemmaContext(docker_manager=manager, container_id=manager._default_container_id,
                    task=task, graph_dir=str(args.data_root / 'graphs'), embeddings_dir=str(args.data_root / 'embeddings'),
                    max_tool_calls=40, max_time_minutes=4, max_exec_seconds=90)
                contexts.append(context)
                context.start_agent_session()
                registry = context.create_tools()
                executor = AdkSandboxCodeExecutor(sandbox=context.sandbox, timeout_seconds=90,
                    start_time=context.task_start_time, max_time_minutes=4, budget_check_fn=context.check_budget)
                compiled = {}
                for arm in ['baseline', 'candidate']:
                    with no_connections():
                        models, adapters = registered(sources[arm])
                        config = EvalConfig(tasks_path=tasks_path, snapshots_dir=args.data_root / 'snapshots',
                            wheels_dir=args.data_root / 'wheels', graph_dir=str(args.data_root / 'graphs'),
                            embeddings_dir=str(args.data_root / 'embeddings'), submission_dir=sources[arm],
                            results_dir=output / (task_id + '_' + arm + '_compile'), models=models, adapter_manifest=adapters,
                            image=args.image, sandbox='docker', task_ids=[task_id], concurrency=1, display_mode='quiet', **BUDGET)
                        agent = compile_submission(submission_dir=sources[arm], tool_registry=registry,
                            model_registry=models, code_executor=executor, script_timeout=90, limits=config.limits,
                            generation_constraints=config.generation_constraints, adapter_manifest=adapters,
                            adapter_resolver_fn=lambda base_model, info: resolve_swegemma_adapter(base_model, info, models))
                        records, tools, tool_context = await contract(agent)
                    compiled[arm] = records
                    if arm == 'candidate':
                        run_tool, candidate_context = tools['run_command'], tool_context
                require(compiled['candidate'] == compiled['baseline'], task_id + ': exact baseline native tools/analyzer/model contract')
                scenario['compiled_contracts'] = compiled
                command = "cd /workspace && PYTHONDONTWRITEBYTECODE=1 python3 - <<'CONSUMER_PROBE'\n" + probe + '\nCONSUMER_PROBE'
                (output / (task_id + '_probe.py')).write_text(probe)
                (output / (task_id + '_command.txt')).write_text(command)
                scenario['command_sha256'] = digest(command.encode())
                for phase in ['unpatched', 'reference']:
                    if phase == 'reference':
                        manager.write_file('/tmp/consumer-reference.patch', task.patch)
                        setup('git apply --check /tmp/consumer-reference.patch && git apply /tmp/consumer-reference.patch',
                              'trusted task.patch reference setup; never test_patch')
                    calls_before = context.tool_calls
                    envelope = await run_tool.run_async(args={'command': command}, tool_context=candidate_context)
                    phase_record = dict(phase=phase, command=command, envelope=safe(envelope),
                                        tool_calls_before=calls_before, tool_calls_after=context.tool_calls)
                    scenario['phases'].append(phase_record)
                    require(context.tool_calls == calls_before + 1, task_id + ': ' + phase + ' actual native tool budget charged')
                    payload = envelope.get('details', envelope)
                    stdout, stderr = payload.get('stdout', ''), payload.get('stderr', '')
                    exit_code = payload.get('exit_code')
                    phase_record.update(exit_code=exit_code, stdout=stdout, stderr=stderr)
                    guards = [json.loads(line[len('IMPORT_GUARD '):]) for line in stdout.splitlines() if line.startswith('IMPORT_GUARD ')]
                    require(len(guards) == (3 if task_id == 'rich_3471' else 4)
                            and all(g['origin'].startswith('/workspace/') for g in guards), task_id + ': ' + phase + ' actual workspace import guards', guards)
                    if phase == 'unpatched':
                        require(exit_code != 0 and expected_before in stdout + stderr,
                                task_id + ': actual exposed unpatched consumer failure', phase_record)
                        if task_id == 'fastapi_13920':
                            observed = [json.loads(line[len('CONSUMER_RESULT '):]) for line in stdout.splitlines() if line.startswith('CONSUMER_RESULT ')]
                            require(len(observed) == 1 and observed[0]['status_code'] == 422,
                                    task_id + ': unpatched actual HTTP 422', observed)
                    else:
                        require(exit_code == 0 and 'CONSUMER_RESULT ' in stdout, task_id + ': actual reference consumer pass', phase_record)
                    diff = setup('git diff --no-ext-diff --binary HEAD', phase + ' source diff observation')
                    untracked = setup('git ls-files --others --exclude-standard', phase + ' untracked observation')
                    require(not untracked.strip(), task_id + ': ' + phase + ' no repository probe/test/untracked files', untracked)
                    require((not diff if phase == 'unpatched' else source_patch_paths(diff) == allowed_paths),
                            task_id + ': ' + phase + ' source-only repository delta', diff)
                    (output / (task_id + '_' + phase + '.diff')).write_text(diff)
                    for relative in sorted(allowed_paths):
                        stream, _ = container.get_archive('/workspace/' + relative)
                        with tarfile.open(fileobj=io.BytesIO(b''.join(stream)), mode='r:*') as archive:
                            files = [member for member in archive.getmembers() if member.isfile()]
                            require(len(files) == 1, task_id + ': exact source observation archive')
                            data = archive.extractfile(files[0]).read()
                        artifact = f'{task_id}_{phase}_{relative.replace("/", "_")}'
                        (output / artifact).write_bytes(data)
                        phase_record.setdefault('source_observations', []).append(
                            dict(path=relative, artifact=artifact, sha256=digest(data), bytes=len(data)))
                require(context.llm_calls_used == 0, task_id + ': no model calls')
                scenario['status'] = 'passed'
            except Exception as error:
                scenario.update(status='failed', error=repr(error), traceback=traceback.format_exc())
                failure = error
            finally:
                if manager is not None:
                    try:
                        manager.cleanup_all()
                        scenario['container_cleanup'] = 'completed'
                    except Exception as error:
                        scenario['container_cleanup'] = dict(error=repr(error))
                        scenario['status'] = 'failed'
                        failure = error
        require(len(report['scenarios']) == 2 and all(s.get('status') == 'passed' for s in report['scenarios']),
                'both actual before/after consumer scenarios passed')
        report.update(status='passed', trusted=True)
    except Exception as error:
        failure = error
        report.update(status='failed', trusted=False, error=repr(error), traceback=traceback.format_exc())
    finally:
        report['model_calls'] = sum(context.llm_calls_used for context in contexts)
        report['budget_tool_calls'] = sum(context.tool_calls for context in contexts)
        cleanup_complete = len(report['scenarios']) == 2 and all(s.get('container_cleanup') == 'completed' for s in report['scenarios'])
        report['container_cleanup'] = 'completed' if cleanup_complete else 'incomplete_or_not_started'
        if report['model_calls'] != 0 or (managers and not cleanup_complete):
            report.update(status='failed', trusted=False)
        report['artifacts'] = [{'path': str(path.relative_to(output)), 'sha256': digest(path.read_bytes()), 'bytes': path.stat().st_size}
                               for path in sorted(output.rglob('*')) if path.is_file()]
        save(output / 'SDK_smoke.json', report)
        print(json.dumps(dict(status=report['status'], trusted=report['trusted'], output=str(output))), flush=True)
    if failure is not None or report['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline-archive', type=Path)
    asyncio.run(main(parser.parse_args()))
