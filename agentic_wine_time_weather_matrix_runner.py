#!/usr/bin/env python3
"""Resumable eight-condition capture for a finalized CARLA scene."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from agentic_wine_handoff_runner import BASE_DIR, HANDOFF_DIR_DEFAULT, load_manifest, resolve_manifest_path, _resolve_path_from_manifest, run_manifest
from agent_skill_scene_loop import validate_code_readiness
from scene_utils.time_weather_matrix import load_time_weather_spec, iter_time_weather_combinations, build_scene_env_cli_args
from scene_utils.matrix_resume import read_json, write_json, simulator_lock, preserve_attempt, capture_integrity, cleanup_verified


def source_signature(manifest, code, cli):
    # Hash local Python dependencies without importing/executing generated code.
    import ast
    pending, seen, sources = [Path(code), Path(__file__), BASE_DIR / 'agentic_wine_handoff_runner.py'], set(), {}
    while pending:
        path = pending.pop().resolve()
        if path in seen:
            continue
        seen.add(path)
        contents = path.read_bytes()
        sources[str(path)] = hashlib.sha256(contents).hexdigest()
        tree = ast.parse(contents)
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
            for name in names:
                for parent in [path.parent, BASE_DIR]:
                    dependency = parent / (name.replace('.', '/') + '.py')
                    if dependency.is_file():
                        pending.append(dependency)
                        break
    payload = {'manifest': manifest, 'sources': sources, 'environment_args': cli}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def validate_variant(output, manifest, signature, result=None):
    resuming = result is None
    result = read_json(output / 'variant_result.json') if resuming else result
    errors, digest, counts = capture_integrity(output, manifest)
    if resuming and (result.get('success') is not True or not result.get('capture_sha256')):
        errors.append('Complete successful receipt with capture hash is required')
    if result.get('dry_run') is not False or result.get('returncode') != 0 or result.get('process_success') is not True:
        errors.append('A successful real process exit is required')
    if result.get('source_signature') != signature:
        errors.append('Source, manifest, or environment settings changed')
    if not cleanup_verified(output):
        errors.append('Checked cleanup_status.json is missing or reports failure')
    if result.get('capture_sha256') and result['capture_sha256'] != digest:
        errors.append('Capture bytes changed since successful validation')
    return errors, digest, counts


def run_variant(manifest, output, cli, timeout, max_attempts, cooldown, dry_run=False):
    code = _resolve_path_from_manifest(manifest, 'code')
    signature = source_signature(manifest, code, cli)
    if dry_run:
        result = run_manifest(manifest, timeout, True, BASE_DIR, output_dir_override=output, script_args_extra=cli)
        return dict(result, success=False, status='DRY_RUN_ONLY')
    if output.exists():
        errors, _, _ = validate_variant(output, manifest, signature)
        if not errors:
            print(f'[SKIP] Revalidated {output.name}', flush=True)
            return dict(read_json(output / 'variant_result.json'), status='SKIPPED_VERIFIED')
    result = {}
    for attempt in range(1, max_attempts + 1):
        saved = preserve_attempt(output)
        if saved:
            print(f'[PRESERVED] {saved}', flush=True)
        print(f'[RUN] {output.name}, attempt {attempt}/{max_attempts}', flush=True)
        result = run_manifest(manifest, timeout, False, BASE_DIR, min_success_ratio=1.0,
                              output_dir_override=output, script_args_extra=cli, label=output.name)
        result['source_signature'] = signature
        errors, digest, counts = validate_variant(output, manifest, signature, result)
        if source_signature(manifest, code, cli) != signature:
            errors.append('Source changed during capture')
        result.update(success=not errors, capture_sha256=digest, frame_counts_by_view=counts,
                      validation_errors=errors, status='CAPTURE_VERIFIED' if not errors else 'FAILED',
                      cleanup_verified=cleanup_verified(output))
        write_json(output / 'variant_result.json', result)
        if not errors or not result['cleanup_verified']:
            break
        if attempt < max_attempts:
            time.sleep(cooldown)
    return result


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--handoff-manifest', required=True, help='Explicit finalized scene manifest')
    parser.add_argument('--handoff-dir', default=str(HANDOFF_DIR_DEFAULT))
    parser.add_argument('--spec', help='Optional eight-condition specification')
    parser.add_argument('--timeout', type=int)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--max-attempts-per-variant', type=int, default=2)
    parser.add_argument('--cooldown-seconds', type=int, default=8)
    return parser.parse_args()


def execute(args):
    manifest_path = resolve_manifest_path(args.handoff_manifest, Path(args.handoff_dir))
    manifest = load_manifest(manifest_path)
    code = _resolve_path_from_manifest(manifest, 'code')
    issues = validate_code_readiness(code)
    if issues:
        raise ValueError('; '.join(issues))
    spec = load_time_weather_spec(args.spec)
    combos = list(iter_time_weather_combinations(spec))
    if {c['variant_name'] for c in combos} != {f'{t}__{w}' for t in ('noon','night') for w in ('clear','storm','worst','foggy')}:
        raise ValueError('The paper capture requires exactly the eight Noon/Night weather combinations')
    output = _resolve_path_from_manifest(manifest, 'output') / spec['matrix_output_subdir']
    if output.resolve() == code.parent.resolve() or code.resolve().is_relative_to(output.resolve()):
        raise ValueError('Capture output must not contain the source script')
    result_path = manifest_path.parent / ('matrix_preparation.json' if args.dry_run else 'simulation_result_matrix8.json')
    previous = read_json(result_path)
    if previous:
        from datetime import datetime
        write_json(manifest_path.parent / 'matrix_history' / (datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json'), previous)
    summary = {'dry_run': args.dry_run, 'success': False, 'variant_count_expected':8, 'matrix_variants':[]}
    for index, combo in enumerate(combos, 1):
        name = combo['variant_name']
        print(f'[{index}/8] {combo["time_preset"]["label"]} / {combo["weather_preset"]["label"]}', flush=True)
        cli = build_scene_env_cli_args(combo['time_preset'], combo['weather_preset'])
        result = run_variant(manifest, output/name, cli, args.timeout,
                             max(1,args.max_attempts_per_variant), max(0,args.cooldown_seconds), args.dry_run)
        summary['matrix_variants'].append(dict(variant_name=name, **result))
        summary['variant_count_completed'] = len(summary['matrix_variants'])
        summary['variant_success_count'] = sum(v['success'] for v in summary['matrix_variants'])
        write_json(result_path, summary)
        print(f'[{index}/8] {result["status"]}', flush=True)
        if not args.dry_run and not result.get('cleanup_verified'):
            summary['stopped_reason'] = 'Cleanup unverified. Inspect the simulator before rerunning.'
            break
    summary['success'] = not args.dry_run and summary.get('variant_success_count') == 8
    write_json(result_path, summary)
    print(f'{summary.get("variant_success_count",0)}/8 captures verified. Visual review remains separate.', flush=True)
    return 0 if args.dry_run or summary['success'] else 1


def main():
    args = parse_args()
    try:
        with simulator_lock(BASE_DIR/'handoffs'/'.simulator.lock'):
            return execute(args)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'[ERROR] {exc}', flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
