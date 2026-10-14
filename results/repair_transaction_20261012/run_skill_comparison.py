#!/usr/bin/env python3
"""Evaluate the isolated skill against a hash-verified baseline from this GPU run."""
import argparse
import asyncio
import dataclasses
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import time
import traceback
import zipfile

os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
os.environ['PYTHONNOUSERSITE'] = '1'
import run_comparison as harness

SKILL_HASH = 'b8ee7279894c8c97481ddceae8ed019f204c756bf2e107918116ba9275130cd2'
ADDED = ['skills/repair-transaction/SKILL.md', 'skills/repair-transaction/scripts/repair.py']
CHANGED = ['agent.yaml', 'prompts/system.md']


def _summarize(ids, development, diagnostics, results, status, trusted):
    summary = harness.summarize(ids, development, diagnostics, results, status, trusted)
    summary['interpretation'] = ('Previously exposed development cases. One later skill sample per task '
        'against the hash-verified baseline from the same backend run; baseline inference is reused, '
        'not a fresh paired replicate. Temporal/order effects remain. No held-out or promotion claim.')
    return summary


async def main(args):
    output = args.output.resolve()
    assert output.is_relative_to(harness.ROOT) and output != harness.ROOT
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    metadata = {'status': 'initializing', 'started_utc': harness.utc(),
        'design': 'Previously exposed development cohort; skill only, baseline sampling unchanged. Candidate arm runs later on the same backend; baseline inference is reused, not repeated.',
        'arguments': vars(args), 'runner_sha256': harness.sha256(Path(__file__)),
        'shared_runner_sha256': harness.sha256(Path(harness.__file__)),
        'candidate_sha256': SKILL_HASH}
    results = {'baseline': {}, 'candidate': {}}
    evaluators = []
    ids = []
    trusted = False
    status = 'failed'
    handler = logging.FileHandler(output / 'runner.log')
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    try:
        remaining = (datetime.fromisoformat(args.gpu_deadline) - datetime.now(timezone.utc)).total_seconds()
        if remaining < 70 * 60:
            status = 'not_started_insufficient_window'
            metadata['remaining_seconds_before_start'] = remaining
            return
        plan = json.loads(args.plan.read_text())
        ids, development, diagnostics = harness.validate_plan(plan)
        assert not diagnostics and len(ids) == 12
        prior = args.baseline_evaluation.resolve()
        assert prior.is_relative_to(harness.ROOT)
        previous = json.loads((prior / 'metadata.json').read_text())
        assert previous['status'] == 'complete' and previous['controls_trusted']
        assert previous['archive_sha256'] == harness.EXPECTED_HASHES
        assert previous['task_ids'] == ids and previous['budget'] == harness.BUDGET
        assert previous['versions'] == harness.EXPECTED_VERSIONS
        for item in previous['artifact_manifest']:
            harness.checked_artifact(prior, item)
        for task_id in ids:
            row_path = prior / 'baseline/records' / (harness.safe_id(task_id) + '.json')
            row = json.loads(row_path.read_text())
            assert row['instance_id'] == task_id
            results['baseline'][task_id] = row
            harness.save(output / 'reused_baseline_records' / row_path.name, row)
        metadata['baseline_reuse'] = {'source': str(prior),
            'metadata_sha256': harness.sha256(prior / 'metadata.json'),
            'verified_artifact_count': len(previous['artifact_manifest']),
            'model_calls_in_this_arm': 0, 'fresh_baseline_replicate': False}
        assert {name: harness.importlib.metadata.version(name) for name in harness.EXPECTED_VERSIONS} == harness.EXPECTED_VERSIONS
        wheels = harness.validate_wheels(plan, args)
        harness.load_sdk()
        assert harness.sha256(args.archive) == SKILL_HASH
        baseline_zip = prior / 'sources/baseline'
        with zipfile.ZipFile(args.archive) as archive:
            names = archive.namelist()
            assert len(names) == len(set(names))
            bodies = {name: archive.read(name) for name in names if not name.endswith('/')}
            original = {item.relative_to(baseline_zip).as_posix(): item.read_bytes()
                        for item in baseline_zip.rglob('*') if item.is_file()}
            assert sorted(set(bodies) - set(original)) == ADDED
            assert not (set(original) - set(bodies))
            assert sorted(name for name in original if original[name] != bodies[name]) == CHANGED
            source = output / 'source'
            archive.extractall(source)
        models, adapters = harness.registered_models(source, args.api_base)
        images, image_ids = harness.inspect_images(plan, ids, None)
        data = args.data_root.resolve()
        assert harness.sha256(data / 'tasks.jsonl') == plan['task_file_sha256']
        empty_models = harness.ModelRegistry()
        hydration = harness.Evaluator(harness.config_for(data, baseline_zip, output / 'hydration',
            image_ids[ids[0]], empty_models, None, ids))
        evaluators.append(hydration)
        tasks = {task.instance_id: task for task in harness.load_tasks(data / 'tasks.jsonl')
                 if task.instance_id in ids}
        tasks = {task_id: hydration._hydrate_task_from_secret(tasks[task_id]) for task_id in ids}
        snapshots = {}
        for task_id in ids:
            paths = harness.resolve_task_snapshot_paths(data / 'snapshots', task_id, tasks[task_id].repo)
            snapshots[task_id] = [{'sha256': harness.sha256(path), 'bytes': path.stat().st_size}
                                  if path else None for path in paths]
        contract = harness.selection_contract(plan, ids, tasks, snapshots, image_ids, wheels)
        assert contract == previous['selection_contract']
        controls = harness.verify_controls(args, plan, contract, tasks)
        server = harness.validate_server(args, plan, output)
        assert server['server_info'] == previous['server_runtime']['server_info']
        assert server['reasoning_proof_sha256'] == previous['server_runtime']['reasoning_proof_sha256']
        trusted = True
        metadata.update(status='evaluating', control_origin_contract=contract,
            control_origin_archive_hashes=harness.EXPECTED_HASHES, controls_verified=len(controls),
            controls_manifest_sha256=args.controls_manifest_sha256, server_runtime=server,
            candidate_sampling=harness.SAMPLING, image_ids=image_ids,
            runtime_wheels=wheels, added_members=ADDED, changed_members=CHANGED)
        harness.save(output / 'metadata.json', metadata)
        running = []
        for index, task_id in enumerate(ids, 1):
            directory = output / 'candidate'
            config = harness.config_for(data, source, directory, image_ids[task_id], models, adapters, ids)
            metadata.setdefault('runtime_configs', {})[task_id] = {
                field.name: harness.json_safe(getattr(config, field.name)) for field in dataclasses.fields(config)}
            harness.save(output / 'metadata.json', metadata)
            evaluator = harness.make_evaluator(config, directory / 'evidence' / task_id)
            evaluators.append(evaluator)
            print(f'START skill {task_id}', flush=True)
            try:
                result = await evaluator.evaluate_task(tasks[task_id], task_index=index, total_tasks=len(ids))
                raw_resolved = result.resolved
                errors = []
                origins = []
                if not result.agent_patch.strip():
                    errors.append('No emitted agent patch; cannot resolve')
                try:
                    origins = harness.provenance(result.test_output, tasks[task_id].repo)
                except Exception as error:
                    errors.append(str(error))
                if result.resolved:
                    okay, reason = harness.junit_check(evaluator.docker.last_junit, tasks[task_id], 'reference')
                    if not okay:
                        errors.append(reason)
                if errors:
                    result.resolved = False
                    result.error = '\n'.join(filter(None, [result.error, *errors]))
                row = harness.persist(result, directory, running, {
                    'raw_harness_resolved': raw_resolved, 'agent_error': evaluator.last_agent_error,
                    'agent_completed_without_error': not bool(evaluator.last_agent_error),
                    'import_provenance': origins, 'image_id': image_ids[task_id]})
            finally:
                evaluator.docker.cleanup_all()
            results['candidate'][task_id] = row
            harness.save(output / 'comparison_summary.json',
                         _summarize(ids, development, diagnostics, results, 'running', trusted))
            print(f"COMPLETE skill {task_id}: resolved={row['resolved']} error={row['error']}", flush=True)
        status = 'complete'
    except BaseException:
        metadata['error'] = traceback.format_exc()
        raise
    finally:
        for evaluator in evaluators:
            evaluator.docker.cleanup_all()
        metadata.update(status=status, finished_utc=harness.utc(),
                        duration_seconds=time.perf_counter() - started, controls_trusted=trusted)
        harness.save(output / 'comparison_summary.json',
            _summarize(ids, ids, [], results, status, trusted))
        metadata['artifact_manifest'] = [harness.artifact(path, output)
            for path in sorted(output.rglob('*')) if path.is_file() and path.name not in {'metadata.json', 'runner.log'}]
        harness.save(output / 'metadata.json', metadata)
        logging.getLogger().removeHandler(handler)
        handler.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--baseline-evaluation', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--gpu-deadline', required=True, help='Observed capped instance stop deadline, ISO8601 UTC')
    parser.add_argument('--runtime-wheels', type=Path, required=True)
    parser.add_argument('--controls-manifest', type=Path, required=True)
    parser.add_argument('--controls-manifest-sha256', required=True)
    parser.add_argument('--reasoning-proof', type=Path, required=True)
    parser.add_argument('--reasoning-proof-sha256', required=True)
    parser.add_argument('--api-base', default='http://127.0.0.1:8000/v1')
    asyncio.run(main(parser.parse_args()))
