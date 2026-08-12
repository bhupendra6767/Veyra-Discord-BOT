# VEYRA PROJECT — STRICT DEVELOPMENT CONTRACT

## PROJECT IDENTITY
This is Veyra, a premium Minecraft-focused Discord community bot.

## NON-NEGOTIABLE ARCHITECTURE
- Python 3.12+
- discord.py 2.x
- SQLite + aiosqlite
- python-dotenv
- Flat root-level architecture
- DisCloud deployment
- discloud.config must remain valid
- No Node.js
- No package.json
- No web server
- No Flask
- No FastAPI
- No aiohttp unless an existing production requirement explicitly requires it
- No dashboards
- No subdirectories unless explicitly approved
- No unnecessary dependencies

## EXISTING SYSTEM
Do NOT rewrite existing phases.

Existing completed systems include:
- Foundation
- Core infrastructure
- Security/RBAC
- Auto Setup
- Verification
- Tickets
- Community Automation
- Analytics
- Premium Minecraft presentation/media
- Content Intelligence foundation

## CHANGE CONTROL
When a task specifies a file:

1. Modify ONLY that file.
2. Do NOT modify any other file.
3. Do NOT create new files.
4. Do NOT delete files.
5. Do NOT rename files.
6. Do NOT change dependencies.
7. Do NOT change database schema.
8. Do NOT refactor unrelated code.
9. Do NOT "clean up" unrelated code.
10. Do NOT introduce new architecture.

You may READ another file ONLY when absolutely necessary to understand an import, function signature, database API, or integration contract.

Reading another file does NOT authorize modifying it.

## BEFORE EDITING
First inspect the target file and identify the smallest required change.

Do not begin implementation until the scope is understood.

## AFTER EDITING
Run appropriate syntax/tests.

Then report:
- exact file modified
- exact functions/classes changed
- tests executed
- whether any other file was modified

If the requested feature cannot be implemented safely within the specified file, STOP and explain why instead of modifying another file.

## UI STANDARD
Every Discord UI must look premium, polished, Minecraft-themed, concise, and consistent with the existing VeyraEmbed system.

Do not replace the existing design system.

## SAFETY
Never expose secrets, tokens, API keys, or .env values.

Never modify deployment configuration unless explicitly requested.

## GIT SAFETY
Never force-push.
Never reset the repository.
Never delete existing working code to simplify an implementation.

Prefer a separate branch for every development phase.
