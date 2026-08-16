"""Bounded project indexing and deterministic context selection."""

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

MANIFESTS = {
    'package.json': 'JavaScript/TypeScript',
    'requirements.txt': 'Python',
    'pyproject.toml': 'Python',
    'tsconfig.json': 'TypeScript',
    'Cargo.toml': 'Rust',
    'go.mod': 'Go',
}
IGNORED_PARTS = {
    '.git', '.idea', '.venv', '.vscode', 'venv', 'node_modules', 'dist',
    'build', '__pycache__', 'coverage', '.pytest_cache',
}
TEXT_SUFFIXES = {
    '.c', '.cc', '.conf', '.cpp', '.css', '.csv', '.env.example', '.go',
    '.h', '.hpp', '.html', '.ini', '.java', '.js', '.json', '.jsx', '.log',
    '.md', '.php', '.properties', '.py', '.rb', '.rs', '.sh', '.sql', '.toml',
    '.ts', '.tsx', '.txt', '.xml', '.yaml', '.yml',
}
TOKEN_RE = re.compile(r'[A-Za-z0-9_./-]{2,}')


def detect_language(path: Path) -> str:
    return {
        '.py': 'Python', '.ts': 'TypeScript', '.tsx': 'TypeScript',
        '.js': 'JavaScript', '.jsx': 'JavaScript', '.go': 'Go', '.rs': 'Rust',
        '.java': 'Java', '.json': 'JSON', '.md': 'Markdown', '.css': 'CSS',
        '.html': 'HTML', '.csv': 'CSV', '.log': 'Log',
    }.get(path.suffix.lower(), MANIFESTS.get(path.name, 'Unknown'))


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _search_text(path: Path, size: int, max_text_bytes: int) -> str:
    suffix = path.suffix.lower()
    if size > max_text_bytes or (suffix not in TEXT_SUFFIXES and path.name not in MANIFESTS):
        return ''
    data = path.read_bytes()
    if b'\x00' in data:
        return ''
    return data.decode('utf-8', errors='replace')


def index_project(root: Path, max_files: int = 1000, max_text_bytes: int = 128_000) -> list[dict]:
    """Index stable file metadata and bounded searchable text under ``root``."""
    root = root.resolve()
    now = datetime.now(timezone.utc).isoformat()
    rows: list[dict] = []
    candidates = sorted(
        (path for path in root.rglob('*') if path.is_file()),
        key=lambda path: path.relative_to(root).as_posix().lower(),
    )
    for path in candidates:
        relative = path.relative_to(root)
        if len(rows) >= max_files:
            break
        if any(part in IGNORED_PARTS for part in relative.parts):
            continue
        try:
            size = path.stat().st_size
            content_hash = _digest(path)
            text = _search_text(path, size, max_text_bytes)
        except (OSError, PermissionError):
            continue
        rows.append({
            'path': relative.as_posix(),
            'language': detect_language(path),
            'summary': f'{path.name} ({size} bytes)',
            'content_hash': content_hash,
            'size_bytes': size,
            'search_text': text,
            'indexed_at': now,
        })
    return rows


def discover_project(root: Path, rows: list[dict] | None = None, max_tree_entries: int = 200) -> dict:
    """Describe the project from indexed metadata without loading the repository."""
    root = root.resolve()
    rows = rows if rows is not None else index_project(root)
    paths = [row['path'] for row in rows]
    names = {Path(path).name for path in paths}
    languages = sorted({row['language'] for row in rows if row['language'] != 'Unknown'})
    frameworks = []
    if 'package.json' in names:
        frameworks.append('Node.js')
    if 'next.config.js' in names or 'next.config.mjs' in names:
        frameworks.append('Next.js')
    if any(name in names for name in {'pyproject.toml', 'requirements.txt'}):
        frameworks.append('Python')
    if 'Cargo.toml' in names:
        frameworks.append('Rust')
    if 'go.mod' in names:
        frameworks.append('Go')
    package_manager = next((manager for lockfile, manager in (
        ('pnpm-lock.yaml', 'pnpm'), ('yarn.lock', 'yarn'),
        ('package-lock.json', 'npm'), ('uv.lock', 'uv'),
        ('poetry.lock', 'Poetry'),
    ) if lockfile in names), None)
    manifests = sorted(path for path in paths if Path(path).name in MANIFESTS)
    return {
        'frameworks': frameworks,
        'languages': languages,
        'package_manager': package_manager,
        'manifests': manifests,
        'file_tree': paths[:max_tree_entries],
        'tree_truncated': len(paths) > max_tree_entries,
    }


def project_context(root: Path, prompt: str, max_files: int = 8, max_chars: int = 12_000) -> dict:
    """Return a full-project fingerprint and only the files relevant to ``prompt``."""
    root = root.resolve()
    rows = index_project(root)
    fingerprint = hashlib.sha256(str(root).encode('utf-8'))
    for row in rows:
        fingerprint.update(row['path'].encode('utf-8'))
        fingerprint.update(row['content_hash'].encode('ascii'))

    terms = {token.lower() for token in TOKEN_RE.findall(prompt)}
    ranked: list[tuple[int, str, dict]] = []
    for row in rows:
        path_lower = row['path'].lower()
        path_tokens = {token.lower() for token in TOKEN_RE.findall(path_lower)}
        text_lower = row['search_text'].lower()
        path_score = sum(5 for term in terms if term in path_lower or term in path_tokens)
        content_score = sum(1 for term in terms if term in text_lower)
        manifest_score = 2 if Path(row['path']).name in MANIFESTS else 0
        score = path_score + content_score + manifest_score
        if score:
            ranked.append((score, path_lower, row))

    selected = []
    remaining = max_chars
    for score, _, row in sorted(ranked, key=lambda item: (-item[0], item[1]))[:max_files]:
        content = row['search_text'][:remaining]
        if not content:
            continue
        selected.append({
            'path': row['path'], 'language': row['language'],
            'content_hash': row['content_hash'], 'score': score, 'content': content,
        })
        remaining -= len(content)
        if remaining <= 0:
            break

    return {
        'root': str(root),
        'context_hash': fingerprint.hexdigest(),
        'files_indexed': len(rows),
        'discovery': discover_project(root, rows),
        'files': selected,
        'rows': rows,
    }


def format_project_context(context: dict) -> str:
    """Format bounded discovery and relevant files with clear provider boundaries."""
    discovery = context.get('discovery', {})
    parts = [
        'Project discovery (authoritative local index):',
        f"Frameworks: {', '.join(discovery.get('frameworks', [])) or 'unknown'}",
        f"Languages: {', '.join(discovery.get('languages', [])) or 'unknown'}",
        f"Package manager: {discovery.get('package_manager') or 'unknown'}",
        f"Manifests: {', '.join(discovery.get('manifests', [])) or 'none'}",
        'Bounded file tree:\n' + '\n'.join(discovery.get('file_tree', [])),
    ]
    if context.get('files'):
        parts.append('Relevant project files (read-only context):')
        for item in context['files']:
            parts.append(f"\n--- {item['path']} [{item['language']}] ---\n{item['content']}")
    return '\n'.join(parts)
