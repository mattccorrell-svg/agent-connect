# Headless regression tests for the review-fix round:
#   1. bulkSetDueDate with a bad days string must leave undo_status()
#      bit-identical (no phantom Redo entry from popping an empty custom
#      undo entry) — SPEC 16.2 "undo stack left untouched".
#   2. exportDeckApkg must reject an outPath that is a directory (or ends
#      in a path separator) instead of writing a surprise sibling file.
#   3. exportDeckApkg must reject outPath="" (empty string).
#
# Run with: <anki-venv>/bin/python headless_fixes_test.py
# Uses a FRESH scratch collection; never touches ~/Library/Application Support/Anki2/.

import importlib.util
import os
import shutil
import sys
import tempfile
import traceback

SCRATCH = (os.environ.get("ANCP_TEST_SCRATCH")
           or tempfile.mkdtemp(prefix="ancp_test_fixes_"))
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

import anki.lang
anki.lang.set_lang("en_US")
from anki.collection import Collection

col = Collection(os.path.join(SCRATCH, "test.anki2"))

RESULTS = []


def run(name, fn):
    try:
        fn()
        RESULTS.append((name, True, ""))
        print("PASS  %s" % name)
    except Exception:
        tb = traceback.format_exc()
        RESULTS.append((name, False, tb))
        print("FAIL  %s\n%s" % (name, tb))


def add_note(deck, front):
    note = col.new_note(col.models.by_name("Basic"))
    note["Front"] = front
    note["Back"] = "b"
    col.add_note(note, col.decks.id(deck))
    return note


def undo_snapshot():
    s = col.undo_status()
    return (s.undo, s.redo, s.last_step, s.SerializeToString())


# ---------------------------------------------------------------- test 1
def test1_bad_days_leaves_undo_stack_untouched():
    note = add_note("DueDeck", "due-front-1")
    cid = col.card_ids_of_note(note.id)[0]
    # put a real entry on the stack so a phantom pop/redo would be visible
    core.bulk_set_due_date(col, [cid], "0")
    before = undo_snapshot()
    for bad in ("abc", "bogus", "1-", "-7", "5 ", "!3", ""):
        try:
            core.bulk_set_due_date(col, [cid], bad)
            raise AssertionError("bad days %r did not raise" % bad)
        except AssertionError:
            raise
        except Exception as e:
            assert str(e).startswith("[invalid_param] invalid parameter: days:"), (bad, str(e))
        after = undo_snapshot()
        assert after == before, (
            "undo_status changed after bad days %r: %r -> %r" % (bad, before, after))
    # message echoes the bad string (backend InvalidInput message shape)
    try:
        core.bulk_set_due_date(col, [cid], "abc")
    except Exception as e:
        assert str(e) == "[invalid_param] invalid parameter: days: abc", str(e)


# ---------------------------------------------------------------- test 2
def test2_valid_days_grammar_still_accepted():
    note = add_note("DueDeck", "due-front-2")
    cid = col.card_ids_of_note(note.id)[0]
    for good in ("0", "5", "1-7", "3!", "1-7!"):
        result = core.bulk_set_due_date(col, [cid], good)
        assert result["changed"] == 1, (good, result)
        assert result["undoEntry"] == "Agent Connect: Bulk Due Date", result
        col.undo()  # keep the stack tidy between iterations


# ---------------------------------------------------------------- test 3
def test3_export_rejects_directory_outpath():
    add_note("ExportDeck", "export-front-1")
    target_dir = os.path.join(SCRATCH, "apkg_target_dir")
    os.makedirs(target_dir)
    for bad in (target_dir, target_dir + os.sep):
        siblings_before = sorted(os.listdir(SCRATCH))
        inside_before = sorted(os.listdir(target_dir))
        try:
            core.export_deck_apkg(col, "ExportDeck", out_path=bad)
            raise AssertionError("directory outPath %r did not raise" % bad)
        except AssertionError:
            raise
        except Exception as e:
            assert str(e).startswith("[invalid_param] invalid parameter: outPath: is a directory:"), (bad, str(e))
        assert sorted(os.listdir(SCRATCH)) == siblings_before, "sibling file written for %r" % bad
        assert sorted(os.listdir(target_dir)) == inside_before, "file written inside dir for %r" % bad


# ---------------------------------------------------------------- test 4
def test4_export_rejects_empty_outpath():
    try:
        core.export_deck_apkg(col, "ExportDeck", out_path="")
        raise AssertionError("empty outPath did not raise")
    except AssertionError:
        raise
    except Exception as e:
        assert str(e) == "[invalid_param] invalid parameter: outPath: string required", str(e)


# ---------------------------------------------------------------- test 5
def test5_export_file_outpath_still_works():
    out = os.path.join(SCRATCH, "export-ok.apkg")
    result = core.export_deck_apkg(col, "ExportDeck", out_path=out)
    assert result["path"] == out, result
    assert os.path.isfile(out), "apkg not written"
    assert result["sizeBytes"] == os.path.getsize(out), result
    assert result["notesExported"] == 1, result
    # never-overwrite suffixing still intact
    result2 = core.export_deck_apkg(col, "ExportDeck", out_path=out)
    assert result2["path"] == os.path.join(SCRATCH, "export-ok-2.apkg"), result2
    assert os.path.isfile(result2["path"])


run("test1_bad_days_leaves_undo_stack_untouched", test1_bad_days_leaves_undo_stack_untouched)
run("test2_valid_days_grammar_still_accepted", test2_valid_days_grammar_still_accepted)
run("test3_export_rejects_directory_outpath", test3_export_rejects_directory_outpath)
run("test4_export_rejects_empty_outpath", test4_export_rejects_empty_outpath)
run("test5_export_file_outpath_still_works", test5_export_file_outpath_still_works)

col.close()

failures = [name for name, ok, _ in RESULTS if not ok]
print("\n%d/%d passed" % (len(RESULTS) - len(failures), len(RESULTS)))
sys.exit(1 if failures else 0)
