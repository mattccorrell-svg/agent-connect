# AnkiConnect Plus — Implementation Specification

Version: 1.0.0 (spec revision 1, 2026-08-11)
Target Anki: 25.09.4 (Qt6, python 3.13). Fork of AnkiConnect (GPLv3) by Alex Yatskov / FooSoft.
Working copy: `/Users/mattyc/Downloads/anki-connect-plus/connect_plus/`
Venv python for all headless execution/tests: `/Users/mattyc/Library/Application Support/AnkiProgramFiles/.venv/bin/python`
Anki packages: `/Users/mattyc/Library/Application Support/AnkiProgramFiles/.venv/lib/python3.13/site-packages` (referred to below as `SP`).

HARD RULES (repeated from project charter, enforced by this spec):
- Never modify anything under `~/Library/Application Support/Anki2/` and never write to the user's real collection during development/testing. All tests run against scratch `.anki2` collections.
- Raw `col.db` **writes are forbidden everywhere** in this codebase. Read-only `SELECT` statements are allowed only where this spec explicitly says so (`queryRevlog`, the bulkAddNotes csum precheck, note-id/card-id location selects, and the §18 sync dirtiness select `select ls, mod from col`). Rationale: raw non-select SQL through `DBProxy` wipes the entire undo queue, and raw note updates bypass `mod`/`usn` bookkeeping, silently breaking sync (verified in research).
- Never run `git commit` from automation.

---

## 0. Deviations from locked decisions

All locked decisions survive. The following are minimal adaptations forced by the researched APIs — each keeps the locked external contract or extends it in a backward-compatible way:

1. **`addImageOcclusionNote` deck placement is post-hoc.** The backend RPC `Collection.add_image_occlusion_note(notetype_id, image_path, occlusions, header, back_extra, tags)` has **no deck parameter** and returns only `OpChanges` (no note id). We honor the locked `deckName` param by moving the new note's cards with `col.set_deck(card_ids, deck_id)` immediately after the add, and merge both ops into one undo entry. The note id is located via a read-only `select max(id) from notes` snapshot before/after the call (safe: handlers are strictly serialized on the Qt main thread).
2. **`updateImageOcclusionNote` cannot change the image.** `Collection.update_image_occlusion_note(note_id, occlusions, header, back_extra, tags)` has no image parameter. The action therefore accepts no `image` param; changing the image requires delete + re-add. (The "inverse of get" contract holds for every other field.)
3. **`getImageOcclusionNote` may return non-rect shapes.** Notes created in Anki's own editor can contain `ellipse`, `polygon`, and `text` shapes. Rects are returned flattened per the locked shape; non-rect shapes are returned as generic `{ordinal, shape, properties}` entries rather than being dropped.
4. **`createBackup` can legitimately return `{created: false}` even with `force: true`** — the backend returns `False` when the collection has no changes since the last backup (probe-verified). This is surfaced, not treated as an error.
5. **`bulkAddNotes` accepts the full upstream note shape, but per-note `options.duplicateScope` / `options.duplicateScopeOptions` are ignored in v1.** Duplicate detection is the locked csum precheck, whose semantics are Anki's native ones: same notetype + same stripped first field, collection-wide. Per-note `options.allowDuplicate` **is** honored (overrides the batch-level `allowDuplicates`). Presence of `duplicateScope` keys is silently ignored (documented in README).
6. **`bulkAddNotes` uses a per-note `col.add_note` loop, not plural `col.add_notes`,** because `atomic: false` partial-continue and per-note skip reporting are impossible with the all-in-one-transaction plural call. The single-undo-entry contract is met with `add_custom_undo_entry` + `merge_undo_entries` (probe-verified pattern). Measured cost of the loop is ~34 ms per 300 notes — acceptable.
7. **`undoEntry` in bulk-action returns is `null` when the batch performed zero collection writes** (everything skipped). The custom undo entry is created lazily right before the first actual write so we never leave an empty entry on the undo stack.
8. **`bulkSuspend` (unsuspend direction) and `bulkSetDueDate` compute `changed` from a read-only precheck, not from the backend.** The locked `{changed, undoEntry}` shape assumed a backend count, but only `suspend_cards` returns `OpChangesWithCount`; `unsuspend_cards` and `set_due_date` return plain `OpChanges` (verified in `SP/anki/scheduler/base.py:150-156,205-227`). Adaptation: input ids are deduplicated and filtered to existing cards via `col.get_card` (so backend behavior on unknown ids never enters the contract); unsuspend's `changed` = cards whose queue was negative before the op (the restore op changes exactly those — it also unburies); `set_due_date`'s `changed` = the count of existing cards passed (the op applies to every one regardless of state). The suspend direction still uses the backend's authoritative `.count`.
9. **Sync-family adaptations (§18), all forced by the installed 25.09.4 source.** (a) `syncStatus` never clears stored auth on a failed check — it mirrors `aqt.sync.get_sync_status` (`SP/aqt/sync.py:42-64`), which swallows status-check errors; auth clearing on `SyncErrorKind.AUTH` happens only in `syncNow`'s real-sync error path, mirroring `handle_sync_error` (`SP/aqt/sync.py:69-76`). (b) While the plus sync job is in state `syncing`, `syncStatus` skips ALL collection access and returns `lastSyncMs`/`modMs`/`required` as `null` — the backend holds the collection mutex for the whole `sync_collection` call, so any `col`/`col.db` touch would block the Qt main thread until the sync finished. (c) `anki.errors.Interrupted` classifies as job error code `aborted` in `syncNow`, but `syncStatus`'s `required` coerces it to `error` (the locked `required` enum has no aborted member). (d) `syncNow` treats ANY post-sync `required != NO_CHANGES` (values 1–4) as `full_sync_required` — after a successful normal sync the backend reports `NO_CHANGES`; anything else means a normal sync cannot converge.
10. **AnkiHub-family adaptations (§19), all verified against the installed AnkiHub add-on 2026-08-10.1.** (a) AnkiHub actions use a parseable two-tier error style: semantic/flow errors raise `"<CODE>: <message>"` with the §19 taxonomy code first (so callers can `error.split(": ", 1)[0]`); parameter-shape errors keep the §3.2 house style. (b) `source.step` (int 1–3) is added to the locked `source: {type, text}` shape — the dialog's UWorld flow carries a "Step N" dropdown whose choice is folded into the comment text, and the locked shape had no way to express it; it is required for UWorld sources and rejected on every other type. (c) The add-on's new-note dialog flow offers no Source widget and submits the rationale alone; the locked `source?` param on `ankihubSuggestNewNote` is honored anyway by folding the identical Source line ('Duplicate Note' excluded — it cannot describe a brand-new note); on duplicate-resubmit the same comment is reused (matching the add-on, which folds the source into its resubmit comment). (d) A `source` is also accepted for `changeType: delete` on ANY deck (optional, 'Duplicate Note' only) — the dialog offers exactly that; everywhere the dialog shows no Source widget a passed `source` is rejected as `invalid parameter` rather than silently folded. (e) `ankihubStatus.decks[]` gains `isAnkingDeck` and the return gains `problems` (feature-detect detail when not compatible) — additive extensions. (f) A note already on AnkiHub passed to `ankihubSuggestNewNote` errors (`VALIDATION_ERROR` pointing at `ankihubSuggestNoteUpdate`) instead of guessing; a note whose notetype resolves to no AnkiHub deck errors `NOT_AN_ANKIHUB_NOTE` unless `deckId` is passed.

---

## 1. Product summary

- Add-on name: **AnkiConnect Plus**. Package/install folder: **`connect_plus`** (must be installed or symlinked into `addons21` under exactly this name — config resolution is keyed by folder name, see §6).
- Default port **8766** (config key `webBindPort`); coexists with stock AnkiConnect on 8765 in the same Anki process. All upstream actions remain available unchanged on 8766 as well.
- Nine new actions: `bulkAddNotes`, `bulkUpdateNoteFields`, `bulkAddTags`, `addImageOcclusionNote`, `getImageOcclusionNote`, `updateImageOcclusionNote`, `queryRevlog`, `createBackup`, `plusInfo`.

## 2. Architecture & module layout

```
connect_plus/
  __init__.py      # upstream, minimal surgical edits (§2.3, §7)
  web.py           # upstream, one optional banner edit (§7)
  util.py          # upstream, port + env-var edits (§6, §7)
  edit.py          # upstream, DOMAIN_PREFIX edit (§7)
  core.py          # NEW — all new business logic, pure functions over anki.Collection
  plus.py          # NEW — thin @util.api() wrappers (PlusMixin) hooking core into dispatch
  config.json      # port 8766 (§6)
  config.md        # rewritten docs (§6)
```

### 2.1 `core.py` — pure logic (headless-testable)

Rules:
- **Imports NOTHING from `aqt`** and nothing from the `connect_plus` package (no `from . import util`, no relative imports at all). Allowed imports: stdlib, `anki.*` only. This lets tests load it standalone via `importlib.util.spec_from_file_location("core", ".../connect_plus/core.py")` without executing the package `__init__.py` (which starts the web server) and without a running Anki.
- Every public function takes `col: anki.collection.Collection` as its first argument and is synchronous and side-effect-free outside that collection.
- Module constants:
  ```python
  PLUS_VERSION = "1.0.0"
  PLUS_ACTIONS = ["bulkAddNotes", "bulkUpdateNoteFields", "bulkAddTags",
                  "addImageOcclusionNote", "getImageOcclusionNote",
                  "updateImageOcclusionNote", "queryRevlog", "createBackup", "plusInfo"]
  DOCS_UPSTREAM = "https://foosoft.net/projects/anki-connect/"
  DOCS_UPSTREAM_SOURCE = "https://git.sr.ht/~foosoft/anki-connect"
  DOCS_PLUS = "https://github.com/mattccorrell-svg/anki-connect-plus#readme"  # placeholder; README.md in repo root is authoritative
  ```
- Public function signatures (python snake_case; JSON camelCase mapping happens in `plus.py`):
  ```python
  def bulk_add_notes(col, notes, atomic=True, allow_duplicates=False) -> dict
  def bulk_update_note_fields(col, notes, atomic=True) -> dict
  def bulk_add_tags(col, note_ids, tags, atomic=True) -> dict
  def add_image_occlusion_note(col, image_path=None, image_data_b64=None, image_filename=None,
                               occlusions=None, header="", back_extra="",
                               tags=None, deck_name=None, hide_all_guess_one=True) -> dict
  def get_image_occlusion_note(col, note_id) -> dict
  def update_image_occlusion_note(col, note_id, occlusions=None, header=None,
                                  back_extra=None, tags=None) -> None
  def query_revlog(col, card_ids=None, note_ids=None, deck_name=None,
                   since_ms=None, until_ms=None, limit=5000) -> dict
  def create_backup(col, force=True) -> dict
  # shared helpers (also public for tests):
  def serialize_occlusions(shapes, hide_all_guess_one=True) -> str
  def parse_io_response_occlusions(resp_note) -> list[dict]
  def io_num(v: float) -> str
  def find_io_notetype_id(col) -> int
  ```

### 2.2 `plus.py` — dispatch wrappers

- Defines `class PlusMixin:` containing one method per action, decorated with bare `@util.api()`. Dispatch resolution: `AnkiConnect.handler` discovers actions by `inspect.getmembers(self, predicate=inspect.ismethod)` filtering on the `api` attribute; with empty `versions`, **the method name is the action name** and JSON `params` keys are splatted as keyword args (`methodInst(**params)`). Therefore method names and parameter names in `plus.py` must be the exact camelCase JSON names below.
- Imports: `from . import util`, `from . import core`, and `aqt` only where needed (media embedding reuse; see bulkAddNotes). `plus.py` is the only new file allowed to touch `aqt`.
- Every wrapper obtains the collection via the existing upstream helper `self.collection()` (`__init__.py:162-167`), which raises `Exception('collection is not available')` before a profile is open — that error path is inherited for free. Exception: `plusInfo` must NOT call `self.collection()` (it must work before profile load).
- Wrapper bodies are 1–5 lines: unpack camelCase params → call `core.*` → return its result. No business logic in `plus.py` beyond (a) media embedding reuse for `bulkAddNotes` and (b) assembling `plusInfo`.

Skeleton:
```python
from . import util
from . import core

class PlusMixin:
    @util.api()
    def bulkAddNotes(self, notes, atomic=True, allowDuplicates=False):
        prepared = [self._plusEmbedNoteMedia(n) for n in notes]   # §4.1 media step
        return core.bulk_add_notes(self.collection(), prepared,
                                   atomic=atomic, allow_duplicates=allowDuplicates)
    ...
```

### 2.3 Surgical edits to upstream files (complete list)

1. `__init__.py` (top, near other relative imports): add `from . import plus`.
2. `__init__.py:65`: `class AnkiConnect:` → `class AnkiConnect(plus.PlusMixin):`. `inspect.getmembers` finds inherited bound methods, so no other dispatch change is needed. Verified no name collisions: none of the nine action names exists on upstream `AnkiConnect` (upstream has `addNotes`, not `bulkAddNotes`, etc.).
3. Rebrand edits per §7 (port, env vars, DOMAIN_PREFIX, dialog strings, config files).

Nothing else in `__init__.py` / `web.py` / `edit.py` / `util.py` changes.

## 3. Global conventions

### 3.1 Threading & reentrancy (from source map — governs every handler)

- There are **no threads**. `web.WebServer` is pumped by a `QTimer` (default 25 ms) on the Qt **main thread**; each HTTP request is parsed and its handler executed **synchronously inside a timer tick**, one request per connection, no keep-alive. Consequences:
  - Handlers may touch the collection directly with no locking; two requests can never interleave.
  - A slow handler freezes the Anki UI for its duration. Bulk actions at the scale Matt uses (hundreds to low thousands of notes) run in tens of ms (probe: 300 `add_note` calls = 34 ms) — acceptable. `createBackup` with `wait_for_completion=True` blocks the UI for the backup duration (seconds); documented, accepted for a personal tool.
  - The "snapshot max(id) → act → select new id" pattern used by `addImageOcclusionNote` is race-free because nothing else can run between the two selects.
- New actions inherit upstream's envelope, apiKey check, CORS gate, and `multi` behavior unchanged (`web.py:164-212`, `__init__.py:106-147`). With `version >= 5` responses are `{"result": ..., "error": null}`; errors are `{"result": null, "error": str(exception)}`, HTTP always 200 (403 only for CORS-denied).

### 3.2 Error style

- All action errors are `raise Exception("<message>")`. Message templates are specified per action. Where a JSON report is embedded, it is `json.dumps(report, separators=(",", ":"))` appended after a fixed prefix so callers can `split(": ", 1)[1]` and parse.
- Type/param validation errors: `Exception("invalid parameter: <name>: <why>")`.

### 3.3 Undo conventions

- Bulk actions use the probe-verified pattern:
  ```python
  target = col.add_custom_undo_entry(name)   # LAZY: created just before the first real write
  ...write op...                             # each backend op creates its own entry
  col.merge_undo_entries(target)             # called after EVERY successful op (aqt convention:
                                             # a mid-loop crash still leaves a merged prefix)
  ```
- Undo entry names (also returned as `undoEntry`):
  - `bulkAddNotes` → `"AnkiConnect Plus: Bulk Add"`
  - `bulkUpdateNoteFields` → `"AnkiConnect Plus: Bulk Update"`
  - `bulkAddTags` → `"AnkiConnect Plus: Bulk Tags"`
- Atomic revert: after merging, a single `col.undo()` reverts the whole batch (probe-verified: one undo reverted 3 adds + 1 update). Guard: only call `col.undo()` if at least one write happened AND `col.undo_status().undo == name`.
- Reminder: any non-`select` raw SQL wipes the undo queue (probe-verified). This is one of the reasons raw writes are banned.

---

## 4. Actions

### 4.1 `bulkAddNotes`

Add many notes with one undo entry, fast duplicate pre-check, and per-note error reporting.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `notes` | array of note objects | required | Same shape as upstream `addNotes`: `{deckName, modelName, fields: {FieldName: html}, tags: [str], options?: {allowDuplicate?: bool, ...}, audio?/video?/picture?: [...]}` |
| `atomic` | bool | `true` | `true`: any hard error reverts the whole batch and raises. `false`: continue past per-note hard errors, reporting them in `skipped`. |
| `allowDuplicates` | bool | `false` | Batch default; per-note `options.allowDuplicate`, when present, overrides it for that note. |
| `dryRun` | bool | `false` | `true`: run the identical resolution pass + duplicate precheck, write nothing, return `{wouldAdd, skipped, undoEntry: null}` — see §15. |

**Returns**

```json
{"added": [1712345678901, ...], "skipped": [{"index": 3, "reason": "duplicate"}], "undoEntry": "AnkiConnect Plus: Bulk Add"}
```
- `added`: note ids of successful adds, in input order **excluding** skipped entries (use `skipped[].index` to realign).
- `skipped[].index` is the 0-based index into the input `notes` array. `reason` strings: `"duplicate"`, `"duplicate (within batch)"`, `"empty first field"`, `"model was not found: <name>"`, `"deck was not found: <name>"`, `"field was not found in model: <field>"`, or for atomic=false hard errors the stringified exception.
- `undoEntry`: the undo entry name, or `null` if nothing was added.

**Anki API calls** (exact, from research)

- `col.models.by_name(modelName)` → notetype dict or None; first field name = `model["flds"][0]["name"]`.
- `col.decks.id_for_name(deckName)` → deck id or None. Decks are NOT auto-created (matches upstream `addNote` behavior).
- Dupe precheck: `anki.utils.field_checksum(first_field_str) -> int` (first 8 hex digits of sha1 of `strip_html_media(text)` as 32-bit int; **matches `notes.csum` exactly**, probe-verified) + one read-only select per distinct mid in the batch:
  `col.db.all("select csum, flds from notes where mid = ? and csum in (%s)" % ",".join("?"*len(csums)), mid, *csums)` — `csum` is indexed (`ix_notes_csum`). Csum hits are confirmed by comparing `strip_html_media(first_field)` values (csum collisions are possible).
- Note build: `note = anki.notes.Note(col, model)`; `note[fieldName] = value` for each provided field (raise/skip on unknown field); `note.tags = tags`.
- Add: `col.add_note(note, DeckId(did))` — populates `note.id`. One "Add Note" undo entry per call, merged per §3.3.
- (Plural `col.add_notes([AddNoteRequest(note, deck_id)])` exists — `SP/anki/collection.py:537` — but is NOT used; see Deviations #6.)

**Algorithm**

1. Wrapper (`plus.py`): for each note dict, run upstream's media embedding — the same audio/video/picture handling `addNote`/`createNote` performs in `__init__.py` — so `fields` arrive in core with media filenames already substituted and files stored. Factor the smallest possible call into the existing upstream code path; do not duplicate its logic in core. Notes without media keys pass through untouched (this keeps core headless-testable: tests simply don't use media keys).
2. Core: validate `notes` is a non-empty list of dicts (empty list → return `{"added": [], "skipped": [], "undoEntry": null}`).
3. Resolution pass (no writes): resolve model + deck per note; compute `(mid, csum, stripped_first)` per note; batch-select existing csums per mid; mark each note `ok` / skip-reason. Track intra-batch `(mid, stripped_first)` seen-set: a second identical note in the same request is `"duplicate (within batch)"` unless that note allows duplicates. Empty `stripped_first` → `"empty first field"`.
4. Write pass: for the first `ok` note, `target = col.add_custom_undo_entry("AnkiConnect Plus: Bulk Add")`. For each `ok` note: build Note, set fields/tags, `col.add_note(note, did)`, append `note.id` to `added`, `col.merge_undo_entries(target)`.
5. Hard error during the write pass (unexpected exception from Anki):
   - `atomic=true`: ensure entries are merged, then if `added` non-empty and `col.undo_status().undo == "AnkiConnect Plus: Bulk Add"`, call `col.undo()`. Then `raise Exception("bulkAddNotes failed (batch reverted): " + json.dumps({"failedIndex": i, "error": str(e), "addedBeforeRevert": len(added), "skipped": skipped}))`.
   - `atomic=false`: record `{"index": i, "reason": str(e)}` in `skipped`, continue.
   - Validation skips (duplicate/empty/missing model/deck/field) are **never** hard errors in either mode — they always go to `skipped`.

**Edge cases tests must cover**

- 2 valid notes → both added, single undo entry, one `col.undo()` removes both.
- Duplicate of an existing collection note → skipped `"duplicate"`; with `allowDuplicates=true` → added; with per-note `options.allowDuplicate=true` and batch false → added.
- Two identical notes within one batch → second skipped `"duplicate (within batch)"`.
- Csum collision, different stripped text → NOT flagged duplicate (stripped-field confirm).
- Same first field, different notetype → NOT a duplicate (dupes are per-mid).
- Empty first field (after HTML strip, e.g. `"<br>"`) → skipped `"empty first field"`.
- Unknown model / unknown deck / unknown field name → per-note skip with the exact reason strings above.
- `atomic=true` with an injected hard error mid-batch (e.g. monkeypatched `add_note` raising on note 3 of 5) → note count returns to pre-batch value; raised message parses as JSON after the prefix.
- `atomic=false` same injection → notes 1,2,4,5 added, note 3 in `skipped`.
- All notes skipped → `undoEntry: null`, undo queue untouched.
- HTML in fields preserved verbatim; unicode fields; tags list applied.
- 300-note batch completes well under 1 s.

### 4.2 `bulkUpdateNoteFields`

**Params**

| name | type | default | notes |
|---|---|---|---|
| `notes` | array of `{id: int, fields?: {FieldName: html}, tags?: [str]}` | required | `fields` updates only the named fields; `tags`, when present, **replaces** the note's whole tag list. At least one of `fields`/`tags` must be present per entry. |
| `atomic` | bool | `true` | Same contract as bulkAddNotes. |
| `dryRun` | bool | `false` | `true`: run the identical per-entry validation, write nothing, return `{wouldUpdate, skipped, undoEntry: null}` — see §15. |

**Returns** `{"updated": [noteIds], "skipped": [{"index", "reason"}], "undoEntry": "AnkiConnect Plus: Bulk Update" | null}`

**Anki API calls**

- `col.get_note(NoteId(id))` — raises `anki.errors.NotFoundError` → skip `"note was not found: <id>"`.
- Field membership: `name in note` (Note supports `__contains__`); unknown → skip `"field was not found in note: <name>"`.
- `col.update_note(note)` — creates "Update Note" entry (do NOT pass `skip_undo_entry=True`; we merge instead), merged per §3.3.

**Algorithm** — mirror of 4.1: validate → per-entry try: load note, apply fields/tags, detect no-op (all values identical → still counts as updated; simplicity over cleverness), `col.update_note`, merge. Lazy undo entry `"AnkiConnect Plus: Bulk Update"`. Atomic revert + error report identical to 4.1 with prefix `"bulkUpdateNoteFields failed (batch reverted): "`.

**Edge cases** — missing note id skipped; unknown field skipped without partial application of that entry's other fields (validate the whole entry before mutating the Note object); tags-only update; fields-only update; entry with neither `fields` nor `tags` → skip `"invalid parameter: notes[i]: fields or tags required"`; atomic revert restores original field values and tags; duplicate ids in one batch (second update wins, both reported in `updated`).

### 4.3 `bulkAddTags`

**Params**

| name | type | default | notes |
|---|---|---|---|
| `noteIds` | [int] | required | |
| `tags` | str or [str] | required | String is split on whitespace, upstream-style. Empty after normalization → error. |
| `atomic` | bool | `true` | |
| `dryRun` | bool | `false` | `true`: run the identical validation + missing-tag detection, write nothing, return `{wouldUpdate, skipped, undoEntry: null}` — see §15. |

**Returns** `{"updated": [noteIds that actually changed], "skipped": [{"index", "reason"}], "undoEntry": "AnkiConnect Plus: Bulk Tags" | null}`

**Anki API calls** — per note id: `col.get_note(nid)` (NotFoundError → skip `"note was not found: <id>"`); `note.has_tag(t)` / `note.add_tag(t)`; if any tag was actually added, `col.update_note(note)` + merge. Notes already having all tags are not written (and appear in neither list — count them in `updated`? No: spec decision — they are returned in `updated` **only if written**; unchanged notes are simply omitted from both lists; tests assert this).

Single undo entry `"AnkiConnect Plus: Bulk Tags"` (lazy). Atomic contract identical, prefix `"bulkAddTags failed (batch reverted): "`.

**Edge cases** — tag already present on all notes → no writes, `undoEntry: null`; mixed present/absent; multi-tag string `"a b"` vs list `["a","b"]` equivalence; nonexistent note id; undo reverts tag additions; tag with `::` hierarchy adds verbatim.

### 4.4 `addImageOcclusionNote`

Creates a **native** (built-in "Image Occlusion", `originalStockKind == 6`) IO note.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `image` | `{path: str}` OR `{data: str(base64), filename: str}` | required | Exactly one of `path` / `data`. `path` = absolute path to an image on disk. `data`+`filename` = base64 payload stored into media under `filename` (possibly renamed on conflict). |
| `occlusions` | str OR array | required | String → treated as a ready-made native occlusions string, passed verbatim. Array → `[{left, top, width, height, ordinal?}]`, all floats normalized 0–1 (fractions of image width/height). |
| `header` | str | `""` | Plain HTML for the Header field. |
| `backExtra` | str | `""` | Plain HTML for the Back Extra field. |
| `tags` | [str] | `[]` | |
| `deckName` | str | required | Must exist (`col.decks.id_for_name`); no auto-create. |
| `hideAllGuessOne` | bool | `true` | `true` appends `:oi=1` to every serialized shape ("Hide all, guess one"); `false` omits it ("Hide one, guess one"). Ignored when `occlusions` is a string. |

**Returns** `{"noteId": int, "cardIds": [int, ...]}` (cardIds ordered by card `ord`).

**Anki API calls** (exact)

- `col.add_image_occlusion_notetype()` — idempotent, ensures the notetype exists (`SP/anki/collection.py:435`).
- `core.find_io_notetype_id(col)`: iterate `col.models.all()`, return id of the notetype with `nt.get("originalStockKind") == 6`; fall back to `col.models.by_name("Image Occlusion")["id"]`; error `"image occlusion notetype not found"` if neither. (Do not trust the name alone — renameable.)
- Media (data variant): `fname = col.media.write_data(filename, base64.b64decode(data))` → returns final possibly-renamed filename (`SP/anki/media.py:97`; same-name+same-bytes dedups to same name, same-name+different-bytes renames to `dup-<sha1>.<ext>` — probe-verified). Then `image_path = os.path.join(col.media.dir(), fname)`. The subsequent backend add re-encounters identical bytes under that name and dedups, so no duplicate media file is created.
- Id snapshot: `before = col.db.scalar("select max(id) from notes") or 0` (read-only, allowed).
- `col.add_image_occlusion_note(notetype_id, image_path, occlusions_str, header, back_extra, tags)` → `OpChanges` only (`SP/anki/collection.py:439`; positional args on the Collection wrapper). Creates one undo entry named "Image Occlusion".
- Locate: `nid = col.db.scalar("select id from notes where id > ?", before)`; error `"image occlusion note was not created"` if None (race-free per §3.1).
- `card_ids = col.db.list("select id from cards where nid = ? order by ord", nid)`.
- Deck move (Deviation #1): `home_did = col.decks.id_for_name(deckName)` (validated up front, before any write). If the new cards are not already in that deck: `target = col.undo_status().last_step` (the "Image Occlusion" entry), then `col.set_deck(card_ids, home_did)`, then `col.merge_undo_entries(target)` so one undo reverts add+move. (`Collection.set_deck(card_ids, deck_id)` exists in 25.09's collection.py; smoke-test at implementation time — if absent, the fallback is `col.decks.set_deck`, NOT raw SQL.)

**Occlusion serialization** — see §5. Array validation: every rect needs all four of `left/top/width/height` as numbers; `0 <= left,top <= 1`, `0 < width,height <= 1` → else `"invalid parameter: occlusions[i]: <why>"`. `ordinal` (int ≥ 0) optional; when absent, ordinals are assigned 1..N in array order. Explicit ordinals may repeat (shapes sharing an ordinal mask together on ONE card — probe-verified) and `0` means annotation-only (generates no card — probe-verified). Empty array → error `"invalid parameter: occlusions: at least one occlusion required"`.

**Error cases** — `"invalid parameter: image: exactly one of path or data required"`; `"image file was not found: <path>"` (checked with `os.path.isfile` before any write); `"invalid parameter: image.data: invalid base64"`; `"invalid parameter: image.filename: required with data"`; `"deck was not found: <name>"`; validation errors above. All validation happens **before** the first write so failures leave no partial state.

**Threading** — main thread; media write + backend add are fast (<50 ms typical).

**Edge cases tests must cover**

- path variant and data variant both produce a note whose Image field is `<img src="<final-fname>">` and whose media file exists in the scratch media dir.
- 3 rects, default ordinals → 3 cards (ords 0,1,2); `cardIds` length 3.
- Two rects sharing `ordinal: 2` + one `ordinal: 1` → 2 cards.
- A rect with `ordinal: 0` plus two normal rects → 2 cards (c0 makes none).
- `hideAllGuessOne` true/false → `:oi=1` present/absent in the stored Occlusion field; round-trip `get_image_occlusion_note(...).note.occlude_inactive` reflects it.
- Pre-made native string passthrough stored verbatim.
- deckName honored: cards' `did` equals target deck; single `col.undo()` removes note, cards, and the deck move.
- Filename collision with different bytes → note references the renamed `dup-<sha1>` file.
- Nonexistent deck / bad base64 / missing image file → error, note count unchanged.

### 4.5 `getImageOcclusionNote`

**Params** — `{noteId: int}` (required).

**Returns**

```json
{
  "imageFilename": "occl-a98591b53359.png",
  "occlusions": [
    {"ordinal": 1, "shape": "rect", "left": 0.3949, "top": 0.0435, "width": 0.271, "height": 0.1016},
    {"ordinal": 2, "shape": "text", "properties": {"left": ".1", "top": ".2", "text": "label", "scale": "1"}}
  ],
  "header": "…", "backExtra": "…", "tags": ["…"], "occludeInactive": true
}
```
- One output entry **per shape**, flattened from the response's per-ordinal grouping (`occlusions[].shapes[]`), each carrying its group's `ordinal`.
- `shape == "rect"`: `left/top/width/height` coerced to float (plus optional `angle`, `fill` passed through in `properties` if present). Non-rect shapes (`ellipse`, `polygon`, `text`): raw `properties` dict of name→string as returned by the backend (Deviation #3).
- `occludeInactive` = backend's `occlude_inactive` (extension beyond the locked shape; harmless).

**Anki API calls** — `resp = col.get_image_occlusion_note(NoteId(noteId))` (`SP/anki/collection.py:457`). `resp.WhichOneof("value")`: `"error"` → `raise Exception("could not read image occlusion note %d: %s" % (noteId, <error>))`; `"note"` → parse `resp.note`: `image_file_name`, `occlusions[]` (each: `ordinal`, `shapes[]` with `shape` str + `properties[]` name/value pairs), `header`, `back_extra`, `tags`, `occlude_inactive`. `image_data` bytes are **not** returned (use upstream `retrieveMediaFile` for bytes).

**Edge cases** — note created by 4.4 round-trips (ordinals, coords ≈ within 1e-4, header, backExtra, tags, occludeInactive); editor-made note with ellipse/polygon/text parses without loss; non-IO noteId → the backend error path fires; nonexistent noteId → same; escaped `\:` in text values is unescaped by the backend before we see it (probe-verified round-trip).

### 4.6 `updateImageOcclusionNote`

**Params**

| name | type | default | notes |
|---|---|---|---|
| `noteId` | int | required | Must be a native-IO note (`originalStockKind == 6` check on `note.note_type()`, else `"note is not an image occlusion note: <id>"`). |
| `occlusions` | str OR array | omit = keep | Same forms/validation as 4.4; array is re-serialized per §5 with `hideAllGuessOne` inferred: array form accepts optional sibling param `hideAllGuessOne` (default `true`). |
| `header` | str | omit = keep | |
| `backExtra` | str | omit = keep | |
| `tags` | [str] | omit = keep | Replaces the whole tag list when present. |

**Returns** `null` (upstream update-action convention). Errors raise.

**Anki API calls** — the backend updater requires all fields, so omitted params are backfilled from current state read **directly from the note's fields** (exact, no lossy re-serialization): `note = col.get_note(nid)`; `idx = col._backend.get_image_occlusion_fields(note.mid)` → `ImageOcclusionFieldIndexes` with `.occlusions/.image/.header/.back_extra` ordinals (probe: 0/1/2/3); current occlusions string = `note.fields[idx.occlusions]`, etc.; current tags = `note.tags`. Then `col.update_image_occlusion_note(note_id, occlusions_str, header, back_extra, tags)` (`SP/anki/collection.py:462`) → `OpChanges`, own undo entry.

**Edge cases** — header-only update leaves occlusion string byte-identical; occlusions array update regenerates cards (adding an ordinal grows card count, removing one empties/deletes — assert via card count after); tags-only; nonexistent note → NotFoundError surfaced as `"note was not found: <id>"`; non-IO note rejected before any write; single undo reverts; no `image` param exists (Deviation #2 — test that passing `image` raises TypeError via dispatch splat, which is acceptable: the enveloped error names the unexpected argument).

### 4.7 `queryRevlog`

Read-only review-history query. **The only SQL action; SELECT only.**

**Params**

| name | type | default | notes |
|---|---|---|---|
| `cardIds` | [int] | omit | Filter on `revlog.cid`. |
| `noteIds` | [int] | omit | Filter on `cards.nid`. |
| `deckName` | str | omit | Deck and all descendants; resolves via `col.decks.id_for_name` (error `"deck was not found: <name>"` if absent). Descendants collected from `col.decks.all_names_and_ids()`: include ids whose name `== deckName` or starts with `deckName + "::"`. |
| `sinceMs` | int | omit | `revlog.id >= sinceMs` (inclusive; revlog id IS the review epoch-ms). |
| `untilMs` | int | omit | `revlog.id < untilMs` (exclusive). |
| `limit` | int | `5000` | Must be ≥ 1. Applied after ordering. |

Filters AND-combine; all omitted → whole table (limited).

**Returns**

```json
{"rows": [{"id": 1712345678901, "cardId": 1690000000000, "noteId": 1690000000000,
           "ease": 3, "interval": 10, "lastInterval": -600, "factor": 2500,
           "timeMs": 4200, "type": 1, "reviewedAt": 1712345678901}, ...]}
```
`reviewedAt` duplicates `id` (both epoch-ms) per the locked shape. `noteId` is `null` for orphan revlog rows whose card was deleted. Field semantics (document in README): `interval`/`lastInterval` positive = days, negative = seconds; `factor` = SM-2 ease permille (0 for learning/manual; not scheduling-relevant under FSRS); `type`: 0 learning, 1 review, 2 relearning, 3 filtered/cram, 4 manual/forget, 5 rescheduled — stats-worthy rows are `type NOT IN (4, 5)`.

**SQL** (exact; ids validated as ints before interpolation of the placeholder list — values themselves always bound with `?`):

```sql
SELECT r.id, r.cid, c.nid, r.ease, r.ivl, r.lastIvl, r.factor, r.time, r.type
FROM revlog r LEFT JOIN cards c ON c.id = r.cid
WHERE 1=1
  [AND r.cid IN (?,...)]
  [AND c.nid IN (?,...)]
  [AND (CASE WHEN c.odid != 0 THEN c.odid ELSE c.did END) IN (?,...)]   -- deck filter; odid = home deck for cards currently in a filtered deck
  [AND r.id >= ?] [AND r.id < ?]
ORDER BY r.id ASC
LIMIT ?
```
via `col.db.all(sql, *args)` (`DBProxy`; plain selects do not touch the undo queue — probe-verified). Caveat to document: the deck filter reflects each card's **current** deck, not the deck at review time (revlog stores no deck).

**Error cases** — unknown deck; non-int in id lists → `"invalid parameter: cardIds: ints required"`; `limit < 1` → `"invalid parameter: limit: must be >= 1"`.

**Edge cases** — empty result → `{"rows": []}`; limit truncation (insert 10, limit 5 → first 5 chronologically); since/until window boundaries (id == sinceMs included, id == untilMs excluded); deck filter includes subdeck reviews; noteIds filter excludes orphans, bare query includes them with `noteId: null`; learning rows have negative `interval`; undo queue untouched after the action (assert `undo_status()` unchanged).

### 4.8 `createBackup`

**Params** — `{force: bool}`, default `true`.

**Returns** `{"created": bool}` — `false` means the backend skipped because nothing changed since the last backup (Deviation #4), not a failure.

**Anki API calls** — `col.create_backup(backup_folder=folder, force=force, wait_for_completion=True) -> bool` (`SP/anki/collection.py:325-351`; kw-only). `folder = os.path.join(os.path.dirname(col.path), "backups")` — derived from `col.path` so core stays aqt-free; this equals Anki's own per-profile backup folder for a normally-opened profile. `os.makedirs(folder, exist_ok=True)` first. Produces `backup-YYYY-MM-DD-HH.MM.SS.colpkg` and rotates old ones.

**Threading** — `wait_for_completion=True` blocks the main thread (UI freeze for the backup duration). Chosen so `{created}` is truthful and errors are raised synchronously; document in README.

**Edge cases** — fresh scratch collection with changes → `true` and a `backup-*.colpkg` appears in the sibling `backups/` dir; immediate second call → `false` (probe-verified sequence); `force=false` respects the user's backup-interval config (may return `false`); backup write failure (unwritable folder) → exception surfaced in the envelope.

### 4.9 `plusInfo`

**Params** — none. Must work with **no profile open** (do not call `self.collection()`); implemented wholly in `plus.py` from `core` constants.

**Returns**

```json
{
  "name": "AnkiConnect Plus",
  "version": "1.0.0",
  "apiVersion": 6,
  "actions": ["bulkAddNotes", "bulkUpdateNoteFields", "bulkAddTags",
              "addImageOcclusionNote", "getImageOcclusionNote", "updateImageOcclusionNote",
              "queryRevlog", "createBackup", "plusInfo"],
  "docs": {
    "plus": "<DOCS_PLUS>",
    "upstream": "https://foosoft.net/projects/anki-connect/",
    "upstreamSource": "https://git.sr.ht/~foosoft/anki-connect"
  }
}
```
`apiVersion` from `util.setting('apiVersion')`. **Edge cases** — callable before profile load; callable through `multi`; action list exactly matches `core.PLUS_ACTIONS` (single source of truth — test asserts every listed name is a dispatchable `@util.api()` method).

---

## 5. Native occlusion string — serialization spec (shared helper)

Syntax (from the shipped TS serializer + live-note recon; format one cloze per shape, `<br>`-joined):

```
{{c<ordinal>::image-occlusion:rect:left=<n>:top=<n>:width=<n>:height=<n>[:oi=1]}}<br>{{c2::...}}
```

- We **emit rects only** (input shape is rects; passthrough strings may contain anything).
- Number format `io_num(v)`: `f"{v:.4f}"` then strip the leading `"0"` when the value is < 1 (`0.3949 → ".3949"`), matching the observed live-note format (`left=.3949:...`). Trailing-zero trimming (upstream does `.2500→".25"`) is NOT replicated — the backend parser accepts standard decimals; tests verify acceptance by round-tripping through `get_image_occlusion_note` rather than by string equality.
- `:` inside any value must be escaped as `\:` (relevant only if text shapes are ever emitted; rect numbers never contain `:`).
- `oi=1` appended to **every** shape when `hide_all_guess_one=True`; omitted entirely when `False`. (`occlude_inactive` on read-back derives from it.)
- Ordinals: shapes sharing an ordinal N form one card (card ord N−1); `c0` = annotation, no card. Serializer orders output by input array order (order within the field is not semantically significant — the live recon note is unordered).
- `angle`/`fill` are not emitted in v1 (accepted on read in `properties`).

`parse_io_response_occlusions(resp_note)` implements the §4.5 flattening; it is the shared inverse used by tests.

---

## 6. Configuration

### 6.1 `config.json` (ship exactly)

```json
{
    "apiKey": null,
    "apiLogPath": null,
    "webBindAddress": "127.0.0.1",
    "webBindPort": 8766,
    "webCorsOriginList": ["http://localhost"],
    "ignoreOriginList": []
}
```
Only the port changes vs upstream. Keys absent here (`apiPollInterval`, `apiVersion`, `webBacklog`, `webTimeout`, `webCorsOrigin`) intentionally fall through to `DEFAULT_CONFIG` in `util.py`.

### 6.2 `util.py` edits

- `DEFAULT_CONFIG['webBindPort']` (`util.py:76`): `8765` → `8766`.
- Env vars (`util.py:75,77`): `ANKICONNECT_BIND_ADDRESS` → `ANKICONNECT_PLUS_BIND_ADDRESS`, `ANKICONNECT_CORS_ORIGIN` → `ANKICONNECT_PLUS_CORS_ORIGIN`. (Stock AnkiConnect reads the originals; sharing them would force both add-ons onto the same bind address → port-clash dialog.)

### 6.3 `config.md`

Rewrite: title "AnkiConnect Plus", note default port **8766** and that stock AnkiConnect (8765) can run alongside; document every key (`apiKey`, `apiLogPath`, `webBindAddress`, `webBindPort`, `webCorsOriginList`, `ignoreOriginList`) and the two renamed env vars; link to the repo README for the Plus action docs; retain a credit line + link to upstream AnkiConnect docs (replaces the current foosoft link at `config.md:1`).

### 6.4 Config resolution invariant (why the folder name matters)

`util.setting` resolves via `aqt.mw.addonManager.getConfig(__name__)` → `module.split(".")[0]` → **`connect_plus`**. Config namespace is therefore keyed by the install folder name: it must be exactly `connect_plus` inside `addons21`, or `getConfig` returns `None` and every `setting()` call fails as `Exception('setting X not found')`. This also guarantees zero config/meta collision with stock AnkiConnect's `2055492159` folder. `requestPermission` persists origins to `connect_plus/meta.json` only.

---

## 7. Rebrand checklist (complete; from source map grep)

Required:

| # | file:line | change |
|---|---|---|
| 1 | `util.py:76` | `'webBindPort': 8765` → `8766` |
| 2 | `config.json:5` | `"webBindPort": 8765` → `8766` |
| 3 | `util.py:75` | env var → `ANKICONNECT_PLUS_BIND_ADDRESS` |
| 4 | `util.py:77` | env var → `ANKICONNECT_PLUS_CORS_ORIGIN` |
| 5 | `edit.py:28` | `DOMAIN_PREFIX = "foosoft.ankiconnect."` → `"connectplus."` — **the coexistence landmine**: with the stock prefix both add-ons compute dialog tag `foosoft.ankiconnect.Edit`; whichever loads second silently skips `aqt.dialogs.register_dialog` and its `browser_will_search` hook, and its `guiEditNote` opens the *other* add-on's Edit class. The new prefix also cleanly diverges the geometry and search tags (`edit.py:182-184`) and editor button ids (`edit.py:400-401`). |
| 6 | `__init__.py:87` | `QMessageBox.critical(..., 'AnkiConnect', ...)` title → `'AnkiConnect Plus'`; message keeps the failing port number |
| 7 | `__init__.py:426-427` | permission-prompt text "…use Anki through AnkiConnect" → "…through AnkiConnect Plus" |

Optional (do it — personal fork, port-scoped clients):

| # | file:line | change |
|---|---|---|
| 8 | `web.py:185` | empty-body banner `{"apiVersion": "AnkiConnect v.6"}` → `{"apiVersion": "AnkiConnect Plus v.6"}`. Note in README: clients that sniff this exact string (Yomitan-style) must point at 8765/stock instead. |
| 9 | `config.md:1` | upstream docs link → per §6.3 |
| 10 | `edit.py:377` | CSS class `anki-connect-button` may stay (styles are per-webview; no cross-add-on effect) |

Leave alone (internal, no cross-process footprint): `class AnkiConnect` name (`__init__.py:65`, aside from the mixin base per §2.3), instance `ac` (`__init__.py:2193`), comments, the `if __name__ != "plugin":` guard (`__init__.py:2187` — module name inside Anki is the folder name `connect_plus`, guard passes).

Coexistence facts to verify post-install: both add-ons bind their own sockets (8765/8766); both start at module import, before any profile opens; config/meta fully isolated per §6.4; the only shared mutable surface was the `aqt.dialogs` registry, fixed by item 5.

---

## 8. README.md requirements (repo root)

Must contain, in order:

1. **Name + one-liner**: AnkiConnect Plus — a personal fork of AnkiConnect adding bulk, image-occlusion, revlog, and backup actions on port **8766**.
2. **Credit + license**: derived from AnkiConnect by **Alex Yatskov (FooSoft Productions)** — https://foosoft.net/projects/anki-connect/ , source https://git.sr.ht/~foosoft/anki-connect — licensed **GPLv3**; this fork remains GPLv3 (see LICENSE).
3. **Install**: copy or symlink the `connect_plus` folder into Anki's add-on directory as exactly `connect_plus`:
   `ln -s /Users/mattyc/Downloads/anki-connect-plus/connect_plus "~/Library/Application Support/Anki2/addons21/connect_plus"` (macOS path; folder name is load-bearing, §6.4). Restart Anki. (The symlink itself is an addons21 *addition*, not a modification of existing Anki data; creating it is a user action — never automated by tooling per the hard rules.)
4. **Coexistence note**: runs alongside stock AnkiConnect (2055492159) in the same Anki — stock on 8765, Plus on 8766; all upstream actions are also served on 8766; configs are independent; env overrides are `ANKICONNECT_PLUS_BIND_ADDRESS` / `ANKICONNECT_PLUS_CORS_ORIGIN`; banner string on 8766 reads "AnkiConnect Plus v.6".
5. **New-action reference**: params/returns/errors for the seventeen actions (condensed from §§4, 11–14, 16–17), incl. the `interval` sign convention and `type` enum for queryRevlog, the atomic/undo contract for bulks, the `dryRun` param on the three bulk actions (`wouldAdd` count vs `wouldUpdate` id-list, `undoEntry: null`, and §15's skipped-media-embedding limitation), the `bulkSetDueDate` `days` grammar, the `exportDeckApkg` never-overwrite `-2` suffixing and fixed `with_deck_configs=False` choice, deviations #1–#8, and one curl example, e.g.:
   ```bash
   curl localhost:8766 -d '{"action":"plusInfo","version":6}'
   ```
6. **UI-freeze note** for createBackup and very large bulks (single-threaded server on the Qt main thread).
7. **Safety note**: the add-on never issues raw SQL writes; revlog access is read-only.

## 9. LICENSE

Repo root `LICENSE` file = the **full, unmodified GNU GPLv3 text** (from https://www.gnu.org/licenses/gpl-3.0.txt). Keep upstream copyright notices in file headers; add a line `Copyright (C) 2026 Matthew Correll (AnkiConnect Plus modifications)` beneath the existing FooSoft notices in modified files, per GPLv3 §5(a).

## 10. Test plan — headless harness

- Location: `tests/` in the repo (NOT inside `connect_plus/`). Runner: the venv python (`.../AnkiProgramFiles/.venv/bin/python`), plain `pytest` or a bare script — no Anki app, no aqt, no display.
- Harness fixture per test module:
  ```python
  import anki.lang; anki.lang.set_lang("en_US")   # REQUIRED once: field_checksum/strip_html_media
                                                  # raise AttributeError without it (probe-verified)
  from anki.collection import Collection
  col = Collection(os.path.join(scratch_dir, "test.anki2"))  # scratch dir under the session scratchpad
  ```
  `core.py` is loaded standalone: `importlib.util.spec_from_file_location("core", "<repo>/connect_plus/core.py")` — this both avoids executing the package `__init__.py` (web server) and **enforces the no-aqt/no-relative-import rule**: the suite asserts `"aqt" not in sys.modules` after import.
- Every `col` is a scratch collection in a throwaway dir (media folder + backups dir are siblings, auto-created). Never touch `~/Library/Application Support/Anki2/`.
- Coverage: every edge-case list in §4 (they are the test matrix), plus §5 round-trip tests, plus the undo invariants in §3.3.
- `plus.py`/dispatch/rebrand items are covered by a separate live smoke checklist (manual, after installing into a **test** Anki profile): `plusInfo` before profile load; one call per action against a disposable profile; stock-AnkiConnect coexistence (both ports up, Edit dialog opens from both, `guiEditNote` on each); banner strings on 8765 vs 8766; permission prompt title. The smoke test must also verify `Collection.set_deck` exists (per §4.4 note).

---

## 11. Image crop actions (spec revision 2, 2026-08-11)

Two additional actions: **`cropImage`** and **`cropImageOcclusionImage`**, bringing the action count to eleven. `core.PLUS_ACTIONS` remains the single source of truth for the `plusInfo` action list. A `padImage` action was considered and **explicitly rejected** — nothing in this section may ever emit padded output. Directly relevant Qt gotcha (probe-verified on this venv, PyQt6 6.9.1 / Qt 6.9.0): `QImage.copy(QRect)` does **not clamp** a rect that extends past the image — it **pads** the result to the requested size. The pixel crop rect is therefore always clamped to image bounds *before* `copy()` (§11.3), so padding can never occur.

Both actions are non-destructive to media: the cropped result is always written as a **new** media file; the original file is never deleted or overwritten (clients that want cleanup can use upstream `deleteMediaFile` explicitly).

### 11.1 `cropImage`

Crop an existing media image into a new media file, optionally rewriting notes to reference it.

Caveat (document in README too): passing an image-occlusion note in `noteIds` — or cropping an IO note's base image at all — rewrites the filename reference but does **NOT** remap the note's occlusion rects, which stay normalized to the original frame, so every mask will silently misalign (probe-confirmed). Use `cropImageOcclusionImage` (§11.2) for IO notes. No code guard is imposed: an IO note may legitimately reference a non-base image in its Header/Back Extra fields, and rejecting every IO note id would break that case.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `filename` | str | required | Bare filename of an existing file in the collection media dir (no path separators — `os.path.basename(filename) == filename`). |
| `rect` | `{left, top, width, height}` | required | **Normalized 0–1 floats** (fractions of image width/height), consistent with the IO endpoints: `0 <= left,top <= 1`, `0 < width,height <= 1`. Mapped to pixels and clamped per §11.3; a rect that clamps to an empty area is an error. |
| `noteIds` | [int] | omit | If given, every occurrence of the old filename in those notes' fields is rewritten to the new filename via `col.update_note`, all merged into ONE undo entry `"AnkiConnect Plus: Crop Image"` (lazy, per §3.3). Duplicate ids are deduplicated. |

**Returns**

```json
{"newFilename": "diagram-crop.png", "width": 512, "height": 384, "notesUpdated": [1712345678901]}
```
- `newFilename`: the **actual stored name** — the derived name (§11.3 naming) possibly renamed by Anki's media dedup (`<stem>-<40-hex-sha1>.<ext>` on same-name/different-bytes collision; returned by `col.media.write_data`).
- `width`/`height`: pixel dimensions of the cropped image (= the clamped pixel rect's `cw`/`ch`).
- `notesUpdated`: ids of notes whose fields actually changed. Notes passed in `noteIds` that contain no occurrence are left untouched and omitted (not an error).

**Filename rewrite semantics (exact)** — occurrences are matched with `re` using boundary guards so a short filename never matches inside a longer one (`a.png` must not match inside `banana.png`): pattern `(?<![\w./\\-])<escaped filename>(?![\w.-])`, replacement done with a callable so the new name is inserted literally. This rewrites `src="..."`/`src='...'` references as well as bare-text occurrences, in every field of the note.

**Anki/Qt API calls** — PyQt6 (`QImage`, `QRect`, `QBuffer`, `QByteArray`, `QIODevice`) is imported **lazily inside the core function** so `import core` stays Qt-free and headless tests never load Qt unless a crop runs. No `QApplication`/`QGuiApplication` is required for load/crop/save on this build (probe-verified, PNG + JPEG). Encode to bytes via `QBuffer` (no temp files); store via `fname = col.media.write_data(newName, data)` accepting the returned (possibly renamed) name. Note updates: `col.get_note` → field rewrite → `col.update_note` + `merge_undo_entries` into the lazy custom entry.

**Order of operations** — all validation (filename, rect, `noteIds` types, and loading of every referenced note) happens **before the first write**. Then: media write, then note rewrites. A hard error during note updates reverts the merged undo entry (all note changes) and raises `"cropImage failed (note updates reverted): <err>"`; the new media file remains (media writes are not undoable; it is a new file only — harmless orphan, Check Media collects it).

**Error cases** — `"invalid parameter: filename: string required"`; `"invalid parameter: filename: bare media filename required"`; `"media file was not found: <filename>"`; `"could not load image: <filename> (unsupported or corrupt format)"`; `"invalid parameter: rect: object required"` / `"... <key> must be a number"` / `"... left and top must be within 0-1"` / `"... width and height must be within 0-1"`; `"invalid parameter: rect: selects an empty area of <filename> (<W>x<H>)"`; `"could not encode cropped image as <fmt>: <filename>"`; `"invalid parameter: noteIds: ints required"`; `"note was not found: <id>"`.

**Edge cases tests must cover** — crop of a known PNG yields exact pixel dims; original media file still present afterward; `noteIds` rewrite changes `<img src>` and returns the id, single `col.undo()` restores the field; note without any occurrence → untouched, omitted from `notesUpdated`; `banana.png` untouched when cropping `a.png`; rect clamping (`left+width > 1` crops to the image edge, never pads); `left = 1.0` → empty-area error; unknown filename / path-y filename / bad rect types → errors above with no writes; repeat crop with identical params dedups to the same `newFilename`.

### 11.2 `cropImageOcclusionImage`

Crop the base image of a **built-in IO note** and remap every occlusion rect into the cropped frame, as one atomic, undoable operation.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `noteId` | int | required | Must be a native-IO note (`originalStockKind == 6`, same guard as §4.6). |
| `rect` | `{left, top, width, height}` | required | Same normalized shape, validation, and pixel mapping as §11.1. |

**Returns**

```json
{"newFilename": "anatomy-crop.png", "occlusionsKept": 4, "occlusionsClipped": 1, "occlusionsDropped": 2, "cardIds": [...]}
```

**Remap semantics (exact)** — all in pixel space of the ORIGINAL `W×H` image, with `(cx, cy, cw, ch)` the clamped pixel crop rect from §11.3. For each occlusion rect (normalized to the original image): `x0 = left·W`, `y0 = top·H`, `x1 = x0 + width·W`, `y1 = y0 + height·H`; intersect with the crop: `nx0 = max(x0, cx)`, `ny0 = max(y0, cy)`, `nx1 = min(x1, cx+cw)`, `ny1 = min(y1, cy+ch)`.
- Empty intersection (`nx1 ≤ nx0` or `ny1 ≤ ny0`) → the rect is **dropped**.
- A surviving rect whose remapped `width` or `height` would serialize to zero at §5's 4-decimal precision (< 0.00005 normalized) is unrepresentable → also **dropped**.
- Otherwise the rect is kept, renormalized against the cropped frame: `left' = (nx0−cx)/cw`, `top' = (ny0−cy)/ch`, `width' = (nx1−nx0)/cw`, `height' = (ny1−ny0)/ch`, **ordinal preserved**.
- A kept rect counts as **clipped** when its original pixel box extended beyond the crop by more than `1e-6` px on any side (tolerance absorbs float noise from the 4-decimal stored coords).
- Counters: `occlusionsKept` = shapes present in the updated note (**includes** the clipped ones); `occlusionsClipped ⊆ kept`; `kept + dropped` = original shape count.
- `oi`/occlude-inactive is preserved: re-serialization uses `hide_all_guess_one = <note's occludeInactive>` from the §4.5 read. This is exact only when the per-shape `oi` flags are uniform (all shapes carry `oi=1`, or none do — the only states Anki's own editor produces, since it sets `oi` globally). Mixed per-shape `oi` on a hand-edited field is unrepresentable by the single note-level flag (the backend reports `occludeInactive = true` when ANY cloze carries `:oi=1`) and is refused, never silently homogenized.

**Refusals (clear error, zero changes)**
- The crop would drop ALL occlusions → `"crop would remove all occlusions on note <id>"`.
- The note contains non-rect shapes (`ellipse`/`polygon`/`text`, possible on editor-made notes per Deviation #3) → `"cropImageOcclusionImage supports rect occlusions only; note <id> contains a <shape> shape"`. Rationale: §5's serializer emits rects only; proceeding would silently destroy those shapes.
- A rect carries properties other than `oi` (e.g. `angle`, `fill`) → `"cropImageOcclusionImage cannot preserve occlusion properties <names> on note <id>"`. Same rationale (v1 serializer does not emit them).
- The rects carry **mixed** per-shape `oi` flags (some have `oi=1`, some don't) → `"cropImageOcclusionImage cannot preserve mixed oi flags on note <id>"`. Same rationale (§5 serialization is all-or-nothing per note; see the oi bullet above).

**Atomicity / undo (probe-verified pattern)** — read via the §4.5 path; `header`/`backExtra`/`tags` backfilled from the note's own fields via `col._backend.get_image_occlusion_fields` exactly as §4.6. Media write first (not undoable; new file only). Then `target = col.add_custom_undo_entry("AnkiConnect Plus: Crop IO Image")` → write 1: `note.fields[idx.image] = '<img src="<newFilename>">'` (raw filename, double quotes — byte-identical format to what the backend itself writes) via `col.update_note` + merge → write 2: `col.update_image_occlusion_note(noteId, remappedOcclusions, header, backExtra, tags)` + merge. A single `col.undo()` restores BOTH the image field and the occlusion string. Failure between the writes reverts the merged entry and raises `"cropImageOcclusionImage failed (changes reverted): <err>"`.

**`cardIds`** — current card ids after the update, via the card-id location select (explicitly allowed read-only select, §4.4 precedent). Caveat (research-verified): if every shape of some ordinal was dropped, the backend does **not** delete that ordinal's now-empty card; its id still appears in `cardIds` and Empty Cards is the cleanup path. Document in README.

**Error cases** — `"invalid parameter: noteId: int required"`; `"note was not found: <id>"`; `"note is not an image occlusion note: <id>"`; §4.5 read-error path; `"could not parse rect occlusion on note <id>"` (a backend rect shape whose left/top/width/height failed float parsing, i.e. the §4.5 parser fell back to raw properties); `"image occlusion note has no image file: <id>"`; all §11.1 media/rect/format errors; the refusals above.

**Edge cases tests must cover** — rect fully inside → kept unclipped, coords remap exactly; rect straddling a crop edge → kept + clipped, clipped edge lands on the crop boundary (`left' == 0` etc.); rect fully outside → dropped; all-outside → refusal with note byte-identical; kept ordinals round-trip through §4.5 within 1e-4; empty-card gotcha surfaced in `cardIds`; single undo restores original image filename AND original rects; original media file untouched; mixed per-shape `oi` (hand-built occlusions string, `oi=1` on one cloze only) → refusal with note untouched.

### 11.3 Shared crop mechanics

- **Pixel mapping + clamp** (shared by both actions): `cx = clamp(round(left·W), 0, W)`, `cy = clamp(round(top·H), 0, H)`, `cw = min(round(width·W), W−cx)`, `ch = min(round(height·H), H−cy)`. If `cw < 1` or `ch < 1` → empty-area error. Guarantees `copy(QRect(...))` stays within bounds, so Qt's pad behavior is unreachable.
- **Derived naming**: `<stem>-crop.<ext>` keeping the source extension when Qt can encode it; otherwise (readable-but-not-writable formats: `gif`, `svg`, `svgz`, `pdf`, `tga`, or an unknown extension) the crop is re-encoded as PNG under `<stem>-crop.png`. Name collisions are resolved by `col.media.write_data`'s dedup (same bytes → same name reused; different bytes → sha1-renamed) and the returned name is authoritative.
- **Write-format allowlist** (probe-verified on this build): `bmp cur heic heif icns ico jfif jp2 jpeg jpg pbm pgm png ppm tif tiff wbmp webp xbm xpm` (`core.CROP_WRITE_FORMATS`).
- **Headless rule**: all Qt imports live inside the core function bodies (lazy), keeping `core.py`'s module import aqt-free AND Qt-free; no application object is created. Pillow is not a dependency (not installed in the venv).

---

## 12. `renderCard` (spec revision 3, 2026-08-11)

First of three **read-only** actions (`renderCard`, `notesSlim`, `mediaThumbnails` — §§12–14) bringing the action count to fourteen. `core.PLUS_ACTIONS` remains the single source of truth for the `plusInfo` action list. None of the three performs any collection write, media write, or undo-stack change; tests assert `undo_status()` unchanged after each call.

Render cards' question/answer HTML exactly as Anki's own template pipeline produces them.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `cardIds` | [int] | required | Bad ids (and per-card render failures) become per-item `error` entries, never a hard failure. Empty list → `{"cards": []}`. |

**Returns**

```json
{"cards": [
  {"cardId": 1712345678901, "question": "<b>front html</b>", "answer": "…", "css": ".card {…}", "deckName": "HA2::PI 7", "modelName": "Basic", "ord": 0},
  {"cardId": 42, "error": "card was not found: 42"}
]}
```

- `question`/`answer` are the rendered template HTML **without** the `<style>` wrapper; `css` is the notetype styling returned separately (clients wanting the `card.question()` equivalent concatenate `"<style>" + css + "</style>" + question`).
- Audio/TTS: rendered text contains `[anki:play:q:<idx>]` markers in place of `[sound:...]` tags (backend behavior). The referenced filenames live in the render output's `question_av_tags`/`answer_av_tags` and are **not** returned in v1.
- `deckName` is the card's current home deck (`odid` when in a filtered deck) via `col.decks.name(card.current_deck_id())`.
- One entry per input id, in input order; duplicate ids render twice.

**Anki API calls** — `col.get_card(cid)` (`NotFoundError` → per-item `"card was not found: <id>"`); `card.render_output()` (`SP/anki/cards.py:161-170`) → `TemplateRenderOutput` (`SP/anki/template.py:280-293`) with `question_text`/`answer_text`/`css`; `col.decks.name(card.current_deck_id())` (`SP/anki/decks.py:384-388`, `SP/anki/cards.py:194-195`); `card.note_type()["name"]` (`SP/anki/cards.py:180-181`, cached lookup). `anki.template` imports zero aqt — probe-verified headless render of Basic + Cloze cards.

**Error cases** — hard (whole action): `"invalid parameter: cardIds: ints required"` (non-list, or any non-int/bool element). Per-item: `"card was not found: <id>"`; any per-card render exception → `"could not render card <id>: <err>"`.

**Edge cases tests must cover** — Basic card renders (question contains the field text, css non-empty, `ord` 0); cloze question contains `class="cloze"` markup; mixed good/bad ids → per-item errors interleaved in input order with successful renders; a `[sound:...]` field renders with an `[anki:play:` marker in the text; undo queue untouched.

## 13. `notesSlim` (spec revision 3, 2026-08-11)

Compact, paginated, HTML-stripped note reader designed for LLM consumption: deterministic order, bounded field lengths, one round trip. Read-only; issues no SQL.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `query` | str | — | Anki search string, passed **verbatim** to the backend parser (empty string matches all notes). Exactly one of `query`/`noteIds` is required. |
| `noteIds` | [int] | — | Explicit ids; page order = caller order (duplicates allowed and returned twice). |
| `fields` | [str] | `null` | Field-name filter; `null` = all fields. Names not present on a note's model are simply absent for that note (a result set may span models) — never an error. |
| `stripHtml` | bool | `true` | Strips via the backend single-line helper: media filenames preserved, `[sound:...]` tags kept, `<br>`/`<div>` boundaries become single spaces. `false` returns raw field HTML. |
| `maxFieldLength` | int | `400` | Per-field character cap applied AFTER stripping (or to the raw HTML when `stripHtml: false` — may cut mid-tag; it is a preview); longer values are cut at the cap with `…` appended. `0` = no truncation. |
| `offset` | int | `0` | Offset into the full matched id list. |
| `limit` | int | `200` | Must be ≥ 1; values above 2000 are silently clamped to 2000 (`core.NOTES_SLIM_LIMIT_CAP`). |

**Returns**

```json
{"total": 812,
 "notes": [{"noteId": 1712345678901, "modelName": "Cloze", "tags": ["HA2::PI7"],
            "fields": {"Text": "The capital of {{c1::France}} is {{c2::Paris::city hint}}.", "Back Extra": ""}}],
 "nextOffset": 200}
```

- `total` = full match count before pagination; `nextOffset` = `offset + limit` while more ids remain, else `null`.
- **Cloze markup passes through unmodified** under `stripHtml: true`: the backend single-line helper strips HTML only, so `{{c1::...}}` / `{{c2::...::hint}}` markers survive verbatim in the output (probe-verified) — clients must not expect any bracketed-hint conversion.
- **Deterministic order**: query path returns ascending `noteId` (creation order — ids are sorted in core, `find_notes` is called with `order=False`); noteIds path preserves caller order.
- The `fields` output dict is in the note's model field order (filtered by the `fields` param when given).
- noteIds path: an id whose note no longer exists is **silently omitted** from `notes` (this shape has no per-item error entry); `total` still counts every supplied id, so a page can come back shorter than `limit`. Query-path ids always exist (same synchronous handler, §3.1).

**Anki API calls** — `col.find_notes(query, order=False)` (`SP/anki/collection.py:669-683`; result supports `len()` and slicing; `order=False` is the fastest path, ordering is ours) — bad syntax raises `anki.errors.SearchError`, re-raised as `"invalid parameter: query: <backend message>"`; `col.get_note(nid)` (`NotFoundError` → omit, noteIds path only); `note.note_type()` for model name + field order. HTML stripping: `col._backend.html_to_text_line(text=..., preserve_media_filenames=True)` — the module-level `anki.utils.html_to_text_line` routes through the collection-less `current_i18n` backend and raises `CollectionNotOpen` headless (probe-verified gotcha), so the open collection's backend is called directly.

**Error cases** — `"invalid parameter: query: exactly one of query or noteIds required"` (both given or neither); `"invalid parameter: query: string required"`; `"invalid parameter: query: <backend parse error>"`; `"invalid parameter: noteIds: ints required"`; `"invalid parameter: fields: list of strings required"`; `"invalid parameter: stripHtml: boolean required"`; `"invalid parameter: maxFieldLength: int >= 0 required"`; `"invalid parameter: offset: int >= 0 required"`; `"invalid parameter: limit: must be >= 1"`.

**Edge cases tests must cover** — query/noteIds mutual exclusion (both and neither → error); pagination: `total` stable across pages, `nextOffset` chains cover exactly `total`, final page `nextOffset: null`; ascending id order on the query path, caller order on the noteIds path; `stripHtml: true` collapses `<div>` lines to single spaces and keeps media filenames; `stripHtml: false` returns raw HTML; `maxFieldLength` truncates at the cap with `…` appended, `0` disables; `fields` filter returns only the named fields, unknown name absent without error; stale noteId omitted while `total` counts it; empty query string matches all notes; bad search syntax → query error; undo queue untouched.

## 14. `mediaThumbnails` (spec revision 3, 2026-08-11)

Base64 thumbnails of collection media images — aspect-preserved, never upscaled, batched with per-item errors. Pure read: nothing is written to the media folder or the collection.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `filenames` | [str] | required | Bare media filenames (same guard as §11.1: `os.path.basename(name) == name`; empty string fails the guard). Empty list → `{"thumbnails": []}`. |
| `maxDim` | int | `320` | Longest output side. Must be ≥ 1; values above 1024 are silently clamped to 1024 (`core.THUMBNAIL_DIM_CAP`). |
| `format` | str | `"jpeg"` | `"jpeg"` or `"png"` only (`core.THUMBNAIL_FORMATS`). |
| `quality` | int | `70` | JPEG encode quality 0–100; ignored for png (Qt default `-1` passed). |

**Returns**

```json
{"thumbnails": [
  {"filename": "anatomy.png", "data": "<base64>", "width": 320, "height": 214},
  {"filename": "gone.png", "error": "media file was not found: gone.png"}
]}
```

- One entry per input filename, input order, duplicates processed twice.
- `width`/`height` = actual thumbnail pixel dimensions. An image already fitting within `maxDim` on both sides is **not upscaled**: it is returned at native size (still re-encoded to `format`).

**Anki/Qt API calls** — lazy in-function PyQt6 imports exactly like the §11 crop code (`QImage`; `Qt` enums, `QBuffer`/`QByteArray`/`QIODevice` from `QtCore`); no application object needed (probe-verified). Scale: `img.scaled(maxDim, maxDim, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)` (probe-verified positional form), executed **only when** a side exceeds `maxDim` — this conditional is what guarantees no upscaling. Encode to bytes via `QBuffer` (no temp files): `img.save(buffer, format, quality)`, quality `-1` for png. Alpha: Qt's JPEG encoder flattens transparency (no compositing is done here); clients that need alpha request `format: "png"`.

**Order of operations** — batch-level param validation first (hard errors, nothing processed); then per file: bare-name guard → `os.path.isfile` → `QImage` load/null check → conditional scale → encode. Every per-file failure produces a per-item `error` entry and the batch continues.

**Error cases** — hard: `"invalid parameter: filenames: list of strings required"`; `"invalid parameter: maxDim: must be >= 1"`; `"invalid parameter: format: jpeg or png required"`; `"invalid parameter: quality: int 0-100 required"`. Per-item: `"invalid parameter: filenames: bare media filename required"`; `"media file was not found: <filename>"`; `"could not load image: <filename> (unsupported or corrupt format)"`; `"could not encode thumbnail as <format>: <filename>"`.

**Edge cases tests must cover** — wide image (640×160, maxDim 320) → 320×80; tall image scales to the height cap; small image (≤ maxDim both sides) returned at native size, not upscaled; `data` base64 round-trips to a decodable image of the reported dims (verify with QImage in the test); png format preserves the alpha channel; per-item error for a missing and a path-y filename while the rest of the batch succeeds; maxDim clamp at 1024; bad format/quality → hard error, nothing processed; media dir file count identical before/after; undo queue untouched.

---

## 15. `dryRun` mode on the bulk actions (spec revision 4, 2026-08-11)

An optional `dryRun: false` parameter on the three existing bulk actions (`bulkAddNotes`, `bulkUpdateNoteFields`, `bulkAddTags` — param rows added to §§4.1–4.3). **No new action names**: `core.PLUS_ACTIONS` is unchanged by this section. Purpose: preview exactly what a batch would do — which entries pass validation, which get skipped and why — before committing anything.

**Shared-validation invariant (the anti-drift rule)** — the dry path is NOT a reimplementation. Each core function runs its normal code and short-circuits at its zero-write boundary, so dry and real validation are the same lines of code by construction:
- `bulk_add_notes`: the full resolution pass + duplicate precheck (both read-only) run unchanged; the early return sits between the dedup stamping and the write pass.
- `bulk_update_note_fields`: the whole per-entry validation chain (dict/id/fields-or-tags/type checks, `col.get_note` load, whole-entry field validation) runs unchanged; `dryRun` records the id and `continue`s immediately before the try/write block — before the in-memory `Note` object is ever mutated.
- `bulk_add_tags`: top-level validation, `col.get_note`, and the missing-tag computation run unchanged; the short-circuit sits after the `if not missing: continue` no-op filter, so no-op notes are omitted from both lists exactly as in real mode.

**Returns** (same envelope as the real action; the success key is renamed because its semantics change)

```json
{"wouldAdd": 2, "skipped": [{"index": 1, "reason": "duplicate"}], "undoEntry": null}
```
```json
{"wouldUpdate": [1712345678901], "skipped": [{"index": 1, "reason": "note was not found: 42"}], "undoEntry": null}
```

- `bulkAddNotes` → `wouldAdd` is a **count** (note ids do not exist until a real add). `bulkUpdateNoteFields` / `bulkAddTags` → `wouldUpdate` is the **list of note ids** that would be written (ids are known). `skipped` is identical in shape and reason strings to the real path. `undoEntry` is always `null`.
- `bulkAddTags` dry run: notes already having every tag appear in **neither** list (same as real mode).
- Hard parameter errors (`"invalid parameter: notes: list required"` etc.) raise exactly as in real mode — dryRun only suppresses writes, not validation errors.

**Zero-mutation guarantees (provable)** — under `dryRun: true`: no `col.add_note` / `col.update_note` call; no `add_custom_undo_entry` (the lazy `target` is never reached), so `col.undo_status()` is bit-identical before/after; no media write — the `bulkAddNotes` wrapper **skips `_plusEmbedNoteMedia`** because upstream media embedding stores files (consequence, documented limitation: notes carrying `audio`/`video`/`picture` keys are validated on their fields **as submitted**, without media-filename substitution; the real run's substituted fields could in principle differ for first-field emptiness/duplicate checks). `atomic` is accepted but irrelevant (no write-time hard-error path can fire).

**What a dry run cannot predict** — write-time hard errors (the `atomic=false` skipped entries produced by an exception inside the write block). A dry-run "would" verdict is a validation verdict, not a transaction guarantee.

**Edge cases tests must cover** — mixed batch (valid + duplicate + unknown model + empty first field) → `wouldAdd` counts only the valid ones, `skipped` reasons identical to a real run on the same batch; note count / field values / tags unchanged in the DB after each dry call; `undo_status()` unchanged (no entry created, not even an empty one); dry-then-real sequence: the real run's `added`/`updated` lengths match the dry prediction; `bulkAddTags` dry run omits already-tagged notes from both lists; empty `notes` list → `{wouldAdd: 0, skipped: [], undoEntry: null}`; hard param errors still raise under dryRun.

## 16. `bulkSuspend` & `bulkSetDueDate` (spec revision 4, 2026-08-11)

Two scheduler bulk actions, bringing the action count to sixteen. `core.PLUS_ACTIONS` remains the single source of truth for the `plusInfo` action list. Both follow the §3.3 undo conventions with new entry names `"AnkiConnect Plus: Bulk Suspend"` / `"AnkiConnect Plus: Bulk Due Date"`, and both share an id-precheck helper: input `cardIds` are **deduplicated (first occurrence wins) and filtered to existing cards** via `col.get_card` (read-only) before any op — unknown ids are silently dropped, never an error, and backend behavior on unknown ids never enters the contract (Deviation #8).

### 16.1 `bulkSuspend`

**Params**

| name | type | default | notes |
|---|---|---|---|
| `cardIds` | [int] | required | Deduplicated; unknown ids dropped. |
| `suspend` | bool | `true` | `true`: suspend. `false`: unsuspend (backend restore op — **also unburies** buried cards; documented backend behavior). |

**Returns**

```json
{"changed": 2, "undoEntry": "AnkiConnect Plus: Bulk Suspend"}
```
- `changed`: cards whose state actually changed. Suspend direction: backend-authoritative (`OpChangesWithCount.count`); already-suspended cards do not count, buried cards do (they become suspended). Unsuspend direction: precheck count of cards whose queue was negative (suspended −1, sibling-buried −2, manually buried −3) — exactly the set the restore op changes (Deviation #8).
- `changed: 0` → `undoEntry: null` and the undo stack is untouched (a no-op batch is skipped before any op; a backend-reported 0 pops the empty custom entry, Deviation #7 precedent).

**Anki API calls** — `col.get_card(cid)` precheck (`NotFoundError` → drop); `col.sched.suspend_cards(ids) -> OpChangesWithCount` (`SP/anki/scheduler/base.py:153-156`); `col.sched.unsuspend_cards(ids) -> OpChanges` (`base.py:150-151`, backend `restore_buried_and_suspended_cards`); undo per §3.3: `add_custom_undo_entry` **before** the op (the op must merge into it), `merge_undo_entries` after. Only cards that would change are passed to the op.

**Error cases** — `"invalid parameter: cardIds: ints required"`; `"invalid parameter: suspend: boolean required"`; unexpected op failure → `"bulkSuspend failed (batch reverted): <err>"` (custom entry reverted).

**Edge cases tests must cover** — suspend 2 new cards (+1 bogus id in the list) → `changed: 2`, both queues −1, `undo_status().undo` = the entry name, single `col.undo()` restores both queues and pops the entry; suspending an already-suspended card → `changed: 0`, `undoEntry: null`, undo stack unchanged; unsuspend the suspended pair → `changed: 2`, queues restored; unsuspend with nothing suspended → `changed: 0`, no op; duplicate ids counted once; empty `cardIds` → `{changed: 0, undoEntry: null}`.

### 16.2 `bulkSetDueDate`

**Params**

| name | type | default | notes |
|---|---|---|---|
| `cardIds` | [int] | required | Deduplicated; unknown ids dropped. |
| `days` | str | required | Backend grammar: `"0"` = due today, `"5"` = in 5 days, `"1-7"` = uniform-random per card in the range, `"3!"` = also force interval to 3 days (probe-verified). Bad strings raise. |

**Returns**

```json
{"changed": 3, "undoEntry": "AnkiConnect Plus: Bulk Due Date"}
```
- `changed` = count of existing (deduplicated) cards passed to the op — `set_due_date` applies to every one regardless of current state, turning new cards into review cards (probe: new 0/0 → `type=2 queue=2 ivl=1`) (Deviation #8). No existing cards → `{changed: 0, undoEntry: null}`, no op.

**Anki API calls** — `col.get_card` precheck; `col.sched.set_due_date(card_ids, days) -> OpChanges` (`SP/anki/scheduler/base.py:205-227`; the optional `config_key` is not used — no config default is read or written); undo per §3.3 (entry created before the op, merged after). The `days` grammar is pre-validated in core (`re.fullmatch(r'[0-9]+(?:-[0-9]+)?!?', days)` — ASCII digits only, matching what the backend actually accepts) **before** `add_custom_undo_entry`, so a bad string raises `"invalid parameter: days: <bad string>"` with the undo stack genuinely untouched (popping an empty custom entry via `col.undo()` would push a phantom Redo item). The `anki.errors.InvalidInput` handler (message = the bad string; empty custom entry popped, error re-raised house-style) remains as a backstop for grammar drift only.

**Error cases** — `"invalid parameter: cardIds: ints required"`; `"invalid parameter: days: string like \"0\" or \"1-7\" required"` (non-string or empty); `"invalid parameter: days: <bad string>"` (grammar rejected by core's pre-validation — same message shape as the backend's InvalidInput, whose message is the echoed bad string; undo stack left untouched, verified bit-identical `undo_status()`); unexpected op failure → `"bulkSetDueDate failed (batch reverted): <err>"`.

**Edge cases tests must cover** — `"0"` on a new card → due today, `type=2 queue=2`, single `col.undo()` restores the new state and pops the entry; `"1-7"` on several cards → each due within [1,7] days; `"3!"` → due 3 and `ivl` 3; `"bogus"` → `invalid parameter: days:` error AND `undo_status()` unchanged (no empty entry left); only-bogus ids → `{changed: 0, undoEntry: null}`; duplicate ids counted once.

## 17. `exportDeckApkg` (spec revision 4, 2026-08-11)

Export one deck (including its subdecks) to an `.apkg` file on disk, bringing the action count to seventeen. `core.PLUS_ACTIONS` remains the single source of truth for the `plusInfo` action list. Runs on the **open** collection (no close/reopen — that is only needed for full `.colpkg` exports); media is written synchronously into the zip during the call.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `deckName` | str | required | Must exist (`col.decks.id_for_name`); export covers the deck **and all its subdecks** (backend `DeckIdLimit` semantics). |
| `outPath` | str | `null` | Target file path (`~` expanded). Default: `~/Downloads/<sanitized-deck>-<YYYY-MM-DD>.apkg` (`core.EXPORT_DEFAULT_DIR`). The parent directory must already exist. |
| `includeScheduling` | bool | `true` | Maps to proto `with_scheduling`. `false` exports notes/cards as new. |
| `includeMedia` | bool | `true` | Maps to proto `with_media`. `false` still writes an (empty) `media` zip member. |

**Returns**

```json
{"path": "/Users/mattyc/Downloads/HA2-PI-7-2026-08-11.apkg", "sizeBytes": 152344, "notesExported": 214}
```
- `path`: the file actually written (after collision suffixing). `sizeBytes`: `os.path.getsize` of it. `notesExported`: the backend's return value (number of notes in the package) — harmless extension beyond the locked `{path, sizeBytes}` shape, kept because the count is authoritative and free.

**Filename semantics (exact)** — sanitized stem: `re.sub(r'[^\w.-]+', '-', deckName).strip('-.')`, falling back to `"deck"` when nothing survives (`\w` is unicode-aware: unicode letters/digits/underscore, dot, dash survive; `::`, spaces, and runs of other characters collapse to single dashes — `"HA2::PI 7"` → `"HA2-PI-7"`). **Never overwrite**: while the target exists, `-2`, `-3`, … is appended before the extension (`report.apkg` → `report-2.apkg`). The exists-check→write sequence is race-free per §3.1 (handlers serialized on the main thread).

**Anki API calls** — `col.decks.id_for_name(deckName)`; `col.export_anki_package(out_path=..., options=..., limit=anki.collection.DeckIdLimit(did)) -> int` (number of notes exported; `SP/anki/collection.py:367-374`, kw-only); `options = anki.collection.ExportAnkiPackageOptions(with_scheduling=includeScheduling, with_deck_configs=False, with_media=includeMedia, legacy=False)` (proto fields per `SP/anki/_backend/import_export_pb2.pyi:250-268`). Fixed choices, documented: `with_deck_configs=False` (deck presets are never exported — matches Anki's own dialog default and keeps imports from mutating the receiving collection's presets); `legacy=False` (modern zstd package, Anki 2.1.50+; zip members `meta`/`collection.anki21b`/`collection.anki2`/`media`+numbered files).

**Order of operations** — all validation (param types, deck lookup, output-directory existence) before any filesystem write; then collision suffixing; then the export call. The export itself is read-only with respect to the collection: no undo entry is created and `undo_status()` is unchanged (tests assert this).

**Error cases** — `"invalid parameter: deckName: string required"` (non-string or empty); `"deck was not found: <name>"`; `"invalid parameter: outPath: string required"` (non-string or empty string); `"invalid parameter: outPath: is a directory: <path>"` (outPath resolves to an existing directory, or ends in a path separator — outPath must be a file path; without this guard the collision loop would write a surprise sibling like `<dir>-2`); `"invalid parameter: includeScheduling: boolean required"`; `"invalid parameter: includeMedia: boolean required"`; `"output directory was not found: <dir>"`; backend export failures surface through the envelope verbatim.

**Edge cases tests must cover** — export of a small deck with a media-bearing note → file exists, `sizeBytes` matches on-disk size, zip members include `media`, `notesExported` correct; subdeck note included when exporting the parent; repeat export to the same path → `-2` (then `-3`) suffix, first file untouched; `includeMedia: false` → smaller file, media member empty; `includeScheduling: false` accepted; unknown deck / bad outPath dir → error with no file written; sanitized default filename for a `::`-nested deck name; undo queue untouched.

## 18. `syncStatus` & `syncNow` (spec revision 5, 2026-08-11)

AnkiWeb sync, bringing the action count to nineteen. `core.PLUS_ACTIONS` remains the single source of truth for the `plusInfo` action list. Locked design: **normal sync only, asynchronous job + polling, zero dialogs**. A required full sync is always REFUSED (surfaced as job error `full_sync_required`); `full_upload_or_download` is never called, and the aqt GUI flows (`mw.on_sync_button_clicked`, `mw._sync_collection_and_media`, `aqt.sync.sync_collection`) are never routed through — they open modal dialogs that hang unattended. Stock AnkiConnect's `sync` action (`addons21/2055492159/__init__.py:502-511`) blocks the main thread for the whole network round trip and then launches the GUI sync flow a second time via `mw.onSync()`; deliberately not copied.

**Job model** — one job slot per add-on instance, created lazily on the mixin (`PlusMixin` has no `__init__`; `getattr` guard): `{state: "idle"|"syncing"|"media_syncing"|"done"|"error", startedMs, result, error}`. The dict is only ever mutated on the Qt **main thread**: HTTP handlers run there (§3.1) and `mw.taskman.run_in_background`'s `on_done` is marshalled there (`SP/aqt/taskman.py:86-88`) — no locking needed, ever. `result` = `{serverMessage, hostNumber}` once the collection phase succeeds (`serverMessage` is returned verbatim, never shown in a dialog); `error` = `{code, message}`. `media_syncing` → `done`/`error` is driven by a **plus-owned media watcher**, not by polling probes from `syncStatus`/`syncNow`: `col.media_sync_status()` `take()`s and `join()`s the *finished* backend media task (rslib `backend/sync.rs`), so a media-sync failure raises **exactly once**, to whichever caller observes it first (probe-verified: first call raises, every later call returns `active=False` cleanly). `_plusSyncDone` therefore starts its own watcher via `mw.taskman.run_in_background(..., uses_collection=False)` that mirrors aqt's monitor loop (`SP/aqt/mediasync.py:57-65`: poll `media_sync_status()` every 0.25 s until inactive) and lets the failure raise into its future; `on_done` (main thread) sets `state=done`, or `state=error, code=media_sync_failed`. `mw.media_syncer.start_monitoring()` is deliberately **not** called: its monitor thread would consume the single raise before plus could (making `media_sync_failed` unreachable) and pops a non-modal `show_info` dialog on failure (`SP/aqt/mediasync.py:89-96`) — zero dialogs. `gui_hooks.media_sync_did_start_or_stop(True/False)` is fired around the watch so the toolbar sync icon still tracks. If `mw.col` is None when the watch would start, the job goes straight to `state=error, code=media_sync_failed` — an unverified media sync is never reported `done`.

**Core split (§2.1 rules hold)** — pure helpers in `core.py`, zero aqt: `SYNC_STATUS_REQUIRED` / `SYNC_COLLECTION_REQUIRED` (proto-enum→string maps), `bounded_sync_auth(auth, timeout_secs)` (copy of a `SyncAuth` with `io_timeout_secs` clamped for status probes; `anki.sync` import is aqt-free), `local_sync_dirty(col)` (read-only `select ls, mod from col` + `col.schema_changed()`; returns `{lastSyncMs, modMs, dirty}` with `dirty = mod > ls or schema_changed`), `classify_sync_error(exc)` (`SyncError` kind `AUTH` → `auth_failed`, other `SyncError` → `error`, `NetworkError` → `offline`, `Interrupted` → `aborted`, anything else → `error`). Wrappers + job state machine live in `plus.py`.

### 18.1 `syncNow`

Start a normal collection sync as a background job. Returns immediately; poll `syncStatus`.

**Params** — none. Media syncing is not a parameter: it follows the profile setting `mw.pm.media_syncing_enabled()` (`SP/aqt/profiles.py:672`), same as Anki's own sync button.

**Returns**

```json
{"started": true, "mediaSync": true}
```
```json
{"started": false, "reason": "already_syncing"}
```

Refusal reasons (checked in order, never raise): `collection_unavailable` (`mw.col is None` — profile screen), `not_logged_in` (`mw.pm.sync_auth()` is None), `already_syncing` (job state `syncing`/`media_syncing` — the plus media watcher transitions the job out of `media_syncing` on its own, no promotion probe), `media_sync_in_progress` (`mw.media_syncer.is_syncing()` — aqt's periodic 15-min media sync or auto-sync owns the media queue; treat as state, not error).

**Flow (exact)** — set job `{state: syncing, startedMs: now-ms, result: null, error: null}`; fire `aqt.gui_hooks.sync_will_start()`; `mw.taskman.run_in_background(lambda: col.sync_collection(auth, sync_media), on_done)` — `col.sync_collection(auth, sync_media) -> SyncCollectionResponse` (`SP/anki/collection.py:1146`) performs the whole network sync synchronously on the worker thread; the full (unclamped) `pm.sync_auth()` is used. `on_done` (main thread) mirrors `SP/aqt/sync.py:105-125` + `SP/aqt/main.py:1104-1113` **including on error**: `col._load_scheduler()` (scheduler version may have changed); on exception → `classify_sync_error`, on `auth_failed` also `mw.pm.clear_sync_auth()` (mirrors `handle_sync_error`), job `state=error`; on success → `pm.set_host_number(out.host_number)`, persist `out.new_endpoint` via `pm.set_current_sync_url`, `result={serverMessage, hostNumber}`; `out.required != NO_CHANGES` (1–4, Deviation #9d) → `state=error, code=full_sync_required`; else `state=media_syncing` + the plus-owned media watcher (see the job model — the backend media sync was auto-started by `sync_collection(…, sync_media=True)`; aqt's `start_monitoring` is deliberately not used) when media syncing is on, `state=done` when off. Finally (all paths): `col.models._clear_cache()`, `gui_hooks.sync_did_finish()`, `mw.reset()`, `mw.toolbar.redraw()`, `mw.flags.require_refresh()` (the last two mirror `_refresh_after_sync`, `SP/aqt/main.py:1098-1100` — without the flags refresh, flag-name changes synced down keep stale labels in an open Browser sidebar).

**Error codes (in `job.error.code`)** — `auth_failed`, `offline`, `aborted`, `full_sync_required`, `media_sync_failed` (set by the plus media watcher), `error`.

**Gotchas (documented behavior)** — during the collection phase the backend holds the collection lock: every other collection-touching action on either port blocks until it finishes. Auto-sync on profile open/close can already own a sync; `syncNow` then refuses with `media_sync_in_progress` (media phase) — the collection phase of an aqt-driven sync is not detectable and a concurrent `syncNow` would queue behind it on the taskman collection executor; accepted for a personal tool.

### 18.2 `syncStatus`

Read-only status probe. Never starts a sync, never clears auth (Deviation #9a), never opens dialogs.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `localOnly` | bool | `false` | `true`: no network I/O at all — `required` computed from local dirtiness only. |
| `timeoutSecs` | int | `8` | 1–300. Network timeout for the status round-trip via `bounded_sync_auth` (default `pm.network_timeout()` is 60 s — too long for a poll on the main thread). |

**Returns**

```json
{"loggedIn": true, "job": {"state": "done", "startedMs": 1754924000000, "result": {"serverMessage": "", "hostNumber": 0}, "error": null},
 "mediaSyncing": false, "mediaSecondsSinceLastSync": 42, "lastSyncMs": 1754924001234, "modMs": 1754924001234, "required": "no_changes"}
```

- `job`: a copy of the job dict (the plus media watcher keeps it current on its own — see the job model).
- `mediaSyncing` / `mediaSecondsSinceLastSync`: `mw.media_syncer.is_syncing()` / `.seconds_since_last_sync()` (`SP/aqt/mediasync.py:105,131`; the latter is 0 while syncing). These track only **aqt-owned** media syncs (periodic 15-min / auto-sync): a plus-initiated media phase never goes through `MediaSyncer`, is visible as `job.state == "media_syncing"` instead, and does not advance `mediaSecondsSinceLastSync`.
- `lastSyncMs` / `modMs`: from `local_sync_dirty` (`ls` = last-sync ms epoch, `mod` = collection mod-time ms). `null` when `mw.col` is None **or** the job is in state `syncing` (Deviation #9b — the backend holds the collection lock; no col/db access is attempted at all in that state, and `required` is likewise `null`).
- `required`: `not_logged_in` | `no_changes` | `normal_sync` | `full_sync_required` | `offline` | `auth_failed` | `error` | (localOnly) `normal_sync`/`unknown_no_network` | `null` (job `syncing`). `not_logged_in` takes precedence over collection unavailability: logged out with `mw.col` None still reports `not_logged_in` (the more informative answer), never `null`. Network path: `col.sync_status(bounded_auth) -> SyncStatusResponse` (`SP/anki/collection.py:1152`; backend answers locally with no network when the collection is dirty, serves a 300 s cache when clean, else one small round-trip); `new_endpoint` persisted via `pm.set_current_sync_url` (mirrors `SP/aqt/sync.py:57-58`). Exceptions map through `classify_sync_error` with `aborted` coerced to `error` (Deviation #9c). `localOnly` path: `normal_sync` if dirty else `unknown_no_network` (a clean local state cannot rule out server-side changes without the network). Logged in + `mw.col` None → `error`.

**Verified-synced contract (for clients)** — the collection is known synced iff `job.state == "done" AND required == "no_changes" AND mediaSyncing == false`. Anything less (job `error`, `required` `normal_sync`/`null`, media still running) means "not verified".

**Error cases** — `"invalid parameter: localOnly: boolean required"`; `"invalid parameter: timeoutSecs: int 1-300 required"`. Everything else is expressed in the return value, never raised.

**Edge cases tests must cover (headless, ZERO network)** — `local_sync_dirty` on a fresh scratch collection (`mod > ls` after a write → dirty; `lastSyncMs`/`modMs` ints); `classify_sync_error` over synthetic `SyncError(kind=AUTH)` / `SyncError(kind=OTHER)` / `NetworkError` / `Interrupted` / plain `Exception` → exact code strings; `bounded_sync_auth` clamps `io_timeout_secs`, preserves `hkey`, maps empty-string endpoint to unset; enum maps cover proto values 0–2 / 0–4 and match the installed `sync_pb2` constants; both actions present in `PLUS_ACTIONS`; headless `core.py` import still keeps `aqt`/`PyQt6` out of `sys.modules`. Documented headless edge case (live-Anki behavior, not headless-testable): logged out + `mw.col` None → `required` `not_logged_in` (precedence rule above). The network paths (`sync_status`/`sync_collection` round-trips) are exercised only manually against a live logged-in Anki — never from the test suite.

## 19. AnkiHub suggestion bridge (spec revision 6, 2026-08-11)

`ankihubStatus`, `ankihubSuggestNoteUpdate`, `ankihubSuggestNewNote` — bringing the action count to twenty-two. The bridge REUSES the installed AnkiHub add-on (package `1322529746`, tested version **2026-08-10.1**, AnkiHub API version 24.0) as a library: its own `main.suggestions` functions compute the field/tag diff against the local AnkiHub DB, rename+upload media, and submit — this codebase re-implements none of that. The add-on directory is read-only to us; `core.py` gains only pure helpers and never imports the add-on (nor aqt).

**Etiquette stance (locked)** — deliberately NO bulk suggestion action. The add-on's `suggest_notes_in_bulk` exists and is intentionally not wrapped: unattended mass suggestions to shared decks (especially the AnKing deck, where Matt is a plain subscriber) would be poor citizenship toward maintainers. One reviewed suggestion per call; batching is the caller's explicit, visible loop.

**Module access (plus.py)** — the folder name `1322529746` is not a valid identifier, so modules are reached with `importlib.import_module`. Guards, in order: package present in `mw.addonManager.allAddons()` else `ANKIHUB_ADDON_MISSING`; `isEnabled('1322529746')` else `ANKIHUB_ADDON_DISABLED`; **`'1322529746' in sys.modules` else `ANKIHUB_ADDON_DISABLED` ("restart Anki")** — when Anki itself loaded the add-on the import is a cached no-op, and when it didn't (enabled without restart), importing it ourselves would run its `entry_point` (real AnkiHub sync machinery), so it is never attempted. Modules used: `.main.suggestions`, `.ankihub_client.models`, `.ankihub_client.ankihub_client`, `.settings`, `.db`, `.gui.media_sync`. The stored token is NEVER read or logged — only `settings.config.is_logged_in()`.

**Feature detection (before every call)** — `inspect.signature` over each function the bridge passes kwargs to (`suggest_note_update`, `suggest_new_note`, `resubmit_new_note_as_change_suggestion`, `has_empty_first_field`, `parse_duplicate_anki_id_error`): its parameters must be a superset of `core.ANKIHUB_REQUIRED_SIGNATURES[name]`. Additionally `SuggestionType` must still carry all nine wire values (the enum values are `(wire, label)` tuples; wire = `value[0]`), `ChangeSuggestionResult` all four members, and the `media_sync`/`config`/`ankihub_db` singletons the attributes used — for `config` that is `is_logged_in` (callable) **and** `anking_deck_id` (attribute presence via `hasattr`; `None` is a legitimate value, but absence would make the unguarded AnKing `SOURCE_REQUIRED` gate in `ankihubSuggestNoteUpdate` raise a raw `AttributeError`). Any drift (or import/attribute error) → `INCOMPATIBLE_ANKIHUB_ADDON` naming installed vs tested version and the specific problems.

**Threading** — both suggest actions run synchronously on the Qt main thread, the same context as the add-on's own single-note dialog flow (`gui/suggestion_dialog.py:339-391`); worst case UI freeze = the AnkiHub client's 10 s connect + 20 s read timeouts.

**Media side effect (documented)** — when the note references newly-added media, the add-on content-hash **renames those files across the whole collection** (raw SQL inside the add-on, not undoable) before uploading them to AnkiHub S3 in the background via `media_sync.start_media_upload`. This is the add-on's own standard behavior for every suggestion; it is inherited, not added.

**Error taxonomy** — semantic/flow errors raise `"<CODE>: <message>"` (parse with `error.split(": ", 1)[0]`): `ANKIHUB_ADDON_MISSING`, `ANKIHUB_ADDON_DISABLED`, `ANKIHUB_NOT_LOGGED_IN` (local `is_logged_in()` false, or HTTP 401 = token rejected), `NOT_AN_ANKIHUB_NOTE`, `NOTE_DELETED_ON_ANKIHUB` (HTTP 404 raised outside `suggest_note_update`'s own catch, or a duplicate-conflict whose conflicting note is soft-deleted), `VALIDATION_ERROR` (HTTP 400 body passthrough as compact JSON; when the body contains the server's "don't have any changes to the original note" error the message gets **"sync with AnkiHub first, then re-suggest"** advice appended — the local AnkiHub DB is the diff baseline and may be behind the server revision), `PERMISSION_DENIED` (HTTP 403 `detail`), `RATE_LIMITED` (HTTP 429), `NETWORK_ERROR` (`AnkiHubRequestException` = offline/transport, or any unexpected HTTP status incl. 5xx), `INCOMPATIBLE_ANKIHUB_ADDON`, `SOURCE_REQUIRED`, `RATIONALE_INVALID`. Parameter-shape errors keep §3.2 house style (Deviation #10a).

**Core split (§2.1 rules hold)** — pure, aqt-free, addon-free helpers in `core.py`: constants (`ANKIHUB_ADDON_PACKAGE`, `ANKIHUB_TESTED_ADDON_VERSION`, `ANKIHUB_RATIONALE_MAX_LENGTH` = 1024 — the limit lives only in the add-on's dialog widget, so the API enforces it here; the widget's trim loop deletes while `len >= 1024` (`suggestion_dialog.py:676-677`), so the dialog's effective cap — byte-matched by the API — is **1023** characters (server acceptance of a 1024th character is unverified: testing it would need an AnkiHub network call) —, `ANKIHUB_CHANGE_TYPES`, `ANKIHUB_SOURCE_TYPES_BY_CHANGE_TYPE`, `ANKIHUB_OPTIONAL_SOURCE_TYPES`, `ANKIHUB_SOURCE_REQUIRED_CHANGE_TYPES`, `ANKIHUB_UWORLD_STEPS`, `ANKIHUB_CHANGE_RESULTS`, `ANKIHUB_REQUIRED_SIGNATURES`), `validate_ankihub_change_type`, `validate_ankihub_rationale` (non-empty after strip, ≤1023 — raises at `len >= 1024`, matching the dialog), `ankihub_comment_for_update` / `ankihub_comment_for_new_note` / `_ankihub_source_parts` (the exact dialog Source-line format), `map_ankihub_http_error`, `map_ankihub_change_result`, `ankihub_missing_params`. Everything touching aqt or the add-on lives in `plus.py`.

### 19.1 `ankihubStatus`

Read-only probe. NEVER network, never imports an add-on Anki did not load itself, never raises for a missing/disabled add-on (it reports instead).

**Returns** `{installed, enabled, loggedIn, addonVersion, testedAddonVersion: "2026-08-10.1", appUrl, decks, compatible}` (+ `problems: [str]` when something is off). `addonVersion` = the add-on's `manifest.json` `version`, `VERSION` file fallback, `null` if unreadable (readable even when the add-on is disabled). `decks` from the add-on's private config (in-memory, no network): `[{ankihubDeckId (uuid str), ankiDeckId (int), name, userRelation ('owner'|'maintainer'|'subscriber'|null), isAnkingDeck}]`. `compatible` = the §19 feature-detect passed. When missing/disabled/unloaded: `loggedIn=false, appUrl=null, decks=[], compatible=false`.

### 19.2 `ankihubSuggestNoteUpdate`

Submit ONE change suggestion for an existing AnkiHub note, via the add-on's `suggest_note_update` (`main/suggestions.py:321`) with `media_upload_cb=media_sync.start_media_upload` — exactly the call the add-on's own dialog makes.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `note` | int | — | Anki note id. Must map to an AnkiHub note (`ankihub_db.ankihub_nid_for_anki_nid`) else `NOT_AN_ANKIHUB_NOTE`. |
| `changeType` | str | — | SuggestionType wire value: `updated_content`, `new_content`, `spelling/grammar`, `content_error`, `new_card_to_add`, `new_tags`, `updated_tags`, `delete`, `other`. |
| `rationale` | str | — | Non-empty, ≤1023 chars (the dialog's `while len >= 1024` trim loop caps at 1023; matched exactly), else `RATIONALE_INVALID`. |
| `source` | object | `null` | `{type, text[, step]}`. See Source rules below. |
| `autoAccept` | bool | `false` | Only effective where the user is owner/maintainer (e.g. Matt's BSOM HA2 deck); pointless on subscriber decks (AnKing). |

**Source rules (replicating the dialog, `suggestion_dialog.py:507-512, 778-786, 829-846`)** — a Source exists only where the dialog shows one: (a) `new_content`/`updated_content` on the **AnKing deck** (`ankihub_did_for_anki_nid(note) == config.anking_deck_id`): REQUIRED — `source` must be present with `type` in `AMBOSS | UWorld | Society Guidelines | Other` and non-empty `text`, else `SOURCE_REQUIRED`; (b) `delete` on any deck: optional, `type` must be `Duplicate Note`, blank text folds nothing. Everywhere else a passed `source` is rejected (`invalid parameter`). The folded comment is `rationale + "\nSource: {type} - {text}"`, with UWorld's text prefixed `"Step {step} "` (`step` int 1–3, required for UWorld, rejected on other types — Deviation #10b). Tags are NOT parameters: the add-on's diff computes added/removed tags itself.

**Returns** `{"result": "success"|"noChanges"|"notFoundOnAnkiHub"|"emptyFirstField", "comment": "<final comment as submitted>"}` — the four `ChangeSuggestionResult` outcomes, never raised. `noChanges` means the diff vs the LOCAL AnkiHub DB was empty — the note may still differ from the server; syncing with AnkiHub first updates the baseline. `notFoundOnAnkiHub` = deleted/tombstoned there.

### 19.3 `ankihubSuggestNewNote`

Submit ONE new-note suggestion via the add-on's `suggest_new_note` (`main/suggestions.py:369`).

**Params** — `note` (int; must NOT already be on AnkiHub, else `VALIDATION_ERROR` pointing at `ankihubSuggestNoteUpdate`), `rationale` (as above), `source` (optional, `AMBOSS | UWorld | Society Guidelines | Other`; folded identically — an API extension, the dialog's new-note flow has no Source widget, Deviation #10c), `deckId` (optional AnkiHub deck uuid string; default resolves via `ankihub_db.ankihub_did_for_note_type(note.mid)`, else `NOT_AN_ANKIHUB_NOTE` asking for an explicit `deckId`), `autoAccept` (false), `resubmitAsChangeOnDuplicate` (true).

**Flow** — empty first field short-circuits to `{"result": "emptyFirstField"}` before any network (mirrors the dialog's pre-submit check, `suggestion_dialog.py:368`). On the server's duplicate-anki_id 400 (`parse_duplicate_anki_id_error`): conflicting note soft-deleted → `NOTE_DELETED_ON_ANKIHUB`; otherwise, with `resubmitAsChangeOnDuplicate` true and a conflicting id present, the suggestion is resubmitted via `resubmit_new_note_as_change_suggestion` with change type `updated_content` and the same comment — mirroring the add-on's own conflict dialog (`suggestion_dialog.py:208-228`; media was already renamed+uploaded by the failed submit and is not re-uploaded). With the flag false (or no conflicting id from an older server) the 400 maps generically to `VALIDATION_ERROR`.

**Returns** `{"result": "success"|"noChanges"|"notFoundOnAnkiHub"|"emptyFirstField", "resubmittedAsChange": bool}`. `noChanges` from the direct path = the add-on found nothing to submit; from the resubmit path = server-diff empty.

**Headless test scope (ZERO network, ZERO add-on imports)** — `tests/headless_ankihub_test.py` covers only the pure `core.py` helpers: the three actions in `PLUS_ACTIONS`; constants incl. the nine wire values and the source-type matrix; change-type/rationale validation; the full Source enforcement matrix (AnKing required, non-AnKing rejected, delete optional, UWorld step, unknown keys/shapes); exact folded-comment strings; HTTP error mapping incl. the no-changes advice and 5xx→`NETWORK_ERROR`; result mapping incl. the unknown-member `INCOMPATIBLE_ANKIHUB_ADDON` path; `ankihub_missing_params`; and that neither `aqt` nor the `1322529746` package ever enters `sys.modules`. The live paths (`ankihubStatus` against the running add-on, actual suggestion submission) are manual-only — never from tests (HARD RULE: no AnkiHub network calls from automation).
