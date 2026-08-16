"""Security and compatibility tests for evolution, updates, and local packages."""
import asyncio
import hashlib
from pathlib import Path

import pytest

import main
from agent.evolution.contribution import ContributionQueue
from agent.evolution.sanitizer import sanitize
from agent.evolution.updater import UpdateComponent, UpdateManifest, VerifiedUpdater
from agent.memory.store import Store
from agent.models.manager import LocalIntelligenceManager
from agent.skills.registry import Skill, SkillRegistry


def _file_url(path: Path) -> str:
    return path.resolve().as_uri()


def test_collective_learning_is_disabled_and_requires_consent(tmp_path, monkeypatch):
    queue = ContributionQueue(Store(tmp_path / 'agent.db'))
    monkeypatch.setattr('agent.evolution.contribution.settings.collective_learning_enabled', False)
    result = queue.enqueue('routing', {'task_class': 'coding', 'route': 'local'})
    assert result == {'accepted': False, 'reason': 'collective_learning_disabled'}
    assert queue.pending() == []


def test_sanitizer_rejects_secrets_and_unknown_fields():
    secret = 'sk-' + ('synthetic' * 3)
    assert not sanitize('knowledge', {'summary': secret}).accepted
    assert not sanitize('routing', {'task_class': 'coding', 'unexpected': 'value'}).accepted


def test_untrusted_skill_is_registered_but_never_loaded(tmp_path):
    registry = SkillRegistry(tmp_path / 'skills.db')
    registry.register(Skill(
        skill_id='remote-candidate',
        name='Remote candidate',
        description='coding helper',
        capabilities=('coding',),
        instructions='Run an unverified process.',
        source='remote',
        trust_state='untrusted',
    ))
    context, used = registry.context_for('coding helper', capabilities={'coding'})
    assert context == ''
    assert used == []


def test_update_component_rejects_traversal_and_insecure_url():
    base = {
        'id': 'core', 'version': '1.0.0', 'sha256': 'a' * 64,
        'destination': 'agent/core.py',
    }
    with pytest.raises(ValueError, match='HTTPS'):
        UpdateComponent.from_dict({**base, 'url': 'http://example.test/core.py'})
    with pytest.raises(ValueError, match='traversal'):
        UpdateComponent.from_dict({**base, 'url': 'https://example.test/core.py', 'destination': '../core.py'})


def test_verified_update_stages_hash_and_rolls_back_activation(tmp_path, monkeypatch):
    root = tmp_path / 'install'
    backup = tmp_path / 'backups'
    source = tmp_path / 'component.bin'
    source.write_bytes(b'verified update')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    component = UpdateComponent.from_dict({
        'id': 'core', 'version': '2.0.0', 'url': _file_url(source),
        'sha256': digest, 'destination': 'agent/core.bin',
        'size_bytes': source.stat().st_size,
    })
    updater = VerifiedUpdater(root, backup)
    staged = asyncio.run(updater.stage([component], tmp_path / 'staging'))
    result = updater.activate(staged, '2.0.0')
    assert result['activated'] == 1
    assert (root / 'agent' / 'core.bin').read_bytes() == b'verified update'

    bad_source = tmp_path / 'bad.bin'
    bad_source.write_bytes(b'bad')
    bad = UpdateComponent.from_dict({
        'id': 'bad', 'version': '2.0.0', 'url': _file_url(bad_source),
        'sha256': '0' * 64, 'destination': 'agent/bad.bin',
    })
    with pytest.raises(ValueError, match='hash mismatch'):
        asyncio.run(updater.stage([bad], tmp_path / 'bad-staging'))
    assert not (root / 'agent' / 'bad.bin').exists()


def test_update_manifest_plan_is_incremental(tmp_path):
    component = UpdateComponent(
        'core', '2.0.0', (tmp_path / 'source').as_uri(), 'a' * 64, 'agent/core.py'
    )
    manifest = UpdateManifest('2.0.0', '0.2.0', (component,))
    updater = VerifiedUpdater(tmp_path / 'root', tmp_path / 'backup')
    assert updater.plan(manifest, {'core': '2.0.0'}) == []
    assert updater.plan(manifest, {'core': '1.0.0'}) == [component]


def test_local_package_uninstall_is_dry_run_then_approval(tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    package = root / 'data' / 'models' / 'managed-package'
    package.mkdir(parents=True)
    (package / 'manifest.json').write_text('{}', encoding='utf-8')
    external = tmp_path / 'external.gguf'
    external.write_bytes(b'external')
    monkeypatch.setattr('agent.models.manager.ROOT', root)
    monkeypatch.setattr('agent.models.manager.settings.local_model_package_path', str(package))

    manager = LocalIntelligenceManager()
    preview = manager.uninstall_package()
    assert preview['executed'] is False
    assert package.exists()
    removed = manager.uninstall_package(approved=True)
    assert removed['executed'] is True
    assert not package.exists()
    assert external.exists()


def test_local_package_uninstall_rejects_external_directory(tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    external = tmp_path / 'external-package'
    external.mkdir()
    monkeypatch.setattr('agent.models.manager.ROOT', root)
    monkeypatch.setattr('agent.models.manager.settings.local_model_package_path', str(external))
    with pytest.raises(ValueError, match='outside'):
        LocalIntelligenceManager().uninstall_package(approved=True)


def test_evolution_status_api_does_not_expose_skill_instructions(tmp_path, monkeypatch):
    registry = SkillRegistry(tmp_path / 'skills.db')
    registry.register(Skill(
        skill_id='safe-skill', name='Safe skill', instructions='private implementation detail'
    ))
    monkeypatch.setattr(main, 'skill_registry', registry)
    result = main.evolution_status()
    assert result['updates']['verification'] == 'sha256_required'
    assert result['collective_learning']['silent_uploads'] is False
    assert result['skills'][0]['skill_id'] == 'safe-skill'
    assert 'instructions' not in result['skills'][0]
