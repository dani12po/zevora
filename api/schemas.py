"""Pydantic request models for the ZEVORA gateway API."""
from pydantic import BaseModel, Field

from agent.core.persona import ZEVORA_PERSONA

class AttachmentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    media_type: str = Field(min_length=1, max_length=100)
    data_base64: str = Field(min_length=1, max_length=14_000_000)

class AgentActionRequest(BaseModel):
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict = Field(default_factory=dict)
    approved: bool = False
    purpose: str = Field(default='', max_length=500)

class TaskRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    progress_id: str | None = Field(default=None, max_length=80)
    project: str | None = Field(default=None, max_length=4096)
    system: str = Field(
        default=ZEVORA_PERSONA, max_length=20_000
    )
    mode: str = Field(default='auto', max_length=32)
    # See ChatMessageRequest.chat_mode: ask disables workspace planning and
    # execution for this task, coding forces it, auto classifies per prompt.
    chat_mode: str = Field(default='auto', max_length=16)
    provider: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=255)
    actions: list[AgentActionRequest] = Field(default_factory=list, max_length=30)
    attachments: list[AttachmentRequest] = Field(default_factory=list, max_length=8)
class PlanRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    project_id: int = Field(gt=0)
class MCPToolUpdateRequest(BaseModel):
    enabled: bool
class TerminalSessionRequest(BaseModel):
    project_id: int = Field(gt=0)
    command: str = Field(min_length=1, max_length=4096)
    cwd: str = Field(default='', max_length=4096)
    timeout: int = Field(default=120, ge=1, le=600)
    approved: bool = False
class FileWriteRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    content: str = Field(max_length=2_000_000)
class IndexRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1,max_length=120)
    approved: bool = False
class ProjectLoadRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
class SettingsUpdateRequest(BaseModel):
    routing_mode: str | None = None
    cloud_fallback: bool | None = None
    cost_optimization: bool | None = None
class ChatCreateRequest(BaseModel):
    title: str = Field(default='New chat', min_length=1, max_length=120)
    project_id: int | None = Field(default=None, gt=0)
class ChatMessageRequest(BaseModel):
    content: str = Field(min_length=1,max_length=20000)
    progress_id: str | None = Field(default=None, max_length=80)
    mode: str = Field(default='auto', max_length=32)
    # Conversation intent, independent from the routing override above:
    # ask = pure Q&A (never plans or executes workspace actions),
    # coding = force the workspace agent flow, auto = classify per message.
    chat_mode: str = Field(default='auto', max_length=16)
    provider: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=255)
    attachments: list[AttachmentRequest] = Field(default_factory=list, max_length=8)
    actions: list[AgentActionRequest] = Field(default_factory=list, max_length=30)
class ChatRequest(BaseModel):
    message: str = Field(min_length=1,max_length=20000)
    request_id: str | None = Field(default=None, max_length=80)
    conversation_id: str | None = Field(default=None, max_length=128)
    project_id: int | None = Field(default=None, gt=0)
    project_context: str | None = Field(default=None, max_length=20_000)
    mode: str = Field(default='auto', max_length=32)
    provider: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=255)
    attachments: list[AttachmentRequest] = Field(default_factory=list, max_length=8)
    actions: list[AgentActionRequest] = Field(default_factory=list, max_length=30)
class ChatRenameRequest(BaseModel): title: str = Field(min_length=1, max_length=120)
class ChatFeedbackRequest(BaseModel):
    rating: str | None = Field(default=None, pattern='^(up|down)$')
class ApprovalRequest(BaseModel):
    approved: bool = False
class ProviderConfigRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=80)
    api_key: str | None = Field(default=None, max_length=4096)
    base_url: str | None = Field(default=None, max_length=2048)
    default_model: str | None = Field(default=None, max_length=255)
    enabled: bool | None = None
    routing_priority: int | None = Field(default=None, ge=0, le=100)
    supports_vision: bool | None = None
class ProviderManifestRequest(BaseModel):
    manifest: dict
    credential_value: str | None = Field(default=None, max_length=4096)
    script: str | None = Field(default=None, max_length=524288)
class ProviderAnalysisRequest(BaseModel):
    source: str = Field(min_length=1, max_length=524288)
    language: str = Field(default='auto', max_length=32)
class ProviderTestRequest(BaseModel):
    runtime_approved: bool = False
class ProviderTrustRequest(BaseModel):
    approved: bool = False
class ProviderEnabledRequest(BaseModel):
    enabled: bool
class ProviderExampleRequest(BaseModel):
    language: str = Field(default='python', max_length=32)


class LocalModelInstallRequest(BaseModel):
    approved: bool = False
    replace: bool = False
    repository: str | None = None
    filename: str | None = None
