"""Create a byte-identical, private upload copy outside hidden cache folders.

This only stages a file. It grants no permission and performs no upload.
"""
import argparse
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path


def fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def stage(source, staging_root=None):
    source = Path(source).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError('regular_file_required')
    root = Path(staging_root or Path.home() / 'PickleUploadStaging').expanduser()
    if not root.is_absolute() or root.is_symlink():
        raise ValueError('absolute_non_symlink_staging_root_required')
    root = root.resolve()
    if any(part.startswith('.') for part in root.parts):
        raise ValueError('staging_path_must_not_contain_hidden_directories')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = root.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError('staging_root_must_be_owner_only')
    folder = Path(tempfile.mkdtemp(prefix='upload-', dir=root))
    filename = source.name if not source.name.startswith('.') else 'attachment' + ''.join(source.suffixes)
    target = folder / filename
    receipt = folder / 'upload-receipt.json'
    if target == receipt:
        target = folder / ('attachment-' + filename)
    try:
        with source.open('rb') as original:
            before = os.fstat(original.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError('regular_file_required')
            expected = hashlib.sha256()
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as copy:
                for block in iter(lambda: original.read(1024 * 1024), b''):
                    expected.update(block)
                    copy.write(block)
            if fingerprint(before) != fingerprint(os.fstat(original.fileno())):
                raise ValueError('source_changed_during_copy')
        if (fingerprint(before) != fingerprint(source.stat())
                or digest_file(source) != expected.hexdigest()
                or digest_file(target) != expected.hexdigest()
                or target.stat().st_size != before.st_size):
            raise ValueError('staged_copy_verification_failed')
        result = {'status': 'staged_only', 'source_path': str(source),
                  'attachment_path': str(target), 'bytes': before.st_size,
                  'sha256': expected.hexdigest(), 'receipt_path': str(receipt)}
        fd = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as out:
            json.dump(result, out, ensure_ascii=False)
        return result
    except BaseException:
        # Only the new files created by this attempt; never the source/cache.
        target.unlink(missing_ok=True)
        receipt.unlink(missing_ok=True)
        folder.rmdir()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--staging-root')
    args = parser.parse_args()
    print(json.dumps(stage(args.source, args.staging_root), ensure_ascii=False))


if __name__ == '__main__':
    main()
