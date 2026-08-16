from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

@dataclass
class ModelMetadata:
    provider: str; model_id: str; display_name: str = ''
    capabilities: list[str] = field(default_factory=list)
    capability_profile: dict = field(default_factory=dict)
    context_window: int | None = None; max_output_tokens: int | None = None
    supports_streaming: bool | None = None; supports_tools: bool | None = None
    supports_vision: bool | None = None; supports_reasoning: bool | None = None; supports_code: bool | None = None
    supports_json: bool | None = None; supports_embeddings: bool | None = None
    input_price: float | None = None; output_price: float | None = None
    availability: str = 'unknown'; health_status: str = 'unknown'; last_verified: str = field(default_factory=lambda:datetime.now(timezone.utc).isoformat())
    def to_dict(self): return asdict(self)
