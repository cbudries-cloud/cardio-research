# Backups, recovery copies and the live provider key (2026-10-26)

No values from the real records are in this file.

## 1. Backups and the passphrase

| Item | Location | State |
|---|---|---|
| Passphrase | `~/.cardio-pass` (mode 0600, 64 base64 characters from `openssl rand`) | Created 2026-10-26; never printed or committed |
| Backups | `~/cardio-research-data/backups/<UTC timestamp>/` (`database.dump.enc`, `documents.tar.enc`, `MANIFEST`, `SHA256SUMS`) | Encrypted (AES-256-CBC, PBKDF2 200 000 iterations) |
| Restore verification | `make verify-backup BACKUP=<dir>` with `CARDIO_BACKUP_PASSPHRASE_FILE=~/.cardio-pass` | Restores into the disposable project `cardio-restore-test` and compares digests with the working stack |

Take a backup: `CARDIO_BACKUP_PASSPHRASE_FILE=~/.cardio-pass make backup`.

**Disaster recovery is not complete.** The passphrase and every backup are on this laptop only. A lost,
stolen or failed laptop loses both. To finish it, keep two independent copies, stored apart:

1. **The passphrase**, in a password manager (for example 1Password: a new Secure Note named "cardio
   backup passphrase"). Copy it without printing it to the terminal:
   `pbcopy < ~/.cardio-pass`, paste into the note, then clear the clipboard (`pbcopy < /dev/null`).
   Optionally also on paper in a safe place. Without the passphrase the backups cannot be decrypted.
2. **The backups**, copied off the laptop: an external drive you keep elsewhere, or a cloud folder.
   They are encrypted, so a cloud copy exposes ciphertext only, but do not store the passphrase in the
   same place. Example: `rsync -a ~/cardio-research-data/backups/ /Volumes/<drive>/cardio-backups/`.
3. Test the off-laptop copy once: `CARDIO_BACKUP_PASSPHRASE_FILE=<file with the passphrase from the
   password manager> make verify-backup BACKUP=/Volumes/<drive>/cardio-backups/<timestamp>`.

Repeat step 2 after each backup you want to keep.

## 2. Anthropic API key for live runs

The key is never typed into a chat, never sent to the browser and never set as an environment value.
It is a file the api container reads, mounted read-only.

1. Create a key in the Claude Console (platform.claude.com, API keys) under an organization you control
   for this personal project. A Claude.ai or Claude Code subscription does not supply API credentials.
   Check the organization's data-retention setting at platform.claude.com/settings/privacy; the
   approval screen assumes standard 30-day retention unless you enabled zero data retention or HIPAA
   readiness for that organization.
2. Write it to the secret file without echoing it:

   ```sh
   umask 077
   mkdir -p ~/.cardio-secrets
   pbpaste > ~/.cardio-secrets/anthropic_api_key   # after copying the key from the Console
   pbcopy < /dev/null                               # clear the clipboard
   chmod 600 ~/.cardio-secrets/anthropic_api_key
   ```

3. Restart the api container so it picks up the mount: `docker compose up -d api`.
   The page http://127.0.0.1:3000/investigation then shows "key file present".

Configuration in `docker-compose.yml` (defaults; override in the shell before `make up`):

| Variable | Default | Meaning |
|---|---|---|
| `CARDIO_RESEARCH_PROVIDER` | `anthropic` | Live adapter (`providers.LiveProvider`); the only one so far |
| `CARDIO_LLM_MODEL` | `claude-opus-5-5` | Model for live runs |
| `CARDIO_LLM_API_KEY_FILE` | `/run/cardio-secrets/anthropic_api_key` | Key file inside the container |
| `CARDIO_SECRETS_DIR` | `~/.cardio-secrets` | Host directory mounted read-only at `/run/cardio-secrets`; test stacks use an empty temporary directory |

Model facts, verified 2026-10-26 from platform.claude.com/docs: `claude-opus-5-5` is a current model
(retirement not sooner than 2027-09-22), $4 per million input tokens and $20 per million output tokens
on global routing, adaptive thinking always on (thinking counts toward `max_tokens`), structured
outputs supported, not a designated Covered Model. Retention: API inputs and outputs deleted within
30 days unless otherwise agreed; Usage Policy flags up to 2 years; not used for training unless you
send feedback or opt in.

Setting the key does not send anything. A request leaves the application only when you approve one
prepared run on the investigation page.
