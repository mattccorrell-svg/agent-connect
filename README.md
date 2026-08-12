# AnkiConnect Plus

A personal fork of AnkiConnect adding bulk note and scheduler actions, image-occlusion, image-crop, card-render, slim-note-read, media-thumbnail, revlog, backup, and deck-export actions, served on port **8766**.

## Credit and license

Derived from **AnkiConnect** by **Alex Yatskov (FooSoft Productions)** — <https://foosoft.net/projects/anki-connect/> (source: <https://git.sr.ht/~foosoft/anki-connect>), licensed under the **GNU GPLv3**. This fork remains GPLv3 — see [LICENSE](LICENSE).

## Install (manual)

Copy or symlink the `connect_plus/` folder into Anki's add-on directory as exactly `connect_plus` (the folder name is load-bearing — config is keyed to it):

```bash
ln -s /Users/mattyc/Downloads/anki-connect-plus/connect_plus "~/Library/Application Support/Anki2/addons21/connect_plus"
```

(or copy `connect_plus/` there). Restart Anki.

## Coexistence with stock AnkiConnect

Runs alongside stock AnkiConnect (add-on `2055492159`) in the same Anki: stock on port **8765**, Plus on **8766**. All upstream actions are also served on 8766. Configs and permission stores are fully independent. Environment overrides are `ANKICONNECT_PLUS_BIND_ADDRESS` / `ANKICONNECT_PLUS_CORS_ORIGIN`. The empty-body banner on 8766 reads `AnkiConnect Plus v.6` — clients that sniff for the exact string `AnkiConnect v.6` (Yomitan-style) should point at stock on 8765 instead.

## Usage

Same JSON-RPC-over-HTTP protocol as upstream, on port 8766:

```bash
curl localhost:8766 -d '{"action":"plusInfo","version":6}'
```

## New actions

| Action | Summary |
|---|---|
| `bulkAddNotes` | Add many notes with one undo entry, fast duplicate pre-check, and per-note error reporting. Params: `notes` (upstream `addNotes` shape), `atomic` (default `true`), `allowDuplicates` (default `false`; per-note `options.allowDuplicate` overrides), `dryRun` (default `false` — see dry-run note below; returns `{wouldAdd: <count>, skipped, undoEntry: null}`). Returns `{added, skipped: [{index, reason}], undoEntry}`. |
| `bulkUpdateNoteFields` | Update fields and/or tags on many notes (`notes: [{id, fields?, tags?}]`; `tags` replaces the whole tag list). One undo entry; same atomic contract. `dryRun` (default `false`) returns `{wouldUpdate: [noteIds], skipped, undoEntry: null}`. Returns `{updated, skipped, undoEntry}`. |
| `bulkAddTags` | Add tags (`str` split on whitespace, or list) to many notes by id. Only notes actually changed are written and reported in `updated`. `dryRun` (default `false`) returns `{wouldUpdate: [noteIds], skipped, undoEntry: null}` — already-fully-tagged notes appear in neither list, same as real mode. Returns `{updated, skipped, undoEntry}`. |
| `addImageOcclusionNote` | Create a native (built-in) Image Occlusion note from an image `{path}` or `{data, filename}` plus `occlusions` (native string, or array of normalized 0–1 rects with optional `ordinal`), `header`, `backExtra`, `tags`, `deckName`, `hideAllGuessOne`. Returns `{noteId, cardIds}`. |
| `getImageOcclusionNote` | Read an IO note: `{imageFilename, occlusions[] (one entry per shape with ordinal; rects as floats, other shapes as raw properties), header, backExtra, tags, occludeInactive}`. |
| `updateImageOcclusionNote` | Update any subset of `occlusions` / `header` / `backExtra` / `tags` on an IO note (omitted params are kept exactly). Returns `null`. The image itself cannot be changed here — `cropImageOcclusionImage` is the supported way to change (crop) it. |
| `cropImage` | Crop a media image into a **new** media file (the original is kept). Params: `filename` (bare media filename), `rect` `{left, top, width, height}` as normalized 0–1 floats (clamped to the image, never padded), optional `noteIds` (every occurrence of the old filename in those notes' fields is rewritten to the new one, one undo entry). Returns `{newFilename, width, height, notesUpdated}`. Not for IO base images — see semantics below. |
| `cropImageOcclusionImage` | Crop a native IO note's base image and remap every occlusion rect into the cropped frame, atomically (one undo restores both the image and the rects). Params: `noteId`, `rect` (same normalized shape). Rects falling fully outside the crop are dropped; straddling rects are clipped to the crop edge; dropping all rects is refused. Returns `{newFilename, occlusionsKept, occlusionsClipped, occlusionsDropped, cardIds}`. |
| `queryRevlog` | Read-only review-history query filtered by `cardIds` / `noteIds` / `deckName` (incl. subdecks) / `sinceMs` (inclusive) / `untilMs` (exclusive), `limit` default 5000. Returns `{rows}`. |
| `createBackup` | Trigger a `.colpkg` backup into the profile's `backups/` folder. `{force}` default `true`. Returns `{created: bool}` — `false` means nothing changed since the last backup, not a failure. |
| `plusInfo` | Version/action/docs metadata for this add-on. Works with no profile open. |
| `renderCard` | Render cards' question/answer HTML exactly as Anki's template pipeline produces them. Params: `cardIds`. Returns `{cards: [{cardId, question, answer, css, deckName, modelName, ord}]}` — one entry per input id in input order; bad ids and per-card render failures become per-item `{cardId, error}` entries, never a hard failure. `question`/`answer` exclude the `<style>` wrapper (`css` is returned separately); `[sound:...]` tags render as `[anki:play:...]` markers. Read-only, undo stack untouched. |
| `notesSlim` | Compact, paginated, HTML-stripped note reader (built for LLM consumption). Params: exactly one of `query` (Anki search, verbatim; `""` = all) / `noteIds` (caller order kept), `fields` (name filter, default all), `stripHtml` (default `true`; media filenames and `[sound:...]` kept; cloze markup like `{{c1::France}}` passes through **verbatim**, no bracketed-hint conversion), `maxFieldLength` (default `400`, `0` = off, cut with `…`), `offset`, `limit` (default `200`, clamped to `2000`). Returns `{total, notes: [{noteId, modelName, tags, fields}], nextOffset}` (`nextOffset: null` on the last page). Query path is ascending-noteId order; stale noteIds are silently omitted while `total` still counts them. Read-only. |
| `mediaThumbnails` | Base64 thumbnails of collection media images — aspect-preserved, **never upscaled** (small images return at native size). Params: `filenames` (bare media names), `maxDim` (default `320`, clamped to `1024`), `format` (`"jpeg"` default or `"png"`), `quality` (JPEG 0–100, default `70`). Returns `{thumbnails: [{filename, data, width, height}]}` with per-item `{filename, error}` entries; input order. JPEG flattens transparency — request `png` to keep alpha. Pure read. |
| `bulkSuspend` | Suspend or unsuspend many cards with one undo entry (`AnkiConnect Plus: Bulk Suspend`). Params: `cardIds` (deduplicated; unknown ids silently dropped), `suspend` (default `true`; `false` uses the backend restore op, which **also unburies** buried cards). Returns `{changed, undoEntry}`; `changed: 0` → `undoEntry: null` and the undo stack is untouched. |
| `bulkSetDueDate` | Set the due date on many cards with one undo entry (`AnkiConnect Plus: Bulk Due Date`). Params: `cardIds` (deduplicated; unknown ids dropped), `days` string — `"0"` due today, `"5"` in 5 days, `"1-7"` uniform-random per card in the range, `"3!"` also forces the interval to 3 days. The grammar (`[0-9]+(-[0-9]+)?!?`) is validated **before** the undo entry is created, so a bad string errors with the undo stack genuinely untouched. Applies to every existing card regardless of state (new cards become review cards). Returns `{changed, undoEntry}`. |
| `exportDeckApkg` | Export one deck **and its subdecks** to an `.apkg` file. Params: `deckName`, `outPath` (default `~/Downloads/<sanitized-deck>-<YYYY-MM-DD>.apkg`; `~` expanded; must be a *file* path — an existing directory or trailing slash is rejected; parent dir must exist), `includeScheduling` (default `true`), `includeMedia` (default `true`; `false` still writes an empty `media` zip member). **Never overwrites**: `-2`, `-3`, … appended before the extension (`report.apkg` → `report-2.apkg`). Deck presets are never exported (fixed `with_deck_configs=False`, matching Anki's own dialog default); modern (non-legacy) package format. Returns `{path, sizeBytes, notesExported}`. No undo entry; collection unchanged. |

### Notes on semantics

- **Atomic/undo contract (bulk actions):** each bulk action creates a single named undo entry (e.g. `AnkiConnect Plus: Bulk Add`) so one Undo in Anki reverts the whole batch. With `atomic: true` (default), any unexpected hard error reverts everything already written and raises an error whose message includes `failedIndex`, the underlying error, `addedBeforeRevert`, and `skipped` as JSON. With `atomic: false`, hard errors are recorded per-note in `skipped` and processing continues. Validation skips (duplicate, empty first field, missing model/deck/field/note) always go to `skipped` in either mode and never abort the batch.
- **Dry-run mode (`dryRun: true` on the three bulk note actions):** previews a batch with zero writes — no notes added or updated, no media stored, no undo entry (not even an empty one; `undo_status()` is bit-identical before/after). The dry path runs the exact same validation code as the real path and short-circuits at the zero-write boundary, so `skipped` entries and reasons match a real run. The success key is renamed because its semantics change: `bulkAddNotes` returns `wouldAdd` as a **count** (note ids do not exist until a real add), while `bulkUpdateNoteFields`/`bulkAddTags` return `wouldUpdate` as the **list of note ids** that would be written. `undoEntry` is always `null`. Limitation: dry runs skip upstream media embedding (embedding stores files), so notes carrying `audio`/`video`/`picture` keys are validated on their fields **as submitted**, without media-filename substitution — in principle the real run's substituted fields could differ for first-field-emptiness/duplicate checks. Hard parameter errors still raise; write-time hard errors (the `atomic: false` skipped entries) cannot be predicted by a dry run.
- **Duplicate detection (`bulkAddNotes`):** Anki-native semantics — same notetype + same stripped first field, collection-wide (checksum precheck confirmed against stripped text). Per-note `options.duplicateScope` / `options.duplicateScopeOptions` are accepted but ignored in v1; per-note `options.allowDuplicate` is honored.
- **`queryRevlog` field semantics:** `interval` / `lastInterval` positive = days, negative = seconds. `factor` = SM-2 ease permille (0 for learning/manual rows; not scheduling-relevant under FSRS). `type`: 0 learning, 1 review, 2 relearning, 3 filtered/cram, 4 manual/forget, 5 rescheduled — stats-worthy rows are `type NOT IN (4, 5)`. `noteId` is `null` for orphan rows whose card was deleted. Caveat: the deck filter reflects each card's *current* deck (home deck for cards in a filtered deck), not the deck at review time.
- **Image occlusion ordinals:** shapes sharing an ordinal mask together on one card; `ordinal: 0` is annotation-only (generates no card); omitted ordinals are assigned 1..N in array order. `getImageOcclusionNote` does not return image bytes — use upstream `retrieveMediaFile`.
- **Deck placement / IO deviations:** IO cards are moved to the requested `deckName` as part of the same undo step; `createBackup` may return `{created: false}` even with `force: true` when the collection is unchanged; `updateImageOcclusionNote` has no `image` parameter.
- **Crop semantics:** both crop actions write the result as a new media file and never delete or overwrite the original (use `deleteMediaFile` for cleanup). Do **not** point `cropImage`'s `noteIds` at an image-occlusion note's base image: the filename is rewritten but the occlusion rects are NOT remapped, so every mask misaligns — `cropImageOcclusionImage` is the IO-safe path. Empty-card gotcha: if `cropImageOcclusionImage` drops every shape of some ordinal, the backend does not delete that ordinal's now-empty card; its id still appears in `cardIds`, and Tools → Empty Cards is the cleanup path.

## UI freeze

The server runs single-threaded on the Qt main thread: `createBackup` (with completion-wait) and very large bulk batches freeze the Anki UI for their duration. Typical bulk batches (hundreds of notes) complete in tens of milliseconds.

## Safety

The add-on never issues raw SQL writes; revlog access is read-only `SELECT`.
