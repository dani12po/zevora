import json
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent

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
    local_model_enabled: bool = True
    local_provider_id: str = 'local'
    local_model_runtime: str = 'llamacpp'
    local_endpoint_url: str = 'http://127.0.0.1:11434'
    local_endpoint_api_key: str = ''
    local_endpoint_timeout_seconds: int = 30
    local_model_path: str = 'models/zevora-4b-thinking.gguf'
    local_model_name: str = 'zevora'
    local_model_package_path: str = 'data/models/zevora-local'
    local_model_external_path: str = ''
    local_model_registry_path: str = 'data/database/model_registry.db'
    local_model_context_length: int = 8192
    local_model_max_tokens: int = 1024
    local_model_threads: int = 0
    local_model_gpu_layers: int = 0
    local_model_temperature: float = .6

    # ── Provider discovery, custom runtimes, and context economy ─────────────
    model_registry_ttl_hours: int = 24
    provider_timeout_seconds: int = 60
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
    basic_skills_dir: str = r'E:\SUPERAGENT-v3-OPENCLAW-HERMES\openclaw\skills'
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

def _load_settings() -> Settings:
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
    refreshed = _load_settings()
    for name in type(refreshed).model_fields:
        setattr(settings, name, getattr(refreshed, name))
    return settings
