# JARVIS Shared Protocol

## Device command envelope

```json
{
  "type": "command",
  "command": "open_app",
  "payload": {"target": "notepad"},
  "device_id": "pc-primary",
  "request_id": "uuid",
  "ts": "2026-10-25T12:00:00Z"
}
```

## Ack envelope

```json
{
  "type": "ack",
  "request_id": "uuid",
  "ok": true,
  "device_id": "pc-primary",
  "result": {
    "status": "accepted"
  }
}
```

## Event envelope

```json
{
  "type": "event",
  "event": "device_status",
  "device_id": "pc-primary",
  "payload": {
    "online": true,
    "revoked": false
  }
}
```

## Error codes

- `device_offline`: the target device is offline or unreachable.
- `device_revoked`: the device has been revoked server-side.
- `device_timeout`: the device did not respond in time.
- `bad_request`: required fields missing or malformed.
- `permission_denied`: command blocked by policy.
- `internal_error`: unexpected backend failure.

## Example: open notepad

1. Client posts `{"command": "open_app", "payload": {"target": "notepad"}}`
2. Server validates device identity and revocation state.
3. Gateway emits command to the paired socket.
4. Device executes the target and replies with an `ack`.
5. Server returns the final result to the Electron client.

## Privacy and camera rules

- Camera allowed defaults to OFF on each fresh launch.
- No base64 image payloads are written to logs, DB history, or audit trails.
- All device revocations are enforced server-side and reflected in cached status.
