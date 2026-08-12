# AnkiConnect Plus — Implementation Specification

Version: 1.0.0 (spec revision 1, 2026-08-11)
Target Anki: 25.09.4 (Qt6, python 3.13). Fork of AnkiConnect (GPLv3) by Alex Yatskov / FooSoft.
Working copy: `/Users/mattyc/Downloads/anki-connect-plus/connect_plus/`
Venv python for all headless execution/tests: `/Users/mattyc/Library/Application Support/AnkiProgramFiles/.venv/bin/python`
Anki packages: `/Users/mattyc/Library/Application Support/AnkiProgramFiles/.venv/lib/python3.13/site-packages` (referred to below as `SP`).

HARD RULES (repeated from project charter, enforced by this spec):
- Never modify anything under `~/Library/Application Support/Anki2/` and never write to the user's real collection during development/testing. All tests run against scratch `.anki2` collections.
- Raw `col.db` **writes are forbidden everywhere** in this codebase. Read-only `SELECT` statements are allowed only where this spec explicitly says so (`queryRevlog`, the bulkAddNotes csum precheck, and note-id/card-id location selects). Rationale: raw non-select SQL through `DBProxy` wipes the entire undo queue, and raw note updates bypass `mod`/`usn` bookkeeping, silently breaking sync (verified in research).
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
5. **New-action reference**: params/returns/errors for the nine actions (condensed from §4), incl. the `interval` sign convention and `type` enum for queryRevlog, the atomic/undo contract for bulks, deviations #1–#5, and one curl example, e.g.:
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
