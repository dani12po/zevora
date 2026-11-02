import re
from dataclasses import dataclass

from ..models import capabilities as cap


@dataclass(frozen=True)
class ClassifiedTask:
    labels: list[str]
    required_capabilities: list[str]
    complexity_score: float
    requires_tools: list[str]


class TaskClassifier:
    """Classify natural-language requests, including common Indonesian coding phrasing."""

    CODING_WORDS = {
        'script', 'javascript', 'typescript', 'java', 'python', 'css', 'html',
        'json', 'api', 'aplikasi', 'program', 'kode', 'fungsi', 'function',
        'project', 'endpoint', 'contract', 'dependency', 'package', 'npm',
        'install', 'build', 'compile', 'jalankan', 'run', 'test', 'jalanin',
        'debug', 'error', 'bug', 'inspect', 'lihat', 'periksa', 'refactor',
        'repository', 'repo', 'terminal', 'command', 'file', 'files', 'folder',
        'git', 'commit', 'diff', 'buat', 'buatkan', 'create', 'ubah', 'edit',
        'perbaiki', 'fix',
    }
    CODING_ACTIONS = {
        'install', 'build', 'compile', 'jalankan', 'run', 'test', 'jalanin',
        'debug', 'inspect', 'lihat', 'periksa', 'refactor', 'commit', 'buat',
        'buatkan', 'create', 'ubah', 'edit', 'perbaiki', 'fix',
    }
    VISION_WORDS = {'image', 'gambar', 'screenshot', 'foto', 'attachment'}
    CODE_EXTENSIONS = ('.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.css', '.json')

    @staticmethod
    def _contains_word(text: str, word: str) -> bool:
        return bool(re.search(rf'(?<![\w-]){re.escape(word)}(?![\w-])', text))

    @staticmethod
    def _contains_phrase(text: str, phrase: str) -> bool:
        pattern = r'(?<![\w-])' + re.escape(phrase).replace(r'\ ', r'\s+') + r'(?![\w-])'
        return bool(re.search(pattern, text))

    def classify(self, prompt: str) -> ClassifiedTask:
        text = str(prompt or '').lower()
        words = {word for word in self.CODING_WORDS if self._contains_word(text, word)}
        has_filename = any(extension in text for extension in self.CODE_EXTENSIONS)
        coding_signal = bool(words & self.CODING_ACTIONS or has_filename)
        labels: list[str] = []
        required: list[str] = []
        tools: list[str] = []
        complexity = .08 + min(.25, len(text) / 8000)

        if coding_signal:
            labels.append('coding')
            required.append(cap.CODING)
            complexity += .12
        if words & {'debug', 'error', 'bug'}:
            labels.append('debugging')
            required.append(cap.REASONING)
            complexity += .12
        if any(self._contains_word(text, word) for word in self.VISION_WORDS):
            labels.append('vision')
            required.append(cap.VISION)
            complexity += .12
        if any(self._contains_word(text, word) for word in ('research', 'latest', 'search web')):
            labels.append('research')
            required.append(cap.GENERAL)
            complexity += .12
        if any(self._contains_word(text, word) for word in ('reason', 'architecture', 'complex')):
            labels.append('reasoning')
            required.append(cap.REASONING)
            complexity += .12
        if any(self._contains_word(text, word) for word in ('summarize', 'summary', 'ringkas')):
            labels.append('summarization')
            required.append(cap.GENERAL)
            complexity += .12
        workspace_operation = any(
            self._contains_word(text, word)
            for word in ('terminal', 'command', 'tool', 'inspect', 'lihat', 'periksa')
        ) and any(
            self._contains_word(text, word)
            for word in ('file', 'files', 'folder', 'project', 'repository', 'repo')
        )
        if coding_signal and (
            any(self._contains_word(text, word) for word in ('terminal', 'command', 'tool'))
            or workspace_operation
        ):
            labels.append('tool_task')
            required.append(cap.GENERAL)
            complexity += .12

        if (
            coding_signal
            and any(self._contains_word(text, word) for word in ('file', 'files', 'folder', 'project', 'repository', 'repo'))
        ) or has_filename:
            tools.append('filesystem.read')
        if (
            self._contains_phrase(text, 'run test')
            or self._contains_phrase(text, 'run tests')
            or any(self._contains_word(text, word) for word in ('terminal', 'command', 'install', 'jalankan', 'jalanin', 'npm'))
        ):
            tools.append('terminal.execute')
        if any(self._contains_word(text, word) for word in ('git', 'commit', 'diff')):
            tools.append('git.status')
        if any(phrase in text for phrase in ('create project', 'buat project', 'buatkan project', 'buat project')):
            tools.append('project.create')
        if any(phrase in text for phrase in ('architecture', 'migration strategy', 'entire project', 'seluruh project', 'refactor seluruh')):
            complexity += .32
        if len(labels) > 1:
            complexity += .1
        return ClassifiedTask(
            labels or ['general_chat'],
            list(dict.fromkeys(required or [cap.GENERAL])),
            min(round(complexity, 2), 1.0),
            list(dict.fromkeys(tools)),
        )
