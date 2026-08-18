# Copyright 2016-2021 Alex Yatskov
# Copyright (C) 2026 Matthew Correll (AnkiConnect Plus modifications)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

"""Business logic for the AnkiConnect Plus actions.

Part of AnkiConnect Plus, a fork of AnkiConnect by Alex Yatskov (FooSoft
Productions) — https://foosoft.net/projects/anki-connect/

Every public function is a pure function over anki.collection.Collection;
this module never imports aqt so it stays headless-testable.
"""

import base64
import binascii
import datetime
import json
import os
import re
import unicodedata

import anki.collection
import anki.consts
import anki.notes
import anki.notes_pb2
import anki.sync
import anki.utils
from anki.errors import (Interrupted, InvalidInput, NetworkError,
                         NotFoundError, SearchError, SyncError, SyncErrorKind)

PLUS_VERSION = "1.2.0"
# The SPEC revision this code implements, kept in lockstep with SPEC.md's
# "Version: <PLUS_VERSION> (spec revision <PLUS_SPEC_REVISION>" header (test-
# locked). Revision 15 is the first revision that changed what two actions DO
# to the collection by default rather than only what they return, so plusInfo
# needs ONE machine-readable field that a caching client can branch on:
# PLUS_VERSION moves on behavior changes, specRevision names the contract.
PLUS_SPEC_REVISION = 16
PLUS_ACTIONS = ["bulkAddNotes", "bulkUpdateNoteFields", "bulkAddTags",
                "addImageOcclusionNote", "getImageOcclusionNote",
                "updateImageOcclusionNote", "queryRevlog", "createBackup",
                # crop a media image into a NEW media file (original kept), optionally rewriting notes to reference it
                "cropImage",
                # crop an IO note's base image and remap its occlusion rects into the cropped frame, one undo entry
                "cropImageOcclusionImage",
                # render cards' question/answer HTML + css through Anki's own template pipeline (read-only)
                "renderCard",
                # compact, paginated, HTML-stripped note reader built for LLM consumption (read-only)
                "notesSlim",
                # base64 thumbnails of media images: aspect-preserved, never upscaled (read-only)
                "mediaThumbnails",
                # do these bare media filenames exist? membership probe without the full listing (read-only)
                "mediaExists",
                # store many media files (base64 data or absolute path) in one call; per-item {requested, actual}
                "storeMediaFilesBulk",
                # suspend or unsuspend cards as one undoable batch
                "bulkSuspend",
                # reschedule cards' due dates ('0', '1-7', '3!') as one undoable batch
                "bulkSetDueDate",
                # export a deck (and its subdecks) to a .apkg file, never overwriting
                "exportDeckApkg",
                # read-only sync probe: login, local dirtiness, server-required kind, async job state
                "syncStatus",
                # start a normal AnkiWeb sync as a background job (never full-sync, never dialogs); poll syncStatus
                "syncNow",
                # AnkiHub bridge: install/enable/login/deck status + add-on compatibility probe (read-only, never network)
                "ankihubStatus",
                # submit ONE change suggestion for an existing AnkiHub note through the installed AnkiHub add-on
                "ankihubSuggestNoteUpdate",
                # submit ONE new-note suggestion; duplicate conflicts can auto-resubmit as a change suggestion
                "ankihubSuggestNewNote",
                # READ-ONLY deck audit: missing media, malformed clozes, cloze/card drift, optional orphan-media scan
                "checkDeckIntegrity",
                # find/replace (literal or regex) on ONE named field's raw HTML, one undoable batch, dryRun preview
                "bulkReplaceInFields",
                # read Anki's own undo stack: what a single undo/redo would do right now (read-only)
                "undoStatus",
                "plusInfo"]
# One-line summaries served by plusInfo's actionDocs (SPEC 4.9): the
# discoverability surface for LLM callers. Keep every PLUS_ACTIONS name
# present here; param signatures are read live off the plus.py wrappers.
PLUS_ACTION_SUMMARIES = {
    "bulkAddNotes": "Add many notes as one undoable batch (duplicate precheck, atomic revert, dryRun preview). Optional suspended-draft mode (SPEC 27): pass suspend=true (or set config key 'suspendNewCards', ships false) and the cards this batch creates are left SUSPENDED inside the same undo entry and listed in 'suspended' — a generated draft never enters review before a human unsuspends it.",
    "bulkUpdateNoteFields": "Update fields and/or replace tags on many notes as one undoable batch; byte-identical no-ops are not written and are reported in 'unchanged'. dryRun=true with diff=true adds a per-field before/after preview capped at maxPreview.",
    "bulkAddTags": "Add tags to many notes as one undoable batch; only notes actually changed are written and reported in 'updated'.",
    "addImageOcclusionNote": "Create a native Image Occlusion note from an image path or base64 data plus normalized 0-1 rects.",
    "getImageOcclusionNote": "Read an IO note's image filename, occlusion shapes, header, backExtra, tags (read-only).",
    "updateImageOcclusionNote": "Update an IO note's occlusions/header/backExtra/tags; omitted params are kept (the image cannot be changed).",
    "queryRevlog": "Read-only review-history query with cardIds/noteIds/deckName/sinceMs/untilMs filters; paginated via offset+limit with total/truncated/nextOffset.",
    "createBackup": "Create a .colpkg backup in the profile's backups folder; created=false means nothing changed since the last backup.",
    "cropImage": "Crop a media image into a NEW media file (original kept), optionally rewriting notes to reference it.",
    "cropImageOcclusionImage": "Crop an IO note's base image and remap its occlusion rects into the cropped frame, one undo entry.",
    "renderCard": "Render cards' question/answer through Anki's template pipeline (read-only); format='html' (verbatim, scripts/styles included), 'body' (script/style blocks removed), or 'text' (visible text only). cssMode controls notetype CSS: 'perCard' (default for html/body), 'byNotetype' (one top-level cssByNotetype map, no per-card css) or 'omit' (default for format='text', where css is meaningless); every card carries 'notetype'.",
    "notesSlim": "Compact paginated note reader for LLM consumption; exactly one of query/noteIds is required. stripHtml (default true; false returns raw field HTML), fields projection, omitEmptyFields, maxFieldLength with per-note truncatedFields. Under noteIds, 'total' counts the ids actually FOUND and 'missing' lists the ids that no longer exist. Raw-fidelity field projection: fields=[...] + stripHtml=false + maxFieldLength=0 returns the chosen fields' exact stored HTML, untruncated.",
    "mediaThumbnails": "Base64 thumbnails of media images: aspect-preserved, never upscaled (read-only).",
    "mediaExists": "Membership probe: which of these bare media filenames exist in the media folder (read-only, input order; malformed/path-y names report exists:false). actualName reveals the true stored spelling when the filesystem matched case-insensitively (macOS/Windows) — a name that only differs in case will 404 on AnkiWeb/Linux/iOS.",
    "storeMediaFilesBulk": "Store many media files (base64 data or absolute path) in one call; per-item {requested, actual} makes Anki's dedup/rename decision visible, {requested, error} on failures, input order.",
    "bulkSuspend": "Suspend or unsuspend cards as one undoable batch; changedIds lists the cards actually written.",
    "bulkSetDueDate": "Reschedule cards' due dates ('0', '1-7', '3!') as one undoable batch. WARNING: Anki's set_due_date RESURRECTS suspended and buried cards — every targeted card becomes a normal review card; the ids it revived are reported in 'unsuspended'/'unburied'. DELIBERATE DEVIATION FROM ANKI (SPEC 27): 'preserveSuspended' defaults to TRUE (config key 'preserveSuspendedOnReschedule'), so the cards it revived are RE-SUSPENDED inside the same undo entry and listed in 'resuspended' (buried cards are deliberately NOT re-buried). Pass preserveSuspended=false (or flip the config key) for stock behavior. It also always writes (no no-op suppression: '1-7' is nondeterministic by design); dryRun=true predicts changedIds and the whole resurrection/re-suspension set without writing anything.",
    "exportDeckApkg": "Export a deck (and its subdecks) to a .apkg file, never overwriting.",
    "syncStatus": "Read-only sync probe: login, local dirtiness, server-required kind, async job state.",
    "syncNow": "Start a normal AnkiWeb sync as a background job (never full-sync, never dialogs); poll syncStatus.",
    "ankihubStatus": "AnkiHub bridge probe: install/enable/login/deck status + add-on compatibility (read-only, never network).",
    "ankihubSuggestNoteUpdate": "Submit ONE change suggestion for an existing AnkiHub note through the installed AnkiHub add-on.",
    "ankihubSuggestNewNote": "Submit ONE new-note suggestion; duplicate conflicts can auto-resubmit as a change suggestion.",
    "checkDeckIntegrity": "Read-only integrity audit of a deck and its subdecks: missing media per field, unbalanced cloze markers, cloze-vs-card ordinal drift, cloze notes with zero effective clozes, optional orphan-media scan. Every list is deck-scoped EXCEPT orphanMediaCollectionWide, which is COLLECTION-WIDE (capped by orphanMediaLimit, full size in orphanMediaCount).",
    "bulkReplaceInFields": "Find/replace (literal or python-regex) on ONE named field's raw HTML, as one undoable batch; field, find and replace are required, plus exactly one of query/noteIds. dryRun returns a capped before/after preview.",
    "undoStatus": "Read Anki's undo stack (read-only): what a single undo/redo would do right now, plus lastStep — the observed truth behind every action's undoEntry.",
    "plusInfo": "Name/version/specRevision/action list plus per-action actionDocs (summary + params + returns), an 'errorCodes' map and a 'recipes' list of named call patterns; works before a profile is open.",
}

# plusInfo actionDocs 'returns' (SPEC 4.9, revision 13 — round-3 field feedback
# ASK 1). actionDocs documented INPUTS and nothing else, so callers guessed
# output shapes and took KeyErrors (measured: 'entries' guessed for queryRevlog,
# which returns {rows,total,truncated,nextOffset}; a bare list guessed for
# renderCard, which returns {cards:[...]}). One shape sketch per action, in the
# same JSON-flavored shorthand as the params strings: `key: type` pairs, `|`
# for alternatives, `[...]` for arrays of the enclosed item shape. Conditional
# and mode-dependent keys are named inline. Every PLUS_ACTIONS name must be
# present (locked by a test alongside PLUS_ACTION_SUMMARIES).
PLUS_ACTION_RETURNS = {
    "bulkAddNotes":
        "{added: [noteId], suspended: [cardId], skipped: [{index, reason}], undoEntry: str|null} "
        "— 'suspended' is ALWAYS present and lists the cards this call left SUSPENDED (SPEC 27: "
        "the 'suspend' param defaults to true, so a successful add normally returns a non-empty "
        "list; a non-empty 'added' with 'suspended': [] means suspension was switched off). "
        "dryRun=true instead returns {wouldAdd: int, wouldSuspend: bool, skipped: [{index, "
        "reason}], undoEntry: null} — wouldSuspend is the resolved DECISION, not a count, because "
        "card ids do not exist until a real add.",
    "bulkUpdateNoteFields":
        "{updated: [noteId], unchanged: [noteId], skipped: [{index, reason}], undoEntry: str|null} — "
        "dryRun=true returns {wouldUpdate: [noteId], unchanged, skipped, undoEntry: null}, and "
        "dryRun+diff=true adds {preview: [{noteId, field, before, after}], previewTruncated: bool} "
        "where field is a notetype field name or the literal '__tags__' for a tags-only change.",
    "bulkAddTags":
        "{updated: [noteId], skipped: [{index, reason}], undoEntry: str|null} — "
        "dryRun=true returns {wouldUpdate: [noteId], skipped, undoEntry: null}.",
    "addImageOcclusionNote":
        "{noteId: int, cardIds: [int], undoEntry: str}",
    "getImageOcclusionNote":
        "{imageFilename: str, occlusions: [{ordinal, shape, left, top, width, height, "
        "properties?} for rects | {ordinal, shape, properties} for ellipse/polygon/text], "
        "header: str, backExtra: str, tags: [str], occludeInactive: bool} — DISCRIMINATE ON "
        "'left', NOT on the absence of 'properties': a rect carries 'properties' too whenever "
        "the backend returned keys beyond the four geometry ones, and every rect this add-on "
        "creates with the default hideAllGuessOne=true has properties {\"oi\": \"1\"} "
        "(editor-made rects may also carry 'angle'/'fill'). left/top/width/height are floats; "
        "everything inside 'properties' is a raw backend string.",
    "updateImageOcclusionNote":
        "{undoEntry: str|null} — null when nothing actually changed (no write, no undo entry).",
    "queryRevlog":
        "{rows: [{id, cardId, noteId, ease, interval, lastInterval, factor, timeMs, type, "
        "reviewedAt}], total: int, truncated: bool, nextOffset: int|null} — NOT 'entries'; "
        "total is the full match count, rows is the page.",
    "createBackup":
        "{created: bool} — false means the backend declined because nothing changed since the "
        "last backup, which is a normal outcome and not an error.",
    "cropImage":
        "{newFilename: str, width: int, height: int, notesUpdated: [noteId], undoEntry: str|null}",
    "cropImageOcclusionImage":
        "{newFilename: str, occlusionsKept: int, occlusionsClipped: int, occlusionsDropped: int, "
        "cardIds: [int], undoEntry: str}",
    "renderCard":
        "{cards: [{cardId, question, answer, deckName, modelName, notetype, ord} | "
        "{cardId, error}]} — each card also carries 'css' when cssMode='perCard', and the "
        "response gains a top-level {cssByNotetype: {notetypeName: css}} ONLY when "
        "cssMode='byNotetype'. Per-card render failures are {cardId, error} entries inside "
        "'cards', not a raised error.",
    "notesSlim":
        "{total: int, notes: [{noteId, modelName, tags: [str], fields: {name: value}, "
        "truncatedFields: [name]}], missing: [noteId], nextOffset: int|null} — under noteIds, "
        "total counts the ids FOUND and missing lists the ids that no longer exist "
        "(len(noteIds) == total + len(missing) on every page); under query, total is the match "
        "count and missing is always []. nextOffset is null when no further page can return a note. COST: total/missing are window-independent, so the noteIds path re-scans the WHOLE id list on EVERY page — a full paged pass is O(N^2/L) (~103 ms added at 5,000 ids / limit 200, ~1.7 s at 20,000). Read total/missing off the first page and carry them.",
    "mediaThumbnails":
        "{thumbnails: [{filename, data, width, height} | {filename, error}]} — data is base64, "
        "per-file failures are {filename, error} entries, never a raised error.",
    "mediaExists":
        "{results: [{filename, exists: bool, actualName: str|null}]} — input order and duplicates "
        "preserved. actualName is non-null only when the filesystem matched case-insensitively "
        "(macOS/Windows): the name as actually stored. A non-null actualName means the requested "
        "spelling will 404 on AnkiWeb/Linux/iOS.",
    "storeMediaFilesBulk":
        "{stored: [{requested, actual} | {requested, error}]} — input order. actual != requested "
        "reveals anki's dedup/rename decision (same name + different bytes gets a SHA-1 suffix).",
    "bulkSuspend":
        "{changed: int, changedIds: [cardId], undoEntry: str|null} — a data no-op returns "
        "changed 0, changedIds [] and undoEntry null (nothing is written).",
    "bulkSetDueDate":
        "{changed: int, changedIds: [cardId], unsuspended: [cardId], unburied: [cardId], "
        "resuspended: [cardId], undoEntry: str|null} — all three id lists are ALWAYS present ([] "
        "when empty). unsuspended/unburied list the cards this call RESURRECTED (anki's "
        "set_due_date turns suspended and buried cards into normal review cards); 'resuspended' "
        "lists the ones it then PUT BACK because preserveSuspended was on (SPEC 27, default "
        "true), re-read from the post-op queues. They are DURING-the-call facts, not final state: "
        "the cards left revived are unsuspended MINUS resuspended, and buried cards are never "
        "re-buried. This action always writes; it never suppresses no-ops. dryRun=true instead "
        "returns {wouldChange: int, wouldChangeIds: [cardId], wouldUnsuspend: [cardId], "
        "wouldUnbury: [cardId], wouldResuspend: [cardId], undoEntry: null} — a prediction from "
        "the pre-state that writes nothing.",
    "exportDeckApkg":
        "{path: str, sizeBytes: int, notesExported: int} — path is the file actually written "
        "(never an overwrite; a serial suffix is added if needed), so read it rather than "
        "assuming the requested outPath.",
    "syncStatus":
        "{loggedIn: bool, job: {state, startedMs, result, error}, mediaSyncing: bool, "
        "mediaSecondsSinceLastSync: int, lastSyncMs: int|null, modMs: int|null, "
        "required: 'no_changes'|'normal_sync'|'full_sync_required'|'not_logged_in'|"
        "'unknown_no_network'|'offline'|'auth_failed'|'error'|null, serverChecked: bool} — "
        "serverChecked is true ONLY when this call completed a network round trip; false always "
        "means 'not verified by this call', never 'the server says no'.",
    "syncNow":
        "{started: true, mediaSync: bool} on start, or {started: false, reason: "
        "'collection_unavailable'|'not_logged_in'|'already_syncing'|'media_sync_in_progress'} — "
        "a refusal is a normal response, NOT an error. Poll syncStatus for the outcome.",
    "ankihubStatus":
        "{installed: bool, enabled: bool, loggedIn: bool, addonVersion: str|null, "
        "testedAddonVersion: str, appUrl: str|null, decks: [{ankihubDeckId, ankiDeckId, name, "
        "userRelation, isAnkingDeck}], compatible: bool} — plus {problems: [str]} only when "
        "compatible is false.",
    "ankihubSuggestNoteUpdate":
        "{result: 'success'|'noChanges'|'emptyFirstField'|..., comment: str} — comment is the "
        "text actually submitted (rationale + folded source line).",
    "ankihubSuggestNewNote":
        "{result: 'success'|'noChanges'|'emptyFirstField'|..., resubmittedAsChange: bool} — "
        "resubmittedAsChange true means the note already existed on AnkiHub and the call was "
        "automatically retried as a change suggestion.",
    "checkDeckIntegrity":
        "{missingMedia: [{noteId, field, filename}], unbalancedCloze: [{noteId, field}], "
        "clozeCardMismatch: [{noteId, expectedOrds, actualOrds}], clozeNotesWithoutCloze: "
        "[noteId], orphanMediaCollectionWide: [filename]|null, orphanMediaCount: int|null, "
        "orphanMediaTruncated: bool, notesChecked: int} — every list is DECK-SCOPED except "
        "orphanMediaCollectionWide, which is COLLECTION-WIDE and capped at orphanMediaLimit "
        "(default 100); orphanMediaCount is the true uncapped total. Both orphan fields are null "
        "unless includeOrphanMedia=true.",
    "bulkReplaceInFields":
        "{changed: [noteId], matchesTotal: int, unchanged: [noteId], skipped: [{noteId, reason}], "
        "undoEntry: str|null} — dryRun=true instead returns {wouldChange: [noteId], matchesTotal, "
        "unchanged, skipped: [{noteId, reason}], preview: [{noteId, before, after}], "
        "previewTruncated: bool, undoEntry: null}. before/after are raw field HTML. NOTE the "
        "deliberate deviation from every other action's skipped[]: entries here are keyed "
        "noteId, NOT index — the query path has no meaningful input index.",
    "undoStatus":
        "{undo: str|null, redo: str|null, lastStep: int} — null (never '') when there is nothing "
        "to undo/redo. lastStep is anki's monotonic undo-step counter: snapshot it, run a write, "
        "call again — it advances iff an undo entry was really created.",
    "plusInfo":
        "{name: str, version: str, specRevision: int (the SPEC revision this build "
        "implements; version's minor moves whenever DEFAULT BEHAVIOR does, so a cached "
        "plusInfo can detect it), apiVersion: int, actions: [str], actionDocs: {action: "
        "{summary, params, returns}}, errorCodes: {code: {retryable: bool, reachable: bool, "
        "meaning: str}}, errorPrefixNote: str, recipes: [{name, description, example}], "
        "docs: {plus, upstream, upstreamSource}}",
}

DOCS_UPSTREAM = "https://foosoft.net/projects/anki-connect/"
DOCS_UPSTREAM_SOURCE = "https://git.sr.ht/~foosoft/anki-connect"
DOCS_PLUS = "https://github.com/mattccorrell-svg/anki-connect-plus#readme"

#
# Stable error codes (SPEC 25). Every error RAISED by a Plus action carries a
# machine-parseable '[code] ' prefix before the unchanged message body; the
# code is one of this closed vocabulary. Per-item error strings embedded in
# results (skipped[].reason, thumbnails[].error, stored[].error, ...) are NOT
# prefixed — they never raise. Value = retryable: True means the same call
# may succeed later without the caller changing anything.
#
PLUS_ERROR_CODES = {
    'not_found': False,               # note/card/media file/IO notetype/output dir absent
    'invalid_param': False,           # request shape/type/range wrong (house 'invalid parameter:' family)
    'deck_not_found': False,          # named deck does not exist (decks are never auto-created)
    'duplicate': False,               # reserved: duplicates are per-item skip reasons today, never raised
    'unsupported_format': False,      # image failed to load/encode (corrupt or unsupported format)
    'io_error': False,                # reserved: disk read/write failure (today only per-item errors)
    'batch_reverted': False,          # atomic batch hit a hard error and was rolled back; JSON report after the prefix
    'collection_unavailable': True,   # no collection open (profile screen); retry once a profile is open
    'sync_in_progress': True,         # REACHABLE (rev 13): the plus_api sync guard; poll syncStatus and retry
    'not_logged_in': False,           # a login this add-on cannot perform is required (e.g. AnkiHub add-on logged out)
    'auth_failed': False,             # stored credential rejected by the server (e.g. AnkiHub 401)
    'offline': True,                  # reserved: sync network failures surface in job.error / required, not raises
    'full_sync_required': False,      # reserved: surfaced via the sync job error, never raised
    'network_error': True,            # transport failure / unexpected HTTP status (5xx included)
    'rate_limited': True,             # server rate limit (e.g. AnkiHub 429); wait, then retry
    'permission_denied': False,       # server refused (e.g. AnkiHub 403)
    'validation_error': False,        # well-formed request refused on semantic grounds (wrong note kind, empty crop, server 400)
    'incompatible_ankihub_addon': False,  # AnkiHub add-on missing/disabled/unloaded or drifted from the tested version
    'source_required': False,         # AnkiHub suggestion needs a source object/text it did not get
    'rationale_invalid': False,       # AnkiHub rationale empty or over the dialog's 1023-char cap
    'internal': False,                # unexpected failure inside the add-on or Anki (bug, not a caller error)
    # dispatcher-level, not raised by any action: the requested action name is
    # not served by this server at all (SPEC 25.2, revision 13)
    'unknown_action': False,
}

# plusInfo 'errorCodes' (SPEC 25.1, revision 13 — round-3 field feedback ASK 1
# and ASK 4). retryable is read from PLUS_ERROR_CODES so the two can never
# drift; this map adds the two things a client could not otherwise learn
# without the repo: whether a code is REACHABLE at all today, and what it
# actually means. 'reachable': False marks a code the vocabulary reserves but
# no code path raises — a caller must not build retry logic around it.
PLUS_ERROR_CODE_DOCS = {
    'not_found': {'reachable': True, 'meaning':
        'A named thing does not exist: note, card, media file, IO notetype, output directory, '
        'or an AnkiHub note that is not on AnkiHub / was deleted there.'},
    'invalid_param': {'reachable': True, 'meaning':
        'The request shape is wrong: the house "invalid parameter: <name>: <why>" family, plus '
        'argument-binding failures (missing required argument, unexpected keyword argument).'},
    'deck_not_found': {'reachable': True, 'meaning':
        'The named deck does not exist. Decks are never auto-created by this add-on.'},
    'duplicate': {'reachable': False, 'meaning':
        'RESERVED — never raised. Duplicates are reported per item in skipped[].reason instead.'},
    'unsupported_format': {'reachable': True, 'meaning':
        'An image could not be loaded or re-encoded (corrupt file, or a format this Qt build '
        'cannot write).'},
    'io_error': {'reachable': False, 'meaning':
        'RESERVED — never raised. Disk read/write failures surface per item in stored[].error.'},
    'batch_reverted': {'reachable': True, 'meaning':
        'An atomic batch hit a hard error and was rolled back completely; a JSON report follows '
        'the message prefix. Nothing was written.'},
    'collection_unavailable': {'reachable': True, 'meaning':
        'No collection is open (Anki is on the profile screen). RETRYABLE: the identical call '
        'succeeds once a profile is open.'},
    'sync_in_progress': {'reachable': True, 'meaning':
        'A syncNow job is mid-flight and the backend holds the collection lock, so this action '
        'was refused rather than blocking Anki. RETRYABLE: poll syncStatus until job.state '
        'leaves "syncing", then repeat the call. syncStatus, syncNow, plusInfo and ankihubStatus '
        'are never refused this way — they are how you observe and drive the sync.'},
    'not_logged_in': {'reachable': True, 'meaning':
        'A login this add-on cannot perform is required — today only the AnkiHub add-on being '
        'logged out. Requires the AnkiHub add-on to be installed to reach.'},
    'auth_failed': {'reachable': True, 'meaning':
        'A stored credential was rejected BY THE SERVER (AnkiHub HTTP 401). Distinct from '
        'not_logged_in, which is a local check. Requires the AnkiHub add-on to reach.'},
    'offline': {'reachable': False, 'meaning':
        'RESERVED — never raised. Sync network failures surface in syncStatus job.error.code and '
        "in 'required', not as an exception."},
    'full_sync_required': {'reachable': False, 'meaning':
        'RESERVED — never raised. Surfaced via the sync job error and syncStatus.required.'},
    'network_error': {'reachable': True, 'meaning':
        'Transport failure or an unexpected HTTP status (5xx included) talking to AnkiHub. '
        'RETRYABLE. Requires the AnkiHub add-on to reach.'},
    'rate_limited': {'reachable': True, 'meaning':
        'The server applied a rate limit (AnkiHub HTTP 429). RETRYABLE after a wait. Requires '
        'the AnkiHub add-on to reach.'},
    'permission_denied': {'reachable': True, 'meaning':
        'The server refused the operation (AnkiHub HTTP 403). Requires the AnkiHub add-on.'},
    'validation_error': {'reachable': True, 'meaning':
        'A well-formed request refused on semantic grounds: wrong note kind, IO note without an '
        'image, a crop that would drop every occlusion, AnkiHub HTTP 400, note already on AnkiHub.'},
    'incompatible_ankihub_addon': {'reachable': True, 'meaning':
        'The AnkiHub add-on is missing, disabled, was not loaded this session, or has drifted '
        'from the version this bridge was tested against. The bridge is unusable either way.'},
    'source_required': {'reachable': True, 'meaning':
        'An AnkiHub suggestion needs a source object/text it did not get (SPEC 19 source rules).'},
    'rationale_invalid': {'reachable': True, 'meaning':
        "An AnkiHub rationale was empty or exceeded the dialog's 1023-character cap."},
    'internal': {'reachable': True, 'meaning':
        'Something unexpected escaped an action (a backend exception or an add-on bug). The '
        'original message body is preserved after the prefix. Not a caller error — report it.'},
    'unknown_action': {'reachable': True, 'meaning':
        'No action by that name is served here. Raised by the DISPATCHER, not by an action; see '
        'the prefixing boundary note. Check plusInfo.actions and upstream AnkiConnect docs.'},
}

# The one boundary rule a client cannot infer from a single response (SPEC 25,
# revision 13): the '[code] ' prefix is NOT universal across this server.
PLUS_ERROR_PREFIX_NOTE = (
    "Prefixing boundary: errors from the 27 Plus actions AND the dispatcher's unknown-action "
    "error carry a '[code] ' prefix and populate the response's errorCode/retryable fields. "
    "EVERY OTHER error is passed through verbatim and UNPREFIXED, with errorCode: null and "
    "retryable: null — that is the ~90 UPSTREAM AnkiConnect actions, the dispatcher's api-key "
    "refusal ('valid api key must be provided', the first error a misconfigured client hits: "
    "raised by the dispatcher but deliberately uncoded, since it is not an unknown action and "
    "predates this contract), and malformed-request/JSON-schema validation failures. So "
    "error.split('] ', 1)[0].lstrip('[') is only safe when errorCode is non-null, and "
    "errorCode: null does NOT prove the failure came from an upstream action. Read errorCode; "
    "do not parse the string. Per-item error strings embedded inside a successful result "
    "(skipped[].reason, thumbnails[].error, stored[].error, cards[].error) are never prefixed "
    "and never carry these fields."
)

# Message body for the SPEC 25.2 sync guard (the prefix is added by PlusError).
# Kept here so the vocabulary and its one genuinely reachable retryable raise
# site live together; the guard itself is in plus.py, where the job state is.
SYNC_IN_PROGRESS_MESSAGE = (
    'a sync is in progress and holds the collection lock; poll syncStatus '
    'until job.state leaves "syncing", then retry'
)

# Liveness ceiling for the SPEC 25.2 guard (round-3 review fix). The guard
# refuses 23 actions with the RETRYABLE [sync_in_progress] for as long as the
# job sits in state 'syncing', so 'syncing' must be a state the add-on can
# always leave. _plusSyncDone now guarantees that under try/finally, but that
# only helps if the completion callback runs at all; if taskman never
# delivers it (Anki bug, killed worker), nothing else would ever clear the
# state and the retryable promise would be unsatisfiable until a restart.
# A job still 'syncing' this long after startedMs is therefore REAPED into a
# terminal job error (code 'error' — the §18 job-error vocabulary is
# unchanged) by syncStatus/syncNow/the guard alike, so the documented
# recovery loop (poll syncStatus until state leaves 'syncing') always
# terminates. Deliberately generous: a real sync that is still running when
# the ceiling passes goes back to pre-guard behavior (the next guarded action
# blocks on the collection mutex) — bad, but recoverable, unlike a permanent
# refusal.
SYNC_JOB_STALE_MS = 60 * 60 * 1000  # 1 hour

# AnkiHub HTTP taxonomy code (SPEC 19; kept verbatim in message bodies) ->
# SPEC 25 machine code for the '[code] ' prefix. Note the 401 mapping:
# 'ANKIHUB_NOT_LOGGED_IN' from a server 401 means the STORED token was
# rejected -> auth_failed; the local is_logged_in() check -> not_logged_in.
ANKIHUB_CODE_TO_PLUS_CODE = {
    'VALIDATION_ERROR': 'validation_error',
    'ANKIHUB_NOT_LOGGED_IN': 'auth_failed',
    'PERMISSION_DENIED': 'permission_denied',
    'NOTE_DELETED_ON_ANKIHUB': 'not_found',
    'RATE_LIMITED': 'rate_limited',
    'NETWORK_ERROR': 'network_error',
}


class PlusError(Exception):
    """Action error carrying a stable machine-parseable code (SPEC 25).

    str() renders '[code] message' — the message body is byte-identical to
    the pre-SPEC-25 error text; only the bracketed prefix is new. Callers
    recover the code with error.split('] ', 1)[0].lstrip('[').
    """

    def __init__(self, code, message):
        if code not in PLUS_ERROR_CODES:
            # a typo'd code is a bug in this add-on, never a caller error
            raise ValueError('unknown plus error code: {}'.format(code))
        super().__init__('[{}] {}'.format(code, message))
        self.code = code
        self.message = message
        self.retryable = PLUS_ERROR_CODES[code]


# plusInfo 'recipes' (SPEC 4.9, revision 10): named call patterns callers
# repeatedly failed to discover from per-action docs alone. Static — plusInfo
# must keep working before a profile is open.
PLUS_RECIPES = [
    {
        'name': 'raw field projection',
        'description': ("Raw-fidelity field projection: to read a field's EXACT stored HTML "
                        "(no stripping, no truncation) for chosen fields, call notesSlim with "
                        "fields=[...] + stripHtml=false + maxFieldLength=0. This is the "
                        "read-before-edit primitive: what it returns is byte-identical to what "
                        "bulkUpdateNoteFields/bulkReplaceInFields will operate on."),
        'example': {'action': 'notesSlim',
                    'params': {'query': 'deck:current', 'fields': ['Text'],
                               'stripHtml': False, 'maxFieldLength': 0}},
    },
    {
        'name': 'verified-sync contract',
        'description': ("The collection is verified synced iff syncStatus reports "
                        "job.state == 'done' AND required == 'no_changes' AND "
                        "mediaSyncing == false. Anything less (job error, required "
                        "normal_sync/null, media still running) means NOT verified. "
                        "Start a sync with syncNow, then poll syncStatus until the "
                        "contract holds."),
        'example': {'action': 'syncStatus', 'params': {'timeoutSecs': 8}},
    },
    {
        'name': 'dry-run-then-write pattern',
        'description': ("Preview every bulk write before committing: call the bulk action "
                        "with dryRun=true (bulkUpdateNoteFields also takes diff=true for a "
                        "per-field before/after preview; bulkReplaceInFields previews on every "
                        "dry run), inspect wouldAdd/wouldUpdate/wouldChange + skipped, then "
                        "repeat the identical call with dryRun=false. Dry and real runs share "
                        "the same validation code by construction, so the real run's writes "
                        "match the dry prediction — with one caveat: a bulkUpdateNoteFields "
                        "batch that repeats the same note id may predict MORE updates (and "
                        "duplicate preview entries) than the real sequential run performs, "
                        "because the dry pass compares every entry against stored pre-batch "
                        "values while the real run re-reads the note after each write; the "
                        "final note state still matches the last entry. De-duplicate ids per "
                        "batch for exact parity."),
        'example': {'action': 'bulkUpdateNoteFields',
                    'params': {'notes': [{'id': 1712345678901,
                                          'fields': {'Front': 'new value'}}],
                               'dryRun': True, 'diff': True}},
    },
    {
        'name': 'undo-label convention',
        'description': ("Pass undoLabel on any write action to name its undo entry "
                        "'AnkiConnect Plus: <label>' (whitespace collapsed, 80-char cap) so "
                        "multiple batches stay distinguishable in Anki's Undo menu; the "
                        "response's undoEntry always reports the ACTUAL final entry name "
                        "(null when nothing undoable was written)."),
        'example': {'action': 'bulkAddTags',
                    'params': {'noteIds': [1712345678901], 'tags': 'reviewed',
                               'undoLabel': 'PI 7 tag sweep'}},
    },
    {
        'name': 'suspended-draft workflow',
        'description': ("This fork ships one DELIBERATE deviation from Anki's own "
                        "behavior plus one opt-in mode, both switchable (SPEC 27). (1) bulkAddNotes can leave the "
                        "cards it creates SUSPENDED — opt in via param 'suspend' or config "
                        "'suspendNewCards' (ships false) — and lists them in 'suspended', "
                        "so a generated batch lands as a draft: write suspended -> a human "
                        "reads them in the browser -> that human unsuspends. (2) "
                        "bulkSetDueDate PUTS BACK the suspensions anki's set_due_date "
                        "silently clears (param 'preserveSuspended', config "
                        "'preserveSuspendedOnReschedule', default true), reporting both "
                        "'unsuspended' (what anki revived mid-call) and 'resuspended' "
                        "(what this add-on put back) — subtract the second from the first "
                        "for the cards actually left in review. Both re-suspensions are "
                        "merged into the action's OWN undo entry, so a single Ctrl+Z "
                        "reverts the whole thing; buried cards are deliberately NOT re-"
                        "buried. Set either param explicitly to override the config for "
                        "one call: suspend=false / preserveSuspended=false restore stock "
                        "Anki behavior. Preview either with dryRun=true "
                        "('wouldSuspend' / 'wouldResuspend')."),
        'example': {'action': 'bulkAddNotes',
                    'params': {'notes': [{'deckName': 'Draft', 'modelName': 'Basic',
                                          'fields': {'Front': 'q', 'Back': 'a'}}],
                               'suspend': True,
                               'undoLabel': 'PI 7 draft batch'}},
    },
    {
        'name': 'lean deck sweep',
        'description': ("Reading a whole deck cheaply: call notesSlim with "
                        "omitEmptyFields=true (empty fields are dropped from every "
                        "note's fields dict) and a fields=[...] projection when you "
                        "know which fields you need. On wide notetypes (AnKing-derived, "
                        "19 fields of which ~4 are populated) omitEmptyFields alone cuts "
                        "the payload roughly in half and the call is FASTER. Pair with "
                        "renderCard cssMode='byNotetype' (or format='text', where CSS is "
                        "omitted by default) when you also need rendered cards — the "
                        "notetype stylesheet would otherwise repeat once per card."),
        'example': {'action': 'notesSlim',
                    'params': {'query': 'deck:current', 'omitEmptyFields': True,
                               'limit': 200}},
    },
    {
        'name': 'reading errors',
        'description': ("Never parse the error string. An error response is "
                        "{result: null, error: '[code] message', errorCode: str|null, "
                        "retryable: bool|null}. Branch on errorCode: null means the error "
                        "came from an UPSTREAM AnkiConnect action and carries no code (the "
                        "'[code] ' prefix is absent too), so treat it as opaque. "
                        "retryable=true means the IDENTICAL call may succeed later with no "
                        "change by you — today that is collection_unavailable (open a "
                        "profile), sync_in_progress (poll syncStatus until job.state leaves "
                        "'syncing'), network_error and rate_limited (wait, then retry). "
                        "Everything else needs a different request. plusInfo.errorCodes is "
                        "the full vocabulary with retryable/reachable/meaning, so a client "
                        "can build its retry table at runtime instead of hardcoding one. "
                        "Inside upstream 'multi' each sub-response is formatted "
                        "INDEPENDENTLY, and only the failing ones carry the four keys: a "
                        "FAILING sub-action gets the full {result, error, errorCode, "
                        "retryable} envelope, while a SUCCEEDING one gets {result, error: "
                        "null} — or, if that sub-action omitted \"version\", the bare "
                        "result with no envelope at all (the handler defaults version to 4). "
                        "So test that the sub-response is a dict and that sub.get('error') is "
                        "non-null BEFORE reading errorCode; never index errorCode "
                        "unconditionally. Check per sub-response, never on the outer reply, "
                        "which reports success even when every sub-action failed. Call this "
                        "example once at startup and build your retry table from the "
                        "errorCodes map it returns."),
        'example': {'action': 'plusInfo', 'params': {}},
    },
]

UNDO_BULK_ADD = 'AnkiConnect Plus: Bulk Add'
UNDO_BULK_UPDATE = 'AnkiConnect Plus: Bulk Update'
UNDO_BULK_TAGS = 'AnkiConnect Plus: Bulk Tags'
UNDO_CROP_IMAGE = 'AnkiConnect Plus: Crop Image'
UNDO_CROP_IO = 'AnkiConnect Plus: Crop IO Image'
UNDO_BULK_SUSPEND = 'AnkiConnect Plus: Bulk Suspend'
UNDO_BULK_DUE = 'AnkiConnect Plus: Bulk Due Date'
UNDO_BULK_REPLACE = 'AnkiConnect Plus: Replace in Fields'

# undoLabel (SPEC 24): every write action takes an optional undoLabel whose
# sanitized form becomes the undo entry name 'AnkiConnect Plus: <label>', so
# the Undo menu can distinguish same-action batches. sanitize_undo_label().
UNDO_LABEL_PREFIX = 'AnkiConnect Plus: '
UNDO_LABEL_MAX_CHARS = 80

# cards.queue: -1 = suspended; any negative queue (-1 suspended, -2 sibling-
# buried, -3 manually buried) is restored by the backend unsuspend op (SPEC 16)
QUEUE_SUSPENDED = -1

#
# Suspension control (SPEC 27, spec revision 15). BOTH defaults are True, which
# means this fork DELIBERATELY DEVIATES from Anki's native behavior on two
# actions -- see SPEC 27 and README for the full rationale and the switch-off:
#   * bulkSetDueDate: anki's own set_due_date turns every targeted card into a
#     review card, silently RESURRECTING suspended ones. Left alone, one
#     deck-wide reschedule can revive every leech you ever suspended. With
#     preserve_suspended the cards that were suspended before the call are put
#     back afterwards, inside the SAME undo entry.
#   * bulkAddNotes: new cards are left suspended so a generated draft batch
#     never enters review before a human has read it.
# These constants are the documented fallback used whenever the parameter is
# None AND no usable config value exists; connect_plus/config.json ships the
# same two values under CONFIG_PRESERVE_SUSPENDED / CONFIG_SUSPEND_NEW_CARDS
# and util.DEFAULT_CONFIG mirrors them (all three are locked in lockstep by a
# test). core.py never reads config itself -- it is aqt-free, so plus.py
# resolves the config and passes an explicit bool down. An explicit parameter
# always wins over config; config wins over these constants.
#
DEFAULT_PRESERVE_SUSPENDED_ON_RESCHEDULE = True
DEFAULT_SUSPEND_NEW_CARDS = False
CONFIG_PRESERVE_SUSPENDED = 'preserveSuspendedOnReschedule'
CONFIG_SUSPEND_NEW_CARDS = 'suspendNewCards'

# reserved 'field' name for the tag row of a bulkUpdateNoteFields dry-run diff
# preview (SPEC 4.2, revision 12). Anki does NOT forbid a notetype field
# literally named '__tags__' (probe-verified: models.add accepts it), so the
# collision is possible-but-pathological and is documented rather than
# defended against; a note's field rows are always emitted BEFORE its tag row.
TAGS_PREVIEW_FIELD = '__tags__'

# default target folder for exportDeckApkg when outPath is omitted (SPEC 17)
EXPORT_DEFAULT_DIR = os.path.expanduser('~/Downloads')

IO_STOCK_KIND = 6

# Formats QImageWriter can encode on this Qt build (probe-verified, SPEC 11.3).
# QImage can READ more (gif/svg/svgz/pdf/tga); crops of those re-encode as PNG.
CROP_WRITE_FORMATS = {'bmp', 'cur', 'heic', 'heif', 'icns', 'ico', 'jfif', 'jp2',
                      'jpeg', 'jpg', 'pbm', 'pgm', 'png', 'ppm', 'tif', 'tiff',
                      'wbmp', 'webp', 'xbm', 'xpm'}

# pixel tolerance when deciding whether a remapped occlusion rect was actually
# trimmed by the crop (absorbs float noise from the 4-decimal stored coords)
CLIP_EPS_PX = 1e-6

# SQLite allows at most 32766 bound variables per statement; chunk IN-lists
# well below that so fixed parameters (mid, dids, since/until, limit) still fit.
SQL_IN_CHUNK = 15000

# read-only action caps (SPEC 13, 14): oversized requests are clamped, not rejected
NOTES_SLIM_LIMIT_CAP = 2000
# checkDeckIntegrity's collection-wide orphan array is capped by default
# (SPEC 20, revision 12); the full size always ships as orphanMediaCount
ORPHAN_MEDIA_DEFAULT_LIMIT = 100
THUMBNAIL_DIM_CAP = 1024
THUMBNAIL_FORMATS = {'jpeg', 'png'}

# SyncStatusResponse.Required / SyncCollectionResponse.ChangesRequired proto
# enum -> stable string maps (SPEC 18). Any post-sync required != 0 means a
# normal sync cannot converge, so plus.py refuses with full_sync_required.
SYNC_STATUS_REQUIRED = {0: 'no_changes', 1: 'normal_sync', 2: 'full_sync_required'}
SYNC_COLLECTION_REQUIRED = {0: 'no_changes', 1: 'normal_sync', 2: 'full_sync',
                            3: 'full_download', 4: 'full_upload'}


#
# Shared helpers
#

def io_num(v):
    s = '{:.4f}'.format(float(v))
    if s.startswith('0.'):
        s = s[1:]
    return s


def serialize_occlusions(shapes, hide_all_guess_one=True):
    if not isinstance(shapes, list):
        raise PlusError('invalid_param', 'invalid parameter: occlusions: string or array required')
    if not shapes:
        raise PlusError('invalid_param', 'invalid parameter: occlusions: at least one occlusion required')

    clozes = []
    for i, shape in enumerate(shapes):
        if not isinstance(shape, dict):
            raise PlusError('invalid_param', 'invalid parameter: occlusions[{}]: object required'.format(i))
        for key in ('left', 'top', 'width', 'height'):
            value = shape.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise PlusError('invalid_param', 'invalid parameter: occlusions[{}]: {} must be a number'.format(i, key))
        left, top = shape['left'], shape['top']
        width, height = shape['width'], shape['height']
        if not (0 <= left <= 1) or not (0 <= top <= 1):
            raise PlusError('invalid_param', 'invalid parameter: occlusions[{}]: left and top must be within 0-1'.format(i))
        if not (0 < width <= 1) or not (0 < height <= 1):
            raise PlusError('invalid_param', 'invalid parameter: occlusions[{}]: width and height must be within 0-1'.format(i))
        # io_num serializes at 4 decimal places; reject sizes that would
        # round to a zero-width/zero-height rect despite passing the range check
        if float('{:.4f}'.format(float(width))) == 0 or float('{:.4f}'.format(float(height))) == 0:
            raise PlusError('invalid_param', 'invalid parameter: occlusions[{}]: width and height must be at least 0.00005'.format(i))
        ordinal = shape.get('ordinal', i + 1)
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0:
            raise PlusError('invalid_param', 'invalid parameter: occlusions[{}]: ordinal must be a non-negative integer'.format(i))

        properties = 'left={}:top={}:width={}:height={}'.format(
            io_num(left), io_num(top), io_num(width), io_num(height))
        if hide_all_guess_one:
            properties += ':oi=1'
        clozes.append('{{{{c{}::image-occlusion:rect:{}}}}}'.format(ordinal, properties))

    return '<br>'.join(clozes)


def parse_io_response_occlusions(resp_note):
    entries = []
    for occlusion in resp_note.occlusions:
        for shape in occlusion.shapes:
            properties = {prop.name: prop.value for prop in shape.properties}
            entry = {'ordinal': occlusion.ordinal, 'shape': shape.shape}
            if shape.shape == 'rect':
                try:
                    for key in ('left', 'top', 'width', 'height'):
                        entry[key] = float(properties.pop(key))
                except (KeyError, ValueError):
                    entry = {'ordinal': occlusion.ordinal, 'shape': shape.shape,
                             'properties': {prop.name: prop.value for prop in shape.properties}}
                else:
                    if properties:
                        entry['properties'] = properties
            else:
                entry['properties'] = properties
            entries.append(entry)
    return entries


def find_io_notetype_id(col):
    for notetype in col.models.all():
        if notetype.get('originalStockKind') == IO_STOCK_KIND:
            return notetype['id']
    notetype = col.models.by_name('Image Occlusion')
    if notetype is not None:
        return notetype['id']
    raise PlusError('not_found', 'image occlusion notetype not found')


def sanitize_undo_label(label):
    """None -> None (the action keeps its default undo entry name). A string
    -> 'AnkiConnect Plus: <label>' with whitespace runs (newlines included)
    collapsed to single spaces, ends stripped, and the label capped at 80
    characters (SPEC 24). Anything else — or a label that sanitizes to
    nothing — is a parameter error, raised before any write."""
    if label is None:
        return None
    if not isinstance(label, str):
        raise PlusError('invalid_param', 'invalid parameter: undoLabel: string required')
    cleaned = ' '.join(label.split())[:UNDO_LABEL_MAX_CHARS].rstrip()
    if not cleaned:
        raise PlusError('invalid_param', 'invalid parameter: undoLabel: non-empty string required')
    return UNDO_LABEL_PREFIX + cleaned


def _revert_batch(col, undo_name):
    # Reverts the batch's merged undo entry. Also called when zero ops merged
    # into the entry: undoing an empty custom entry is a data no-op but pops
    # it off the stack, so we never leave a do-nothing item in the Undo menu
    # (SPEC Deviation #7).
    #
    # Returns True iff the undo actually fired. Our entry is only ours to pop
    # while it is still on TOP: if an op succeeded but its merge_undo_entries
    # raised, anki's own entry ("Suspend", ...) sits above ours, the name check
    # fails and nothing is reverted. A caller about to TELL the world "batch
    # reverted" must branch on this — a false 'reverted' makes the caller's
    # retry duplicate the writes (SPEC 27.4, revision 15 fix pass).
    if col.undo_status().undo == undo_name:
        col.undo()
        return True
    return False


def _pop_empty_undo(col, target, written, undo_name):
    # Non-atomic path: the lazily created entry stayed empty because every
    # write after its creation failed; drop it so the UI matches undoEntry=null.
    if target is not None and not written:
        _revert_batch(col, undo_name)


def _batch_error(action, undo_name, count_key, index, error, count, skipped):
    report = {'failedIndex': index, 'error': str(error), count_key: count, 'skipped': skipped}
    return PlusError('batch_reverted', '{} failed (batch reverted): {}'.format(
        action, json.dumps(report, separators=(',', ':'))))


def resolve_suspension_flag(value, name, default):
    """Resolve a suspension-control parameter (SPEC 27).

    None -> the documented default (a plus.py wrapper has usually already
    replaced None with the config value, so None here means "nothing said
    anywhere"); a real bool -> itself; anything else is a parameter error
    raised BEFORE any write, so a typo can never half-apply a policy.
    """
    if value is None:
        return default
    if not isinstance(value, bool):
        raise PlusError('invalid_param',
                        'invalid parameter: {}: boolean required'.format(name))
    return value


def _validate_tag_list(tags, name):
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise PlusError('invalid_param', 'invalid parameter: {}: list of strings required'.format(name))


def tag_registry_map(col):
    """{lowercased tag: the spelling the collection has REGISTERED}.

    One col.tags.all() read, hoisted out of per-note loops on purpose: on a
    real AnKing-sized collection the registry is ~10k strings, so calling it
    once per note in a bulk batch would dominate the call.
    """
    registered = {}
    for existing in col.tags.all():
        registered.setdefault(existing.lower(), existing)
    return registered


def canonify_tags(tags, registry):
    """Predict the tag list anki will actually STORE for a requested list.

    Round-3 review fix. `note.tags = list(tags); col.update_note(note)` does
    not store `tags` — the backend canonifies on save, and every step of that
    is observable from the outside. Measured on scratch collections:

        ['beta','alpha']        -> ['alpha','beta']    (sorted)
        ['alpha','alpha']       -> ['alpha']           (de-duplicated)
        ['  alpha  ']           -> ['alpha']           (whitespace stripped)
        ['gamma delta']         -> ['delta','gamma']   (ONE request -> TWO tags)
        ['Beta','beta']         -> ['Beta']            (case-insensitive dedup,
                                                        first occurrence wins)
        ['Zed','apple']         -> ['apple','Zed']     (sort is case-INsensitive)
        ['BETA'] with 'beta'
          already registered    -> ['beta']            (registry spelling wins)

    That last rule is why `registry` (from tag_registry_map) is a parameter:
    the backend matches each tag case-insensitively against the collection's
    registered tag list and stores the REGISTERED spelling. The match is on
    the FULL tag — a registered `Parent::Child` does not lend its case to a
    new `parent::other`, probe-verified. So the prediction is
    collection-dependent and cannot be a pure string function.

    Used for two things that were both wrong before: the `__tags__` dry-run
    preview row's `after` (which promised the raw request, a post-state the
    write would not produce) and the shared no-op comparison (which compared
    the raw request against already-canonical stored tags, so an identical
    repeat of any non-canonical request always re-wrote the note — mod/usn
    bump plus an undo entry for no net change).

    `col.tags.canonify()` is NOT usable: it is a deprecated no-op stub in
    25.09.4 (SP/anki/tags.py:144, verified — it returns its input unchanged)
    and there is no canonify RPC to call instead.

    Two documented approximations, neither of which can cause a wrong write —
    the worst case is a preview row or a no-op suppression that reverts to
    the old (over-reporting) behavior:
      * case folding uses python's str.lower(), the backend uses rust
        unicase. They agree on ASCII and on ordinary accented text (probe:
        'Ärger'/'ärger' de-duplicate identically); exotic pairs such as
        'STRASSE'/'straße' could differ.
      * `registry` is a snapshot. Inside one bulk batch an earlier entry can
        register a tag that a later entry names with different case; the
        later entry is canonified against the pre-batch registry.
    """
    requested = ' '.join(tags).split()
    deduped = {}
    for tag in requested:
        key = tag.lower()
        # first occurrence wins, then the registry spelling overrides it
        deduped.setdefault(key, registry.get(key, tag))
    return sorted(deduped.values(), key=str.lower)


#
# Bulk actions
#

def bulk_add_notes(col, notes, atomic=True, allow_duplicates=False, dry_run=False,
                   suspend=None, undo_label=None):
    undo_name = sanitize_undo_label(undo_label) or UNDO_BULK_ADD
    if not isinstance(notes, list):
        raise PlusError('invalid_param', 'invalid parameter: notes: list required')
    # SPEC 27: suspend the cards this batch creates. Resolved (and type-checked)
    # before the empty-list early return so every return shape below can report
    # the decision, and before any write so a bad value never lands a half-batch.
    suspend_new = resolve_suspension_flag(suspend, 'suspend', DEFAULT_SUSPEND_NEW_CARDS)
    if not notes:
        if dry_run:
            return {'wouldAdd': 0, 'wouldSuspend': suspend_new, 'skipped': [],
                    'undoEntry': None}
        return {'added': [], 'suspended': [], 'skipped': [], 'undoEntry': None}
    for i, note in enumerate(notes):
        if not isinstance(note, dict):
            raise PlusError('invalid_param', 'invalid parameter: notes[{}]: object required'.format(i))

    # resolution pass: no writes
    resolved = []
    for i, note in enumerate(notes):
        modelName = note.get('modelName')
        if modelName is not None and not isinstance(modelName, str):
            resolved.append({'skip': 'invalid parameter: notes[{}].modelName: string required'.format(i)})
            continue
        model = col.models.by_name(modelName) if modelName else None
        if model is None:
            resolved.append({'skip': 'model was not found: {}'.format(modelName)})
            continue
        deckName = note.get('deckName')
        if deckName is not None and not isinstance(deckName, str):
            resolved.append({'skip': 'invalid parameter: notes[{}].deckName: string required'.format(i)})
            continue
        did = col.decks.id_for_name(deckName) if deckName else None
        if did is None:
            resolved.append({'skip': 'deck was not found: {}'.format(deckName)})
            continue

        fields = note.get('fields') or {}
        if not isinstance(fields, dict):
            resolved.append({'skip': 'invalid parameter: notes[{}].fields: object required'.format(i)})
            continue
        fieldNames = {fld['name'] for fld in model['flds']}
        unknown = next((name for name in fields if name not in fieldNames), None)
        if unknown is not None:
            resolved.append({'skip': 'field was not found in model: {}'.format(unknown)})
            continue
        badValue = next((name for name, value in fields.items() if not isinstance(value, str)), None)
        if badValue is not None:
            resolved.append({'skip': 'invalid parameter: notes[{}].fields.{}: string required'.format(i, badValue)})
            continue

        tags = note.get('tags') or []
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            resolved.append({'skip': 'invalid parameter: notes[{}].tags: list of strings required'.format(i)})
            continue

        options = note.get('options') or {}
        allow = options.get('allowDuplicate', allow_duplicates) if isinstance(options, dict) else allow_duplicates
        if not isinstance(allow, bool):
            resolved.append({'skip': 'invalid parameter: notes[{}].options.allowDuplicate: boolean required'.format(i)})
            continue

        firstField = model['flds'][0]['name']
        stripped = anki.utils.strip_html_media(fields.get(firstField, ''))
        if not stripped.strip():
            resolved.append({'skip': 'empty first field'})
            continue

        resolved.append({
            'model': model,
            'did': did,
            'fields': fields,
            'tags': tags,
            'allow': allow,
            'csum': anki.utils.field_checksum(fields.get(firstField, '')),
            'stripped': stripped,
        })

    # duplicate precheck: one read-only select per distinct mid
    csumsByMid = {}
    for entry in resolved:
        if 'skip' not in entry:
            csumsByMid.setdefault(entry['model']['id'], set()).add(entry['csum'])

    existingByMid = {}
    for mid, csums in csumsByMid.items():
        existing = set()
        csumList = sorted(csums)
        for start in range(0, len(csumList), SQL_IN_CHUNK):
            chunk = csumList[start:start + SQL_IN_CHUNK]
            placeholders = ','.join('?' * len(chunk))
            rows = col.db.all(
                'select csum, flds from notes where mid = ? and csum in ({})'.format(placeholders),
                mid, *chunk)
            existing.update(anki.utils.strip_html_media(flds.split('\x1f')[0]) for _, flds in rows)
        existingByMid[mid] = existing

    seen = set()
    for entry in resolved:
        if 'skip' in entry:
            continue
        key = (entry['model']['id'], entry['stripped'])
        if not entry['allow']:
            if entry['stripped'] in existingByMid.get(entry['model']['id'], set()):
                entry['skip'] = 'duplicate'
                continue
            if key in seen:
                entry['skip'] = 'duplicate (within batch)'
                continue
        seen.add(key)

    # dry run: everything above IS the real path's validation (resolution pass
    # + duplicate precheck, both read-only); stop at the zero-write boundary
    # so the two paths cannot drift (SPEC 15)
    if dry_run:
        skipped = [{'index': i, 'reason': entry['skip']}
                   for i, entry in enumerate(resolved) if 'skip' in entry]
        # 'wouldSuspend' is the resolved DECISION, not a count: card ids (and
        # even the card COUNT, for a cloze notetype) do not exist until a real
        # add, so a number here would be a guess (SPEC 15, 27).
        return {'wouldAdd': len(resolved) - len(skipped), 'wouldSuspend': suspend_new,
                'skipped': skipped, 'undoEntry': None}

    # write pass
    added = []
    skipped = []
    target = None
    for i, entry in enumerate(resolved):
        if 'skip' in entry:
            skipped.append({'index': i, 'reason': entry['skip']})
            continue
        try:
            ankiNote = anki.notes.Note(col, entry['model'])
            for name, value in entry['fields'].items():
                ankiNote[name] = value
            ankiNote.tags = list(entry['tags'])
            if target is None:
                target = col.add_custom_undo_entry(undo_name)
            col.add_note(ankiNote, entry['did'])
            col.merge_undo_entries(target)
            added.append(ankiNote.id)
        except Exception as e:
            if atomic:
                _revert_batch(col, undo_name)
                raise _batch_error('bulkAddNotes', undo_name, 'addedBeforeRevert', i, e, len(added), skipped)
            skipped.append({'index': i, 'reason': str(e)})

    # SPEC 27: leave the batch's new cards suspended, INSIDE the same undo
    # entry (one Ctrl+Z must not leave notes added but unsuspended). Cards are
    # collected per note via col.card_ids_of_note (no raw SQL) and suspended in
    # ONE op after the loop; freshly created cards are queue 0, so the op
    # changes every one of them and 'suspended' == the ids passed to it.
    suspended = []
    if suspend_new and added:
        for nid in added:
            suspended.extend(col.card_ids_of_note(nid))
        try:
            suspendOp = col.sched.suspend_cards(suspended)
            col.merge_undo_entries(target)
        except Exception as e:
            # A failure HERE is always fatal, even under atomic=false: the
            # caller asked for suspended drafts, and handing back added-but-
            # live notes while reporting success is exactly the silent
            # divergence this add-on refuses to ship. 'failedStep' replaces
            # 'failedIndex' because the step is not per-note.
            reverted = _revert_batch(col, undo_name)
            if reverted:
                report = {'failedStep': 'suspend', 'error': str(e),
                          'addedBeforeRevert': len(added), 'skipped': skipped}
                raise PlusError('batch_reverted',
                                'bulkAddNotes failed (batch reverted): {}'.format(
                                    json.dumps(report, separators=(',', ':'))))
            # The revert could NOT run (our entry was no longer on top —
            # suspend_cards succeeded and only the merge failed, so anki's own
            # entry is above ours). Say exactly that and name what is still in
            # the collection: claiming 'reverted' here would make a retry
            # create the notes twice (SPEC 4.1/27.4).
            report = {'failedStep': 'suspend', 'error': str(e), 'reverted': False,
                      'addedStillCommitted': len(added), 'addedIds': added,
                      'skipped': skipped}
            raise PlusError('internal',
                            'bulkAddNotes failed (batch NOT reverted): {}'.format(
                                json.dumps(report, separators=(',', ':'))))
        # Honesty cross-check (SPEC 27.4): 'suspended' must be post-op state,
        # not the ids we handed the backend. suspend_cards is the one scheduler
        # op that answers authoritatively (OpChangesWithCount) and every
        # freshly created card is queue 0, so the count MUST equal the ids
        # passed; if it ever does not, re-read the queues and report only the
        # cards that really are suspended rather than over-claiming.
        suspendCount = getattr(suspendOp, 'count', None)
        if suspendCount is not None and suspendCount != len(suspended):
            confirmed = []
            for cid in suspended:
                try:
                    if col.get_card(cid).queue == QUEUE_SUSPENDED:
                        confirmed.append(cid)
                except NotFoundError:  # pragma: no cover - handlers are serialized
                    continue
            suspended = confirmed

    _pop_empty_undo(col, target, added, undo_name)
    return {'added': added, 'suspended': suspended, 'skipped': skipped,
            'undoEntry': undo_name if added else None}


def bulk_update_note_fields(col, notes, atomic=True, dry_run=False, diff=False,
                            max_preview=20, undo_label=None):
    undo_name = sanitize_undo_label(undo_label) or UNDO_BULK_UPDATE
    if not isinstance(notes, list):
        raise PlusError('invalid_param', 'invalid parameter: notes: list required')
    if not isinstance(diff, bool):
        raise PlusError('invalid_param', 'invalid parameter: diff: boolean required')
    if isinstance(max_preview, bool) or not isinstance(max_preview, int) or max_preview < 0:
        raise PlusError('invalid_param', 'invalid parameter: maxPreview: int >= 0 required')
    if diff and not dry_run:
        # diff is a preview feature (SPEC 4.2, revision 10); the real run
        # stays lean — reading before-values back would double its cost
        raise PlusError('invalid_param', 'invalid parameter: diff: only valid with dryRun')

    updated = []
    unchanged = []
    skipped = []
    preview = []       # dryRun+diff only: [{noteId, field, before, after}], capped
    diffTotal = 0      # changed-field entries found, INCLUDING those past the cap
    target = None
    tagRegistry = None  # lazy: one col.tags.all() read, only if some entry has tags
    for i, entry in enumerate(notes):
        if not isinstance(entry, dict):
            skipped.append({'index': i, 'reason': 'invalid parameter: notes[{}]: object required'.format(i)})
            continue
        nid = entry.get('id')
        if isinstance(nid, bool) or not isinstance(nid, int):
            skipped.append({'index': i, 'reason': 'invalid parameter: notes[{}]: id required'.format(i)})
            continue
        fields = entry.get('fields')
        tags = entry.get('tags')
        if fields is None and tags is None:
            skipped.append({'index': i, 'reason': 'invalid parameter: notes[{}]: fields or tags required'.format(i)})
            continue
        if fields is not None and not isinstance(fields, dict):
            skipped.append({'index': i, 'reason': 'invalid parameter: notes[{}].fields: object required'.format(i)})
            continue
        if tags is not None and (not isinstance(tags, list) or not all(isinstance(t, str) for t in tags)):
            skipped.append({'index': i, 'reason': 'invalid parameter: notes[{}].tags: list of strings required'.format(i)})
            continue

        try:
            ankiNote = col.get_note(nid)
        except NotFoundError:
            skipped.append({'index': i, 'reason': 'note was not found: {}'.format(nid)})
            continue

        # validate the whole entry before mutating the note
        if fields is not None:
            unknown = next((name for name in fields if name not in ankiNote), None)
            if unknown is not None:
                skipped.append({'index': i, 'reason': 'field was not found in note: {}'.format(unknown)})
                continue
            badValue = next((name for name, value in fields.items() if not isinstance(value, str)), None)
            if badValue is not None:
                skipped.append({'index': i, 'reason': 'invalid parameter: notes[{}].fields.{}: string required'.format(i, badValue)})
                continue

        # tags are compared and previewed in the form anki will actually
        # STORE, not as requested (round-3 review fix; see canonify_tags).
        # Comparing the raw request against already-canonical stored tags made
        # an identical repeat of any non-canonical request ('gamma delta',
        # ['b','a'], ['x','X'], ' padded ') report 'updated' and re-write the
        # note every time, for no net data change.
        if tags is not None:
            if tagRegistry is None:
                tagRegistry = tag_registry_map(col)
            canonTags = canonify_tags(tags, tagRegistry)
        else:
            canonTags = None

        # no-op detection (shared rule with bulkAddTags, SPEC 4.2/4.3): an
        # entry whose requested fields AND tags all byte-match the note's
        # current values is never written — it lands in 'unchanged', creates
        # no undo entry, and the check is read-only so the dry and real paths
        # share it by construction (SPEC 15)
        if ((fields is None or all(ankiNote[name] == value for name, value in fields.items()))
                and (canonTags is None or canonTags == ankiNote.tags)):
            unchanged.append(nid)
            continue

        # dry run: full per-entry validation done, nothing read past this point
        # touches the collection or the in-memory Note (SPEC 15)
        if dry_run:
            updated.append(nid)
            if diff:
                # one preview entry PER CHANGED FIELD, unchanged fields
                # omitted (byte comparison against the loaded note — the
                # same read the no-op check above already performs)
                if fields is not None:
                    for name, value in fields.items():
                        if ankiNote[name] == value:
                            continue
                        diffTotal += 1
                        if len(preview) < max_preview:
                            preview.append({'noteId': nid, 'field': name,
                                            'before': ankiNote[name], 'after': value})
                # ...plus ONE row for a tag change, under the reserved field
                # name '__tags__' (SPEC 4.2, revision 12 — round-3 field
                # feedback: a tags-only entry previously landed in wouldUpdate
                # with no preview row at all, so a reviewer saw a note slated
                # for an update with no visible reason). Emitted after the
                # note's field rows, values space-joined in list order.
                # 'after' is the CANONIFIED form — what the write will
                # really store — not the raw request (round-3 review fix)
                if canonTags is not None and canonTags != ankiNote.tags:
                    diffTotal += 1
                    if len(preview) < max_preview:
                        preview.append({'noteId': nid, 'field': TAGS_PREVIEW_FIELD,
                                        'before': ' '.join(ankiNote.tags),
                                        'after': ' '.join(canonTags)})
            continue

        try:
            if fields is not None:
                for name, value in fields.items():
                    ankiNote[name] = value
            if tags is not None:
                ankiNote.tags = list(tags)
            if target is None:
                target = col.add_custom_undo_entry(undo_name)
            col.update_note(ankiNote)
            col.merge_undo_entries(target)
            updated.append(nid)
        except Exception as e:
            if atomic:
                _revert_batch(col, undo_name)
                raise _batch_error('bulkUpdateNoteFields', undo_name, 'updatedBeforeRevert', i, e, len(updated), skipped)
            skipped.append({'index': i, 'reason': str(e)})

    if dry_run:
        result = {'wouldUpdate': updated, 'unchanged': unchanged, 'skipped': skipped,
                  'undoEntry': None}
        if diff:
            # additive keys, present only when diff was requested (SPEC 4.2)
            result['preview'] = preview
            result['previewTruncated'] = diffTotal > len(preview)
        return result
    _pop_empty_undo(col, target, updated, undo_name)
    return {'updated': updated, 'unchanged': unchanged, 'skipped': skipped,
            'undoEntry': undo_name if updated else None}


def bulk_add_tags(col, note_ids, tags, atomic=True, dry_run=False, undo_label=None):
    undo_name = sanitize_undo_label(undo_label) or UNDO_BULK_TAGS
    if not isinstance(note_ids, list):
        raise PlusError('invalid_param', 'invalid parameter: noteIds: list required')
    if not all(isinstance(nid, int) and not isinstance(nid, bool) for nid in note_ids):
        raise PlusError('invalid_param', 'invalid parameter: noteIds: ints required')
    if isinstance(tags, str):
        tagList = tags.split()
    elif isinstance(tags, list) and all(isinstance(t, str) for t in tags):
        tagList = [t for tag in tags for t in tag.split()]
    else:
        raise PlusError('invalid_param', 'invalid parameter: tags: string or list of strings required')
    if not tagList:
        raise PlusError('invalid_param', 'invalid parameter: tags: at least one tag required')

    updated = []
    skipped = []
    target = None
    for i, nid in enumerate(note_ids):
        try:
            ankiNote = col.get_note(nid)
        except NotFoundError:
            skipped.append({'index': i, 'reason': 'note was not found: {}'.format(nid)})
            continue
        missing = [t for t in tagList if not ankiNote.has_tag(t)]
        if not missing:
            continue
        # dry run: same no-op detection as the real path, zero writes (SPEC 15)
        if dry_run:
            updated.append(nid)
            continue
        try:
            for t in missing:
                ankiNote.add_tag(t)
            if target is None:
                target = col.add_custom_undo_entry(undo_name)
            col.update_note(ankiNote)
            col.merge_undo_entries(target)
            updated.append(nid)
        except Exception as e:
            if atomic:
                _revert_batch(col, undo_name)
                raise _batch_error('bulkAddTags', undo_name, 'updatedBeforeRevert', i, e, len(updated), skipped)
            skipped.append({'index': i, 'reason': str(e)})

    if dry_run:
        return {'wouldUpdate': updated, 'skipped': skipped, 'undoEntry': None}
    _pop_empty_undo(col, target, updated, undo_name)
    return {'updated': updated, 'skipped': skipped, 'undoEntry': undo_name if updated else None}


#
# Image occlusion
#

def add_image_occlusion_note(col, image_path=None, image_data_b64=None, image_filename=None,
                             occlusions=None, header="", back_extra="",
                             tags=None, deck_name=None, hide_all_guess_one=True,
                             undo_label=None):
    undo_name = sanitize_undo_label(undo_label)
    if (image_path is None) == (image_data_b64 is None):
        raise PlusError('invalid_param', 'invalid parameter: image: exactly one of path or data required')

    if isinstance(occlusions, str):
        occlusionsStr = occlusions
    elif isinstance(occlusions, list):
        occlusionsStr = serialize_occlusions(occlusions, hide_all_guess_one)
    else:
        raise PlusError('invalid_param', 'invalid parameter: occlusions: string or array required')

    if not isinstance(header, str):
        raise PlusError('invalid_param', 'invalid parameter: header: string required')
    if not isinstance(back_extra, str):
        raise PlusError('invalid_param', 'invalid parameter: backExtra: string required')
    tags = tags or []
    _validate_tag_list(tags, 'tags')

    if deck_name is not None and not isinstance(deck_name, str):
        raise PlusError('invalid_param', 'invalid parameter: deckName: string required')
    did = col.decks.id_for_name(deck_name) if deck_name else None
    if did is None:
        raise PlusError('deck_not_found', 'deck was not found: {}'.format(deck_name))

    imageData = None
    if image_data_b64 is not None:
        if not image_filename or not isinstance(image_filename, str):
            raise PlusError('invalid_param', 'invalid parameter: image.filename: required with data')
        if not isinstance(image_data_b64, str):
            raise PlusError('invalid_param', 'invalid parameter: image.data: string required')
        try:
            # tolerate MIME/RFC-2045 line-wrapped base64 (as upstream's lenient
            # media path does) while still rejecting garbage via validate=True
            imageData = base64.b64decode(''.join(image_data_b64.split()), validate=True)
        except (binascii.Error, ValueError):
            raise PlusError('invalid_param', 'invalid parameter: image.data: invalid base64')
    else:
        if not isinstance(image_path, str) or not os.path.isfile(image_path):
            raise PlusError('not_found', 'image file was not found: {}'.format(image_path))

    # all validation done; writes start here
    col.add_image_occlusion_notetype()
    notetypeId = find_io_notetype_id(col)

    if imageData is not None:
        fname = col.media.write_data(image_filename, imageData)
        imagePath = os.path.join(col.media.dir(), fname)
    else:
        imagePath = image_path

    before = col.db.scalar('select max(id) from notes') or 0
    # undoLabel (SPEC 24): the custom entry wraps the backend add AND the deck
    # move so one relabeled undo reverts both; the media write above is not
    # undoable either way. Without a label the pre-SPEC-24 path is unchanged
    # (the backend's own entry, deck move merged into it).
    target = col.add_custom_undo_entry(undo_name) if undo_name is not None else None
    try:
        col.add_image_occlusion_note(notetypeId, imagePath, occlusionsStr, header, back_extra, list(tags))
        if target is not None:
            col.merge_undo_entries(target)
        nid = col.db.scalar('select id from notes where id > ?', before)
        if nid is None:
            raise PlusError('internal', 'image occlusion note was not created')
        cardIds = col.db.list('select id from cards where nid = ? order by ord', nid)

        currentDids = set(col.db.list('select distinct did from cards where nid = ?', nid))
        if cardIds and currentDids != {did}:
            mergeTarget = target if target is not None else col.undo_status().last_step
            col.set_deck(cardIds, did)
            col.merge_undo_entries(mergeTarget)
    except Exception:
        if target is not None:
            _revert_batch(col, undo_name)
        raise

    # undoEntry always reports the ACTUAL top-of-stack entry name (SPEC 24):
    # the sanitized label when given, else the backend's own entry name
    return {'noteId': nid, 'cardIds': cardIds, 'undoEntry': col.undo_status().undo}


def get_image_occlusion_note(col, note_id):
    if isinstance(note_id, bool) or not isinstance(note_id, int):
        raise PlusError('invalid_param', 'invalid parameter: noteId: int required')

    resp = col.get_image_occlusion_note(note_id)
    if resp.WhichOneof('value') != 'note':
        raise PlusError('not_found', 'could not read image occlusion note {}: {}'.format(note_id, resp.error))

    note = resp.note
    return {
        'imageFilename': note.image_file_name,
        'occlusions': parse_io_response_occlusions(note),
        'header': note.header,
        'backExtra': note.back_extra,
        'tags': list(note.tags),
        'occludeInactive': note.occlude_inactive,
    }


def update_image_occlusion_note(col, note_id, occlusions=None, header=None,
                                back_extra=None, tags=None, hide_all_guess_one=True,
                                undo_label=None):
    undo_name = sanitize_undo_label(undo_label)
    if isinstance(note_id, bool) or not isinstance(note_id, int):
        raise PlusError('invalid_param', 'invalid parameter: noteId: int required')
    try:
        ankiNote = col.get_note(note_id)
    except NotFoundError:
        raise PlusError('not_found', 'note was not found: {}'.format(note_id))
    if ankiNote.note_type().get('originalStockKind') != IO_STOCK_KIND:
        raise PlusError('validation_error', 'note is not an image occlusion note: {}'.format(note_id))

    if occlusions is None:
        occlusionsStr = None
    elif isinstance(occlusions, str):
        occlusionsStr = occlusions
    elif isinstance(occlusions, list):
        occlusionsStr = serialize_occlusions(occlusions, hide_all_guess_one)
    else:
        raise PlusError('invalid_param', 'invalid parameter: occlusions: string or array required')
    if header is not None and not isinstance(header, str):
        raise PlusError('invalid_param', 'invalid parameter: header: string required')
    if back_extra is not None and not isinstance(back_extra, str):
        raise PlusError('invalid_param', 'invalid parameter: backExtra: string required')
    if tags is not None:
        _validate_tag_list(tags, 'tags')

    # the backend updater requires every field; backfill omitted ones from the note
    indexes = col._backend.get_image_occlusion_fields(ankiNote.mid)
    if occlusionsStr is None:
        occlusionsStr = ankiNote.fields[indexes.occlusions]
    if header is None:
        header = ankiNote.fields[indexes.header]
    if back_extra is None:
        back_extra = ankiNote.fields[indexes.back_extra]
    if tags is None:
        tags = ankiNote.tags

    # no-op pre-detection (SPEC 4.6/24, revision 11 — same read-only
    # unchanged-detection convention as SPEC 4.2/4.3): when every resolved
    # value already byte-matches the note, the backend performs zero undoable
    # writes and rslib drops its own empty undo step, so reading
    # undo_status().undo afterwards would report an UNRELATED older entry
    # (and a labeled call would leave an empty do-nothing custom entry,
    # violating Deviation #7). Return before any entry is created.
    if (occlusionsStr == ankiNote.fields[indexes.occlusions]
            and header == ankiNote.fields[indexes.header]
            and back_extra == ankiNote.fields[indexes.back_extra]
            and list(tags) == ankiNote.tags):
        return {'undoEntry': None}

    # undoLabel (SPEC 24): wrap the backend update in a relabeled custom entry
    # when a label was given; the default path stays the backend's own entry
    if undo_name is not None:
        target = col.add_custom_undo_entry(undo_name)
        try:
            col.update_image_occlusion_note(note_id, occlusionsStr, header, back_extra, list(tags))
            col.merge_undo_entries(target)
        except Exception:
            _revert_batch(col, undo_name)
            raise
    else:
        col.update_image_occlusion_note(note_id, occlusionsStr, header, back_extra, list(tags))
    # contract change (SPEC 24, was null): report the ACTUAL undo entry name.
    # Safe here: the no-op pre-detection above guarantees the backend wrote
    # (and pushed) an entry, so the top of the stack is ours.
    return {'undoEntry': col.undo_status().undo}


#
# Image cropping (SPEC 11)
#

def _validate_crop_rect(rect):
    if not isinstance(rect, dict):
        raise PlusError('invalid_param', 'invalid parameter: rect: object required')
    for key in ('left', 'top', 'width', 'height'):
        value = rect.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PlusError('invalid_param', 'invalid parameter: rect: {} must be a number'.format(key))
    left, top = float(rect['left']), float(rect['top'])
    width, height = float(rect['width']), float(rect['height'])
    if not (0 <= left <= 1) or not (0 <= top <= 1):
        raise PlusError('invalid_param', 'invalid parameter: rect: left and top must be within 0-1')
    if not (0 < width <= 1) or not (0 < height <= 1):
        raise PlusError('invalid_param', 'invalid parameter: rect: width and height must be within 0-1')
    return left, top, width, height


def _crop_media_image(col, filename, rect):
    """Load a media image, crop it per the normalized rect, and encode the
    result. Pure read: returns (newName, data, (cx, cy, cw, ch), imgW, imgH)
    without writing anything; callers store data via col.media.write_data.

    PyQt6 is imported lazily so importing this module stays Qt-free; QImage
    load/crop/save needs no Q(Gui)Application on this build (probe-verified).
    """
    left, top, width, height = _validate_crop_rect(rect)
    if not isinstance(filename, str) or not filename:
        raise PlusError('invalid_param', 'invalid parameter: filename: string required')
    if os.path.basename(filename) != filename:
        raise PlusError('invalid_param', 'invalid parameter: filename: bare media filename required')
    path = os.path.join(col.media.dir(), filename)
    if not os.path.isfile(path):
        raise PlusError('not_found', 'media file was not found: {}'.format(filename))

    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QRect
    from PyQt6.QtGui import QImage

    img = QImage(path)
    if img.isNull() or img.width() < 1 or img.height() < 1:
        raise PlusError('unsupported_format', 'could not load image: {} (unsupported or corrupt format)'.format(filename))
    imgW, imgH = img.width(), img.height()

    # QImage.copy PADS (does not clamp) when the rect leaves the image, and
    # padded output is explicitly forbidden -> clamp the pixel rect ourselves
    cx = max(0, min(int(round(left * imgW)), imgW))
    cy = max(0, min(int(round(top * imgH)), imgH))
    cw = min(int(round(width * imgW)), imgW - cx)
    ch = min(int(round(height * imgH)), imgH - cy)
    if cw < 1 or ch < 1:
        raise PlusError('invalid_param', 'invalid parameter: rect: selects an empty area of {} ({}x{})'.format(
            filename, imgW, imgH))

    cropped = img.copy(QRect(cx, cy, cw, ch))

    stem, ext = os.path.splitext(filename)
    fmt = ext[1:].lower()
    if fmt in CROP_WRITE_FORMATS:
        newName = '{}-crop{}'.format(stem, ext)
    else:
        fmt = 'png'  # readable but not writable format (gif/svg/pdf/...): re-encode
        newName = '{}-crop.png'.format(stem)

    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    ok = cropped.save(buf, fmt)
    buf.close()
    if not ok:
        raise PlusError('unsupported_format', 'could not encode cropped image as {}: {}'.format(fmt, filename))
    return newName, bytes(ba), (cx, cy, cw, ch), imgW, imgH


def crop_image(col, filename, rect, note_ids=None, undo_label=None):
    undo_name = sanitize_undo_label(undo_label) or UNDO_CROP_IMAGE
    notes = []
    if note_ids is not None:
        if not isinstance(note_ids, list) or not all(
                isinstance(nid, int) and not isinstance(nid, bool) for nid in note_ids):
            raise PlusError('invalid_param', 'invalid parameter: noteIds: ints required')
        for nid in dict.fromkeys(note_ids):  # dedupe: one Note object per id
            try:
                notes.append(col.get_note(nid))
            except NotFoundError:
                raise PlusError('not_found', 'note was not found: {}'.format(nid))

    newName, data, (_cx, _cy, cw, ch), _imgW, _imgH = _crop_media_image(col, filename, rect)

    # writes start here; the original media file is never touched
    fname = col.media.write_data(newName, data)

    # boundary-guarded so 'a.png' never matches inside 'banana.png'; the
    # callable replacement inserts the new name literally (no \-escape parsing)
    pattern = re.compile(r'(?<![\w./\\-])' + re.escape(filename) + r'(?![\w.-])')
    updated = []
    target = None
    for ankiNote in notes:
        changed = False
        for i, value in enumerate(ankiNote.fields):
            newValue, count = pattern.subn(lambda match: fname, value)
            if count:
                ankiNote.fields[i] = newValue
                changed = True
        if not changed:
            continue
        if target is None:
            target = col.add_custom_undo_entry(undo_name)
        try:
            col.update_note(ankiNote)
            col.merge_undo_entries(target)
        except Exception as e:
            _revert_batch(col, undo_name)
            raise PlusError('batch_reverted', 'cropImage failed (note updates reverted): {}'.format(e))
        updated.append(ankiNote.id)

    return {'newFilename': fname, 'width': cw, 'height': ch, 'notesUpdated': updated,
            'undoEntry': undo_name if updated else None}


def crop_image_occlusion_image(col, note_id, rect, undo_label=None):
    undo_name = sanitize_undo_label(undo_label) or UNDO_CROP_IO
    if isinstance(note_id, bool) or not isinstance(note_id, int):
        raise PlusError('invalid_param', 'invalid parameter: noteId: int required')
    try:
        ankiNote = col.get_note(note_id)
    except NotFoundError:
        raise PlusError('not_found', 'note was not found: {}'.format(note_id))
    if ankiNote.note_type().get('originalStockKind') != IO_STOCK_KIND:
        raise PlusError('validation_error', 'note is not an image occlusion note: {}'.format(note_id))

    ioNote = get_image_occlusion_note(col, note_id)
    filename = ioNote['imageFilename']
    if not filename:
        raise PlusError('validation_error', 'image occlusion note has no image file: {}'.format(note_id))

    # refuse anything the rect-only serializer (SPEC 5) cannot re-emit losslessly
    shapes = ioNote['occlusions']
    oiValues = set()
    for entry in shapes:
        if entry['shape'] != 'rect':
            raise PlusError('validation_error',
                            'cropImageOcclusionImage supports rect occlusions only; '
                            'note {} contains a {} shape'.format(note_id, entry['shape']))
        if 'left' not in entry:
            raise PlusError('validation_error', 'could not parse rect occlusion on note {}'.format(note_id))
        properties = entry.get('properties') or {}
        extra = sorted(set(properties) - {'oi'})
        if extra:
            raise PlusError('validation_error',
                            'cropImageOcclusionImage cannot preserve occlusion properties {} '
                            'on note {}'.format(', '.join(extra), note_id))
        oiValues.add(properties.get('oi'))
    # serialize_occlusions applies one note-level oi flag to every shape; mixed
    # per-shape oi (only possible on hand-edited fields -- Anki's editor sets
    # oi globally) cannot be represented, so refuse rather than homogenize
    if len(oiValues) > 1:
        raise PlusError('validation_error',
                        'cropImageOcclusionImage cannot preserve mixed oi flags '
                        'on note {}'.format(note_id))

    newName, data, (cx, cy, cw, ch), imgW, imgH = _crop_media_image(col, filename, rect)

    # remap in pixel space of the ORIGINAL image (SPEC 11.2)
    kept = []
    clippedCount = 0
    droppedCount = 0
    for entry in shapes:
        x0 = entry['left'] * imgW
        y0 = entry['top'] * imgH
        x1 = x0 + entry['width'] * imgW
        y1 = y0 + entry['height'] * imgH
        nx0, ny0 = max(x0, cx), max(y0, cy)
        nx1, ny1 = min(x1, cx + cw), min(y1, cy + ch)
        newWidth = (nx1 - nx0) / cw
        newHeight = (ny1 - ny0) / ch
        # entirely outside the crop, or a sliver that io_num's 4-decimal
        # serialization would collapse to zero size: unrepresentable -> drop
        if (nx1 <= nx0 or ny1 <= ny0
                or float('{:.4f}'.format(newWidth)) == 0
                or float('{:.4f}'.format(newHeight)) == 0):
            droppedCount += 1
            continue
        if (x0 < nx0 - CLIP_EPS_PX or y0 < ny0 - CLIP_EPS_PX
                or x1 > nx1 + CLIP_EPS_PX or y1 > ny1 + CLIP_EPS_PX):
            clippedCount += 1
        kept.append({'left': (nx0 - cx) / cw, 'top': (ny0 - cy) / ch,
                     'width': newWidth, 'height': newHeight,
                     'ordinal': entry['ordinal']})

    if not kept:
        raise PlusError('validation_error', 'crop would remove all occlusions on note {}'.format(note_id))

    occlusionsStr = serialize_occlusions(kept, hide_all_guess_one=ioNote['occludeInactive'])

    indexes = col._backend.get_image_occlusion_fields(ankiNote.mid)
    header = ankiNote.fields[indexes.header]
    backExtra = ankiNote.fields[indexes.back_extra]

    # media write first: not undoable, but it only ADDS a new file
    fname = col.media.write_data(newName, data)

    target = col.add_custom_undo_entry(undo_name)
    try:
        # same raw format the backend itself writes to the Image field
        ankiNote.fields[indexes.image] = '<img src="{}">'.format(fname)
        col.update_note(ankiNote)
        col.merge_undo_entries(target)
        col.update_image_occlusion_note(note_id, occlusionsStr, header, backExtra, list(ankiNote.tags))
        col.merge_undo_entries(target)
    except Exception as e:
        _revert_batch(col, undo_name)
        raise PlusError('batch_reverted', 'cropImageOcclusionImage failed (changes reverted): {}'.format(e))

    cardIds = col.db.list('select id from cards where nid = ? order by ord', note_id)
    return {'newFilename': fname, 'occlusionsKept': len(kept),
            'occlusionsClipped': clippedCount, 'occlusionsDropped': droppedCount,
            'cardIds': cardIds, 'undoEntry': undo_name}


#
# Review history
#

def query_revlog(col, card_ids=None, note_ids=None, deck_name=None,
                 since_ms=None, until_ms=None, limit=5000, offset=0):
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise PlusError('invalid_param', 'invalid parameter: limit: must be >= 1')
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise PlusError('invalid_param', 'invalid parameter: offset: int >= 0 required')

    def validated_ids(name, values):
        if not isinstance(values, list) or not all(isinstance(v, int) and not isinstance(v, bool) for v in values):
            raise PlusError('invalid_param', 'invalid parameter: {}: ints required'.format(name))
        return values

    empty = {'rows': [], 'total': 0, 'truncated': False, 'nextOffset': None}

    # id filters are chunked to stay under SQLite's bound-variable cap; ids
    # are deduped first (dict.fromkeys — order is irrelevant, rows re-sort on
    # r.id) so each id lands in exactly one chunk and every (card chunk x
    # note chunk) combination selects a disjoint set of rows: the per-query
    # results union cleanly (no duplicate rows, COUNTs sum exactly) and only
    # need a re-sort + trim.
    card_chunks = [None]
    if card_ids is not None:
        card_ids = list(dict.fromkeys(validated_ids('cardIds', card_ids)))
        if not card_ids:
            return empty
        card_chunks = [card_ids[i:i + SQL_IN_CHUNK] for i in range(0, len(card_ids), SQL_IN_CHUNK)]

    note_chunks = [None]
    if note_ids is not None:
        note_ids = list(dict.fromkeys(validated_ids('noteIds', note_ids)))
        if not note_ids:
            return empty
        note_chunks = [note_ids[i:i + SQL_IN_CHUNK] for i in range(0, len(note_ids), SQL_IN_CHUNK)]

    baseConditions = []
    baseArgs = []

    if deck_name is not None:
        if not isinstance(deck_name, str):
            raise PlusError('invalid_param', 'invalid parameter: deckName: string required')
        did = col.decks.id_for_name(deck_name)
        if did is None:
            raise PlusError('deck_not_found', 'deck was not found: {}'.format(deck_name))
        # id-based descendant lookup: immune to the caller's deckName casing
        # (id_for_name matches case-insensitively, stored names may differ)
        dids = sorted(set(col.decks.deck_and_child_ids(did)))
        baseConditions.append('(case when c.odid != 0 then c.odid else c.did end) in ({})'.format(','.join('?' * len(dids))))
        baseArgs.extend(dids)

    if since_ms is not None:
        if isinstance(since_ms, bool) or not isinstance(since_ms, int):
            raise PlusError('invalid_param', 'invalid parameter: sinceMs: int required')
        baseConditions.append('r.id >= ?')
        baseArgs.append(since_ms)

    if until_ms is not None:
        if isinstance(until_ms, bool) or not isinstance(until_ms, int):
            raise PlusError('invalid_param', 'invalid parameter: untilMs: int required')
        baseConditions.append('r.id < ?')
        baseArgs.append(until_ms)

    multi = len(card_chunks) * len(note_chunks) > 1
    rawRows = []
    total = 0
    for cardChunk in card_chunks:
        for noteChunk in note_chunks:
            conditions = list(baseConditions)
            args = list(baseArgs)
            if cardChunk is not None:
                conditions.append('r.cid in ({})'.format(','.join('?' * len(cardChunk))))
                args.extend(cardChunk)
            if noteChunk is not None:
                conditions.append('c.nid in ({})'.format(','.join('?' * len(noteChunk))))
                args.extend(noteChunk)
            fromWhere = 'from revlog r left join cards c on c.id = r.cid where 1=1'
            for condition in conditions:
                fromWhere += ' and ' + condition
            # chunk pairs select disjoint row sets, so the per-pair COUNTs sum
            # to the full match count (one cheap COUNT per pair, same WHERE)
            total += col.db.scalar('select count(*) ' + fromWhere, *args) or 0
            sql = ('select r.id, r.cid, c.nid, r.ease, r.ivl, r.lastIvl, r.factor, r.time, r.type '
                   + fromWhere + ' order by r.id asc limit ?')
            if multi:
                # the global rows [offset, offset+limit) are contained in the
                # union of each chunk pair's first offset+limit rows
                args.append(offset + limit)
            else:
                # single chunk pair: page directly in SQL
                sql += ' offset ?'
                args.extend([limit, offset])
            rawRows.extend(col.db.all(sql, *args))

    if multi:
        rawRows.sort(key=lambda row: row[0])
        rawRows = rawRows[offset:offset + limit]

    rows = []
    for rid, cid, nid, ease, ivl, lastIvl, factor, timeMs, rtype in rawRows:
        rows.append({
            'id': rid,
            'cardId': cid,
            'noteId': nid,
            'ease': ease,
            'interval': ivl,
            'lastInterval': lastIvl,
            'factor': factor,
            'timeMs': timeMs,
            'type': rtype,
            'reviewedAt': rid,
        })
    # tell the caller what happened, not just what they asked for: truncated
    # distinguishes "exactly limit rows exist" from "more rows remain"
    truncated = offset + len(rows) < total
    return {'rows': rows, 'total': total, 'truncated': truncated,
            'nextOffset': offset + len(rows) if truncated else None}


#
# Backup
#

def create_backup(col, force=True):
    if not isinstance(force, bool):
        raise PlusError('invalid_param', 'invalid parameter: force: boolean required')

    folder = os.path.join(os.path.dirname(col.path), 'backups')
    os.makedirs(folder, exist_ok=True)
    created = col.create_backup(backup_folder=folder, force=force, wait_for_completion=True)
    return {'created': created}


#
# Card rendering (SPEC 12)
#

RENDER_FORMATS = ('html', 'body', 'text')

# how the notetype stylesheet is delivered (SPEC 12, revision 12 — round-3
# field feedback: 50 rendered cards measured 314,564 B of which 265,350 B
# (90%) was the SAME AnKing stylesheet repeated once per card).
#   'perCard'    per-card 'css' key, today's behavior (default for html/body)
#   'byNotetype' one top-level cssByNotetype {notetypeName: css}, no per-card css
#   'omit'       no css anywhere (default for format 'text', where it is
#                meaningless — the rendered text carries no markup to style)
RENDER_CSS_MODES = ('perCard', 'byNotetype', 'omit')

# matched open/close pairs only, non-greedy, case-insensitive, dot-matches-
# newline; an unclosed <script>/<style> block is left in place (format 'body')
_SCRIPT_BLOCK_RE = re.compile(r'(?si)<script\b.*?</script\s*>')
_STYLE_BLOCK_RE = re.compile(r'(?si)<style\b.*?</style\s*>')


def _render_format_text(col, html, render_format):
    if render_format == 'body':
        return _STYLE_BLOCK_RE.sub('', _SCRIPT_BLOCK_RE.sub('', html))
    if render_format == 'text':
        # same strip helper + conventions as notesSlim (SPEC 13): visible text
        # only, media filenames preserved, cloze markup verbatim
        return col._backend.html_to_text_line(text=html, preserve_media_filenames=True)
    return html


def render_card(col, card_ids, render_format='html', css_mode=None):
    if not isinstance(card_ids, list) or not all(
            isinstance(cid, int) and not isinstance(cid, bool) for cid in card_ids):
        raise PlusError('invalid_param', 'invalid parameter: cardIds: ints required')
    if render_format not in RENDER_FORMATS:
        raise PlusError('invalid_param', 'invalid parameter: format: one of {} required'.format(
            ', '.join(RENDER_FORMATS)))
    if css_mode is not None and css_mode not in RENDER_CSS_MODES:
        raise PlusError('invalid_param', 'invalid parameter: cssMode: one of {} required'.format(
            ', '.join(RENDER_CSS_MODES)))
    if css_mode is None:
        # format-dependent default (SPEC 12, revision 12): css is meaningless
        # for 'text'. An explicit cssMode ALWAYS wins, including cssMode
        # 'perCard' with format 'text'.
        css_mode = 'omit' if render_format == 'text' else 'perCard'

    cards = []
    cssByNotetype = {}
    for cid in card_ids:
        try:
            card = col.get_card(cid)
        except NotFoundError:
            cards.append({'cardId': cid, 'error': 'card was not found: {}'.format(cid)})
            continue
        try:
            out = card.render_output()
            notetype = card.note_type()['name']
            entry = {
                'cardId': cid,
                # rendered template HTML WITHOUT the notetype-CSS <style>
                # wrapper (css ships separately so clients can wrap — or not —
                # themselves); template-authored <style>/<script> blocks ARE
                # part of that HTML and survive verbatim under format 'html'
                'question': _render_format_text(col, out.question_text, render_format),
                'answer': _render_format_text(col, out.answer_text, render_format),
                # current_deck_id() = odid or did: home deck for filtered cards
                'deckName': col.decks.name(card.current_deck_id()),
                'modelName': notetype,
                # 'notetype' (revision 12): the key cssByNotetype is keyed by,
                # present in EVERY cssMode. 'modelName' is the same string,
                # kept for compat with upstream AnkiConnect's naming.
                'notetype': notetype,
                'ord': card.ord,
            }
            if css_mode == 'perCard':
                entry['css'] = out.css
            elif css_mode == 'byNotetype':
                # first render of a notetype wins; the stylesheet is a
                # property of the notetype, identical for all its cards
                cssByNotetype.setdefault(notetype, out.css)
            cards.append(entry)
        except Exception as e:
            cards.append({'cardId': cid, 'error': 'could not render card {}: {}'.format(cid, e)})
    if css_mode == 'byNotetype':
        # present only in this mode, so the other two shapes are byte-unchanged
        return {'cards': cards, 'cssByNotetype': cssByNotetype}
    return {'cards': cards}


#
# Slim note reads (SPEC 13)
#

def _existing_note_ids(col, ids):
    """Set of the given note ids that still exist. One chunked read-only
    existence select (SPEC 13, revision 12 — the noteIds path's honest
    'total'/'missing' needs to know about ids OUTSIDE the current page, which
    a per-page col.get_note loop cannot see). Read-only select of note ids:
    the same 'note-id/card-id location select' family the HARD RULES allow.

    COST, disclosed (round-3 review): this runs on EVERY page over the WHOLE
    requested list, because window-independent total/missing is the point.
    A full paged pass over N ids at page size L is therefore O(N^2/L), not
    O(N). Measured ~0.83 us/id on a scratch collection: ~1 ms added over a
    full pass at N=500, ~103 ms at N=5,000, ~1.7 s at N=20,000 (limit 200).
    No opt-out param by design — a flag to skip it would be a flag to
    reinstate the revision-12 lie; SPEC 13 tells callers to read
    total/missing off the first page and carry them instead."""
    found = set()
    unique = list(dict.fromkeys(ids))
    for start in range(0, len(unique), SQL_IN_CHUNK):
        chunk = unique[start:start + SQL_IN_CHUNK]
        found.update(col.db.list(
            'select id from notes where id in ({})'.format(','.join('?' * len(chunk))),
            *chunk))
    return found


def notes_slim(col, query=None, note_ids=None, fields=None, strip_html=True,
               max_field_length=400, offset=0, limit=200,
               omit_empty_fields=False):
    if (query is None) == (note_ids is None):
        raise PlusError('invalid_param', 'invalid parameter: query: exactly one of query or noteIds required')
    if query is not None and not isinstance(query, str):
        raise PlusError('invalid_param', 'invalid parameter: query: string required')
    if note_ids is not None and (not isinstance(note_ids, list) or not all(
            isinstance(nid, int) and not isinstance(nid, bool) for nid in note_ids)):
        raise PlusError('invalid_param', 'invalid parameter: noteIds: ints required')
    if fields is not None:
        _validate_tag_list(fields, 'fields')
    if not isinstance(strip_html, bool):
        raise PlusError('invalid_param', 'invalid parameter: stripHtml: boolean required')
    if not isinstance(omit_empty_fields, bool):
        raise PlusError('invalid_param', 'invalid parameter: omitEmptyFields: boolean required')
    if isinstance(max_field_length, bool) or not isinstance(max_field_length, int) or max_field_length < 0:
        raise PlusError('invalid_param', 'invalid parameter: maxFieldLength: int >= 0 required')
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise PlusError('invalid_param', 'invalid parameter: offset: int >= 0 required')
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise PlusError('invalid_param', 'invalid parameter: limit: must be >= 1')
    limit = min(limit, NOTES_SLIM_LIMIT_CAP)

    if query is not None:
        try:
            # order=False is the fastest path; sorting ids ourselves gives a
            # deterministic ascending-noteId (creation) order for pagination
            ids = sorted(col.find_notes(query, order=False))
        except SearchError as e:
            raise PlusError('invalid_param', 'invalid parameter: query: {}'.format(e))
        # every id came out of the search: all of them exist
        total = len(ids)
        missing = []
        exists = None
    else:
        ids = list(note_ids)  # caller order preserved, duplicates included
        # SPEC 13, revision 12 (round-3 field feedback, DELIBERATE BREAKING
        # CHANGE): 'total' used to be len(requested ids) — it counted ids that
        # no longer exist, so [real, fake, real, fake] reported total 4 with 2
        # notes and 3 stale ids reported total 3 with an empty page plus a
        # nextOffset pointing at another empty page. total is now the number
        # of requested entries that were FOUND, the stale ones are named in
        # 'missing', and the invariant len(noteIds) == total + len(missing)
        # holds on every page (duplicates counted on both sides).
        found = _existing_note_ids(col, ids)
        exists = [nid in found for nid in ids]
        total = sum(exists)
        missing = [nid for nid, ok in zip(ids, exists) if not ok]

    wanted = set(fields) if fields is not None else None

    notes = []
    for nid in ids[offset:offset + limit]:
        try:
            ankiNote = col.get_note(nid)
        except NotFoundError:
            # noteIds path only: stale id, omitted from the page (SPEC 13)
            # and named in 'missing'; pages may run short of limit
            continue
        model = ankiNote.note_type()
        outFields = {}
        truncatedFields = []
        for fld in model['flds']:
            name = fld['name']
            if wanted is not None and name not in wanted:
                continue
            text = ankiNote[name]
            if strip_html:
                # module-level anki.utils.html_to_text_line routes through the
                # collection-less current_i18n backend and raises headless;
                # the open collection's backend works everywhere (SPEC 13)
                text = col._backend.html_to_text_line(text=text, preserve_media_filenames=True)
            if max_field_length and len(text) > max_field_length:
                text = text[:max_field_length] + '…'
                # explicit truncation signal: the trailing '…' alone is
                # ambiguous (a field may genuinely end in one)
                truncatedFields.append(name)
            if omit_empty_fields and text == '':
                # SPEC 13, revision 12: drop the key entirely. The test is on
                # the value that WOULD be emitted, so under stripHtml=true a
                # field holding only markup ('<br>') also drops out. Measured
                # on a 19-field AnKing-derived notetype with 4 fields
                # populated: 49% smaller AND faster (0.68 ms -> 0.29 ms).
                continue
            outFields[name] = text
        notes.append({
            'noteId': ankiNote.id,
            'modelName': model['name'],
            'tags': list(ankiNote.tags),
            'fields': outFields,
            'truncatedFields': truncatedFields,
        })

    # pagination window is over the ID LIST (which is what offset/limit slice),
    # not over 'total' — under noteIds the two are no longer the same number.
    # nextOffset is suppressed when no FOUND id remains past the window, so a
    # pager is never sent after a page that can only come back empty (SPEC 13,
    # revision 12). Query path: every id exists, so this is the old rule.
    window = offset + limit
    hasMore = window < len(ids) if exists is None else any(
        exists[i] for i in range(window, len(ids)))
    nextOffset = window if hasMore else None
    return {'total': total, 'notes': notes, 'missing': missing,
            'nextOffset': nextOffset}


#
# Media thumbnails (SPEC 14)
#

def media_thumbnails(col, filenames, max_dim=320, image_format='jpeg', quality=70):
    """Pure read: encodes scaled-down copies to base64, writes nothing.

    PyQt6 is imported lazily so importing this module stays Qt-free; QImage
    load/scale/save needs no Q(Gui)Application on this build (probe-verified).
    """
    if not isinstance(filenames, list) or not all(isinstance(f, str) for f in filenames):
        raise PlusError('invalid_param', 'invalid parameter: filenames: list of strings required')
    if isinstance(max_dim, bool) or not isinstance(max_dim, int) or max_dim < 1:
        raise PlusError('invalid_param', 'invalid parameter: maxDim: must be >= 1')
    max_dim = min(max_dim, THUMBNAIL_DIM_CAP)
    if image_format not in THUMBNAIL_FORMATS:
        raise PlusError('invalid_param', 'invalid parameter: format: jpeg or png required')
    if isinstance(quality, bool) or not isinstance(quality, int) or not (0 <= quality <= 100):
        raise PlusError('invalid_param', 'invalid parameter: quality: int 0-100 required')
    if not filenames:
        return {'thumbnails': []}

    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PyQt6.QtGui import QImage

    mediaDir = col.media.dir()
    thumbnails = []
    for filename in filenames:
        if not filename or os.path.basename(filename) != filename:
            thumbnails.append({'filename': filename,
                               'error': 'invalid parameter: filenames: bare media filename required'})
            continue
        path = os.path.join(mediaDir, filename)
        if not os.path.isfile(path):
            thumbnails.append({'filename': filename,
                               'error': 'media file was not found: {}'.format(filename)})
            continue
        img = QImage(path)
        if img.isNull() or img.width() < 1 or img.height() < 1:
            thumbnails.append({'filename': filename,
                               'error': 'could not load image: {} (unsupported or corrupt format)'.format(filename)})
            continue
        # scale only when a side exceeds the cap: this conditional is the
        # never-upscale guarantee (QImage.scaled itself happily upscales)
        if img.width() > max_dim or img.height() > max_dim:
            img = img.scaled(max_dim, max_dim, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        ok = img.save(buf, image_format, quality if image_format == 'jpeg' else -1)
        buf.close()
        if not ok:
            thumbnails.append({'filename': filename,
                               'error': 'could not encode thumbnail as {}: {}'.format(image_format, filename)})
            continue
        thumbnails.append({
            'filename': filename,
            'data': base64.b64encode(bytes(ba)).decode('ascii'),
            'width': img.width(),
            'height': img.height(),
        })
    return {'thumbnails': thumbnails}


#
# Media membership & bulk store (SPEC 22, 23)
#

def media_exists(col, filenames):
    """Pure read (SPEC 22): which of these bare filenames exist in the media
    folder. Results in input order. A malformed or path-carrying name is
    simply exists:false (it can never name a stored media file); only a
    non-string entry is a hard parameter error. Rationale (round-2 field
    feedback): a caller pulled 4.22 MB via getMediaFilesNames to answer a
    13-name membership test.

    actualName (revision 12, round-3 field feedback): APFS/NTFS answer
    os.path.isfile case-insensitively, so 'BSOM_L2_S3A.PNG' reports exists
    for a stored 'bsom_l2_s3a.png' — and that name 404s on AnkiWeb/Linux/iOS.
    When the requested string is not byte-identical to the stored one,
    actualName carries the TRUE on-disk spelling; null when it matches
    exactly (or when the file does not exist). The media DB is deliberately
    NOT the oracle here: files dropped into the media folder outside Anki are
    absent from media.db2 and are not added by col.media.check()
    (probe-verified), so a DB lookup would report exists:false for real
    files. The directory listing is read at most once per call (~2 ms per
    5,000 files, measured) and only when something actually exists."""
    if not isinstance(filenames, list) or not all(isinstance(f, str) for f in filenames):
        raise PlusError('invalid_param', 'invalid parameter: filenames: list of strings required')

    mediaDir = col.media.dir()
    listing = None   # raw os.listdir names, read lazily
    folded = None    # NFC-casefolded name -> sorted list of raw names
    results = []
    for filename in filenames:
        exists = bool(filename) and os.path.basename(filename) == filename \
            and os.path.isfile(os.path.join(mediaDir, filename))
        actualName = None
        if exists:
            if listing is None:
                listing = set(os.listdir(mediaDir))
                folded = {}
                for entry in sorted(listing):
                    folded.setdefault(_nfc(entry).casefold(), []).append(entry)
            if filename not in listing:
                # case and/or unicode-normalization drift; ties (a
                # case-sensitive volume holding several matches) resolve to
                # the first in sorted order — deterministic, documented
                candidates = folded.get(_nfc(filename).casefold())
                actualName = candidates[0] if candidates else None
        results.append({'filename': filename, 'exists': exists,
                        'actualName': actualName})
    return {'results': results}


def store_media_files_bulk(col, files):
    """Store many media files in one call (SPEC 23). Per-item results in
    input order: {requested, actual} on success — actual is the filename anki
    actually stored, making its dedup/rename decision visible (same-name+
    same-bytes dedups to the same name, same-name+different-bytes renames) —
    or {requested, error} on a per-item failure. Media writes are not
    undoable (upstream storeMediaFile precedent); no undo entry is created.
    Rationale (round-2 field feedback): callers stored files blind, then
    pulled the full media listing to verify."""
    if not isinstance(files, list):
        raise PlusError('invalid_param', 'invalid parameter: files: list required')

    stored = []
    for i, entry in enumerate(files):
        if not isinstance(entry, dict):
            stored.append({'requested': None,
                           'error': 'invalid parameter: files[{}]: object required'.format(i)})
            continue
        filename = entry.get('filename')
        requested = filename if isinstance(filename, str) else None

        def item_error(message):
            return {'requested': requested, 'error': message}

        unknown = sorted(set(entry) - {'filename', 'data', 'path'})
        if unknown:
            stored.append(item_error('invalid parameter: files[{}]: unknown key(s): {}'.format(
                i, ', '.join(str(key) for key in unknown))))
            continue
        if not isinstance(filename, str) or not filename:
            stored.append(item_error('invalid parameter: files[{}].filename: string required'.format(i)))
            continue
        if os.path.basename(filename) != filename:
            stored.append(item_error('invalid parameter: files[{}].filename: bare media filename required'.format(i)))
            continue
        data = entry.get('data')
        path = entry.get('path')
        if (data is None) == (path is None):
            stored.append(item_error('invalid parameter: files[{}]: exactly one of data or path required'.format(i)))
            continue

        if data is not None:
            if not isinstance(data, str):
                stored.append(item_error('invalid parameter: files[{}].data: string required'.format(i)))
                continue
            try:
                # same lenient-base64 rule as addImageOcclusionNote (SPEC 4.4)
                payload = base64.b64decode(''.join(data.split()), validate=True)
            except (binascii.Error, ValueError):
                stored.append(item_error('invalid parameter: files[{}].data: invalid base64'.format(i)))
                continue
        else:
            if not isinstance(path, str) or not path:
                stored.append(item_error('invalid parameter: files[{}].path: string required'.format(i)))
                continue
            expanded = os.path.expanduser(path)
            if not os.path.isabs(expanded):
                stored.append(item_error('invalid parameter: files[{}].path: absolute path required'.format(i)))
                continue
            if not os.path.isfile(expanded):
                stored.append(item_error('media source file was not found: {}'.format(path)))
                continue
            try:
                with open(expanded, 'rb') as handle:
                    payload = handle.read()
            except OSError as e:
                stored.append(item_error('could not read file: {}: {}'.format(path, e)))
                continue

        try:
            actual = col.media.write_data(filename, payload)
        except Exception as e:
            stored.append(item_error('could not store media file {}: {}'.format(filename, e)))
            continue
        stored.append({'requested': filename, 'actual': actual})
    return {'stored': stored}


#
# Scheduler bulk ops (SPEC 16)
#

def _existing_cards(col, card_ids):
    """Dedupe card ids (first occurrence wins) and drop ids with no card,
    returning [(cid, queue)]. Read-only. Keeps backend behavior on unknown
    ids out of the contract entirely (SPEC 16)."""
    if not isinstance(card_ids, list) or not all(
            isinstance(cid, int) and not isinstance(cid, bool) for cid in card_ids):
        raise PlusError('invalid_param', 'invalid parameter: cardIds: ints required')
    existing = []
    for cid in dict.fromkeys(card_ids):
        try:
            existing.append((cid, col.get_card(cid).queue))
        except NotFoundError:
            continue
    return existing


def bulk_suspend(col, card_ids, suspend=True, undo_label=None):
    undo_name = sanitize_undo_label(undo_label) or UNDO_BULK_SUSPEND
    if not isinstance(suspend, bool):
        raise PlusError('invalid_param', 'invalid parameter: suspend: boolean required')
    existing = _existing_cards(col, card_ids)

    if suspend:
        # suspending an already-suspended card is a no-op; buried cards DO
        # change (queue -2/-3 -> -1), so they count as pending
        pending = [cid for cid, queue in existing if queue != QUEUE_SUSPENDED]
    else:
        # the backend restore op unsuspends AND unburies: every negative
        # queue changes, so all of them count as pending (SPEC Deviation #8)
        pending = [cid for cid, queue in existing if queue < 0]
    if not pending:
        return {'changed': 0, 'changedIds': [], 'undoEntry': None}

    target = col.add_custom_undo_entry(undo_name)
    try:
        if suspend:
            # OpChangesWithCount: backend-authoritative changed count
            changed = col.sched.suspend_cards(pending).count
        else:
            # unsuspend returns plain OpChanges (no count); the pending
            # precheck is the changed count (SPEC Deviation #8)
            col.sched.unsuspend_cards(pending)
            changed = len(pending)
        col.merge_undo_entries(target)
    except Exception as e:
        _revert_batch(col, undo_name)
        raise PlusError('batch_reverted', 'bulkSuspend failed (batch reverted): {}'.format(e))

    if not changed:
        # data no-op: pop the empty custom entry so the Undo menu stays clean
        _revert_batch(col, undo_name)
        return {'changed': 0, 'changedIds': [], 'undoEntry': None}
    # changedIds (revision 12, round-3 field feedback: the bulk family reported
    # ids inconsistently — bulkAddTags/bulkUpdateNoteFields returned id lists,
    # the scheduler pair only counts) = the precheck set actually passed to the
    # op, which IS the set the op changes (Deviation #8). In the suspend
    # direction 'changed' stays backend-authoritative, so a (never observed)
    # backend/precheck disagreement would show as changed != len(changedIds).
    return {'changed': changed, 'changedIds': pending, 'undoEntry': undo_name}


def bulk_set_due_date(col, card_ids, days, preserve_suspended=None, dry_run=False,
                     undo_label=None):
    undo_name = sanitize_undo_label(undo_label) or UNDO_BULK_DUE
    if not isinstance(days, str) or not days:
        raise PlusError('invalid_param', 'invalid parameter: days: string like "0" or "1-7" required')
    # pre-validate the backend grammar ("0", "5", "1-7", "3!", "1-7!") BEFORE
    # any undo entry exists: if InvalidInput fired after add_custom_undo_entry,
    # popping the empty entry via col.undo() would push a phantom Redo item
    # (SPEC 16.2 promises the undo stack is left untouched on a bad days string).
    # ASCII digits only: the backend regex accepts unicode digits but its int
    # parse then rejects them, so [0-9] is the true accepted alphabet.
    if not re.fullmatch(r'[0-9]+(?:-[0-9]+)?!?', days):
        raise PlusError('invalid_param', 'invalid parameter: days: {}'.format(days))
    # SPEC 27: put back the suspensions anki's set_due_date clears. Resolved
    # (and type-checked) before any undo entry exists, same as the days grammar.
    preserve = resolve_suspension_flag(preserve_suspended, 'preserveSuspended',
                                       DEFAULT_PRESERVE_SUSPENDED_ON_RESCHEDULE)
    # dryRun is type-checked in the same breath, and for the same reason: a
    # truthy non-boolean ("false", "no", 1) would silently turn a requested
    # reschedule into a zero-write prediction and still answer 200. Same idiom
    # as bulk_replace_in_fields' flag loop (SPEC 15).
    if not isinstance(dry_run, bool):
        raise PlusError('invalid_param', 'invalid parameter: dryRun: boolean required')
    existing = _existing_cards(col, card_ids)
    if not existing:
        if dry_run:
            return {'wouldChange': 0, 'wouldChangeIds': [], 'wouldUnsuspend': [],
                    'wouldUnbury': [], 'wouldResuspend': [], 'undoEntry': None}
        return {'changed': 0, 'changedIds': [], 'unsuspended': [], 'unburied': [],
                'resuspended': [], 'undoEntry': None}
    ids = [cid for cid, _queue in existing]
    # queues are already in hand from the precheck: remember the cards that
    # were suspended (-1) or buried (-2 sibling, -3 manual) so the RESURRECTION
    # side effect can be reported (revision 12, round-3 field feedback)
    preNegative = [(cid, queue) for cid, queue in existing if queue < 0]

    # dry run (SPEC 15, 27): the precheck above IS the real path's validation,
    # and it is read-only; stop here, before add_custom_undo_entry, so
    # undo_status() stays bit-identical. The 'would' keys are renamed because
    # they are a PREDICTION from the pre-state, not an observation: unsuspended/
    # unburied are re-read from the post-state on a real run, while wouldUnsuspend
    # /wouldUnbury assume anki's measured resurrection behavior holds.
    if dry_run:
        wouldUnsuspend = [cid for cid, queue in preNegative if queue == QUEUE_SUSPENDED]
        return {'wouldChange': len(ids), 'wouldChangeIds': ids,
                'wouldUnsuspend': wouldUnsuspend,
                'wouldUnbury': [cid for cid, queue in preNegative
                                if queue != QUEUE_SUSPENDED],
                'wouldResuspend': list(wouldUnsuspend) if preserve else [],
                'undoEntry': None}

    target = col.add_custom_undo_entry(undo_name)
    try:
        col.sched.set_due_date(ids, days)
        col.merge_undo_entries(target)
    except InvalidInput as e:
        # bad days string: the op never ran, pop the empty custom entry
        _revert_batch(col, undo_name)
        raise PlusError('invalid_param', 'invalid parameter: days: {}'.format(e))
    except Exception as e:
        _revert_batch(col, undo_name)
        raise PlusError('batch_reverted', 'bulkSetDueDate failed (batch reverted): {}'.format(e))

    # DISCLOSURE (SPEC 16.2, revision 12 — round-3 field feedback): anki's own
    # set_due_date turns every targeted card into a review card, which SILENTLY
    # RESURRECTS suspended and buried ones (measured: 5 cards queue -1 -> queue
    # 2 with no signal of any kind). The revived ids are reported here; the
    # post-state is re-read ONLY for cards whose queue was negative before the
    # op, so the common case costs nothing.
    unsuspended = []
    unburied = []
    for cid, queue in preNegative:
        try:
            after = col.get_card(cid).queue
        except NotFoundError:  # pragma: no cover - handlers are serialized
            continue
        if after >= 0:
            (unsuspended if queue == QUEUE_SUSPENDED else unburied).append(cid)

    # CONTROL (SPEC 27, revision 15): re-suspend exactly the cards this call
    # revived, merged into the SAME undo entry so one Ctrl+Z cannot leave a
    # half-reverted state. Only 'unsuspended' is put back -- a card that was
    # suspended before and stayed suspended never left, and claiming to have
    # re-suspended it would be a lie. Buried cards are deliberately NOT re-
    # buried (Deviation #13b): anki's unbury on reschedule is desirable, and
    # only suspension was asked for. 'resuspended' is re-read from the post-op
    # queues, so it reports what actually IS suspended now, not what was asked.
    resuspended = []
    if preserve and unsuspended:
        try:
            col.sched.suspend_cards(unsuspended)
            col.merge_undo_entries(target)
        except Exception as e:
            if _revert_batch(col, undo_name):
                raise PlusError('batch_reverted',
                                'bulkSetDueDate failed (batch reverted): re-suspend: {}'.format(e))
            # Our entry was no longer on top, so nothing was rolled back: the
            # reschedule (and possibly the re-suspension itself) IS committed.
            # Re-read the queues so the report names the cards actually left
            # in review instead of asserting a revert that did not happen.
            stillLive = []
            for cid in unsuspended:
                try:
                    if col.get_card(cid).queue != QUEUE_SUSPENDED:
                        stillLive.append(cid)
                except Exception:  # pragma: no cover - handlers are serialized
                    continue
            report = {'failedStep': 'resuspend', 'error': str(e), 'reverted': False,
                      'rescheduledStillCommitted': len(ids),
                      'stillUnsuspended': stillLive}
            raise PlusError('internal',
                            'bulkSetDueDate failed (batch NOT reverted): {}'.format(
                                json.dumps(report, separators=(',', ':'))))
        for cid in unsuspended:
            try:
                if col.get_card(cid).queue == QUEUE_SUSPENDED:
                    resuspended.append(cid)
            except NotFoundError:  # pragma: no cover - handlers are serialized
                continue

    # set_due_date returns plain OpChanges (no count); it applies to every
    # existing card regardless of state (SPEC Deviation #8)
    return {'changed': len(ids), 'changedIds': ids, 'unsuspended': unsuspended,
            'unburied': unburied, 'resuspended': resuspended,
            'undoEntry': undo_name}


#
# Deck export (SPEC 17)
#

def export_deck_apkg(col, deck_name, out_path=None, include_scheduling=True,
                     include_media=True):
    if not isinstance(deck_name, str) or not deck_name:
        raise PlusError('invalid_param', 'invalid parameter: deckName: string required')
    if out_path is not None and (not isinstance(out_path, str) or not out_path):
        raise PlusError('invalid_param', 'invalid parameter: outPath: string required')
    if not isinstance(include_scheduling, bool):
        raise PlusError('invalid_param', 'invalid parameter: includeScheduling: boolean required')
    if not isinstance(include_media, bool):
        raise PlusError('invalid_param', 'invalid parameter: includeMedia: boolean required')
    did = col.decks.id_for_name(deck_name)
    if did is None:
        raise PlusError('deck_not_found', 'deck was not found: {}'.format(deck_name))

    if out_path is None:
        # sanitize: unicode word chars, dot, dash survive; '::' and anything
        # else collapse to single dashes
        stem = re.sub(r'[^\w.-]+', '-', deck_name).strip('-.') or 'deck'
        out_path = os.path.join(EXPORT_DEFAULT_DIR, '{}-{}.apkg'.format(
            stem, datetime.date.today().isoformat()))
    else:
        out_path = os.path.expanduser(out_path)
        # outPath must be a FILE path: a directory (or trailing slash) would
        # make splitext see no extension and the collision loop would write a
        # surprise sibling like '<dir>-2' (or a file literally named '-2')
        if os.path.isdir(out_path) or not os.path.basename(out_path):
            raise PlusError(
                'invalid_param',
                'invalid parameter: outPath: is a directory: {}'.format(out_path))
    outDir = os.path.dirname(out_path) or '.'
    if not os.path.isdir(outDir):
        raise PlusError('not_found', 'output directory was not found: {}'.format(outDir))

    # never overwrite: append -2, -3, ... before the extension (race-free:
    # handlers are serialized on the main thread, SPEC 3.1)
    base, ext = os.path.splitext(out_path)
    serial = 2
    while os.path.exists(out_path):
        out_path = '{}-{}{}'.format(base, serial, ext)
        serial += 1

    options = anki.collection.ExportAnkiPackageOptions(
        with_scheduling=include_scheduling,
        # deck presets are NOT exported (matches Anki's own dialog default);
        # importing presets would mutate the receiving collection's config
        with_deck_configs=False,
        with_media=include_media,
        legacy=False,  # modern package format (Anki 2.1.50+)
    )
    notes = col.export_anki_package(out_path=out_path, options=options,
                                    limit=anki.collection.DeckIdLimit(did))
    return {'path': out_path, 'sizeBytes': os.path.getsize(out_path),
            'notesExported': notes}


#
# Deck integrity audit (SPEC 20) — READ-ONLY
#

# anki's own cloze-open marker (rslib cloze regex: lowercase c, digits, '::');
# the balance check counts these opens against '}}' closes per field
_CLOZE_OPEN_RE = re.compile(r'\{\{c\d+::')

# cheap guard before the extract_latex backend call: the three tag pairs the
# backend's latex extractor recognizes
_LATEX_MARKERS = ('[latex]', '[$]', '[$$]')


def _media_refs_in_field(media_regexps, text):
    """Filenames referenced by one field's raw HTML, in match order.

    Mirrors anki's MediaManager.files_in_str body (same regexps object, same
    remote-scheme exclusion) MINUS its render_latex step — render_latex can
    WRITE generated latex images into the media folder, which a read-only
    action must never do. Latex handling is done separately with the pure
    backend extract_latex where needed (orphan scan only, SPEC 20).
    """
    files = []
    for reg in media_regexps:
        for match in re.finditer(reg, text):
            fname = match.group('fname')
            if not re.match('(https?|ftp)://', fname.lower()):
                files.append(fname)
    return files


def _nfc(name):
    # media filename comparisons are NFC-normalized on both sides: Anki stores
    # NFC on macOS, but Finder-copied files can sit on disk as NFD
    return unicodedata.normalize('NFC', name)


def _media_dir_files(col):
    """Set of NFC-normalized plain-file names in the collection media dir."""
    mediaDir = col.media.dir()
    return {_nfc(entry) for entry in os.listdir(mediaDir)
            if os.path.isfile(os.path.join(mediaDir, entry))}


def _cloze_numbers(col, field_values):
    """Cloze ordinals present in the given field strings, via anki's own
    backend parser (the exact code card generation uses). Pure: the minimal
    proto never touches the collection."""
    if not any('{{c' in value for value in field_values):
        return []
    return list(col._backend.cloze_numbers_in_note(
        anki.notes_pb2.Note(fields=list(field_values))))


def check_deck_integrity(col, deck_name, include_orphan_media=False,
                         orphan_media_limit=ORPHAN_MEDIA_DEFAULT_LIMIT):
    if not isinstance(deck_name, str) or not deck_name:
        raise PlusError('invalid_param', 'invalid parameter: deckName: string required')
    if not isinstance(include_orphan_media, bool):
        raise PlusError('invalid_param', 'invalid parameter: includeOrphanMedia: boolean required')
    if isinstance(orphan_media_limit, bool) or not isinstance(orphan_media_limit, int) \
            or orphan_media_limit < 0:
        raise PlusError('invalid_param', 'invalid parameter: orphanMediaLimit: int >= 0 required')
    did = col.decks.id_for_name(deck_name)
    if did is None:
        raise PlusError('deck_not_found', 'deck was not found: {}'.format(deck_name))

    # scope: notes with ANY card homed in the deck or its subdecks (odid =
    # home deck for cards currently in a filtered deck — same semantics as
    # queryRevlog's deck filter). Read-only note/card location selects.
    dids = sorted(set(col.decks.deck_and_child_ids(did)))
    nids = col.db.list(
        'select distinct nid from cards where (case when odid != 0 then odid '
        'else did end) in ({}) order by nid'.format(','.join('?' * len(dids))),
        *dids)

    mediaFiles = _media_dir_files(col)
    modelCache = {}  # mid -> (fieldNames, isCloze) ; None for a missing model

    missingMedia = []
    unbalancedCloze = []
    clozeNotes = []  # (nid, expectedOrds)

    for start in range(0, len(nids), SQL_IN_CHUNK):
        chunk = nids[start:start + SQL_IN_CHUNK]
        placeholders = ','.join('?' * len(chunk))
        for nid, mid, flds in col.db.all(
                'select id, mid, flds from notes where id in ({}) order by id'.format(placeholders),
                *chunk):
            cached = modelCache.get(mid)
            if cached is None and mid not in modelCache:
                model = col.models.get(mid)
                cached = None if model is None else (
                    [fld['name'] for fld in model['flds']],
                    model['type'] == anki.consts.MODEL_CLOZE)
                modelCache[mid] = cached
            values = flds.split('\x1f')
            if cached is not None:
                fieldNames, isCloze = cached
            else:
                # orphaned mid (corrupt collection): index-named fallback
                fieldNames, isCloze = [], False
            for i, value in enumerate(values):
                name = fieldNames[i] if i < len(fieldNames) else '<field {}>'.format(i + 1)
                seen = set()
                for fname in _media_refs_in_field(col.media.regexps, value):
                    normalized = _nfc(fname)
                    if normalized not in mediaFiles and normalized not in seen:
                        seen.add(normalized)
                        missingMedia.append({'noteId': nid, 'field': name,
                                             'filename': fname})
                opens = len(_CLOZE_OPEN_RE.findall(value))
                closes = value.count('}}')
                if opens != closes:
                    unbalancedCloze.append({'noteId': nid, 'field': name})
            if isCloze:
                numbers = _cloze_numbers(col, values)
                # c0 is annotation-only (generates no card, SPEC 5)
                expectedOrds = sorted({n - 1 for n in numbers if n >= 1})
                clozeNotes.append((nid, expectedOrds))

    # one chunked read of the cloze notes' existing card ordinals
    clozeCardMismatch = []
    clozeNotesWithoutCloze = []
    if clozeNotes:
        ordsByNid = {}
        clozeNids = [nid for nid, _expected in clozeNotes]
        for start in range(0, len(clozeNids), SQL_IN_CHUNK):
            chunk = clozeNids[start:start + SQL_IN_CHUNK]
            placeholders = ','.join('?' * len(chunk))
            for nid, ord_ in col.db.all(
                    'select nid, ord from cards where nid in ({}) order by nid, ord'.format(placeholders),
                    *chunk):
                ordsByNid.setdefault(nid, []).append(ord_)
        for nid, expectedOrds in clozeNotes:
            actualOrds = ordsByNid.get(nid, [])
            if not expectedOrds:
                # zero effective cloze numbers (no markers / c0-only /
                # uppercase-C only): anki's own card generation creates and
                # KEEPS a placeholder card ord 0 for such a note (rslib
                # cardgen ensure-not-empty rule; Empty Cards keeps it too),
                # so [] vs [0] is anki's maintained state, not drift. Still
                # an authoring smell — surfaced in clozeNotesWithoutCloze.
                clozeNotesWithoutCloze.append(nid)
                if actualOrds == [0]:
                    continue
            if expectedOrds != actualOrds:
                clozeCardMismatch.append({'noteId': nid,
                                          'expectedOrds': expectedOrds,
                                          'actualOrds': actualOrds})

    orphanMedia = None
    orphanMediaCount = None
    orphanMediaTruncated = False
    if include_orphan_media:
        # COLLECTION-WIDE by nature: a file unreferenced by this deck may be
        # used by any other note or notetype template, so orphan status can
        # only be decided against every reference in the collection.
        referenced = set()
        for mid, flds in col.db.all('select mid, flds from notes'):
            model = col.models.get(mid)
            svg = bool(model.get('latexsvg', False)) if model else False
            for value in flds.split('\x1f'):
                if any(marker in value for marker in _LATEX_MARKERS):
                    # pure backend text transform (verified: writes nothing):
                    # maps latex tags to their generated image filenames so a
                    # rendered latex png is never reported as an orphan — the
                    # exact transform files_in_str applies, minus its
                    # image-generation side effect
                    value = col._backend.extract_latex(
                        text=value, svg=svg, expand_clozes=True).text
                for fname in _media_refs_in_field(col.media.regexps, value):
                    referenced.add(_nfc(fname))
        for model in col.models.all():
            # template/CSS-referenced static media, via anki's own extractor
            for fname in col.media.extract_static_media_files(model['id']):
                referenced.add(_nfc(fname))
        # leading-underscore files are static-use by Anki convention (never
        # reported unused by Anki's own media check); dotfiles are junk like
        # .DS_Store, not media
        orphanMedia = sorted(
            fname for fname in mediaFiles - referenced
            if not fname.startswith('_') and not fname.startswith('.'))
        # revision 12 (round-3 field feedback): the uncapped array measured
        # 1,659,713 B / 37,243 entries on a real collection and, sitting beside
        # four DECK-scoped arrays, read as "this deck has 37,243 orphans". The
        # count is now always reported, the array is capped, and the key names
        # its scope. orphanMediaLimit=0 = count only.
        orphanMediaCount = len(orphanMedia)
        orphanMediaTruncated = orphanMediaCount > orphan_media_limit
        if orphanMediaTruncated:
            orphanMedia = orphanMedia[:orphan_media_limit]

    return {'missingMedia': missingMedia,
            'unbalancedCloze': unbalancedCloze,
            'clozeCardMismatch': clozeCardMismatch,
            'clozeNotesWithoutCloze': clozeNotesWithoutCloze,
            # NOT deck-scoped, unlike every list above it — the name says so
            # (renamed from 'orphanMedia', revision 12; DELIBERATE BREAKING
            # CHANGE, the old key was one day old)
            'orphanMediaCollectionWide': orphanMedia,
            'orphanMediaCount': orphanMediaCount,
            'orphanMediaTruncated': orphanMediaTruncated,
            'notesChecked': len(nids)}


#
# Bulk field replace (SPEC 21)
#

def bulk_replace_in_fields(col, query=None, note_ids=None, field=None,
                           find=None, replace=None, is_regex=False,
                           case_sensitive=True, dry_run=False, atomic=True,
                           max_preview=20, undo_label=None):
    undo_name = sanitize_undo_label(undo_label) or UNDO_BULK_REPLACE
    if (query is None) == (note_ids is None):
        raise PlusError('invalid_param', 'invalid parameter: query: exactly one of query or noteIds required')
    if query is not None and not isinstance(query, str):
        raise PlusError('invalid_param', 'invalid parameter: query: string required')
    if note_ids is not None and (not isinstance(note_ids, list) or not all(
            isinstance(nid, int) and not isinstance(nid, bool) for nid in note_ids)):
        raise PlusError('invalid_param', 'invalid parameter: noteIds: ints required')
    if not isinstance(field, str) or not field:
        raise PlusError('invalid_param', 'invalid parameter: field: string required')
    # an empty find would match between every character (regex and literal
    # alike) and inject `replace` everywhere: never meaningful, always a bug
    if not isinstance(find, str) or not find:
        raise PlusError('invalid_param', 'invalid parameter: find: non-empty string required')
    if not isinstance(replace, str):
        raise PlusError('invalid_param', 'invalid parameter: replace: string required')
    for flagName, flagValue in (('isRegex', is_regex), ('caseSensitive', case_sensitive),
                                ('dryRun', dry_run), ('atomic', atomic)):
        if not isinstance(flagValue, bool):
            raise PlusError('invalid_param', 'invalid parameter: {}: boolean required'.format(flagName))
    if isinstance(max_preview, bool) or not isinstance(max_preview, int) or max_preview < 0:
        raise PlusError('invalid_param', 'invalid parameter: maxPreview: int >= 0 required')

    flags = 0 if case_sensitive else re.IGNORECASE
    if is_regex:
        # python re semantics; no backtracking-bomb protection (SPEC 21) —
        # a pathological pattern can hang the single-threaded server
        try:
            pattern = re.compile(find, flags)
        except re.error as e:
            raise PlusError('invalid_param', 'invalid parameter: find: invalid regex: {}'.format(e))
        repl = replace  # re template: backrefs like \1 / \g<name> expand
    else:
        pattern = re.compile(re.escape(find), flags)
        repl = lambda match: replace  # callable: inserted literally, no \-escape parsing

    if query is not None:
        try:
            # ascending noteId, deterministic (notesSlim precedent, SPEC 13)
            ids = sorted(col.find_notes(query, order=False))
        except SearchError as e:
            raise PlusError('invalid_param', 'invalid parameter: query: {}'.format(e))
    else:
        # dedupe, first occurrence wins (cropImage precedent): processing one
        # note twice in a batch would re-match against its own replacement
        ids = list(dict.fromkeys(note_ids))

    # compute pass — read-only; shared by the dry and real paths by
    # construction (SPEC 15 anti-drift rule)
    changed_ids = []
    unchanged = []
    skipped = []
    preview = []
    pending = []  # (ankiNote, newValue)
    matchesTotal = 0
    for nid in ids:
        try:
            ankiNote = col.get_note(nid)
        except NotFoundError:
            skipped.append({'noteId': nid, 'reason': 'note was not found: {}'.format(nid)})
            continue
        if field not in ankiNote:
            skipped.append({'noteId': nid, 'reason': 'field was not found in note: {}'.format(field)})
            continue
        before = ankiNote[field]
        try:
            after, count = pattern.subn(repl, before)
        except re.error as e:
            # bad regex replacement template (e.g. \9 with one group); raises
            # on the first match, before any write in this batch
            raise PlusError('invalid_param', 'invalid parameter: replace: {}'.format(e))
        matchesTotal += count
        if count == 0 or after == before:
            # nothing matched, or every match replaced itself byte-identically:
            # not written (shared no-op rule, SPEC 4.2/4.3)
            unchanged.append(nid)
            continue
        changed_ids.append(nid)
        if dry_run and len(preview) < max_preview:
            preview.append({'noteId': nid, 'before': before, 'after': after})
        if not dry_run:
            pending.append((ankiNote, after))

    if dry_run:
        return {'wouldChange': changed_ids, 'matchesTotal': matchesTotal,
                'unchanged': unchanged, 'skipped': skipped,
                'preview': preview,
                'previewTruncated': len(changed_ids) > len(preview),
                'undoEntry': None}

    # write pass
    changed = []
    target = None
    for ankiNote, after in pending:
        try:
            ankiNote[field] = after
            if target is None:
                target = col.add_custom_undo_entry(undo_name)
            col.update_note(ankiNote)
            col.merge_undo_entries(target)
            changed.append(ankiNote.id)
        except Exception as e:
            if atomic:
                _revert_batch(col, undo_name)
                report = {'failedNoteId': ankiNote.id, 'error': str(e),
                          'changedBeforeRevert': len(changed), 'skipped': skipped}
                raise PlusError('batch_reverted', 'bulkReplaceInFields failed (batch reverted): {}'.format(
                    json.dumps(report, separators=(',', ':'))))
            skipped.append({'noteId': ankiNote.id, 'reason': str(e)})

    _pop_empty_undo(col, target, changed, undo_name)
    return {'changed': changed, 'matchesTotal': matchesTotal,
            'unchanged': unchanged, 'skipped': skipped,
            'undoEntry': undo_name if changed else None}


#
# Undo stack read (SPEC 26)
#

def undo_status(col):
    """Read anki's undo stack (SPEC 26). Pure read: get_undo_status is a
    backend RPC, no write, no stack change.

    Rationale (round-3 field feedback): every write action REPORTS the undo
    entry name it set, but a caller had no way to OBSERVE the stack, so the
    undoEntry contract could only be taken on trust (the reporter resorted to
    driving Anki's menu bar with AppleScript and was blocked by assistive-
    access permissions).

    Reads col._backend.get_undo_status() DIRECTLY rather than the
    col.undo_status() wrapper (round-3 review fix). The wrapper is
    `self._check_backend_undo_status() or UndoStatus()`
    (SP/anki/collection.py:1033-1035), and _check_backend_undo_status
    (:1080-1086) returns None whenever BOTH undo and redo are empty — so the
    wrapper hands back a synthesized default proto whose last_step is 0. That
    silently broke the monotonicity this action exists to provide: measured
    on a scratch collection, col.fix_integrity() (Check Database) left
    _backend.get_undo_status() == ('', '', 1) while col.undo_status()
    reported last_step 0. col.decks.add_config() and col.mod_schema() clear
    the stack the same way. The backend call returns the identical
    undo/redo strings plus the TRUE counter, and is read-only (verified
    stable across repeated calls); core.py already reaches for _backend the
    same way for html_to_text_line, extract_latex and cloze_numbers_in_note.

    UndoStatus is the collection_pb2 proto with str 'undo'/'redo' and uint32
    'last_step'. Empty strings mean "nothing to undo/redo" (never None, never
    a raise, probe-verified on a fresh collection) and are normalized to null.
    lastStep is anki's monotonic step counter: it advances on every undoable
    operation, so a caller can prove a call created a new entry (or, for the
    documented always-writes case in §16.2, that a byte-identical repeat
    still did). Note that lastStep is monotonic within a session but is NOT
    reset-proof: clearing the stack keeps the counter, it does not rewind it.
    """
    status = col._backend.get_undo_status()
    return {'undo': status.undo or None,
            'redo': status.redo or None,
            'lastStep': status.last_step}


#
# Sync helpers (SPEC 18) — pure logic; the job state machine lives in plus.py
#

def bounded_sync_auth(auth, timeout_secs):
    """Copy of a SyncAuth with io_timeout_secs clamped for status probes.

    pm.sync_auth() carries pm.network_timeout() (default 60 s) — far too long
    for a poll running on the Qt main thread. The proto endpoint field reads
    as '' when unset; that maps back to unset (None) here.
    """
    if isinstance(timeout_secs, bool) or not isinstance(timeout_secs, int) or timeout_secs < 1:
        raise PlusError('invalid_param', 'invalid parameter: timeoutSecs: int >= 1 required')
    return anki.sync.SyncAuth(hkey=auth.hkey,
                              endpoint=auth.endpoint or None,
                              io_timeout_secs=timeout_secs)


def local_sync_dirty(col):
    """Read-only local dirtiness check (SPEC 18): no network, no writes.

    ls = last-sync ms epoch, mod = collection mod-time ms (col table).
    dirty when mod > ls (normal changes) or scm > ls (schema changed —
    col.schema_changed(), which itself is a read-only select).
    """
    ls, mod = col.db.first('select ls, mod from col')
    # bool(): schema_changed() surfaces SQLite's raw 0/1 int, not a bool
    return {'lastSyncMs': ls, 'modMs': mod,
            'dirty': bool(mod > ls or col.schema_changed())}


def classify_sync_error(exc):
    """Map a sync exception to a stable code string (SPEC 18).

    Mirrors aqt.sync.handle_sync_error's dispatch (SP/aqt/sync.py:69-76)
    without any of its dialogs: SyncError kind AUTH -> 'auth_failed'
    (plus.py then clears stored auth, as aqt does), NetworkError ->
    'offline', Interrupted -> 'aborted', anything else -> 'error'.
    """
    if isinstance(exc, SyncError):
        return 'auth_failed' if exc.kind is SyncErrorKind.AUTH else 'error'
    if isinstance(exc, NetworkError):
        return 'offline'
    if isinstance(exc, Interrupted):
        return 'aborted'
    return 'error'


#
# AnkiHub suggestion helpers (SPEC 19) — pure logic only. This module never
# imports the AnkiHub add-on (nor aqt); the bridge that does lives in plus.py.
# All dialog-replication facts below were verified against the installed
# add-on version 2026-08-10.1.
#

ANKIHUB_ADDON_PACKAGE = '1322529746'
ANKIHUB_TESTED_ADDON_VERSION = '2026-08-10.1'

# settings.RATIONALE_FOR_CHANGE_MAX_LENGTH in the tested add-on. The limit
# lives only in their dialog widget (rationale_edit trim loop), so the API
# must enforce it here. The widget deletes chars while
# len >= RATIONALE_FOR_CHANGE_MAX_LENGTH (suggestion_dialog.py:676-677), so
# the dialog's effective cap is 1023 — the API byte-matches that (server
# acceptance of a 1024th character is unverified; no network calls allowed).
ANKIHUB_RATIONALE_MAX_LENGTH = 1024

# SuggestionType wire values (ankihub_client/models.py:21-30). The enum
# values are (wire, label) tuples; the wire value is value[0].
ANKIHUB_CHANGE_TYPES = ('updated_content', 'new_content', 'spelling/grammar',
                        'content_error', 'new_card_to_add', 'new_tags',
                        'updated_tags', 'delete', 'other')

# change type -> SourceType options the dialog offers for it
# (suggestion_dialog.py change_type_to_source_types). The Source widget is
# shown ONLY for these change types — new/updated content additionally gated
# on the target being the AnKing deck; delete's source is shown on any deck.
ANKIHUB_SOURCE_TYPES_BY_CHANGE_TYPE = {
    'new_content': ('AMBOSS', 'UWorld', 'Society Guidelines', 'Other'),
    'updated_content': ('AMBOSS', 'UWorld', 'Society Guidelines', 'Other'),
    'delete': ('Duplicate Note',),
}

# SourceTypes whose input text may be left empty (the dialog drops the
# "(Required)" label for these; source_types_where_input_is_optional)
ANKIHUB_OPTIONAL_SOURCE_TYPES = ('Duplicate Note',)

# change types for which the AnKing deck REQUIRES a source object
ANKIHUB_SOURCE_REQUIRED_CHANGE_TYPES = ('new_content', 'updated_content')

# the dialog's UWorld step dropdown options are 'Step 1'..'Step 3'
ANKIHUB_UWORLD_STEPS = (1, 2, 3)

# ChangeSuggestionResult member name -> locked API result string
ANKIHUB_CHANGE_RESULTS = {'SUCCESS': 'success', 'NO_CHANGES': 'noChanges',
                          'ANKIHUB_NOT_FOUND': 'notFoundOnAnkiHub',
                          'EMPTY_FIRST_FIELD': 'emptyFirstField'}

# call-time feature detection: these functions must exist on the add-on's
# main.suggestions module with AT LEAST these keyword parameters
ANKIHUB_REQUIRED_SIGNATURES = {
    'suggest_note_update': ('note', 'change_type', 'comment',
                            'media_upload_cb', 'auto_accept'),
    'suggest_new_note': ('note', 'comment', 'ankihub_did',
                         'media_upload_cb', 'auto_accept'),
    'resubmit_new_note_as_change_suggestion': ('note', 'ah_did',
                                               'conflicting_ah_nid',
                                               'change_type', 'comment',
                                               'auto_accept'),
    'has_empty_first_field': ('note',),
    'parse_duplicate_anki_id_error': ('errors',),
}

# fragment of the server's 400 non_field_error for a change suggestion whose
# fields/tags match the server revision (main/suggestions.py:64)
ANKIHUB_NO_CHANGES_ERROR_FRAGMENT = "don't have any changes to the original note"
ANKIHUB_SYNC_FIRST_ADVICE = (' (the note may already match the AnkiHub revision'
                             ' - sync with AnkiHub first, then re-suggest)')


def validate_ankihub_change_type(change_type):
    if not isinstance(change_type, str) or change_type not in ANKIHUB_CHANGE_TYPES:
        raise PlusError('invalid_param', 'invalid parameter: changeType: one of {} required'.format(
            ', '.join(ANKIHUB_CHANGE_TYPES)))
    return change_type


def validate_ankihub_rationale(rationale):
    if not isinstance(rationale, str) or not rationale.strip():
        raise PlusError('rationale_invalid', 'RATIONALE_INVALID: rationale must be a non-empty string')
    if len(rationale) >= ANKIHUB_RATIONALE_MAX_LENGTH:
        # >= matches the dialog widget's trim loop: max 1023 characters
        raise PlusError('rationale_invalid',
                        'RATIONALE_INVALID: rationale is {} characters; the '
                        'AnkiHub dialog caps it at {}'.format(
                            len(rationale), ANKIHUB_RATIONALE_MAX_LENGTH - 1))
    return rationale


def _ankihub_source_parts(source, allowed_types):
    """Validate a {type, text[, step]} source; return (type, raw_text, line).

    line is the dialog's exact comment suffix (_comment_with_source,
    suggestion_dialog.py:507-512): '\\nSource: {type} - {text}', with the
    UWorld step dropdown text prepended to the text ('Step N ',
    suggestion_dialog.py:963-970). line is '' when raw_text is blank — the
    dialog only folds a source whose text carries content.
    """
    if not isinstance(source, dict):
        raise PlusError('invalid_param', 'invalid parameter: source: object {type, text} required')
    unknown = sorted(set(source) - {'type', 'text', 'step'})
    if unknown:
        raise PlusError('invalid_param', 'invalid parameter: source: unknown key(s): {}'.format(
            ', '.join(str(key) for key in unknown)))
    source_type = source.get('type')
    if not isinstance(source_type, str) or source_type not in allowed_types:
        raise PlusError('invalid_param', 'invalid parameter: source.type: one of {} required '
                        'here'.format(', '.join(allowed_types)))
    text = source.get('text', '')
    if not isinstance(text, str):
        raise PlusError('invalid_param', 'invalid parameter: source.text: string required')
    step = source.get('step')
    if source_type == 'UWorld':
        if isinstance(step, bool) or not isinstance(step, int) \
                or step not in ANKIHUB_UWORLD_STEPS:
            raise PlusError('invalid_param', 'invalid parameter: source.step: 1, 2 or 3 '
                            'required for UWorld sources')
        folded_text = 'Step {} {}'.format(step, text)
    else:
        if step is not None:
            raise PlusError('invalid_param', 'invalid parameter: source.step: only valid for '
                            'UWorld sources')
        folded_text = text
    if not text.strip():
        return source_type, text, ''
    return source_type, text, '\nSource: {} - {}'.format(source_type, folded_text)


def ankihub_comment_for_update(rationale, change_type, source, for_anking_deck):
    """Final comment for a change suggestion, replicating the AnkiHub dialog's
    Source rules exactly (suggestion_dialog.py:778-786, 829-846):

    - a Source exists only for new_content/updated_content on the AnKing deck
      (REQUIRED there, non-empty text) and for delete on any deck (optional,
      'Duplicate Note' only); anywhere else a source param is rejected
    - the folded line is '\\nSource: {type} - {text}' with UWorld's 'Step N '
      prefix; a blank optional source folds nothing
    """
    rationale = validate_ankihub_rationale(rationale)
    change_type = validate_ankihub_change_type(change_type)
    anking_source = (change_type in ANKIHUB_SOURCE_REQUIRED_CHANGE_TYPES
                     and for_anking_deck)
    source_shown = anking_source or change_type == 'delete'
    if source is None:
        if anking_source:
            raise PlusError('source_required',
                            "SOURCE_REQUIRED: the AnKing deck requires a "
                            "source {{type, text}} for changeType '{}' "
                            "(types: {})".format(
                                change_type,
                                ', '.join(ANKIHUB_SOURCE_TYPES_BY_CHANGE_TYPE[change_type])))
        return rationale
    if not source_shown:
        raise PlusError('invalid_param', "invalid parameter: source: not accepted for "
                        "changeType '{}'{} - the AnkiHub dialog offers a "
                        "Source only for new_content/updated_content on the "
                        "AnKing deck and for delete".format(
                            change_type,
                            '' if change_type in ANKIHUB_SOURCE_REQUIRED_CHANGE_TYPES
                            else ' on any deck'))
    source_type, raw_text, line = _ankihub_source_parts(
        source, ANKIHUB_SOURCE_TYPES_BY_CHANGE_TYPE[change_type])
    if source_type not in ANKIHUB_OPTIONAL_SOURCE_TYPES and not raw_text.strip():
        raise PlusError('source_required',
                        'SOURCE_REQUIRED: source.text must be non-empty for '
                        '{} sources'.format(source_type))
    return rationale + line


def ankihub_comment_for_new_note(rationale, source):
    """Final comment for a new-note suggestion. The add-on's new-note dialog
    flow has NO Source widget and submits the rationale alone
    (suggestion_dialog.py:373-376); the optional source here is a locked API
    extension folded with the identical line format. 'Duplicate Note' is
    excluded — it cannot describe a brand-new note.
    """
    rationale = validate_ankihub_rationale(rationale)
    if source is None:
        return rationale
    _source_type, _raw_text, line = _ankihub_source_parts(
        source, ANKIHUB_SOURCE_TYPES_BY_CHANGE_TYPE['new_content'])
    return rationale + line


def map_ankihub_http_error(status_code, body):
    """AnkiHubHTTPError -> (taxonomy code, message); pure and testable.

    400 = server validation (body passed through; the 'no changes vs server
    revision' error gets sync-with-AnkiHub-first advice appended), 401 =
    bad/expired token, 403 = permission/subscription, 404 = note deleted or
    tombstoned on AnkiHub, 429 = rate limited, anything else (5xx included)
    = NETWORK_ERROR. body may be parsed JSON, a text snippet, or None.
    """
    if isinstance(body, str):
        detail = body
    elif body is None:
        detail = ''
    else:
        detail = json.dumps(body, separators=(',', ':'))
    if status_code == 400:
        message = detail or 'validation failed'
        if ANKIHUB_NO_CHANGES_ERROR_FRAGMENT in message:
            message += ANKIHUB_SYNC_FIRST_ADVICE
        return 'VALIDATION_ERROR', message
    if status_code == 401:
        return ('ANKIHUB_NOT_LOGGED_IN', 'AnkiHub rejected the stored token '
                '(401) - log in through the AnkiHub add-on')
    if status_code == 403:
        message = body.get('detail') if isinstance(body, dict) else None
        return 'PERMISSION_DENIED', message or detail or 'permission denied (403)'
    if status_code == 404:
        return ('NOTE_DELETED_ON_ANKIHUB', 'the note does not exist on '
                'AnkiHub (deleted or tombstoned)')
    if status_code == 429:
        return ('RATE_LIMITED', 'AnkiHub rate limit hit (429) - wait before '
                'submitting more suggestions')
    return 'NETWORK_ERROR', 'unexpected AnkiHub response: HTTP {}{}'.format(
        status_code, ' ' + detail if detail else '')


def map_ankihub_change_result(result_name):
    """ChangeSuggestionResult member NAME -> locked API result string."""
    mapped = ANKIHUB_CHANGE_RESULTS.get(result_name)
    if mapped is None:
        raise PlusError('incompatible_ankihub_addon',
                        'INCOMPATIBLE_ANKIHUB_ADDON: unknown '
                        'ChangeSuggestionResult member {!r} (this bridge was '
                        'tested against add-on version {})'.format(
                            result_name, ANKIHUB_TESTED_ADDON_VERSION))
    return mapped


def ankihub_missing_params(param_names, function_name):
    """Names from ANKIHUB_REQUIRED_SIGNATURES[function_name] absent from
    param_names, sorted. Non-empty means the installed add-on's signature
    drifted from the tested version -> INCOMPATIBLE_ANKIHUB_ADDON."""
    return sorted(set(ANKIHUB_REQUIRED_SIGNATURES[function_name]) - set(param_names))
