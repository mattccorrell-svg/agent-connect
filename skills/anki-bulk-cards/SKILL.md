---
name: anki-bulk-cards
description: Build, edit, audit, or repair Anki cards at scale through the AnkiConnect Plus add-on. Use when a task involves creating many notes, bulk-editing fields or tags, image occlusion, cropping or highlighting slide images, deck integrity checks, find/replace across notes, or verified AnkiWeb sync. Triggers on "make cards from", "bulk add/edit/retag", "fix these cards", "audit my deck", "occlude this figure", "sync and confirm".
---

# Bulk Anki work via AnkiConnect Plus

AnkiConnect Plus is a fork of AnkiConnect that makes large Anki jobs fast, atomic, and reviewable. It serves **everything on port 8766** — the 36 Plus actions *and* the full upstream AnkiConnect surface (decks, models, GUI, `findNotes`, `storeMediaFile`), since it is a fork of the whole codebase. (On Matt's machine stock AnkiConnect is disabled; if a stock install is active elsewhere it answers on 8765.) Anki must be open. Protocol:

```
POST http://localhost:8766   {"action": "...", "version": 6, "params": {...}}
```

**Call `plusInfo` first.** It returns `actionDocs` (every action's params **and** return shape), `errorCodes` (with a `retryable` flag per code), and `recipes`. It is the complete reference — do not guess shapes.

## The non-negotiable ritual for any write

1. **`syncNow`**, then poll **`syncStatus`** until `job.state == "done"`. AnkiWeb now holds a pre-job copy.
2. **`createBackup`** (`force: true`). Returns `{created: true}` only when a real file landed.
3. **`dryRun: true`** on the write. You get the full validation report — what would change, what would be skipped and why — with zero writes and no undo entry. For field writes add `diff: true` for before/after previews.
4. **Show the user the dry-run result** and get a go. Never skip this on a batch you did not personally verify.
5. Run it for real with an **`undoLabel`** describing the job ("lab 9-12 source slides"). One Ctrl+Z reverts the entire batch; without a label the undo menu is indistinguishable entries.
6. **`syncNow`** again and confirm.

Verified-synced means all three: `job.state == "done"` **and** `required == "no_changes"` **and** `mediaSyncing == false`.

## Token discipline — this is where budgets are won or lost

- **Reading fields:** `notesSlim` with `fields: ["Text"]`, `stripHtml: false`, `maxFieldLength: 0`, `omitEmptyFields: true`. Raw editable HTML, only the field you need, empty fields dropped. Do **not** use stock `notesInfo` for bulk reads — it has no projection and ships every empty field.
- **Reading rendered cards:** `renderCard` with `format: "text"`. On AnKing-style notetypes the default `"html"` is ~95% template JavaScript and CSS. Use `"body"` if you need markup without script/style.
- **Scanning images:** `mediaThumbnails` (one call, downscaled) — never fetch full-size media to look at a batch.
- **Checking media:** `mediaExists`, not `getMediaFilesNames` (which returns the entire media list).
- **Pagination:** `notesSlim` returns `total`, `nextOffset`, and `missing`. Walk `nextOffset` until null.

## Split mechanical from judgment — the biggest cost lever

Anything deterministic belongs in **code**, not in generated tokens. First-letter cloze hints, CSV-to-notes, template formatting, sequence numbering: write a short script, run it, spend nothing per card. Reserve model tokens for the judgment layer — what deserves a card, whether a fact is right, whether the wording is clear.

When drafting, emit **compact card content** (a small object per card) and let code expand it into formatted HTML. Generating full styled HTML per card costs several times more for identical output.

## Matt's card rules (BSOM decks)

Read `~/Documents/anki-backups/BSOM_card_build_spec.md` and `card_style_spec.md` before writing or rewriting cards. Load-bearing rules:

- **Cards land suspended.** New and adjusted cards stay suspended for review; he unsuspends. Suspension state must never change as a side effect — pass `preserveSuspended` on reschedules.
- **Never occlude text in a paragraph.** Text slides become cloze or basic cards; image occlusion is for real anatomical diagrams.
- **Short cards.** ≤3 cloze blanks; split rather than cram. One muscle per card; attachments separate from action+innervation.
- **Leading hints.** Reveal the scaffold, cloze the key term. Hints must be accurate, plain, specific (`motion`, `foramen`, `name`) — never vague (`structure 1`) or jargon.
- **No repeated ideas** across a deck. Fewer, higher-yield cards over exhaustive coverage.
- **Cards mirror their source slide** — lead with the slide's primary term, mirror its structure, move alt-names to Extra.

## Auditing and repair

- **`checkDeckIntegrity`** — one read-only call finds missing media, unbalanced cloze braces, cloze/card ordinal mismatches (the Empty Cards condition), and orphan media. Note `orphanMediaCollectionWide` is collection-wide, unlike the other deck-scoped lists.
- **`bulkReplaceInFields`** — literal or regex find/replace on one field. **Always dry-run first**; it operates on raw HTML, so a careless pattern can rewrite `<img src>` attributes. The preview shows the tag, so the danger is visible before committing.
- **`queryRevlog`** — review history; check `truncated` and walk `nextOffset` rather than trusting the first page.

## Images

- **`addImageOcclusionNote`** — image plus normalized 0–1 rects; no clicking through the editor.
- **`cropImage`** — non-destructive; writes a new file and optionally repoints notes. For an occlusion note use **`cropImageOcclusionImage`** instead, which remaps the masks into the new frame; plain `cropImage` would leave them misaligned.
- Coordinates everywhere are **normalized 0–1 floats**, consistent across occlusion, crop, and highlight actions.

## Hard rules

- **Decks must already exist.** A missing deck comes back as a skipped note, not an auto-created deck — call stock `createDeck` first.
- **Never call `ankihubSuggest*` without explicit per-suggestion approval.** Those submit to real human maintainers under the user's name. One at a time, always after showing the exact diff. For AnKing content changes a `source` is required and gets folded into the rationale in their format.
- **Errors carry codes.** Branch on `errorCode` and honor `retryable`; do not parse English. Per-item skip reasons inside a successful result are plain text by design and are not errors.
- **Report what happened, not what was requested.** Every action distinguishes `updated` from `unchanged`, `changed` from `unsuspended`, `total` from `missing`. Pass those distinctions through to the user verbatim — a batch that "succeeded" while skipping 40 notes is not a success.
