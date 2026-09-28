# Project rules

## Jira sync (Dj, 2026-09-28)

- Every story change is mirrored in Jira project **OCR** (`https://example.atlassian.net/`) in the same session. That covers adding, editing, splitting, moving or removing a story or its subtasks in `_bmad-output/planning-artifacts/epics.md` (or any story file), and a story's status changing during a build.
- Update the matching issue's summary, description, acceptance criteria and subtasks. Create an issue for a new story, and never leave an orphan.
- Match issues by summary prefix: epics are `Epic <n>: …`, stories `<n.m> …`, subtasks `<n.m> <area>: …`.
- Report the Jira keys you touched. If Jira can't be reached, say so and list the pending updates. Never skip them silently.
