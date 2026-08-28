# AnkiConnect Plus — Implementation Specification

Version: 1.5.0 (spec revision 20, 2026-08-19 — revision 7 field-feedback amendments to §§4.2, 4.3, 4.7, 4.9, 12, 13, 15; revision 8 adds the two field-feedback actions §§20–21, `checkDeckIntegrity` and `bulkReplaceInFields`; revision 9 (round-2 field feedback, 2026-08-12) adds `mediaExists` and `storeMediaFilesBulk` (§§22–23) and the cross-cutting `undoLabel` param (§24, amending §§3.3, 4.4, 4.6 — §4.6's return changing from `null` to `{undoEntry}` is one of the round's TWO deliberate breaking contract changes, beside §25's error prefix); revision 10 (round-2 field feedback, 2026-08-12) adds the `diff`/`maxPreview` dry-run preview on `bulkUpdateNoteFields` (§§4.2, 15), stable machine-parseable error codes on every raised Plus error (§25, amending §3.2 and every action's error list — the round's second deliberate breaking change), and the discoverability lock (§4.9 `recipes`, §13 raw-fidelity-field-projection naming); revision 11 (round-2 fix pass, 2026-08-12) amends §§4.6/24 (no-op `updateImageOcclusionNote` returns `undoEntry: null` instead of echoing an unrelated stale entry) and §15/§4.9 (duplicate-note-id dry-run parity caveat on `bulkUpdateNoteFields`); **revision 12 (round-3 field feedback, 2026-08-12)** is the data-shape round: `undoStatus` (§26 — action count 26 → **27**), `renderCard`'s `cssMode` + per-card `notetype` (§12), `notesSlim`'s honest `total` + `missing` + `omitEmptyFields` (§13), `bulkSetDueDate`'s resurrection disclosure `unsuspended`/`unburied` plus `changedIds` on both scheduler actions (§16), `checkDeckIntegrity`'s `orphanMediaCollectionWide`/`orphanMediaCount`/`orphanMediaTruncated`/`orphanMediaLimit` (§20), `mediaExists`' `actualName` (§22), `syncStatus`' `serverChecked` (§18.2), `bulkUpdateNoteFields`' `__tags__` diff rows (§§4.2, 15), and the `lean deck sweep` recipe (§4.9). **Revision 12 carries exactly TWO deliberate breaking contract changes, both flagged in place: (i) §13 `notesSlim.total` under `noteIds` now counts the ids FOUND, not the ids REQUESTED — the old value was a lie and fixing it is the point; (ii) §20's `orphanMedia` is renamed `orphanMediaCollectionWide` — the key was one day old.** Everything else in revision 12 is additive; sections carry their own revision markers; **revision 13 (round-3 field feedback, 2026-08-12)** is the error-surface + discoverability round, and is **additive in KEYS and DEFAULTS, but it does change two pre-existing error STRINGS** (corrected after the round-3 review, which caught this paragraph claiming otherwise): (a) the dispatcher's unknown-action reply `"unsupported action"` becomes `"[unknown_action] unsupported action"` (§25.2a), and (b) the whole argument-binding family is rewritten to strip the internal class name — `"PlusMixin.renderCard() missing 1 required positional argument: 'cardIds'"` becomes `"[invalid_param] renderCard() missing required argument: cardIds"` (§25.3). A client string-matching either one breaks; both are deliberate, and neither has a compatibility alias. Everything else in the round is additive: the structured error envelope `errorCode`/`retryable` on every error reply incl. `multi` sub-responses (§25.1), the new `unknown_action` code and the newly REACHABLE `sync_in_progress` guard (§25.2), class-name-free argument-binding messages (§25.3), a `reachable` column on §25's code table, and `plusInfo`'s `returns` for all 27 actions + `errorCodes` + `errorPrefixNote` + the `reading errors` recipe (§4.9). Every pre-existing key and default is byte-unchanged, and every error string EXCEPT the two named above is byte-unchanged; **revision 14 (2026-08-18) — the fix pass for the round-3 REVIEW** (the independent code review OF revisions 12–13, not another field report; "round-3 review" below always means that review, never the round-3 field feedback that produced revisions 12–13) is a correctness-and-honesty pass with no new actions and no new params: `undoStatus` reads the backend counter directly so `lastStep` is monotonic again (§26), `bulkUpdateNoteFields` compares and previews tags CANONIFIED so the `__tags__` preview matches what is stored and a byte-identical repeat stops re-writing (§§4.2, 15), the `syncing` state is now guaranteed to end so the retryable `[sync_in_progress]` is honest (§§18, 25.2), and several `plusInfo`/SPEC/README statements that contradicted the code were corrected — `bulkReplaceInFields.skipped` is keyed `noteId` not `index` (§21), rect occlusions carry `properties` (§4.5), `multi` success sub-responses are NOT four-key envelopes (§25.1), the uncoded-error enumeration now names the api-key refusal and schema failures (§25), `rationale_invalid` needs no AnkiHub add-on (§25 table), and `notesSlim`'s O(N²/L) paging cost is disclosed (§13). The two error strings named above are the only ones that ever changed); **revision 15 (2026-08-18) — suspension control (§27)**, the round's ONE deliberate BEHAVIOR change and the first place this fork knowingly diverges from Anki's own semantics BY DEFAULT: `bulkAddNotes` gains `suspend` (config `suspendNewCards`, shipped `true` in revision 15, **`false` since revision 16**) so a generated batch can land SUSPENDED, and `bulkSetDueDate` gains `preserveSuspended` (config `preserveSuspendedOnReschedule`, ships `true`) so the suspensions anki's `set_due_date` silently clears are PUT BACK inside the same undo entry, plus `dryRun` to predict all of it. Every KEY added is additive (`bulkAddNotes` → `suspended` / dry `wouldSuspend`; `bulkSetDueDate` → `resuspended` and a full `would*` dry shape), but the DEFAULT BEHAVIOR of both actions changes for a caller who passes neither parameter — that is the point, it is switchable per call and per config, and it is flagged in §0 Deviation #13, §4.1, §15, §16.2, §27, the two `plusInfo` summaries and the README. Amends §§4.1, 6.1, 6.3, 15, 16.2. **Because revision 15 is the first revision to change what an action DOES rather than only what it returns, the version moves too: `core.PLUS_VERSION` 1.0.0 → `1.1.0`, and `plusInfo` gains `specRevision` (this header's revision number, locked to it by test) — a client that caches `plusInfo` must be able to see a default-behavior change in a machine-readable field, not only in prose.** Revision-15 fix pass (2026-08-18, from the independent review of revision 15, no new params): `bulkSetDueDate`'s `dryRun` is type-checked like every other flag (§15), the two new re-suspension failure handlers report whether the revert ACTUALLY happened instead of asserting it (§§4.1, 27.4), and `bulkAddNotes` cross-checks the backend's suspend count before reporting `suspended` (§27.4); **revision 16 (2026-08-18, pre-publication defaults split)**: `suspendNewCards` now ships **`false`** (stock-compatible; the suspended-draft workflow becomes opt-in per call or per config) while `preserveSuspendedOnReschedule` still ships **`true`** (the anti-resurrection protection remains the shipped deviation). Rationale: for a public release, a default that changes what integrations *expect* (live new cards) should be opt-in, while a default that only *prevents silent damage* and self-discloses in the response stays on. Code, config.json, util.DEFAULT_CONFIG, docs, and the lockstep tests all updated; `PLUS_VERSION` 1.1.0 → 1.2.0; **revision 17 (2026-08-18, round-4 field feedback — COMPLETE, landed in two slices under this one revision number)**. The round's design principle, adopted: *where the GUI can do something the API can't, the agent hands the job back to the human — and the human is the least reliable part of the loop.* **Slice 1 — deck/flag/tag maintenance (§28)**: `renameDeck` (§28.1: whole-subtree in-place rename; options presets, per-deck descriptions and collapse state survive, `configPreserved` is an actual post-check; an occupied `newName` is refused with `[duplicate]` instead of inheriting the backend's silent auto-rename, which makes the previously RESERVED `duplicate` code REACHABLE — §25 table updated), `bulkSetFlag` (§28.2: set/clear card flags as one undoable batch, `updated`/`unchanged` split from the cards' real pre-op flags — closes the flag-inbox loop stock leaves open), and `renameTag` (§28.3: segment-aware subtree rename on `col.tags.rename` — `lab1` → `lab01` never touches `lab10`; `dryRun` previews the exact pairs). **Slice 2 — filtered-deck safety + empty cards (§§29–30)**: `filteredDeckReport` (§29.1, read-only: per filtered deck, `cardCount` + `homeDecks` breakdown, scopable to one home subtree — the pre-export probe), `emptyFilteredDeck` (§29.2: `col.sched.empty_filtered_deck` as one undoable op, the remediation step no stock action offers), `getEmptyCards` (§30.1, read-only: anki's Tools > Empty Cards report as data with the deletion/protection split precomputed), `deleteEmptyCards` (§30.2: the dialog's own deletion incl. its keep-notes last-card protection, one undoable batch), **and the round's ONE deliberate BEHAVIOR change: `exportDeckApkg` now FAILS CLOSED (§§17, 29.3, §0 Deviation #14) when any card whose HOME deck is inside the export scope sits in a filtered deck** — the backend's deck-scoped gather follows cards' CURRENT `did`, so notes whose every card is filtered VANISH from the package and partially-filtered notes ship scheduling-reset (both probe-verified; the field report nearly shipped a class deck missing 141 cards / 96 notes). The refusal is `[cards_in_filtered_decks]` (new §25 code, born reachable) naming counts and filtered-deck names; `allowFilteredOmission: true` is the per-call escape hatch (deliberately NOT config-backed — a config default that silently re-enables data loss would recreate the failure the guard closes), and the response's new ALWAYS-present `warnings` array itemizes whatever an allowed export omitted (`[]` on a clean export — additive key). Action count 27 → **30** (slice 1) → **34** (slice 2); every write action ships `dryRun` + `undoLabel` and lands as ONE merged undo entry (§§15, 24 amended); `plusInfo` gains the `safe deck export` and `empty-cards cleanup` recipes (§4.9). Slice 1 and the four slice-2 actions are purely additive; the export fail-closed default is a behavior change, so **`PLUS_VERSION` 1.2.0 → 1.3.0** (the revision-15 rule: the version's minor moves whenever default behavior does). **Revision-17 fix pass (2026-08-18, from the independent review of revision 17; no new actions, no new params, no version/revision move — the revision-15-fix-pass precedent)**: (i) `exportDeckApkg`'s fail-closed guard gains its SECOND flagged set — filtered decks nested INSIDE the export subtree holding cards homed OUTSIDE it, whose foreign notes previously shipped silently (scheduling-reset, filter recreated as a regular deck; behaviorally proven on 25.09.4) — refused under the same `[cards_in_filtered_decks]` code and itemized as a sibling `warnings` entry `{code: "foreign_cards_in_scope_filters", count, decks}` when `allowFilteredOmission: true` lets it through (§§17, 29.3; the export ROOT is excluded from the new set, so exporting a filtered deck by name stays legal); (ii) `renameDeck`'s `[duplicate]` exemption is tightened from subtree membership to **pairwise self-identity** — a predicted target may resolve only to that pair's own deck, so renaming a deck onto its own descendant is now refused instead of riding the backend's silent auto-`+` with a diverging dry-run (§§15, 28.1); (iii) `renameDeck` refuses an un-normalized `newName` (empty or whitespace-padded `::` component) with `[invalid_param]` up front on both paths, instead of dry-predicting a name the backend would rewrite (`'P3A2 '` → `'P3A2'`, `'P3B2::'` → `'P3B2::blank'`) (§§15, 28.1); **revision 18 (2026-08-18, round-5 field feedback — §31)**: docs, additive keys and dry-run fields only, NO behavior change, so `PLUS_VERSION` moves a **PATCH**, 1.3.0 → **1.3.1** (the minor still moves only with default behavior). The round's through-line: *a default that changes state is a decision the API made on the caller's behalf — it must be visible in the dry run and correct in the docs.* (i) **stale-default sweep**: `bulkAddNotes`' `returns` doc still claimed the revision-15 `suspend` default ("defaults to true … normally returns a non-empty list") — corrected to config-language; the §15 `wouldSuspend` bullet's resolution ladder ended `→ true` and §27.2's table shipped `true` for `suspendNewCards` — both corrected to `false` (revision-16 leftovers). (ii) **`plusInfo.effectiveConfig`** (§31.3): the two §27 knobs RESOLVED at call time through the same `util.setting` ladder the writes use — `{value, source: 'user_config'|'shipped_default'}` each; headless/no-`mw` reports the shipped default. (iii) **`preserves`** (§31.1): every side-effectful action's `actionDocs` entry states what it does NOT touch (scheduling, suspension, flags, tags, note ids, GUIDs, deck assignment), every claim code- or probe-verified. (iv) **preservation post-checks** (§31.2): `bulkUpdateNoteFields` / `bulkReplaceInFields` real responses gain always-present `suspensionPreserved` / `schedulingPreserved` — before/after snapshots of the written notes' cards `(queue, due, ivl)`, the `configPreserved` pattern: verified facts, never promises. (v) **dry-run gaps** (§31.4): `renameTag` `dryRun` gains `notesUpdated` (a zero-write prediction from anki's own tag search), `renameDeck` `dryRun` gains `configWillBePreserved: true` (a static contract statement — a property of the in-place rename path, NOT a post-check); both actions' real and dry key sets are documented side by side. All new keys additive; no pre-existing key, default, or error string changes. **Revision-18 fix pass (2026-08-19, from the independent review of revision 18; no new keys, no version/revision move — the revision-15/17 fix-pass precedent)**: `effectiveConfig.source` is now probed from the user's SAVED `meta.json` config via `addonManager.addonMeta`, not `getConfig`'s merged view — the shipped `config.json` carries both §27 keys, so the merged-view probe answered `user_config` on every intact install (values were always correct; only the attribution was wrong). §§4.9/31.3 state the corrected rule and its one honest caveat: saving Anki's config dialog writes the whole merged dict into `meta.json`, after which both keys genuinely report `user_config`; **revision 19 (2026-08-19, filtered-deck build — §32)**: two new actions close the write half of the §29 story — the API could report and empty filtered decks but never make one. **`createFilteredDeck`** (§32.1: create AND build a cram deck from a search as ONE undoable op — `col.sched.add_or_update_filtered_deck` with GUI-template defaults 100/`random` (second filter 20/`due`), reschedule on; suspended/buried/other-filter cards are never gathered, per anki's own probe-pinned gather rule; STRICTER than the backend exactly where the backend is silently surprising: taken name → `[duplicate]` instead of anki's silent `name+`, zero gatherable cards → `[validation_error]` with nothing created (mirroring the GUI's own refusal; `allow_empty` stays `False`), filtered parent → `[validation_error]`, un-normalized name → `[invalid_param]` — every refusal fired BEFORE any undo entry exists; `dryRun` sizes the deck without creating it: `wouldGather` + `exact` + `wouldGatherMin`/`Max` bounds, the two-term overlap-under-binding-limit case being genuinely order-dependent so a point count would be a lie) and **`rebuildFilteredDeck`** (§32.2: `col.sched.rebuild_filtered_deck` — empty-then-regather by the deck's SAVED terms, reporting BOTH halves: `returnedFirst` observed pre-op, `cardsGathered` observed post-op; rebuild-to-zero is anki's own legal outcome; the full data no-op — empty deck, terms would gather 0 — is gated before any undo entry exists, the §16.2 answer again; `dryRun` from birth per the §15 rule). Action count 34 → **36**; both take §24 `undoLabel` (entries `"AnkiConnect Plus: Create Filtered Deck"` / `"AnkiConnect Plus: Rebuild Filtered Deck"`), both land as ONE merged undo entry (a single undo deletes the created deck AND returns its cards, probe-verified); `plusInfo`'s `safe deck export` recipe grows into the full filtered-deck lifecycle (create → rebuild → report → empty → export). Purely ADDITIVE: no existing action's params, defaults, keys or error strings change. NEW CAPABILITY moves the MINOR: `PLUS_VERSION` 1.3.1 → **1.4.0** (plain semver; the revision-15 guarantee still holds in the direction a caching client relies on — a default-behavior change always moves the minor, so an unmoved minor still proves no default changed). Adaptations from the locked §32 design, each forced by probe evidence or a standing house rule, are flagged in §0 Deviation #15; **revision-19 fix pass (2026-08-19, from the independent review of revision 19; no new actions, params or keys, no version/revision move — the revision-15/17/18 fix-pass precedent)**: `rebuildFilteredDeck`'s gather-pool residency now composes the own-deck disjunct from the deck ID (`did:<id>`) instead of the deck NAME — a filtered deck literally named lowercase `filtered` made the writer's unquoted `deck:filtered` parse as anki's in-any-filtered-deck keyword (case-sensitive, probe-verified), turning the residency disjunction into a tautology that counted OTHER filters' cards as re-gatherable, broke the dry-run bounds promise and bypassed the full-no-op gate into a phantom do-nothing undo entry (§32.2; regression-locked in §32.3); and the doc surfaces the review caught trailing the served code were brought in line: the §25 `duplicate`/`validation_error` rows, the §4.9 example version and `safe deck export` recipe registry, the §§29↔32 lifecycle cross-references (SPEC, `plusInfo` summaries, README), the §30.3/§31.5 lock forward-notes, and the SKILL/test count itemizations (34 → 36); **revision 20 (2026-08-19, staged optional-tag suggestion — §33)**: ONE new action, `ankihubStageOptionalTagSuggestion` — publishing an AnkiHub Optional Tag group as a STAGED, HUMAN-SUBMITTED flow: all-or-nothing local validation first (canonical `AnkiHub_Optional::<TagGroup>::<Tag>` tag shape with ≥3 non-empty `::` segments — the add-on's dialog silently ignores anything else; every note must exist — one miss refuses the whole call; all notes on exactly ONE AnkiHub deck via the add-on's own `ankihub_dids_for_anki_nids`, a LOCAL read of the add-on's database file; ≤500 unique notes/call), then the tag applied locally through the `bulkAddTags` core path as ONE undoable entry (`"AnkiConnect Plus: Stage Optional Tag"`, §24 `undoLabel` honored), then the Browser opened on exactly those notes (`aqt.dialogs.open("Browser", mw, search=("nid:...",))` — the search is a 1-TUPLE; both `Browser.__init__` and `reopen` splat it into `search_for_terms(*search)`, so a bare string would shred into per-character terms) — **and then the action STOPS**. The human right-clicks the selection → AnkiHub → "Suggest Optional Tags", reviews, and presses Submit in AnkiHub's own dialog. **The action never submits AND never touches AnkiHub's code or servers: AnkiHub's ToS (effective 2025-01-14) prohibits scripted content posting, and this project's constraints additionally require written permission for ANY programmatic AnkiHub access — even constructing the add-on's own suggestion dialog from code fires AnkiHub network calls (deck-extension fetch, tag-group prevalidation) with no human action taken, so the boundary sits one step earlier: everything local plus the Browser selection, with both AnkiHub-touching clicks (the menu item, then Submit) performed by the human** (the ToS rationale and the written-permission path that would unlock a future auto-submit variant are served in the §4.9 `staged optional-tag publication` recipe; `OPTIONAL_TAGS_FEEDBACK.md` drafts the exact question to ask AnkiHub). The action imports NO module from the add-on's `gui/` package and makes ZERO calls that can reach the network — regression-locked by a repo grep for the add-on client's posting functions and the dialog class name, plus a socket deny-guard in the verifier suite. **GUI-COUPLED CAVEAT — the first Plus action that opens a window**: the real run needs the Anki GUI (it opens/refocuses the Browser, replacing its current search); headless callers get the full §33 validation chain and the tag-write prediction through `dryRun: true`, which writes NOTHING and opens NOTHING. Real return `{tagged, alreadyTagged, ankihubDeckId, browserOpened, nextStep, undoEntry}`; dry return `{wouldTag, alreadyTagged, ankihubDeckId, wouldOpenBrowser, undoEntry: null}`. §19 feature detection grows (drift → `[incompatible_ankihub_addon]`): `db.ankihub_dids_for_anki_nids`. Action count 36 → **37**; purely ADDITIVE — no existing action's params, defaults, keys or error strings change; NEW CAPABILITY moves the MINOR: `PLUS_VERSION` 1.4.0 → **1.5.0** (plain semver; the revision-15 guarantee still holds — no default behavior changed)
Target Anki: 25.09.4 (Qt6, python 3.13). Fork of AnkiConnect (GPLv3) by Alex Yatskov / FooSoft.
Working copy: `<repo>/connect_plus/`
Venv python for all headless execution/tests: `<anki-venv>/bin/python`
Anki packages: `/Users/mattyc/Library/Application Support/AnkiProgramFiles/.venv/lib/python3.13/site-packages` (referred to below as `SP`).

HARD RULES (repeated from project charter, enforced by this spec):
- Never modify anything under `~/Library/Application Support/Anki2/` and never write to the user's real collection during development/testing. All tests run against scratch `.anki2` collections.
- Raw `col.db` **writes are forbidden everywhere** in this codebase. Read-only `SELECT` statements are allowed only where this spec explicitly says so (`queryRevlog`, the bulkAddNotes csum precheck, note-id/card-id location selects, the §18 sync dirtiness select `select ls, mod from col`, the §20 integrity-audit scope/note/ord selects, the §29 filtered-deck residency selects — `did`/`odid` card-location reads behind `filteredDeckReport`, `emptyFilteredDeck`'s breakdown/post-check and `exportDeckApkg`'s fail-closed check — and the §30 empty-cards ord/home/existence selects, and the §32 filtered-deck build residency counts — `select count() from cards where did = ?` before/after build/rebuild). Rationale: raw non-select SQL through `DBProxy` wipes the entire undo queue, and raw note updates bypass `mod`/`usn` bookkeeping, silently breaking sync (verified in research).
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
11. **Revision-12 adaptations (round-3 field feedback), each forced by measured behavior.** (a) **`bulkSetDueDate` also reports `unburied`, not just the asked-for `unsuspended`** — probing found `set_due_date` restores manually buried cards (queue `-3`) exactly as it does suspended ones, so a disclosure that named only suspension would have been a half-truth. (b) **`undoStatus` returns `lastStep` alongside `{undo, redo}`** — the proto carries anki's monotonic step counter for free, and it is the only way a caller can prove that a call which reports no visible change (e.g. §16.2's always-writes repeat) really did create an undo entry. (c) **`notesSlim`'s noteIds path now issues ONE chunked read-only id-existence select** (`select id from notes where id in (...)`) — §13 previously issued no SQL, but an honest `total`/`missing` must know about ids OUTSIDE the current page, which a per-page `col.get_note` loop cannot see. Read-only select of note ids: the same family the HARD RULES already allow. (d) **`syncStatus(localOnly: true)` reports `full_sync_required` for a schema-changed collection** instead of flattening every dirty state to `normal_sync` — the backend's own local verdict for `scm > ls` is `full_sync_required` (measured against an unreachable endpoint: verdict returned in 0.008 ms with no socket opened), so the old answer under-reported a collection that cannot converge. (e) **`renderCard` keeps `modelName` and adds `notetype` with the same value** — `cssByNotetype` is keyed by the notetype name and the locked design asks for a `notetype` key on every card; `modelName` stays for compat with upstream AnkiConnect's naming.
12. **Revision-13 adaptations (round-3 error surface).** (a) **The `sync_in_progress` guard exempts four actions, two of which do touch the collection.** The locked design says "collection-touching Plus actions raise `[sync_in_progress]` while a `syncNow` job is in flight"; taken literally that includes `syncStatus` and `syncNow`, and applying it there would have been self-defeating — `syncStatus` is the only way to *observe* the sync a caller is being told to wait for (and it already skips all collection access while `syncing`, Deviation #9b), and `syncNow` reports busy states as **data** (`{started: false, reason: 'already_syncing'}`, §18.1), so guarding it would break a documented contract to signal the very condition it already reports. `plusInfo`/`ankihubStatus` are exempt for the plain reason that they touch no collection. (b) **Only job state `syncing` is guarded, never `media_syncing`** — by then `sync_collection` has returned and the collection mutex is free; stock Anki lets you review during a media sync, and refusing there would invent a restriction Anki does not have. (c) **`errorCode`/`retryable` are emitted on EVERY error reply, not only on coded ones** — the round-3 triage suggested guarding the keys behind `isinstance(PlusError)` so upstream replies kept exactly two keys, but the locked design types them `string|null` / `bool|null`, and a client benefits far more from one stable envelope shape than from key-presence sniffing. `null` is given an explicit meaning ("this server has no opinion", §25.1) distinct from `false`. The `error` string itself is byte-unchanged either way, so this is additive. (d) **The `reading errors` recipe's `example` is `plusInfo`, not a `multi` call** — the §4.9 recipe lock requires `example.action` to be a member of `PLUS_ACTIONS`, and `multi` is an upstream action; rather than weaken the lock, the multi trap is described in the recipe's prose and the example became the recipe's actionable step (fetch `errorCodes` at startup).

13. **Revision-15 suspension control (§27) is a DELIBERATE deviation from Anki's own behavior, on by default.** Every other deviation in this list is an adaptation forced by the API; this one is a choice. (a) **`bulkSetDueDate` re-suspends.** Anki's `set_due_date` turns every targeted card into a review card, which silently resurrects suspended ones (measured, §16.2) — one deck-wide reschedule can revive every leech a user ever suspended, and revision 12 could only *report* the damage. With `preserveSuspended` (default `true`) the cards the call revived are re-suspended, merged into the SAME undo entry so one Ctrl+Z cannot leave a half-reverted state. (b) **Buried cards are deliberately NOT re-buried.** Anki's unbury-on-reschedule is desirable (a buried card is hidden *for today*, and you just moved its due date), and only suspension was in scope; the response still discloses `unburied`. This asymmetry is intentional, not an oversight. (c) **`bulkAddNotes` leaves its new cards suspended** (`suspend`, default `true`) so a generated draft batch cannot enter review before a human has read it — the write-suspended → review → unsuspend workflow. (d) **Both defaults are config-backed and per-call overridable**, and both responses report what actually happened (`resuspended`, `suspended`) rather than what was asked, so a caller on an unknown config can always tell which policy ran. (e) A non-boolean value in either config key is ignored in favor of the documented default: a config typo must not fail a write action. §27 has the full contract.

14. **Revision-17 `exportDeckApkg` fail-closed (§§17, 29.3) is that round's ONE deliberate behavior change, and its escape hatch is deliberately NOT config-backed.** The backend's deck-scoped gather ships a note iff at least one of its cards has `did` inside the export subtree, so a card visiting a filtered deck (did = filter, odid = home) does not count as present: a note whose EVERY card is in filtered decks silently VANISHES from the .apkg (measured: 5/12 notes, 41.7%, zero warnings), and a partially-filtered note's filtered card ships with `did` = filter — the importer recreates the filter as a REGULAR deck and the card arrives scheduling-reset (measured: review card → new card). The fix pass added the mirror hazard: a filtered deck nested INSIDE the export subtree holds cards homed OUTSIDE it — the filter's `did` IS in scope, so those FOREIGN notes ship, scheduling-reset, into the recreated deck (behaviorally proven); the guard flags both sets. The action whose whole purpose is handing a deck to OTHER PEOPLE must not be silently wrong, so the default refuses with `[cards_in_filtered_decks]` naming counts + filtered-deck names. `allowFilteredOmission: true` is per-call only: a config key that silently re-enabled the loss for every later call would recreate the exact failure the guard exists to close — deliberately unlike §27's config-backed suspension defaults, which change scheduling visibility, never content. The response's `warnings` array is ALWAYS present (`[]` when clean) so callers branch on content, not key presence.

15. **Revision-19 §32 adaptations from the locked filtered-deck-build design, each forced by probe evidence or a standing house rule.** (a) **The filtered-parent and zero-gather refusals are PRECHECKED, with the backend's `FilteredDeckError` kept as a drift backstop mapped to the same `[validation_error]`** — the locked design said "catch the backend error"; firing after `add_custom_undo_entry` would pop an empty custom entry and push a phantom Redo item (the §16.2 hazard `emptyFilteredDeck` already answers by gating first), so every refusal fires before any undo entry exists. The backstop maps `FilteredDeckError` (probe-verified atomic: nothing created) to `[validation_error]`, not `[batch_reverted]` — nothing was written, and "reverted" would overstate. (b) **`rebuildFilteredDeck` ships `dryRun`** though the locked design omitted it: §15's from-birth rule for write actions stands, and the rebuild prediction formula was probe-verified (own cards re-gatherable: `(-deck:filtered OR deck:<self>)`). (c) **`secondFilter` defaults are the GUI template's** (limit 20, order `due`; the locked design left them unstated) — the same probe-pinned template that supplies the first filter's 100/`random`. (d) **The two-term dry count is a BOUNDS PAIR + `exact` flag, not a single number** — probe evidence: when the terms overlap and the first limit binds, anki's own outcome depends on term-1's gather order (RANDOM is nondeterministic), so no exact count EXISTS; `wouldGather` reports the upper bound and `wouldGatherMin`/`wouldGatherMax` bracket every possible outcome (single-term counts stay exact, probe-verified formula). (e) **An empty `searchQuery` is refused** (`[invalid_param]`) though anki would accept it: `build_search_string('')` is `deck:*` (probe-verified) — a write that can move up to `limit` cards from the ENTIRE collection should not happen by accident; callers who mean it say `deck:*`. (f) **The saved-normalized echo**: terms are saved and echoed through `col.build_search_string`'s canonical spelling, so the response, the deck's stored config and the dry prediction can never disagree about what the search IS. (g) **`terms`/`eligible` echo keys and the rebuild no-op gate** are additive extensions of the locked return shapes (`{deckId, name, cardsGathered, undoEntry}` / `{cardsGathered, returnedFirst}` all present as locked).

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
  PLUS_VERSION = "1.1.0"       # minor moves whenever DEFAULT BEHAVIOR changes
  PLUS_SPEC_REVISION = 15      # == this document's header revision (test-locked)
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
4. **(revision 13)** `__init__.py`: add `core` to the existing `from . import web, util` line, and change the dispatcher's `raise Exception('unsupported action')` to `raise core.PlusError('unknown_action', 'unsupported action')` (§25.2a). Two lines; the message body after the prefix is unchanged, and no other upstream raise site is touched.
5. **(revision 13)** `web.py`: add `core` to the existing `from . import util` line, and extend `format_exception_reply` with the `errorCode`/`retryable` keys (§25.1). `format_success_reply`, the request schema, and the whole socket/CORS layer are untouched. The new import adds no dependency `web.py` did not already have: its existing `from . import util` pulls in `aqt` (`util.py:22`), and `core` is aqt-free (test-asserted) and needs only `anki`. `core` has no import-time dependency on `web`, so there is no cycle.

Nothing else in `__init__.py` / `web.py` / `edit.py` / `util.py` changes.

## 3. Global conventions

### 3.1 Threading & reentrancy (from source map — governs every handler)

- There are **no threads**. `web.WebServer` is pumped by a `QTimer` (default 25 ms) on the Qt **main thread**; each HTTP request is parsed and its handler executed **synchronously inside a timer tick**, one request per connection, no keep-alive. Consequences:
  - Handlers may touch the collection directly with no locking; two requests can never interleave.
  - A slow handler freezes the Anki UI for its duration. Bulk actions at the scale Matt uses (hundreds to low thousands of notes) run in tens of ms (probe: 300 `add_note` calls = 34 ms) — acceptable. `createBackup` with `wait_for_completion=True` blocks the UI for the backup duration (seconds); documented, accepted for a personal tool.
  - The "snapshot max(id) → act → select new id" pattern used by `addImageOcclusionNote` is race-free because nothing else can run between the two selects.
- New actions inherit upstream's envelope, apiKey check, CORS gate, and `multi` behavior unchanged (`web.py:164-212`, `__init__.py:106-147`). With `version >= 5` responses are `{"result": ..., "error": null}`; errors are `{"result": null, "error": str(exception)}`, HTTP always 200 (403 only for CORS-denied).

### 3.2 Error style (amended 2026-08-12, spec revision 10: stable error codes — see §25; revision 13: the structured envelope — see §25.1)

- **The response carries the code as data, not only as text (revision 13):** every error reply is `{result: null, error: "[<code>] <message>", errorCode: <code>|null, retryable: <bool>|null}`. Read `errorCode`; parse the string only as a last resort. `null` on both means the error came from an upstream AnkiConnect action, which is also the only case where the `"[<code>] "` prefix is absent (§25.1).
- All action errors are raised exceptions whose message is `"[<code>] <message>"`: a **stable machine-parseable code prefix** (§25 vocabulary) followed by the pre-revision-10 message body **unchanged**. Raised as `core.PlusError(code, message)`; anything unexpected escaping an action is re-raised by the `plus_api` wrapper as `[internal]` (§25). Message templates are specified per action. Where a JSON report is embedded, it is `json.dumps(report, separators=(",", ":"))` appended after a fixed prefix so callers can `split(": ", 1)[1]` and parse (the bracketed code contains no `": "`, so this parse rule survives revision 10 unchanged).
- Type/param validation errors: `"[invalid_param] invalid parameter: <name>: <why>"`.
- **Per-item error strings embedded in results** (`skipped[].reason`, `thumbnails[].error`, `stored[].error`, `cards[].error`, …) are NOT raises and carry **no** code prefix — unchanged from earlier revisions.

### 3.3 Undo conventions (amended 2026-08-12, spec revision 9: `undoLabel`)

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
- **`undoLabel` (spec revision 9, see §24):** every Plus action that creates an undo entry accepts an optional `undoLabel` (default `null`). When given, `core.sanitize_undo_label` turns it into `"AnkiConnect Plus: " + <label>` (whitespace runs — newlines included — collapsed to single spaces, ends stripped, label capped at 80 chars), and that name replaces the action's default entry name everywhere the name is used: entry creation, merge target, atomic revert, and the response's `undoEntry` field. When `null`, the default names above are byte-for-byte unchanged. The `undoEntry` response field always reports the **actual** final entry name.

---

## 4. Actions

### 4.1 `bulkAddNotes`

Add many notes with one undo entry, fast duplicate pre-check, and per-note error reporting.

**Preserves (§31.1)** — every PRE-EXISTING note and card entirely (scheduling, suspension, flags, tags, ids, GUIDs, deck assignment); this call only creates. Decks/notetypes are never auto-created; suspension applies only to the cards the call itself created.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `notes` | array of note objects | required | Same shape as upstream `addNotes`: `{deckName, modelName, fields: {FieldName: html}, tags: [str], options?: {allowDuplicate?: bool, ...}, audio?/video?/picture?: [...]}` |
| `atomic` | bool | `true` | `true`: any hard error reverts the whole batch and raises. `false`: continue past per-note hard errors, reporting them in `skipped`. |
| `allowDuplicates` | bool | `false` | Batch default; per-note `options.allowDuplicate`, when present, overrides it for that note. |
| `dryRun` | bool | `false` | `true`: run the identical resolution pass + duplicate precheck, write nothing, return `{wouldAdd, wouldSuspend, skipped, undoEntry: null}` — see §15. |
| `suspend` | bool\|null | `null` → config `suspendNewCards` → **`false`** | **Revision 15, §27; default flipped in revision 16.** `true`: the cards this batch creates are left **suspended**, in the same undo entry as the adds, and listed in `suspended`. `null` (omitted) reads config key `suspendNewCards`, which **ships `false`** (stock-compatible; set it `true` to opt into the suspended-draft workflow); an explicit `true`/`false` always wins over config. Non-boolean → `[invalid_param]`, raised before any write. |

**Returns**

```json
{"added": [1712345678901, ...], "suspended": [1712345678911, ...],
 "skipped": [{"index": 3, "reason": "duplicate"}], "undoEntry": "AnkiConnect Plus: Bulk Add"}
```
- `added`: note ids of successful adds, in input order **excluding** skipped entries (use `skipped[].index` to realign).
- `suspended` (revision 15): **always present**; the **card** ids this call left suspended — every card of every added note, collected with `col.card_ids_of_note` (no raw SQL) and suspended in ONE op after the write loop, merged into the same undo entry. `[]` when `suspend` resolved `false` or nothing was added; since every added note produces at least one card, a non-empty `added` with `suspended: []` means suspension was switched off, so the pair is self-describing and no separate policy echo is needed. Newly created cards are queue `0`, so the op changes every id passed and `suspended` is exactly that set — and that expectation is **verified, not assumed** (revision-15 fix pass): `col.sched.suspend_cards` returns `OpChangesWithCount`, and when its `.count` does not equal the number of ids passed, the queues of those ids are re-read and `suspended` reports only the cards that really are queue `-1`. In that never-observed case a non-empty `added` with `suspended: []` means the backend disagreed, not that the policy was off — the response still states the post-op truth, which is the property that matters.
- `skipped[].index` is the 0-based index into the input `notes` array. `reason` strings: `"duplicate"`, `"duplicate (within batch)"`, `"empty first field"`, `"model was not found: <name>"`, `"deck was not found: <name>"`, `"field was not found in model: <field>"`, or for atomic=false hard errors the stringified exception.
- `undoEntry`: the undo entry name, or `null` if nothing was added.
- **Suspend-step failure is fatal in BOTH atomic modes (revision 15).** If the trailing suspend op raises, the whole batch is reverted and `[batch_reverted]` `"bulkAddNotes failed (batch reverted): " + json.dumps({"failedStep": "suspend", "error": ..., "addedBeforeRevert": N, "skipped": [...]})` is raised — note `failedStep`, not `failedIndex`: the step is not per-note. `atomic: false` does **not** downgrade it, because the caller asked for suspended drafts and returning added-but-live notes under a success response is exactly the silent divergence this add-on refuses to ship. (Unreachable in practice: the ids are cards this call just created.)
- **…and the revert claim is verified, not asserted (revision-15 fix pass).** `_revert_batch` can only undo while the batch's entry is still on TOP of the undo stack. If `col.sched.suspend_cards` SUCCEEDS and the following `col.merge_undo_entries` raises, anki's own `"Suspend"` entry sits above ours, the name check fails and nothing is rolled back. The handler therefore branches on `_revert_batch`'s return value: `[batch_reverted]` (the shape above) **only when the undo really fired**, otherwise `[internal]` `"bulkAddNotes failed (batch NOT reverted): " + json.dumps({"failedStep": "suspend", "error": ..., "reverted": false, "addedStillCommitted": N, "addedIds": [...], "skipped": [...]})`. A false "reverted" is worse than the original failure: the caller's retry would add every note twice, and `addedIds` is what it needs to clean up instead.

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
2. Core: validate `notes` is a non-empty list of dicts (empty list → return `{"added": [], "suspended": [], "skipped": [], "undoEntry": null}` — revision 15: `suspended` is present on **every** return path, including this one, so a caller can branch on one stable shape; the dry-run twin is `{"wouldAdd": 0, "wouldSuspend": <resolved bool>, "skipped": [], "undoEntry": null}`, which is why `suspend` is resolved and type-checked *before* this early return).
3. Resolution pass (no writes): resolve model + deck per note; compute `(mid, csum, stripped_first)` per note; batch-select existing csums per mid; mark each note `ok` / skip-reason. Track intra-batch `(mid, stripped_first)` seen-set: a second identical note in the same request is `"duplicate (within batch)"` unless that note allows duplicates. Empty `stripped_first` → `"empty first field"`.
4. Write pass: for the first `ok` note, `target = col.add_custom_undo_entry("AnkiConnect Plus: Bulk Add")`. For each `ok` note: build Note, set fields/tags, `col.add_note(note, did)`, append `note.id` to `added`, `col.merge_undo_entries(target)`.
4b. (Revision 15, §27) If `suspend` resolved `true` and `added` is non-empty: collect `col.card_ids_of_note(nid)` for every added note, `col.sched.suspend_cards(cardIds)`, then `col.merge_undo_entries(target)` **again** — the same target as the adds, so the whole batch (adds + suspension) is one undo entry (probe-verified: a single `col.undo()` removes the notes AND their cards, leaving no half state).
5. Hard error during the write pass (unexpected exception from Anki):
   - `atomic=true`: ensure entries are merged, then if `added` non-empty and `col.undo_status().undo == "AnkiConnect Plus: Bulk Add"`, call `col.undo()`. Then raise `[batch_reverted]` (§25) `"bulkAddNotes failed (batch reverted): " + json.dumps({"failedIndex": i, "error": str(e), "addedBeforeRevert": len(added), "skipped": skipped})`.
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
- Revision 15: default add → every card of every added note is queue `-1` and listed in `suspended`; a 2-card notetype reports BOTH cards; `suspend: false` → `suspended: []` and queue `0`; a single `col.undo()` after a default add removes notes and cards (one entry, not two); `suspend` non-boolean → `[invalid_param]` with note count and `undo_status()` unchanged; empty batch and all-skipped batch still report `suspended: []` / `wouldSuspend`; `undoLabel` + `suspend` still yields ONE labelled entry covering both halves.

### 4.2 `bulkUpdateNoteFields` (amended 2026-08-12, spec revision 7: no-op detection; revision 10: `diff` dry-run preview; revision 12: `__tags__` preview rows; **revision 14, round-3 review: tags are compared and previewed CANONIFIED**)

**Params**

| name | type | default | notes |
|---|---|---|---|
| `notes` | array of `{id: int, fields?: {FieldName: html}, tags?: [str]}` | required | `fields` updates only the named fields; `tags`, when present, **replaces** the note's whole tag list. At least one of `fields`/`tags` must be present per entry. |
| `atomic` | bool | `true` | Same contract as bulkAddNotes. |
| `dryRun` | bool | `false` | `true`: run the identical per-entry validation + no-op detection, write nothing, return `{wouldUpdate, unchanged, skipped, undoEntry: null}` — see §15. |
| `diff` | bool | `false` | Revision 10. **Only valid with `dryRun: true`** — `diff: true` on a real run raises `"[invalid_param] invalid parameter: diff: only valid with dryRun"` (diff is a preview feature; the real run stays lean). When set, the dry response additionally carries `preview` + `previewTruncated` — see §15. |
| `maxPreview` | int | `20` | Revision 10. Cap on `preview` entries (≥ 0); an entry is one **changed field** — or, from revision 12, one **changed tag list** — so one note can contribute several. Same knob as §21's. Validated on every call. |

**Tag rows in the `diff` preview (revision 12, round-3 field feedback)** — a note whose only change was `tags` used to land in `wouldUpdate` with **no preview row at all** (measured: 4 `wouldUpdate` entries, 3 preview rows; the reviewer saw a note slated for an update with no visible reason, and a note changing both fields and tags got a row that hid the tag half). A differing `tags` list now emits exactly one additional row, `{noteId, field: "__tags__", before: "<space-joined current tags>", after: "<space-joined requested tags>"}`, emitted **after** that note's field rows, counted in `previewTruncated`, and capped by `maxPreview` like any other row. `__tags__` is a reserved pseudo-field name; anki does not actually forbid a notetype field literally named `__tags__` (probe-verified), so that pathological collision is documented rather than defended against — field rows always come first. Post-revision-12 invariant, test-guarded: every id in `wouldUpdate` appears in the preview unless the cap cut it off.

**Tags are compared and previewed in the form anki will actually STORE (revision 14, round-3 review) — a behavior change on both the preview and the no-op rule.** `note.tags = list(tags); col.update_note(note)` does not store `tags`: the backend canonifies on save. Measured divergences between the request and the stored result — `['beta','alpha']` → `['alpha','beta']` (sorted, case-INsensitively: `['Zed','apple']` → `['apple','Zed']`); `['alpha','alpha']` → `['alpha']`; `['  alpha  ']` → `['alpha']`; `['Beta','beta']` → `['Beta']` (case-insensitive dedup, first occurrence wins); `['gamma delta']` → `['delta','gamma']` (ONE requested tag becomes TWO); and `['BETA']` with `beta` already in the collection's tag registry → `['beta']` (the REGISTERED spelling wins, matched on the full tag — a registered `Parent::Child` does not lend its case to a new `parent::other`). Two consequences, both fixed: (i) the `__tags__` row's `after` promised a post-state the write would not produce, and now carries the canonified form; (ii) the shared no-op check compared the raw request against already-canonical stored tags, so **an identical repeat of any non-canonical request was always reported `updated`/`wouldUpdate` and always wrote** — a `mod`/`usn` bump plus an undo entry for zero net data change — and now lands in `unchanged` with no write. `core.canonify_tags` mirrors the rule (`col.tags.canonify()` is a deprecated no-op stub in 25.09.4 and there is no canonify RPC), fed by one hoisted `core.tag_registry_map(col)` read per call rather than per note. Verified against the live backend on 400 randomized tag lists: 400/400 exact. Two documented approximations, neither able to cause a wrong write — python `str.lower()` stands in for rust unicase (agrees on ASCII and ordinary accented text), and the registry is a per-call snapshot. The REAL write still assigns the requested list and lets the backend canonify, so the backend stays the single source of truth for what is stored; the prediction is only ever used to REPORT and to suppress no-ops.

**Returns** `{"updated": [noteIds actually written], "unchanged": [noteIds whose requested values already matched], "skipped": [{"index", "reason"}], "suspensionPreserved": bool, "schedulingPreserved": bool, "undoEntry": "AnkiConnect Plus: Bulk Update" | null}` (`undoEntry` is `null` whenever `updated` is empty — nothing was written).

**Preserves (§31.1) + the revision-18 post-check (§31.2)** — a field/tags write must never move a card: scheduling, suspension, flags and deck assignment of every existing card are preserved (plus ids/GUIDs; tags unless the entry carries `tags`), and the response **proves the scheduling/suspension half per call**: the written notes' cards' `(queue, due, ivl)` are snapshotted immediately before each note's write and re-read after the batch — `suspensionPreserved` (queue `-1` membership unchanged in either direction) and `schedulingPreserved` (the whole triple unchanged; a suspension flip trips both), ALWAYS present on the real response, `true` on a zero-write batch, and reported `false` honestly if anything moved (never expected — that is the alarm's point). Cards BORN during the call are absent from the snapshot by construction: the one real non-preservation is the note's CARD SET — a field edit introducing a new cloze number generates that card (probe-verified: existing cards' rows stay byte-identical; removing a cloze deletes nothing — §30). Dry runs carry neither key: nothing was written.

**Shared no-op rule (revision 7; same rule as 4.3 `bulkAddTags`)** — an entry whose requested `fields` values ALL byte-match the note's current values AND whose `tags` (when present) equal the note's current tag list (exact list comparison, order-sensitive; Anki normalizes/sorts tags on write — probe-verified `["b","a"]` stores as `["a","b"]` — so re-sending the stored list no-ops while a re-ordered list is written and re-normalized) is **not written**: it creates no undo entry and its id is reported in `unchanged` instead of `updated`. Rationale (field feedback): the backend already no-ops byte-identical `update_note` calls physically, so the old behavior reported a write — and pushed an undo entry — that never happened; the response must tell the caller what was done, not what was asked. NOTE this narrows the meaning of `updated` (previously = attempted, revision 1 said "all values identical → still counts as updated"): the one deliberately non-additive change of revision 7.

**Anki API calls**

- `col.get_note(NoteId(id))` — raises `anki.errors.NotFoundError` → skip `"note was not found: <id>"`.
- Field membership: `name in note` (Note supports `__contains__`); unknown → skip `"field was not found in note: <name>"`.
- `col.update_note(note)` — creates "Update Note" entry (do NOT pass `skip_undo_entry=True`; we merge instead), merged per §3.3.

**Algorithm** — mirror of 4.1: validate → per-entry: load note, whole-entry field validation, no-op check (read-only, shared by the dry and real paths — see §15) → try: apply fields/tags, `col.update_note`, merge. Lazy undo entry `"AnkiConnect Plus: Bulk Update"`. Atomic revert + error report identical to 4.1 with prefix `"[batch_reverted] bulkUpdateNoteFields failed (batch reverted): "` (§25).

**Edge cases** — missing note id skipped; unknown field skipped without partial application of that entry's other fields (validate the whole entry before mutating the Note object); tags-only update; fields-only update; entry with neither `fields` nor `tags` → skip `"invalid parameter: notes[i]: fields or tags required"`; atomic revert restores original field values and tags; duplicate ids in one batch (second update wins; a later entry that re-requests values the note already has lands in `unchanged`); batch of only no-op entries → `updated: []`, `undoEntry: null`, undo stack untouched.

### 4.3 `bulkAddTags`

**Params**

| name | type | default | notes |
|---|---|---|---|
| `noteIds` | [int] | required | |
| `tags` | str or [str] | required | String is split on whitespace, upstream-style. Empty after normalization → error. |
| `atomic` | bool | `true` | |
| `dryRun` | bool | `false` | `true`: run the identical validation + missing-tag detection, write nothing, return `{wouldUpdate, skipped, undoEntry: null}` — see §15. |

**Returns** `{"updated": [noteIds that actually changed], "skipped": [{"index", "reason"}], "undoEntry": "AnkiConnect Plus: Bulk Tags" | null}`

**Anki API calls** — per note id: `col.get_note(nid)` (NotFoundError → skip `"note was not found: <id>"`); `note.has_tag(t)` / `note.add_tag(t)`; if any tag was actually added, `col.update_note(note)` + merge. Notes already having all tags are not written (and appear in neither list — count them in `updated`? No: spec decision — they are returned in `updated` **only if written**; unchanged notes are simply omitted from both lists; tests assert this). *(Revision 7 note: this only-write-what-changed rule is now shared with §4.2 `bulkUpdateNoteFields`, which additionally reports its no-op ids in an `unchanged` list; this action's shape is unchanged.)*

Single undo entry `"AnkiConnect Plus: Bulk Tags"` (lazy). Atomic contract identical, prefix `"[batch_reverted] bulkAddTags failed (batch reverted): "` (§25).

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

**Returns** `{"noteId": int, "cardIds": [int, ...], "undoEntry": str}` (cardIds ordered by card `ord`). `undoEntry` (added 2026-08-12, spec revision 9, §24): the actual top-of-stack undo entry name — the backend's own entry (locale-dependent, e.g. "Image Occlusion") by default, or `"AnkiConnect Plus: <label>"` when `undoLabel` is given (the custom entry then wraps the add AND the deck move; one undo reverts both, probe- and test-verified).

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

**Error cases** (codes per §25) — `[invalid_param]` `"invalid parameter: image: exactly one of path or data required"`; `[not_found]` `"image file was not found: <path>"` (checked with `os.path.isfile` before any write); `[invalid_param]` `"invalid parameter: image.data: invalid base64"`; `[invalid_param]` `"invalid parameter: image.filename: required with data"`; `[deck_not_found]` `"deck was not found: <name>"`; validation errors above (all `[invalid_param]`); `[not_found]` `"image occlusion notetype not found"`; `[internal]` `"image occlusion note was not created"`. All validation happens **before** the first write so failures leave no partial state.

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
    {"ordinal": 1, "shape": "rect", "left": 0.3949, "top": 0.0435, "width": 0.271, "height": 0.1016, "properties": {"oi": "1"}},
    {"ordinal": 2, "shape": "text", "properties": {"left": ".1", "top": ".2", "text": "label", "scale": "1"}}
  ],
  "header": "…", "backExtra": "…", "tags": ["…"], "occludeInactive": true
}
```
- One output entry **per shape**, flattened from the response's per-ordinal grouping (`occlusions[].shapes[]`), each carrying its group's `ordinal`.
- `shape == "rect"`: `left/top/width/height` coerced to float, and **every leftover property key is passed through in `properties`**. Corrected after the round-3 review: this used to name only `angle`/`fill` and read as if `properties` were the discriminator between rect and non-rect shapes. It is not — **every rect this add-on creates with the default `hideAllGuessOne: true` carries `properties: {"oi": "1"}`** (§4.4 serializes `:oi=1` onto each cloze), verified by round-tripping `addImageOcclusionNote` through `get_image_occlusion_note` headless. `properties` is omitted only when nothing is left over. **Callers must discriminate on the presence of `left`, never on the absence of `properties`.** Non-rect shapes (`ellipse`, `polygon`, `text`): raw `properties` dict of name→string as returned by the backend (Deviation #3).
- `occludeInactive` = backend's `occlude_inactive` (extension beyond the locked shape; harmless).

**Anki API calls** — `resp = col.get_image_occlusion_note(NoteId(noteId))` (`SP/anki/collection.py:457`). `resp.WhichOneof("value")`: `"error"` → raise `[not_found]` (§25) `"could not read image occlusion note %d: %s" % (noteId, <error>)`; `"note"` → parse `resp.note`: `image_file_name`, `occlusions[]` (each: `ordinal`, `shapes[]` with `shape` str + `properties[]` name/value pairs), `header`, `back_extra`, `tags`, `occlude_inactive`. `image_data` bytes are **not** returned (use upstream `retrieveMediaFile` for bytes).

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

**Returns** (changed 2026-08-12, spec revision 9, §24 — was `null` per the upstream update-action convention; nullability amended spec revision 11) `{"undoEntry": str | null}`: the actual top-of-stack undo entry name — the backend's own entry by default, or `"AnkiConnect Plus: <label>"` when `undoLabel` is given — or `null` when the update is a **no-op**: after omitted-param backfill every resolved value (occlusions string, header, backExtra, tags) already byte-matches the note, the backend performs zero undoable writes (rslib drops its own empty undo step), and the action returns before creating any entry, so it never echoes an unrelated pre-existing entry (revision 11; previously it reported whatever was on top of the stack) and never leaves an empty labeled entry behind. Errors raise.

**Anki API calls** — the backend updater requires all fields, so omitted params are backfilled from current state read **directly from the note's fields** (exact, no lossy re-serialization): `note = col.get_note(nid)`; `idx = col._backend.get_image_occlusion_fields(note.mid)` → `ImageOcclusionFieldIndexes` with `.occlusions/.image/.header/.back_extra` ordinals (probe: 0/1/2/3); current occlusions string = `note.fields[idx.occlusions]`, etc.; current tags = `note.tags`. Then `col.update_image_occlusion_note(note_id, occlusions_str, header, back_extra, tags)` (`SP/anki/collection.py:462`) → `OpChanges`, own undo entry.

**Edge cases** — header-only update leaves occlusion string byte-identical; occlusions array update regenerates cards (adding an ordinal grows card count, removing one empties/deletes — assert via card count after); tags-only; nonexistent note → NotFoundError surfaced as `"note was not found: <id>"`; non-IO note rejected before any write; single undo reverts; no-op update (values identical to current state — a re-sent unchanged header, or every param omitted) → `{undoEntry: null}` with the undo stack byte-untouched, both with and without `undoLabel` and with an unrelated marker entry already on the stack (revision 11); no `image` param exists (Deviation #2 — test that passing `image` raises TypeError via dispatch splat, which is acceptable: the enveloped error names the unexpected argument).

### 4.7 `queryRevlog` (amended 2026-08-12, spec revision 7: pagination + truncation signal)

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
| `offset` | int | `0` | Must be ≥ 0 (revision 7). Rows skipped after ordering, before `limit` — page N is `offset = N·limit`. |

Filters AND-combine; all omitted → whole table (limited).

**Returns** (revision 7: `total`/`truncated`/`nextOffset` added — the old `{rows}`-only shape could not distinguish "exactly `limit` rows exist" from silent truncation, which produced confidently wrong caller reports in the field)

```json
{"rows": [{"id": 1712345678901, "cardId": 1690000000000, "noteId": 1690000000000,
           "ease": 3, "interval": 10, "lastInterval": -600, "factor": 2500,
           "timeMs": 4200, "type": 1, "reviewedAt": 1712345678901}, ...],
 "total": 5541, "truncated": true, "nextOffset": 5000}
```
- `rows`: unchanged in shape and order (chronological ascending).
- `total` = full count of **distinct** matching revlog rows, before `offset`/`limit` (one cheap `COUNT(*)` per chunk query under the same WHERE; `cardIds`/`noteIds` are deduplicated before chunking — `dict.fromkeys`, order irrelevant since rows re-sort on `r.id` — so chunk pairs are disjoint and the counts sum exactly even when a duplicated id would otherwise straddle a chunk boundary; duplicate ids never duplicate rows).
- `truncated` = more matching rows remain beyond this page (`offset + len(rows) < total`).
- `nextOffset` = `offset + len(rows)` when `truncated`, else `null` — pass it back as `offset` to resume.
- `reviewedAt` duplicates `id` (both epoch-ms) per the locked shape. `noteId` is `null` for orphan revlog rows whose card was deleted. Field semantics (document in README): `interval`/`lastInterval` positive = days, negative = seconds; `factor` = SM-2 ease permille (0 for learning/manual; not scheduling-relevant under FSRS); `type`: 0 learning, 1 review, 2 relearning, 3 filtered/cram, 4 manual/forget, 5 rescheduled — stats-worthy rows are `type NOT IN (4, 5)`.

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
LIMIT ?  -- single chunk pair: LIMIT ? OFFSET ? pages in SQL; multi-chunk: each pair fetches its first offset+limit rows, the union is re-sorted and sliced [offset, offset+limit)
```
plus one `SELECT COUNT(*)` per chunk pair under the same WHERE (revision 7), via `col.db.all`/`col.db.scalar` (`DBProxy`; plain selects do not touch the undo queue — probe-verified). Caveat to document: the deck filter reflects each card's **current** deck, not the deck at review time (revlog stores no deck).

**Error cases** (codes per §25) — unknown deck → `[deck_not_found]`; non-int in id lists → `[invalid_param]` `"invalid parameter: cardIds: ints required"`; `limit < 1` → `[invalid_param]` `"invalid parameter: limit: must be >= 1"`; bad `offset` → `[invalid_param]` `"invalid parameter: offset: int >= 0 required"`.

**Edge cases** — empty result → `{"rows": [], "total": 0, "truncated": false, "nextOffset": null}` (also the shape for an empty `cardIds`/`noteIds` list); limit truncation (insert 10, limit 5 → first 5 chronologically with `total: 10`, `truncated: true`, `nextOffset: 5`); result count exactly `limit` → `truncated: false`, `nextOffset: null`; `offset` past `total` → empty `rows`, `truncated: false`; `nextOffset` chaining walks the full set with no gaps or overlaps; since/until window boundaries (id == sinceMs included, id == untilMs excluded); deck filter includes subdeck reviews; noteIds filter excludes orphans, bare query includes them with `noteId: null`; learning rows have negative `interval`; undo queue untouched after the action (assert `undo_status()` unchanged).

### 4.8 `createBackup`

**Params** — `{force: bool}`, default `true`.

**Returns** `{"created": bool}` — `false` means the backend skipped because nothing changed since the last backup (Deviation #4), not a failure.

**Anki API calls** — `col.create_backup(backup_folder=folder, force=force, wait_for_completion=True) -> bool` (`SP/anki/collection.py:325-351`; kw-only). `folder = os.path.join(os.path.dirname(col.path), "backups")` — derived from `col.path` so core stays aqt-free; this equals Anki's own per-profile backup folder for a normally-opened profile. `os.makedirs(folder, exist_ok=True)` first. Produces `backup-YYYY-MM-DD-HH.MM.SS.colpkg` and rotates old ones.

**Threading** — `wait_for_completion=True` blocks the main thread (UI freeze for the backup duration). Chosen so `{created}` is truthful and errors are raised synchronously; document in README.

**Edge cases** — fresh scratch collection with changes → `true` and a `backup-*.colpkg` appears in the sibling `backups/` dir; immediate second call → `false` (probe-verified sequence); `force=false` respects the user's backup-interval config (may return `false`); backup write failure (unwritable folder) → exception surfaced in the envelope.

### 4.9 `plusInfo` (amended 2026-08-12, spec revision 7: `actionDocs`; revision 10: `recipes`; revision 13: `returns`, `errorCodes`, `errorPrefixNote`; **revision 18: `preserves` + `effectiveConfig` — §31**)

**Params** — none. Must work with **no profile open** (do not call `self.collection()`); implemented wholly in `plus.py` from `core` constants + wrapper signatures.

**Returns**

```json
{
  "name": "AnkiConnect Plus",
  "version": "1.4.0",
  "specRevision": 19,
  "apiVersion": 6,
  "actions": ["bulkAddNotes", "bulkUpdateNoteFields", "bulkAddTags",
              "addImageOcclusionNote", "getImageOcclusionNote", "updateImageOcclusionNote",
              "queryRevlog", "createBackup", "plusInfo"],
  "actionDocs": {
    "notesSlim": {
      "summary": "Compact paginated note reader for LLM consumption: ...",
      "params": "query=null, noteIds=null, fields=null, stripHtml=true, maxFieldLength=400, offset=0, limit=200",
      "returns": "{total: int, notes: [{noteId, modelName, tags, fields, truncatedFields}], missing: [noteId], nextOffset: int|null} — ..."
    }
  },
  "errorCodes": {
    "sync_in_progress": {"retryable": true, "reachable": true, "meaning": "A syncNow job is mid-flight ..."}
  },
  "errorPrefixNote": "Prefixing boundary: errors from the 37 Plus actions AND the dispatcher's unknown-action error ...",
  "effectiveConfig": {
    "suspendNewCards": {"value": false, "source": "shipped_default"},
    "preserveSuspendedOnReschedule": {"value": true, "source": "shipped_default"}
  },
  "docs": {
    "plus": "<DOCS_PLUS>",
    "upstream": "https://foosoft.net/projects/anki-connect/",
    "upstreamSource": "https://git.sr.ht/~foosoft/anki-connect"
  }
}
```
`apiVersion` from `util.setting('apiVersion')`. `actions` is kept as bare names for compatibility.

**`version` + `specRevision` (revision 15 fix pass)** — `version` is `core.PLUS_VERSION` and `specRevision` is `core.PLUS_SPEC_REVISION`, an int equal to the revision number in this document's header line; a test parses that header and asserts both match, so neither can drift from the contract they claim to implement. Rationale: `plusInfo` is the one response a client is likely to fetch once and cache, and until revision 15 every revision was additive in behavior, so a frozen `1.0.0` cost nothing. Revision 15 changes what `bulkAddNotes` and `bulkSetDueDate` DO by default; a cached-`plusInfo` client that pins on version needs that to move. Rule going forward: **`specRevision` moves with every revision of this document; `PLUS_VERSION`'s minor moves whenever default behavior changes.**

**`actionDocs` (revision 7 — the discoverability fix)** — one entry per `PLUS_ACTIONS` name (`actionDocs` example above is elided to one entry): `summary` is the one-liner from `core.PLUS_ACTION_SUMMARIES` (a static dict beside `PLUS_ACTIONS`; keep both in lockstep), `params` is a JSON-flavored signature string generated at call time via `inspect.signature` on the bound `plus.py` wrapper (`self` already excluded on bound methods; defaults rendered with `json.dumps` so booleans/null read as JSON: `atomic=true`, `query=null`; the revision-10 `plus_api` error-code wrapper preserves the real signature via `functools.wraps`/`__wrapped__` — test-guarded). Rationale (field feedback): with bare action names only, an LLM caller could not discover that e.g. `notesSlim` has `stripHtml`/`maxFieldLength` and hand-rolled a worse bulk read. **Required-but-`None`-defaulted params (field feedback)**: the signature string cannot distinguish a genuine optional from a required-with-`None`-sentinel param (`field=null` on `bulkReplaceInFields` looks optional but is hard-required; same for the exactly-one-of `query`/`noteIds` pairs on `notesSlim`/`bulkReplaceInFields`) — so the `PLUS_ACTION_SUMMARIES` one-liner for any action with such params MUST name them as required; keep the summaries honest when adding actions.

**`recipes` (revision 10 — the discoverability LOCK, round-2 field feedback)** — the response gains a top-level `recipes` list (`core.PLUS_RECIPES`, static — plusInfo keeps working before a profile is open) of `{name, description, example}` entries: cross-action call patterns callers repeatedly failed to assemble from per-action docs alone. `example` is a ready-to-send `{action, params}` object. Required minimum set (test-guarded):
- **`raw field projection`** — the §13 raw-fidelity combination `fields=[...]` + `stripHtml=false` + `maxFieldLength=0` (named in the description with exactly those spellings), as the read-before-edit primitive;
- **`verified-sync contract`** — §18.2's verified-synced iff `job.state == "done" && required == "no_changes" && mediaSyncing == false`;
- **`dry-run-then-write pattern`** — §15's preview-first convention incl. `bulkUpdateNoteFields`' `diff: true` and (revision 11) §15's duplicate-note-id parity caveat;
- **`undo-label convention`** — §24's `undoLabel` naming rule and the `undoEntry` reporting contract;
- **`lean deck sweep`** (revision 12) — §13's `omitEmptyFields` (+ the `fields` projection) as the way to read a whole deck cheaply, paired with §12's `cssMode: "byNotetype"` / `format: "text"` when rendered cards are also needed. Rationale (measured): on a 19-field AnKing-derived notetype with ~4 populated fields, `omitEmptyFields` alone cut the payload 48–49% AND ran faster; the CSS knob cut a 20-card `renderCard` payload by 92%. Neither knob is discoverable from a per-action summary alone.
- **`reading errors`** (revision 13) — the §25.1 envelope as a decision procedure: never parse the error string, branch on `errorCode`, treat `null` as *uncoded upstream error*, and retry only on `retryable: true` (naming the four codes that carry it and what each one's recovery move is). Also states the `multi` trap — the outer reply reports success even when every sub-response failed. `example` is `plusInfo` itself, since fetching this map at startup is the recipe's actionable step.
- **`suspended-draft workflow`** (revision 15; revision 16 makes `suspendNewCards` opt-in) — §27's shipped deviation (`preserveSuspendedOnReschedule`) and opt-in mode (`suspendNewCards`) in one place: `bulkAddNotes`' `suspend` / `suspendNewCards` and `bulkSetDueDate`' `preserveSuspended` / `preserveSuspendedOnReschedule`, the *write suspended → a human reads → that human unsuspends* loop they exist to serve, `unsuspended` − `resuspended` as the cards actually left in review, the single-undo-entry guarantee, the deliberate no-re-bury asymmetry, and how to switch either off per call. This recipe and `safe deck export` are the two that document places where the fork deliberately does NOT behave like Anki, so they are the ones a caller most needs before its first write.
- **`safe deck export`** (revision 17 slice 2; revision 19 grows it into the full filtered-deck lifecycle) — CREATE → REBUILD → REPORT → EMPTY → export, mirroring the served description: `createFilteredDeck` builds a cram deck from a search as one undoable op (`dryRun` first answers "how big would it be" without creating anything; suspended/buried/other-filter cards are never gathered), `rebuildFilteredDeck` re-runs a deck's saved terms with both halves reported (`returnedFirst`/`cardsGathered`), then the revision-17 export tie-in: `filteredDeckReport` with `deckName=<export deck>` to see what filtered decks hold (its `totalCards` is the home-side count the export check trips on; the unscoped report also shows nested filters holding foreign-homed cards, the fix pass's second flagged set), `emptyFilteredDeck` per named filter, then a clean `exportDeckApkg`; names the `[cards_in_filtered_decks]` refusal, the measured 141-cards/96-notes near-miss that motivated it, and `allowFilteredOmission=true` + `warnings` as the deliberate-omission path. Documents the fail-closed default — the round-4 behavior change (§0 Deviation #14).
- **`empty-cards cleanup`** (revision 17 slice 2) — the §§20/30 audit → remediate loop: `checkDeckIntegrity`'s `clozeCardMismatch` DETECTS, `getEmptyCards` reports actionably (per-note delete/protect split), `deleteEmptyCards` `dryRun` previews the exact card ids, the real call deletes as one undoable batch; states the dialog's own protection rule (never a note's last card, never the note — `protected` / `notesPreserved`).

**`returns` (revision 13 — round-3 ASK 1, the highest-leverage ask)** — each `actionDocs` entry gains a third key, a shape sketch from the static `core.PLUS_ACTION_RETURNS`. Rationale (measured in real use): `actionDocs` documented **inputs and nothing else**, so callers guessed output shapes and took `KeyError`s — `entries` guessed for `queryRevlog` (really `{rows, total, truncated, nextOffset}`), a bare list for `renderCard` (really `{cards: [...]}`) — and then had to read this SPEC, which a client without repo access cannot do. Unlike `params`, a return shape is **not introspectable**, so these are hand-written and must be maintained with the code: `set(PLUS_ACTION_RETURNS) == set(PLUS_ACTIONS)` is test-locked, as is a non-empty `{`-leading sketch for every action. Format: the same JSON-flavored shorthand as `params` — `key: type` pairs, `|` for alternatives, `[...]` for an array of the enclosed item shape — with conditional keys (`dryRun` variants, `cssMode`-dependent `css`/`cssByNotetype`, `problems`) named inline, and the round-3 shape changes (`missing`, `unsuspended`/`unburied`, `orphanMediaCollectionWide`, `serverChecked`, `actualName`) all described. Where a caller was measured guessing wrong, the sketch names the trap explicitly (`queryRevlog`'s says "NOT 'entries'").

**`preserves` (revision 18 — §31.1)** — side-effectful actions' `actionDocs` entries carry a fourth key, `preserves`, from the static `core.PLUS_ACTION_PRESERVES`: what the action does **not** touch among scheduling (due/interval/queue), suspension, flags, tags, note ids, GUIDs, deck assignment — with its genuine non-preservations named in the same breath. Read-only actions carry no `preserves` key (their summaries already say read-only); the key set of `PLUS_ACTION_PRESERVES` is test-locked to exactly the side-effectful subset. §31.1 is the per-action registry.

**`effectiveConfig` (revision 18 — §31.3; source probe corrected by the revision-18 fix pass)** — the two §27 config knobs **resolved for this install at call time**, `{suspendNewCards: {value, source}, preserveSuspendedOnReschedule: {value, source}}`, computed through the same `_resolve_suspension_config` ladder the write actions use — by construction, what the next parameterless `bulkAddNotes`/`bulkSetDueDate` will do. `source` is `"user_config"` only when the **user's saved config** — `meta.json`'s `config` dict, probed via `addonManager.addonMeta` — carries the key with a usable boolean. The probe is deliberately NOT `addonManager.getConfig`: `getConfig` returns the shipped `config.json` defaults with the user's keys merged over them, and this add-on ships both §27 keys in `config.json`, so a merged-view probe would see a boolean for every key on every intact install and claim `user_config` unconditionally (the round-5 review caught exactly that). `"shipped_default"` covers key-absent-from-the-user-store, unreadable-config, headless no-`mw` (the value is then the shipped default — `util.DEFAULT_CONFIG` and the `core` constants, lockstep-tested equal), and non-boolean typo values, which resolution deliberately ignores. One honest caveat: saving Anki's add-on config dialog writes the **entire merged dict** into `meta.json` (`writeConfig`), so after any dialog save every shipped key is legitimately user-stored and reports `user_config` from then on. Config reads only — `plusInfo` still works before a profile is open.

**`errorCodes` + `errorPrefixNote` (revision 13 — round-3 ASK 4)** — the response gains `errorCodes`, the full §25 vocabulary as `{code: {retryable: bool, reachable: bool, meaning: str}}`, so a client can build its retry table **at runtime** instead of hardcoding this spec's table. `retryable` is read from `core.PLUS_ERROR_CODES` (single source of truth — the map is assembled per call, so drift is impossible); `reachable` and `meaning` come from `core.PLUS_ERROR_CODE_DOCS`, whose key set is test-locked to the vocabulary. `errorPrefixNote` is `core.PLUS_ERROR_PREFIX_NOTE` verbatim: the one boundary rule (§25.1) a client cannot infer from a single response — Plus + unknown-action errors are coded and prefixed, upstream AnkiConnect errors are neither.

**Edge cases** — callable before profile load (signature reflection touches no collection); callable through `multi`; **callable during a sync** (`guard_sync=False`, §25.2); action list exactly matches `core.PLUS_ACTIONS` (single source of truth — test asserts every listed name is a dispatchable `@util.api()` method); every `actionDocs` entry has `{summary, params, returns}` exactly — plus `preserves` exactly when the action is side-effectful (§31.1) —, a non-empty `summary`, a `params` string matching the wrapper's real signature, and a non-empty `returns`; `errorCodes` covers the vocabulary exactly (incl. `unknown_action`) with `retryable` matching `PLUS_ERROR_CODES` per code and every reserved code's `meaning` saying so.

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
    "ignoreOriginList": [],
    "preserveSuspendedOnReschedule": true,
    "suspendNewCards": false
}
```
Only the port changes vs upstream, plus the two revision-15 suspension keys (§27). Keys absent here (`apiPollInterval`, `apiVersion`, `webBacklog`, `webTimeout`, `webCorsOrigin`) intentionally fall through to `DEFAULT_CONFIG` in `util.py`.

**Revision 15 — `preserveSuspendedOnReschedule` (ships `true`) / `suspendNewCards` (shipped `true` in revision 15, `false` since revision 16), §27.** These are *defaults*, not switches: an explicit `preserveSuspended` / `suspend` parameter on the call always wins. Their values live in THREE places that must agree — this `config.json`, `util.DEFAULT_CONFIG`, and `core.DEFAULT_PRESERVE_SUSPENDED_ON_RESCHEDULE` / `core.DEFAULT_SUSPEND_NEW_CARDS` — and a test locks the three in lockstep. `core.py` never reads config (it is aqt-free); `plus.py` resolves the value and passes an explicit bool down, falling back to the core constant when the read fails. An **older `config.json` missing these keys keeps working**: `util.setting` already falls back to `DEFAULT_CONFIG`, and `plus.py` falls back again if that read raises. A non-boolean value is ignored in favor of the documented default (documented in `config.md`) — a config typo must not fail a write action.

### 6.2 `util.py` edits

- `DEFAULT_CONFIG['webBindPort']` (`util.py:76`): `8765` → `8766`.
- Revision 15: `DEFAULT_CONFIG` gains `'preserveSuspendedOnReschedule': True` and `'suspendNewCards': True` (§27); revision 16 flips `'suspendNewCards'` to `False`. Spelled as literals rather than imported from `core` so this upstream module keeps its import graph; the lockstep test is what keeps them honest.
- Env vars (`util.py:75,77`): `ANKICONNECT_BIND_ADDRESS` → `ANKICONNECT_PLUS_BIND_ADDRESS`, `ANKICONNECT_CORS_ORIGIN` → `ANKICONNECT_PLUS_CORS_ORIGIN`. (Stock AnkiConnect reads the originals; sharing them would force both add-ons onto the same bind address → port-clash dialog.)

### 6.3 `config.md`

Rewrite: title "AnkiConnect Plus", note default port **8766** and that stock AnkiConnect (8765) can run alongside; document every key (`apiKey`, `apiLogPath`, `webBindAddress`, `webBindPort`, `webCorsOriginList`, `ignoreOriginList`, and — revision 15 — `preserveSuspendedOnReschedule` / `suspendNewCards` under their own "deliberate deviations from Anki's own behavior" heading, each with its switch-off) and the two renamed env vars; link to the repo README for the Plus action docs; retain a credit line + link to upstream AnkiConnect docs (replaces the current foosoft link at `config.md:1`).

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
   `ln -s <repo>/connect_plus "~/Library/Application Support/Anki2/addons21/connect_plus"` (macOS path; folder name is load-bearing, §6.4). Restart Anki. (The symlink itself is an addons21 *addition*, not a modification of existing Anki data; creating it is a user action — never automated by tooling per the hard rules.)
4. **Coexistence note**: runs alongside stock AnkiConnect (2055492159) in the same Anki — stock on 8765, Plus on 8766; all upstream actions are also served on 8766; configs are independent; env overrides are `ANKICONNECT_PLUS_BIND_ADDRESS` / `ANKICONNECT_PLUS_CORS_ORIGIN`; banner string on 8766 reads "AnkiConnect Plus v.6".
5. **New-action reference**: params/returns/errors for every Plus action (condensed from §§4, 11–14, 16–30), incl. the `interval` sign convention and `type` enum for queryRevlog, the atomic/undo contract for bulks, the `dryRun` param on the three bulk actions (`wouldAdd` count vs `wouldUpdate` id-list, `undoEntry: null`, and §15's skipped-media-embedding limitation), the `bulkSetDueDate` `days` grammar, the `exportDeckApkg` never-overwrite `-2` suffixing and fixed `with_deck_configs=False` choice, deviations #1–#8, and one curl example, e.g.:
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

**Error cases** (codes per §25) — `[invalid_param]` `"invalid parameter: filename: string required"` / `"invalid parameter: filename: bare media filename required"`; `[not_found]` `"media file was not found: <filename>"`; `[unsupported_format]` `"could not load image: <filename> (unsupported or corrupt format)"`; `[invalid_param]` `"invalid parameter: rect: object required"` / `"... <key> must be a number"` / `"... left and top must be within 0-1"` / `"... width and height must be within 0-1"` / `"invalid parameter: rect: selects an empty area of <filename> (<W>x<H>)"`; `[unsupported_format]` `"could not encode cropped image as <fmt>: <filename>"`; `[invalid_param]` `"invalid parameter: noteIds: ints required"`; `[not_found]` `"note was not found: <id>"`; `[batch_reverted]` `"cropImage failed (note updates reverted): <err>"`.

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

**Refusals (clear error, zero changes; all `[validation_error]` per §25)**
- The crop would drop ALL occlusions → `"crop would remove all occlusions on note <id>"`.
- The note contains non-rect shapes (`ellipse`/`polygon`/`text`, possible on editor-made notes per Deviation #3) → `"cropImageOcclusionImage supports rect occlusions only; note <id> contains a <shape> shape"`. Rationale: §5's serializer emits rects only; proceeding would silently destroy those shapes.
- A rect carries properties other than `oi` (e.g. `angle`, `fill`) → `"cropImageOcclusionImage cannot preserve occlusion properties <names> on note <id>"`. Same rationale (v1 serializer does not emit them).
- The rects carry **mixed** per-shape `oi` flags (some have `oi=1`, some don't) → `"cropImageOcclusionImage cannot preserve mixed oi flags on note <id>"`. Same rationale (§5 serialization is all-or-nothing per note; see the oi bullet above).

**Atomicity / undo (probe-verified pattern)** — read via the §4.5 path; `header`/`backExtra`/`tags` backfilled from the note's own fields via `col._backend.get_image_occlusion_fields` exactly as §4.6. Media write first (not undoable; new file only). Then `target = col.add_custom_undo_entry("AnkiConnect Plus: Crop IO Image")` → write 1: `note.fields[idx.image] = '<img src="<newFilename>">'` (raw filename, double quotes — byte-identical format to what the backend itself writes) via `col.update_note` + merge → write 2: `col.update_image_occlusion_note(noteId, remappedOcclusions, header, backExtra, tags)` + merge. A single `col.undo()` restores BOTH the image field and the occlusion string. Failure between the writes reverts the merged entry and raises `"cropImageOcclusionImage failed (changes reverted): <err>"`.

**`cardIds`** — current card ids after the update, via the card-id location select (explicitly allowed read-only select, §4.4 precedent). Caveat (research-verified): if every shape of some ordinal was dropped, the backend does **not** delete that ordinal's now-empty card; its id still appears in `cardIds` and Empty Cards is the cleanup path. Document in README.

**Error cases** (codes per §25) — `[invalid_param]` `"invalid parameter: noteId: int required"`; `[not_found]` `"note was not found: <id>"`; `[validation_error]` `"note is not an image occlusion note: <id>"`; §4.5 read-error path (`[not_found]`); `[validation_error]` `"could not parse rect occlusion on note <id>"` (a backend rect shape whose left/top/width/height failed float parsing, i.e. the §4.5 parser fell back to raw properties); `[validation_error]` `"image occlusion note has no image file: <id>"`; all §11.1 media/rect/format errors (their §11.1 codes); the refusals above (`[validation_error]`); `[batch_reverted]` `"cropImageOcclusionImage failed (changes reverted): <err>"`.

**Edge cases tests must cover** — rect fully inside → kept unclipped, coords remap exactly; rect straddling a crop edge → kept + clipped, clipped edge lands on the crop boundary (`left' == 0` etc.); rect fully outside → dropped; all-outside → refusal with note byte-identical; kept ordinals round-trip through §4.5 within 1e-4; empty-card gotcha surfaced in `cardIds`; single undo restores original image filename AND original rects; original media file untouched; mixed per-shape `oi` (hand-built occlusions string, `oi=1` on one cloze only) → refusal with note untouched.

### 11.3 Shared crop mechanics

- **Pixel mapping + clamp** (shared by both actions): `cx = clamp(round(left·W), 0, W)`, `cy = clamp(round(top·H), 0, H)`, `cw = min(round(width·W), W−cx)`, `ch = min(round(height·H), H−cy)`. If `cw < 1` or `ch < 1` → empty-area error. Guarantees `copy(QRect(...))` stays within bounds, so Qt's pad behavior is unreachable.
- **Derived naming**: `<stem>-crop.<ext>` keeping the source extension when Qt can encode it; otherwise (readable-but-not-writable formats: `gif`, `svg`, `svgz`, `pdf`, `tga`, or an unknown extension) the crop is re-encoded as PNG under `<stem>-crop.png`. Name collisions are resolved by `col.media.write_data`'s dedup (same bytes → same name reused; different bytes → sha1-renamed) and the returned name is authoritative.
- **Write-format allowlist** (probe-verified on this build): `bmp cur heic heif icns ico jfif jp2 jpeg jpg pbm pgm png ppm tif tiff wbmp webp xbm xpm` (`core.CROP_WRITE_FORMATS`).
- **Headless rule**: all Qt imports live inside the core function bodies (lazy), keeping `core.py`'s module import aqt-free AND Qt-free; no application object is created. Pillow is not a dependency (not installed in the venv).

---

## 12. `renderCard` (spec revision 3, 2026-08-11; amended 2026-08-12, spec revision 7: `format` param + style/script clarification; revision 12: `cssMode` + per-card `notetype`)

First of three **read-only** actions (`renderCard`, `notesSlim`, `mediaThumbnails` — §§12–14) bringing the action count to fourteen. `core.PLUS_ACTIONS` remains the single source of truth for the `plusInfo` action list. None of the three performs any collection write, media write, or undo-stack change; tests assert `undo_status()` unchanged after each call.

Render cards' question/answer HTML exactly as Anki's own template pipeline produces them.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `cardIds` | [int] | required | Bad ids (and per-card render failures) become per-item `error` entries, never a hard failure. Empty list → `{"cards": []}`. |
| `format` | str | `"html"` | Revision 7. `"html"` = raw rendered template HTML (byte-identical to pre-revision-7 output). `"body"` = `question`/`answer` with matched `<script>…</script>` and `<style>…</style>` blocks removed (regex, case-insensitive, dot-matches-newline, non-greedy; unclosed blocks are left in place). `"text"` = visible text only via the same backend strip helper `notesSlim` uses (`html_to_text_line`, media filenames preserved, cloze markup verbatim — §13 conventions). Bad value → hard error `"invalid parameter: format: one of html, body, text required"`. Applies to `question`/`answer` only; every other per-card field is unchanged. |
| `cssMode` | str | `null` | Revision 12. How the notetype stylesheet is delivered: `"perCard"` (a `css` key on every card — the pre-revision-12 behavior), `"byNotetype"` (ONE top-level `cssByNotetype: {notetypeName: css}`, no per-card `css`), `"omit"` (no CSS anywhere). `null` = the **format-dependent default**: `"omit"` for `format: "text"`, `"perCard"` for `"html"`/`"body"`. An explicit value always wins, in either direction. Bad value → hard error `"invalid parameter: cssMode: one of perCard, byNotetype, omit required"`. |

**Returns**

```json
{"cards": [
  {"cardId": 1712345678901, "question": "<b>front html</b>", "answer": "…", "css": ".card {…}", "deckName": "HA2::PI 7", "modelName": "Basic", "notetype": "Basic", "ord": 0},
  {"cardId": 42, "error": "card was not found: 42"}
]}
```
```json
{"cards": [{"cardId": 1712345678901, "question": "…", "answer": "…", "deckName": "HA2::PI 7", "modelName": "Basic", "notetype": "Basic", "ord": 0}],
 "cssByNotetype": {"Basic": ".card {…}"}}
```

**CSS delivery (revision 12, round-3 field feedback).** Rationale, measured in real use: 50 rendered cards at `format: "text"` totalled 314,564 B, of which 265,350 B (**90%**) was the SAME AnKing stylesheet repeated once per card, against 27,951 B of actual content — and in a text render the CSS styles nothing at all. Contract:
- `"perCard"` — unchanged shape: `css` on every successfully rendered card.
- `"byNotetype"` — the response gains a top-level `cssByNotetype` map (first render of a notetype wins; the stylesheet is a property of the notetype, identical for all its cards) and per-card `css` is **omitted**. The key is missing entirely in the other two modes, so their shapes are byte-unchanged. Re-verified on this build: 20 cards on a 5.5 kB stylesheet shrank 92.2%.
- `"omit"` — no `css` key and no `cssByNotetype`. Default for `format: "text"` (measured 97.1% smaller than the old text response). **This default is the one non-additive edge of revision 12's `renderCard` change**: `format: "text"` responses no longer carry `css`. The format itself was one day old, and `cssMode: "perCard"` restores the old bytes exactly.
- **`notetype`** is present on every successfully rendered card in **all** modes (additive) — it is the key `cssByNotetype` is keyed by. `modelName` carries the identical string and is retained for compat with upstream AnkiConnect's naming.
- Per-item error entries (`{cardId, error}`) never carry `css`/`notetype` in any mode.

- `question`/`answer` are the rendered template HTML **without** the notetype-CSS `<style>` wrapper; `css` is the notetype styling returned separately (clients wanting the `card.question()` equivalent concatenate `"<style>" + css + "</style>" + question`). **Clarification (revision 7, field-verified):** "without the `<style>` wrapper" refers ONLY to that notetype-CSS wrapper — `<style>`/`<script>` blocks **authored inside the card template itself** are part of the rendered HTML and are returned verbatim under `format: "html"` (on script-heavy notetypes like AnKing they can dominate the payload: a field case measured 76% of a 43 kB answer inside `<script>` tags). Callers that don't want them use `format: "body"` or `"text"` — an LLM consumer almost always wants `"text"`.
- Audio/TTS: rendered text contains `[anki:play:q:<idx>]` markers in place of `[sound:...]` tags (backend behavior). The referenced filenames live in the render output's `question_av_tags`/`answer_av_tags` and are **not** returned in v1.
- `deckName` is the card's current home deck (`odid` when in a filtered deck) via `col.decks.name(card.current_deck_id())`.
- One entry per input id, in input order; duplicate ids render twice.

**Anki API calls** — `col.get_card(cid)` (`NotFoundError` → per-item `"card was not found: <id>"`); `card.render_output()` (`SP/anki/cards.py:161-170`) → `TemplateRenderOutput` (`SP/anki/template.py:280-293`) with `question_text`/`answer_text`/`css`; `col.decks.name(card.current_deck_id())` (`SP/anki/decks.py:384-388`, `SP/anki/cards.py:194-195`); `card.note_type()["name"]` (`SP/anki/cards.py:180-181`, cached lookup). `anki.template` imports zero aqt — probe-verified headless render of Basic + Cloze cards.

**Error cases** (codes per §25) — hard (whole action, all `[invalid_param]`): `"invalid parameter: cardIds: ints required"` (non-list, or any non-int/bool element); `"invalid parameter: format: one of html, body, text required"` (revision 7); `"invalid parameter: cssMode: one of perCard, byNotetype, omit required"` (revision 12). Per-item (unprefixed, §3.2): `"card was not found: <id>"`; any per-card render exception → `"could not render card <id>: <err>"`.

**Edge cases tests must cover** — Basic card renders (question contains the field text, css non-empty, `ord` 0); cloze question contains `class="cloze"` markup; mixed good/bad ids → per-item errors interleaved in input order with successful renders; a `[sound:...]` field renders with an `[anki:play:` marker in the text; template-authored `<script>`/`<style>` blocks present under `format: "html"`, absent under `"body"` (surrounding HTML kept), and `"text"` returns visible text with no tags; bad `format` → hard error; undo queue untouched. Revision 12: `format: "text"` carries no `css` by default while `cssMode: "perCard"` restores it; `cssMode: "omit"` on `format: "html"` drops it; `cssMode: "byNotetype"` over a mixed-notetype batch yields one map entry per notetype (values equal to the per-card `css` of the same cards), no per-card `css`, and a `notetype` key on every rendered card; bad `cssMode` → hard error; `render_card(col, [])` still returns exactly `{"cards": []}` in the default mode.

## 13. `notesSlim` (spec revision 3, 2026-08-11; amended 2026-08-12, spec revision 7: per-note `truncatedFields`; revision 10: raw-fidelity field projection named; revision 12: honest `total` + `missing`, `omitEmptyFields`)

Compact, paginated, HTML-stripped note reader designed for LLM consumption: deterministic order, bounded field lengths, one round trip. Read-only; the `noteIds` path issues ONE chunked read-only id-existence select (revision 12, Deviation #11c), the `query` path none.

**Raw-fidelity field projection (revision 10 — discoverability lock, round-2 field feedback: callers failed to find this combination twice).** The combination `fields=[...]` + `stripHtml: false` + `maxFieldLength: 0` is THE supported way to read chosen fields' **exact stored HTML** — no stripping, no truncation, byte-identical to what `bulkUpdateNoteFields`/`bulkReplaceInFields` operate on. This combination is named ("raw-fidelity field projection") in `notesSlim`'s `PLUS_ACTION_SUMMARIES` one-liner (the §4.9 `actionDocs` surface) and repeated as the §4.9 `recipes` entry `raw field projection`; both are test-guarded so the naming cannot silently regress.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `query` | str | — | Anki search string, passed **verbatim** to the backend parser (empty string matches all notes). Exactly one of `query`/`noteIds` is required. |
| `noteIds` | [int] | — | Explicit ids; page order = caller order (duplicates allowed and returned twice). |
| `fields` | [str] | `null` | Field-name filter; `null` = all fields. Names not present on a note's model are simply absent for that note (a result set may span models) — never an error. |
| `stripHtml` | bool | `true` | Strips via the backend single-line helper: media filenames preserved, `[sound:...]` tags kept, `<br>`/`<div>` boundaries become single spaces. `false` returns raw field HTML. |
| `maxFieldLength` | int | `400` | Per-field character cap applied AFTER stripping (or to the raw HTML when `stripHtml: false` — may cut mid-tag; it is a preview); longer values are cut at the cap with `…` appended. `0` = no truncation. Truncation is also signalled explicitly per note via `truncatedFields` (revision 7) — the `…` marker alone is ambiguous, since a field may genuinely end in `…`. |
| `omitEmptyFields` | bool | `false` | Revision 12. `true`: a field whose **emitted** value is the empty string is dropped from that note's `fields` dict entirely (so under `stripHtml: true` a field holding only markup, e.g. `<br>`, also drops out; with `stripHtml: false` that same field survives as `"<br>"`). Default `false` keeps every field, so the pre-revision-12 shape is unchanged. Rationale (measured in real use): an AnKing-derived notetype has 19 fields of which a typical note populates 4 — 27% of a 50-note payload was empty strings in the field report, 48–49% on the re-verified 20-note case here, and the projected call was also **faster** (0.68 ms → 0.29 ms measured, 1.33 → 0.93 ms re-verified). |
| `offset` | int | `0` | Offset into the full matched id list. |
| `limit` | int | `200` | Must be ≥ 1; values above 2000 are silently clamped to 2000 (`core.NOTES_SLIM_LIMIT_CAP`). |

**Returns**

```json
{"total": 812,
 "notes": [{"noteId": 1712345678901, "modelName": "Cloze", "tags": ["HA2::PI7"],
            "fields": {"Text": "The capital of {{c1::France}} is {{c2::Paris::city hint}}.", "Back Extra": ""},
            "truncatedFields": []}],
 "missing": [],
 "nextOffset": 200}
```

- **`total` (revision 12 — DELIBERATE BREAKING CHANGE on the `noteIds` path).** Query path, unchanged: the full match count before pagination. noteIds path: the number of requested entries that **were found** — it used to be `len(requested ids)`, which counted ids whose note no longer exists and had no channel to say so. Measured before/after on the reported repro: `[real, fake, real, fake]` reported `{total: 4, notes: [2 notes]}` and now reports `{total: 2, missing: [fake, fake]}`; `[3 fakes]` with `limit: 2` reported `{total: 3, notes: [], nextOffset: 2}` — instructing a pager to fetch a second page that could only be empty — and now reports `{total: 0, notes: [], missing: [3 ids], nextOffset: null}`. Duplicates are counted on both sides exactly as they are returned (`[id, id]` for an existing note → `total: 2`), which makes the invariant **`len(noteIds) == total + len(missing)`** hold on every page.
  - **Cost of that invariant, disclosed (round-3 review).** Making `total`/`missing` window-INdependent means every page re-scans the WHOLE requested id list (`_existing_note_ids`, one chunked `select id from notes where id in (…)`), so a full paged pass over N ids at page size L costs O(N²/L), not O(N). Measured on a 5,000-note scratch collection: the scan is ~0.83 µs per id (0.42 ms at N=500, 1.53 ms at N=2,000, 4.13 ms at N=5,000), so a full pass at the default `limit: 200` adds ~1 ms at N=500, ~15 ms at N=2,000, ~103 ms at N=5,000 and ~1.7 s at N=20,000. There is deliberately no opt-out param: the window-independence is the point of the revision-12 fix, and a flag to turn it off would be a flag to turn the old lie back on. **Callers paging a large `noteIds` list should read `total`/`missing` from the FIRST page and carry them** — they cannot change between pages of one pass, since the scan covers the whole list every time.
- **`missing` (revision 12)**: always present. `[]` on the query path (every id came out of the search). On the noteIds path: every requested id whose note no longer exists, in caller order with duplicates preserved (that is what makes the invariant above hold). It is computed over the WHOLE requested list, not just the current page, so it is identical on every page of a walk.
- `nextOffset` = `offset + limit` while more ids remain, else `null`. The window is over the requested **id list** (which is what `offset`/`limit` slice) — under `noteIds` that is no longer the same number as `total` — and it is additionally suppressed when no FOUND id remains past the window, so a caller is never sent after a page that can only come back empty. Query path behavior is bit-identical to revision 11.
- `truncatedFields` (revision 7): per-note list of the field names whose returned value was cut by `maxFieldLength` — **always present**, `[]` when nothing was truncated; names appear in the note's model field order. The `…` marker behavior is unchanged; this is the unambiguous signal.
- **Cloze markup passes through unmodified** under `stripHtml: true`: the backend single-line helper strips HTML only, so `{{c1::...}}` / `{{c2::...::hint}}` markers survive verbatim in the output (probe-verified) — clients must not expect any bracketed-hint conversion.
- **Deterministic order**: query path returns ascending `noteId` (creation order — ids are sorted in core, `find_notes` is called with `order=False`); noteIds path preserves caller order.
- The `fields` output dict is in the note's model field order (filtered by the `fields` param when given, minus the empties when `omitEmptyFields` is set).
- noteIds path: an id whose note no longer exists is still **omitted** from `notes` (this shape has no per-item error entry) — but from revision 12 it is named in `missing` and excluded from `total`, so a short page is explained rather than silent. Query-path ids always exist (same synchronous handler, §3.1).

**Anki API calls** — `col.find_notes(query, order=False)` (`SP/anki/collection.py:669-683`; result supports `len()` and slicing; `order=False` is the fastest path, ordering is ours) — bad syntax raises `anki.errors.SearchError`, re-raised as `"invalid parameter: query: <backend message>"`; `col.get_note(nid)` (`NotFoundError` → omit, noteIds path only); `note.note_type()` for model name + field order. Revision 12, noteIds path only: one chunked (`SQL_IN_CHUNK`) read-only `select id from notes where id in (...)` over the deduplicated requested ids, to decide `total`/`missing`/`nextOffset` for ids outside the current page (Deviation #11c — this is the section's only SQL, and it is a note-id existence select, the family the HARD RULES allow). HTML stripping: `col._backend.html_to_text_line(text=..., preserve_media_filenames=True)` — the module-level `anki.utils.html_to_text_line` routes through the collection-less `current_i18n` backend and raises `CollectionNotOpen` headless (probe-verified gotcha), so the open collection's backend is called directly.

**Error cases** (all `[invalid_param]` per §25) — `"invalid parameter: query: exactly one of query or noteIds required"` (both given or neither); `"invalid parameter: query: string required"`; `"invalid parameter: query: <backend parse error>"`; `"invalid parameter: noteIds: ints required"`; `"invalid parameter: fields: list of strings required"`; `"invalid parameter: stripHtml: boolean required"`; `"invalid parameter: maxFieldLength: int >= 0 required"`; `"invalid parameter: offset: int >= 0 required"`; `"invalid parameter: limit: must be >= 1"`; `"invalid parameter: omitEmptyFields: boolean required"` (revision 12).

**Edge cases tests must cover** — query/noteIds mutual exclusion (both and neither → error); pagination: `total` stable across pages, `nextOffset` chains cover exactly `total`, final page `nextOffset: null`; ascending id order on the query path, caller order on the noteIds path; `stripHtml: true` collapses `<div>` lines to single spaces and keeps media filenames; `stripHtml: false` returns raw HTML; `maxFieldLength` truncates at the cap with `…` appended and the field name listed in `truncatedFields`, `0` disables and `truncatedFields` stays `[]` (also `[]` for untruncated fields genuinely ending in `…`); `fields` filter returns only the named fields, unknown name absent without error; empty query string matches all notes; bad search syntax → query error; undo queue untouched. Revision 12: stale noteId omitted from `notes`, named in `missing`, and NOT counted in `total`; duplicates counted on both sides so `len(noteIds) == total + len(missing)`; an all-stale page returns `nextOffset: null` while a real id past the window still yields a `nextOffset` whose page returns that note; query path keeps `total` = match count with `missing: []`; `omitEmptyFields` drops empty-valued fields (including a markup-only field under `stripHtml: true`, which survives under `stripHtml: false`) and defaults to off; bad `omitEmptyFields` → error.

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

**Error cases** (codes per §25) — hard (all `[invalid_param]`): `"invalid parameter: filenames: list of strings required"`; `"invalid parameter: maxDim: must be >= 1"`; `"invalid parameter: format: jpeg or png required"`; `"invalid parameter: quality: int 0-100 required"`. Per-item (unprefixed, §3.2): `"invalid parameter: filenames: bare media filename required"`; `"media file was not found: <filename>"`; `"could not load image: <filename> (unsupported or corrupt format)"`; `"could not encode thumbnail as <format>: <filename>"`.

**Edge cases tests must cover** — wide image (640×160, maxDim 320) → 320×80; tall image scales to the height cap; small image (≤ maxDim both sides) returned at native size, not upscaled; `data` base64 round-trips to a decodable image of the reported dims (verify with QImage in the test); png format preserves the alpha channel; per-item error for a missing and a path-y filename while the rest of the batch succeeds; maxDim clamp at 1024; bad format/quality → hard error, nothing processed; media dir file count identical before/after; undo queue untouched.

---

## 15. `dryRun` mode on the bulk actions (spec revision 4, 2026-08-11; amended 2026-08-12, spec revision 7: bulkUpdateNoteFields `unchanged`; **amended 2026-08-18, spec revision 15: `bulkAddNotes` `wouldSuspend` and `bulkSetDueDate` gains `dryRun`**; **amended 2026-08-18, spec revision 17: the three §28 maintenance actions ship with `dryRun` from birth; slice 2 adds §29's `emptyFilteredDeck` and §30's `deleteEmptyCards`, same rule**)

An optional `dryRun: false` parameter on the three original bulk actions (`bulkAddNotes`, `bulkUpdateNoteFields`, `bulkAddTags` — param rows added to §§4.1–4.3), later `bulkReplaceInFields` (§21), from revision 15 `bulkSetDueDate` (§16.2), and from revision 17 the three §28 maintenance actions (`renameDeck`, `bulkSetFlag`, `renameTag` — dry shapes specified in §28) plus slice 2's `emptyFilteredDeck` (§29.2) and `deleteEmptyCards` (§30.2), and from revision 19 the two §32 build actions (`createFilteredDeck`, `rebuildFilteredDeck` — write actions ship `dryRun` from birth, the same rule); like `bulkSetDueDate` they all type-check `dryRun` itself as a real boolean. **No new action names**: `core.PLUS_ACTIONS` is unchanged by this section. Purpose: preview exactly what a batch would do — which entries pass validation, which get skipped and why — before committing anything.

**Shared-validation invariant (the anti-drift rule)** — the dry path is NOT a reimplementation. Each core function runs its normal code and short-circuits at its zero-write boundary, so dry and real validation are the same lines of code by construction:
- `bulk_add_notes`: the full resolution pass + duplicate precheck (both read-only) run unchanged; the early return sits between the dedup stamping and the write pass.
- `bulk_update_note_fields`: the whole per-entry validation chain (dict/id/fields-or-tags/type checks, `col.get_note` load, whole-entry field validation) runs unchanged, **including the revision-7 no-op check** (read-only comparison against the loaded note, so no-op entries land in `unchanged` identically in both modes); `dryRun` records the id and `continue`s immediately before the try/write block — before the in-memory `Note` object is ever mutated.
- `bulk_add_tags`: top-level validation, `col.get_note`, and the missing-tag computation run unchanged; the short-circuit sits after the `if not missing: continue` no-op filter, so no-op notes are omitted from both lists exactly as in real mode.
- `bulk_set_due_date` (revision 15): the `days` grammar pre-validation, the `preserveSuspended` type check and the shared `_existing_cards` precheck (dedupe + drop unknown ids, read-only) run unchanged; the short-circuit sits immediately before `add_custom_undo_entry`, so `undo_status()` is bit-identical across a dry call.

**Returns** (same envelope as the real action; the success key is renamed because its semantics change)

```json
{"wouldAdd": 2, "wouldSuspend": true, "skipped": [{"index": 1, "reason": "duplicate"}], "undoEntry": null}
```
```json
{"wouldUpdate": [1712345678901], "unchanged": [], "skipped": [{"index": 1, "reason": "note was not found: 42"}], "undoEntry": null}
```

- **`bulkAddNotes` `wouldSuspend` (revision 15, §27)** — a **bool**, not a count: the resolved `suspend` decision for this call (explicit param → config `suspendNewCards` → **`false`** — the terminal fallback is the revision-16 shipped default; this line said `true` until the revision-18 sweep). Card ids, and for a cloze notetype even the card *count*, do not exist until a real add, so any number here would be a guess. `true` predicts that the real run's `suspended` will be non-empty whenever `wouldAdd > 0`.
- `bulkAddNotes` → `wouldAdd` is a **count** (note ids do not exist until a real add). `bulkUpdateNoteFields` / `bulkAddTags` → `wouldUpdate` is the **list of note ids** that would be written (ids are known). `skipped` is identical in shape and reason strings to the real path. `undoEntry` is always `null`.
- `bulkUpdateNoteFields` dry run additionally returns `unchanged` (revision 7): the no-op ids, mirroring the real path's `unchanged` list exactly.
- **`bulkUpdateNoteFields` `diff: true` (revision 10; only with `dryRun: true`, else `[invalid_param]` — §4.2):** the dry response additionally carries `preview: [{noteId, field, before, after}]` — one entry per **changed field** (byte-comparison against the loaded note, the same read the revision-7 no-op check performs), unchanged fields omitted, **plus (revision 12) one entry per changed tag list under the reserved field name `"__tags__"`, emitted after that note's field rows with space-joined before/after values — `after` being the CANONIFIED form the write will really store, revision 14** (§4.2) — capped at `maxPreview` entries, plus `previewTruncated: bool` (more entries existed than previewed; counted past the cap). Reuses §21 `bulkReplaceInFields`' preview conventions (`before`/`after` are full raw field HTML). Without `diff` the dry response shape is byte-identical to revision 9 (no `preview`/`previewTruncated` keys). Zero-write guarantees unchanged: the preview is built inside the existing read-only pass.
- `bulkAddTags` dry run: notes already having every tag appear in **neither** list (same as real mode; its shape has no `unchanged` key).
- **Duplicate-note-id caveat on `bulkUpdateNoteFields` (revision 11)** — the dry pass compares every entry against the note's **stored pre-batch** values, never against an earlier entry's pending write, while the real run re-reads the note after each write. A batch containing the same note id more than once may therefore predict **more** updates than the real sequential run performs, and the `diff` preview may emit duplicate entries whose `before` value is stale for the later occurrence: e.g. two identical entries `{id: n, fields: {Back: "NEW"}}` dry-predict `wouldUpdate: [n, n]` (two identical preview entries) but really yield `updated: [n]`, `unchanged: [n]` (§4.2's duplicate-ids edge case). The final note state still matches the last entry in both modes. De-duplicate ids within a batch for exact dry/real parity.
- **`bulkSetDueDate` dry run (revision 15, §16.2)** returns `{wouldChange: int, wouldChangeIds: [cardId], wouldUnsuspend: [cardId], wouldUnbury: [cardId], wouldResuspend: [cardId], undoEntry: null}`. Every key is renamed for a reason stronger than convention here: the real run's `unsuspended`/`unburied` are **observations** re-read from the post-op queues, while `wouldUnsuspend`/`wouldUnbury` are a **prediction** from the pre-state that assumes anki's measured resurrection behavior still holds. `wouldResuspend` = `wouldUnsuspend` when `preserveSuspended` resolves `true`, `[]` when it resolves `false` — which is how a caller reads the active policy off a dry run. Unknown/empty id sets return the same shape with zeroes and empty lists.
- **§28 maintenance actions (revision 17)** — same shared-validation construction: each runs its full read-only validation/precheck (deck lookup + collision scan, flag precheck, tag-pair computation + the carried-by-notes gate) and short-circuits immediately before `add_custom_undo_entry`, so `undo_status()` is bit-identical across a dry call and the `[deck_not_found]`/`[duplicate]`/`[not_found]`/`[invalid_param]` refusals fire identically in both modes. Dry keys: `renameDeck` → `wouldRename` (prediction from pre-op names — the real run's `renamed` is re-read post-op), `bulkSetFlag` → `wouldUpdate`, `renameTag` → `wouldRewrite` (prediction: pairs whose tags no note carries are dropped by the real run — §28.3).
- **§§29–30 actions (revision 17, slice 2)** — same construction. `emptyFilteredDeck` runs deck resolution, the is-it-filtered check and the pre-op residency breakdown unchanged, short-circuiting immediately before `add_custom_undo_entry`: dry keys `wouldReturn` (count) + `homeDecks` (the same pre-op observation the real run reports). `deleteEmptyCards` runs the full `col.get_empty_cards()` read + the target/protection/skip computation unchanged and short-circuits the same way: dry key `wouldDelete` (the exact card ids — ids exist before deletion, unlike `bulkAddNotes`' counts), with `notesAffected`/`protected`/`skipped` identical to the real shape. Both leave `undo_status()` bit-identical on the dry path, and both fire their `[deck_not_found]`/`[validation_error]`/`[invalid_param]` refusals identically in both modes.
- Hard parameter errors (`"invalid parameter: notes: list required"` etc.) raise exactly as in real mode — dryRun only suppresses writes, not validation errors. Revision 15: this covers the new suspension params too (`suspend` / `preserveSuspended` non-boolean → `[invalid_param]` under `dryRun: true`), and a bad `days` string under `dryRun: true` still leaves `undo_status()` bit-identical. **Revision-15 fix pass: `dryRun` is itself type-checked on `bulkSetDueDate`** (`"invalid parameter: dryRun: boolean required"`, raised beside the `preserveSuspended` check and before any write), matching `bulkReplaceInFields`' flag loop. Rationale, and it is the house bug class: a truthy non-boolean — `dryRun: "false"` is the mistake an LLM caller actually makes — would otherwise turn a requested real reschedule into a zero-write prediction and still answer `200`, while a falsy non-boolean (`[]`, `{}`) would write when a preview was asked for. The older `dryRun` surfaces (`bulkAddNotes`, `bulkUpdateNoteFields`, `bulkAddTags`) still coerce and are unchanged in this revision.

**Zero-mutation guarantees (provable)** — under `dryRun: true`: no `col.add_note` / `col.update_note` call; no `add_custom_undo_entry` (the lazy `target` is never reached), so `col.undo_status()` is bit-identical before/after; no media write — the `bulkAddNotes` wrapper **skips `_plusEmbedNoteMedia`** because upstream media embedding stores files (consequence, documented limitation: notes carrying `audio`/`video`/`picture` keys are validated on their fields **as submitted**, without media-filename substitution; the real run's substituted fields could in principle differ for first-field emptiness/duplicate checks). `atomic` is accepted but irrelevant (no write-time hard-error path can fire).

**What a dry run cannot predict** — write-time hard errors (the `atomic=false` skipped entries produced by an exception inside the write block). A dry-run "would" verdict is a validation verdict, not a transaction guarantee.

**Edge cases tests must cover (revision 15 additions first)** — `bulkAddNotes` dry run reports `wouldSuspend` on every return path incl. the empty batch, and `bool(real["suspended"]) == dry["wouldSuspend"]`; `bulkSetDueDate` dry run on a set containing a suspended card, a manually buried card and an untouched card predicts each list exactly, changes no `cards` row and leaves `undo_status()` bit-identical, and the following real call matches the prediction key for key; the same dry call with `preserveSuspended: false` predicts `wouldResuspend: []`. Original: mixed batch (valid + duplicate + unknown model + empty first field) → `wouldAdd` counts only the valid ones, `skipped` reasons identical to a real run on the same batch; note count / field values / tags unchanged in the DB after each dry call; `undo_status()` unchanged (no entry created, not even an empty one); dry-then-real sequence: the real run's `added`/`updated` lengths match the dry prediction (for batches without duplicate note ids — see the duplicate-note-id caveat above); `bulkAddTags` dry run omits already-tagged notes from both lists; empty `notes` list → `{wouldAdd: 0, wouldSuspend: <resolved bool>, skipped: [], undoEntry: null}` (revision 15: `wouldSuspend` is on the empty path too — see the revision-15 clause above); hard param errors still raise under dryRun, **including a non-boolean `dryRun` itself on `bulkSetDueDate`** (revision-15 fix pass).

## 16. `bulkSuspend` & `bulkSetDueDate` (spec revision 4, 2026-08-11; amended 2026-08-12, spec revision 12: `changedIds` on both, resurrection disclosure on `bulkSetDueDate`; **amended 2026-08-18, spec revision 15: `preserveSuspended` + `dryRun` on `bulkSetDueDate` — see §27**)

Two scheduler bulk actions, bringing the action count to sixteen. `core.PLUS_ACTIONS` remains the single source of truth for the `plusInfo` action list. Both follow the §3.3 undo conventions with new entry names `"AnkiConnect Plus: Bulk Suspend"` / `"AnkiConnect Plus: Bulk Due Date"`, and both share an id-precheck helper: input `cardIds` are **deduplicated (first occurrence wins) and filtered to existing cards** via `col.get_card` (read-only) before any op — unknown ids are silently dropped, never an error, and backend behavior on unknown ids never enters the contract (Deviation #8).

### 16.1 `bulkSuspend`

**Preserves (§31.1)** — only `queue` changes: due dates, intervals, ease, flags, tags, fields, note ids and deck assignment survive — **including filtered-deck residency** (probe-verified: suspending a card visiting a filtered deck leaves it there). NOT preserved: bury state — suspending a buried card replaces burial, and unsuspend restores every negative queue (Deviation #8).

**Params**

| name | type | default | notes |
|---|---|---|---|
| `cardIds` | [int] | required | Deduplicated; unknown ids dropped. |
| `suspend` | bool | `true` | `true`: suspend. `false`: unsuspend (backend restore op — **also unburies** buried cards; documented backend behavior). |

**Returns**

```json
{"changed": 2, "changedIds": [1712345678901, 1712345678902], "undoEntry": "AnkiConnect Plus: Bulk Suspend"}
```
- `changedIds` (revision 12, additive): the ids actually passed to the op — deduplicated, unknown ids dropped, precheck order — which IS the set the op changes (Deviation #8). `[]` on every no-op path. Rationale (round-3 field feedback): the bulk family reported ids inconsistently — `bulkAddTags`/`bulkUpdateNoteFields` return id lists, the scheduler pair returned a bare count, so a caller could not tell WHICH of its ids were written. In the suspend direction `changed` remains backend-authoritative, so a (never-observed) backend/precheck disagreement would surface as `changed != len(changedIds)` rather than being hidden.
- `changed`: cards whose state actually changed. Suspend direction: backend-authoritative (`OpChangesWithCount.count`); already-suspended cards do not count, buried cards do (they become suspended). Unsuspend direction: precheck count of cards whose queue was negative (suspended −1, sibling-buried −2, manually buried −3) — exactly the set the restore op changes (Deviation #8).
- `changed: 0` → `changedIds: []`, `undoEntry: null` and the undo stack is untouched (a no-op batch is skipped before any op; a backend-reported 0 pops the empty custom entry, Deviation #7 precedent).

**Anki API calls** — `col.get_card(cid)` precheck (`NotFoundError` → drop); `col.sched.suspend_cards(ids) -> OpChangesWithCount` (`SP/anki/scheduler/base.py:153-156`); `col.sched.unsuspend_cards(ids) -> OpChanges` (`base.py:150-151`, backend `restore_buried_and_suspended_cards`); undo per §3.3: `add_custom_undo_entry` **before** the op (the op must merge into it), `merge_undo_entries` after. Only cards that would change are passed to the op.

**Error cases** (codes per §25) — `[invalid_param]` `"invalid parameter: cardIds: ints required"`; `[invalid_param]` `"invalid parameter: suspend: boolean required"`; unexpected op failure → `[batch_reverted]` `"bulkSuspend failed (batch reverted): <err>"` (custom entry reverted).

**Edge cases tests must cover** — suspend 2 new cards (+1 bogus id in the list) → `changed: 2` with `changedIds` naming exactly those two, both queues −1, `undo_status().undo` = the entry name, single `col.undo()` restores both queues and pops the entry; suspending an already-suspended card → `changed: 0`, `undoEntry: null`, undo stack unchanged; unsuspend the suspended pair → `changed: 2`, queues restored; unsuspend with nothing suspended → `changed: 0`, no op; duplicate ids counted once; empty `cardIds` → `{changed: 0, undoEntry: null}`.

### 16.2 `bulkSetDueDate`

**Preserves (§31.1)** — flags, fields, tags, note ids, GUIDs, ease factor. NOT preserved (rescheduling is the job): due/queue/type on every targeted card (`!` also rewrites interval; new cards become review cards), suspension/burial per §27, **and filtered-deck residency: a card sitting in a filtered deck is sent back to its home deck, `odid` consumed (probe-verified on 25.09.4 — revision 18 discloses it)**.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `cardIds` | [int] | required | Deduplicated; unknown ids dropped. |
| `days` | str | required | Backend grammar: `"0"` = due today, `"5"` = in 5 days, `"1-7"` = uniform-random per card in the range, `"3!"` = also force interval to 3 days (probe-verified). Bad strings raise. |
| `preserveSuspended` | bool\|null | `null` → config `preserveSuspendedOnReschedule` → **`true`** | **Revision 15, §27 — deliberate deviation from Anki.** `true`: re-suspend the cards this call revived, inside the SAME undo entry, and report them in `resuspended`. `null` (omitted) reads config key `preserveSuspendedOnReschedule`, which **ships `true`**; an explicit `true`/`false` always wins over config. Non-boolean → `[invalid_param]`, raised before any undo entry exists. Buried cards are **never** re-buried. |
| `dryRun` | bool | `false` | Revision 15: `true` predicts `wouldChange`/`wouldChangeIds`/`wouldUnsuspend`/`wouldUnbury`/`wouldResuspend` and writes nothing — see §15. |

**Returns**

```json
{"changed": 3, "changedIds": [1712345678901, 1712345678902, 1712345678903],
 "unsuspended": [1712345678901], "unburied": [], "resuspended": [1712345678901],
 "undoEntry": "AnkiConnect Plus: Bulk Due Date"}
```
- `changed` = count of existing (deduplicated) cards passed to the op — `set_due_date` applies to every one regardless of current state, turning new cards into review cards (probe: new 0/0 → `type=2 queue=2 ivl=1`) (Deviation #8). `changedIds` (revision 12) lists exactly those ids. No existing cards → `{changed: 0, changedIds: [], unsuspended: [], unburied: [], resuspended: [], undoEntry: null}`, no op.
- **⚠ THIS ACTION RESURRECTS SUSPENDED AND BURIED CARDS (disclosure, revision 12 — round-3 field feedback).** Anki's own `set_due_date` turns every targeted card into a review card, which silently clears suspension (queue `-1`) and burial (`-2`/`-3`). Measured: 5 cards suspended (queues all `-1`) → `bulkSetDueDate days: "5"` → queues all `2`, with the pre-revision-12 response `{"changed": 5}` giving no hint whatsoever. This is Anki's semantics, not a bug in this add-on — but the realistic disaster is real: suspend your leeches, later reschedule a deck-wide selection that happens to include them, silently bring them all back. The response therefore always carries **`unsuspended`** (ids whose queue was `-1` before the call and non-negative after) and **`unburied`** (same for `-2`/`-3`; Deviation #11a — burial is restored too, so a disclosure naming only suspension would be a half-truth), both `[]` when nothing was revived. Detection is free: the queue is already in hand from the shared precheck, and the post-state is re-read ONLY for cards that were negative-queued.
- **`resuspended` — the CONTROL, not just the disclosure (revision 15, §27).** Always present. With `preserveSuspended` (default `true`) the cards reported in `unsuspended` are passed straight back to `col.sched.suspend_cards`, and `col.merge_undo_entries(target)` is called a **second time on the same target**, so the reschedule and the re-suspension are ONE undo entry — a single Ctrl+Z restores the exact pre-call state (probe-verified: `(due, ivl, queue, type)` byte-identical afterwards), where two entries would leave the cards rescheduled but live. `resuspended` is re-read from the post-op queues, so it reports the cards that ARE suspended now, not the ids that were asked for. Precise semantics, because they are easy to misread:
  - `unsuspended` stays a **during-the-call** fact — "anki revived these" — even when they were immediately put back. It is not a final state.
  - **Cards left in review = `unsuspended` − `resuspended`.** Normally that is empty with the default on, and equals `unsuspended` with it off.
  - `resuspended ⊆ unsuspended` by construction: a card that was suspended before and stayed suspended never left, and claiming to have re-suspended it would be a lie.
  - **Buried cards are deliberately NOT re-buried** (Deviation #13b) — anki's unbury-on-reschedule is desirable and only suspension was in scope; `unburied` still discloses them. This asymmetry is intentional.
  - The pair is self-describing: a non-empty `unsuspended` with `resuspended: []` means the policy was off for this call, so no separate policy echo is emitted. When `unsuspended` is `[]` the policy had nothing to act on and the distinction does not matter.
  - Re-suspend failure → the whole batch is reverted and `[batch_reverted]` `"bulkSetDueDate failed (batch reverted): re-suspend: <err>"` is raised (never a partially applied policy).
- **It always writes — no no-op suppression (documented, revision 12).** Unlike `bulkSuspend`/`bulkAddTags`/`bulkUpdateNoteFields`, a byte-identical repeat still writes and still creates an undo entry (measured: identical `due 2358 / ivl 3` before and after, `changed: 5`, `undo_status().last_step` 33 → 34). This is deliberate: a range spec like `"1-7"` is nondeterministic per card by design (the backend fuzzes), so an exact-parity precheck would be sound only for the single-day/`!` forms and would make the action's behavior depend on the shape of `days`. Callers wanting a no-write guarantee must compare state themselves (§26 `undoStatus`'s `lastStep` proves whether an entry appeared).

**Anki API calls** — `col.get_card` precheck; `col.sched.set_due_date(card_ids, days) -> OpChanges` (`SP/anki/scheduler/base.py:205-227`; revision 15 adds `col.sched.suspend_cards(unsuspended) -> OpChangesWithCount` + a second `col.merge_undo_entries(target)` when `preserveSuspended` is on, and a `col.get_card` re-read of just those ids to build `resuspended`; the optional `config_key` is not used — no config default is read or written); undo per §3.3 (entry created before the op, merged after). The `days` grammar is pre-validated in core (`re.fullmatch(r'[0-9]+(?:-[0-9]+)?!?', days)` — ASCII digits only, matching what the backend actually accepts) **before** `add_custom_undo_entry`, so a bad string raises `"invalid parameter: days: <bad string>"` with the undo stack genuinely untouched (popping an empty custom entry via `col.undo()` would push a phantom Redo item). The `anki.errors.InvalidInput` handler (message = the bad string; empty custom entry popped, error re-raised house-style) remains as a backstop for grammar drift only.

**Error cases** (codes per §25) — `[invalid_param]` `"invalid parameter: cardIds: ints required"`; `[invalid_param]` `"invalid parameter: days: string like \"0\" or \"1-7\" required"` (non-string or empty); `[invalid_param]` `"invalid parameter: days: <bad string>"` (grammar rejected by core's pre-validation — same message shape as the backend's InvalidInput, whose message is the echoed bad string; undo stack left untouched, verified bit-identical `undo_status()`); unexpected op failure → `[batch_reverted]` `"bulkSetDueDate failed (batch reverted): <err>"`.

**Edge cases tests must cover** — `"0"` on a new card → due today, `type=2 queue=2`, single `col.undo()` restores the new state and pops the entry; `"1-7"` on several cards → each due within [1,7] days; `"3!"` → due 3 and `ivl` 3; `"bogus"` → `invalid parameter: days:` error AND `undo_status()` unchanged (no empty entry left); only-bogus ids → the all-empty no-op shape; duplicate ids counted once. Revision 12: a suspended card and a manually buried card in the same call come back in `unsuspended` / `unburied` respectively with their queues restored to `2` (and the assertion doubles as an alarm if a future Anki stops resurrecting); an untouched card contributes to neither list; `changedIds` matches the deduplicated existing-card set; a byte-identical repeat still advances `undo_status().last_step`. **Revision 15:** with the default on, three suspended cards reschedule to `"5!"` → `unsuspended == resuspended == the three ids`, queues back at `-1`, and `due`/`ivl`/`type` show the reschedule really landed; ONE `col.undo()` restores `(type, queue, due, ivl)` exactly; `preserveSuspended: false` → `resuspended: []` and queues `2`; a manually buried card in the same call appears in `unburied`, NOT in `resuspended`, and ends at queue `2`; `preserveSuspended` non-boolean → `[invalid_param]` with the undo stack untouched; the `dryRun` cases in §15.

## 17. `exportDeckApkg` (spec revision 4, 2026-08-11; **amended 2026-08-18, spec revision 17 slice 2: FAIL-CLOSED on filtered-deck omission, `allowFilteredOmission`, always-present `warnings` — the revision's one deliberate behavior change; rationale in §29.3 and §0 Deviation #14**)

Export one deck (including its subdecks) to an `.apkg` file on disk, bringing the action count to seventeen. `core.PLUS_ACTIONS` remains the single source of truth for the `plusInfo` action list. Runs on the **open** collection (no close/reopen — that is only needed for full `.colpkg` exports); media is written synchronously into the zip during the call.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `deckName` | str | required | Must exist (`col.decks.id_for_name`); export covers the deck **and all its subdecks** (backend `DeckIdLimit` semantics). |
| `outPath` | str | `null` | Target file path (`~` expanded). Default: `~/Downloads/<sanitized-deck>-<YYYY-MM-DD>.apkg` (`core.EXPORT_DEFAULT_DIR`). The parent directory must already exist. |
| `includeScheduling` | bool | `true` | Maps to proto `with_scheduling`. `false` exports notes/cards as new. |
| `includeMedia` | bool | `true` | Maps to proto `with_media`. `false` still writes an (empty) `media` zip member. |
| `allowFilteredOmission` | bool | `false` | **Revision 17 (slice 2; second flagged set in the fix pass).** `false`: refuse with `[cards_in_filtered_decks]` whenever any card whose HOME deck (odid-aware) is inside the export scope currently sits in a filtered deck — those cards would be silently omitted (whole notes vanish when every card is in out-of-scope filters) or shipped scheduling-reset — OR whenever a filtered deck nested inside the scope holds cards homed OUTSIDE it, which would ship those foreign notes scheduling-reset into the filter recreated as a regular deck. `true`: export anyway; the damage is itemized in `warnings`. Per-call only, deliberately not config-backed (§0 Deviation #14). |

**Returns**

```json
{"path": "~/Downloads/HA2-PI-7-2026-08-11.apkg", "sizeBytes": 152344, "notesExported": 214, "warnings": []}
```
- `path`: the file actually written (after collision suffixing). `sizeBytes`: `os.path.getsize` of it. `notesExported`: the backend's return value (number of notes in the package) — harmless extension beyond the locked `{path, sizeBytes}` shape, kept because the count is authoritative and free.
- `warnings` (revision 17, additive, **always present**): `[]` on a clean export. When `allowFilteredOmission: true` let a flagged export proceed, up to two entries (fix pass; each present only when its set is non-empty, in this order): `{"code": "cards_in_filtered_decks", "count": <in-scope-home cards sitting in filtered decks>, "decks": {"<filtered deck name>": <count>, ...}, "notesOmitted": <notes whose EVERY card is in an out-of-scope filtered deck — they vanish from the package entirely>}` (the flagged cards NOT belonging to omitted notes do ship, but scheduling-reset — §29.3), and `{"code": "foreign_cards_in_scope_filters", "count": <cards homed outside the scope sitting in filtered decks nested inside it>, "decks": {"<filtered deck name>": <count>, ...}}` (those foreign notes SHIP, scheduling-reset, with the filter recreated as a regular deck — nothing vanishes, so there is no `notesOmitted`). The array form is deliberate: future warnings extend it without a key change, and a caller branches on content, never on key presence.

**Filename semantics (exact)** — sanitized stem: `re.sub(r'[^\w.-]+', '-', deckName).strip('-.')`, falling back to `"deck"` when nothing survives (`\w` is unicode-aware: unicode letters/digits/underscore, dot, dash survive; `::`, spaces, and runs of other characters collapse to single dashes — `"HA2::PI 7"` → `"HA2-PI-7"`). **Never overwrite**: while the target exists, `-2`, `-3`, … is appended before the extension (`report.apkg` → `report-2.apkg`). The exists-check→write sequence is race-free per §3.1 (handlers serialized on the main thread).

**Anki API calls** — `col.decks.id_for_name(deckName)`; `col.export_anki_package(out_path=..., options=..., limit=anki.collection.DeckIdLimit(did)) -> int` (number of notes exported; `SP/anki/collection.py:367-374`, kw-only); `options = anki.collection.ExportAnkiPackageOptions(with_scheduling=includeScheduling, with_deck_configs=False, with_media=includeMedia, legacy=False)` (proto fields per `SP/anki/_backend/import_export_pb2.pyi:250-268`). Fixed choices, documented: `with_deck_configs=False` (deck presets are never exported — matches Anki's own dialog default and keeps imports from mutating the receiving collection's presets); `legacy=False` (modern zstd package, Anki 2.1.50+; zip members `meta`/`collection.anki21b`/`collection.anki2`/`media`+numbered files).

**Order of operations** — all validation before any filesystem write: param types, deck lookup, **then (revision 17) the fail-closed filtered-deck check — before the output path is even resolved, so a refused export leaves zero filesystem trace and cannot burn a collision suffix** — then output-directory existence; then collision suffixing; then the export call. The export itself is read-only with respect to the collection: no undo entry is created and `undo_status()` is unchanged (tests assert this).

**Error cases** (codes per §25) — `[invalid_param]` `"invalid parameter: deckName: string required"` (non-string or empty); `[deck_not_found]` `"deck was not found: <name>"`; `[invalid_param]` `"invalid parameter: outPath: string required"` (non-string or empty string); `[invalid_param]` `"invalid parameter: outPath: is a directory: <path>"` (outPath resolves to an existing directory, or ends in a path separator — outPath must be a file path; without this guard the collision loop would write a surprise sibling like `<dir>-2`); `[invalid_param]` `"invalid parameter: includeScheduling: boolean required"`; `[invalid_param]` `"invalid parameter: includeMedia: boolean required"`; `[not_found]` `"output directory was not found: <dir>"`; `[invalid_param]` `"invalid parameter: allowFilteredOmission: boolean required"`; **`[cards_in_filtered_decks]`** `"<sentence per flagged set>. Empty the filtered decks first (emptyFilteredDeck) or pass allowFilteredOmission=true to export anyway"` — the home-side sentence reads `"<N> cards whose home deck is inside \"<stored deck name>\" are sitting in filtered decks (<name: count, ...>); a deck-scoped export silently omits notes whose every card is in a filtered deck (<M> such notes here) and ships the other filtered cards scheduling-reset"`, the foreign-side sentence (fix pass) reads `"<N> cards homed OUTSIDE \"<stored deck name>\" are sitting in filtered decks nested inside it (<name: count, ...>); the export would ship those foreign notes scheduling-reset, with their filtered decks recreated as regular decks"`, and both appear `'. '`-joined when both sets are non-empty (revision 17 — raised BEFORE any filesystem work; the counts/names in the message match what `warnings` would carry); backend export failures surface through the envelope as `[internal]`.

**Edge cases tests must cover** — export of a small deck with a media-bearing note → file exists, `sizeBytes` matches on-disk size, zip members include `media`, `notesExported` correct; subdeck note included when exporting the parent; repeat export to the same path → `-2` (then `-3`) suffix, first file untouched; `includeMedia: false` → smaller file, media member empty; `includeScheduling: false` accepted; unknown deck / bad outPath dir → error with no file written; sanitized default filename for a `::`-nested deck name; undo queue untouched. **Revision-17 additions**: a deck with one card pulled into a filtered deck → default export refuses `[cards_in_filtered_decks]`, NO file written, no collision suffix burned, undo untouched; same call with `allowFilteredOmission: true` → file written, `warnings` carries exactly `{code, count, decks, notesOmitted}` and the imported package really lacks the omitted notes; after `emptyFilteredDeck` the identical default call succeeds with `warnings: []`; a clean deck always returns `warnings: []`; exporting a FILTERED deck by name is out of the guard's scope by construction (no card's odid names a filtered deck, and the export root is excluded from the foreign-set filter list — §29.3) and really proceeds. **Fix-pass additions**: a filtered deck NESTED inside the exported subtree holding a card homed OUTSIDE it → default export refuses `[cards_in_filtered_decks]` naming the foreign count + filter, no file written; same call with `allowFilteredOmission: true` → `warnings` carries `{code: "foreign_cards_in_scope_filters", count, decks}` and the imported package really contains the foreign note (the disclosed damage); after `emptyFilteredDeck` on the nested filter the default call succeeds clean.

## 18. `syncStatus` & `syncNow` (spec revision 5, 2026-08-11)

AnkiWeb sync, bringing the action count to nineteen. `core.PLUS_ACTIONS` remains the single source of truth for the `plusInfo` action list. Locked design: **normal sync only, asynchronous job + polling, zero dialogs**. A required full sync is always REFUSED (surfaced as job error `full_sync_required`); `full_upload_or_download` is never called, and the aqt GUI flows (`mw.on_sync_button_clicked`, `mw._sync_collection_and_media`, `aqt.sync.sync_collection`) are never routed through — they open modal dialogs that hang unattended. Stock AnkiConnect's `sync` action (`addons21/2055492159/__init__.py:502-511`) blocks the main thread for the whole network round trip and then launches the GUI sync flow a second time via `mw.onSync()`; deliberately not copied.

**Job model** — one job slot per add-on instance, created lazily on the mixin (`PlusMixin` has no `__init__`; `getattr` guard): `{state: "idle"|"syncing"|"media_syncing"|"done"|"error", startedMs, result, error}`. The dict is only ever mutated on the Qt **main thread**: HTTP handlers run there (§3.1) and `mw.taskman.run_in_background`'s `on_done` is marshalled there (`SP/aqt/taskman.py:86-88`) — no locking needed, ever. `result` = `{serverMessage, hostNumber}` once the collection phase succeeds (`serverMessage` is returned verbatim, never shown in a dialog); `error` = `{code, message}`. `media_syncing` → `done`/`error` is driven by a **plus-owned media watcher**, not by polling probes from `syncStatus`/`syncNow`: `col.media_sync_status()` `take()`s and `join()`s the *finished* backend media task (rslib `backend/sync.rs`), so a media-sync failure raises **exactly once**, to whichever caller observes it first (probe-verified: first call raises, every later call returns `active=False` cleanly). `_plusSyncDone` therefore starts its own watcher via `mw.taskman.run_in_background(..., uses_collection=False)` that mirrors aqt's monitor loop (`SP/aqt/mediasync.py:57-65`: poll `media_sync_status()` every 0.25 s until inactive) and lets the failure raise into its future; `on_done` (main thread) sets `state=done`, or `state=error, code=media_sync_failed`. `mw.media_syncer.start_monitoring()` is deliberately **not** called: its monitor thread would consume the single raise before plus could (making `media_sync_failed` unreachable) and pops a non-modal `show_info` dialog on failure (`SP/aqt/mediasync.py:89-96`) — zero dialogs. `gui_hooks.media_sync_did_start_or_stop(True/False)` is fired around the watch so the toolbar sync icon still tracks. If `mw.col` is None when the watch would start, the job goes straight to `state=error, code=media_sync_failed` — an unverified media sync is never reported `done`. **Liveness of the `syncing` state (revision 14, round-3 review).** The §25.2 guard refuses 23 actions with a code documented RETRYABLE for exactly as long as the job reads `syncing`, so leaving that state must be guaranteed, not merely likely. It was neither: `_plusSyncDone` ran `self.window()`, `mw.col._load_scheduler()` and two `mw.pm.*` writes — every one of which can raise when the profile closes mid-sync — **before** any `job['state']` assignment, with no `try/finally`; a raise inside a taskman `on_done` callback is swallowed, stranding the job at `syncing` until Anki restarted. Three layers now prevent that: (a) `_plusSyncDoneBody` assigns the terminal state BEFORE any statement that can fail (the bookkeeping moved after it); (b) `_plusSyncDone` wraps the body in `try/except/finally` — an unexpected escape becomes `state=error, code=error`, the `finally` clause asserts the state is no longer `syncing` whatever happened, and `_plusSyncFinishGui` now runs on every path instead of being skipped by the raise; (c) a job still `syncing` more than `core.SYNC_JOB_STALE_MS` (1 h) after `startedMs` — or with no `startedMs` at all — is REAPED into `state=error, code=error` by `plus._reap_stale_sync_job`, which the guard, `syncNow` and `syncStatus` all call, so the documented recovery loop (poll `syncStatus` until the state leaves `syncing`) always terminates and all three agree on the state. Reaping rather than merely ignoring is the point: a guard that let actions through while `syncStatus` still reported `syncing` would just move the deadlock into the caller's poll loop. **The job error-code vocabulary is unchanged** — the reaper reuses the generic `error` code and names the staleness in the message. The ceiling is deliberately generous: a real sync still running when it passes reverts to pre-guard behavior (the next guarded action blocks on the collection mutex), which is bad but recoverable, unlike a permanent refusal.

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

### 18.2 `syncStatus` (amended 2026-08-12, spec revision 12: `serverChecked` + honest `localOnly` verdict)

Read-only status probe. Never starts a sync, never clears auth (Deviation #9a), never opens dialogs.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `localOnly` | bool | `false` | `true`: no network I/O at all — `required` computed from local dirtiness only. |
| `timeoutSecs` | int | `8` | 1–300. Network timeout for the status round-trip via `bounded_sync_auth` (default `pm.network_timeout()` is 60 s — too long for a poll on the main thread). |

**Returns**

```json
{"loggedIn": true, "job": {"state": "done", "startedMs": 1754924000000, "result": {"serverMessage": "", "hostNumber": 0}, "error": null},
 "mediaSyncing": false, "mediaSecondsSinceLastSync": 42, "lastSyncMs": 1754924001234, "modMs": 1754924001234, "required": "no_changes", "serverChecked": true}
```

- `job`: a copy of the job dict (the plus media watcher keeps it current on its own — see the job model).
- `mediaSyncing` / `mediaSecondsSinceLastSync`: `mw.media_syncer.is_syncing()` / `.seconds_since_last_sync()` (`SP/aqt/mediasync.py:105,131`; the latter is 0 while syncing). These track only **aqt-owned** media syncs (periodic 15-min / auto-sync): a plus-initiated media phase never goes through `MediaSyncer`, is visible as `job.state == "media_syncing"` instead, and does not advance `mediaSecondsSinceLastSync`.
- `lastSyncMs` / `modMs`: from `local_sync_dirty` (`ls` = last-sync ms epoch, `mod` = collection mod-time ms). `null` when `mw.col` is None **or** the job is in state `syncing` (Deviation #9b — the backend holds the collection lock; no col/db access is attempted at all in that state, and `required` is likewise `null`).
- `required`: `not_logged_in` | `no_changes` | `normal_sync` | `full_sync_required` | `offline` | `auth_failed` | `error` | (localOnly) `normal_sync`/`unknown_no_network` | `null` (job `syncing`). `not_logged_in` takes precedence over collection unavailability: logged out with `mw.col` None still reports `not_logged_in` (the more informative answer), never `null`. Network path: `col.sync_status(bounded_auth) -> SyncStatusResponse` (`SP/anki/collection.py:1152`; backend answers locally with no network when the collection is dirty, serves a 300 s cache when clean, else one small round-trip); `new_endpoint` persisted via `pm.set_current_sync_url` (mirrors `SP/aqt/sync.py:57-58`). Exceptions map through `classify_sync_error` with `aborted` coerced to `error` (Deviation #9c). `localOnly` path (revision 12): `full_sync_required` if the schema changed (`scm > ls`), else `normal_sync` if dirty, else `unknown_no_network` (a clean local state cannot rule out server-side changes without the network) — revisions 5–11 flattened every dirty state to `normal_sync`, under-reporting a schema-changed collection whose own backend verdict is `full_sync_required` (Deviation #11d). Logged in + `mw.col` None → `error`.
- **`serverChecked` (revision 12, round-3 field feedback)**: `true` **only** when this call actually completed a network status round-trip; `false` always means "not verified by this call" — never "the server said no". Rationale (measured in real use): `localOnly` true vs false were timing-indistinguishable (26.3/17.2/21.9 ms vs 24.9/24.6/23.7 ms, against 387.6 ms for one real TLS round-trip to sync.ankiweb.net) and returned byte-identical 258 B responses, so a caller leaning on the verified-sync contract could not tell a server answer from a local inference. The `SyncStatusResponse` proto carries no round-trip flag, but the short-circuit rule is exactly decidable locally and was proved against an unreachable endpoint (`http://127.0.0.1:1/`, nothing left the machine): rslib answers locally **iff the collection is dirty** (dirty → verdict in 0.018 ms, no socket; clean → NetworkError after attempting one; `scm > ls` and a fresh collection → local `full_sync_required`). Implementation: `serverChecked = not local['dirty']` on the successful network path only — the same `core.local_sync_dirty` predicate the function already computed one line earlier. It is `false` on every other path (job `syncing`, `localOnly`, not logged in, no collection, probe exception), and it is never guessed `true`.

**Verified-synced contract (for clients)** — the collection is known synced iff `job.state == "done" AND required == "no_changes" AND mediaSyncing == false`. Anything less (job `error`, `required` `normal_sync`/`null`, media still running) means "not verified". Revision 12: `required == "no_changes"` already implies `serverChecked == true` (a dirty collection can never report `no_changes`), so the contract is unchanged — `serverChecked` is what lets a caller audit the *other* verdicts.

**Error cases** (codes per §25) — `[invalid_param]` `"invalid parameter: localOnly: boolean required"`; `[invalid_param]` `"invalid parameter: timeoutSecs: int 1-300 required"`. Everything else is expressed in the return value, never raised (the job `error.code` and `required`/`reason` vocabularies are unprefixed and unchanged — §25).

**Edge cases tests must cover (headless, ZERO network)** — `local_sync_dirty` on a fresh scratch collection (`mod > ls` after a write → dirty; `lastSyncMs`/`modMs` ints); `classify_sync_error` over synthetic `SyncError(kind=AUTH)` / `SyncError(kind=OTHER)` / `NetworkError` / `Interrupted` / plain `Exception` → exact code strings; `bounded_sync_auth` clamps `io_timeout_secs`, preserves `hkey`, maps empty-string endpoint to unset; enum maps cover proto values 0–2 / 0–4 and match the installed `sync_pb2` constants; both actions present in `PLUS_ACTIONS`; headless `core.py` import still keeps `aqt`/`PyQt6` out of `sys.modules`. Documented headless edge case (live-Anki behavior, not headless-testable): logged out + `mw.col` None → `required` `not_logged_in` (precedence rule above). The network paths (`sync_status`/`sync_collection` round-trips) are exercised only manually against a live logged-in Anki — never from the test suite. Revision 12 (headless, still zero network — the backend probe is stubbed on a fake `mw`): dirty collection → `serverChecked: false`; clean collection → `serverChecked: true`; `localOnly: true` → `serverChecked: false` and `unknown_no_network` when clean, `full_sync_required` when `scm > ls`, `normal_sync` when only `mod > ls`.

## 19. AnkiHub suggestion bridge (spec revision 6, 2026-08-11)

`ankihubStatus`, `ankihubSuggestNoteUpdate`, `ankihubSuggestNewNote` — bringing the action count to twenty-two. The bridge REUSES the installed AnkiHub add-on (package `1322529746`, tested version **2026-08-10.1**, AnkiHub API version 24.0) as a library: its own `main.suggestions` functions compute the field/tag diff against the local AnkiHub DB, rename+upload media, and submit — this codebase re-implements none of that. The add-on directory is read-only to us; `core.py` gains only pure helpers and never imports the add-on (nor aqt).

**Etiquette stance (locked)** — deliberately NO bulk suggestion action. The add-on's `suggest_notes_in_bulk` exists and is intentionally not wrapped: unattended mass suggestions to shared decks (especially the AnKing deck, where Matt is a plain subscriber) would be poor citizenship toward maintainers. One reviewed suggestion per call; batching is the caller's explicit, visible loop.

**Module access (plus.py)** — the folder name `1322529746` is not a valid identifier, so modules are reached with `importlib.import_module`. Guards, in order: package present in `mw.addonManager.allAddons()` else `ANKIHUB_ADDON_MISSING`; `isEnabled('1322529746')` else `ANKIHUB_ADDON_DISABLED`; **`'1322529746' in sys.modules` else `ANKIHUB_ADDON_DISABLED` ("restart Anki")** — when Anki itself loaded the add-on the import is a cached no-op, and when it didn't (enabled without restart), importing it ourselves would run its `entry_point` (real AnkiHub sync machinery), so it is never attempted. Modules used: `.main.suggestions`, `.ankihub_client.models`, `.ankihub_client.ankihub_client`, `.settings`, `.db`, and — on the `gui=True` path only (the two suggest actions and `ankihubStatus`) — `.gui.media_sync`. **The §33 staging action imports with `gui=False`: NO module from the add-on's `gui/` package is ever imported on its path** (revision 20 trim; its boundary is "everything local"). The stored token is NEVER read or logged — only `settings.config.is_logged_in()`.

**Feature detection (before every call)** — `inspect.signature` over each function the bridge passes kwargs to (`suggest_note_update`, `suggest_new_note`, `resubmit_new_note_as_change_suggestion`, `has_empty_first_field`, `parse_duplicate_anki_id_error`): its parameters must be a superset of `core.ANKIHUB_REQUIRED_SIGNATURES[name]`. Additionally `SuggestionType` must still carry all nine wire values (the enum values are `(wire, label)` tuples; wire = `value[0]`), `ChangeSuggestionResult` all four members, and the `media_sync`/`config`/`ankihub_db` singletons the attributes used — for `config` that is `is_logged_in` (callable) **and** `anking_deck_id` (attribute presence via `hasattr`; `None` is a legitimate value, but absence would make the unguarded AnKing `SOURCE_REQUIRED` gate in `ankihubSuggestNoteUpdate` raise a raw `AttributeError`). Any drift (or import/attribute error) → `INCOMPATIBLE_ANKIHUB_ADDON` naming installed vs tested version and the specific problems. **Revision 20 (§33) addition to the same detector**: `db.ankihub_db.ankihub_dids_for_anki_nids` (callable) — checked before every AnkiHub-family call and reflected in `ankihubStatus.compatible`, same code either way. The `media_sync` singleton check runs only when the `gui=True` import path brought that module in; the §33 staging action (`gui=False`) never imports it.

**Threading** — both suggest actions run synchronously on the Qt main thread, the same context as the add-on's own single-note dialog flow (`gui/suggestion_dialog.py:339-391`); worst case UI freeze = the AnkiHub client's 10 s connect + 20 s read timeouts.

**Media side effect (documented)** — when the note references newly-added media, the add-on content-hash **renames those files across the whole collection** (raw SQL inside the add-on, not undoable) before uploading them to AnkiHub S3 in the background via `media_sync.start_media_upload`. This is the add-on's own standard behavior for every suggestion; it is inherited, not added.

**Error taxonomy** (amended, spec revision 10: the §25 machine code is layered IN FRONT of this taxonomy — full form `"[<plus-code>] <CODE>: <message>"`; the taxonomy code and message body are unchanged) — semantic/flow errors raise `"<CODE>: <message>"` (parse the taxonomy code with `error.split("] ", 1)[1].split(": ", 1)[0]`, the machine code per §25): `ANKIHUB_ADDON_MISSING` (`[incompatible_ankihub_addon]`), `ANKIHUB_ADDON_DISABLED` (`[incompatible_ankihub_addon]`), `ANKIHUB_NOT_LOGGED_IN` (local `is_logged_in()` false → `[not_logged_in]`, or HTTP 401 = token rejected → `[auth_failed]` — the machine code is what distinguishes them), `NOT_AN_ANKIHUB_NOTE` (`[not_found]`), `NOTE_DELETED_ON_ANKIHUB` (`[not_found]`; HTTP 404 raised outside `suggest_note_update`'s own catch, or a duplicate-conflict whose conflicting note is soft-deleted), `VALIDATION_ERROR` (`[validation_error]`; HTTP 400 body passthrough as compact JSON; when the body contains the server's "don't have any changes to the original note" error the message gets **"sync with AnkiHub first, then re-suggest"** advice appended — the local AnkiHub DB is the diff baseline and may be behind the server revision), `PERMISSION_DENIED` (`[permission_denied]`; HTTP 403 `detail`), `RATE_LIMITED` (`[rate_limited]`; HTTP 429), `NETWORK_ERROR` (`[network_error]`; `AnkiHubRequestException` = offline/transport, or any unexpected HTTP status incl. 5xx), `INCOMPATIBLE_ANKIHUB_ADDON` (`[incompatible_ankihub_addon]`), `SOURCE_REQUIRED` (`[source_required]`), `RATIONALE_INVALID` (`[rationale_invalid]`). Parameter-shape errors keep §3.2 house style (Deviation #10a) with `[invalid_param]`.

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
| `autoAccept` | bool | `false` | Only effective where the user is owner/maintainer of the AnkiHub deck; pointless on decks you merely subscribe to. |

**Source rules (replicating the dialog, `suggestion_dialog.py:507-512, 778-786, 829-846`)** — a Source exists only where the dialog shows one: (a) `new_content`/`updated_content` on the **AnKing deck** (`ankihub_did_for_anki_nid(note) == config.anking_deck_id`): REQUIRED — `source` must be present with `type` in `AMBOSS | UWorld | Society Guidelines | Other` and non-empty `text`, else `SOURCE_REQUIRED`; (b) `delete` on any deck: optional, `type` must be `Duplicate Note`, blank text folds nothing. Everywhere else a passed `source` is rejected (`invalid parameter`). The folded comment is `rationale + "\nSource: {type} - {text}"`, with UWorld's text prefixed `"Step {step} "` (`step` int 1–3, required for UWorld, rejected on other types — Deviation #10b). Tags are NOT parameters: the add-on's diff computes added/removed tags itself.

**Returns** `{"result": "success"|"noChanges"|"notFoundOnAnkiHub"|"emptyFirstField", "comment": "<final comment as submitted>"}` — the four `ChangeSuggestionResult` outcomes, never raised. `noChanges` means the diff vs the LOCAL AnkiHub DB was empty — the note may still differ from the server; syncing with AnkiHub first updates the baseline. `notFoundOnAnkiHub` = deleted/tombstoned there.

### 19.3 `ankihubSuggestNewNote`

Submit ONE new-note suggestion via the add-on's `suggest_new_note` (`main/suggestions.py:369`).

**Params** — `note` (int; must NOT already be on AnkiHub, else `VALIDATION_ERROR` pointing at `ankihubSuggestNoteUpdate`), `rationale` (as above), `source` (optional, `AMBOSS | UWorld | Society Guidelines | Other`; folded identically — an API extension, the dialog's new-note flow has no Source widget, Deviation #10c), `deckId` (optional AnkiHub deck uuid string; default resolves via `ankihub_db.ankihub_did_for_note_type(note.mid)`, else `NOT_AN_ANKIHUB_NOTE` asking for an explicit `deckId`), `autoAccept` (false), `resubmitAsChangeOnDuplicate` (true).

**Flow** — empty first field short-circuits to `{"result": "emptyFirstField"}` before any network (mirrors the dialog's pre-submit check, `suggestion_dialog.py:368`). On the server's duplicate-anki_id 400 (`parse_duplicate_anki_id_error`): conflicting note soft-deleted → `NOTE_DELETED_ON_ANKIHUB`; otherwise, with `resubmitAsChangeOnDuplicate` true and a conflicting id present, the suggestion is resubmitted via `resubmit_new_note_as_change_suggestion` with change type `updated_content` and the same comment — mirroring the add-on's own conflict dialog (`suggestion_dialog.py:208-228`; media was already renamed+uploaded by the failed submit and is not re-uploaded). With the flag false (or no conflicting id from an older server) the 400 maps generically to `VALIDATION_ERROR`.

**Returns** `{"result": "success"|"noChanges"|"notFoundOnAnkiHub"|"emptyFirstField", "resubmittedAsChange": bool}`. `noChanges` from the direct path = the add-on found nothing to submit; from the resubmit path = server-diff empty.

**Headless test scope (ZERO network, ZERO add-on imports)** — `tests/headless_ankihub_test.py` covers only the pure `core.py` helpers: the three actions in `PLUS_ACTIONS`; constants incl. the nine wire values and the source-type matrix; change-type/rationale validation; the full Source enforcement matrix (AnKing required, non-AnKing rejected, delete optional, UWorld step, unknown keys/shapes); exact folded-comment strings; HTTP error mapping incl. the no-changes advice and 5xx→`NETWORK_ERROR`; result mapping incl. the unknown-member `INCOMPATIBLE_ANKIHUB_ADDON` path; `ankihub_missing_params`; and that neither `aqt` nor the `1322529746` package ever enters `sys.modules`. The live paths (`ankihubStatus` against the running add-on, actual suggestion submission) are manual-only — never from tests (HARD RULE: no AnkiHub network calls from automation).

## 20. `checkDeckIntegrity` (spec revision 8, 2026-08-12; amended 2026-08-12, spec revision 12: `orphanMedia` → `orphanMediaCollectionWide` + count/cap)

First of two field-feedback actions (§§20–21) bringing the action count to **twenty-four**. `core.PLUS_ACTIONS` remains the single source of truth for the `plusInfo` action list. **READ-ONLY**: no collection write, no media write, no undo-stack change — tests assert `undo_status()` bit-identical after every call. Rationale (field feedback): after ~1,500 LLM-driven writes the caller had no way to audit what it had broken — media references to files that were never stored, cloze markup it mangled, and cloze notes whose cards no longer match their fields.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `deckName` | str | required | Must exist (`col.decks.id_for_name`). Scope = notes with **any card homed in the deck or its subdecks** (`odid` = home deck for cards currently in a filtered deck — same semantics as §4.7's deck filter). |
| `includeOrphanMedia` | bool | `false` | `true` additionally runs the **collection-wide** orphan scan (see below). Off by default because it reads every note in the collection, not just the deck. |
| `orphanMediaLimit` | int | `100` | Revision 12. Cap on how many orphan filenames are returned in the array (≥ 0; `0` = count only). Ignored when the scan is off. `orphanMediaCount` always reports the FULL size regardless of the cap. |

**Returns**

```json
{"missingMedia": [{"noteId": 1712345678901, "field": "Back", "filename": "gone.png"}],
 "unbalancedCloze": [{"noteId": 1712345678902, "field": "Text"}],
 "clozeCardMismatch": [{"noteId": 1712345678903, "expectedOrds": [0, 1, 2], "actualOrds": [0, 2]}],
 "clozeNotesWithoutCloze": [1712345678904],
 "orphanMediaCollectionWide": ["scratch-unused.png"],
 "orphanMediaCount": 1,
 "orphanMediaTruncated": false,
 "notesChecked": 812}
```

> **SCOPE WARNING (revision 12).** Every list in this report is **deck-scoped** — `missingMedia`, `unbalancedCloze`, `clozeCardMismatch`, `clozeNotesWithoutCloze`, `notesChecked` — **except `orphanMediaCollectionWide`, which is COLLECTION-WIDE.** Rationale (round-3 field feedback): the old key `orphanMedia` returned 1,659,713 B / 37,243 uncapped entries in 2.68 s on a real collection (data verified accurate — 8/8 sampled orphans confirmed, zero false positives), sitting fourth in a list of deck-scoped arrays, and the reporter nearly concluded "this deck has 37,243 orphans". The rename is one of revision 12's **two deliberate breaking contract changes** (the key was one day old); `orphanMedia` is gone, not aliased, so a stale caller fails loudly instead of silently reading `null`.

- `missingMedia`: per-field media references whose file is absent from the media dir. References are extracted with **anki's own `MediaManager.regexps`** (img/audio/source `src`, object `data`, `[sound:...]`) and the same remote-scheme exclusion `files_in_str` applies — but deliberately **without** `files_in_str`'s `render_latex` step, which can WRITE generated latex images into the media folder (read-only action). Consequence, documented: latex-generated images (`[latex]`/`[$]` tags) are **exempt** from `missingMedia` — Anki regenerates them on render. Filename comparison is NFC-normalized on both sides (macOS Finder copies can sit as NFD); no case folding, no HTML-entity decoding (parity with `files_in_str`). One entry per distinct `(noteId, field, filename)`; notes in ascending id order, fields in model order.
- `unbalancedCloze`: per field, count of `{{cN::` opens (anki's cloze-open marker, lowercase `c` + digits) vs count of `}}` closes; reported when they differ. Simple brace-balance by design — documented limitation: a field containing literal `}}` text (nested LaTeX braces, handlebars snippets) with no cloze opens is reported too. Checked on **every** notetype (cloze markers in a non-cloze note are equally an authoring error worth surfacing).
- `clozeCardMismatch`: **cloze-type notetypes only** (`model["type"] == MODEL_CLOZE` — includes the Image Occlusion notetype). `expectedOrds` = card ordinals implied by the fields' cloze numbers via the backend's own parser (`col._backend.cloze_numbers_in_note` on a minimal `notes_pb2.Note(fields=...)` proto — the exact code card generation uses; probe-verified pure and collection-free), mapped `{{cN::}}` → ord N−1, `c0` excluded (annotation-only, §5). `actualOrds` = ords of the note's existing cards (all decks, not just the audited one). Reported only when the sorted lists differ — **except the placeholder pair `expectedOrds: []` / `actualOrds: [0]`, which is never reported**: for a cloze note whose fields yield zero effective cloze numbers (no markers, `c0`-only, uppercase `{{C1::…}}` — anki's parser is lowercase-only), anki's own card generation deliberately creates and keeps a single placeholder card ord 0 (rslib cardgen ensure-not-empty rule; the Empty Cards tool keeps it too — empirically verified on 25.09.4), so `[0]` is exactly the correct card set, not drift. Typical hits: a deleted cloze card, or field edits that never regenerated cards.
- `clozeNotesWithoutCloze` (additive, field-feedback fix to the placeholder false-positive class): note ids of cloze-type notes whose fields yield **zero effective cloze numbers** (ascending). Not card/field drift — anki maintains the placeholder card for them — but precisely the LLM authoring error this audit targets (a "cloze" note that will never cloze anything), surfaced under its own name so it cannot drown `clozeCardMismatch`.
- `orphanMediaCollectionWide` (revision 12; was `orphanMedia`): `null` when `includeOrphanMedia` is false. When true: media-dir files referenced by **no note field in the whole collection** and no notetype template. Collection-wide by nature — a file unreferenced by this deck may be used elsewhere, so orphan status can only be decided globally. Referenced set = every note's field references (same regexps), **plus** latex-generated filenames via the pure backend `extract_latex` transform (`expand_clozes=True`, per-model `latexsvg`; guarded by a cheap `[latex]`/`[$]`/`[$$]` marker check — this is exactly `files_in_str`'s transform minus its image-generation side effect), **plus** template/CSS static references via `col.media.extract_static_media_files(mid)`. Excluded from the report: leading-`_` files (static-use by Anki's own convention) and dotfiles (`.DS_Store` junk). Sorted, then truncated to `orphanMediaLimit` entries.
- `orphanMediaCount` (revision 12): the FULL number of collection-wide orphans found, independent of `orphanMediaLimit` — `int` when the scan ran, `null` when `includeOrphanMedia` is false (same null-means-not-scanned rule as the array). This is the number a caller should act on; the array is a sample.
- `orphanMediaTruncated` (revision 12): `true` when `orphanMediaCount > orphanMediaLimit`, i.e. the array is a prefix of the sorted full list. `false` when the scan is off (there is no array to truncate). **Deliberate inconsistency, kept (round-3 review raised it as a minor).** Its two siblings, `orphanMediaCollectionWide` and `orphanMediaCount`, use `null` to mean "not computed", and the reviewer argued all three should. They should not be silently different, so: `false` here is a claim about the ARRAY ("nothing was truncated"), which is true whether or not the scan ran, and it is the value this section has documented since revision 12. Changing it would be a wire change to a shipped key for tidiness alone. Callers must read `orphanMediaCollectionWide is null` (never `orphanMediaTruncated`) to learn whether the scan ran.
- `notesChecked` = number of notes in the deck scope.

**Anki API calls / SQL (read-only; explicitly allowed by the HARD RULES bullet)** — `col.decks.id_for_name` + `col.decks.deck_and_child_ids`; scope select `select distinct nid from cards where (case when odid != 0 then odid else did end) in (...) order by nid`; chunked (`SQL_IN_CHUNK`) `select id, mid, flds from notes where id in (...) order by id` (fields split on `\x1f`, names from `col.models.get(mid)` cached per mid); chunked `select nid, ord from cards where nid in (...) order by nid, ord` for the cloze notes; `col.media.regexps` / `col._backend.cloze_numbers_in_note` / `col._backend.extract_latex` / `col.media.extract_static_media_files` as above; `os.listdir(col.media.dir())` filtered to plain files. Single pass over scope notes (plus one pass over all notes iff `includeOrphanMedia`); target a few seconds on a 30k-note collection.

**Error cases** (codes per §25) — `[invalid_param]` `"invalid parameter: deckName: string required"`; `[deck_not_found]` `"deck was not found: <name>"`; `[invalid_param]` `"invalid parameter: includeOrphanMedia: boolean required"`; `[invalid_param]` `"invalid parameter: orphanMediaLimit: int >= 0 required"` (revision 12). Everything else is expressed in the return value.

**Edge cases tests must cover** — clean deck → four empty list signals (`missingMedia`, `unbalancedCloze`, `clozeCardMismatch`, `clozeNotesWithoutCloze`), `orphanMediaCollectionWide: null` + `orphanMediaCount: null` + no `orphanMedia` key at all, `notesChecked` exact, undo snapshot bit-identical; missing `[sound:...]` and `<img src>` each reported with the right field name, duplicate reference in one field reported once, present file and remote URL exempt, subdeck note in scope, other-deck note out of scope; unbalanced `{{c2::b` reported, balanced cloze not, literal `}}` in a Basic field reported (documented limitation); cloze note with a removed card → `expectedOrds`/`actualOrds` drift reported, Basic note with cloze-looking text never in `clozeCardMismatch`; zero-cloze cloze notes (no markers / `{{c0::…}}`-only / uppercase `{{C1::…}}`) each keep anki's placeholder card ord 0 and appear in `clozeNotesWithoutCloze` but **never** in `clozeCardMismatch`, while a genuinely deleted cloze card is still reported; orphan scan: unreferenced file reported sorted, referenced file / `_`-prefixed file / existing latex-generated image all exempt, flag off → `null`; revision 12 — `orphanMediaCount` equals the full list length while `orphanMediaLimit` truncates the array to a prefix and flips `orphanMediaTruncated`, `orphanMediaLimit: 0` returns `[]` with the count intact, negative limit → hard error.

## 21. `bulkReplaceInFields` (spec revision 8, 2026-08-12)

Second field-feedback action (count: twenty-four, see §20). Find/replace on the **raw field HTML of ONE named field** across many notes, as one undoable batch with a mandatory-preview-friendly dry run. Rationale (field feedback): the caller hand-rolled read-modify-write loops over `notesSlim` + `bulkUpdateNoteFields` for simple text substitutions — slow, and each hand-rolled loop is a fresh chance to mangle fields.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `query` | str | — | Anki search string (verbatim, §13 conventions). Exactly one of `query`/`noteIds` required. Processing order: ascending noteId. |
| `noteIds` | [int] | — | Explicit ids, caller order, **deduplicated first-occurrence-wins** (§11.1 precedent — processing one note twice would re-match against its own replacement). |
| `field` | str | required | The single field operated on. Notes lacking it are skipped with a reason, never an error. |
| `find` | str | required | **Non-empty** (an empty find matches between every character in both modes — never meaningful, always a bug). Literal text, or a python `re` pattern when `isRegex`. |
| `replace` | str | required (may be `""`) | Literal mode: inserted **verbatim** (callable replacement — no `\`-escape parsing). Regex mode: a python `re` template (`\1`, `\g<name>` expand). |
| `isRegex` | bool | `false` | Python `re` semantics. **No backtracking-bomb protection** (documented): a pathological pattern can hang the single-threaded server for its duration. The pattern is compiled up front — a non-compiling pattern is a clear parameter error. |
| `caseSensitive` | bool | `true` | `false` = `re.IGNORECASE` in both modes. |
| `dryRun` | bool | `false` | Zero-write preview, §15 anti-drift rule: the identical read/compute pass runs and short-circuits before the write pass. |
| `atomic` | bool | `true` | Same contract as the other bulk actions (§3.3/§4.1). |
| `maxPreview` | int | `20` | Dry-run only: cap on `preview` entries (≥ 0). |

**Returns** (real run)

```json
{"changed": [1712345678901], "matchesTotal": 3, "unchanged": [1712345678902],
 "skipped": [{"noteId": 1712345678903, "reason": "field was not found in note: Front"}],
 "suspensionPreserved": true, "schedulingPreserved": true,
 "undoEntry": "AnkiConnect Plus: Replace in Fields"}
```

**Preserves (§31.1) + the revision-18 post-check (§31.2)** — everything except the one named field's HTML on the matched notes: tags always, other fields, ids, GUIDs, and every existing card's scheduling/suspension/flags/deck. `suspensionPreserved`/`schedulingPreserved` are the same before/after `(queue, due, ivl)` snapshot check `bulkUpdateNoteFields` carries (§4.2/§31.2): always present on the real response, absent on dry runs, `false` = alarm. Card-set caveat as §4.2: a replacement introducing a new cloze number generates that card.

**Returns** (`dryRun: true`)

```json
{"wouldChange": [1712345678901], "matchesTotal": 3, "unchanged": [1712345678902],
 "skipped": [], "preview": [{"noteId": 1712345678901, "before": "<b>old</b>", "after": "<b>new</b>"}],
 "previewTruncated": false, "undoEntry": null}
```

- `changed` / `wouldChange`: ids actually (or would-be) written, in processing order. `matchesTotal`: total pattern matches found across all processed notes — **including** matches whose replacement was byte-identical (see `unchanged`).
- `unchanged`: ids where the pattern found nothing **or** every match replaced itself byte-identically (`find == replace` etc.) — never written, no undo entry for them (the shared §4.2/§4.3 no-op rule).
- `skipped`: `{noteId, reason}` — `"note was not found: <id>"` (stale explicit id) or `"field was not found in note: <field>"` (result sets may span models), plus `atomic: false` write-failure reasons. Keyed by **noteId, not index** (deliberate deviation from §4.1's `{index, reason}`: the query path has no meaningful input index).
- `preview`: dry-run only, first `maxPreview` would-change notes with full raw before/after field HTML; `previewTruncated` = more would-change notes exist than previewed. The dry response also carries `skipped` and `undoEntry: null` (house §15 shape) beyond the locked key list — additive.
- `undoEntry`: `"AnkiConnect Plus: Replace in Fields"`, `null` when nothing was written. One merged entry; single `col.undo()` reverts the whole batch. Atomic failure raises `"bulkReplaceInFields failed (batch reverted): {json}"` with `{failedNoteId, error, changedBeforeRevert, skipped}` (noteId-keyed for the same reason as `skipped`).

**Algorithm** — validate params → compile pattern (`re.escape` in literal mode) → resolve ids (query: `col.find_notes(query, order=False)` sorted, §13; bad syntax → `"invalid parameter: query: <backend message>"`) → **compute pass, read-only and shared by dry/real by construction (§15)**: per note `col.get_note`, field membership, `pattern.subn` on the raw field value (an invalid regex replacement template — e.g. `\9` with one group — raises `re.error` on the first match, which is always **before any write**, and surfaces as `"invalid parameter: replace: <error>"`) → dry run returns here → write pass: set field, lazy `add_custom_undo_entry` + `merge_undo_entries` per §3.3, atomic revert per §4.1.

**Error cases** (codes per §25) — all `[invalid_param]`: `"invalid parameter: query: exactly one of query or noteIds required"`; `"invalid parameter: query: string required"` / `"invalid parameter: query: <backend parse error>"`; `"invalid parameter: noteIds: ints required"`; `"invalid parameter: field: string required"`; `"invalid parameter: find: non-empty string required"`; `"invalid parameter: find: invalid regex: <error>"`; `"invalid parameter: replace: string required"` / `"invalid parameter: replace: <re template error>"`; `"invalid parameter: isRegex|caseSensitive|dryRun|atomic: boolean required"`; `"invalid parameter: maxPreview: int >= 0 required"`. Plus `[batch_reverted]` `"bulkReplaceInFields failed (batch reverted): <json>"`.

**Edge cases tests must cover** — literal replace across a query: `changed` ascending, per-note multi-match counted in `matchesTotal`, other fields untouched, single undo reverts all; dry run: exact shape incl. capped `preview` + `previewTruncated`, DB and undo snapshot untouched, dry-then-real prediction matches; regex with group backrefs; case-insensitive literal; literal-mode `replace` containing `\1` inserted verbatim; `find == replace` → `unchanged` with `matchesTotal` counted, `undoEntry: null`, undo stack untouched; note lacking the field skipped with the exact reason; stale noteId skipped; duplicate noteIds deduplicated; invalid template → parameter error with zero writes; atomic injected failure → full revert + parseable report; `atomic: false` → partial continue with the failure in `skipped`.

---

## 22. `mediaExists` (spec revision 9, 2026-08-12; amended 2026-08-12, spec revision 12: `actualName`)

First round-2 field-feedback action (count: twenty-six together with §23). Cheap **read-only membership probe** for media filenames. Rationale (measured in real use): the caller pulled **4.22 MB** via `getMediaFilesNames` to answer a 13-name membership test.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `filenames` | [str] | required | Bare media filenames to test, any length (empty list allowed). **Non-string entries are a hard parameter error**; malformed or path-carrying strings are NOT errors — they simply report `exists: false` (they can never name a stored media file). |

**Returns**

```json
{"results": [{"filename": "occl-a98591b53359.png", "exists": true, "actualName": null},
             {"filename": "BSOM_L2_S3A.PNG", "exists": true, "actualName": "bsom_l2_s3a.png"},
             {"filename": "sub/dir.png", "exists": false, "actualName": null}]}
```

- One entry per input name, **input order preserved** (duplicates included).
- `exists` = the name is non-empty, bare (`os.path.basename(f) == f`), and `os.path.isfile(mediaDir/f)` — the same file test `mediaThumbnails` (§14) uses. **Unchanged in revision 12**: the existence oracle is exactly what it was, so `exists` never flips.
- **`actualName` (revision 12, round-3 field feedback, additive)**: the TRUE on-disk spelling when it differs from the requested string; `null` when they match byte-for-byte, and `null` whenever `exists` is false. Rationale (measured): APFS (and NTFS) answer `os.path.isfile` case-insensitively, so `BSOM_L2_S3A.PNG` and `BsOm_L2_s3a.PNG` both reported `exists: true` for a single stored `bsom_l2_s3a.png` — a caller validating `<img src>` spellings before an AnkiHub push got a green light on names that 404 on Linux/iOS/AnkiWeb. Inherited from stock `getMediaFilesNames`/`col.media.have()` (same `os.path.exists`), not a regression — but now visible. Implementation: one `os.listdir(mediaDir)` per call, taken lazily (only when at least one requested name exists) and reused for the whole call (~2.13 ms per 5,000 files measured; ~16 ms at 37 k), then exact membership first and an NFC-casefolded lookup for the drifted case. Ties (a case-sensitive volume holding several matches) resolve to the first in sorted order.
- **The media DB is deliberately NOT the oracle** (refuting the suggested fix): `<col>.media.db2` IS readable read-only and IS case-exact, but a file dropped into the media folder outside Anki is absent from it and `col.media.check()` does not add it (probe-verified: folder `[handdropped.png, viaapi.png]`, DB `[viaapi.png]` before and after `check()`), so matching the DB would report `exists: false` for real files.
- On a case-SENSITIVE volume the drifted spelling simply reports `exists: false, actualName: null` — the honest answer there. Tests accept both outcomes but forbid `exists: true` with `actualName: null` for a drifted spelling.
- Pure read: no writes, no undo entry, media folder untouched.

**Error cases** (codes per §25) — `[invalid_param]` `"invalid parameter: filenames: list of strings required"` (non-list, or any non-string entry).

**Edge cases tests must cover** — present/absent mix in input order; duplicate names; path-y (`sub/a.png`, `/abs/a.png`) and empty-string names → `false`, not errors; non-string entry → hard error; empty list → `{"results": []}`; notes/undo/media-dir snapshots bit-identical; revision 12 — exact spelling → `actualName: null`, case-drifted spelling → the stored name (or `exists: false` on a case-sensitive volume), absent name → `actualName: null`.

---

## 23. `storeMediaFilesBulk` (spec revision 9, 2026-08-12)

Second round-2 field-feedback action. Store many media files in one call with **per-item results that surface Anki's dedup/rename decision**, closing the caller's "stored 13 files blind, then pulled 4.22 MB to verify" loop. Stock `storeMediaFile` (upstream code) stays untouched.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `files` | [{filename, data \| path}] | required | Per item: `filename` (bare media filename, required), plus **exactly one** of `data` (base64; MIME line-wrapping tolerated, same lenient rule as §4.4) or `path` (absolute path to a file on disk; `~` expanded). Unknown keys are a per-item error. |

**Returns**

```json
{"stored": [{"requested": "a.png", "actual": "a.png"},
            {"requested": "a.png", "actual": "dup-3ba3ff….png"},
            {"requested": "b.png", "error": "invalid parameter: files[2].data: invalid base64"}]}
```

- One entry per input item, **input order preserved**; failures are per-item `{requested, error}` (requested `null` when no string filename could be read off the item) and never abort the batch — later items still store.
- `actual` = the filename Anki actually stored via `col.media.write_data` (§4.4 semantics, probe-verified: same-name+same-bytes dedups to the same name with no new file; same-name+different-bytes renames to `dup-<sha1>.<ext>`; the original file's bytes are never overwritten).
- Media writes are **not undoable** (upstream `storeMediaFile` precedent): no undo entry, undo stack bit-identical.

**Error cases** (codes per §25) — hard: `[invalid_param]` `"invalid parameter: files: list required"`. Per-item (unprefixed, §3.2): `"invalid parameter: files[i]: object required"`, `"invalid parameter: files[i]: unknown key(s): <keys>"`, `"invalid parameter: files[i].filename: string required"`, `"invalid parameter: files[i].filename: bare media filename required"`, `"invalid parameter: files[i]: exactly one of data or path required"`, `"invalid parameter: files[i].data: string required"` / `"… invalid base64"`, `"invalid parameter: files[i].path: string required"` / `"… absolute path required"`, `"media source file was not found: <path>"`, `"could not read file: <path>: <err>"`, `"could not store media file <name>: <err>"`.

**Edge cases tests must cover** — data and path variants store byte-exact; dedup (same bytes → same `actual`, no new file); rename (different bytes → `actual != requested`, original preserved); relative path rejected; every per-item error shape above with a later valid item still succeeding; empty list; undo snapshot bit-identical throughout.

---

## 24. `undoLabel` on write actions (spec revision 9, 2026-08-12)

Cross-cutting param (amends §3.3; return-shape amendments in §4.4 and §4.6). Rationale (measured in real use): three same-named entries in the Undo menu made selective undo a coin flip.

- **Actions**: every Plus action that creates an undo entry — `bulkAddNotes`, `bulkUpdateNoteFields`, `bulkAddTags`, `bulkSuspend`, `bulkSetDueDate`, `bulkReplaceInFields`, `cropImage`, `cropImageOcclusionImage`, `updateImageOcclusionNote`, `addImageOcclusionNote`, and (revision 17) `renameDeck`, `bulkSetFlag`, `renameTag`, plus slice 2's `emptyFilteredDeck`, `deleteEmptyCards`, and (revision 19) `createFilteredDeck`, `rebuildFilteredDeck` — gains `undoLabel` (str, default `null`).
- **Sanitization** (`core.sanitize_undo_label`, raised **before any write**): whitespace runs (newlines included) collapse to single spaces, ends stripped, label capped at **80 chars**; final name = `"AnkiConnect Plus: " + <label>`. Non-string → `"invalid parameter: undoLabel: string required"`; empty after sanitizing → `"invalid parameter: undoLabel: non-empty string required"`.
- **Threading**: the sanitized name replaces the action's default entry name (§3.3 table) at every use site — lazy `add_custom_undo_entry`, `merge_undo_entries` target, atomic revert / empty-entry pop, and the `undoEntry` response field. With `undoLabel: null` every default name and behavior is byte-for-byte unchanged.
- **IO actions** (`addImageOcclusionNote`, `updateImageOcclusionNote`) have no custom entry by default (the backend op's own entry). With a label, a custom entry wraps the backend op(s) — for the add, the deck move too — via the §3.3 add/merge pattern, and a failure after entry creation pops/reverts it. Their responses now always carry `undoEntry` (§4.4 additive; §4.6 was `null` → **deliberate contract change**), reporting the ACTUAL top-of-stack name (`col.undo_status().undo`) so the default path stays honest about the backend's own (locale-dependent) entry name. A **no-op** `updateImageOcclusionNote` (every backfilled value byte-matches the note — §4.6) short-circuits before any entry is created and returns `undoEntry: null` per the reporting rule below (revision 11 — previously the unlabeled path echoed whatever unrelated entry was on top of the stack, and the labeled path left an empty do-nothing custom entry, violating Deviation #7).
- **`undoEntry` reporting rule** (all seventeen actions): the actual final entry name when at least one undoable write happened, else `null` (§3.3 lazy-entry rule; dry runs always `null`). `cropImageOcclusionImage` always writes, so its response (which gains `undoEntry`, additive) always names the entry; `cropImage`'s is `null` when no notes were rewritten (the media write alone is not undoable).

**Edge cases tests must cover** — labeled entry name on top of the undo stack + single undo reverts (bulk add, replace, IO add incl. deck move, IO update, both crops); defaults byte-identical with `undoLabel` omitted; sanitize (collapse/strip/80-cap); bad labels raise before any write; dry run with a label → `undoEntry: null`, undo snapshot untouched; nothing-written paths (`bulkReplaceInFields` no-match, `cropImage` without note rewrites, no-op `updateImageOcclusionNote` with an unrelated marker entry on the stack) → `undoEntry: null` even with a label, marker entry untouched.

---

## 25. Stable error codes (spec revision 10, 2026-08-12; amended revision 13: `reachable` column, `unknown_action`, and §§25.1–25.3 — the structured envelope, the sync guard, and argument-binding messages)

Cross-cutting contract on **every Plus action** (26 at revision 10, **27** since revision 12's §26 `undoStatus`, **30** since revision 17's §28 maintenance actions, **34** since revision 17 slice 2's §§29–30 filtered-deck/empty-cards actions, **36** since revision 19's §32 filtered-deck build actions, **37** since revision 20's §33 staged optional-tag action; amends §3.2; every action's error list now shows its codes). Rationale (round-2 field feedback, measured in real use): callers pattern-matched free-text error messages to decide whether to retry, fix params, or give up — brittle and English-locked.

**Format** — every error **raised** by a Plus wrapper or by `core` carries a machine-parseable prefix: `"[<code>] <message>"`. The `<message>` body is byte-identical to the pre-revision-10 text (including, for AnkiHub actions, the §19 `CODE:` taxonomy prefix — two layers, coarse machine code + fine taxonomy code, both stable). Codes never contain `]` or whitespace; parse with `error.split("] ", 1)[0].lstrip("[")`. Implementation: `core.PlusError(code, message)` (`.code`, `.message`, `.retryable` attributes; `str()` renders the prefixed form; an unknown code is a `ValueError` at raise time — an add-on bug, never a caller error) + the `plus_api` wrapper on every action, which passes `PlusError` through and re-raises anything unexpected as `[internal]` with the original message body. **Per-item error strings embedded in results are NOT prefixed** (§3.2).

**Code vocabulary** (`core.PLUS_ERROR_CODES`, closed set; *retryable* = the same call may succeed later without the caller changing anything). **Amended revision 13** with a **reachable** column and the new `unknown_action` code. *Reachable* = some code path can actually raise it today; `no` marks a code the vocabulary reserves but nothing raises, so **a caller must not build retry logic around it**. This distinction was invisible before revision 13 and was the substance of round-3 ASK 4: of the five codes flagged retryable, two were documented as never raised, two were AnkiHub-only, and the flag itself never reached the wire. Both columns are served at runtime by `plusInfo.errorCodes` (§4.9), whose `retryable` is read from this same dict so the two can never drift; the prose lives in `core.PLUS_ERROR_CODE_DOCS`.

| code | retryable | reachable | meaning / current raise sites |
|---|---|---|---|
| `not_found` | no | yes | note/card/media file/IO notetype/output directory absent; AnkiHub note not on AnkiHub (`NOT_AN_ANKIHUB_NOTE`) or deleted there (`NOTE_DELETED_ON_ANKIHUB`, incl. HTTP 404) |
| `invalid_param` | no | yes | the whole `"invalid parameter: …"` house family (§3.2), plus a dispatch-splat `TypeError` (unexpected/missing argument in the request), house-formatted per §25.3 |
| `deck_not_found` | no | yes | `"deck was not found: <name>"` everywhere (decks are never auto-created) |
| `duplicate` | no | **yes (new in revision 17)** | a name you asked to claim is already taken — both sites refuse with `"deck already exists: <name>"` instead of inheriting the backend's silent auto-rename to `name+`. `renameDeck`: `newName` (or an implied descendant name) resolves to ANY deck other than the very deck being renamed onto it — the renamed subtree's own members included; a case-only respelling resolves to itself and stays legal (§28.1, the revision-17 fix pass's pairwise self-identity rule). `createFilteredDeck` (revision 19): the requested name already exists, matched the way anki matches deck names — case-insensitively, surrounding whitespace ignored (§32.1). NOTE-level duplicates are still per-item `skipped[].reason` strings, never raised |
| `cards_in_filtered_decks` | no | **yes (new in revision 17, slice 2)** | `exportDeckApkg`'s fail-closed default (§§17, 29.3): at least one card whose HOME deck is inside the export scope sits in a filtered deck, or a filtered deck nested inside the scope holds cards homed outside it (fix pass) — the .apkg would silently omit whole notes, ship scheduling-reset cards, or ship foreign notes into a recreated deck; the message names the filtered decks and counts. Empty them (`emptyFilteredDeck`) and re-export, or pass `allowFilteredOmission: true` to export anyway with the damage itemized in `warnings` |
| `unsupported_format` | no | yes | crop load/encode failures: `"could not load image: …"`, `"could not encode cropped image as …"` |
| `io_error` | no | **no** | **reserved** — disk read/write failures surface as per-item errors today (`stored[].error`), never raised |
| `batch_reverted` | no | yes | every `"… failed (batch reverted): {json}"` / `"cropImage failed (note updates reverted): …"` / `"cropImageOcclusionImage failed (changes reverted): …"`; the JSON report parse rule (§3.2) is unchanged |
| `collection_unavailable` | **yes** | yes | upstream `self.collection()`'s `"collection is not available"` (profile screen), mapped at the `plus_api` boundary |
| `sync_in_progress` | **yes** | **yes (new in revision 13)** | the §25.2 sync guard: a guarded action was called while a `syncNow` job is in state `syncing`. **No longer reserved** — this is the one genuinely reachable retryable code that needs neither a network nor a second add-on, so the `retryable` flag is finally testable. `syncNow` still reports its own busy states via `{started: false, reason}` and never raises |
| `not_logged_in` | no | yes* | a login this add-on cannot perform is required: AnkiHub `is_logged_in()` false (`ANKIHUB_NOT_LOGGED_IN:` local check) |
| `auth_failed` | no | yes* | stored credential **rejected by the server**: AnkiHub HTTP 401 (message keeps its `ANKIHUB_NOT_LOGGED_IN:` taxonomy prefix — the two are distinguished by machine code, deliberately) |
| `offline` | **yes** | **no** | **reserved** — sync network failures surface in `job.error.code` / `required`, never raised |
| `full_sync_required` | no | **no** | **reserved** — surfaced via the sync job error, never raised |
| `network_error` | **yes** | yes* | `AnkiHubRequestException` transport failures and unexpected HTTP statuses incl. 5xx (`NETWORK_ERROR:` taxonomy) |
| `rate_limited` | **yes** | yes* | AnkiHub HTTP 429 (`RATE_LIMITED:` taxonomy) |
| `permission_denied` | no | yes* | AnkiHub HTTP 403 (`PERMISSION_DENIED:` taxonomy) |
| `validation_error` | no | yes | well-formed request refused on semantic grounds: not-an-IO-note, IO note without an image, non-rect/unpreservable/mixed-oi occlusions, crop-drops-all-occlusions, AnkiHub HTTP 400 (`VALIDATION_ERROR:` taxonomy) and note-already-on-AnkiHub; plus the deck-kind refusal family (revisions 17/19, §§29.2, 32): `emptyFilteredDeck`/`rebuildFilteredDeck` aimed at a regular deck, `createFilteredDeck` under a filtered parent or matching zero gatherable cards (nothing created), and `rebuildFilteredDeck`'s unparseable saved search term |
| `incompatible_ankihub_addon` | no | yes | AnkiHub add-on missing / disabled / not loaded this session (`ANKIHUB_ADDON_MISSING:` / `ANKIHUB_ADDON_DISABLED:` taxonomy) or drifted from the tested version (`INCOMPATIBLE_ANKIHUB_ADDON:`) — the bridge is unusable either way |
| `source_required` | no | yes* | `SOURCE_REQUIRED:` taxonomy (§19 Source rules) |
| `rationale_invalid` | no | yes | `RATIONALE_INVALID:` taxonomy (§19 rationale rules). **No AnkiHub add-on needed** (corrected after the round-3 review, which had it marked `yes*`): `core.validate_ankihub_rationale` runs BEFORE `self._plusAnkiHubModules()` in both suggest wrappers (`plus.py` `ankihubSuggestNoteUpdate` / `ankihubSuggestNewNote`), so a client with no add-on that passes an empty rationale gets `[rationale_invalid]`, not `[incompatible_ankihub_addon]` |
| `internal` | no | yes | anything unexpected escaping an action (backend exception, add-on bug): `"image occlusion note was not created"`, unhandled `col.*` failures, … |
| `unknown_action` | no | yes | **new in revision 13** — the DISPATCHER's `"unsupported action"` (§25.2). The only non-action error that carries a code |

`yes*` = reachable only with the AnkiHub add-on installed; a client without it will never see these. Note which codes are NOT starred: `source_required` is (it is only reached via `_ankihub_source_parts`, downstream of a successful `_plusAnkiHubModules()`), but `rationale_invalid` is not — its validation runs before the add-on import, so an add-on-less client can reach it with an empty rationale. The three `no` rows (`duplicate` moved to reachable in revision 17) are the honest answer to "which retryable codes can I actually test?": **`collection_unavailable` and `sync_in_progress` are the two a plain client can reach**, and `network_error`/`rate_limited` need AnkiHub.

**AnkiHub taxonomy mapping** (`core.ANKIHUB_CODE_TO_PLUS_CODE`): `VALIDATION_ERROR→validation_error`, `ANKIHUB_NOT_LOGGED_IN` (HTTP 401) `→auth_failed`, `PERMISSION_DENIED→permission_denied`, `NOTE_DELETED_ON_ANKIHUB→not_found`, `RATE_LIMITED→rate_limited`, `NETWORK_ERROR→network_error`. The §19 message-level taxonomy is unchanged and remains authoritative for AnkiHub-specific detail.

**Non-raise channels are untouched**: `syncNow`/`syncStatus` job `error.code` values (§18: `auth_failed`, `offline`, `aborted`, `full_sync_required`, `media_sync_failed`, `error`) and refusal `reason` strings, and all per-item result errors, keep their existing unprefixed vocabularies.

**Edge cases tests must cover** — vocabulary exact-match incl. retryable flags; `str(PlusError)` format and attribute surface; unknown code → `ValueError`; one raise-site spot check per code family (invalid_param, deck_not_found, not_found, validation_error, unsupported_format, batch_reverted with the JSON report still parsing after the prefix, rationale_invalid, source_required, incompatible_ankihub_addon); wrapper boundary: `collection is not available` → `[collection_unavailable]`, dispatch-splat TypeError → `[invalid_param]` — including a params object carrying a `"self"` key (revision 11: the wrapper declares `self` positional-only so the bound-method collision fails inside the wrapper, not before it, and maps to `[invalid_param]` instead of escaping unprefixed) — deeper TypeError and any unexpected exception → `[internal]` with the message body unchanged, PlusError pass-through byte-identical; per-item error strings unprefixed; `actionDocs` params strings still reflect the real signatures through the `plus_api` wrapper.

---

### 25.1 Structured error envelope (spec revision 13, 2026-08-12)

Round-3 ASK 4, measured: `PlusError` carried `.retryable` **as a Python attribute only** — the JSON error was a bare string, so any client wanting to know whether to retry had to hardcode the table above from a spec it may not have. Revision 13 puts the decision on the wire.

**Every error reply gains two keys, additive and ALWAYS present:**

```json
{"result": null, "error": "[collection_unavailable] collection is not available",
 "errorCode": "collection_unavailable", "retryable": true}
```

- `error` — **byte-for-byte unchanged** from revision 12. Nothing that parsed it keeps working differently.
- `errorCode` — `string | null`. The §25 code when the exception is a `core.PlusError`; **`null` otherwise**.
- `retryable` — `bool | null`. `PLUS_ERROR_CODES[code]` when coded; **`null` otherwise**.

Both keys are emitted on **every** error reply, including uncoded ones, so a client branches on a stable shape rather than on key presence. `null` is meaningfully different from `false`: it means *this server has no opinion*, not *do not retry*.

**Implementation — one choke point.** `web.format_exception_reply` (`connect_plus/web.py`) is the sole producer of error replies; it gains `from . import core` and an `isinstance(exception, core.PlusError)` branch. `format_success_reply` is untouched (success replies gain nothing, and the `version <= 4` raw-result path is unchanged). Because `AnkiConnect.multi` is `list(map(self.handler, actions))` and `handler` funnels every action exception through this same function, **`multi` sub-responses carry the identical four keys with no extra code** — verified end-to-end, not assumed. Note the trap for callers: the outer `multi` reply reports `error: null` even when every sub-action failed, so the fields must be read per sub-response.

**Prefixing boundary** (`core.PLUS_ERROR_PREFIX_NOTE`, served verbatim as `plusInfo.errorPrefixNote`): the 37 Plus actions and the §25.2 unknown-action error are prefixed and coded; the ~90 **upstream** AnkiConnect actions are passed through verbatim with `errorCode: null, retryable: null`. Consequence, stated because the round-2 spec implied otherwise: the documented parse rule `error.split("] ", 1)[0].lstrip("[")` **is not unconditional** — it is valid only when `errorCode` is non-null, and a client should simply read `errorCode` instead. The api-key refusal (`"valid api key must be provided"`) is raised by the dispatcher but is deliberately **not** coded: it is not an unknown action, and it predates this contract.

### 25.2 `unknown_action` and the reachable `sync_in_progress` guard (spec revision 13)

**(a) `unknown_action`** — round-3 ASK 11a: `{"action": "noSuchAction"}` answered a bare `"unsupported action"`, so the single most likely error a new client hits was the one case the vocabulary did not cover, and the documented parse rule silently returned the whole message. The dispatcher's `raise Exception('unsupported action')` in `connect_plus/__init__.py` becomes `raise core.PlusError('unknown_action', 'unsupported action')` (one surgical line plus `core` on the existing `from . import` — §2.3). The message body after the prefix is unchanged. **No other upstream error is prefixed**, by design.

**(b) `sync_in_progress` becomes genuinely reachable.** Round-3 ASK 4 objected — correctly — that the flag was untestable: of five retryable codes, two were reserved, two needed AnkiHub, and the fifth needed closing the profile. The documented hazard was already real (README: "sync blocks everything"), just unenforced: while `syncNow`'s job is in state `syncing` the backend holds the collection mutex for the whole `sync_collection` call, so any collection touch from an HTTP handler would **block the Qt main thread, and with it this server**, until the sync finished.

`plus_api` gains `guard_sync=True`. Before argument binding, a guarded action reads the mixin's lazy job slot (`getattr(self, '_plusSyncJobState', None)` — a read-only probe that never creates it) and raises `[sync_in_progress]` when the state is `syncing`. Because the guard runs *before* binding, it fires for every guarded action regardless of its parameters.

- **Guarded: 23 actions.** Message body is `core.SYNC_IN_PROGRESS_MESSAGE`, which names the recovery move (poll `syncStatus`).
- **Not guarded: `syncStatus`, `syncNow`, `plusInfo`, `ankihubStatus`** (`@plus_api(guard_sync=False)`). `syncStatus` is the only way to *observe* a running sync and already skips all collection access while `syncing` (Deviation #9b); `syncNow` reports busy states as **data** (`{started: false, reason: 'already_syncing'}`, §18.1) and must not start raising; `plusInfo` is pure reflection and must work before a profile is open; `ankihubStatus` reads the AnkiHub add-on's own config, never the collection.
- **Only `syncing` is guarded, never `media_syncing`.** By then `sync_collection` has returned and the mutex is free — stock Anki lets you review during a media sync, and so does this.

- **The refusal is bounded (revision 14, round-3 review).** `[sync_in_progress]` is advertised RETRYABLE, which is a lie unless the `syncing` state is guaranteed to end. See §18 for the three layers that now guarantee it (`_plusSyncDoneBody` state-before-side-effects ordering, `_plusSyncDone`'s `try/except/finally`, and the `core.SYNC_JOB_STALE_MS` reaper shared by the guard, `syncNow` and `syncStatus`). Before this, any exception in the completion callback refused all 23 guarded actions until Anki restarted.

**Test hook** (as locked, and no hidden params were added): the verify phase constructs a `PlusMixin` subclass and assigns `_plusSyncJobState` directly. No real sync, no network, no Qt. **That hook must now set a RECENT `startedMs`** — the reaper treats `startedMs: 1` (1970) as stale, and a `syncing` job with no `startedMs` at all as unaccountable. `headless_round3review_test.py` additionally drives the real state machine through each raising dependency (`_load_scheduler`, `set_host_number`, `window()`, `clear_sync_auth` on the auth path, an unclassified `future.result()` raise, and `mw.col is None`) and asserts the job never stays `syncing` and that a guarded action succeeds afterwards — the revision-13 test only set and cleared the state by hand, which is why this survived.

### 25.3 Argument-binding messages (spec revision 13)

Round-3 ASK 11b: CPython renders binding failures with the bound method's `__qualname__`, so `"PlusMixin.renderCard() missing 1 required positional argument: 'cardIds'"` — this add-on's internal class name — went out on the wire beside house-format text like `"invalid parameter: field: string required"`. `plus._normalize_arity_message` (applied in the `plus_api` wrapper's `tb_next is None` branch, so only true binding failures are touched) normalizes them:

| CPython | on the wire |
|---|---|
| `PlusMixin.renderCard() missing 1 required positional argument: 'cardIds'` | `[invalid_param] renderCard() missing required argument: cardIds` |
| `PlusMixin.f() missing 2 required positional arguments: 'find' and 'replace'` | `[invalid_param] f() missing required arguments: find, replace` |
| `PlusMixin.mediaExists() got an unexpected keyword argument 'bogus'` | `[invalid_param] mediaExists() unexpected keyword argument: bogus` |
| anything else (e.g. `got multiple values for argument 'self'`) | class qualifier stripped, remaining text kept verbatim |

The fallback row is the invariant: **no message keeps the class name**, whatever CPython invents. The code is still `invalid_param` in every case.

**Edge cases tests must cover (§§25.1–25.3)** — envelope: coded and uncoded exceptions, all four keys present at api version 6 **and** 4, `error` string unchanged, `retryable` agreeing with `PLUS_ERROR_CODES` for **every** code, success replies untouched; dispatcher: unknown action → `[unknown_action] unsupported action` + `errorCode`/`retryable`, the parse rule now working on it, api-key refusal and an upstream action error both unprefixed with `null`/`null`; `multi` sub-responses each a full four-key envelope with the outer reply still `error: null`; guard: all 23 guarded actions raise `[sync_in_progress]` from a bare call, the four exempt ones do not, `media_syncing`/`idle`/`done`/`error`/no-slot-at-all do not, `plusInfo` still answers mid-sync; arity: each row of the table above plus a message with no qualifier at all passing through untouched.

---

## 26. `undoStatus` (spec revision 12, 2026-08-12)

The round-3 field-feedback action, bringing the action count to **twenty-seven**. `core.PLUS_ACTIONS` remains the single source of truth for the `plusInfo` action list. **READ-ONLY**: `get_undo_status` is a backend RPC — no write, no undo-stack change; tests assert it bit-identical across calls. **Revision 14 (round-3 review): read `col._backend.get_undo_status()` DIRECTLY, not the `col.undo_status()` wrapper.** The wrapper is `self._check_backend_undo_status() or UndoStatus()` (`SP/anki/collection.py:1033-1035`) and `_check_backend_undo_status` (`:1080-1086`) returns `None` whenever BOTH `undo` and `redo` are empty — so the wrapper hands back a **synthesized default proto with `last_step = 0`**, silently breaking the one property this action exists to provide. Measured on a scratch collection: after `col.fix_integrity()` (Check Database) the backend reported `('', '', 1)` while `col.undo_status()` reported `last_step 0`; `col.decks.add_config()` (which upstream AnkiConnect's own `cloneDeckConfigId` calls, and Anki's deck-options UI does routinely) and `col.mod_schema()` clear the stack the same way. The backend call returns the identical `undo`/`redo` strings plus the TRUE counter.

Rationale (measured in real use): every write action REPORTS the undo entry it created (`undoEntry`, §24), but nothing let a caller OBSERVE the stack, so the entire undo contract had to be taken on trust — `undoEntry` is the API's own report, not observed truth. The reporter resorted to driving Anki's menu bar with AppleScript and was blocked by assistive-access permissions. This action closes that loop, and is also what makes §16.2's "always writes" behavior auditable.

**Params** — none.

**Returns**

```json
{"undo": "AnkiConnect Plus: Bulk Update", "redo": null, "lastStep": 34}
```

- `undo` / `redo`: what a single Undo / Redo would do right now, exactly as Anki's own menu labels them (locale-dependent for backend-named entries; Plus entries carry the §3.3/§24 names). The proto returns **empty strings** for "nothing to undo/redo" (never `None`, never a raise — probe-verified on a fresh collection: `('', '', 0)`); those are normalized to `null` here.
- `lastStep`: anki's monotonic undo-step counter (`UndoStatus.last_step`, uint32). It advances on every undoable operation — including an undo itself — so a caller can PROVE whether a call created a new entry (Deviation #11b). Monotonic **within a session**: clearing the stack (Check Database, a schema mod, adding a deck config) keeps the counter, it does not rewind it — which is precisely what revision 14 restored. Measured on a fresh collection: empty stack `0`; after Add Note `1`; after undoing it `2`; after a Plus custom entry `3`.
- Verification recipe: snapshot `lastStep`, run a write action, call `undoStatus` again — `undo` must equal the action's reported `undoEntry` and `lastStep` must have advanced; a no-op action (`undoEntry: null`) must leave both unchanged.

**Anki API calls** — `col._backend.get_undo_status() -> UndoStatus` (revision 14; the `col.undo_status()` wrapper at `SP/anki/collection.py:1033-1035` is deliberately BYPASSED, see above). `UndoStatus` is `collection_pb2.UndoStatus` with fields `undo: str`, `redo: str`, `last_step: uint32`. No SQL, no collection write; `core.py` already reaches for `_backend` the same way for `html_to_text_line`, `extract_latex` and `cloze_numbers_in_note`.

**Error cases** (codes per §25) — none of its own; `[collection_unavailable]` from the `plus_api` boundary when no profile is open. No params to validate.

**Edge cases tests must cover** — `lastStep` never goes BACKWARDS across a stack clear (`fix_integrity`, `decks.add_config`) and equals `col._backend.get_undo_status().last_step` there, while `col.undo_status()` would report `0` (revision 14); after a labeled write, `undo` equals the reported `undoEntry` and `redo` is `null`; two consecutive calls are equal and the undo snapshot is bit-identical (read-only proof); after `col.undo()` the entry moves to `redo` and `lastStep` advances; empty proto strings surface as `null`, never `""`; the action is registered in `PLUS_ACTIONS` (27, `plusInfo` still last) with a non-empty summary.

## 27. Suspension control (spec revision 15, 2026-08-18)

Two parameters, two config keys, **one deliberate behavior change** (Deviation #13). This is the first place the fork knowingly diverges from Anki's own semantics *by default*, so the whole contract is stated in one place and cross-referenced from §4.1, §15, §16.2, §6.1, both `plusInfo` summaries, the `suspended-draft workflow` recipe and the README.

### 27.1 Why

Anki's `set_due_date` turns every targeted card into a review card, which **silently clears suspension** (queue `-1`) and burial (`-2`/`-3`). Measured: 5 suspended cards → `bulkSetDueDate days: "5"` → all 5 at queue `2`, and before revision 12 the response said only `{"changed": 5}`. Revision 12 made that visible (`unsuspended`/`unburied`); it could not make it *stop*. The realistic disaster is unchanged by disclosure alone: suspend your leeches, later reschedule a deck-wide selection that happens to include them, and the next session hands back every leech you ever benched. Meanwhile the workflow this add-on exists to serve is *write-suspended → a human reads the draft → that human unsuspends*, and a bulk add that drops live cards straight into review breaks it on the way in. Hence: put suspension back on reschedule, and leave new cards suspended — both on by default, both switchable.

### 27.2 The two knobs

| action | param | config key | ships | effect when true |
|---|---|---|---|---|
| `bulkSetDueDate` (§16.2) | `preserveSuspended` | `preserveSuspendedOnReschedule` | `true` | Cards the call revived are re-suspended and reported in `resuspended`. |
| `bulkAddNotes` (§4.1) | `suspend` | `suspendNewCards` | `false` (revision 16; this row said `true` until the revision-18 sweep) | The batch's new cards are left suspended and reported in `suspended`. |

**Resolution order (identical for both): explicit parameter → config key → the constant in `core.py`.** `null`/omitted means "the caller said nothing" and only then is config read. `plus.py` does the config read through the same `util.setting()` accessor `webBindPort` uses and passes an explicit bool into `core`; `core.py` never reads config (it is aqt-free) but carries the documented default as `DEFAULT_PRESERVE_SUSPENDED_ON_RESCHEDULE` / `DEFAULT_SUSPEND_NEW_CARDS`, so a direct `core` call with the parameter omitted behaves exactly like the wire with a stock config — one default, not two. Fallbacks: a config.json predating these keys resolves through `util.DEFAULT_CONFIG`; an unreadable config (no `aqt.mw` yet) or a non-boolean value falls back to the core constant rather than failing the write. A non-boolean **parameter** is `[invalid_param]`, raised before any write or undo entry exists — config typos are forgiven, request typos are not. (Revision-15 fix pass: `bulkSetDueDate`'s `dryRun` is type-checked in the same place and for the same reason — see §15.) **Revision 18:** the RESOLVED values of both keys — and whether each came from the user's config or the shipped default — are served machine-readably as `plusInfo.effectiveConfig` (§31.3), computed through this very ladder, so a caller never has to infer the effective default from prose.

### 27.3 Undo merging (the part that must not be half-done)

Both actions perform their re-suspension as a **second op merged into the action's existing undo entry**: `target = col.add_custom_undo_entry(name)` before the first op, `col.merge_undo_entries(target)` after the first op, and `col.merge_undo_entries(target)` again after `col.sched.suspend_cards(...)`. Probe-verified on 25.09.4, both directions:

- `bulkSetDueDate`: suspend 3 → reschedule `"5"` → re-suspend → **one** `col.undo()` restores `(due, ivl, queue, type)` byte-identically for all three. Two separate entries would have left the cards rescheduled but live after a single Ctrl+Z — the exact half-reverted state this rule exists to prevent.
- `bulkAddNotes`: add 2 → suspend both cards → **one** `col.undo()` removes the notes AND their cards (`select count() from cards where id in (...)` → 0).

`undoEntry` in the response keeps reporting the single entry name, `undoLabel` (§24) still renames it, and the lazy-entry rules (§Deviation #7) are unchanged: nothing added → no entry, no suspend step.

### 27.4 What the response says

Both actions report **what happened**, never what was requested — the project's standing rule that the response IS the caller's only observation.

- `bulkAddNotes` → `suspended: [cardId]`, always present. Every card of every added note (`col.card_ids_of_note`, no raw SQL). Since every added note yields at least one card, `added` non-empty + `suspended: []` unambiguously means the policy was off — **unless the backend disagreed** (revision-15 fix pass): `suspend_cards`' `OpChangesWithCount.count` is compared against the ids passed, and on any mismatch the queues are re-read so `suspended` still reports post-op reality rather than the request. §16.1 keeps `bulkSuspend`'s `changed` backend-authoritative for exactly this reason; the same rule now applies here instead of trusting that freshly created cards are always queue `0`.
- `bulkSetDueDate` → `resuspended: [cardId]`, always present, **re-read from the post-op queues**. `unsuspended` keeps its revision-12 meaning (what anki revived *during* the call) even when the cards were immediately put back, so **cards left in review = `unsuspended` − `resuspended`**. `resuspended ⊆ unsuspended` always.
- Dry runs answer the same questions without writing: `wouldSuspend` (a bool — card ids do not exist yet) and `wouldResuspend` (§15).
- **Asymmetry, deliberate:** buried cards are disclosed in `unburied` and are **never re-buried**. Burial hides a card *for today*; you just moved its due date, so anki's unbury is the right outcome. Only suspension is restored.
- Failure of the re-suspension step reverts the whole batch and raises `[batch_reverted]` — for `bulkAddNotes` this overrides `atomic: false`, because handing back added-but-live notes under a success response is precisely the silent divergence this add-on refuses to ship.
- **…and "reverted" is a claim, so it is checked (revision-15 fix pass).** `_revert_batch` undoes only while the batch's entry is still on top of the undo stack; if `suspend_cards` succeeds and its `merge_undo_entries` raises, anki's own `"Suspend"` entry is on top and nothing rolls back. Both handlers now branch on `_revert_batch`'s return value and raise `[internal]` `"<action> failed (batch NOT reverted): {...}"` when the undo did not fire, naming what is still committed — `addedStillCommitted`/`addedIds` for `bulkAddNotes` (§4.1), `rescheduledStillCommitted` and a re-read `stillUnsuspended` for `bulkSetDueDate`. This section promises "failure of the re-suspension step reverts the whole batch"; when that promise cannot be kept, the response has to say so, because a caller told "reverted" retries and duplicates the writes.

### 27.5 Switching it off

Per call: `{"action": "bulkAddNotes", "params": {..., "suspend": false}}` / `{"action": "bulkSetDueDate", "params": {..., "preserveSuspended": false}}`. Permanently: set `"suspendNewCards": false` / `"preserveSuspendedOnReschedule": false` in `connect_plus/config.json` (Anki → Tools → Add-ons → AnkiConnect Plus → Config). Either restores stock Anki behavior exactly; nothing else in the two actions changes.

### 27.6 Tests

`tests/headless_suspension_test.py` (16 cases) covers: default-on for both actions; every card of a multi-card note suspended; `false` and explicit `None`; type checking before any write; the decision reported on every return path incl. empty and all-skipped batches; `undoLabel` interaction; single-undo restoration for both actions; the bury asymmetry; dry-run prediction matching the real run key for key with zero writes; the three-way config lockstep (`config.json` = `util.DEFAULT_CONFIG` = the `core` constants); and, through the real `plus.py` wrappers, param-over-config-over-default resolution, the older-config and unreadable-config fallbacks, a non-boolean config value, and the `plusInfo` discoverability surface (params, summaries naming the deviation and its switch-off, returns, recipe). Revision-15 fix pass adds two cases: **case 15** stubs the two failure shapes for both actions — `suspend_cards` raising (entry still on top → real revert → `[batch_reverted]`, note count and card rows back to baseline) versus `merge_undo_entries` raising after `suspend_cards` succeeded (anki's entry on top → no revert → `[internal]` `"batch NOT reverted"` naming what survived, asserted against the collection) — plus the backend-count cross-check (a stubbed `suspend_cards` that reports `count: 0` and suspends nothing must yield `suspended: []`, never the ids passed); **case 16** locks `core.PLUS_VERSION` / `core.PLUS_SPEC_REVISION` to this document's header line and to `plusInfo`'s `version` / `specRevision`. Suites amended for the deliberate default change: `headless_six_test` (fixtures opt out with `suspend=False`; new `wouldSuspend`/`resuspended` keys; the raw-resurrection block names `preserve_suspended=False` so its "anki stopped resurrecting" alarm still fires), `headless_media_undolabel_test` (same fixture opt-out + new key), `headless_report3_test` (ASK 5 asserts anki's native resurrection, so it names the opt-out).

## 28. Round-4 maintenance actions: `renameDeck`, `bulkSetFlag`, `renameTag` (spec revision 17, 2026-08-18)

Three actions from the round-4 field report (real maintenance of a 2,619-note class deck), bringing the action count to **thirty**. `core.PLUS_ACTIONS` remains the single source of truth for the `plusInfo` action list. The report's design principle, adopted here: *where the GUI can do something the API can't, the agent hands the job back to the human — and the human is the least reliable part of the loop.* All three expose an existing, verified backend op; none invents behavior. All three follow the §3.3 undo conventions (entry created before the op, merged after, ONE entry per call), take §24's `undoLabel`, ship §15 `dryRun` from birth (with `dryRun` itself type-checked as a real boolean, the revision-15-fix-pass standard), and raise §25-coded errors. New entry names: `"AnkiConnect Plus: Rename Deck"` / `"AnkiConnect Plus: Bulk Flag"` / `"AnkiConnect Plus: Rename Tag"`. No new config keys; no raw SQL anywhere in the three (deck/card/tag reads go through `col.decks` / `col.get_card` / `col.tags` / anki's own search).

### 28.1 `renameDeck`

Rename a deck **in place** — the whole subtree follows in one backend op. The field report's manual workaround (`createDeck` + `changeDeck` + `deleteDecks`) silently loses every subdeck's options-preset assignment (cards are scheduled by their deck's preset, so a forgotten re-point reset ~21 decks to Default and changed the scheduling of ~2,900 cards with no error), plus per-deck descriptions and collapse state. `col.decks.rename` keeps deck **ids stable**, so all of that survives by construction — and the response **re-checks it from the post-op decks anyway**, because a Plus response reports what HAPPENED, not what the mechanism implies.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `oldName` | str | required | Must exist (`col.decks.id_for_name`, which matches case-insensitively). The rename covers the deck **and every descendant**. |
| `newName` | str | required | The new full `::` path, **normalized** (fix pass): every `::` component must be non-empty with no leading/trailing whitespace, else `[invalid_param]` up front on both paths — the backend silently rewrites such names (strips padding, fills empty components with `blank`), which would make the dry-run prediction diverge from the landed name (§15). Renaming under an existing parent (`"A"` → `"Archive::A"`) is a **move** and is legal; missing intermediate parents are auto-created by the backend. A `newName` that resolves to any deck **other than the renamed deck itself** is refused with `[duplicate]` (see below). A byte-identical `newName` is a data no-op; a case-only respelling is a real rename. |
| `dryRun` | bool | `false` | Predict `wouldRename` and write nothing (§15). Type-checked: non-boolean → `[invalid_param]`. |
| `undoLabel` | str | `null` | §24. |

**Preserves (§31.1)** — everything about cards and notes (ids, scheduling, suspension, flags, tags, fields): only stored deck NAMES change; deck ids are stable, cards do not move, presets/descriptions/collapse state survive (post-checked).

**Returns**

```json
{"renamed": [{"from": "HA2::PI 7", "to": "HA2::PI 07"}, {"from": "HA2::PI 7::Labs", "to": "HA2::PI 07::Labs"}],
 "configPreserved": true, "cardsAffected": 214, "undoEntry": "AnkiConnect Plus: Rename Deck"}
```
- `renamed`: one pair per subtree member (root included, backend name-sorted parent-first order), `from` = the pre-op **stored** spelling, `to` = the post-op name **re-read from the collection by deck id** — never computed by string math, so the response stays truthful even in pathological self-nesting renames (`"A"` → `"A::B"` is backend-legal: missing parents are recreated, and the pairs report exactly what landed).
- `configPreserved`: an **actual post-check**, not an assumption — every subtree deck's options-preset id (`conf`) is snapshotted before and compared after; filtered subtree members (no `conf` key — embedded config) compare `None == None`. Structurally this is always `true` (ids are stable); it exists so a backend regression would be *reported*, not silently absorbed — the workaround's silent preset loss is the whole reason this action exists.
- `cardsAffected`: cards homed in **or currently visiting** the subtree (`col.decks.card_count(did, include_subdecks=True)`, which counts `did` OR `odid` — a card sitting in a filtered deck keeps its home here, and that home's name is what changes). Same value on dry and real runs (it is a pre-op read-only count, not a post-op observation, so it keeps its name in both shapes).
- Byte-identical `newName` → `{renamed: [], configPreserved: true, cardsAffected: 0, undoEntry: null}`, nothing written, undo stack untouched (dry: `{wouldRename: [], configWillBePreserved: true, cardsAffected: 0, undoEntry: null}`).
- `dryRun: true` → `{wouldRename: [{from, to}], configWillBePreserved: true, cardsAffected, undoEntry: null}` — `wouldRename` is a **prediction** from the pre-op names (suffix arithmetic against the stored root spelling), which is why it is renamed from `renamed` (an observation). **`configWillBePreserved` (revision 18, §31.4)** is a **static contract statement**, always `true`: preset/description/collapse survival is a property of the in-place rename path itself (deck ids are stable across it), NOT a post-check — the real run's `configPreserved` is the post-check; the dry key exists so the state-preservation decision is visible in the dry run too, and the different key name marks the different epistemic status. **Key sets side by side:** real `{renamed, configPreserved, cardsAffected, undoEntry}` / dry `{wouldRename, configWillBePreserved, cardsAffected, undoEntry: null}`. The `[duplicate]`/`[deck_not_found]`/`[invalid_param]` refusals fire on the dry path too, so the prediction is exactly what the real call would land (fix pass: un-normalized `newName` is refused rather than predicted un-normalized).

**The `[duplicate]` refusal (deliberately stricter than the backend; tightened in the fix pass)** — anki's own `rename` silently auto-renames an occupied target (probe-verified: renaming onto `"Occupied"` lands as `"Occupied+"`). An agent renaming decks in a deck it ships to classmates must not discover that from the deck list later, so every predicted target name (root and descendants; index-aligned with the subtree snapshot) is checked with `col.decks.id_for_name`; a hit resolving to **any deck other than that pair's own** raises `[duplicate]` `"deck already exists: <name>"` before any write — the renamed subtree's own members included, because renaming `"A"` onto its own child `"A::B"` otherwise rides the backend's ensure-unique auto-`+` (probe-verified: lands `"A::B+"`/`"A::B+::B"` while the dry-run predicted `"A::B"`, the exact silent divergence this refusal exists to prevent). The only legal resolution is the pair's own deck — a case-only respelling (`id_for_name` matches case-insensitively); clean self-nesting (`"A"` → `"A::B"` with no existing `A::B`) stays legal because every predicted target resolves to `None`. This makes the previously RESERVED `duplicate` code REACHABLE — §25 table updated.

**Anki API calls** — `col.decks.id_for_name(oldName)`; `col.decks.deck_and_child_name_ids(did)` (pre-op subtree snapshot: stored spellings + stable ids); `col.decks.card_count(did, include_subdecks=True)`; `col.decks.get(deck_id, default=False)` (pre/post `conf` + post names); `col.decks.rename(did, newName) -> OpChanges` (`SP/anki/decks.py:271`, docstring "Rename deck prefix to NAME if not exists. Updates children."; `reparent` is not needed — `rename` takes a full `::` path and moves/renames in one op); undo per §3.3.

**Error cases** (codes per §25) — `[invalid_param]` `"invalid parameter: oldName: string required"` / `"invalid parameter: newName: string required"` / `"invalid parameter: newName: every \"::\" component must be non-empty with no leading/trailing whitespace: <repr>"` (fix pass) / `"invalid parameter: dryRun: boolean required"`; `[deck_not_found]` `"deck was not found: <oldName>"`; `[duplicate]` `"deck already exists: <predicted target>"`; unexpected op failure → `[batch_reverted]` `"renameDeck failed (batch reverted): <err>"`.

**Edge cases tests must cover** — parent+child+grandchild with a custom preset, a description and collapse state on the child: rename the parent → all three pairs reported, `configPreserved: true` with the preset id really unchanged, description intact, ONE undo entry named `"AnkiConnect Plus: Rename Deck"`, single `col.undo()` restores every name; dryRun predicts the identical pairs with `undo_status()` bit-identical and no name changed; occupied `newName` (and a descendant collision) → `[duplicate]`, nothing renamed; a `newName` equal to an existing DESCENDANT of the renamed deck → `[duplicate]` on the dry path and the real path (fix pass: pairwise self-identity, no silent auto-`+`); clean self-nesting (`"A"` → `"A::B"` with no existing `A::B`) still lands; padded (`"X "`) and empty-component (`"X::"`) `newName` → `[invalid_param]` on both paths with nothing written (fix pass); case-only rename lands (`"alpha"` → `"ALPHA"`, no `+` suffix); byte-identical no-op shape; missing `oldName` → `[deck_not_found]`; move under an existing parent works; `undoLabel` honored; `cardsAffected` counts subtree cards.

### 28.2 `bulkSetFlag`

Set or **clear** (`flag: 0`) the colored flag on many cards as one undoable batch. Flags are the user→agent channel (a human flags cards during review, the agent fixes them) — but stock AnkiConnect has no sanctioned write: the inbox never empties (the report counted 13 resolved cards still red). Stock's only route is `setSpecificValueOfCard`, whose own docs warn against it, and which clobbers the whole `flags` byte via `update_card(skip_undo_entry=True)` — no undo entry at all.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `cardIds` | [int] | required | Deduplicated (first occurrence wins); unknown ids silently dropped — the §16 precheck contract. |
| `flag` | int | required | `0`–`7`; `0` clears. Bools and out-of-range ints → `[invalid_param]` **before any write** (the backend rejects `8` itself but negatives die inside pyo3, so the range is pre-validated here). |
| `dryRun` | bool | `false` | Predict the split, write nothing (§15). Type-checked. |
| `undoLabel` | str | `null` | §24. |

**Returns**

```json
{"updated": [1712345678901], "unchanged": [1712345678902], "undoEntry": "AnkiConnect Plus: Bulk Flag"}
```
- `updated` / `unchanged`: split from the cards' **real pre-op flags** (`col.get_card(cid).user_flag()`, i.e. `flags & 0b111`) — `unchanged` means "already carried exactly this flag", so a repeat call is a reported no-op: `{updated: [], unchanged: [...], undoEntry: null}` with nothing written and the undo stack untouched.
- Only the pending cards are passed to the op. The backend (`OpChangesWithCount`) no-op-detects on its own; its count is cross-checked against the precheck, and on a (never-observed) disagreement `updated` is **re-read from the post-op flags** — the report names the cards that really carry the flag now, never the ask (§27.4 precedent).
- `dryRun: true` → `{wouldUpdate: [cardId], unchanged, undoEntry: null}`.

**Anki API calls** — `col.get_card(cid)` precheck (`NotFoundError` → drop) + `Card.user_flag()` (`SP/anki/cards.py:232`); `col.set_user_flag_for_cards(flag, pending) -> OpChangesWithCount` (`SP/anki/collection.py:1113`, backend `set_flag` — writes only the user-flag bits); undo per §3.3.

**Error cases** (codes per §25) — `[invalid_param]` `"invalid parameter: flag: integer 0-7 required"` / `"invalid parameter: cardIds: ints required"` / `"invalid parameter: dryRun: boolean required"`; unexpected op failure → `[batch_reverted]` `"bulkSetFlag failed (batch reverted): <err>"`.

**Edge cases tests must cover** — flag 3 cards (+1 bogus id, +1 duplicate) → `updated` names exactly the three, flags really `2`, ONE entry `"AnkiConnect Plus: Bulk Flag"`, single `col.undo()` restores the old flags; repeat → all `unchanged`, `undoEntry: null`, `undo_status()` bit-identical; partial pre-flagged split; `flag: 0` clears; `8` / `-1` / `true` → `[invalid_param]` with nothing written; dryRun split matches the following real run with zero writes; `undoLabel` honored.

### 28.3 `renameTag`

Rename or move a tag **and its `::` subtree** with anki's own segment-aware op. The report asked for this fearing stock `replaceTagsInAllNotes` corrupts `lab10` when renaming `lab1` → `lab01`; triage showed stock's matching is exact-whole-tag (no prefix corruption) but found its real defects: **children are silently stranded** (`lab1::sub` keeps the old parent), it writes per note with `skip_undo_entry=True` (**no undo at all**), and it loops the whole collection in Python. `col.tags.rename` fixes all three: segment-aware (`lab1` → `lab01` rewrites `lab1` and `lab1::*`, never `lab10` — probe: `x::lab10` byte-untouched), subtree-aware, one backend op, one undo entry.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `oldTag` | str | required | A single tag, no spaces (anki splits tags on whitespace, U+3000 included — a spacey value can never name one stored tag). Matched **case-insensitively** (backend unicase; a note tagged `X::LAB1` is renamed by `oldTag: "x::lab1"`). No stored tag matching → `[not_found]` — a typo'd `oldTag` must fail loudly, never "succeed" renaming nothing. |
| `newTag` | str | required | Single tag, no spaces (pre-validated; the backend's own `InvalidInput` for a space is kept as a drift backstop). Renaming **onto an existing tag merges the trees** (backend behavior, deliberate — disclosed in `merged`). Byte-identical to `oldTag` → data no-op; case-only respelling is a real rename. |
| `dryRun` | bool | `false` | Preview the exact pairs, write nothing (§15). Type-checked. |
| `undoLabel` | str | `null` | §24. |

**Returns**

```json
{"notesUpdated": 3, "tagsRewritten": [{"from": "x::lab1", "to": "x::lab01"}, {"from": "x::lab1::sub", "to": "x::lab01::sub"}],
 "merged": [], "undoEntry": "AnkiConnect Plus: Rename Tag"}
```
- `notesUpdated`: the backend's **own** changed-note count (`OpChangesWithCount`), not a re-derivation.
- `tagsRewritten`: **re-read from the post-op tag registry** (`col.tags.all()`), so it reports the spellings that actually landed — on a merge the EXISTING spelling wins (rename `lab1` → `Lab01` when `lab01` is registered stores `lab01`), and the pair says so. `from` values are the pre-op stored spellings, case included.
- `merged`: pre-existing tags this rename folded into (pair targets that already existed outside the renamed set, matched case-insensitively). Pre-op observation, same value on dry and real runs.
- **Registered-but-unused matches** (a "ghost" tag left registered after its notes were deleted): the backend renames only note-carried tags (probe-verified: registry byte-unchanged, count 0). Detected **before any undo entry exists** via anki's own search (`col.find_notes(col.build_search_string(SearchNode(tag=oldTag)))` — its writer escapes hostile tag names, its matcher is the same unicase engine, and `tag:X` matches `X` and `X::*`); an all-ghost match returns `{notesUpdated: 0, tagsRewritten: [], merged, undoEntry: null}` with `undo_status()` bit-identical (popping an empty custom entry afterwards would push a phantom Redo item — the §16.2 hazard). A mixed match proceeds; ghost pairs simply do not appear in `tagsRewritten`.
- `dryRun: true` → `{notesUpdated: int, wouldRewrite: [{from, to}], merged, undoEntry: null}` — **the preview that proves prefix safety**: for `lab1` → `lab01` it lists `lab1` and `lab1::*` only, never `lab10` (test-locked). It is a prediction: pair targets use casefold matching (the closest python mirror of unicase — the documented `canonify_tags` approximation; subtree cut points are located on the stored tag's own `::` separators, so a casefold length drift can never mis-slice), and ghost pairs that survive the gate in a mixed batch will not be rewritten by the real run. **Dry `notesUpdated` (revision 18, §31.4)**: the count of notes CARRYING the affected tags — `len(col.find_notes(...))` from the very tag search the ghost gate already runs (`tag:X` matches `X` and `X::*`), so it costs no extra read and writes nothing. It PREDICTS the real run's backend changed-note count; rust-unicase vs python-casefold drift is the only way they can differ (the same documented approximation `wouldRewrite` carries). The no-op and all-ghost dry shapes report `notesUpdated: 0`. **Key sets side by side:** real `{notesUpdated, tagsRewritten, merged, undoEntry}` / dry `{notesUpdated, wouldRewrite, merged, undoEntry: null}`.

**Preserves (§31.1)** — note fields, ids, GUIDs, every card's scheduling/suspension/flags/deck, and every OTHER tag on the affected notes: only the matched tag and its `::` subtree are rewritten.

**Anki API calls** — `col.tags.all()` (pre-op pair computation + post-op observation); `col.find_notes` / `col.build_search_string` / `anki.collection.SearchNode(tag=...)` (the ghost gate — read-only search, no SQL); `col.tags.rename(oldTag, newTag) -> OpChangesWithCount` (`SP/anki/tags.py:95`, backend `rename_tags(current_prefix, new_prefix)`); undo per §3.3.

**Error cases** (codes per §25) — `[invalid_param]` `"invalid parameter: oldTag: string required"` / `"invalid parameter: oldTag: a single tag (no spaces) required"` (same pair for `newTag`) / `"invalid parameter: dryRun: boolean required"` / `"invalid parameter: newTag: <backend message>"` (the `InvalidInput` backstop); `[not_found]` `"tag was not found: <oldTag>"`; unexpected op failure → `[batch_reverted]` `"renameTag failed (batch reverted): <err>"`.

**Edge cases tests must cover** — the prefix-safety lock: notes tagged `x::lab1`, `x::lab1::sub`, `x::lab10`, `X::LAB1` → rename `x::lab1` → `x::lab01`: dry `wouldRewrite` lists exactly the two pairs (NEVER `x::lab10`), real run reports `notesUpdated: 3` with `x::lab10` byte-untouched and the `X::LAB1` note rewritten (case-insensitive match), ONE entry `"AnkiConnect Plus: Rename Tag"`, single `col.undo()` restores the registry; merge onto a pre-existing `x::lab01` → `merged: ["x::lab01"]` on dry and real; ghost tag (register, delete note) → the no-write shape with `undo_status()` bit-identical; `[not_found]` for a missing tag; spacey `newTag` → `[invalid_param]` with the undo stack untouched; case-only rename lands; byte-identical no-op; `undoLabel` honored.

### 28.4 Tests

`tests/headless_round4_test.py` covers the three actions' edge-case lists above end to end on a scratch collection (subtree rename with preset/description survival + single-undo restore, the `[duplicate]` refusal, flag split/no-op/clear/undo, the `lab1`/`lab10` prefix-safety lock, merge disclosure, the ghost gate's bit-identical undo snapshot, every dry run's zero-write proof, `undoLabel` on all three) plus the lockstep surface (action count 30, summaries/returns/actionDocs present, wrapper signatures, `duplicate` reachable in `PLUS_ERROR_CODE_DOCS`). The pre-existing count locks in `headless_feedback_test` / `headless_errorcodes_diff_test` / `headless_media_undolabel_test` / `headless_seven_test` / `headless_report3_test` / `headless_sync_ankihub_test` move 27 → 30, and `headless_errorcodes_diff_test`'s reserved-code set drops `duplicate` — both deliberate revision-17 contract changes. (With slice 2 — §§29–30 — landed, the same locks moved again, 30 → **34**; the new `cards_in_filtered_decks` code is born reachable, so the reserved set is unchanged by it.)

## 29. Filtered-deck safety: `filteredDeckReport`, `emptyFilteredDeck`, and the `exportDeckApkg` fail-closed amendment (spec revision 17 slice 2, 2026-08-18)

The highest-stakes ask of the round-4 field report: a deck-scoped `.apkg` export **silently omitted 141 cards / 96 notes** that were sitting in a filtered deck when the report's author exported a class deck — caught by hand-counting, not by any error. Root cause (probe-verified on 25.09.4): the backend's `DeckIdLimit` gather ships a note iff **at least one of its cards has `did` inside the export subtree**; a card visiting a filtered deck carries `did` = filter / `odid` = home, so it does not count as present. Notes whose every card is filtered **vanish**; a shipped note's filtered sibling exports with `did` = filter, and the importer recreates that filter as a REGULAR deck with the card **scheduling-reset** (measured: review card `type=2/ivl=5` → new card `type=0/due=1`). No API could even empty a filtered deck — the GUI's Empty button had no equivalent, which is exactly the report's design principle failing: the human was the only actor who could do the safe thing, and the human is the least reliable part of the loop.

Two new actions + one deliberate behavior change (§17, §0 Deviation #14). Both actions follow §3.3 undo conventions where they write, take §24's `undoLabel` and §15's `dryRun` where they write, and raise §25-coded errors. New entry name: `"AnkiConnect Plus: Empty Filtered Deck"`. No new config keys. Card-location selects (`did`/`odid`) are read-only and explicitly allowed by the §0 HARD-RULES bullet, which names this section. **Revision 19 (§32) adds the build half of the same lifecycle — `createFilteredDeck` / `rebuildFilteredDeck`; §29's two actions are its census (`filteredDeckReport`) and remediation (`emptyFilteredDeck`) halves.**

### 29.1 `filteredDeckReport`

Read-only census: which filtered decks hold whose cards right now. Unscoped it answers "what filtered decks exist and what is in them"; scoped to a home deck it is **the pre-export probe** — its `totalCards` is the home-side count `exportDeckApkg`'s fail-closed check trips on, and its rows name the decks to pass to `emptyFilteredDeck`. (The export check's second flagged set — foreign-homed cards sitting in filters nested inside the scope, fix pass — is not in a home-scoped `totalCards`; the unscoped report shows those filters' rows.)

**Params**

| name | type | default | notes |
|---|---|---|---|
| `deckName` | str | `null` | `null`: every filtered deck in the collection, empty ones included (their existence is the information). A **regular** deck: scope to cards whose HOME deck (odid) lies in that subtree — rows holding none of those cards are dropped (scoped mode reports *exposure*, not existence). A **filtered** deck: just that deck's full row (a filter has no children and never appears in `odid`, so subtree-scoping it would always report nothing — the useful reading is the deck's own row). Missing → `[deck_not_found]`. |

**Returns**

```json
{"filteredDecks": [{"filteredDeck": "Cram", "filteredDeckId": 1723456789012, "cardCount": 5,
                    "homeDecks": {"HA2::PI 7": 3, "HA2::PI 8": 2}}], "totalCards": 5}
```
- One row per filtered deck, **name-sorted**. `cardCount` = cards currently in it (scoped: only the scoped ones); `homeDecks` = `{home deck name: count}` from the cards' `odid`. A home name of `"[no deck]"` is anki's own label for a dangling `odid` (database damage, surfaced not hidden); name-aggregation guards two such rows from clobbering each other.
- Read-only: no undo entry, `undo_status()` byte-identical (test-locked).

**Anki API calls / SQL** — `col.decks.all()` (`dyn` truthy = filtered), `col.decks.id_for_name`, `col.decks.is_filtered`, `col.decks.deck_and_child_ids`, `col.decks.name`; per filter `select odid, count() from cards where did = ? [and odid in (<scope>)] group by odid` (read-only card-location selects, §0 allowlist).

**Error cases** — `[invalid_param]` `"invalid parameter: deckName: string required"`; `[deck_not_found]` `"deck was not found: <name>"`.

**Edge cases tests must cover** — unscoped report lists every filter incl. an empty one (`cardCount: 0, homeDecks: {}`) name-sorted; scoped report drops filters holding none of the scope's cards, counts only in-scope cards of shared filters, and its `totalCards` equals the export check's home-side count; a filtered `deckName` returns exactly its own row; `[deck_not_found]`; read-only proof.

### 29.2 `emptyFilteredDeck`

**Preserves (§31.1)** — note content, tags, flags, ids, intervals, and the cards' HOME deck assignment (going home IS the operation: `did=odid`, `odid=0`, scheduling intact). NOT preserved: filtered-deck residency and the filter's temporary due override.

Send every card in ONE filtered deck back to its home deck — the API equivalent of the filtered deck's own **Empty** action. Cards return to `did = odid`, `odid = 0`, scheduling intact (`col.sched.empty_filtered_deck`, the same backend op the GUI button calls). This is the remediation step the §17 refusal points at.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `deckName` | str | `null` | Exactly ONE of `deckName`/`deckId` (both or neither → `[invalid_param]`). Case-insensitive lookup. |
| `deckId` | int | `null` | For callers holding ids from `filteredDeckReport`. Bool is not an int. |
| `dryRun` | bool | `false` | §15. Predict `wouldReturn`/`homeDecks`, write nothing. Type-checked. |
| `undoLabel` | str | `null` | §24. |

**Returns**

```json
{"returned": 5, "homeDecks": {"HA2::PI 7": 3, "HA2::PI 8": 2}, "undoEntry": "AnkiConnect Plus: Empty Filtered Deck"}
```
- `returned`: the cards actually sent home — the pre-op residency count **cross-checked against the post-op count** of cards still in the filter (the op returns plain `OpChanges`, no count, so the observation is ours; on a never-observed disagreement `returned` reports the difference, not the ask).
- `homeDecks`: where they went, read from the cards' `odid` BEFORE the op (afterwards `odid` is 0 and the information is gone).
- **Already-empty filter is a data no-op**: `{returned: 0, homeDecks: {}, undoEntry: null}` with nothing written. This is gated BEFORE any undo entry exists, deliberately: the backend happily creates an undo entry for an empty op (probe-verified `+1` step), and popping an empty custom entry afterwards would push a phantom Redo item — the §16.2 hazard, answered the same way as `renameTag`'s ghost gate.
- `dryRun: true` → `{wouldReturn: int, homeDecks, undoEntry: null}`.
- ONE undo entry; a single `col.undo()` puts every card back into the filter (test-locked).

**Anki API calls / SQL** — `col.decks.id_for_name` / `col.decks.get`; `dyn` check (pre-checked so the refusal is §25-coded and no undo entry ever exists; the backend's own `FilteredDeckError` — `"This action can only be used on a filtered deck."` — stays as a drift backstop inside the try, surfacing as `[batch_reverted]`); `select odid, count() from cards where did = ? group by odid` (pre-op breakdown) + `select count() from cards where did = ?` (post-check); `col.sched.empty_filtered_deck(did) -> OpChanges` (`SP/anki/scheduler/base.py:123`); undo per §3.3.

**Error cases** — `[invalid_param]` `"invalid parameter: exactly one of deckName/deckId is required"` / `"invalid parameter: deckName: string required"` / `"invalid parameter: deckId: integer required"` / `"invalid parameter: dryRun: boolean required"`; `[deck_not_found]` `"deck was not found: <name or id>"`; `[validation_error]` `"deck is not a filtered deck: <stored name>"`; unexpected op failure → `[batch_reverted]` `"emptyFilteredDeck failed (batch reverted): <err>"`.

**Edge cases tests must cover** — filter holding cards from two home decks: dry predicts `{wouldReturn, homeDecks}` with `undo_status()` bit-identical, real call returns the same numbers, cards really back home (`did = odid`, `odid = 0`), ONE entry, single undo restores the filter, `undoLabel` honored; by-`deckId` path; already-empty filter → no-write shape with `undo_status()` bit-identical; regular deck → `[validation_error]`; missing name and missing id → `[deck_not_found]`; both/neither params → `[invalid_param]`.

### 29.3 `exportDeckApkg` fail-closed (the behavior change)

Contract text lives in §17 (params/returns/errors/order); §0 Deviation #14 carries the design rationale. Mechanics pinned here:

- **Detection** (after deck resolution, before ANY filesystem work): `scope = col.decks.deck_and_child_ids(did)`; home-side flagged cards = `select did, count() from cards where odid != 0 and odid in (<scope>) group by did` (per-filter counts; `odid != 0` is belt-and-braces — a plain card's `odid` 0 can never equal a real deck id, but the intent must not depend on that). Foreign-side flagged cards (fix pass) = with `filters_in_scope = [x for x in scope if x != did and col.decks.is_filtered(x)]`, when non-empty: `select did, count() from cards where did in (<filters_in_scope>) and odid not in (<scope>) group by did` (root excluded — see the filtered-deck-by-name bullet; the `odid not in` form also nets a corrupt `odid` 0 row, which is genuinely homeless). Vanishing notes = `select count() from (select nid from cards where odid != 0 and odid in (<scope>) and nid not in (select nid from cards where did in (<scope>)) group by nid)` — cards in IN-scope filters keep an in-scope `did`, so their notes correctly never count as vanished (they ship; that is the foreign set's damage class).
- **Semantics**: the home-side set is "any card whose HOME deck is in scope while it sits in a filtered deck" — vanish (every card in out-of-scope filters) + scheduling-reset, both starting from the same displacement; `notesOmitted` separates the vanish class because that is the unrecoverable one. The foreign-side set (fix pass) is "any card sitting in a filtered deck nested inside the scope whose HOME is outside it" — those notes do NOT vanish: they SHIP, scheduling-reset, into the filter recreated as a regular deck, which is the recreated-deck damage class arriving with someone else's content (behaviorally proven: filtered child `EA::Cram` holding a card homed in `EZ` exported the EZ note into a regular `EA::Cram`). Same refusal code, sibling warning code `foreign_cards_in_scope_filters`.
- **Exporting a filtered deck by name** is out of the guard's scope by construction: `scope` is then the filter's own id, no card's `odid` ever names a filtered deck (home side), and the export ROOT is excluded from `filters_in_scope` (foreign side; filtered decks cannot nest, so a filtered root has no children either way) — the guard protects home-deck exports, which is where the field failure happened. (Exporting a filter directly ships its visiting cards' notes; that is an explicit choice with its own semantics, not a silent omission.)
- The check runs **whether or not** `allowFilteredOmission` is set (the `warnings` payload needs its numbers), costs at most three indexed selects (the foreign select only runs when the scope actually nests filtered decks), and changes nothing for clean collections except the constant-true `warnings: []` key.

### 29.4 Tests

`tests/headless_round4b_test.py` covers §29 end to end on a scratch collection (report unscoped/scoped/filtered-name/read-only, empty with both selectors + dry + no-op gate + undo/redo + label, export refusal with zero filesystem trace, allowed export with `warnings` verified against a real import of the package, clean-after-empty loop, the fix pass's nested-foreign fixture — refusal, allowed export shipping the foreign note, filtered-root export legality — verified by import) — see §30.3 for the shared suite note.

## 30. Empty cards: `getEmptyCards`, `deleteEmptyCards` (spec revision 17 slice 2, 2026-08-18)

Round-4 ASK 3: `checkDeckIntegrity` **detects** the Empty Cards condition (`clozeCardMismatch`, §20) but nothing could **act** on it — the human had to click Tools > Empty Cards, read a localized HTML list, and click Delete. These two actions are that dialog as an API: the same backend report (`col.get_empty_cards()`), the same removal op (`col.remove_cards_and_orphaned_notes`), and the same protection its shipped default applies (`keep_notes` ships CHECKED in `aqt/emptycards.py`: an all-empty note keeps `card_ids[0]` and the note survives). New entry name: `"AnkiConnect Plus: Delete Empty Cards"`. No new config keys. The report's `card_ids` order is the backend's own — the dialog keeps `card_ids[0]`, so that order IS the protection contract and is preserved, never re-sorted.

### 30.1 `getEmptyCards`

**Params** — `deckName` (str, default `null`): `null` = collection-wide (the dialog's scope); a deck name scopes to notes with **at least one empty card homed in that subtree** (odid-aware, same home rule as §20's scope select). A listed note still reports ALL its empty cards — deletion acts per note and empty siblings can sit in other decks (cloze siblings are movable). Missing → `[deck_not_found]`.

**Returns**

```json
{"notes": [{"noteId": 1712345678901, "ords": [1], "willDeleteCards": [1712345678955], "protectedCard": null},
           {"noteId": 1712345678902, "ords": [0, 1], "willDeleteCards": [1712345678957], "protectedCard": 1712345678956}],
 "total": 2}
```
- One entry per note with empty cards, in anki's own report order. `ords` = the empty cards' template/cloze ordinals, aligned with the note's empty cards in the backend's order. `willDeleteCards` = exactly what `deleteEmptyCards` would delete. `protectedCard` is non-null **iff every card of the note is empty** (the proto's `will_delete_note`): that first card would be kept — its ordinal is `ords[0]`, and it appears in no `willDeleteCards`. `total` = notes listed.
- Read-only, probe-verified: `col.get_empty_cards()` leaves `undo_status()` byte-identical and is stable across calls.

**Anki API calls / SQL** — `col.get_empty_cards() -> EmptyCardsReport` (`SP/anki/collection.py:620`; proto `{report: html, notes: [{note_id, card_ids, will_delete_note}]}` — the HTML is the dialog's rendering and is deliberately NOT returned); chunked (`SQL_IN_CHUNK`) `select id, ord, (case when odid != 0 then odid else did end) from cards where id in (…)` for ords + odid-aware homes (§0 allowlist); `col.decks.id_for_name` / `deck_and_child_ids` for the scope.

**Error cases** — `[invalid_param]` `"invalid parameter: deckName: string required"`; `[deck_not_found]` `"deck was not found: <name>"`.

### 30.2 `deleteEmptyCards`

**Preserves (§31.1)** — the notes themselves (never deleted — post-checked as `notesPreserved`; an all-empty note keeps its first card), every non-empty card, and every surviving card's scheduling/suspension/flags/deck; fields, tags, ids, GUIDs untouched. Deletes exactly the reported empty card ids, nothing else.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `noteIds` | [int] | `null` | `null`: everything the live report finds (the dialog's Delete button). Explicit ids: deduplicated, first occurrence wins; ids the report does not cover land in `skipped` — `"no empty cards"` (note exists, nothing empty) or `"note was not found"` — keyed `noteId`, the §21 precedent, never silently dropped. |
| `dryRun` | bool | `false` | §15. Preview the exact card ids, write nothing. Type-checked. |
| `undoLabel` | str | `null` | §24. |

**Returns**

```json
{"cardsDeleted": 2, "deletedCardIds": [1712345678955, 1712345678957], "notesAffected": 2,
 "protected": [{"noteId": 1712345678902, "cardId": 1712345678956}], "notesPreserved": true,
 "skipped": [], "undoEntry": "AnkiConnect Plus: Delete Empty Cards"}
```
- **The protection rule (the dialog's own, always on)**: an all-empty note keeps `card_ids[0]` — listed in `protected` as `{noteId, cardId}` — and the note itself is never deleted (`remove_cards_and_orphaned_notes` only removes a note when its LAST card goes, which the protection makes impossible). `notesPreserved` is an **actual post-check** that every protected note still exists (the `configPreserved` precedent, §28.1): structurally always `true`; it exists so a backend regression would be reported, not absorbed. Corollary (test-locked): a protected note REAPPEARS in later reports — its kept card is still empty — exactly as anki's own dialog behaves with keep-notes on; repeat calls are reported no-ops, never an error loop.
- `cardsDeleted`/`deletedCardIds`: the backend's `OpChangesWithCount.count` cross-checked against the ids passed; on a (never-observed) disagreement the survivors are re-read and the response reports the cards really gone (§27.4 precedent), with `notesAffected` recomputed to match.
- `notesAffected` = notes that lost at least one card. A note whose ONLY empty card is its protected last card contributes nothing to `cardsDeleted` and is **not** `skipped` — its report is the `protected` entry (every requested note lands in exactly one story: deleted-from, protected-only, or skipped).
- **Data no-op** (no empty cards at all, only protected last cards, or every requested id skipped): `{cardsDeleted: 0, deletedCardIds: [], notesAffected: 0, protected, notesPreserved: true, skipped, undoEntry: null}` — nothing written, undo stack untouched.
- `dryRun: true` → `{wouldDelete: [cardId], notesAffected, protected, skipped, undoEntry: null}` — the ids are knowable pre-op, so the dry key is the id list itself.
- ONE undo entry; a single `col.undo()` restores every deleted card and the report reproduces byte-identically (probe-verified).

**Anki API calls / SQL** — `col.get_empty_cards()` (fresh at call time — a stale caller-side report cannot be replayed); `col.get_note(nid)` (`NotFoundError` → the skip reason split); `col.remove_cards_and_orphaned_notes(card_ids) -> OpChangesWithCount` (`SP/anki/collection.py:611`, the dialog's own op); chunked existence selects for the disagreement path and the `notesPreserved` post-check (§0 allowlist); undo per §3.3.

**Error cases** — `[invalid_param]` `"invalid parameter: noteIds: ints required"` / `"invalid parameter: dryRun: boolean required"`; unexpected op failure → `[batch_reverted]` `"deleteEmptyCards failed (batch reverted): <err>"`.

**Edge cases tests must cover** — the three-shapes fixture (partial-empty cloze, all-empty single-card note, all-empty two-card note in another deck): report lists all three with correct `ords`/`willDeleteCards`/`protectedCard`, read-only proof, deck scoping in and out incl. the all-cards-reported rule for a scoped note; dry run predicts the exact ids with `undo_status()` bit-identical; real run deletes exactly them, all notes alive, protected cards alive, `notesPreserved: true`, ONE entry, single undo restores the report; noteIds path: protected-only note → no-write shape with the `protected` entry; clean note → `skipped: "no empty cards"`; bogus id → `skipped: "note was not found"`; duplicates deduplicated; empty-card sibling sitting in a FILTERED deck still reported (odid-aware home) and deletable; validation errors with nothing written; `undoLabel` honored.

### 30.3 Tests

`tests/headless_round4b_test.py` (shared with §29) covers both edge-case lists end to end plus the slice-2 lockstep surface: action count **34** (with revision 19 the same locks moved again, 34 → **36**), summaries/returns/actionDocs for the four new actions and the amended `exportDeckApkg`, wrapper signatures, `cards_in_filtered_decks` present + reachable + non-retryable in the vocabulary, `warnings: []` on a clean export, and the two new recipes (`safe deck export`, `empty-cards cleanup`) served by `plusInfo`. The pre-existing count locks (§28.4 list) move 30 → **34**; `headless_round4_test`'s own count lock moves with them; the SPEC header version moves 1.2.0 → **1.3.0** and the `headless_suspension_test` version lockstep parses it.

## 31. Preservation contract: `preserves`, post-checks, `effectiveConfig`, dry-run parity (spec revision 18, 2026-08-18)

Round-5 field feedback, one through-line: **a default that changes state is a decision the API made on the caller's behalf — it must be visible in the dry run and correct in the docs.** Revision 18 is the mirror image of that rule applied to writes generally: a caller must be able to see what a write will NOT touch (§31.1), have the two claims most worth distrusting verified per call (§31.2), read the resolved defaults machine-readably instead of inferring them from prose (§31.3), and see every state-preservation decision in the dry run too (§31.4). No behavior changes; every new key is additive; `PLUS_VERSION` 1.3.0 → **1.3.1** (patch — the minor is reserved for default-behavior changes).

### 31.1 `preserves` — the per-action non-effects registry

Every **side-effectful** action's `actionDocs` entry carries a fourth key, `preserves` (`core.PLUS_ACTION_PRESERVES`, served verbatim by `plusInfo` — this table is its SPEC mirror): what the action does **not** touch among scheduling (due/interval/queue), suspension, flags, tags, note ids, GUIDs, deck assignment — with the genuine NON-preservations named in the same breath, because an untrue `preserves` claim is worse than none. Every claim below is verified against the code path or probed on 25.09.4 (probes locked in `tests/headless_round5_test.py`). Read-only actions (`getImageOcclusionNote`, `queryRevlog`, `renderCard`, `notesSlim`, `mediaThumbnails`, `mediaExists`, `syncStatus`, `ankihubStatus`, `checkDeckIntegrity`, `undoStatus`, `filteredDeckReport`, `getEmptyCards`, `plusInfo`) carry **no** `preserves` key — their summaries already say read-only, and the key set of `PLUS_ACTION_PRESERVES` is test-locked to exactly the side-effectful subset.

| action | preserves | does NOT preserve |
|---|---|---|
| `bulkAddNotes` | every pre-existing note/card entirely (scheduling, suspension, flags, tags, ids, GUIDs, deck); decks/notetypes never auto-created | — (creates: notes, their cards — suspended only under the resolved `suspend` flag —, embedded media files; media writes not undoable) |
| `bulkUpdateNoteFields` | existing cards' scheduling/suspension (**post-checked**, §31.2) and flags/deck (probe-verified, not per-call); ids, GUIDs; tags unless the entry carries `tags` | card SET can grow: a new cloze number generates its card (existing rows byte-identical, probe-verified); removing a cloze deletes nothing |
| `bulkAddTags` | fields, scheduling, suspension, flags, deck, ids, GUIDs, card set (tags-only update generates no cards, probe-verified) | the notes' tag lists (append-only) |
| `addImageOcclusionNote` | every pre-existing note/card/media file (name collision renames the INCOMING image) | — (adds one note + cards + one media file; first use adds the stock IO notetype if absent — an addition) |
| `updateImageOcclusionNote` | note id, GUID, deck, the base image/media file; existing cards' scheduling/suspension/flags | occlusion ordinals are cloze numbers: a new ordinal generates its card, a removed one leaves its card empty |
| `cropImage` | the ORIGINAL media file (crop lands in a NEW file); unlisted notes; on listed notes everything but the filename references (scheduling, suspension, flags, tags, ids, GUIDs, deck, card set) | — |
| `cropImageOcclusionImage` | original media file; note id/GUID/tags/deck; cards' scheduling/suspension/flags; kept occlusions keep ORDINALS (card identity) | Image field points at the new file; geometry remapped; a dropped occlusion's card left empty, never deleted |
| `storeMediaFilesBulk` | the entire collection DB; every EXISTING media file (different-bytes collision renames the INCOMING file; identical bytes dedup) | — |
| `bulkSuspend` | due, interval, ease, flags, tags, fields, ids, deck — including filtered-deck residency (probe-verified) | bury state: suspending a buried card replaces burial; unsuspend restores every negative queue (Deviation #8) |
| `bulkSetDueDate` | flags, fields, tags, ids, GUIDs, ease factor | due/queue/type (the job; `!` also interval); suspension/burial per §27; **filtered-deck residency — the card is sent home, `odid` consumed (probe-verified)** |
| `bulkReplaceInFields` | everything but the one named field: tags always, other fields, ids, GUIDs; existing cards' scheduling/suspension (**post-checked**, §31.2) and flags/deck (probe-verified, not per-call) | same card-set caveat as `bulkUpdateNoteFields` |
| `renameDeck` | cards and notes entirely (ids, scheduling, suspension, flags, tags, fields); deck ids stable — cards do not move; presets/descriptions/collapse (post-checked) | stored deck NAMES (the job) |
| `bulkSetFlag` | scheduling, suspension, deck, fields, tags, ids; the NON-user bits of the flags byte (`set_user_flag_for_cards` writes only the flag bits) | the requested cards' user flag (the job) |
| `renameTag` | note fields, ids, GUIDs; cards' scheduling/suspension/flags/deck; every OTHER tag on the affected notes | the matched tag + its `::` subtree (the job) |
| `emptyFilteredDeck` | note content, tags, flags, ids, intervals; the cards' HOME deck (going home IS the op: `did=odid`, `odid=0`, scheduling intact) | filtered-deck residency; the filter's temporary due override |
| `deleteEmptyCards` | the notes (never deleted — `notesPreserved` post-check; all-empty note keeps its first card); every non-empty/surviving card's state; fields, tags, ids, GUIDs | exactly the reported empty card ids |
| `createBackup` | the entire collection (a backup is a read into a new `.colpkg`) | — |
| `exportDeckApkg` | the entire local collection (a read into a NEW `.apkg`, never overwriting; the fail-closed check is about the PACKAGE) | — |
| `syncNow` | **no per-item guarantee CAN be stated** — a normal sync applies whatever the other side changed | guaranteed only: never a FULL sync (no wholesale replace), never a dialog |
| `ankihubSuggestNoteUpdate` / `ankihubSuggestNewNote` | local scheduling, suspension, flags, tags, ids, GUIDs, deck — the suggestion goes to AnkiHub's server | CAVEAT (§19, inherited): newly-added media content-hash RENAMED across the collection + referencing FIELDS rewritten, before background upload |

### 31.2 Preservation post-checks — `suspensionPreserved` / `schedulingPreserved`

The `renameDeck` `configPreserved` pattern (**verified fact, not promise**) applied to the two field writers, whose §31.1 claims are the ones most worth distrusting because they run arbitrary caller content through `col.update_note`. `bulkUpdateNoteFields` and `bulkReplaceInFields` real responses gain two ALWAYS-present additive booleans, computed inside the same call by `core._preservation_post_check`: immediately before each note's write, its cards' `(queue, due, ivl)` rows are snapshotted (one query per **written** note — unchanged/skipped notes cost nothing; a repeated id keeps the first pre-write state); after the batch the same card ids are re-read and compared. `suspensionPreserved` = no card's queue-`-1` membership changed in either direction; `schedulingPreserved` = no card's `(queue, due, ivl)` triple changed at all — a suspension flip trips **both** (the facet report is a subset signal, not an exclusive one). A card that vanished mid-call fails both. Cards BORN during the call (new cloze number → new card) are absent from the snapshot by construction — new cards are not "moved" state, and the §31.1 card-set caveat discloses them. Both `true` on a zero-write batch (zero writes moved zero cards); dry responses carry **neither** key (nothing was written, so there is no fact to verify — §15's zero-write rule). `false` is reported HONESTLY: it should never happen, and that is the alarm's point — treat it as a stop-the-line signal, not a formality. **Scope note:** upstream stock actions (`changeDeck` among them) are out of scope — this fork amends upstream behavior in exactly one place (§25's error envelope) and otherwise leaves stock actions byte-compatible; a preservation post-check there would change a stock response shape.

### 31.3 `plusInfo.effectiveConfig`

§4.9 documents the shape; §27.2 the ladder. The point stated once: the round-5 report was misled by a `returns` doc claiming a revision-15 default AND could not have learned the truth from any API surface, because the EFFECTIVE value is config-dependent (the reporting install had `suspendNewCards: true` in user config overriding the shipped `false` — which is why they observed suspension). `effectiveConfig` closes that class: `{value, source}` per §27 knob, resolved at call time through `plus._resolve_suspension_config` — the SAME function `_resolve_suspension_param` defers to for a `null` parameter, so what `plusInfo` reports is by construction what the next write will do. `source: "user_config"` requires the **user's saved config** — `meta.json`'s `config` dict, probed via `addonManager.addonMeta`, deliberately NOT `getConfig`'s merged view: `getConfig` folds the shipped `config.json` defaults under the user keys, and both §27 keys ship there, so a merged-view probe would answer `user_config` on every intact install (the round-5 review's blocker; the probe now reads the user store alone) — to carry the key with a usable **boolean**; everything else — key absent from the user store, unreadable config, **headless/no-`mw`** (the documented nuance: the value reported is then the shipped default), or a non-boolean typo (which value resolution deliberately ignores) — reports `"shipped_default"`. Residual nuance, disclosed rather than hidden: Anki's config dialog saves the **whole merged dict** (`writeConfig` → `meta.json`), so once the user saves that dialog — about anything — both keys are genuinely present in the user store and report `user_config` from then on.

### 31.4 Dry-run parity for state-preservation decisions

Two §15 gaps, closed additively: (i) `renameTag` `dryRun` gains `notesUpdated` — countable without writing (the ghost gate's own `find_notes` read; prediction semantics and the unicase/casefold caveat in §28.3); (ii) `renameDeck` `dryRun` gains `configWillBePreserved: true` — a **static contract statement** about the rename path, deliberately NOT named `configPreserved` because it is not a post-check (§28.1). Both actions' real and dry key sets are documented side by side in §28.1/§28.3 and in their `plusInfo` `returns` sketches.

### 31.5 Tests

`tests/headless_round5_test.py`: the stale-line sweep locks (the corrected `bulkAddNotes` returns doc names `suspendNewCards`+`effectiveConfig` and no `actionDocs` text claims the revision-15 defaults); `PLUS_ACTION_PRESERVES` key-set lockstep (exactly the side-effectful subset; every claim non-empty; served by `plusInfo` only for those actions; the §31.1 probe claims re-verified live — suspend keeps filtered residency, `set_due_date` evicts, cloze-add leaves existing rows byte-identical, tags-only update generates no cards); the §31.2 post-checks (present+`true` on real runs incl. zero-write batches, absent on dry runs, and **honestly `false`** when a wrapped collection's `update_note` is rigged to also suspend/reschedule the written note's cards); the §31.4 dry keys (renameTag dry `notesUpdated` == the following real run's backend count; 0 on the no-op/all-ghost shapes; renameDeck dry `configWillBePreserved: true` on both dry shapes); and `effectiveConfig` (against a FAITHFUL aqt model — `getConfig` returns the shipped `config.json` defaults merged under user keys, `addonMeta` the user store alone: shipped defaults + `source: "shipped_default"` headless AND on a **virgin install**, where the merged view already carries both booleans — the decisive case the old only-user-keys stub could not express; `user_config` when the user store carries the key with a boolean, attributed per key on a partial store; non-boolean typo → shipped value + `shipped_default`; lockstep with what a parameterless wrapper call actually passes to core). Version locks in `headless_guigap_test`/`headless_suspension_test` move to 1.3.1/18 (revision 19 moved these version locks again, to 1.4.0/19); the `actionDocs` entry-shape locks in `headless_errorcodes_diff_test`/`headless_report3_test` learn the optional `preserves` key; the strict-equality response asserts in `headless_feedback_test`/`headless_six_test` (bulkUpdateNoteFields) and `headless_round4_test` (renameTag/renameDeck dry shapes) learn the additive keys — all deliberate revision-18 contract-change updates.

## 32. Filtered-deck build: `createFilteredDeck`, `rebuildFilteredDeck` (spec revision 19, 2026-08-19)

The write half of the §29 story. Revision 17 made filtered decks *observable* (`filteredDeckReport`) and *emptiable* (`emptyFilteredDeck`), but the API still could not MAKE one — "cram deck of everything tagged PI 9 that's due", "filtered deck of my flagged cards" still meant a human clicking Tools > Create Filtered Deck. These two actions are that dialog and the deck's own Rebuild button as an API: the same backend ops (`col.sched.get_or_create_filtered_deck(0)` for the template, `add_or_update_filtered_deck` to create+build, `rebuild_filtered_deck` to re-run), the same defaults the dialog starts from, and the same gather rules — with the backend's silent surprises turned into coded refusals. Both follow §3.3 undo conventions, take §24's `undoLabel` and §15's `dryRun` (type-checked), and raise §25-coded errors. New entry names: `"AnkiConnect Plus: Create Filtered Deck"`, `"AnkiConnect Plus: Rebuild Filtered Deck"`. No new config keys, no new error codes (`duplicate` and `validation_error` gain new reachable sites, §25 table prose updated). Adaptations from the locked design are flagged in §0 Deviation #15.

**Probe-pinned backend facts this section builds on (25.09.4)** — the template read (`get_or_create_filtered_deck(deck_id=0)`) is pure and arrives with TWO prefilled default terms (`deck:<current> is:due` 100/`random`, `deck:<current> is:new` 20/`due`) that must be cleared before appending (the GUI's `_update_deck` does exactly this); `add_or_update_filtered_deck` creates, gathers and lands as ONE atomic undoable op (backend label "Build Deck") that the §3.3 add/merge pattern wraps cleanly — a single undo deletes the deck AND returns every card; the gather NEVER takes suspended cards, buried cards, or cards sitting in another filtered deck; with `allow_empty` left `False` a zero-match build raises `FilteredDeckError` atomically (nothing created — the GUI's own refusal; `allow_empty` is per-call, never persisted); a name collision NEVER errors — the backend silently uniquifies to `name+` (and names are matched case-insensitively with surrounding whitespace ignored); anki SAVES ≥3 search terms but GATHERS only the first two; term 2 skips only cards term 1 ALREADY GATHERED; the single-term gather count equals `min(limit, |matches − suspended − buried − other-filter|)` EXACTLY; `SearchTerm.limit` is an unsigned 32-bit proto field (2³² raises a raw `ValueError`); the order enum is OPEN (order=99 builds silently), so the closed vocabulary lives in this add-on; missing `::` parents are created as REGULAR decks inside the same op (the undo removes them too); a filtered PARENT raises `FilteredDeckError` ("Filtered decks can not have child decks."); `add_or_update` SELECTS the built deck as current (GUI parity) while `rebuild` does not; and a zero-change rebuild still writes an undo step, which is why the full no-op is gated.

### 32.1 `createFilteredDeck`

**Preserves (§31.1)** — note content, tags, flags, note ids, intervals/ease (the original due goes to `odue` and is restored on empty/rebuild), suspension and burial (never gathered), every OTHER deck's membership. NOT preserved: gathered cards' residency (`did` = filter, `odid` = home — that is the operation), the current-deck selection (anki's own build op selects the built deck), and missing `::` parents are added as regular decks.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `name` | str | — | Full `::` path. Must be normalized (the §28.1 renameDeck rule): empty or whitespace-padded components → `[invalid_param]`. Taken name (anki's matching: case-insensitive, surrounding whitespace ignored) → `[duplicate]` — the backend would silently create `name+` and the response would report a name the deck doesn't carry. A filtered ANCESTOR → `[validation_error]`. Missing parents are created as regular decks inside the same undo entry. |
| `searchQuery` | str | — | Validated AND normalized through `col.build_search_string` (the notesSlim path): bad syntax → `[invalid_param]`. Saved and echoed in the parser's canonical spelling (composing the eligibility search parenthesizes OR terms where grouping matters — probe-verified). EMPTY/whitespace → `[invalid_param]`: anki reads `''` as the whole collection (`deck:*`, probe-verified) — too much deck to gather by accident; say `deck:*` explicitly. |
| `limit` | int | `100` | 1 ≤ limit ≤ 4294967295 (unsigned 32-bit proto field; 0 would gather nothing — probe-verified — so it is refused, not accepted-and-useless). Default mirrors the GUI template's first filter. |
| `order` | str | `"random"` | One of `oldestReviewedFirst, random, intervalsAscending, intervalsDescending, lapses, added, due, reverseAdded, retrievabilityAscending, retrievabilityDescending` — index = backend enum = position in `col.sched.filtered_deck_order_labels()` (probe-pinned). Anything else → `[invalid_param]` (the proto is open and would accept garbage silently). Default mirrors the GUI template. |
| `secondFilter` | object | `null` | `{searchQuery[, limit, order]}` — same validation, `[invalid_param]` prefix `secondFilter.`; unknown keys refused (a typo'd `order` must not silently vanish). Defaults mirror the GUI template's second filter: limit `20`, order `"due"`. Capped at TWO terms by construction — anki saves a third but never gathers it. |
| `reschedule` | bool | `true` | The dialog's "Reschedule cards based on my answers in this deck". `false` = preview mode (cards return unchanged; the template's preview seconds 60/600/0 ride along). Round-trips (probe-verified). |
| `dryRun` | bool | `false` | §15. Size the deck without creating anything; see returns. Type-checked. |
| `undoLabel` | str | `null` | §24. |

**Returns**

```json
{"deckId": 1723456789012, "name": "PI9 cram", "cardsGathered": 52,
 "terms": [{"search": "tag:PI9 is:due", "limit": 100, "order": "random", "eligible": 52}],
 "undoEntry": "AnkiConnect Plus: Create Filtered Deck"}
```
- `deckId`: from the backend op (`OpChangesWithId.id`). `name`: the deck's ACTUAL saved name, read back post-op — the collision precheck makes it equal to the request; reading it back keeps that a fact. `cardsGathered`: post-op residency count (observation, not the ask).
- `terms`: one row per saved term — the NORMALIZED search (what the deck now carries), the limit/order used (defaults resolved), and `eligible`: the cards that term could gather at validation time (matches minus suspended/buried/other-filter).
- ONE undo entry; a single `col.undo()` deletes the deck and returns every card (missing parents it created disappear too). Test-locked.
- **`dryRun: true`** → `{wouldCreate: bool, wouldGather: int, exact: bool, wouldGatherMin: int, wouldGatherMax: int, name, terms, undoEntry: null}`, provably writing nothing (undo status byte-identical, test-locked). Single filter: `exact: true` and `wouldGather` equals the later real `cardsGathered` (the probe-verified formula `min(limit, eligible)`). Two filters: exact unless the terms OVERLAP while the first limit BINDS — anki then decides the split by term-1's gather order (`random` is nondeterministic), so no point count exists; `wouldGather` reports the UPPER bound and min/max bracket every possible outcome (bounds derivation in `_predict_filtered_gather`; the real count always lands inside, test-locked). A zero prediction is always exact (any nonzero term-1 gather lifts both bounds), so `wouldCreate: false` — the dry run REPORTS zero rather than raising; sizing is its whole point — exactly predicts the real call's `[validation_error]`.
- **Zero gatherable cards (real run)** → `[validation_error]`, NOTHING created, no undo entry (prechecked; `allow_empty` stays `False` so the backend enforces the same rule as drift backstop).

**Anki API calls / SQL** — `col.build_search_string` (validate+normalize; also composes the eligibility search with `-is:suspended -is:buried -deck:filtered`), `col.find_cards` (eligibility pools), `col.decks.id_for_name` / `col.decks.is_filtered` / `col.decks.name` (collision + ancestor prechecks), `col.sched.get_or_create_filtered_deck(deck_id=0)` (template; `del config.delays[:]` + `del config.search_terms[:]` before appending — the GUI's own sequence), `FilteredDeckConfig.SearchTerm(search, limit, order)`, `col.sched.add_or_update_filtered_deck` inside the §3.3 add/merge pattern, post-op `select count() from cards where did = ?` (§0 allowlist).

**Error cases** — `[invalid_param]` (`name`/`searchQuery`/`limit`/`order`/`secondFilter`/`secondFilter.*`/`reschedule`/`dryRun`/`undoLabel` messages per the house family, e.g. `"invalid parameter: order: one of [...] required"`); `[duplicate]` `"deck already exists: <name>"`; `[validation_error]` `"cannot create '<name>' under '<ancestor>': filtered decks can not have child decks"` / `"no cards would be gathered: suspended cards, buried cards, and cards already in another filtered deck are never gathered (anki's own rule) — nothing was created; size the search first with dryRun=true"` / a drift-backstop `FilteredDeckError` message verbatim; `[batch_reverted]` `"createFilteredDeck failed (batch reverted): <err>"` for any other mid-op failure.

### 32.2 `rebuildFilteredDeck`

**Preserves (§31.1)** — the deck and its SAVED config (name/terms/limits/orders/reschedule — a rebuild only re-runs them), the current-deck selection (probe-verified: rebuild does not re-select, unlike build), and every card's note content, tags, flags, intervals/ease, suspension and burial (never gathered; one suspended INSIDE the deck goes home on the empty half and is not re-gathered). NOT preserved: the deck's card membership — empty-then-regather IS the operation.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `deckName` | str | `null` | Exactly ONE of `deckName`/`deckId` (both or neither → `[invalid_param]`); the §29.2 selector block verbatim. Case-insensitive lookup. Missing → `[deck_not_found]`; a regular deck → `[validation_error]`. |
| `deckId` | int | `null` | For callers holding ids from `filteredDeckReport`/`createFilteredDeck`. Bool is not an int. |
| `dryRun` | bool | `false` | §15 (from birth, §0 Deviation #15b). Predict without writing; see returns. |
| `undoLabel` | str | `null` | §24. |

**Returns**

```json
{"cardsGathered": 48, "returnedFirst": 52, "undoEntry": "AnkiConnect Plus: Rebuild Filtered Deck"}
```
- Anki empties then regathers as ONE op; both halves reported honestly: `returnedFirst` = pre-op residency (observed BEFORE the op — the op does not report it), `cardsGathered` = post-op residency (the backend's `OpChangesWithCount.count` agrees; the DB read is what gets reported). ONE undo entry; a single undo restores the previous membership.
- **Rebuild-to-zero** (deck held cards, saved terms now match nothing): succeeds silently with `cardsGathered: 0`, deck left empty — anki's own behavior, not an error.
- **Full data no-op** (deck EMPTY and saved terms would gather 0): `{cardsGathered: 0, returnedFirst: 0, undoEntry: null}`, nothing written — gated BEFORE any undo entry exists because the backend happily writes a do-nothing undo step there (probe-verified; the §16.2 phantom-redo hazard, answered the same way as `emptyFilteredDeck`'s already-empty gate). A zero prediction is always exact, so the gate never mispredicts.
- The prediction/`eligible` reads use the REBUILD eligibility rule (probe-verified): the deck's OWN cards are re-gatherable, so the residency exclusion is `(-deck:filtered OR did:<this deck's id>)`. **The own-deck disjunct is the deck ID, never the deck NAME (revision-19 fix pass)**: for a filtered deck literally named lowercase `filtered`, the writer emits `deck:filtered` unquoted and anki's parser reads that as the in-any-filtered-deck KEYWORD (case-sensitive — `deck:Filtered` matches the deck; quoting does not escape it; probe-verified on 25.09.4), so a name-based disjunction was a tautology that counted OTHER filters' cards as re-gatherable — the dry bounds could miss the real count and the full-no-op gate below could be bypassed into a phantom do-nothing undo step. `did:<id>` matches exactly the deck's current residents (filtered decks have no children and are never a home); the §32.3 regression locks all three phases.
- **`dryRun: true`** → `{wouldReturn: int, wouldGather: int, exact: bool, wouldGatherMin: int, wouldGatherMax: int, terms: [{search, limit, order, eligible}], termsIgnored: int, undoEntry: null}` with the undo status byte-identical (test-locked; the saved-config read is a pure read). `terms` echoes the (normalized) saved terms anki will actually gather — the first TWO; `termsIgnored` counts saved terms beyond those (an externally-written deck can carry more; anki stores but never gathers them, probe-verified). A saved term that no longer parses (external writer) → `[validation_error]` `"the deck's saved search term <n> does not parse: <err>"` on both paths, before any undo entry — not `[invalid_param]`, because it is not the caller's parameter.

**Anki API calls / SQL** — §29.2's selector prechecks verbatim (`id_for_name`/`get`/`dyn`); `select count() from cards where did = ?` pre-op (`returnedFirst`) and post-op (`cardsGathered`) (§0 allowlist); `col.sched.get_or_create_filtered_deck(deck_id=<real id>)` (saved-config read); `col.build_search_string` + `col.find_cards` + `col.group_searches(SearchNode(negated=SearchNode(deck="filtered")), SearchNode(parsable_text="did:<id>"), joiner="OR")` (prediction; the ID-based own-deck disjunct — revision-19 fix pass); `col.sched.rebuild_filtered_deck` inside the §3.3 add/merge pattern.

**Error cases** — `[invalid_param]` selector/`dryRun`/`undoLabel` messages (§29.2's family verbatim); `[deck_not_found]` `"deck was not found: <name or id>"`; `[validation_error]` `"deck is not a filtered deck: <stored name>"` / the saved-term parse refusal above / a drift-backstop `FilteredDeckError` verbatim; `[batch_reverted]` `"rebuildFilteredDeck failed (batch reverted): <err>"`.

### 32.3 Tests

`tests/headless_round6_test.py` covers §32 end to end on a scratch collection: create dry→real parity (single-term exact; undo snapshot byte-identical on dry; real `cardsGathered` == `wouldGather`; suspended/buried/other-filter exclusions live), limit binding, every refusal (`[duplicate]` incl. case-variant, un-normalized name, empty/bad search, bad order incl. case-sensitivity, filtered parent with NOTHING created, zero-gather real refusal vs dry `wouldCreate: false`), two-term builds (disjoint exact; overlap-under-binding-limit → `exact: false` with the real count inside the bounds), `reschedule: false` round-trip, missing-parent creation + single-undo removal, the current-deck side effect (create selects, rebuild preserves), `undoLabel` on both actions, rebuild by name and by id with honest `returnedFirst`/`cardsGathered` after a tag mutation, rebuild-to-zero, the full no-op gate (byte-identical undo), a 3-term externally-saved deck (`termsIgnored: 1`, prediction still brackets), saved-term parse refusal, a filtered deck literally named lowercase `filtered` (revision-19 fix-pass regression: the `did:`-composed residency keeps other filters' cards out of the pool through all three phases — resident, rebuild-to-zero, gated no-op — the dry bounds bracket every real count, and the no-op gate fires with the undo status byte-identical), selector errors, and the registry/lockstep surface (action list, summaries, returns, preserves, README/SPEC/SKILL.md counts). Count locks in the other suites move 34 → 36 and version locks to 1.4.0/19 — deliberate revision-19 lockstep updates.

## 33. Staged optional-tag suggestion: `ankihubStageOptionalTagSuggestion` (spec revision 20, 2026-08-19)

Publishing an AnkiHub **Optional Tag** group (tags like `AnkiHub_Optional::BSOM::MCQ_03::PI_027_Pancreas`) was the one step of the BSOM→AnKing pipeline no API could reach: `Browser → select notes → right-click → Suggest Optional Tags`. This action is the LOCAL half of that flow as an API — validate, tag, and hand the human the exact Browser selection — **stopping deliberately before anything of AnkiHub's is touched**.

**ToS + permission boundary (locked)** — two independent constraints draw the same line. (1) AnkiHub's Terms of Service (effective 2025-01-14) prohibit "any automated use of our resources, including... using scripts to create or post content": a direct-submit endpoint (the feature request's `suggestOptionalTags`, calling the add-on client's own posting method) is therefore **not built and must not be built**. (2) This project's own constraints file requires **written permission for ANY programmatic AnkiHub access** ("do not design a workaround") — and that rules out more than posting: **constructing the add-on's own `OptionalTagsSuggestionDialog` from code is itself programmatic AnkiHub access**, because its `__init__` fires AnkiHub network calls (a synchronous deck-extension fetch plus a background tag-group prevalidation op) with no human action taken. An earlier draft of this action opened that dialog; it was trimmed on review. The shipped boundary is: **everything local, plus the Browser selection** — the action tags the notes, opens Anki's own Browser on exactly those notes, returns, and the human performs BOTH AnkiHub-touching clicks (the right-click menu item, then Submit in AnkiHub's dialog). This codebase calls **no AnkiHub client method and constructs no AnkiHub GUI object** for this action — no suggestion post, no tag-group prevalidation, no deck-extension fetch, no dialog; it imports **no module from the add-on's `gui/` package** (`_plusAnkiHubImport(gui=False)`) and makes **zero calls that can reach the network** (the only add-on reads are local: `settings.config.is_logged_in()` and the `ankihub_db` deck mapping, both file reads). The written-permission path that would unlock a future auto-submit variant: ask AnkiHub directly — they recruit tagging contributors at `ahmed@ankihub.net`, and the repo's `OPTIONAL_TAGS_FEEDBACK.md` drafts the exact question; the §4.9 `staged optional-tag publication` recipe serves this rationale and path to every caller. The §19 etiquette stance (no bulk suggestion actions) is unchanged; a regression lock greps `connect_plus/` for the add-on client's optional-tag method names AND the dialog class name and fails on any hit, and the verifier suite runs under a process-wide socket deny-guard.

**GUI-COUPLED CAVEAT** — this is the first Plus action that opens a window: the real run needs the running Anki GUI (it opens/refocuses the Browser — **replacing its current search**). A headless caller gets the full validation chain and the tag-write prediction via `dryRun: true`, which writes nothing and opens nothing; only the real run is GUI-coupled.

**Guard order (the §19 family rule, §25 codes)** — (1) cheap param validation: `dryRun` bool, `undoLabel` shape (§24), `tag` shape, `noteIds` shape/dedup/ceiling; (2) add-on presence + feature detection (`_plusAnkiHubModules(gui=False)`, §19 incl. the revision-20 addition `ankihub_dids_for_anki_nids`; imports NOTHING from the add-on's `gui/` package) → `[incompatible_ankihub_addon]`; (3) login check → `[not_logged_in]` — not because this action talks to AnkiHub (it never does), but because a logged-out human could not submit the staged suggestion, so failing fast beats a dead-end Browser handoff; (4) local db checks, all-or-nothing: every note id must exist in the collection (`[not_found]` on the FIRST miss, nothing written — staging a partial set is worse than staging nothing), and `ankihub_db.ankihub_dids_for_anki_nids(noteIds)` must return exactly ONE deck (`0 → [not_found]` `NOT_AN_ANKIHUB_NOTE`, `>1 → [validation_error]` — AnkiHub's own dialog enforces the same single-deck rule, but only after the human opens it; checking the same LOCAL add-on db mapping here refuses a doomed staging before any write); (5) `dryRun` exit; (6) tag write; (7) Browser; (8) **STOP** — the rest is the human's.

**Params**

| name | type | default | notes |
|---|---|---|---|
| `tag` | str | — | Canonical `AnkiHub_Optional::<TagGroup>::<Tag>`: must start with `AnkiHub_Optional::` (exact spelling; `[validation_error]` otherwise — this action only stages optional tags) and carry ≥3 non-empty `::` segments (`[validation_error]` — the add-on's dialog filters on `len(tag.split("::", maxsplit=2)) == 3` and would silently ignore anything shorter). Embedded whitespace is `[invalid_param]` (the tag path splits on whitespace — a spaced "tag" would silently become several tags). |
| `noteIds` | [int] | — | Non-empty list of ints, deduplicated preserving first occurrence; **≤500 unique ids** (`core.ANKIHUB_OPTIONAL_TAG_NOTE_CEILING`) else `[invalid_param]` — a runaway loop should fail, not stage. All-or-nothing existence and single-deck rules above. |
| `dryRun` | bool | `false` | §15, type-checked. Full validation chain (params → add-on → login → local db), then the `bulk_add_tags` dry prediction — **nothing written, no Browser, zero network** (zero network holds on the real path too). |
| `undoLabel` | str | `null` | §24; names the tag write's undo entry. Default entry: `"AnkiConnect Plus: Stage Optional Tag"`. |

**Returns**

```json
{"tagged": [1483845152253], "alreadyTagged": [1489115655836],
 "ankihubDeckId": "e77aedfe-a636-40e2-8169-2fce2673187e", "browserOpened": true,
 "nextStep": "right-click the selection -> AnkiHub -> Suggest Optional Tags",
 "undoEntry": "AnkiConnect Plus: Stage Optional Tag"}
```

- `tagged`: notes this call actually wrote the tag onto — ONE undo entry via the `bulkAddTags` core path (`core.bulk_add_tags`, atomic), so its single-entry/`undoLabel`/idempotence contracts apply unchanged. `alreadyTagged`: the rest of the (deduplicated) request — already carried the tag. Re-staging an already-tagged set is a reported no-op write (`tagged: []`, `undoEntry: null`, nothing written) that still reopens the Browser selection — the legitimate "reopen to submit" flow.
- `ankihubDeckId`: the single AnkiHub deck (uuid string, the `ankihubStatus.decks` spelling) every staged note belongs to — resolved from the add-on's LOCAL db mapping, no network.
- `browserOpened: true`: the Browser now shows exactly the staged notes. `nextStep` (`core.ANKIHUB_STAGE_NEXT_STEP`, verbatim): `"right-click the selection -> AnkiHub -> Suggest Optional Tags"` — the human's remaining move; AnkiHub's own dialog then loads, prevalidates and submits under the human's clicks, exactly as if they had built the selection by hand. **Nothing has been submitted to AnkiHub when this returns — and nothing ever is by this action.**
- **`dryRun: true`** → `{wouldTag: [noteId], alreadyTagged: [noteId], ankihubDeckId: str, wouldOpenBrowser: true, undoEntry: null}` (§31.4 side-by-side rule: real `tagged`/`browserOpened` ↔ dry `wouldTag`/`wouldOpenBrowser`; `nextStep` is real-only — a dry run leaves the human nothing to click yet).

**Browser mechanics** — the Browser is opened with `aqt.dialogs.open("Browser", mw, search=("nid:<id>,<id>,...",))` in REQUEST order — `search` is a **1-tuple** because both `Browser.__init__` and `reopen` splat it (`search_for_terms(*search)`; a bare string would shred into per-character garbage terms, aqt 25.09.4 `browser.py:558`). The `nid:` search selects exactly the staged notes, which is what the add-on's right-click menu action reads (`browser.selected_nids`). Should the Browser open fail AFTER the tag write (no GUI), the write is KEPT — one undo entry — and re-running the identical call once the GUI is up is safe: already-tagged notes are skipped.

**Preserves (§31.1)** — everything except the staged notes' tag lists (the `bulkAddTags` path: fields, scheduling, suspension, flags, deck assignment, note ids, GUIDs, card set untouched). AnkiHub is not touched at all — no server write, no read, no GUI object of theirs constructed. GUI side effect disclosed: Browser search replaced.

**Error cases** — `[invalid_param]` (`tag`/`noteIds`/`dryRun`/`undoLabel` house messages incl. the whitespace-in-tag and >500 ceiling refusals); `[validation_error]` (non-optional tag prefix, <3 segments, notes spanning >1 AnkiHub deck); `[not_found]` (`"note was not found: <id>"` on the first missing id; `NOT_AN_ANKIHUB_NOTE` when zero AnkiHub decks match); `[incompatible_ankihub_addon]` (§19 detector incl. the revision-20 `ankihub_dids_for_anki_nids` addition); `[not_logged_in]`; `[batch_reverted]` if the tag write itself fails mid-batch (nothing kept, §4.4 contract); `[sync_in_progress]` (guarded action); `[collection_unavailable]`. The AnkiHub HTTP taxonomy codes (`[auth_failed]`/`[permission_denied]`/`[rate_limited]`/`[network_error]`) are NOT reachable from this action — it makes no AnkiHub calls.

### 33.1 Tests

`tests/headless_optionaltag_test.py` (ZERO network, ZERO real-add-on imports — the AnkiHub package is faked in `sys.modules`, and the staging worlds seed NO `gui/` module at all, so a single green happy-path run PROVES the action imports none): pure validators (canonical prefix, segment rule, whitespace refusal, dedup order, the 500 ceiling at 500/501, boundary codes); registry/lockstep (37th action, summaries/returns/preserves/recipe/SPEC header/README/SKILL counts, `1.5.0`/rev 20, `UNDO_STAGE_OPTIONAL_TAG` ↔ `sanitize_undo_label(ANKIHUB_STAGE_TAG_LABEL)` lockstep, `ANKIHUB_STAGE_NEXT_STEP` served verbatim); wrapper behavior against a scratch collection with a faked add-on: cheap-validation-first (ceiling refused before the add-on manager is ever touched), `[incompatible_ankihub_addon]` for missing add-on / unloaded add-on / missing `ankihub_dids_for_anki_nids`, `[not_logged_in]` before any write or UI, first-missing-note all-or-nothing with nothing tagged, 0-deck → `[not_found]` / 2-deck → `[validation_error]`, `dryRun` full prediction (`wouldOpenBrowser`) with `undo_status()` byte-identical + zero Browser opens, real-path happy flow (notes tagged, ONE undo entry named the default, Browser opened with the 1-tuple `nid:` search in request order, `browserOpened: true`, `nextStep` verbatim, and NO other window: no dialog machinery exists to open), idempotent re-staging (`tagged: []`, `undoEntry: null`, Browser still reopens), `undoLabel` override, single-undo revert, and the ToS-boundary regression grep — no optional-tag client method name, no `OptionalTagsSuggestionDialog`, no `gui/`-module import anywhere in the action's path. `tests/headless_stagetags_test.py` (independent verifier) re-proves the same contract behind a process-wide **socket deny-guard** (any python-level connection attempt fails the suite), with forbidden-call recorders on every faked AnkiHub client function and an exit gate asserting no `1322529746.gui*` module ever entered `sys.modules`. Count locks in the other suites move 36 → 37 and version locks to 1.5.0/rev 20 — deliberate revision-20 lockstep updates.
