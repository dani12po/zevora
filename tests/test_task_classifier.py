import pytest

from agent.routing.task_classifier import TaskClassifier


CODING_PROMPTS = [
    'jalankan hello.py',
    'ubah hello.py agar mencetak Hello ZEVORA',
    'jalankan lagi',
    'buatkan package.json dan jalankan npm test',
    'run npm test',
    'install dependency',
    'jalankan aplikasi',
    'buat project React',
    'ubah CSS',
    'buat API endpoint',
    'buat smart contract',
    'ubah fungsi login',
    'buat file hello.py yang mencetak Hello World',
    'perbaiki error project ini dan jalankan test',
    'create a JavaScript program',
    'build aplikasi HTML dan CSS',
    'compile Java project ini',
    'edit function authentication',
    'refactor kode TypeScript',
    'jalanin script test.js',
    'fix bug pada API endpoint',
]


@pytest.mark.parametrize('prompt', CODING_PROMPTS)
def test_bilingual_coding_prompts_are_classified_for_workspace(prompt):
    task = TaskClassifier().classify(prompt)

    assert 'coding' in task.labels


@pytest.mark.parametrize('prompt', [
    'apa itu Python?',
    'ceritakan sejarah AI',
    'jelaskan apa itu JavaScript',
    'siapa pencipta bahasa Java?',
    'ringkas artikel ini',
])
def test_non_coding_prompts_do_not_trigger_coding_workspace(prompt):
    task = TaskClassifier().classify(prompt)

    assert 'coding' not in task.labels
    assert 'debugging' not in task.labels
    assert 'tool_task' not in task.labels


def test_file_and_action_prompts_expose_navigation_tool_hints():
    classifier = TaskClassifier()

    assert 'filesystem.read' in classifier.classify('ubah app.py').requires_tools
    assert 'terminal.execute' in classifier.classify('jalankan npm test').requires_tools
    assert 'project.create' in classifier.classify('buat project React').requires_tools
