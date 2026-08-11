# Veyra

Veyra is a production-grade Discord bot designed exclusively for the **Veylora** community.

## Current Status
**Phase 6: Verification & Member Gate System** (Completed)
Phase 6 introduces a fully persistent and asynchronous member verification system:
- **Member Gate:** Automatically applies the Unverified role on join when enabled, locking members into a gated view.
- **Discord-Native Persistent UI:** Reusable, stateless persistent views that survive bot reboots and DisCloud deployments.
- **Idempotency & Resilience:** Role manipulations are resistant to rate limits, missing permissions, and duplicate inputs.
- **Auto-Setup Integration:** Intelligently discovers structures provisioned by Phase 4 and repairs natively.

**Phase 5.6: Production Foundation Hardening & Pre-Phase-6 Audit** (Completed)
Phase 5.6 hardens the codebase for production:
- **Database Safety:** Added `backup()` method using safe native SQLite WAL backup API.
- **Embed Formatting:** Standardized truncation logic ensuring text fits safely within Discord's strict length constraints.
- **Error Handlers:** Verified proper fallback logic removing sensitive tracebacks in user responses.
- **Logging:** Synchronized timestamps to timezone-aware strings.
- **Dependency Checks:** Re-verified async task stability and non-blocking I/O.

**Phase 5: Permissions, RBAC & Hierarchy Security** (Implemented)
Phase 5 implements a robust Role-Based Access Control (RBAC) system deeply integrated with Discord's native security:
- **Comprehensive RBAC:** Hierarchical authorization mapping (Levels 0-9) covering Founder, Owner, Staff, and Members.
- **Strict Role Protections:** Command execution checks prevent targeting users with higher Veyra rank or Discord role position.
- **Fail-Closed Design:** Actions are rejected by default if permission mappings or users cannot be reliably verified.
- **In-Memory Caching:** Database role mapping is cached efficiently and cleared on auto-setup and auto-repair.
- **Discord Parity Checks:** Enforces that the bot actually holds necessary native permissions before executing tasks.

**Phase 4: Veylora Auto-Setup & Auto-Repair System** (Implemented)
Phase 4 implements the automated community scaffolding commands:
- **Idempotent Operations:** Setup only creates missing objects, avoiding duplicate channels/roles.
- **Auto Repair:** `/auto repair` safely reinstates manually deleted structures without resetting unaffected custom configurations.
- **State Management:** Setup locks and transactional state machine (NOT_STARTED, IN_PROGRESS, PARTIAL, COMPLETE) protect the guild baseline.
- **Permission Safety:** Bot operations apply bitwise constraints against its actual Discord permissions so it never attempts to over-grant.
- **Auto Status:** `/auto status` reports missing objects directly from the `server_layout` registry.

**Not Yet Implemented (Future Phases):**
- Veyra Shield behavior
- Tickets
- Minecraft fetching
- Gemini AI
- Analytics processing
- Persistent Scheduler
- Backups

## Technical Stack
- **Language:** Python 3.12+
- **Library:** discord.py 2.x
- **Database:** SQLite (aiosqlite)
- **Deployment Target:** DisCloud (Root-level architecture)

## Installation & Setup

1. **Clone the repository**
2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Configure Environment Variables:**
   Rename `.env.example` to `.env` and fill in the required values:
   - `DISCORD_TOKEN`: Your Discord bot token.
   - `APPLICATION_ID`: Your Discord application client ID.
   - `FOUNDER_ID`: Your personal Discord User ID.
4. **Discord Developer Portal Intents:**
   - **Message Content:** **DISABLED** (Do not enable for Phase 1)
   - **Server Members:** Enabled
   - **Presence Intent:** **DISABLED** (Do not enable)

## Running Locally

```bash
pip install -r requirements.txt

python main.py
```

## DisCloud Deployment
This project is structured specifically for DisCloud deployment without nested subdirectories.
1. Zip the root contents (excluding `.env`, virtual environments, etc.)
2. Ensure `discloud.config` is included.
3. Upload to DisCloud.

## Current Commands
- `/system-status`: Displays Veyra system diagnostics and status.
- `/auto setup`: Run the Veylora Auto-Setup process (Requires Manager+).
- `/auto repair`: Repair missing or broken Veylora server structures (Requires Manager+).
- `/auto status`: Check the status of the Veylora server structure (Requires Manager+).
- `/verification setup`: Configure or repair the verification system using Auto-Setup infrastructure (Requires Manager+).
- `/verification panel`: Post the verification UI button to the configured channel (Requires Manager+).
- `/verification status`: Show the status of the Verification module (Requires Manager+).
