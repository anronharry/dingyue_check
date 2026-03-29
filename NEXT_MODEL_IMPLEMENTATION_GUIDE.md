# Next Model Implementation Guide

## Goal

This document defines the required enhancement work for this Telegram subscription bot project. The next model should treat this as an implementation contract, not as optional brainstorming.

Primary objectives:

1. Improve owner-side visibility of who is using the bot.
2. Make operation logs pageable and focused on non-owner users by default.
3. Change subscription result messages to "detailed first, compact later".
4. Cache exportable node results for limited-use subscription links and other parsed artifacts for up to 48 hours.
5. Provide full backup and restore so server migration is transparent to users.
6. Perform local self-checks after modification to reduce broken integration points.

Do not perform a broad rewrite. Extend the current architecture incrementally.

---

## Non-Negotiable Principles

1. Preserve the current layered structure.
   Keep work aligned with the existing `handlers/`, `services/`, `core/`, `renderers/`, `features/`, `jobs/` split.

2. Avoid destructive refactors.
   Do not collapse the app back into `bot_async.py`. New behavior should be introduced through services, renderers, jobs, and focused handler changes.

3. Respect current ownership and authorization behavior.
   New features must not weaken existing owner-only or authorized-user-only access checks.

4. Prefer backward-compatible persistence changes.
   If new JSON files are introduced, load missing files gracefully and avoid breaking existing deployments.

5. Every user-facing change must be testable.
   Do not ship new flows without adding or updating tests.

6. Every new persistence feature must have cleanup or recovery logic.
   Cached exports require expiry cleanup. Backup/restore requires startup-safe restore behavior.

7. Self-check before finishing.
   Run compile/import/tests and at least a minimal local integration pass.

---

## Current Project Reality

The project is already partially refactored:

- `main.py` is a thin entrypoint into `bot_async.py`
- `bot_async.py` assembles the app and wires handlers/services
- `app/bootstrap.py` builds the PTB application and registers handlers
- `services/` contains business workflows
- `handlers/` contains command/message/callback factories
- `core/` contains parser/storage/workspace/access primitives
- `features/monitor.py` contains periodic subscription monitoring

Current limitations relevant to this task:

1. Authorized users are stored mostly as raw IDs.
2. Owner-facing user list and usage audit are not suitable for large user sets.
3. Subscription result messages are verbose and persistent.
4. Parsed subscriptions are not cached as reusable export artifacts for later delivery.
5. Existing `/export` and `/import` are subscription-centric, not full-state migration tools.

---

## Required Feature Set

### 1. Owner-Friendly User Identity Display

#### Problem

The owner currently sees mostly raw numeric IDs. This is operationally poor.

#### Required behavior

1. Whenever a user interacts with the bot, record a lightweight user profile.
2. Owner-facing views should display:
   - clickable user mention when possible
   - readable username or full name
   - numeric Telegram ID in parentheses
3. Never remove the numeric ID from owner views.

#### Telegram constraints

The bot cannot magically inspect arbitrary Telegram users outside interaction context. It can only reliably use data from users who have interacted with the bot. Design around that.

#### Recommended implementation

Add a new persistence-backed profile service.

Suggested file:

- `services/user_profile_service.py`

Suggested storage:

- `data/db/user_profiles.json`

Suggested fields:

```json
{
  "123456789": {
    "user_id": 123456789,
    "username": "alice",
    "full_name": "Alice Zhang",
    "first_seen_at": "2026-03-29 18:00:00",
    "last_seen_at": "2026-03-29 18:33:21",
    "last_source": "/check",
    "is_owner": false,
    "is_authorized": true
  }
}
```

Suggested display format:

```html
<a href="tg://user?id=123456789">@alice</a> (<code>123456789</code>)
```

Fallback order:

1. `@username`
2. `full_name`
3. raw ID only

#### Integration points

Refresh profile on all interaction entrypoints:

- command handlers
- text message handlers
- document handlers
- callback handlers

Likely files needing integration:

- `bot_async.py`
- `handlers/commands/*.py`
- `handlers/messages/*.py`
- `handlers/callbacks/*.py`
- `services/admin_service.py`

#### Acceptance criteria

1. `/listusers` should not be raw-ID-only anymore.
2. Owner views should show readable user identity plus ID.
3. Profile files should be created automatically on first interaction.

---

### 2. Usage Audit Pagination and Better Owner-Focused Browsing

#### Problem

`/usageaudit` currently emits long blocks of text and is not scalable.

#### Required behavior

1. Usage audit must support pagination.
2. Default view must focus on non-owner users.
3. Owner-only view and all-users view should also be available.
4. Navigation must use inline buttons.

#### Recommended modes

- `others`
- `owner`
- `all`

#### Recommended page size

- 5 or 10 records per page

#### Recommended implementation

Extend `UsageAuditService` with query/filter/pagination support instead of only returning the last N lines.

Likely files:

- `services/usage_audit_service.py`
- `services/admin_service.py`
- `handlers/commands/admin.py`
- `handlers/callbacks/router.py`
- possibly a new callback module if cleaner

#### UX requirements

Each log entry should show concise metadata, not a wall of links.

Recommended per-entry display:

- timestamp
- user display name + ID
- source
- number of URLs
- first URL or truncated URL summary

Optional:

- "view details" button per record if you want deeper inspection

#### Acceptance criteria

1. `/usageaudit` defaults to non-owner users.
2. Inline buttons allow previous/next page.
3. Inline buttons allow switching `others/owner/all`.
4. Large logs remain readable.

---

### 3. Detailed Result First, Auto-Collapse to Compact Output

#### Problem

Current subscription output is too long and remains too long.

#### Required behavior

1. On successful subscription parsing, send a detailed result first.
2. After 20 seconds, edit that same message into a compact version.
3. Compact version must keep the action buttons.

#### Compact version should keep only

- subscription name
- remaining traffic
- expiration time or remaining days
- node count
- optionally tags

#### Compact version should remove or drastically reduce

- detailed geographic distribution
- detailed location list
- ISP-heavy output
- verbose breakdowns

#### Recommended implementation

Introduce explicit formatter split:

- verbose formatter
- compact formatter

Likely files:

- `renderers/formatters.py`
- or new `renderers/subscription_presenter.py`
- `handlers/messages/subscriptions.py`
- `handlers/messages/documents.py`
- `handlers/callbacks/subscription_actions.py`

#### Scheduling

Use `context.job_queue.run_once(...)`.
Do not block handlers with sleep.

#### Important note

Some current handlers discard `context`. That must be changed where auto-collapse is needed.

#### Acceptance criteria

1. Fresh parse response is detailed.
2. Around 20 seconds later the same message becomes compact.
3. If message edit fails due to deletion or invalid state, the bot should fail silently and continue.

---

### 4. Export Cache for Limited-Use Subscription Links and Parsed Artifacts

#### Problem

Some subscription links have limited read counts or short validity windows. The project currently stores summary metadata, not reusable export artifacts.

#### Required behavior

1. On first successful parse of a subscription link, immediately generate reusable export artifacts.
2. Cached artifacts must remain available for up to 48 hours.
3. Users must be able to export cached YAML or TXT later without re-fetching the original subscription URL.
4. Users must be able to delete their own cached artifacts.
5. Expired artifacts must be automatically cleaned up.
6. This cache concept should also cover conversion outputs from uploaded TXT/YAML and deep-check outputs where appropriate.

#### Critical architectural requirement

The parser currently returns summary data plus `_raw_nodes`, but caching reusable export artifacts is much more reliable if the parse result also exposes raw source content and source format.

Recommended parser additions in `core/parser.py`:

- `_raw_content`
- `_content_format`
- `_normalized_nodes`

#### Recommended storage

Suggested directory:

- `data/cache_exports/`

Suggested index file:

- `data/db/export_cache_index.json`

Suggested index entry:

```json
{
  "https://example.com/sub?a=1": {
    "owner_uid": 123456789,
    "created_at": "2026-03-29 18:00:00",
    "expires_at": "2026-03-31 18:00:00",
    "yaml_path": "data/cache_exports/123456789_abcd1234.yaml",
    "txt_path": "data/cache_exports/123456789_abcd1234.txt",
    "raw_snapshot_path": "data/cache_exports/123456789_abcd1234.raw",
    "last_exported_at": null
  }
}
```

#### Recommended service

Add:

- `services/export_cache_service.py`

Suggested responsibilities:

- save/update cached exports
- locate cached exports by owner + source key
- send/export cached files
- delete cached files
- cleanup expired entries

#### Keyboard changes

Current subscription keyboard is too limited.

Recommended additions:

- export YAML
- export TXT
- delete cache

Suggested affected file:

- `renderers/telegram_keyboards.py`

Suggested callback additions:

- `export_yaml`
- `export_txt`
- `delete_cache`

#### Cleanup

Add periodic cleanup for 48-hour expiry.

Likely files:

- `jobs/cache_cleanup_job.py`
- `bot_async.py`
- possibly `core/workspace_manager.py`

#### Acceptance criteria

1. User can parse a limited-use subscription once and still export YAML/TXT later.
2. Cache expires automatically after 48 hours.
3. Cache is owner-scoped or user-scoped properly.
4. Cache can be deleted manually by the owning user or owner.

---

### 5. Full Backup and Restore for Server Migration

#### Problem

The current export/import feature is not a complete migration story.

#### Required behavior

1. Owner must be able to export a full-state backup package.
2. Owner must be able to restore a full-state backup package.
3. On a fresh server, if a designated bootstrap restore package exists and current data is empty, the app should auto-restore at startup.
4. If current data already exists, startup auto-restore must not overwrite it.

#### Full-state backup must include

1. subscriptions
2. authorized users
3. access-state flags
4. user profiles
5. usage audit log
6. export cache index
7. optionally cached artifact files if feasible

#### Recommended service

Add:

- `services/backup_service.py`

Suggested responsibilities:

- create backup zip
- restore backup zip
- optional startup bootstrap restore

#### Recommended backup layout

Create a zip archive with a manifest.

Suggested path:

- `data/backups/backup_YYYYMMDD_HHMMSS.zip`

Suggested `manifest.json`:

```json
{
  "version": "2.0",
  "exported_at": "2026-03-29 19:00:00",
  "app": "dingyue_TG",
  "files": [
    "data/db/subscriptions.json",
    "data/db/users.json",
    "data/db/access_state.json",
    "data/db/user_profiles.json",
    "data/logs/usage_audit.jsonl",
    "data/db/export_cache_index.json"
  ]
}
```

#### Command recommendations

Add owner-only commands:

- `/backup`
- `/restore`

Keep existing `/export` and `/import` if desired, but treat them as legacy subscription-only tools, not full migration.

#### Startup bootstrap restore

Recommended behavior in startup flow:

1. Check a dedicated path such as `data/bootstrap_restore/latest_backup.zip`
2. Only auto-restore if current core state is empty
3. After success, archive or rename the bootstrap file to avoid repeated restores

Likely integration point:

- `bot_async.py`

#### Acceptance criteria

1. Full backup round-trip restores bot state.
2. Users remain authorized after migration.
3. Access mode and user profiles persist across migration.
4. Empty environment can bootstrap restore automatically.
5. Non-empty environment is not overwritten.

---

## Implementation Order

Do not implement in a random order. Recommended sequence:

1. User profile persistence and owner display enhancements
2. Usage audit pagination
3. Detailed-to-compact result flow
4. Export cache service and buttons
5. Full backup/restore
6. Cleanup jobs and startup restore integration
7. Tests and self-check

Reason:

- Steps 1 and 2 are lower-risk service/UI improvements
- Step 3 affects handler lifecycle and jobs
- Step 4 affects parser/output/storage/buttons/cleanup
- Step 5 affects persistence contracts and migration behavior

---

## Likely Files To Modify

High probability:

- `bot_async.py`
- `app/bootstrap.py`
- `renderers/telegram_keyboards.py`
- `renderers/formatters.py`
- `handlers/messages/subscriptions.py`
- `handlers/messages/documents.py`
- `handlers/commands/admin.py`
- `handlers/callbacks/subscription_actions.py`
- `handlers/callbacks/router.py`
- `services/admin_service.py`
- `services/usage_audit_service.py`
- `core/parser.py`
- `core/workspace_manager.py`
- `jobs/cache_cleanup_job.py`
- `features/monitor.py`

Recommended new files:

- `services/user_profile_service.py`
- `services/export_cache_service.py`
- `services/backup_service.py`
- `tests/test_user_profiles.py`
- `tests/test_usageaudit_paging.py`
- `tests/test_result_collapse.py`
- `tests/test_export_cache.py`
- `tests/test_backup_restore.py`

---

## Testing Requirements

You must add tests. Do not stop at code changes only.

### User profile tests

1. first interaction creates a profile
2. subsequent interaction updates `last_seen_at`
3. owner-facing formatting includes clickable mention when possible

### Usage audit tests

1. pagination works
2. default mode excludes owner records
3. mode switching works
4. page navigation boundaries behave safely

### Result collapse tests

1. verbose text is initially used
2. scheduled compact edit is registered
3. edit failure does not crash handler flow

### Export cache tests

1. successful parse writes cache index
2. YAML/TXT artifacts are generated
3. owner/user permissions are respected
4. expired entries are cleaned up

### Backup/restore tests

1. backup archive is created with expected files
2. restore reconstructs state
3. startup bootstrap restore only runs on empty state

---

## Mandatory Self-Check Before Finishing

Run these checks locally after implementation.

### 1. Compile and import checks

```powershell
python -m compileall .
python -m unittest tests/test_smoke_assembly.py
```

### 2. Full test pass

```powershell
python -m unittest discover -s tests
```

### 3. Manual smoke checklist

At minimum verify:

1. Owner runs `/listusers` and sees readable identity plus ID.
2. Global access enabled, non-owner uses the bot, owner sees paged `/usageaudit`.
3. A parsed subscription first shows verbose output and then collapses after about 20 seconds.
4. Export YAML/TXT buttons work without re-fetching the original link.
5. Cache cleanup removes expired artifacts.
6. Backup export and restore round-trip successfully.

If any required check cannot be completed, document exactly what was not verified and why.

---

## Important Risks and Guardrails

1. Telegram callback data is limited to 64 bytes.
   Do not embed long raw URLs in callback payloads.

2. Do not use blocking sleeps in handlers.
   Use PTB job queue for delayed collapse/cleanup behavior.

3. File paths must be safe.
   Never derive file names directly from user input without sanitization.

4. Backup restore must be safe by default.
   Automatic restore must not overwrite non-empty live state.

5. Owner visibility does not mean arbitrary Telegram discovery.
   Only show information actually observed through bot interactions.

6. Cache and backup are not the same thing.
   Export cache is temporary, backup is durable migration state.

---

## Definition of Done

The task is done only if all conditions below are true:

1. Owner can identify real bot users more easily than by ID alone.
2. Usage audit is pageable and defaults to non-owner focus.
3. Subscription result messages auto-collapse to a compact summary.
4. Parsed subscription outputs can be exported from a 48-hour cache.
5. Full-state backup and restore work for migration.
6. Automated tests were updated and run.
7. Compile/import/tests pass, or failures are explicitly documented with cause.

Do not report completion before these conditions are satisfied.
