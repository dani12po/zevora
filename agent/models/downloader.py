"""Single-file GGUF downloader for the bundled local model (Phase 5).

Downloads ONLY the selected ``<repository>/<filename>`` file from the
Hugging Face ``resolve`` endpoint — it never clones or downloads the whole
repository. Supports resumable downloads, byte progress callbacks, size and
SHA-256 verification, atomic installation via a temporary file, and rollback
on failure. The existing model file is never silently overwritten.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Callable

import httpx

logger = logging.getLogger(__name__)

HF_RESOLVE_URL = 'https://huggingface.co/{repository}/resolve/{revision}/{filename}'
_CHUNK_SIZE = 1024 * 1024  # 1 MiB per streamed chunk


class DownloadError(RuntimeError):
    """Raised when the GGUF download cannot be completed safely."""


class SizeMismatchError(DownloadError):
    """Raised when the downloaded bytes disagree with the expected size."""


class ChecksumMismatchError(DownloadError):
    """Raised when the downloaded SHA-256 disagrees with the reference."""


ProgressCallback = Callable[[int, int], None]


def resolve_download_url(repository: str, filename: str, revision: str = 'main') -> str:
    """Return the direct single-file download URL for a GGUF blob."""
    return HF_RESOLVE_URL.format(repository=repository, revision=revision, filename=filename)


def download_gguf(
    *,
    repository: str,
    filename: str,
    dest: Path | str,
    expected_size_bytes: int = 0,
    sha256: str = '',
    revision: str = 'main',
    timeout_seconds: int = 120,
    replace: bool = False,
    progress_cb: ProgressCallback | None = None,
    client: httpx.Client | None = None,
) -> dict:
    """Download one GGUF file to ``dest`` with verification and atomic install.

    * ``replace=False`` (default) refuses to overwrite an existing model file.
    * A ``<dest>.part`` temporary file enables resume across interruptions.
    * Size and SHA-256 are verified before the atomic rename; on verification
      failure the temporary file is removed (rollback) and the previous model
      — if any — is left untouched.
    """
    target = Path(dest).expanduser()
    if target.exists() and not replace:
        raise DownloadError(
            f'destination already exists: {target} '
            '(pass replace=True to explicitly replace the managed model)'
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + '.part')
    url = resolve_download_url(repository, filename, revision)
    resume_from = tmp.stat().st_size if tmp.is_file() else 0
    headers = {'Range': f'bytes={resume_from}-'} if resume_from else {}

    owned_client = client is None
    http = client or httpx.Client(timeout=timeout_seconds, follow_redirects=True)
    try:
        with http.stream('GET', url, headers=headers) as response:
            if resume_from and response.status_code == 200:
                # Server ignored the range; restart from scratch.
                resume_from = 0
                if tmp.is_file():
                    tmp.unlink()
            elif response.status_code not in (200, 206):
                raise DownloadError(
                    f'model download failed: HTTP {response.status_code} for {url}'
                )
            total = _total_size(response, resume_from)
            digest = hashlib.sha256()
            if resume_from:
                with tmp.open('rb') as handle:
                    for block in iter(lambda: handle.read(_CHUNK_SIZE), b''):
                        digest.update(block)
            downloaded = resume_from
            if progress_cb is not None:
                progress_cb(downloaded, total)
            mode = 'ab' if resume_from else 'wb'
            with tmp.open(mode) as handle:
                for chunk in response.iter_bytes(_CHUNK_SIZE):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    if progress_cb is not None:
                        progress_cb(downloaded, total)
    finally:
        if owned_client:
            http.close()

    if expected_size_bytes and downloaded != expected_size_bytes:
        tmp.unlink(missing_ok=True)
        raise SizeMismatchError(
            f'model size mismatch: got {downloaded} bytes, '
            f'expected {expected_size_bytes} bytes'
        )
    actual_sha256 = digest.hexdigest()
    if sha256 and actual_sha256.lower() != sha256.lower():
        tmp.unlink(missing_ok=True)
        raise ChecksumMismatchError(
            'model SHA-256 mismatch: downloaded file does not match its reference'
        )

    tmp.replace(target)  # atomic install on the same filesystem
    if sha256:
        target.with_name(target.name + '.sha256').write_text(
            f'{actual_sha256}  {target.name}\n', encoding='utf-8',
        )
    logger.info(
        'local_model_downloaded repository=%s filename=%s bytes=%s',
        repository, filename, downloaded,
    )
    return {
        'repository': repository,
        'filename': filename,
        'path': str(target),
        'bytes': downloaded,
        'sha256': actual_sha256,
        'resumed': resume_from > 0,
    }


def _total_size(response: httpx.Response, resume_from: int) -> int:
    """Best-effort total byte count for progress reporting (0 when unknown)."""
    content_range = response.headers.get('content-range', '')
    if '/' in content_range:
        try:
            return int(content_range.rsplit('/', 1)[1])
        except ValueError:
            pass
    try:
        return int(response.headers.get('content-length', 0)) + resume_from
    except (TypeError, ValueError):
        return resume_from
