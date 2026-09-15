"""Local capture integrity and cross-platform simulator serialization."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import os
import shutil
from datetime import datetime
from PIL import Image


def read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


@contextmanager
def simulator_lock(path):
    """OS-held lock: released on process exit, including crashes; never unlink it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open('a+b')
    if path.stat().st_size == 0:
        handle.write(b'0')
        handle.flush()
    handle.seek(0)
    acquired = False
    try:
        if os.name == 'nt':
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError('Another scene runner holds the simulator lock.') from exc
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError('Another scene runner holds the simulator lock.') from exc
        acquired = True
        yield
    finally:
        if acquired:
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def preserve_attempt(output):
    """Move only this variant's payload aside before any retry."""
    output = Path(output)
    if not output.exists():
        return None
    destination = output.parent / 'failed_attempts' / output.name / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(output), str(destination))
    return destination


def capture_integrity(output, manifest):
    """Check complete, decodable required camera streams and hash their bytes."""
    output = Path(output)
    expected = int(manifest.get('duration_seconds', 20)) * 20
    if expected <= 0:
        raise ValueError('duration_seconds must be positive')
    views = ['front']
    for line in str(manifest.get('scene_specifications', '')).splitlines():
        if line.lower().strip().startswith('camera contract:'):
            views = [v for v in ('front', 'front_left', 'front_right', 'rear', 'drone_follow')
                     if re.search(r'\b' + v + r'\b', line)] or ['front']
    dimensions = tuple(manifest.get('image_dimensions', [1280, 720]))
    digest = hashlib.sha256()
    errors, counts = [], {}
    for view in views:
        files = sorted((output / view).glob('*.png'))
        counts[view] = len(files)
        numbers = []
        if len(files) != expected:
            errors.append(f'{view}: expected {expected} frames, found {len(files)}')
        for path in files:
            match = re.fullmatch(re.escape(view) + r'_frame_(\d+)\.png', path.name)
            if not match:
                errors.append(f'Unexpected frame name: {view}/{path.name}')
                continue
            numbers.append(int(match.group(1)))
            try:
                with Image.open(path) as im:
                    if im.format != 'PNG' or im.size != dimensions:
                        raise ValueError('incorrect image format/dimensions')
                    im.verify()
                with Image.open(path) as im:
                    im.load()
                digest.update(str(path.relative_to(output)).encode())
                digest.update(hashlib.sha256(path.read_bytes()).digest())
            except (OSError, ValueError, SyntaxError) as exc:
                errors.append(f'Invalid image {view}/{path.name}: {type(exc).__name__}')
        numbers.sort()
        if numbers and numbers != list(range(numbers[0], numbers[0] + expected)):
            errors.append(f'{view}: frame IDs are not consecutive')
    return errors, digest.hexdigest(), counts


def cleanup_verified(output):
    status = read_json(Path(output) / 'cleanup_status.json')
    return status.get('complete') is True and not status.get('errors')
