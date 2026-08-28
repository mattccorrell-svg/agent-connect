# Headless verification for the two field-feedback actions (SPEC 20-21):
# checkDeckIntegrity and bulkReplaceInFields.
#
# Run with: <anki-venv>/bin/python headless_seven_test.py
#
# Uses a FRESH scratch collection; never touches ~/Library/Application Support/Anki2/.

import importlib.util
import json
import os
import shutil
import struct
import sys
import tempfile
import traceback
import zlib

SCRATCH = (os.environ.get("ANCP_TEST_SCRATCH")
           or tempfile.mkdtemp(prefix="ancp_seven_r1_"))
CORE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "connect_plus", "core.py")

# safety guards
assert not SCRATCH.startswith(os.path.expanduser("~/Library")), "scratch dir must not be under ~/Library"
assert "Anki2" not in SCRATCH

if os.path.exists(SCRATCH):
    shutil.rmtree(SCRATCH)
os.makedirs(SCRATCH)

# load core.py standalone (no package __init__, no aqt)
spec = importlib.util.spec_from_file_location("core", CORE_PATH)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
assert "aqt" not in sys.modules, "core.py (or its imports) pulled in aqt"
assert "PyQt6" not in sys.modules, "core.py import pulled in Qt"

import anki.lang
anki.lang.set_lang("en_US")
from anki.collection import Collection

col = Collection(os.path.join(SCRATCH, "seven.anki2"))

RESULTS = []


def undo_snap():
    # UndoStatus proto bytes: the bit-identical comparison SPEC 15/20 promise
    return col.undo_status().SerializeToString()


def add_basic(deck, front, back="b", tags=None):
    import anki.notes
    model = col.models.by_name("Basic")
    note = anki.notes.Note(col, model)
    note["Front"] = front
    note["Back"] = back
    note.tags = list(tags or [])
    col.add_note(note, col.decks.id(deck))
    return note.id


def add_cloze(deck, text, extra=""):
    import anki.notes
    model = col.models.by_name("Cloze")
    note = anki.notes.Note(col, model)
    note["Text"] = text
    note["Back Extra"] = extra
    col.add_note(note, col.decks.id(deck))
    return note.id


def card_ids(nid):
    return col.db.list("select id from cards where nid = ? order by ord", nid)


def field_value(nid, name):
    import anki.notes
    return col.get_note(nid)[name]


def make_png(w=8, h=8):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    idat = zlib.compress((b"\x00" + b"\x80\x40\xc0" * w) * h)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


def expect_error(fn, *fragments):
    try:
        fn()
    except Exception as e:
        for frag in fragments:
            assert frag in str(e), "error %r missing fragment %r" % (str(e), frag)
        return str(e)
    raise AssertionError("expected an exception containing %r" % (fragments,))


def run(name, fn):
    try:
        fn()
        RESULTS.append((name, True, ""))
        print("PASS  %s" % name)
    except Exception:
        tb = traceback.format_exc()
        RESULTS.append((name, False, tb))
        print("FAIL  %s\n%s" % (name, tb))


# ---------------------------------------------------------------- test 0
def test0_actions_registered():
    assert "checkDeckIntegrity" in core.PLUS_ACTIONS
    assert "bulkReplaceInFields" in core.PLUS_ACTIONS
    assert "undoStatus" in core.PLUS_ACTIONS
    # 37 = 24 + round-2 SPEC 22/23 (mediaExists, storeMediaFilesBulk)
    #         + round-3 SPEC 26 (undoStatus)
    #         + round-4 SPEC 28 (renameDeck, bulkSetFlag, renameTag)
    #         + round-4 SPEC 29/30 (filteredDeckReport, emptyFilteredDeck,
    #           getEmptyCards, deleteEmptyCards)
    #         + revision-19 SPEC 32 (createFilteredDeck, rebuildFilteredDeck)
    #         + revision-20 SPEC 33 (ankihubStageOptionalTagSuggestion)
    assert len(core.PLUS_ACTIONS) == 37, core.PLUS_ACTIONS
    assert len(set(core.PLUS_ACTIONS)) == 37, "duplicate action names"
    assert core.PLUS_ACTIONS[-1] == "plusInfo"
    # summaries lockstep (SPEC 4.9): every action documented, no strays
    assert set(core.PLUS_ACTION_SUMMARIES) == set(core.PLUS_ACTIONS), (
        sorted(set(core.PLUS_ACTION_SUMMARIES) ^ set(core.PLUS_ACTIONS)))
    assert all(core.PLUS_ACTION_SUMMARIES[name].strip()
               for name in core.PLUS_ACTIONS), "empty summary"
    assert core.UNDO_BULK_REPLACE == "Agent Connect: Replace in Fields"


# ---------------------------------------------------------------- test 1
def test1_integrity_validation():
    expect_error(lambda: core.check_deck_integrity(col, None),
                 "invalid parameter: deckName: string required")
    expect_error(lambda: core.check_deck_integrity(col, ""),
                 "invalid parameter: deckName: string required")
    expect_error(lambda: core.check_deck_integrity(col, "NoSuchDeck-xyz"),
                 "deck was not found: NoSuchDeck-xyz")
    col.decks.id("IntValid")
    expect_error(lambda: core.check_deck_integrity(col, "IntValid", include_orphan_media="yes"),
                 "invalid parameter: includeOrphanMedia: boolean required")


# ---------------------------------------------------------------- test 2
def test2_integrity_clean_deck():
    fname = col.media.write_data("seven-used.png", make_png())
    add_basic("Clean", 'ok <img src="%s">' % fname, "fine")
    add_basic("Clean::Sub", "sub note", "fine")
    snap = undo_snap()
    out = core.check_deck_integrity(col, "Clean")
    assert out["missingMedia"] == [], out
    assert out["unbalancedCloze"] == [], out
    assert out["clozeCardMismatch"] == [], out
    assert out["clozeNotesWithoutCloze"] == [], out
    assert out["orphanMediaCollectionWide"] is None, out
    assert out["orphanMediaCount"] is None, out
    assert out["notesChecked"] == 2, out
    assert undo_snap() == snap, "checkDeckIntegrity touched the undo stack"


# ---------------------------------------------------------------- test 3
def test3_integrity_missing_media():
    fname = col.media.write_data("seven-present.png", make_png())
    n1 = add_basic("Missing", '[sound:seven-absent.mp3] hi',
                   'x <img src="seven-gone.png"> y <img src="seven-gone.png"> z')
    n2 = add_basic("Missing::Sub", '<img src="%s">' % fname,
                   '<img src="https://example.com/remote.png">')
    out = core.check_deck_integrity(col, "Missing")
    # duplicate reference in one field reported once; remote URL exempt;
    # present media not flagged; subdeck note included in the scope
    assert out["missingMedia"] == [
        {"noteId": n1, "field": "Front", "filename": "seven-absent.mp3"},
        {"noteId": n1, "field": "Back", "filename": "seven-gone.png"},
    ], out["missingMedia"]
    assert out["notesChecked"] == 2, out
    assert n2 not in [e["noteId"] for e in out["missingMedia"]]


# ---------------------------------------------------------------- test 4
def test4_integrity_unbalanced_cloze():
    good = add_cloze("Unbal", "{{c1::a}} and {{c2::b::hint}}")
    bad = add_cloze("Unbal", "{{c1::a}} and {{c2::b")   # 2 opens, 1 close
    # documented limitation: literal '}}' text with no cloze opens is reported
    plain = add_basic("Unbal", "brace }} noise", "clean")
    out = core.check_deck_integrity(col, "Unbal")
    assert {"noteId": bad, "field": "Text"} in out["unbalancedCloze"], out
    assert {"noteId": plain, "field": "Front"} in out["unbalancedCloze"], out
    assert all(e["noteId"] != good for e in out["unbalancedCloze"]), out
    assert len(out["unbalancedCloze"]) == 2, out


# ---------------------------------------------------------------- test 5
def test5_integrity_cloze_card_mismatch():
    ok = add_cloze("Drift", "{{c1::x}} {{c2::y}}")
    drifted = add_cloze("Drift", "{{c1::x}} {{c2::y}} {{c3::z}}")
    cids = card_ids(drifted)
    assert len(cids) == 3
    col.remove_cards_and_orphaned_notes([cids[1]])  # kill the c2 card
    out = core.check_deck_integrity(col, "Drift")
    assert out["clozeCardMismatch"] == [
        {"noteId": drifted, "expectedOrds": [0, 1, 2], "actualOrds": [0, 2]},
    ], out["clozeCardMismatch"]
    assert all(e["noteId"] != ok for e in out["clozeCardMismatch"])
    # Basic notes never checked for cloze/card drift
    add_basic("Drift", "{{c1::not a cloze model}}", "b")
    out2 = core.check_deck_integrity(col, "Drift")
    assert len(out2["clozeCardMismatch"]) == 1, out2


# ---------------------------------------------------------------- test 5b
def test5b_integrity_zero_cloze_placeholder():
    # anki's own card generation creates and KEEPS a placeholder card ord 0
    # for a cloze note whose fields yield zero effective cloze numbers
    # (rslib cardgen ensure-not-empty rule) — that state is anki-maintained,
    # NOT card/field drift, and must never hit clozeCardMismatch. It is
    # surfaced additively in clozeNotesWithoutCloze instead.
    no_marker = add_cloze("ZeroCloze", "no cloze markers at all")
    c0_only = add_cloze("ZeroCloze", "{{c0::annotation only}}")
    upper_c = add_cloze("ZeroCloze", "{{C1::uppercase is not a cloze}}")
    zero_nids = sorted([no_marker, c0_only, upper_c])
    for nid in zero_nids:
        cids = col.db.all("select ord from cards where nid = ?", nid)
        assert [row[0] for row in cids] == [0], (nid, cids)
    # a genuinely drifted cloze note in the same deck IS still reported
    drifted = add_cloze("ZeroCloze", "{{c1::x}} {{c2::y}}")
    dcids = card_ids(drifted)
    assert len(dcids) == 2
    col.remove_cards_and_orphaned_notes([dcids[1]])
    out = core.check_deck_integrity(col, "ZeroCloze")
    assert out["clozeCardMismatch"] == [
        {"noteId": drifted, "expectedOrds": [0, 1], "actualOrds": [0]},
    ], out["clozeCardMismatch"]
    assert out["clozeNotesWithoutCloze"] == zero_nids, out
    # survives Anki's Empty Cards semantics: the placeholder stays one card
    # per note, so a second audit is stable
    out2 = core.check_deck_integrity(col, "ZeroCloze")
    assert out2["clozeCardMismatch"] == out["clozeCardMismatch"]
    assert out2["clozeNotesWithoutCloze"] == zero_nids


# ---------------------------------------------------------------- test 6
def test6_integrity_orphan_media():
    used = col.media.write_data("seven-inuse.png", make_png())
    add_basic("Orphan", 'ref <img src="%s">' % used, "b")
    col.media.write_data("seven-orphan.png", make_png(4, 4))
    col.media.write_data("_seven-static.png", make_png(4, 4))  # '_' = static-use
    # a latex-generated image must count as referenced (pure extract_latex path)
    latex_nid = add_basic("Orphan", "eq [latex]x^2[/latex]", "b")
    latex_name = col._backend.extract_latex(
        text="[latex]x^2[/latex]", svg=False, expand_clozes=True).latex[0].filename
    col.media.write_data(latex_name, make_png(4, 4))
    snap = undo_snap()
    out = core.check_deck_integrity(col, "Orphan", include_orphan_media=True)
    # revision 12: renamed to orphanMediaCollectionWide (the only NON-deck-
    # scoped list in the report) + always-present count and cap
    orphans = out["orphanMediaCollectionWide"]
    assert isinstance(orphans, list), out
    assert "seven-orphan.png" in orphans, orphans
    assert used not in orphans, orphans
    assert "_seven-static.png" not in orphans, orphans
    assert latex_name not in orphans, orphans
    assert orphans == sorted(orphans)
    assert out["orphanMediaCount"] == len(orphans), out
    assert out["orphanMediaTruncated"] is False, out
    # cap: the array shrinks to the limit, the COUNT still reports the truth
    capped = core.check_deck_integrity(col, "Orphan", include_orphan_media=True,
                                       orphan_media_limit=1)
    assert capped["orphanMediaCollectionWide"] == orphans[:1], capped
    assert capped["orphanMediaCount"] == out["orphanMediaCount"], capped
    assert capped["orphanMediaTruncated"] is (out["orphanMediaCount"] > 1), capped
    # latex image absence is NOT missing media (regenerated on demand)
    assert all(e["noteId"] != latex_nid for e in out["missingMedia"]), out
    assert undo_snap() == snap, "orphan scan touched the undo stack"
    # flag off -> null, and the scan is collection-wide either way
    out2 = core.check_deck_integrity(col, "Orphan")
    assert out2["orphanMediaCollectionWide"] is None, out2
    assert out2["orphanMediaCount"] is None, out2


# ---------------------------------------------------------------- test 7
def test7_integrity_scope():
    stray = add_basic("Elsewhere", '<img src="seven-elsewhere-gone.png">', "b")
    out = core.check_deck_integrity(col, "Missing")
    assert all(e["noteId"] != stray for e in out["missingMedia"]), out
    # the note IS caught when its own deck is audited
    out2 = core.check_deck_integrity(col, "Elsewhere")
    assert [e["noteId"] for e in out2["missingMedia"]] == [stray], out2


# ---------------------------------------------------------------- test 8
def test8_replace_validation():
    nid = add_basic("RVal", "front", "back")
    expect_error(lambda: core.bulk_replace_in_fields(col, field="Front", find="a", replace="b"),
                 "invalid parameter: query: exactly one of query or noteIds required")
    expect_error(lambda: core.bulk_replace_in_fields(col, query="deck:RVal", note_ids=[nid],
                                                     field="Front", find="a", replace="b"),
                 "invalid parameter: query: exactly one of query or noteIds required")
    expect_error(lambda: core.bulk_replace_in_fields(col, query=5, field="Front", find="a", replace="b"),
                 "invalid parameter: query: string required")
    expect_error(lambda: core.bulk_replace_in_fields(col, note_ids=[True], field="Front", find="a", replace="b"),
                 "invalid parameter: noteIds: ints required")
    expect_error(lambda: core.bulk_replace_in_fields(col, note_ids=[nid], field="", find="a", replace="b"),
                 "invalid parameter: field: string required")
    expect_error(lambda: core.bulk_replace_in_fields(col, note_ids=[nid], field="Front", find="", replace="b"),
                 "invalid parameter: find: non-empty string required")
    expect_error(lambda: core.bulk_replace_in_fields(col, note_ids=[nid], field="Front", find="a", replace=7),
                 "invalid parameter: replace: string required")
    expect_error(lambda: core.bulk_replace_in_fields(col, note_ids=[nid], field="Front", find="a",
                                                     replace="b", is_regex="yes"),
                 "invalid parameter: isRegex: boolean required")
    expect_error(lambda: core.bulk_replace_in_fields(col, note_ids=[nid], field="Front", find="a",
                                                     replace="b", max_preview=-1),
                 "invalid parameter: maxPreview: int >= 0 required")
    expect_error(lambda: core.bulk_replace_in_fields(col, note_ids=[nid], field="Front", find="(unclosed",
                                                     replace="b", is_regex=True),
                 "invalid parameter: find: invalid regex:")
    expect_error(lambda: core.bulk_replace_in_fields(col, query="deck:\"unclosed", field="Front",
                                                     find="a", replace="b"),
                 "invalid parameter: query:")


# ---------------------------------------------------------------- test 9
def test9_replace_literal():
    n1 = add_basic("RLit", "alpha one", "b")
    n2 = add_basic("RLit", "two alpha alpha", "b")
    n3 = add_basic("RLit", "beta", "b")
    out = core.bulk_replace_in_fields(col, query="deck:RLit", field="Front",
                                      find="alpha", replace="gamma")
    assert out["changed"] == sorted([n1, n2]), out
    assert out["matchesTotal"] == 3, out
    assert out["unchanged"] == [n3], out
    assert out["skipped"] == [], out
    assert out["undoEntry"] == "Agent Connect: Replace in Fields", out
    assert field_value(n1, "Front") == "gamma one"
    assert field_value(n2, "Front") == "two gamma gamma"
    assert field_value(n2, "Back") == "b", "other field touched"
    # ONE merged entry, single undo reverts both notes
    assert col.undo_status().undo == "Agent Connect: Replace in Fields"
    col.undo()
    assert field_value(n1, "Front") == "alpha one"
    assert field_value(n2, "Front") == "two alpha alpha"
    assert col.undo_status().undo != "Agent Connect: Replace in Fields"


# ---------------------------------------------------------------- test 10
def test10_replace_dry_run():
    n1 = add_basic("RDry", "cat cat", "b")
    n2 = add_basic("RDry", "one cat", "b")
    n3 = add_basic("RDry", "dog", "b")
    snap = undo_snap()
    dry = core.bulk_replace_in_fields(col, query="deck:RDry", field="Front",
                                      find="cat", replace="rat", dry_run=True,
                                      max_preview=1)
    assert dry == {"wouldChange": sorted([n1, n2]), "matchesTotal": 3,
                   "unchanged": [n3], "skipped": [],
                   "preview": [{"noteId": min(n1, n2), "before": "cat cat",
                                "after": "rat rat"}],
                   "previewTruncated": True, "undoEntry": None}, dry
    assert field_value(n1, "Front") == "cat cat", "dry run wrote"
    assert undo_snap() == snap, "dry run touched the undo stack"
    # uncapped preview covers every would-change note
    dry2 = core.bulk_replace_in_fields(col, query="deck:RDry", field="Front",
                                       find="cat", replace="rat", dry_run=True)
    assert len(dry2["preview"]) == 2 and dry2["previewTruncated"] is False, dry2
    # dry-then-real: the real run matches the prediction
    real = core.bulk_replace_in_fields(col, query="deck:RDry", field="Front",
                                       find="cat", replace="rat")
    assert real["changed"] == dry["wouldChange"], real
    assert real["matchesTotal"] == dry["matchesTotal"], real
    col.undo()


# ---------------------------------------------------------------- test 11
def test11_replace_regex_and_case():
    n1 = add_basic("RRex", "range 3-14 end", "b")
    out = core.bulk_replace_in_fields(col, note_ids=[n1], field="Front",
                                      find=r"(\d+)-(\d+)", replace=r"\2-\1",
                                      is_regex=True)
    assert out["changed"] == [n1], out
    assert field_value(n1, "Front") == "range 14-3 end"
    # case-insensitive literal
    n2 = add_basic("RRex", "Alpha ALPHA alpha", "b")
    out2 = core.bulk_replace_in_fields(col, note_ids=[n2], field="Front",
                                       find="ALPHA", replace="x",
                                       case_sensitive=False)
    assert out2["matchesTotal"] == 3, out2
    assert field_value(n2, "Front") == "x x x"
    # literal mode inserts replace VERBATIM (no \-escape parsing)
    n3 = add_basic("RRex", "slash", "b")
    out3 = core.bulk_replace_in_fields(col, note_ids=[n3], field="Front",
                                       find="slash", replace=r"a\1b")
    assert out3["changed"] == [n3], out3
    assert field_value(n3, "Front") == r"a\1b"


# ---------------------------------------------------------------- test 12
def test12_replace_noop_and_skips():
    n1 = add_basic("RNoop", "same same", "b")
    cz = add_cloze("RNoop", "{{c1::cloze note}}")
    snap = undo_snap()
    # find == replace: matches found, note NOT written (shared no-op rule)
    out = core.bulk_replace_in_fields(col, query="deck:RNoop", field="Front",
                                      find="same", replace="same")
    assert out["changed"] == [] and out["undoEntry"] is None, out
    assert out["matchesTotal"] == 2, out
    assert out["unchanged"] == [n1], out
    # the Cloze note has no Front field -> skipped with reason
    assert out["skipped"] == [{"noteId": cz,
                               "reason": "field was not found in note: Front"}], out
    assert undo_snap() == snap, "no-op batch touched the undo stack"
    # stale id skipped; duplicate ids deduped (first occurrence wins)
    out2 = core.bulk_replace_in_fields(col, note_ids=[n1, n1, 424242],
                                       field="Front", find="same", replace="diff")
    assert out2["changed"] == [n1], out2
    assert out2["matchesTotal"] == 2, out2
    assert out2["skipped"] == [{"noteId": 424242,
                                "reason": "note was not found: 424242"}], out2
    assert field_value(n1, "Front") == "diff diff"
    col.undo()


# ---------------------------------------------------------------- test 13
def test13_replace_bad_template():
    n1 = add_basic("RTpl", "abc", "b")
    snap = undo_snap()
    expect_error(lambda: core.bulk_replace_in_fields(
        col, note_ids=[n1], field="Front", find="(a)", replace=r"\9",
        is_regex=True), "invalid parameter: replace:")
    assert field_value(n1, "Front") == "abc", "bad template wrote"
    assert undo_snap() == snap, "bad template touched the undo stack"


# ---------------------------------------------------------------- test 14
def test14_replace_atomic():
    n1 = add_basic("RAtom", "hit one", "b")
    n2 = add_basic("RAtom", "hit two", "b")
    original_update = col.update_note
    state = {"n": 0}

    def failing_update(note, *args, **kwargs):
        state["n"] += 1
        if state["n"] == 2:
            raise Exception("injected hard error")
        return original_update(note, *args, **kwargs)

    col.update_note = failing_update
    try:
        raised = None
        try:
            core.bulk_replace_in_fields(col, query="deck:RAtom", field="Front",
                                        find="hit", replace="miss")
        except Exception as e:
            raised = e
    finally:
        del col.update_note
    assert raised is not None, "atomic hard error did not raise"
    msg = str(raised)
    prefix = "[batch_reverted] bulkReplaceInFields failed (batch reverted): "
    assert msg.startswith(prefix), msg
    report = json.loads(msg[len(prefix):])
    assert report["failedNoteId"] == n2, report
    assert report["changedBeforeRevert"] == 1, report
    assert "injected hard error" in report["error"], report
    assert field_value(n1, "Front") == "hit one", "atomic revert failed"
    assert field_value(n2, "Front") == "hit two"
    assert col.undo_status().undo != "Agent Connect: Replace in Fields"

    # atomic=false: continue past the injected failure
    state["n"] = 0
    col.update_note = failing_update
    try:
        out = core.bulk_replace_in_fields(col, query="deck:RAtom", field="Front",
                                          find="hit", replace="miss", atomic=False)
    finally:
        del col.update_note
    assert out["changed"] == [n1], out
    assert out["skipped"] == [{"noteId": n2, "reason": "injected hard error"}], out
    assert out["undoEntry"] == "Agent Connect: Replace in Fields", out
    assert field_value(n1, "Front") == "miss one"
    assert field_value(n2, "Front") == "hit two"
    col.undo()
    assert field_value(n1, "Front") == "hit one"


# ---------------------------------------------------------------- run
run("test0_actions_registered", test0_actions_registered)
run("test1_integrity_validation", test1_integrity_validation)
run("test2_integrity_clean_deck", test2_integrity_clean_deck)
run("test3_integrity_missing_media", test3_integrity_missing_media)
run("test4_integrity_unbalanced_cloze", test4_integrity_unbalanced_cloze)
run("test5_integrity_cloze_card_mismatch", test5_integrity_cloze_card_mismatch)
run("test5b_integrity_zero_cloze_placeholder", test5b_integrity_zero_cloze_placeholder)
run("test6_integrity_orphan_media", test6_integrity_orphan_media)
run("test7_integrity_scope", test7_integrity_scope)
run("test8_replace_validation", test8_replace_validation)
run("test9_replace_literal", test9_replace_literal)
run("test10_replace_dry_run", test10_replace_dry_run)
run("test11_replace_regex_and_case", test11_replace_regex_and_case)
run("test12_replace_noop_and_skips", test12_replace_noop_and_skips)
run("test13_replace_bad_template", test13_replace_bad_template)
run("test14_replace_atomic", test14_replace_atomic)

# core stayed headless through every call above
assert "aqt" not in sys.modules, "a test path pulled in aqt"

col.close()

print("\n===== SUMMARY =====")
n_pass = sum(1 for _, ok, _ in RESULTS if ok)
for name, ok, _ in RESULTS:
    print("%s  %s" % ("PASS" if ok else "FAIL", name))
print("%d/%d passed" % (n_pass, len(RESULTS)))
sys.exit(0 if n_pass == len(RESULTS) else 1)
