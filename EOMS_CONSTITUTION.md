# EOMS Constitution

## Project Identity

Essayons Operations Management System (EOMS) is a logistics operations platform for RMS automation, dispatch, warehouse coordination, fleet visibility, operational exceptions, communications, analytics, and AI-assisted decision support.

EOMS exists to strengthen operational control without removing operator judgment. Automation should surface facts, reduce repetitive work, and make exceptions visible. Operators remain the final decision-makers.

## AI Roles

- Xavier: Product Owner & Founder
- ChatGPT: Chief Architect & Technical Lead
- Codex: Senior Software Engineer / Code Reviewer

## Development Workflow

- One mission at a time.
- Entire file replacements only.
- Compile after every mission.
- Runtime test before commit.
- Local commits first.
- GitHub push only after stable milestones.

## Architecture Rules

- `stores.json` is the single source of truth.
- No duplicate databases.
- Operational exceptions are filtered views, not separate storage.
- Business workflow and operational exceptions are separate domains.
- Infrastructure first, features second.
- Automation informs, operators decide.
- Preserve existing functionality unless intentionally changing it.

## FT3.3 Safety Rules

- No stale writes to `stores.json`.
- Worker failures must be marked `FAILED`.
- Queue writes must be locked and atomic.
- Long-running automation should not be treated as normal UI work.
- Executable worker actions must be allowlisted.
- User input must be validated with controlled errors.
