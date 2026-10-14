#!/usr/bin/env python3
"""Execute fresh CPU preparation and all admission checks on the parent-created clone.

Required CLI: --work-root NEW_ROOT --run-name revision_bound_edit_20261013
--data-root ORIGINAL_ROOT/competition_data --model-root ORIGINAL_ROOT/model
--reference-root FRESH_REFERENCE --helper-root NEW_ROOT/results/repair_transaction_20261012
--sandbox-profile framework --allow-index-resolution. --python-executable defaults
to /usr/bin/python3.12; the installed native environment is NEW_ROOT/.venv-current.

Required packet in NEW_ROOT/results/revision_bound_edit_20261013: this script,
prepare_cpu_environment.py, run_comparison.py, smoke_native_revision.py,
evaluation_plan.json, baseline.zip, candidate.zip, and wheelhouse containing all
41 official wheels plus downloaded_wheels.json. The helper root must contain
freeze_base_wheels.py, Dockerfile.provenance, container_provenance.py,
regenerate_httpbin_certificates.py, tls_fixture_manifest.py, run_comparison.py,
and native_smoke_reproduction_sources.zip. The preserved historical harness is
self-contained; no history_off_screen_20261009 dependency is required.
Fresh references must contain docker/Dockerfile.public, docker/Dockerfile.sandbox,
docker/imp.py, docker/telnetlib.py, HARNESS_README.md, sandbox/setup.py, tasks.jsonl.

No previous CPU result is accepted. This driver creates a new .venv-current,
freezes dependencies explicitly, builds native framework fixtures, compiles both
exact ZIPs, executes all 24 trusted controls, and performs the actual native
revision-edit smoke against restored rich_3454 and the exact candidate ZIP.
It never provisions resources, allocates a GPU, starts serving, requests a model,
uploads a submission, or writes to original data/model/venvs. Completion is CPU
admission evidence only, not authorization for GPU/model measurement.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

from prepare_cpu_environment import SDK_HASHES, file_record, protected_origins, sha256

RUN_NAME = 'revision_bound_edit_20261013'
HASHES = {
    'baseline': '75387e03e97b50b3816ba683e88cdce71a9762023e65a5ba79f8b192c6c03142',
    'candidate': '8f69efd70fbdffa8924f10d60a1117fd0f98cb838bc137b7b172af79bd3f440b',
}
IDS = ['fastapi_13920', 'rich_4075', 'fastapi_14356', 'rich_3471',
       'fastapi_14301', 'rich_3894', 'fastapi_9425', 'rich_3518',
       'fastapi_14485', 'rich_3506', 'fastapi_13713', 'rich_3454']
VERSIONS = {'swegemma': '0.2.11', 'adk-submission': '0.2.13', 'adk-eval-core': '0.1.0'}
BUDGET = {'timeout_seconds': 90, 'max_tool_calls': 40, 'max_time_minutes': 4, 'max_turns': 100}
HELPERS = ['freeze_base_wheels.py', 'Dockerfile.provenance', 'container_provenance.py',
           'regenerate_httpbin_certificates.py', 'tls_fixture_manifest.py',
           'run_comparison.py', 'native_smoke_reproduction_sources.zip']
REFERENCES = ['docker/Dockerfile.public', 'docker/Dockerfile.sandbox', 'docker/imp.py',
              'docker/telnetlib.py', 'HARNESS_README.md', 'sandbox/setup.py', 'tasks.jsonl']


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def load(path):
    return json.loads(path.read_text())


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--work-root', type=Path, required=True)
    parser.add_argument('--run-name', required=True, help='Experiment folder, not VM prefix')
    parser.add_argument('--protected-root', type=Path, default=Path('/home/davidproctor/competition'))
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--model-root', type=Path, required=True)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--helper-root', type=Path, required=True)
    parser.add_argument('--sandbox-profile', choices=['framework'], required=True)
    parser.add_argument('--python-executable', default='/usr/bin/python3.12')
    parser.add_argument('--allow-index-resolution', action='store_true')
    parser.add_argument('--resume-native-smoke', action='store_true',
                        help='Resume this same fresh admission after a smoke-driver-only failure; preserve failed evidence')
    parser.add_argument('--recovery-attempt', type=int, default=1)
    parser.add_argument('--revalidate-candidate', action='store_true')
    args = parser.parse_args()
    require(args.run_name == RUN_NAME, '--run-name must be revision_bound_edit_20261013, not a VM prefix')
    require(args.allow_index_resolution, 'Explicit --allow-index-resolution is required for a fresh freeze')
    root = args.work_root.resolve(strict=True)
    protected = args.protected_root.resolve(strict=True)
    run = (root / 'results' / args.run_name).resolve(strict=True)
    require(root != protected and not root.is_relative_to(protected), 'New work-root must be outside original clone root')
    require(run.is_relative_to(root) and Path(__file__).resolve().parent == run,
            'Execute the packet staged in the exact new work-root/run folder')
    require(args.data_root.resolve(strict=True).is_relative_to(protected)
            and args.model_root.resolve(strict=True).is_relative_to(protected),
            'Data and model weights must remain read-only inputs from the original clone')
    if not args.resume_native_smoke:
        require(not (root / '.venv-current').exists() and not (root / '.venv-current').is_symlink(),
                'Refusing existing .venv-current; this driver does not reuse CPU environments')
    require(args.helper_root.resolve(strict=True) == (root / 'results/repair_transaction_20261012').resolve(strict=True),
            'Preserved smoke dependencies must be staged in the new root at their historical relative location')
    required = [run / name for name in ['prepare_cpu_environment.py', 'run_comparison.py',
                'smoke_native_revision.py', 'evaluation_plan.json', 'baseline.zip', 'candidate.zip',
                'wheelhouse/downloaded_wheels.json']]
    required += [args.helper_root / name for name in HELPERS]
    required += [args.reference_root / name for name in REFERENCES]
    for path in required:
        require(path.is_file() and path.stat().st_size > 0, f'Missing required packet/reference file: {path}')
    recovery = None
    if args.resume_native_smoke:
        recovery = load(run / 'cpu_driver_progress.json')
        require(recovery['status'] == 'failed' and recovery['protected_origin_evidence_unchanged']
                and recovery['stages']['native_revision_smoke']['returncode'] == 1
                and all(recovery['stages'][stage]['returncode'] == 0 for stage in
                        ['inventory', 'freeze', 'prepare', 'linux_compiler_preflight', 'cpu_controls']),
                'Recovery requires this admission to have failed only in the native smoke driver')
        require(load(run / 'cpu_driver_protected_origins_before.json')
                == load(run / 'cpu_driver_protected_origins_after.json') == protected_origins(protected),
                'Protected origins changed since failed smoke admission')
        recovery_prefix = f'cpu_driver_recovery_{args.recovery_attempt}'
        names = [f'{recovery_prefix}_progress.json', f'{recovery_prefix}.log',
                 'cpu_driver_evidence.json', f'{recovery_prefix}_protected_origins_before.json',
                 f'{recovery_prefix}_protected_origins_after.json', f'native_smoke_recovery_{args.recovery_attempt}']
        if args.revalidate_candidate:
            names += [f'linux_preflight_recovery_{args.recovery_attempt}', f'cpu_controls_recovery_{args.recovery_attempt}']
    else:
        names = ['cpu_driver_progress.json', 'cpu_driver.log', 'cpu_driver_evidence.json',
                 'cpu_driver_protected_origins_before.json', 'cpu_driver_protected_origins_after.json',
                 'linux_preflight', 'cpu_controls', 'native_smoke', 'cpu_setup']
    for name in names:
        require(not (run / name).exists() and not (run / name).is_symlink(),
                f'Refusing existing CPU evidence or outputs: {run / name}')
    archives = {arm: run / f'{arm}.zip' for arm in HASHES}
    for arm, path in archives.items():
        require(sha256(path) == HASHES[arm], f'{arm} archive differs from frozen exact ZIP')
    plan_path = run / 'evaluation_plan.json'
    plan = load(plan_path)
    require(plan.get('task_ids') == IDS and plan.get('tasks_per_configuration') == 12,
            'Exactly the original ordered 12 development IDs are required; no substitutions')
    require(plan.get('archive_sha256') == HASHES and plan.get('expected_versions') == VERSIONS
            and plan.get('budgets') == BUDGET, 'Plan archive/SDK/budget contract mismatch')
    official = (run / 'wheelhouse').resolve(strict=True)
    require(official.is_relative_to(run), 'Runtime wheelhouse must be inside this new run folder')
    supplied = load(official / 'downloaded_wheels.json')['wheels']
    supplied_by_name = {row['name']: row for row in supplied}
    require(len(supplied) == 41 and len(supplied_by_name) == 41, 'Expected 41 distinct official downloaded wheels')
    for name, digest in SDK_HASHES.items():
        path = (official / name).resolve(strict=True)
        origin = supplied_by_name.get(name)
        require(path.parent == official and origin and origin['sha256'] == digest
                and sha256(path) == digest and path.stat().st_size == origin['bytes'],
                f'Current SDK wheel differs from official downloaded provenance: {name}')
    runtime = plan.get('runtime_wheels', [])
    require(len(runtime) == 3 and {Path(row['path']).name for row in runtime} == set(SDK_HASHES),
            'Plan must bind exactly all three official SDK runtime wheels')
    for row in runtime:
        name = Path(row['path']).name
        require(row['sha256'] == SDK_HASHES[name], f'Plan runtime wheel SHA mismatch: {name}')
        row['path'] = str(official / name)
    prefix = recovery_prefix if recovery else 'cpu_driver'
    progress_path = run / f'{prefix}_progress.json'
    driver_log = run / f'{prefix}.log'
    smoke_directory = run / (f'native_smoke_recovery_{args.recovery_attempt}' if recovery else 'native_smoke')
    preflight_directory = run / (f'linux_preflight_recovery_{args.recovery_attempt}' if args.revalidate_candidate else 'linux_preflight')
    controls_directory = run / (f'cpu_controls_recovery_{args.recovery_attempt}' if args.revalidate_candidate else 'cpu_controls')
    progress = {'status': 'starting', 'run_name': args.run_name, 'gpu_allocated_by_driver': False,
                'gpu_authorized': False, 'model_requests': 0, 'sandbox_profile': args.sandbox_profile,
                'stages': {}, 'development_task_ids': IDS}
    if recovery:
        progress['stages'] = {name: row for name, row in recovery['stages'].items()
                              if name != 'native_revision_smoke'}
        progress['recovery_of'] = file_record(run / 'cpu_driver_progress.json')
        progress['recovery_reason'] = 'Native tool normalization and symlink-safe locate; exact candidate revalidated when requested'
    env = {**os.environ, 'LITELLM_LOCAL_MODEL_COST_MAP': 'True', 'PYTHONNOUSERSITE': '1',
           'CUDA_VISIBLE_DEVICES': '', 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1'}
    env.pop('PYTHONPATH', None)
    env.pop('VIRTUAL_ENV', None)
    before = protected_origins(protected)
    save(run / f'{prefix}_protected_origins_before.json', before)

    def execute(name, command, expect_output=False):
        progress['status'] = name
        save(progress_path, progress)
        outputs = []
        with driver_log.open('a') as log:
            log.write('\nCOMMAND ' + repr([str(x) for x in command]) + '\n')
            with subprocess.Popen([str(x) for x in command], cwd=root, env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, bufsize=1) as process:
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    print(line, end='', flush=True)
                    if line.startswith('CPU_PREPARATION_OUTPUT '):
                        outputs.append(line.removeprefix('CPU_PREPARATION_OUTPUT ').strip())
                code = process.wait()
        progress['stages'][name] = {'returncode': code}
        save(progress_path, progress)
        require(code == 0, f'{name} exited {code}; GPU/model admission prohibited')
        if expect_output:
            require(len(outputs) == 1, f'{name} lacks unique preparation output')
            output = Path(outputs[0]).resolve(strict=True)
            require(output.is_relative_to(run / 'cpu_setup'), 'Preparation output escaped this new run')
            status = load(output / 'status.json')
            require(status['status'] in ['recorded', 'prepared'] and status['protected_origin_evidence_unchanged'],
                    'Preparation output failed original-data/venv protection')
            progress['stages'][name]['output'] = str(output)
            return output

    try:
        base = [args.python_executable, run / 'prepare_cpu_environment.py']
        shared = ['--work-root', root, '--run-name', args.run_name, '--protected-root', protected,
                  '--data-root', args.data_root, '--model-root', args.model_root,
                  '--python-executable', args.python_executable, '--sandbox-profile', args.sandbox_profile]
        if recovery:
            prepared = Path(recovery['stages']['prepare']['output']).resolve(strict=True)
            require(prepared.is_relative_to(run / 'cpu_setup'), 'Recovered setup escaped this fresh run')
            require(load(prepared / 'status.json')['protected_origin_evidence_unchanged'],
                    'Recovered prepared environment lacks origin protection')
        else:
            execute('inventory', base + ['inventory'] + shared, True)
            frozen = execute('freeze', base + ['freeze'] + shared + [
                '--wheelhouse', official, '--allow-index-resolution', '--pygments-version', '2.13.0'], True)
            prepared = execute('prepare', base + ['prepare'] + shared + [
                '--reference-root', args.reference_root, '--helper-root', args.helper_root,
                '--frozen-stack', frozen / 'frozen_stack.json', '--sudo-docker'], True)
        environment = load(prepared / 'cpu_environment.json')
        python = root / '.venv-current/bin/python'
        require(environment['python'] == str(python) and environment['run_name'] == args.run_name
                and environment['sandbox_profile'] == 'framework'
                and environment['model_root'] == str(args.model_root.resolve()), 'Prepared environment contract mismatch')
        image = environment['images']['2.13.0']
        plan['image_map'] = {task: image['image_id'] for task in IDS}
        plan['image_ids'] = plan['image_map'].copy()
        save(plan_path, plan)
        common = ['--plan', plan_path, '--baseline', archives['baseline'], '--candidate', archives['candidate'],
                  '--data-root', environment['data_root'], '--runtime-wheels', official]
        if not recovery or args.revalidate_candidate:
            execute('linux_compiler_preflight', [python, run / 'run_comparison.py', '--preflight-only'] + common + [
                '--output', preflight_directory])
        preflight = load(preflight_directory / 'metadata.json')
        require(preflight['status'] == 'preflight_complete' and preflight['versions'] == VERSIONS
                and not preflight.get('cleanup_errors'), 'SDK compiler preflight did not complete cleanly')
        if not recovery or args.revalidate_candidate:
            execute('cpu_controls', [python, run / 'run_comparison.py', '--cpu-controls-only'] + common + [
                '--output', controls_directory])
        manifest_path = controls_directory / 'controls_manifest.json'
        manifest = load(manifest_path)
        metadata = load(controls_directory / 'metadata.json')
        rows = manifest['controls']
        require(manifest['status'] == 'trusted' and manifest['expected_control_count'] == 24
                and manifest['completed_control_count'] == 24 and len(rows) == 24
                and metadata['status'] == 'controls_complete' and metadata['controls_trusted']
                and metadata['versions'] == VERSIONS and not metadata.get('cleanup_errors'),
                'All 24 controls must finish trusted with exact SDK versions and clean native cleanup')
        require({(row['instance_id'], row['kind']) for row in rows}
                == {(task, kind) for task in IDS for kind in ['unpatched', 'reference']},
                'Controls omitted, duplicated, or substituted a frozen task/kind')
        require(load(controls_directory / 'controls_summary.json') == rows, 'Control summary differs from trusted manifest')
        require(manifest['selection_contract']['task_ids'] == IDS
                and manifest['selection_contract']['image_ids'] == plan['image_map']
                and manifest['selection_contract']['archive_sha256'] == HASHES, 'Control selection/image/archive identity mismatch')
        checked = {}
        for artifact in manifest['artifacts']:
            path = (manifest_path.parent / artifact['path']).resolve(strict=True)
            require(path.is_relative_to(manifest_path.parent) and sha256(path) == artifact['sha256']
                    and path.stat().st_size == artifact['bytes'], 'Control artifact provenance mismatch')
            checked[artifact['path']] = path
        for row in rows:
            task, kind = row['instance_id'], row['kind']
            require(row['trusted'] and not row['trust_error'] and not row['error']
                    and row['resolved'] == (kind == 'reference')
                    and row['test_exit_code'] == (0 if kind == 'reference' else 1)
                    and row['image_id'] == image['image_id'], f'Untrusted/mismatched control: {task}/{kind}')
            record = f'controls/{kind}/records/{task}.json'
            require({record, f'controls/{kind}/test_outputs/{task}.log',
                     f'controls/{kind}/patches/{task}.patch', f'controls/{kind}/evidence/{task}/junit.xml'}.issubset(checked)
                    and load(checked[record]) == row, f'Missing actual control record/output/patch/JUnit: {task}/{kind}')
        execute('native_revision_smoke', [python, run / 'smoke_native_revision.py', '--archive', archives['candidate'],
            '--expected-sha256', HASHES['candidate'], '--data-root', environment['data_root'],
            '--image', image['image_id'], '--output', smoke_directory])
        smoke_path = smoke_directory / 'SDK_smoke.json'
        smoke = load(smoke_path)
        require(smoke['status'] == 'passed' and smoke['trusted'] and smoke['archive_sha256'] == HASHES['candidate']
                and smoke['versions'] == VERSIONS and smoke['model_calls'] == 0
                and smoke['image_id'] == image['image_id'] and smoke['fixture_snapshot']['task_id'] == 'rich_3454'
                and smoke['container_cleanup'] == 'completed' and smoke['assertions']
                and all(row['passed'] for row in smoke['assertions'])
                and any(row['name'] == 'real rich snapshot restored' and row['passed'] for row in smoke['assertions']),
                'Exact-candidate native SDK smoke/restored rich_3454 fixture did not pass trusted')
        require(sha256(archives['candidate']) == HASHES['candidate'] and sha256(archives['baseline']) == HASHES['baseline'],
                'An archive changed during CPU checks')
        evidence = {
            'status': 'cpu_admission_complete', 'run_name': args.run_name, 'development_task_ids': IDS,
            'controls_manifest': file_record(manifest_path), 'native_smoke': file_record(smoke_path),
            'environment': file_record(prepared / 'cpu_environment.json'), 'plan': file_record(plan_path),
            'archives': {arm: file_record(path) for arm, path in archives.items()},
            'gpu_authorized': False, 'model_requests': 0, 'no_upload': True}
        progress['status'] = 'complete'
    except BaseException as error:
        progress['status'] = 'failed'
        progress['error'] = repr(error)
        raise
    finally:
        after = protected_origins(protected)
        save(run / f'{prefix}_protected_origins_after.json', after)
        progress['protected_origin_evidence_unchanged'] = before == after
        if before != after:
            progress['status'] = 'rejected_origin_change'
        elif progress['status'] == 'complete':
            save(run / 'cpu_driver_evidence.json', evidence)
        save(progress_path, progress)
        require(before == after, 'Original retained data/setup/venv evidence changed; CPU admission rejected')


if __name__ == '__main__':
    main()
