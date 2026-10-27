# User Data Ownership Inventory

| Table or storage | Scope | Owner key / isolation |
| --- | --- | --- |
| `conversations` | User data | `owner_username`; session IDs are not globally unique |
| `notes` | User data | `owner_username` |
| `alarms` | User data | `owner_username`; scheduler/cache operations are owner-keyed |
| `memory_facts` | User data | `owner_username`; semantic search filters by owner |
| `memory_vectors` | User data (Neon/Postgres) | `owner_username`; pgvector search filters by owner |
| `monitors` | User data | `owner_username`; monitor cache and worker are owner-keyed |
| `monitor_log` | User data | `owner_username` |
| `command_log` | User data | `owner_username` |
| `events` | User data | `owner_username` |
| `heartbeat_log` | User data | `owner_username` |
| `session_stats` | User data | `owner_username` |
| `cameras` | User data | `owner_username` |
| `smarthome_devices` | User data | `owner_username` plus `device_id`; replaces the legacy global config JSON |
| `discord_settings` | User data | `owner_username`; replaces legacy Discord values stored in global config |
| `devices` | User data | `owner_username`; device scopes and revocation remain device-specific |
| `user_api_keys` | User data | `owner_username` (composite key with `provider`) |
| `pairing_codes` | User data | `owner_username` |
| `pending_confirmations` | User data | `owner_username` (composite key with `session_id`) |
| `snapshots` | User data (Neon/Postgres) | `owner_username`; local SQLite snapshots are stored in owner-hashed directories |
| `user_owners` | Per-user ownership index | `owner_username` primary key |
| `config` | Shared service configuration | Global key/value records; not per-user content |
| `pair_code_rate_limits` | Shared security state | Global rate keys; not per-user content |
| `users` | Legacy identity/authentication | `username` is the identity key; not user content or Clerk profile storage |

SQLite's canonical schema creates owner columns for the user-data tables, and its startup migration upgrades existing databases. Neon/Postgres uses the shared schema plus snapshot/vector schemas and explicit `ALTER TABLE` migrations. Legacy unassigned records have an empty owner until the operator explicitly runs `scripts/assign_legacy_owner.py` with `OWNER_USERNAME`; the script imports/removes the old shared smart-home JSON and deletes the legacy global Discord setting keys without reading their values. Discord settings must then be re-entered by their owner. No setting values are printed, and no user is selected automatically.