# AnkiConnect Plus

A personal fork of [AnkiConnect](https://foosoft.net/projects/anki-connect/) by Alex Yatskov / FooSoft Productions. Default port is **8766**, so it can run alongside stock AnkiConnect (which uses 8765) in the same Anki install. See the repo README for documentation of the Plus actions.

### Configuration keys

- **`apiKey`** — string or `null` (default `null`). When set, every request must include a matching `key` field.
- **`apiLogPath`** — string path or `null` (default `null`). When set, requests/responses are appended to this log file.
- **`webBindAddress`** — default `"127.0.0.1"`. Address the HTTP server binds to. Can be overridden with the `ANKICONNECT_PLUS_BIND_ADDRESS` environment variable.
- **`webBindPort`** — default `8766`. Port the server listens on. Stock AnkiConnect defaults to 8765; keeping these distinct lets both add-ons run at once.
- **`webCorsOriginList`** — default `["http://localhost"]`. Origins allowed CORS access. The `ANKICONNECT_PLUS_CORS_ORIGIN` environment variable appends one more origin.
- **`ignoreOriginList`** — default `[]`. Origins that are silently denied without prompting.

### Environment variables

- `ANKICONNECT_PLUS_BIND_ADDRESS` — overrides `webBindAddress`.
- `ANKICONNECT_PLUS_CORS_ORIGIN` — adds an allowed CORS origin.

(These are intentionally different from stock AnkiConnect's `ANKICONNECT_BIND_ADDRESS` / `ANKICONNECT_CORS_ORIGIN` so the two add-ons never share a bind address.)

For the upstream actions and general usage, see the [AnkiConnect documentation](https://foosoft.net/projects/anki-connect/).
