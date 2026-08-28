# Agent Connect

A personal fork of [AnkiConnect](https://foosoft.net/projects/anki-connect/) by Alex Yatskov / FooSoft Productions. Default port is **8766**, so it can run alongside stock AnkiConnect (which uses 8765) in the same Anki install. See the repo README for documentation of the Agent Connect actions.

### Configuration keys

- **`apiKey`** — string or `null` (default `null`). When set, every request must include a matching `key` field.
- **`apiLogPath`** — string path or `null` (default `null`). When set, requests/responses are appended to this log file.
- **`webBindAddress`** — default `"127.0.0.1"`. Address the HTTP server binds to. Can be overridden with the `ANKICONNECT_PLUS_BIND_ADDRESS` environment variable.
- **`webBindPort`** — default `8766`. Port the server listens on. Stock AnkiConnect defaults to 8765; keeping these distinct lets both add-ons run at once.
- **`webCorsOriginList`** — default `["http://localhost"]`. Origins allowed CORS access. The `ANKICONNECT_PLUS_CORS_ORIGIN` environment variable appends one more origin.
- **`ignoreOriginList`** — default `[]`. Origins that are silently denied without prompting.

### Suspension control

These two keys are *defaults* only — an explicit parameter on the call always wins, and a request that passes neither gets the value below.

**`preserveSuspendedOnReschedule` ships `true` and is a deliberate deviation from stock Anki.** Anki's own `set_due_date` silently un-suspends every card it touches — rescheduling a deck-wide selection can revive a whole set of suspended leeches in one call. This fork protects against that by default, and the response always discloses what happened. **`suspendNewCards` ships `false`** (stock-compatible): flip it to `true` to opt into the suspended-draft workflow, where generated batches never enter review before a human has read them.

- **`preserveSuspendedOnReschedule`** — default `true`. `bulkSetDueDate` snapshots which target cards are suspended, reschedules, then **re-suspends exactly the cards Anki revived**, all inside the action's own undo entry (one Ctrl+Z reverts both halves). The response reports both `unsuspended` (what Anki revived mid-call) and `resuspended` (what was put back). Set to `false`, or pass `preserveSuspended: false` on the call, for stock Anki behavior. Buried cards are deliberately **not** re-buried.
- **`suspendNewCards`** — default `false` (stock Anki behavior: new cards are live). Set to `true`, or pass `suspend: true` on the call, and `bulkAddNotes` leaves the cards it creates **suspended**, in the same undo entry as the adds, listing them in `suspended`.

The RESOLVED value of both keys on this install — and whether each came from this config or the shipped default — is served machine-readably by the `plusInfo` action as `effectiveConfig`, through the same code path the two write actions use. `source: "user_config"` means the key sits in your saved config; `"shipped_default"` means the shipped value is in force. Saving this config dialog stores every key at once, so after one save both keys report `user_config`.

A value that is not a JSON boolean is ignored and the documented default above applies (a config typo must not fail a write action).

### Environment variables

- `ANKICONNECT_PLUS_BIND_ADDRESS` — overrides `webBindAddress`.
- `ANKICONNECT_PLUS_CORS_ORIGIN` — adds an allowed CORS origin.

(These are intentionally different from stock AnkiConnect's `ANKICONNECT_BIND_ADDRESS` / `ANKICONNECT_CORS_ORIGIN` so the two add-ons never share a bind address.)

For the upstream actions and general usage, see the [AnkiConnect documentation](https://foosoft.net/projects/anki-connect/).
