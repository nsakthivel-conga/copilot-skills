# .github/copilot-instructions.md

The AI skills for this project are located in a sibling repository named `copilot-skills`.

1. To understand what skills are available and what their folder names are, you MUST first read the skill index by executing:
   `Get-Content -Path "$((Get-Item (git rev-parse --show-toplevel)).Parent.FullName)\copilot-skills\COPILOT_SKILLS.md" -Raw`

2. Once you know the correct `<skill-folder>` for the user's request, you MUST read the detailed instructions for that skill by executing:
   `Get-Content -Path "$((Get-Item (git rev-parse --show-toplevel)).Parent.FullName)\copilot-skills\<skill-folder>\SKILL.md" -Raw`

Do exactly what the detailed SKILL.md output says, and do not make assumptions.
