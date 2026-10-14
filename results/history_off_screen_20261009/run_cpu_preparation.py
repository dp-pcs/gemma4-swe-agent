import argparse
import json
import os
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--work-root', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--reference-root', type=Path, required=True)
    args = parser.parse_args()
    root = args.work_root.absolute()
    run = root / 'results/history_off_screen_20261009'
    driver_log = run / 'cpu_driver.log'
    progress = {'status': 'starting', 'gpu_allocated_by_driver': False, 'model_requests': 0, 'stages': {}}
    env = {**os.environ, 'LITELLM_LOCAL_MODEL_COST_MAP': 'True', 'PYTHONNOUSERSITE': '1'}
    env.pop('PYTHONPATH', None)

    def execute(name, command, expect_output=False):
        progress['status'] = name
        (run / 'cpu_driver_progress.json').write_text(json.dumps(progress, indent=2) + '\n')
        lines = []
        with driver_log.open('a') as log:
            log.write('\nCOMMAND ' + repr(command) + '\n')
            with subprocess.Popen([str(x) for x in command], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1) as process:
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    print(line, end='', flush=True)
                    lines.append(line)
                code = process.wait()
        progress['stages'][name] = {'returncode': code}
        if expect_output:
            outputs = [line.removeprefix('CPU_PREPARATION_OUTPUT ').strip() for line in lines if line.startswith('CPU_PREPARATION_OUTPUT ')]
            if len(outputs) == 1:
                progress['stages'][name]['output'] = outputs[0]
        (run / 'cpu_driver_progress.json').write_text(json.dumps(progress, indent=2) + '\n')
        if code:
            raise RuntimeError(f'{name} exited {code}; no GPU allocation permitted')
        if expect_output:
            if len(outputs) != 1:
                raise RuntimeError(f'{name} lacks unique preparation output')
            return Path(outputs[0])

    try:
        base = ['/usr/bin/python3.12', run / 'prepare_cpu_environment.py']
        shared = ['--work-root', root, '--data-root', args.data_root, '--python-executable', '/usr/bin/python3.12']
        execute('inventory', base + ['inventory'] + shared, True)
        frozen = execute('freeze', base + ['freeze'] + shared + ['--wheelhouse', run / 'wheelhouse', '--allow-index-resolution', '--pygments-version', '2.13.0'], True)
        prepared = execute('prepare', base + ['prepare'] + shared + ['--reference-root', args.reference_root, '--frozen-stack', frozen / 'frozen_stack.json', '--sudo-docker'], True)
        environment = json.loads((prepared / 'cpu_environment.json').read_text())
        python = root / '.venv-current/bin/python'
        plan_path = run / 'evaluation_plan.json'
        plan = json.loads(plan_path.read_text())
        image = environment['images']['2.13.0']
        plan['image_map'] = {task: image['image_id'] for task in plan['task_ids']}
        plan['image_ids'] = plan['image_map'].copy()
        plan_path.write_text(json.dumps(plan, indent=2) + '\n')
        common = ['--baseline', run / 'baseline.zip', '--candidate', run / 'candidate.zip', '--data-root', environment['data_root']]
        execute('linux_compiler_preflight', [python, run / 'run_comparison.py', '--preflight-only'] + common + ['--output', run / 'linux_preflight'])
        execute('cpu_controls', [python, run / 'run_comparison.py', '--cpu-controls-only'] + common + ['--output', run / 'cpu_controls'])
        progress['status'] = 'complete'
    except BaseException as error:
        progress['status'] = 'failed'
        progress['error'] = repr(error)
        raise
    finally:
        (run / 'cpu_driver_progress.json').write_text(json.dumps(progress, indent=2) + '\n')


if __name__ == '__main__':
    main()
