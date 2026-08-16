"""Legacy task-type classifier kept for backwards compatibility.

New code should use agent.routing.task_classifier.TaskClassifier directly,
which returns a richer ClassifiedTask with capability tags and tool hints.
"""
from enum import Enum
from ..config import settings


class TaskType(str, Enum):
    SIMPLE = 'simple'
    CODING = 'coding'
    DEBUGGING = 'debugging'
    REASONING = 'reasoning'
    RESEARCH = 'research'
    SUMMARIZATION = 'summarization'
    FILE_OPERATION = 'file_operation'
    AUTOMATION = 'automation'
    COMPLEX_AGENT_TASK = 'complex_agent_task'


class ModelRouter:
    """Keyword-based task classifier.

    Note: provider/model selection is handled by AdaptiveHybridRouter.
    This class is only used to attach a TaskType label to usage_events.
    """

    def classify(self, prompt: str) -> TaskType:
        p = prompt.lower()
        if any(x in p for x in ('debug', 'error', 'bug')):
            return TaskType.DEBUGGING
        if any(x in p for x in ('code', 'function', 'class ', 'python', 'javascript')):
            return TaskType.CODING
        if any(x in p for x in ('research', 'compare', 'latest', 'web ')):
            return TaskType.RESEARCH
        if any(x in p for x in ('summar', 'ringkas')):
            return TaskType.SUMMARIZATION
        if len(p) > 900 or any(x in p for x in ('analyze deeply', 'step-by-step reasoning')):
            return TaskType.REASONING
        return TaskType.SIMPLE
