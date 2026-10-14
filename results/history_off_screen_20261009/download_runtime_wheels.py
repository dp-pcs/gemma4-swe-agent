import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = [r for r in json.loads(args.manifest.read_text())['datasetFiles'] if r['name'].endswith('.whl')]

    def fetch(row):
        name = row['name']
        if Path(name).name != name:
            raise ValueError('Unexpected nested organizer wheel path')
        path = args.output / name
        reused = path.exists() and path.stat().st_size == row['totalBytes'] and zipfile.is_zipfile(path)
        if not reused:
            command = ['kaggle', 'datasets', 'download', '-d', 'metric/gemma-4-developer-agent-wheelhouse', '-f', name, '-p', str(args.output), '--quiet']
            result = subprocess.run(command, capture_output=True, text=True, timeout=600)
            (args.output / (name + '.download.log')).write_text(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError(f'{name}: download exited {result.returncode}')
        if path.stat().st_size != row['totalBytes'] or not zipfile.is_zipfile(path):
            raise RuntimeError(f'{name}: size or ZIP validation failed')
        digest = hashlib.sha256()
        with path.open('rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(chunk)
        return {'name': name, 'bytes': path.stat().st_size, 'sha256': digest.hexdigest(), 'reused_exact_sized_wheel': reused}

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(fetch, rows))
    (args.output / 'downloaded_wheels.json').write_text(json.dumps({'dataset': 'metric/gemma-4-developer-agent-wheelhouse', 'official_manifest': str(args.manifest), 'wheels': results}, indent=2) + '\n')
    print(json.dumps({'validated_wheels': len(results), 'bytes': sum(r['bytes'] for r in results)}, indent=2))


if __name__ == '__main__':
    main()
