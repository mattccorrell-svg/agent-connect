# AnkiConnect Plus

A personal fork of AnkiConnect adding bulk, image-occlusion, image-crop, revlog, and backup actions, served on port **8766**.

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
| `bulkAddNotes` | Add many notes with one undo entry, fast duplicate pre-check, and per-note error reporting. Params: `notes` (upstream `addNotes` shape), `atomic` (default `true`), `allowDuplicates` (default `false`; per-note `options.allowDuplicate` overrides). Returns `{added, skipped: [{index, reason}], undoEntry}`. |
| `bulkUpdateNoteFields` | Update fields and/or tags on many notes (`notes: [{id, fields?, tags?}]`; `tags` replaces the whole tag list). One undo entry; same atomic contract. Returns `{updated, skipped, undoEntry}`. |
| `bulkAddTags` | Add tags (`str` split on whitespace, or list) to many notes by id. Only notes actually changed are written and reported in `updated`. Returns `{updated, skipped, undoEntry}`. |
| `addImageOcclusionNote` | Create a native (built-in) Image Occlusion note from an image `{path}` or `{data, filename}` plus `occlusions` (native string, or array of normalized 0–1 rects with optional `ordinal`), `header`, `backExtra`, `tags`, `deckName`, `hideAllGuessOne`. Returns `{noteId, cardIds}`. |
| `getImageOcclusionNote` | Read an IO note: `{imageFilename, occlusions[] (one entry per shape with ordinal; rects as floats, other shapes as raw properties), header, backExtra, tags, occludeInactive}`. |
| `updateImageOcclusionNote` | Update any subset of `occlusions` / `header` / `backExtra` / `tags` on an IO note (omitted params are kept exactly). Returns `null`. The image itself cannot be changed here — `cropImageOcclusionImage` is the supported way to change (crop) it. |
| `cropImage` | Crop a media image into a **new** media file (the original is kept). Params: `filename` (bare media filename), `rect` `{left, top, width, height}` as normalized 0–1 floats (clamped to the image, never padded), optional `noteIds` (every occurrence of the old filename in those notes' fields is rewritten to the new one, one undo entry). Returns `{newFilename, width, height, notesUpdated}`. Not for IO base images — see semantics below. |
| `cropImageOcclusionImage` | Crop a native IO note's base image and remap every occlusion rect into the cropped frame, atomically (one undo restores both the image and the rects). Params: `noteId`, `rect` (same normalized shape). Rects falling fully outside the crop are dropped; straddling rects are clipped to the crop edge; dropping all rects is refused. Returns `{newFilename, occlusionsKept, occlusionsClipped, occlusionsDropped, cardIds}`. |
| `queryRevlog` | Read-only review-history query filtered by `cardIds` / `noteIds` / `deckName` (incl. subdecks) / `sinceMs` (inclusive) / `untilMs` (exclusive), `limit` default 5000. Returns `{rows}`. |
| `createBackup` | Trigger a `.colpkg` backup into the profile's `backups/` folder. `{force}` default `true`. Returns `{created: bool}` — `false` means nothing changed since the last backup, not a failure. |
| `plusInfo` | Version/action/docs metadata for this add-on. Works with no profile open. |

### Notes on semantics

- **Atomic/undo contract (bulk actions):** each bulk action creates a single named undo entry (e.g. `AnkiConnect Plus: Bulk Add`) so one Undo in Anki reverts the whole batch. With `atomic: true` (default), any unexpected hard error reverts everything already written and raises an error whose message includes `failedIndex`, the underlying error, `addedBeforeRevert`, and `skipped` as JSON. With `atomic: false`, hard errors are recorded per-note in `skipped` and processing continues. Validation skips (duplicate, empty first field, missing model/deck/field/note) always go to `skipped` in either mode and never abort the batch.
- **Duplicate detection (`bulkAddNotes`):** Anki-native semantics — same notetype + same stripped first field, collection-wide (checksum precheck confirmed against stripped text). Per-note `options.duplicateScope` / `options.duplicateScopeOptions` are accepted but ignored in v1; per-note `options.allowDuplicate` is honored.
- **`queryRevlog` field semantics:** `interval` / `lastInterval` positive = days, negative = seconds. `factor` = SM-2 ease permille (0 for learning/manual rows; not scheduling-relevant under FSRS). `type`: 0 learning, 1 review, 2 relearning, 3 filtered/cram, 4 manual/forget, 5 rescheduled — stats-worthy rows are `type NOT IN (4, 5)`. `noteId` is `null` for orphan rows whose card was deleted. Caveat: the deck filter reflects each card's *current* deck (home deck for cards in a filtered deck), not the deck at review time.
- **Image occlusion ordinals:** shapes sharing an ordinal mask together on one card; `ordinal: 0` is annotation-only (generates no card); omitted ordinals are assigned 1..N in array order. `getImageOcclusionNote` does not return image bytes — use upstream `retrieveMediaFile`.
- **Deck placement / IO deviations:** IO cards are moved to the requested `deckName` as part of the same undo step; `createBackup` may return `{created: false}` even with `force: true` when the collection is unchanged; `updateImageOcclusionNote` has no `image` parameter.
- **Crop semantics:** both crop actions write the result as a new media file and never delete or overwrite the original (use `deleteMediaFile` for cleanup). Do **not** point `cropImage`'s `noteIds` at an image-occlusion note's base image: the filename is rewritten but the occlusion rects are NOT remapped, so every mask misaligns — `cropImageOcclusionImage` is the IO-safe path. Empty-card gotcha: if `cropImageOcclusionImage` drops every shape of some ordinal, the backend does not delete that ordinal's now-empty card; its id still appears in `cardIds`, and Tools → Empty Cards is the cleanup path.

## UI freeze

The server runs single-threaded on the Qt main thread: `createBackup` (with completion-wait) and very large bulk batches freeze the Anki UI for their duration. Typical bulk batches (hundreds of notes) complete in tens of milliseconds.

## Safety

The add-on never issues raw SQL writes; revlog access is read-only `SELECT`.
