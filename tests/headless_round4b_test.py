# Headless verification for SPEC 29 + SPEC 30 — round-4 slice 2
# (spec revision 17):
#
#   * filteredDeckReport (29.1) — read-only census: per filtered deck,
#                                 cardCount + homeDecks; scopable to one home
#                                 subtree (the pre-export probe)
#   * emptyFilteredDeck  (29.2) — send every card in ONE filtered deck home,
#                                 one undoable op; already-empty = gated no-op
#   * exportDeckApkg     (29.3) — FAIL-CLOSED on filtered-deck omission (the
#                                 revision's one deliberate behavior change);
#                                 allowFilteredOmission + always-present
#                                 'warnings', verified against a real import
#   * getEmptyCards      (30.1) — anki's Empty Cards report as data, with the
#                                 deletion/protection split precomputed
#   * deleteEmptyCards   (30.2) — the dialog's deletion incl. its keep-notes
#                                 last-card protection, one undoable batch
#
# Run with: "/Users/mattyc/Library/Application Support/AnkiProgramFiles/.venv/bin/python" headless_round4b_test.py
#
# Uses FRESH scratch collections; never touches ~/Library/Application Support/Anki2/.

import importlib
import importlib.util
import os
import shutil
import sys
import tempfile
import traceback
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = (os.environ.get("ANCP_TEST_SCRATCH")
           or tempfile.mkdtemp(prefix="ancp_r4b_"))
CORE_PATH = os.path.join(REPO, "connect_plus", "core.py")

# safety guards
assert not SCRATCH.startswith(os.path.expanduser("~/Library")), \
    "scratch dir must not be under ~/Library"
assert "Anki2" not in SCRATCH

if os.path.exists(SCRATCH):
    shutil.rmtree(SCRATCH)
os.makedirs(SCRATCH)

sys.dont_write_bytecode = True

# load core.py standalone (no package __init__, no aqt) and verify purity
spec = importlib.util.spec_from_file_location("core", CORE_PATH)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
assert "aqt" not in sys.modules, "core.py (or its imports) pulled in aqt"
assert not any(m.startswith("PyQt6") for m in sys.modules), \
    "core.py (or its imports) pulled in PyQt6"

import anki.lang
anki.lang.set_lang("en_US")
from anki.collection import Collection, ImportAnkiPackageRequest
from anki.decks import DeckId

col = Collection(os.path.join(SCRATCH, "r4b.anki2"))

RESULTS = []


def run(name, fn):
    try:
        fn()
        RESULTS.append((name, True, ""))
        print("PASS  %s" % name, flush=True)
    except Exception:
        RESULTS.append((name, False, traceback.format_exc()))
        print("FAIL  %s" % name, flush=True)
        print(traceback.format_exc(), flush=True)


def add_note(deck, front, tags=()):
    model = col.models.by_name("Basic")
    n = col.new_note(model)
    n["Front"] = front
    n["Back"] = "b"
    n.tags = list(tags)
    col.add_note(n, col.decks.id(deck))
    return n


def add_cloze(deck, text):
    n = col.new_note(col.models.by_name("Cloze"))
    n["Text"] = text
    col.add_note(n, col.decks.id(deck))
    return n


def mkfilter(name, search, allow_empty=False):
    fd = col.sched.get_or_create_filtered_deck(DeckId(0))
    fd.name = name
    fd.allow_empty = allow_empty
    del fd.config.search_terms[:]
    term = fd.config.search_terms.add()
    term.search = search
    term.limit = 100
    term.order = 0
    return int(col.sched.add_or_update_filtered_deck(fd).id)


def undo_snap():
    # the BACKEND status (undo/redo strings + the monotonic last_step), the
    # strict form of the bit-identical claim (SPEC 26)
    return col._backend.get_undo_status().SerializeToString()


def code_of(fn):
    try:
        fn()
    except Exception as err:
        msg = str(err)
        assert msg.startswith("["), "unprefixed error: %r" % msg
        return msg.split("] ", 1)[0].lstrip("[")
    raise AssertionError("expected an exception")


def card_rows(nid):
    return col.db.all("select id, ord, did, odid from cards where nid = ? order by ord", nid)


def _load_plus():
    pkg_name = "ancp_r4b_pkg"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [os.path.join(REPO, "connect_plus")]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg
    return importlib.import_module(pkg_name + ".plus")


# ============================================================================
# 1 — filteredDeckReport: unscoped / home-scoped / filtered-name modes,
#     name-sorted rows, read-only proof
# ============================================================================
def test1_filtered_deck_report():
    n_home = [add_note("R1Home", "h%d" % i) for i in range(3)]
    n_sub = add_note("R1Home::Sub", "s0")
    n_away = add_note("R1Away", "a0")
    f_b = mkfilter("R1FB", "nid:%d" % n_away.id)          # away only
    f_a = mkfilter("R1FA", "nid:%d OR nid:%d" % (n_home[0].id, n_sub.id))
    f_e = mkfilter("R1FE", "nid:1", allow_empty=True)     # empty

    before = undo_snap()
    rep = core.filtered_deck_report(col)
    assert undo_snap() == before, "report wrote"
    rows = {r["filteredDeck"]: r for r in rep["filteredDecks"]}
    # name-sorted, every filter present, empty one included
    assert [r["filteredDeck"] for r in rep["filteredDecks"]] == \
        sorted(rows), rep["filteredDecks"]
    assert rows["R1FA"]["cardCount"] == 2
    assert rows["R1FA"]["homeDecks"] == {"R1Home": 1, "R1Home::Sub": 1}
    assert rows["R1FA"]["filteredDeckId"] == f_a
    assert rows["R1FB"]["homeDecks"] == {"R1Away": 1}
    assert rows["R1FE"] == {"filteredDeck": "R1FE", "filteredDeckId": f_e,
                            "cardCount": 0, "homeDecks": {}}
    assert rep["totalCards"] == 3

    # scoped to the home subtree: R1FB (away) and R1FE (empty) drop out, and
    # totalCards is exactly the export check's count
    scoped = core.filtered_deck_report(col, deck_name="R1Home")
    assert scoped == {"filteredDecks": [
        {"filteredDeck": "R1FA", "filteredDeckId": f_a, "cardCount": 2,
         "homeDecks": {"R1Home": 1, "R1Home::Sub": 1}}], "totalCards": 2}, scoped

    # a filtered deckName reports just that deck's full row
    own = core.filtered_deck_report(col, deck_name="R1FB")
    assert own["totalCards"] == 1 and len(own["filteredDecks"]) == 1
    assert own["filteredDecks"][0]["filteredDeck"] == "R1FB"

    assert code_of(lambda: core.filtered_deck_report(col, deck_name="R1Nope")) \
        == "deck_not_found"
    assert code_of(lambda: core.filtered_deck_report(col, deck_name=7)) \
        == "invalid_param"
    assert code_of(lambda: core.filtered_deck_report(col, deck_name="")) \
        == "invalid_param"

    # cleanup for later tests: send everything home, drop the filters
    col.sched.empty_filtered_deck(DeckId(f_a))
    col.sched.empty_filtered_deck(DeckId(f_b))
    col.decks.remove([DeckId(f_a), DeckId(f_b), DeckId(f_e)])


# ============================================================================
# 2 — emptyFilteredDeck: dry prediction, real run (cards really home, ONE
#     entry, single undo restores the filter), deckId path, undoLabel,
#     already-empty no-op gate, refusals
# ============================================================================
def test2_empty_filtered_deck():
    n1 = add_note("R2Home", "x1")
    n2 = add_note("R2Home::Sub", "x2")
    fid = mkfilter("R2F", "nid:%d OR nid:%d" % (n1.id, n2.id))
    assert col.db.scalar("select count() from cards where did = ?", fid) == 2

    before = undo_snap()
    dry = core.empty_filtered_deck(col, deck_name="R2F", dry_run=True)
    assert dry == {"wouldReturn": 2, "homeDecks": {"R2Home": 1, "R2Home::Sub": 1},
                   "undoEntry": None}, dry
    assert undo_snap() == before, "dry wrote"

    res = core.empty_filtered_deck(col, deck_name="R2F")
    assert res == {"returned": 2, "homeDecks": {"R2Home": 1, "R2Home::Sub": 1},
                   "undoEntry": "AnkiConnect Plus: Empty Filtered Deck"}, res
    status = col._backend.get_undo_status()
    assert status.undo == "AnkiConnect Plus: Empty Filtered Deck", status.undo
    # cards really home: did = old odid, odid = 0
    assert card_rows(n1.id) == [[card_rows(n1.id)[0][0], 0,
                                 col.decks.id_for_name("R2Home"), 0]]
    assert col.db.scalar("select count() from cards where did = ?", fid) == 0

    # single undo puts both cards back into the filter
    col.undo()
    assert col.db.scalar("select count() from cards where did = ?", fid) == 2

    # deckId path + undoLabel
    res2 = core.empty_filtered_deck(col, deck_id=fid, undo_label="send home")
    assert res2["returned"] == 2
    assert res2["undoEntry"] == "AnkiConnect Plus: send home"
    assert col._backend.get_undo_status().undo == "AnkiConnect Plus: send home"

    # already-empty: gated no-op, bit-identical undo status (the backend
    # WOULD write an entry here — probe-verified — so the gate is the test)
    before = undo_snap()
    noop = core.empty_filtered_deck(col, deck_name="R2F")
    assert noop == {"returned": 0, "homeDecks": {}, "undoEntry": None}, noop
    dry0 = core.empty_filtered_deck(col, deck_name="R2F", dry_run=True)
    assert dry0 == {"wouldReturn": 0, "homeDecks": {}, "undoEntry": None}, dry0
    assert undo_snap() == before

    # refusals, all before any write
    assert code_of(lambda: core.empty_filtered_deck(col, deck_name="R2Home")) \
        == "validation_error"
    try:
        core.empty_filtered_deck(col, deck_name="R2Home")
    except core.PlusError as e:
        assert e.message == "deck is not a filtered deck: R2Home", e.message
    assert code_of(lambda: core.empty_filtered_deck(col, deck_name="R2Nope")) \
        == "deck_not_found"
    assert code_of(lambda: core.empty_filtered_deck(col, deck_id=424242)) \
        == "deck_not_found"
    assert code_of(lambda: core.empty_filtered_deck(col)) == "invalid_param"
    assert code_of(lambda: core.empty_filtered_deck(
        col, deck_name="R2F", deck_id=fid)) == "invalid_param"
    assert code_of(lambda: core.empty_filtered_deck(col, deck_id=True)) \
        == "invalid_param"
    assert code_of(lambda: core.empty_filtered_deck(col, deck_name="")) \
        == "invalid_param"
    assert code_of(lambda: core.empty_filtered_deck(
        col, deck_name="R2F", dry_run="yes")) == "invalid_param"
    assert undo_snap() == before

    col.decks.remove([DeckId(fid)])


# ============================================================================
# 3 — exportDeckApkg fail-closed: refusal leaves zero filesystem trace,
#     allowFilteredOmission itemizes the loss in 'warnings' and the imported
#     package really lacks the omitted notes, empty-then-export runs clean
# ============================================================================
def test3_export_fail_closed():
    n_keep = add_note("R3Exp", "keeps")                     # clean
    n_gone = add_note("R3Exp", "vanishes")                  # whole note filtered
    n_part = add_cloze("R3Exp", "{{c1::a}} {{c2::b}}")      # one of two filtered
    part_cids = [r[0] for r in card_rows(n_part.id)]
    fid = mkfilter("R3F", "nid:%d" % n_gone.id)
    fid2 = mkfilter("R3F2", "cid:%d" % part_cids[0])  # exactly one of the two
    assert card_rows(n_part.id)[0][3] != 0 and card_rows(n_part.id)[1][3] == 0, \
        "fixture: exactly one card of n_part should be filtered"

    out = os.path.join(SCRATCH, "r3.apkg")
    before = undo_snap()
    try:
        core.export_deck_apkg(col, "R3Exp", out_path=out)
        raise AssertionError("expected refusal")
    except core.PlusError as e:
        assert e.code == "cards_in_filtered_decks", e.code
        assert e.retryable is False
        # the message names counts + filtered decks + both remedies
        for token in ('2 cards whose home deck is inside "R3Exp"',
                      "R3F: 1", "R3F2: 1", "1 such notes here",
                      "emptyFilteredDeck", "allowFilteredOmission=true"):
            assert token in e.message, (token, e.message)
    assert not os.path.exists(out), "refusal left a file"
    assert undo_snap() == before

    # escape hatch: export proceeds, warnings itemize, import proves the loss
    res = core.export_deck_apkg(col, "R3Exp", out_path=out,
                                allow_filtered_omission=True)
    assert res["path"] == out and os.path.getsize(out) == res["sizeBytes"]
    assert res["notesExported"] == 2, res  # n_keep + n_part; n_gone vanished
    assert res["warnings"] == [{"code": "cards_in_filtered_decks", "count": 2,
                                "decks": {"R3F": 1, "R3F2": 1},
                                "notesOmitted": 1}], res["warnings"]
    os.makedirs(os.path.join(SCRATCH, "r3import"), exist_ok=True)
    dst = Collection(os.path.join(SCRATCH, "r3import", "i.anki2"))
    dst.import_anki_package(ImportAnkiPackageRequest(package_path=out))
    imported = set(dst.db.list("select id from notes"))
    dst.close()
    assert n_keep.id in imported and n_part.id in imported
    assert n_gone.id not in imported, "omitted note somehow shipped"

    # remediate -> the identical default call succeeds, warnings []
    assert core.empty_filtered_deck(col, deck_name="R3F")["returned"] == 1
    assert core.empty_filtered_deck(col, deck_id=fid2)["returned"] == 1
    res2 = core.export_deck_apkg(col, "R3Exp", out_path=out)  # -2 suffix
    assert res2["warnings"] == [] and res2["notesExported"] == 3, res2

    # a clean deck always reports warnings: []
    add_note("R3Clean", "c")
    res3 = core.export_deck_apkg(
        col, "R3Clean", out_path=os.path.join(SCRATCH, "r3clean.apkg"))
    assert res3["warnings"] == [], res3
    # bad flag type refused before anything else touches the filesystem
    assert code_of(lambda: core.export_deck_apkg(
        col, "R3Clean", allow_filtered_omission="yes")) == "invalid_param"
    col.decks.remove([DeckId(fid), DeckId(fid2)])


# ============================================================================
# 3b — exportDeckApkg fix pass: the SECOND flagged set — a filtered deck
#      nested INSIDE the export subtree holding cards homed OUTSIDE it
#      (foreign notes would ship scheduling-reset into a recreated regular
#      deck); plus the both-sets-at-once message/warnings order and the
#      filtered-root-export legality (root excluded from the foreign set)
# ============================================================================
def test3b_export_foreign_in_scope_filters():
    n_own = add_note("R3bEA", "own")
    n_foreign = add_note("R3bEZ", "foreign")
    fid = mkfilter("R3bEA::Cram", "nid:%d" % n_foreign.id)
    # fixture: the foreign card really sits in the nested filter, homed outside
    row = card_rows(n_foreign.id)[0]
    assert row[2] == fid and row[3] == col.decks.id_for_name("R3bEZ"), row

    out = os.path.join(SCRATCH, "r3b.apkg")
    before = undo_snap()
    try:
        core.export_deck_apkg(col, "R3bEA", out_path=out)
        raise AssertionError("expected refusal")
    except core.PlusError as e:
        assert e.code == "cards_in_filtered_decks", e.code
        for token in ('1 cards homed OUTSIDE "R3bEA"', "R3bEA::Cram: 1",
                      "recreated as regular decks",
                      "emptyFilteredDeck", "allowFilteredOmission=true"):
            assert token in e.message, (token, e.message)
    assert not os.path.exists(out), "refusal left a file"
    assert undo_snap() == before

    # escape hatch: the foreign note SHIPS (the disclosed damage), warnings
    # itemize it under the sibling code, and a real import proves both the
    # foreign note's arrival and the filter's recreation as a REGULAR deck
    res = core.export_deck_apkg(col, "R3bEA", out_path=out,
                                allow_filtered_omission=True)
    assert res["notesExported"] == 2, res  # n_own + the foreign note
    assert res["warnings"] == [{"code": "foreign_cards_in_scope_filters",
                                "count": 1,
                                "decks": {"R3bEA::Cram": 1}}], res["warnings"]
    os.makedirs(os.path.join(SCRATCH, "r3bimport"), exist_ok=True)
    dst = Collection(os.path.join(SCRATCH, "r3bimport", "i.anki2"))
    dst.import_anki_package(ImportAnkiPackageRequest(package_path=out))
    imported = set(dst.db.list("select id from notes"))
    recreated = dst.decks.id_for_name("R3bEA::Cram")
    assert recreated is not None and not dst.decks.is_filtered(recreated), \
        "nested filter should arrive recreated as a REGULAR deck"
    dst.close()
    assert n_foreign.id in imported, "foreign note should ship when allowed"
    assert n_own.id in imported

    # both sets at once: also pull the in-scope-home card into an OUTSIDE
    # filter — one refusal names both sentences; an allowed export carries
    # both warnings entries, home-side first
    fid2 = mkfilter("R3bOut", "nid:%d" % n_own.id)
    try:
        core.export_deck_apkg(col, "R3bEA", out_path=out)
        raise AssertionError("expected refusal")
    except core.PlusError as e:
        assert e.code == "cards_in_filtered_decks", e.code
        assert '1 cards whose home deck is inside "R3bEA"' in e.message, e.message
        assert '1 cards homed OUTSIDE "R3bEA"' in e.message, e.message
    res2 = core.export_deck_apkg(col, "R3bEA", out_path=out,
                                 allow_filtered_omission=True)
    assert [w["code"] for w in res2["warnings"]] == \
        ["cards_in_filtered_decks", "foreign_cards_in_scope_filters"], res2
    assert res2["warnings"][0]["count"] == 1
    assert res2["warnings"][0]["notesOmitted"] == 1, res2  # n_own vanishes
    assert "notesOmitted" not in res2["warnings"][1], res2  # nothing vanishes

    # remediate both filters -> the identical default call succeeds clean
    assert core.empty_filtered_deck(col, deck_id=fid2)["returned"] == 1
    assert core.empty_filtered_deck(col, deck_id=fid)["returned"] == 1
    res3 = core.export_deck_apkg(col, "R3bEA", out_path=out)
    assert res3["warnings"] == [] and res3["notesExported"] == 1, res3

    # exporting a FILTERED deck by name stays legal: the export root is
    # excluded from the foreign set, so a filter full of visiting cards
    # exports without tripping the guard (explicit choice, SPEC 29.3)
    fid3 = mkfilter("R3bDirect", "nid:%d" % n_foreign.id)
    assert card_rows(n_foreign.id)[0][2] == fid3, "fixture: card in the filter"
    res4 = core.export_deck_apkg(
        col, "R3bDirect", out_path=os.path.join(SCRATCH, "r3bdirect.apkg"))
    assert res4["warnings"] == [] and res4["notesExported"] == 1, res4
    col.decks.remove([DeckId(fid), DeckId(fid2), DeckId(fid3)])


# ============================================================================
# 4 — getEmptyCards: the three shapes, ords/willDeleteCards/protectedCard,
#     read-only proof, deck scoping (odid-aware, all-cards-reported rule)
# ============================================================================
def test4_get_empty_cards():
    partial = add_cloze("R4A", "{{c1::a}} {{c2::b}}")
    partial["Text"] = "{{c1::a}}"
    col.update_note(partial)
    single = add_cloze("R4A", "{{c1::x}}")
    single["Text"] = "no cloze left"
    col.update_note(single)
    double = add_cloze("R4B", "{{c1::p}} {{c2::q}}")
    double["Text"] = "gone"
    col.update_note(double)
    add_cloze("R4A", "{{c1::fine}}")  # clean control

    before = undo_snap()
    rep = core.get_empty_cards(col)
    assert undo_snap() == before, "getEmptyCards wrote"
    by_note = {n["noteId"]: n for n in rep["notes"]}
    assert rep["total"] == 3 and len(rep["notes"]) == 3, rep

    p = by_note[partial.id]
    assert p["protectedCard"] is None
    assert p["ords"] == [1]
    assert p["willDeleteCards"] == [card_rows(partial.id)[1][0]]

    s = by_note[single.id]
    assert s["willDeleteCards"] == [] and s["ords"] == [0]
    assert s["protectedCard"] == card_rows(single.id)[0][0]

    d = by_note[double.id]
    assert d["ords"] == [0, 1]
    assert d["protectedCard"] is not None
    assert len(d["willDeleteCards"]) == 1
    assert d["protectedCard"] not in d["willDeleteCards"]
    assert {d["protectedCard"]} | set(d["willDeleteCards"]) == \
        {r[0] for r in card_rows(double.id)}

    # deck scoping: R4A sees partial+single, R4B sees double
    in_a = core.get_empty_cards(col, deck_name="R4A")
    assert {n["noteId"] for n in in_a["notes"]} == {partial.id, single.id}
    assert in_a["total"] == 2
    in_b = core.get_empty_cards(col, deck_name="R4B")
    assert [n["noteId"] for n in in_b["notes"]] == [double.id]

    # odid-aware: pull partial's empty card into a filtered deck — the note
    # still reports under its HOME deck, with the same card ids
    fid = mkfilter("R4F", "cid:%d" % p["willDeleteCards"][0])
    assert card_rows(partial.id)[1][3] != 0, "card not in filter"
    in_a2 = core.get_empty_cards(col, deck_name="R4A")
    assert {n["noteId"] for n in in_a2["notes"]} == {partial.id, single.id}
    p2 = {n["noteId"]: n for n in in_a2["notes"]}[partial.id]
    assert p2 == p, (p2, p)
    core.empty_filtered_deck(col, deck_id=fid)
    col.decks.remove([DeckId(fid)])

    assert code_of(lambda: core.get_empty_cards(col, deck_name="R4Nope")) \
        == "deck_not_found"
    assert code_of(lambda: core.get_empty_cards(col, deck_name="")) \
        == "invalid_param"
    # NOTE: the three empty-card notes are deliberately left for test5


# ============================================================================
# 5 — deleteEmptyCards: dry parity, real deletion with the dialog's own
#     protection, skipped reasons, no-op gate, single undo restores the report
# ============================================================================
def test5_delete_empty_cards():
    rep = core.get_empty_cards(col)
    assert rep["total"] == 3, "test4 fixture missing"
    by_note = {n["noteId"]: n for n in rep["notes"]}
    partial_id, single_id, double_id = sorted(
        by_note, key=lambda nid: (by_note[nid]["protectedCard"] is not None,
                                  len(by_note[nid]["ords"])))
    # partial: no protection; single: protected-only; double: protected + 1
    assert by_note[partial_id]["protectedCard"] is None
    assert by_note[single_id]["willDeleteCards"] == []
    assert len(by_note[double_id]["willDeleteCards"]) == 1

    expect_delete = (by_note[partial_id]["willDeleteCards"] +
                     by_note[double_id]["willDeleteCards"])

    before = undo_snap()
    dry = core.delete_empty_cards(col, dry_run=True)
    assert undo_snap() == before, "dry wrote"
    assert sorted(dry["wouldDelete"]) == sorted(expect_delete), dry
    assert dry["notesAffected"] == 2
    assert {p["noteId"] for p in dry["protected"]} == {single_id, double_id}
    assert dry["skipped"] == [] and dry["undoEntry"] is None

    # noteIds path: protected-only + clean + bogus + duplicate
    clean_note = add_note("R5Clean", "c")
    before = undo_snap()  # re-snapshot: the add_note above moved the stack
    res = core.delete_empty_cards(
        col, note_ids=[single_id, clean_note.id, 999999, single_id])
    assert res == {"cardsDeleted": 0, "deletedCardIds": [], "notesAffected": 0,
                   "protected": [{"noteId": single_id,
                                  "cardId": by_note[single_id]["protectedCard"]}],
                   "notesPreserved": True,
                   "skipped": [{"noteId": clean_note.id, "reason": "no empty cards"},
                               {"noteId": 999999, "reason": "note was not found"}],
                   "undoEntry": None}, res
    assert undo_snap() == before, "all-protected wrote"

    # real run, labeled: exactly the dry ids die, every note + every
    # protected card survives, ONE entry, single undo restores the report
    notes_before = col.db.scalar("select count() from notes")
    res = core.delete_empty_cards(col, undo_label="cloze sweep")
    assert res["cardsDeleted"] == 2, res
    assert sorted(res["deletedCardIds"]) == sorted(expect_delete)
    assert res["notesAffected"] == 2
    assert {p["noteId"] for p in res["protected"]} == {single_id, double_id}
    assert res["notesPreserved"] is True and res["skipped"] == []
    assert res["undoEntry"] == "AnkiConnect Plus: cloze sweep"
    assert col._backend.get_undo_status().undo == "AnkiConnect Plus: cloze sweep"
    assert col.db.scalar("select count() from notes") == notes_before
    for entry in res["protected"]:
        assert col.db.scalar("select count() from cards where id = ?",
                             entry["cardId"]) == 1, "protected card deleted"
    for cid in res["deletedCardIds"]:
        assert col.db.scalar("select count() from cards where id = ?", cid) == 0
    # protected notes REAPPEAR in later reports — their kept card is still
    # empty (anki's own dialog with keep-notes behaves identically): single
    # and double both remain, partial (whose empty card really died) is gone
    after = core.get_empty_cards(col)
    assert {n["noteId"] for n in after["notes"]} == {single_id, double_id}, after
    assert all(n["willDeleteCards"] == [] for n in after["notes"]), after

    col.undo()
    rep2 = core.get_empty_cards(col)
    assert rep2["total"] == 3 and \
        {n["noteId"]: n for n in rep2["notes"]} == by_note, "undo did not restore"

    # nothing-deletable-anywhere no-op: collection whose only empties are
    # protected — delete the two deletable ones first, then repeat
    core.delete_empty_cards(col)
    before = undo_snap()
    res2 = core.delete_empty_cards(col)
    assert res2["cardsDeleted"] == 0 and res2["undoEntry"] is None
    assert {p["noteId"] for p in res2["protected"]} == {single_id, double_id}
    assert undo_snap() == before

    # validation, nothing written
    for bad in [lambda: core.delete_empty_cards(col, note_ids="x"),
                lambda: core.delete_empty_cards(col, note_ids=[1, True]),
                lambda: core.delete_empty_cards(col, dry_run="no"),
                lambda: core.delete_empty_cards(col, undo_label="   ")]:
        assert code_of(bad) == "invalid_param"
    assert undo_snap() == before


# ============================================================================
# 6 — lockstep surface: the four actions + amended export in every registry,
#     the new error code, the recipes, wrapper signatures + '[code] ' envelope
#     end to end, README/SPEC artifacts
# ============================================================================
def test6_lockstep_and_wrappers():
    for name in ("filteredDeckReport", "emptyFilteredDeck",
                 "getEmptyCards", "deleteEmptyCards"):
        assert name in core.PLUS_ACTIONS, name
        assert core.PLUS_ACTION_SUMMARIES[name].strip(), name
        assert core.PLUS_ACTION_RETURNS[name].startswith("{"), name
    assert len(core.PLUS_ACTIONS) == 34, len(core.PLUS_ACTIONS)
    assert core.PLUS_ACTIONS[-1] == "plusInfo"
    assert core.UNDO_EMPTY_FILTERED == "AnkiConnect Plus: Empty Filtered Deck"
    assert core.UNDO_DELETE_EMPTY == "AnkiConnect Plus: Delete Empty Cards"
    # the export summary/returns disclose the fail-closed default + warnings
    assert "FAIL-CLOSED" in core.PLUS_ACTION_SUMMARIES["exportDeckApkg"]
    assert "warnings" in core.PLUS_ACTION_RETURNS["exportDeckApkg"]
    # new error code: present, reachable, not retryable
    assert core.PLUS_ERROR_CODES["cards_in_filtered_decks"] is False
    assert core.PLUS_ERROR_CODE_DOCS["cards_in_filtered_decks"]["reachable"] is True
    assert "emptyFilteredDeck" in \
        core.PLUS_ERROR_CODE_DOCS["cards_in_filtered_decks"]["meaning"]
    assert "34 Plus actions" in core.PLUS_ERROR_PREFIX_NOTE
    # recipes: the export-safety story and the audit->remediate loop
    names = [r["name"] for r in core.PLUS_RECIPES]
    assert "safe deck export" in names and "empty-cards cleanup" in names, names
    for recipe in core.PLUS_RECIPES:
        assert recipe["example"]["action"] in core.PLUS_ACTIONS, recipe["name"]
    safe = next(r for r in core.PLUS_RECIPES if r["name"] == "safe deck export")
    for token in ("filteredDeckReport", "emptyFilteredDeck",
                  "allowFilteredOmission", "cards_in_filtered_decks"):
        assert token in safe["description"], token
    loop = next(r for r in core.PLUS_RECIPES if r["name"] == "empty-cards cleanup")
    for token in ("checkDeckIntegrity", "getEmptyCards", "deleteEmptyCards",
                  "protected"):
        assert token in loop["description"], token

    plus = _load_plus()
    util_mod = sys.modules["ancp_r4b_pkg.util"]
    orig = util_mod.setting
    try:
        util_mod.setting = lambda key: util_mod.DEFAULT_CONFIG[key]
        info = plus.PlusMixin().plusInfo()
    finally:
        util_mod.setting = orig
    docs = info["actionDocs"]
    assert docs["filteredDeckReport"]["params"] == "deckName=null", \
        docs["filteredDeckReport"]
    assert docs["emptyFilteredDeck"]["params"] == \
        "deckName=null, deckId=null, dryRun=false, undoLabel=null", \
        docs["emptyFilteredDeck"]
    assert docs["getEmptyCards"]["params"] == "deckName=null", docs["getEmptyCards"]
    assert docs["deleteEmptyCards"]["params"] == \
        "noteIds=null, dryRun=false, undoLabel=null", docs["deleteEmptyCards"]
    assert docs["exportDeckApkg"]["params"] == \
        ("deckName, outPath=null, includeScheduling=true, includeMedia=true, "
         "allowFilteredOmission=false"), docs["exportDeckApkg"]
    assert info["errorCodes"]["cards_in_filtered_decks"] == {
        "retryable": False, "reachable": True,
        "meaning": core.PLUS_ERROR_CODE_DOCS["cards_in_filtered_decks"]["meaning"]}

    # end-to-end through the real wrappers: the '[code] ' envelope holds
    class Inst(plus.PlusMixin):
        def collection(self):
            return col

    inst = Inst()
    n = add_note("R6Wrap", "w")
    fid = mkfilter("R6WrapF", "nid:%d" % n.id)
    rep = inst.filteredDeckReport(deckName="R6Wrap")
    assert rep["totalCards"] == 1 and \
        rep["filteredDecks"][0]["filteredDeck"] == "R6WrapF", rep
    try:
        inst.exportDeckApkg(deckName="R6Wrap",
                            outPath=os.path.join(SCRATCH, "wrap.apkg"))
        raise AssertionError("expected an exception")
    except Exception as e:
        assert str(e).startswith("[cards_in_filtered_decks] "), str(e)
    try:
        inst.emptyFilteredDeck(deckName="R6Wrap")
        raise AssertionError("expected an exception")
    except Exception as e:
        assert str(e) == \
            "[validation_error] deck is not a filtered deck: R6Wrap", str(e)
    assert inst.emptyFilteredDeck(deckId=fid)["returned"] == 1
    assert inst.getEmptyCards()["total"] >= 0
    assert inst.deleteEmptyCards(dryRun=True)["undoEntry"] is None

    # docs artifacts name the four actions (README table + SPEC 29/30)
    readme = open(os.path.join(REPO, "README.md"), encoding="utf-8").read()
    spec_text = open(os.path.join(REPO, "SPEC.md"), encoding="utf-8").read()
    for name in ("filteredDeckReport", "emptyFilteredDeck",
                 "getEmptyCards", "deleteEmptyCards"):
        assert "`%s`" % name in readme, "README does not document %s" % name
    assert "allowFilteredOmission" in readme
    assert "## 29." in spec_text, "SPEC 29 missing"
    assert "## 30." in spec_text, "SPEC 30 missing"


# ================================================================ run
run("test1_filtered_deck_report", test1_filtered_deck_report)
run("test2_empty_filtered_deck", test2_empty_filtered_deck)
run("test3_export_fail_closed", test3_export_fail_closed)
run("test3b_export_foreign_in_scope_filters", test3b_export_foreign_in_scope_filters)
run("test4_get_empty_cards", test4_get_empty_cards)
run("test5_delete_empty_cards", test5_delete_empty_cards)
run("test6_lockstep_and_wrappers", test6_lockstep_and_wrappers)

col.close()

failed = [name for name, ok, _tb in RESULTS if not ok]
print()
print("%d/%d passed" % (len(RESULTS) - len(failed), len(RESULTS)))
if failed:
    print("FAILED:", ", ".join(failed))
    sys.exit(1)
