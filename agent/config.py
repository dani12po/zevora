import json
import os
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class LocalModelProfile:
    """Model-agnostic description of a bundled local model."""
    provider_id: str = 'local'
    model_id: str = 'lexi-llama-3-8b-q4_k_m'
    display_name: str = 'Lexi Llama 3 8B Q4_K_M'
    repository: str = 'bartowski/Lexi-Llama-3-8B-Uncensored-GGUF'
    filename: str = 'Lexi-Llama-3-8B-Uncensored-Q4_K_M.gguf'
    quantization: str = 'Q4_K_M'
    runtime: str = 'llamacpp'
    format: str = 'gguf'
    context_length: int = 8192
    max_output_tokens: int = 2048
    temperature: float = 0.4
    batch_size: int = 512
    threads: int = 0
    gpu_layers: int = 0
    expected_size_bytes: int = 0
    sha256: str = ''
    capabilities: list[str] = dc_field(default_factory=lambda: ['chat', 'instruction'])
    source: str = 'huggingface'
    license: str = 'apache-2.0'
    deployment_mode: str = 'bundled'
    # Optional override so tests can point at a tmp_path without touching the
    # real model directory.  When None the path is derived from repository/filename.
    model_file_path: str = ''


DEFAULT_LEXI_PROFILE = LocalModelProfile()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')

    # ── Cloud provider API keys & endpoints ──────────────────────────────────
    openai_api_key: str = ''
    openai_base_url: str = 'https://api.openai.com/v1'
    openai_model: str = 'gpt-4o-mini'
    xai_api_key: str = ''
    xai_base_url: str = 'https://api.x.ai/v1'
    xai_model: str = 'grok-3-mini'
    nvidia_api_key: str = ''
    nvidia_base_url: str = 'https://integrate.api.nvidia.com/v1'
    nvidia_model: str = 'meta/llama-3.1-8b-instruct'
    deepseek_api_key: str = ''
    deepseek_base_url: str = 'https://api.deepseek.com/v1'
    deepseek_model: str = 'deepseek-chat'
    gemini_api_key: str = ''
    gemini_model: str = 'gemini-2.0-flash'
    anthropic_api_key: str = ''
    anthropic_base_url: str = 'https://api.anthropic.com'
    anthropic_model: str = 'claude-3-5-haiku-latest'
    cloud_default_provider: str = 'openai'

    # ── Hybrid local intelligence (runtime-agnostic configuration) ───────────
    # The local model reference is fully configurable so quantization changes
    # (or a future model family swap) never require a provider rewrite.
    local_model_enabled: bool = True
    local_provider_id: str = 'local'
    local_model_runtime: str = 'llamacpp'
    local_endpoint_url: str = 'http://127.0.0.1:11434'
    local_endpoint_api_key: str = ''
    local_endpoint_timeout_seconds: int = 30
    # Lexi-Llama-3-8B GGUF repository and quantization. The provider loads the
    # single selected package; it never downloads the whole repository.
    local_model_repository: str = 'bartowski/Lexi-Llama-3-8B-Uncensored-GGUF'
    local_model_quant: str = 'Q4_K_M'
    local_model_base_url: str = ''
    local_model_display_name: str = 'Lexi Llama 3 8B Q4_K_M'
    local_model_path: str = 'models/Lexi-Llama-3-8B-Uncensored-Q4_K_M.gguf'
    local_model_filename: str = 'Lexi-Llama-3-8B-Uncensored-Q4_K_M.gguf'
    local_model_name: str = 'lexi-llama-3-8b-q4_k_m'
    local_model_package_path: str = 'data/models/zevora-local'
    local_model_external_path: str = ''
    local_model_registry_path: str = 'data/database/model_registry.db'
    local_model_context_length: int = 8192
    local_model_max_tokens: int = 2048
    local_model_threads: int = 0
    # GPU layers offloaded to llama.cpp. ``0`` means AUTO: prefer GPU offload
    # when a GPU is detected, otherwise stay on CPU. Accepts ``auto`` as well.
    local_model_gpu_layers: int = 0
    local_model_batch_size: int = 512
    local_model_temperature: float = .4
    # Active bundled-local-model profile. The provider reads model parameters from
    # this profile instead of the flat ``local_model_*`` fields; it never
    # downloads the whole repository, only the selected package.
    active_local_model_profile: LocalModelProfile = DEFAULT_LEXI_PROFILE

    # ── Remote Lexi backend (generic OpenAI-compatible llama.cpp server) ──────
    # May run on Colab, Kaggle, self-hosted GPU, or any compatible endpoint.
    # Only BASE_URL + MODEL_ID (+ optional API key) are required; never commit
    # a temporary tunnel URL to the repository.
    remote_local_enabled: bool = False
    remote_local_base_url: str = ''
    remote_local_api_key: str = ''
    remote_local_model: str = 'lexi-llama-3-8b-q4_k_m'
    remote_local_timeout_seconds: int = 120
    remote_local_health_check_timeout_seconds: int = 10
    remote_local_streaming: bool = True
    remote_local_routing_priority: int = 90

    @field_validator('local_model_gpu_layers', mode='before')
    @classmethod
    def _coerce_gpu_layers(cls, value):
        """Accept ``auto`` (Phase 19) as AUTO == 0 instead of failing parsing."""
        if isinstance(value, str) and value.strip().lower() == 'auto':
            return 0
        return value

    # ── Provider discovery, custom runtimes, and context economy ─────────────
    model_registry_ttl_hours: int = 24
    # Discovery is a preflight step; it must not consume the full generation timeout.
    discovery_timeout_seconds: int = 8
    provider_timeout_seconds: int = 60
    routing_max_attempts: int = 2
    custom_runtime_max_concurrency: int = 2
    custom_runtime_timeout_seconds: int = 120
    custom_runtime_max_output_mb: int = 10
    custom_runtime_max_temp_mb: int = 100
    context_max_tokens: int = 12000
    context_compression_enabled: bool = True
    context_metrics_enabled: bool = True

    # ── Cache & memory ───────────────────────────────────────────────────────
    cache_enabled: bool = True
    semantic_cache_enabled: bool = False
    memory_enabled: bool = True
    experience_logging: bool = True
    auto_background_tasks: bool = False
    database_path: str = 'data/database/agent.db'

    # ── Skills and evolution ─────────────────────────────────────────────────
    basic_skills_enabled: bool = True
    basic_skills_dir: str = ''
    basic_skills_allowlist: str = 'm0,m1,m2,m3,m4,m5,m6,m7,m8,m9,m11,m12,x1,x2,x3'
    skill_registry_path: str = 'data/database/skills.db'
    evolution_enabled: bool = True
    evolution_min_confidence: float = .80
    evolution_require_verification: bool = True

    # ── Storage budgets ──────────────────────────────────────────────────────
    max_total_storage_gb: int = 30
    warning_storage_gb: int = 25
    critical_storage_gb: int = 28
    raw_retention_days: int = 30
    cache_default_ttl_hours: int = 168
    log_retention_days: int = 14
    debug_log_retention_days: int = 7
    archive_retention_days: int = 365
    min_memory_score: float = .80
    semantic_duplicate_threshold: float = .92
    storage_warning_percent: int = 75
    storage_critical_percent: int = 90
    max_cache_gb: int = 3
    max_raw_gb: int = 5
    max_log_gb: int = 1
    max_archive_gb: int = 10
    max_embedding_gb: int = 5

    # ── Collective learning and verified updates ─────────────────────────────
    collective_learning_enabled: bool = False
    collective_consent_skills: bool = False
    collective_consent_knowledge: bool = False
    collective_consent_routing: bool = False
    collective_consent_evaluation: bool = False
    collective_registry_url: str = ''
    update_manifest_url: str = ''
    update_channel: str = 'stable'

    # ── Routing and bounded agent execution ──────────────────────────────────
    routing_mode: str = 'AUTO'
    cloud_fallback: bool = True
    cost_optimization: bool = True
    max_repair_attempts: int = 1
    adaptive_routing: bool = True
    max_agent_iterations: int = 12
    max_agent_tool_calls: int = 30
    agent_timeout_seconds: int = 300

    @property
    def database_file(self) -> Path:
        return ROOT / self.database_path

    @property
    def local_model_file(self) -> Path:
        if self.active_local_model_profile.model_file_path:
            return Path(self.active_local_model_profile.model_file_path).expanduser().resolve()
        configured = Path(self.local_model_path).expanduser()
        return configured.resolve() if configured.is_absolute() else (ROOT / configured).resolve()

    @property
    def local_model_registry_file(self) -> Path:
        configured = Path(self.local_model_registry_path).expanduser()
        return configured.resolve() if configured.is_absolute() else (ROOT / configured).resolve()

    @property
    def local_model_package_dir(self) -> Path:
        configured = Path(self.local_model_package_path).expanduser()
        return configured.resolve() if configured.is_absolute() else (ROOT / configured).resolve()

    @property
    def skill_registry_file(self) -> Path:
        configured = Path(self.skill_registry_path).expanduser()
        return configured.resolve() if configured.is_absolute() else (ROOT / configured).resolve()

    @property
    def allowed_basic_skills(self) -> set[str]:
        return {item.strip().lower() for item in self.basic_skills_allowlist.split(',') if item.strip()}

# Phase 19: ``ZEVORA_``-prefixed aliases for every documented variable.
# Existing unprefixed names keep working; an explicitly set unprefixed value
# always wins over its ``ZEVORA_`` alias so current deployments never break.
_ZEVORA_ENV_ALIASES = {
    'ZEVORA_LOCAL_MODEL_ENABLED': 'LOCAL_MODEL_ENABLED',
    'ZEVORA_LOCAL_MODEL_RUNTIME': 'LOCAL_MODEL_RUNTIME',
    'ZEVORA_LOCAL_MODEL_REPOSITORY': 'LOCAL_MODEL_REPOSITORY',
    'ZEVORA_LOCAL_MODEL_FILENAME': 'LOCAL_MODEL_FILENAME',
    'ZEVORA_LOCAL_MODEL_QUANT': 'LOCAL_MODEL_QUANT',
    'ZEVORA_LOCAL_MODEL_NAME': 'LOCAL_MODEL_NAME',
    'ZEVORA_LOCAL_MODEL_DISPLAY_NAME': 'LOCAL_MODEL_DISPLAY_NAME',
    'ZEVORA_LOCAL_MODEL_PATH': 'LOCAL_MODEL_PATH',
    'ZEVORA_LOCAL_MODEL_CONTEXT_LENGTH': 'LOCAL_MODEL_CONTEXT_LENGTH',
    'ZEVORA_LOCAL_MODEL_MAX_TOKENS': 'LOCAL_MODEL_MAX_TOKENS',
    'ZEVORA_LOCAL_MODEL_GPU_LAYERS': 'LOCAL_MODEL_GPU_LAYERS',
    'ZEVORA_LOCAL_MODEL_BATCH_SIZE': 'LOCAL_MODEL_BATCH_SIZE',
    'ZEVORA_LOCAL_MODEL_TEMPERATURE': 'LOCAL_MODEL_TEMPERATURE',
    'ZEVORA_REMOTE_LOCAL_ENABLED': 'REMOTE_LOCAL_ENABLED',
    'ZEVORA_REMOTE_LOCAL_BASE_URL': 'REMOTE_LOCAL_BASE_URL',
    'ZEVORA_REMOTE_LOCAL_API_KEY': 'REMOTE_LOCAL_API_KEY',
    'ZEVORA_REMOTE_LOCAL_MODEL': 'REMOTE_LOCAL_MODEL',
    'ZEVORA_REMOTE_LOCAL_TIMEOUT_SECONDS': 'REMOTE_LOCAL_TIMEOUT_SECONDS',
}


def _apply_zevora_env_aliases() -> None:
    for prefixed, plain in _ZEVORA_ENV_ALIASES.items():
        if prefixed in os.environ and plain not in os.environ:
            os.environ[plain] = os.environ[prefixed]


def _load_settings() -> Settings:
    _apply_zevora_env_aliases()
    loaded = Settings()
    ui_file = ROOT / 'config' / 'ui_settings.json'
    try:
        overrides = json.loads(ui_file.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        overrides = {}
    for name in ('routing_mode', 'cloud_fallback', 'cost_optimization'):
        if name in overrides:
            setattr(loaded, name, overrides[name])
    return loaded


settings = _load_settings()


def reload_settings() -> Settings:
    """Reload .env and persisted UI settings without restarting the gateway."""
    _apply_zevora_env_aliases()
    refreshed = _load_settings()
    for name in type(refreshed).model_fields:
        setattr(settings, name, getattr(refreshed, name))
    return settings
