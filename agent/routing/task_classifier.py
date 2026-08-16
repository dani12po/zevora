from dataclasses import dataclass
from ..models import capabilities as cap

@dataclass(frozen=True)
class ClassifiedTask:
    labels:list[str]; required_capabilities:list[str]; complexity_score:float; requires_tools:list[str]
class TaskClassifier:
    def classify(self,prompt):
        text=prompt.lower(); labels=[]; required=[]; tools=[]; complexity=.08 + min(.25,len(text)/8000)
        rules=[(('debug','error','bug'),('debugging',[cap.CODING,cap.REASONING])),(('code','typescript','python','refactor'),('coding',[cap.CODING])),(('image','vision','screenshot'),('vision',[cap.VISION])),(('research','latest','search web'),('research',[cap.GENERAL])),(('reason','architecture','complex'),('reasoning',[cap.REASONING])),(('summar','ringkas'),('summarization',[cap.GENERAL])),(('tool','terminal','file'),('tool_task',[cap.GENERAL]))]
        for words,(label,caps) in rules:
            if any(word in text for word in words): labels.append(label); required.extend(caps); complexity+=.12
        if any(word in text for word in ('file','folder','project','repository','repo')): tools.append('filesystem.read')
        if any(word in text for word in ('run test','terminal','command','install package')): tools.append('terminal.execute')
        if any(word in text for word in ('git ','commit','diff')): tools.append('git.status')
        if any(word in text for word in ('create project','buat project','buatkan project')): tools.append('project.create')
        if any(word in text for word in ('architecture','migration strategy','entire project','seluruh project','refactor seluruh')): complexity+=.32
        if len(labels)>1: complexity+=.1
        return ClassifiedTask(labels or ['general_chat'],list(dict.fromkeys(required or [cap.GENERAL])),min(round(complexity,2),1.0),list(dict.fromkeys(tools)))
