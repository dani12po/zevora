from dataclasses import dataclass

@dataclass(frozen=True)
class Selection: provider:str; model_id:str; score:float; reason:str
class ModelSelector:
    def select(self,models,required):
        candidates=[]
        for model in models:
            if model.get('availability')!='verified' or model.get('health_status')!='healthy': continue
            caps=set(model.get('capabilities',[]))
            if not set(required).issubset(caps): continue
            score=len(set(required)&caps)*100
            candidates.append((score,model))
        if not candidates: return None
        score,model=max(candidates,key=lambda item:item[0]); return Selection(model['provider'],model['model_id'],score,'capability match and verified health')
