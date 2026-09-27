# Adolf-StreamX Dynamic Commands — Step 15

This release adds admin-managed dynamic Main Bot commands without overriding existing hard-coded commands.

## Files added/changed

- `security/command_repository.py` — Neon/PostgreSQL repository + audit storage.
- `security/commands/dynamic.py` — `/cmdadd`, `/cmded`, `/cmddel`, `/cmdlist`.
- `security/command_migration.py` — explicit, manual production schema migration.
- `security/commands/__init__.py` — registers the new admin handlers.
- `security_bot.py` — keeps existing startup and V3 lifecycle; no automatic schema mutation.
- `main/updatedserver.py` — dynamic fallback after reserved hard-coded commands.

## Production migration

Do this once, deliberately, with the production `DATABASE_URL`:

`python -m security.command_migration`

Normal bot startup does **not** create or alter the dynamic-command tables.

## Security behavior

- Security Bot command management is owner/admin-only.
- Command names are normalized to lowercase `a-z`, `0-9`, `_`, 1–32 chars.
- `/cmddel` disables a row instead of deleting it.
- Existing Main Bot `/start` and `/stats` remain hard-coded and win over dynamic entries.
- Dynamic responses are limited to Telegram's 4096-character message limit.
- Button URLs, when stored through the repository, are restricted to `http(s)` or `tg://`.
- Database failures are logged and fail closed; they do not crash the bot command handler.
- Audit records contain action, actor, command, success and bounded details; secrets are not logged.

## Admin usage

- `/cmdadd help` → bot asks for the response.
- `/cmded help` → bot asks for the replacement response.
- `/cmddel help` → disables the dynamic / multi-page command.
- `/cmdlist` → lists dynamic / multi-page commands and status.
- `/cancel` → cancels a pending add/edit action.


### Multi-page dynamic commands
`security/commands/dynamic.py` is the audited multi-page version. It supports /cmdadd, /cmded, /cmddel, /cmdlist, optional buttons, and up to 20 draft pages. Run the explicit migration only when you intentionally want to create the Neon command tables.

## Service monitor /check

Optional environment variables:
- `SERVICE_MONITOR_INTERVAL` (default 60 seconds)
- `SERVICE_MONITOR_TIMEOUT` (default 10 seconds)
- `MONITOR_JUSTRUNMY_WEB_URL` (default Adolf-StreamX `/health` URL)
- `MONITOR_RAMNAYMCLOUD_URL` (default RamNaymCloud `/health` URL)
- `MONITOR_JRM_SECURITY_END_AT` (optional ISO-8601 end timestamp)
- `MONITOR_JRM_WEB_END_AT` (optional ISO-8601 end timestamp)
- `MONITOR_RAMNAYMCLOUD_END_AT` (optional ISO-8601 end timestamp)

`/check` is owner-only and reports all three services. The monitor sends a notification only when an external service changes state, preventing repeated spam. The security bot reports its own clean startup/shutdown, but an unexpected hard kill cannot be detected by the same process; that requires an external watchdog.
