"""Read-only, bounded adapter for the operator's OpenClaw skill pack."""
from dataclasses import dataclass
from pathlib import Path
import re
from ..config import settings

@dataclass(frozen=True)
class SkillMatch:
    skill_id: str
    score: int

# Mirrors the supplied registry's intent vocabulary; skill bodies remain external/on-demand.
KEYWORDS = {
    'm1': ('monetize pricing jual jualan cuan business income funnel sell', 3),
    'm2': ('vps deploy ssh nginx docker systemd server linux bash sysadmin', 3),
    'm3': ('viral hook caption thread naskah content post copywriting konten', 3),
    'm4': ('telegram bot cron webhook n8n automate otomatis schedule jadwal', 3),
    'm5': ('spreadsheet excel csv dataset snapshot data analytics report laporan', 3),
    'm6': ('api rest webhook midtrans integrasi endpoint sdk integration', 3),
    'm7': ('llm prompt claude api openrouter kimi ai agent model gpt inference', 3),
    'm8': ('pdf docx xlsx pptx generate file export dokumen format save', 3),
    'm9': ('landing page react tailwind frontend website ui html css web design', 3),
    'm11': ('audit vulnerability exploit scam check security review safe malicious verify', 3),
    'm12': ('batch parallel bulk mass queue worker concurrent throughput snapshot', 3),
    'x1': ('improve system self-audit refactor brain audit me review agent upgrade self optimize', 3),
    'x2': ('strategy architecture decompose plan complex multi-step design system think', 3),
    'x3': ('error bug debug gagal rusak stack failed broken fix crash traceback issue', 3),
}
# Bound injected guidance so cloud prompts remain cost-aware.
MAX_SKILL_CHARS = 5_000
MAX_TOTAL_SKILL_CHARS = 8_000

class OpenClawSkillSource:
    def __init__(self, directory: str | Path | None = None):
        self.directory = Path(directory or settings.basic_skills_dir)
    def route(self, prompt: str) -> list[SkillMatch]:
        words = re.findall(r"[\w-]+", prompt.lower())
        matches=[]
        for skill_id, (terms, weight) in KEYWORDS.items():
            if skill_id not in settings.allowed_basic_skills: continue
            score=sum(weight for term in terms.split() if term in words)
            if score: matches.append(SkillMatch(skill_id, score))
        matches.sort(key=lambda item: item.score, reverse=True)
        if not matches: return []
        primary=matches[0]
        return [m for m in matches if m.score >= primary.score * .5][:2]
    def load(self, match: SkillMatch) -> str:
        if not settings.basic_skills_enabled or match.skill_id not in settings.allowed_basic_skills: return ''
        path=(self.directory / f'{match.skill_id}.md').resolve()
        # The resolver and parent check prevent a crafted skill id escaping this source directory.
        try:
            if path.parent != self.directory.resolve() or not path.is_file(): return ''
            return path.read_text(encoding='utf-8')[:MAX_SKILL_CHARS]
        except OSError: return ''
    def context_for(self, prompt: str) -> tuple[str, list[str]]:
        matches=self.route(prompt)
        chunks=[]; used=[]; remaining=MAX_TOTAL_SKILL_CHARS
        for match in matches:
            chunk=self.load(match)[:remaining]
            if chunk:
                chunks.append(chunk); used.append(match.skill_id); remaining -= len(chunk)
            if remaining <= 0: break
        if not chunks: return '', []
        return '\n\n--- APPROVED ON-DEMAND SKILL ---\n'.join(chunks)[:MAX_TOTAL_SKILL_CHARS], used
