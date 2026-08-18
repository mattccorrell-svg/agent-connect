# INDEPENDENT verification (round 1) of SPEC 27 suspension control.
#
# Written by a verifier, not by the implementer, on the assumption that the
# implementer's own suite (tests/headless_suspension_test.py) has blind spots.
# It deliberately re-derives every claim from the collection instead of from
# the response, and it re-checks the two things a response cannot fake:
#
#   * the CARD ROWS, card-by-card, against a snapshot taken before the batch
#   * the UNDO STACK depth, so "one Ctrl+Z" is proven rather than asserted
#
# Covered (numbering follows the verification brief):
#   1  bulkSetDueDate preserveSuspended=true  -- round trip + single undo
#   2  bulkSetDueDate preserveSuspended=false -- stock behavior
#   3  config resolution through the REAL util.setting() chain
#   4  bulkAddNotes suspend -- true / false / dryRun
#   5  dryRun vs real parity for bulkSetDueDate
#   6  buried asymmetry: unburied, NOT re-buried, and the response says so
#   7  regression: round-3 behaviors (unsuspended/changedIds, undoLabel
#      readback via undoStatus, notesSlim total == found + missing)
#
# Run with: "/Users/mattyc/Library/Application Support/AnkiProgramFiles/.venv/bin/python" tests/headless_suspend_test.py
#
# FRESH scratch collections only; never touches ~/Library/Application Support/Anki2/.
# ZERO NETWORK by construction AND by enforcement (socket deny-guard below).

import importlib
import importlib.util
import json
import os
import shutil
import socket
import sys
import traceback
import types

sys.dont_write_bytecode = True

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_PATH = os.path.join(REPO, "connect_plus", "core.py")
SCRATCH = (os.environ.get("ANCP_TEST_SCRATCH") or
           "/private/tmp/claude-501/-Users-mattyc-Downloads-prite-daily-main/"
           "6b24b91e-e4dc-4cbf-934f-6e83d3ff850a/scratchpad/ancp_susp_v1")

# ---------------------------------------------------------------- safety
# Matt's real collection lives under ~/Library/Application Support/Anki2/.
# Refuse to run at all if the scratch path could possibly land there.
assert os.path.isabs(SCRATCH), "scratch dir must be absolute"
assert not SCRATCH.startswith(os.path.expanduser("~/Library")), \
    "scratch dir must not be under ~/Library"
assert "Anki2" not in SCRATCH, "scratch dir must not name Anki2"

if os.path.exists(SCRATCH):
    shutil.rmtree(SCRATCH)
os.makedirs(SCRATCH)

# ---------------------------------------------------------------- core load
# core.py standalone: no package __init__, no aqt. The purity alarm is armed
# here, BEFORE anything can import plus.py (item 3 does, and runs last).
spec = importlib.util.spec_from_file_location("core", CORE_PATH)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
assert "aqt" not in sys.modules, "core.py (or its imports) pulled in aqt"
assert not any(m.startswith("PyQt6") for m in sys.modules), \
    "core.py (or its imports) pulled in PyQt6"

# ---------------------------------------------------------------- net guard
NETWORK_ATTEMPTS = []


def _make_deny(name):
    def _deny(*args, **kwargs):
        NETWORK_ATTEMPTS.append((name, args[:2]))
        raise RuntimeError("network access blocked by headless_suspend_test "
                           "(%s)" % name)
    return _deny


socket.socket.connect = _make_deny("socket.connect")
socket.socket.connect_ex = _make_deny("socket.connect_ex")
socket.create_connection = _make_deny("socket.create_connection")
socket.getaddrinfo = _make_deny("socket.getaddrinfo")

# ---------------------------------------------------------------- anki setup
import anki.lang  # noqa: E402
anki.lang.set_lang("en_US")
from anki.collection import Collection  # noqa: E402

# One collection per item that asserts on undo-stack depth, so a neighbouring
# test can never move the stack out from under an assertion.
col1 = Collection(os.path.join(SCRATCH, "t1_preserve.anki2"))
col2 = Collection(os.path.join(SCRATCH, "t2_stock.anki2"))
col3 = Collection(os.path.join(SCRATCH, "t3_config.anki2"))
col4 = Collection(os.path.join(SCRATCH, "t4_add.anki2"))
col5 = Collection(os.path.join(SCRATCH, "t5_parity.anki2"))
col6 = Collection(os.path.join(SCRATCH, "t6_bury.anki2"))
col7 = Collection(os.path.join(SCRATCH, "t7_regress.anki2"))

RESULTS = []

QUEUE_SUSPENDED = -1          # spelled out, NOT read from core, on purpose:
QUEUE_BURIED_SIBLING = -2     # a constant renamed in core must not silently
QUEUE_BURIED_MANUAL = -3      # rewrite what this suite is checking
QUEUE_REVIEW = 2
TYPE_NEW = 0
TYPE_REVIEW = 2


def run(name, fn):
    try:
        fn()
        RESULTS.append((name, True, ""))
        print("PASS  %s" % name, flush=True)
    except Exception:
        RESULTS.append((name, False, traceback.format_exc()))
        print("FAIL  %s" % name, flush=True)
        print(traceback.format_exc(), flush=True)


#
# helpers -- every one of these reads the DB or the backend, never a response
#

def basic(deck, front, back="b"):
    return {"deckName": deck, "modelName": "Basic",
            "fields": {"Front": front, "Back": back}, "tags": []}


def cloze(deck, text):
    return {"deckName": deck, "modelName": "Cloze",
            "fields": {"Text": text, "Back Extra": ""}, "tags": []}


def make_cards(col, deck, n, prefix):
    """n live (queue 0) Basic cards. Returns card ids in creation order."""
    col.decks.id(deck)
    r = core.bulk_add_notes(col, [basic(deck, "%s-%d" % (prefix, i))
                                  for i in range(n)], suspend=False)
    assert len(r["added"]) == n, r
    cids = [cid for nid in r["added"] for cid in col.card_ids_of_note(nid)]
    assert len(cids) == n, cids
    assert all(col.get_card(c).queue == 0 for c in cids), snapshot(col, cids)
    return cids


def snapshot(col, cids):
    """cid -> the full scheduling row. This is the ground truth an undo has to
    restore; a queue-only snapshot would let a due-date regression through."""
    snap = {}
    for cid in cids:
        row = col.db.first(
            "select type, queue, due, ivl, factor, reps, lapses, odue, odid "
            "from cards where id = ?", cid)
        snap[cid] = tuple(row) if row else None
    return snap


def queues(col, cids):
    return [col.get_card(c).queue for c in cids]


def dues(col, cids):
    return [col.get_card(c).due for c in cids]


def undo_top(col):
    """(undo label, redo label, last_step) straight from the backend.

    col.undo_status() (the python wrapper) synthesizes an empty proto whenever
    both undo and redo are empty, zeroing last_step -- see core.undo_status's
    docstring. The backend call is the one that carries the true counter, so
    the stack-depth assertions below use it."""
    st = col._backend.get_undo_status()
    return (st.undo, st.redo, st.last_step)


def undo_proto(col):
    return col._backend.get_undo_status().SerializeToString()


def note_count(col):
    return col.db.scalar("select count() from notes") or 0


def card_count(col):
    return col.db.scalar("select count() from cards") or 0


def assert_one_undo_entry(before_top, after_top, entry_name):
    """Exactly ONE undoable step was created by the batch.

    Two independent readings, because either alone is defeatable:
      * last_step advanced by exactly 1 (anki's monotonic step counter)
      * the batch's own name is on top, and the name UNDER it is whatever was
        on top before -- so a second, same-named entry cannot hide."""
    assert after_top[2] == before_top[2] + 1, \
        ("last_step moved by %d, expected 1" % (after_top[2] - before_top[2]),
         before_top, after_top)
    assert after_top[0] == entry_name, (after_top, entry_name)


def assert_json_wire_safe(payload):
    """The response crosses an HTTP boundary; a numpy int or a set would 500
    at serialization time and never be seen by these asserts otherwise."""
    assert json.loads(json.dumps(payload)) == payload, payload


def expect_error_code(fn, code):
    """Assert fn() fails with the SPEC 25 wire code, matched on the '[code] '
    prefix rather than on isinstance(err, core.PlusError).

    Deliberate: this suite loads core.py standalone AND (in item 3) again as
    ancp_verify_pkg.core when plus.py imports it, so the two PlusError classes
    are distinct objects and an isinstance check would miss the real error. The
    string prefix is what actually reaches a caller, so it is also the stricter
    thing to test."""
    try:
        fn()
    except Exception as err:
        text = str(err)
        assert text.startswith("[%s] " % code), (code, text)
        return text
    raise AssertionError("expected [%s], no exception raised" % code)


# ============================================================================
# 1 -- preserveSuspended=true: the full round trip, proven card-by-card
#
#      5 cards, 3 of them suspended in a NON-contiguous pattern (indices
#      0, 2, 4) so a bug that confuses list position with card id cannot pass.
# ============================================================================
def test1_preserve_true_round_trip():
    col = col1
    cids = make_cards(col, "T1", 5, "t1")
    suspended_ids = [cids[0], cids[2], cids[4]]
    live_ids = [cids[1], cids[3]]

    col.sched.suspend_cards(suspended_ids)
    assert queues(col, cids) == [QUEUE_SUSPENDED, 0, QUEUE_SUSPENDED, 0,
                                 QUEUE_SUSPENDED], queues(col, cids)

    DAYS = 20
    # precondition: the post-reschedule due must differ from EVERY pre due,
    # otherwise "all 5 due dates changed" would be untestable rather than true
    expected_due = col.sched.today + DAYS
    pre_dues = dues(col, cids)
    assert expected_due not in pre_dues, (expected_due, pre_dues)

    pre = snapshot(col, cids)
    before_top = undo_top(col)

    r = core.bulk_set_due_date(col, cids, str(DAYS), preserve_suspended=True)
    assert_json_wire_safe(r)

    # --- the response names the right cards, in caller order
    assert r["changed"] == 5, r
    assert r["changedIds"] == cids, (r["changedIds"], cids)
    assert r["unsuspended"] == suspended_ids, (r["unsuspended"], suspended_ids)
    assert r["resuspended"] == suspended_ids, (r["resuspended"], suspended_ids)
    assert r["unsuspended"] == r["resuspended"], r
    assert r["unburied"] == [], r
    assert r["undoEntry"] == core.UNDO_BULK_DUE, r

    # --- the COLLECTION agrees (this is the part a response cannot fake)
    post = snapshot(col, cids)
    for cid in cids:
        assert post[cid] != pre[cid], ("card row unchanged", cid, pre[cid])
    # every one of the 5 due dates really moved
    assert dues(col, cids) == [expected_due] * 5, dues(col, cids)
    for cid, pre_due in zip(cids, pre_dues):
        assert col.get_card(cid).due != pre_due, (cid, pre_due)
    assert [post[c][0] for c in cids] == [TYPE_REVIEW] * 5, post
    # the 3 are suspended AGAIN; the 2 that were never suspended stayed live
    assert queues(col, suspended_ids) == [QUEUE_SUSPENDED] * 3, \
        queues(col, suspended_ids)
    assert queues(col, live_ids) == [QUEUE_REVIEW] * 2, queues(col, live_ids)

    # --- exactly ONE entry landed on the undo stack
    after_top = undo_top(col)
    assert_one_undo_entry(before_top, after_top, core.UNDO_BULK_DUE)

    # --- a SINGLE undo restores due dates AND suspension, card by card
    col.undo()
    restored = snapshot(col, cids)
    for cid in cids:
        assert restored[cid] == pre[cid], \
            ("single undo did not restore card", cid, pre[cid], restored[cid])
    assert queues(col, cids) == [QUEUE_SUSPENDED, 0, QUEUE_SUSPENDED, 0,
                                 QUEUE_SUSPENDED], queues(col, cids)
    assert dues(col, cids) == pre_dues, (dues(col, cids), pre_dues)

    # nothing of the batch is left on the stack: the label under it is back on
    # top and the batch moved to redo -- a second entry would still be here
    now_top = undo_top(col)
    assert now_top[0] == before_top[0], (now_top, before_top)
    assert now_top[1] == core.UNDO_BULK_DUE, now_top


# ============================================================================
# 2 -- preserveSuspended=false (EXPLICIT): stock Anki behavior is still
#      reachable, and the response does not claim a re-suspension that never
#      happened.
# ============================================================================
def test2_preserve_false_is_stock_behavior():
    col = col2
    cids = make_cards(col, "T2", 5, "t2")
    suspended_ids = [cids[0], cids[2], cids[4]]
    col.sched.suspend_cards(suspended_ids)

    pre = snapshot(col, cids)
    before_top = undo_top(col)

    r = core.bulk_set_due_date(col, cids, "9", preserve_suspended=False)
    assert_json_wire_safe(r)

    assert r["changed"] == 5, r
    assert r["changedIds"] == cids, r
    assert r["unsuspended"] == suspended_ids, (r["unsuspended"], suspended_ids)
    assert r["resuspended"] == [], r          # nothing was put back...
    assert r["unburied"] == [], r
    # ...and nothing IS suspended: all 5 came back as review cards
    assert queues(col, cids) == [QUEUE_REVIEW] * 5, queues(col, cids)
    assert all(col.get_card(c).type == TYPE_REVIEW for c in cids)

    # still one entry, and still one undo to put the suspensions back
    after_top = undo_top(col)
    assert_one_undo_entry(before_top, after_top, core.UNDO_BULK_DUE)
    col.undo()
    assert snapshot(col, cids) == pre, "single undo did not restore stock run"
    assert queues(col, suspended_ids) == [QUEUE_SUSPENDED] * 3, \
        queues(col, suspended_ids)


# ============================================================================
# 5 -- dryRun predicts exactly what the real run reports.
#
#      Run the dry pass and the real pass over the SAME pre-state, then
#      compare field by field. A prediction that drifts from the write is the
#      silent-divergence bug class this project exists to prevent.
# ============================================================================
def test5_dryrun_real_parity():
    col = col5
    cids = make_cards(col, "T5", 6, "t5")
    suspended_ids = [cids[1], cids[3], cids[5]]
    col.sched.suspend_cards(suspended_ids)

    scrambled = [cids[3], cids[0], cids[5], cids[1], cids[4], cids[2]]

    pre = snapshot(col, cids)
    pre_proto = undo_proto(col)

    dry = core.bulk_set_due_date(col, scrambled, "11", preserve_suspended=True,
                                 dry_run=True)
    assert_json_wire_safe(dry)
    assert dry["undoEntry"] is None, dry

    # the dry pass wrote NOTHING: rows identical, undo stack proto identical
    assert snapshot(col, cids) == pre, "dryRun mutated card rows"
    assert undo_proto(col) == pre_proto, "dryRun touched the undo stack"

    real = core.bulk_set_due_date(col, scrambled, "11", preserve_suspended=True)
    assert_json_wire_safe(real)

    assert dry["wouldChange"] == real["changed"], (dry, real)
    assert dry["wouldChangeIds"] == real["changedIds"], (dry, real)
    assert dry["wouldUnsuspend"] == real["unsuspended"], (dry, real)
    assert dry["wouldUnbury"] == real["unburied"], (dry, real)
    # the headline claim: the predicted re-suspension set IS what happened
    assert dry["wouldResuspend"] == real["resuspended"], (dry, real)
    assert real["resuspended"] != [], real          # guard against vacuous ==
    # caller order, not id order, on both sides
    assert real["changedIds"] == scrambled, (real["changedIds"], scrambled)
    assert set(real["resuspended"]) == set(suspended_ids), real
    assert queues(col, suspended_ids) == [QUEUE_SUSPENDED] * 3, \
        queues(col, suspended_ids)

    # ...and the same parity with the flag OFF, so the dry path is reading the
    # flag rather than always echoing wouldUnsuspend
    col.undo()
    assert snapshot(col, cids) == pre, "undo did not restore before phase 2"
    dry_off = core.bulk_set_due_date(col, scrambled, "11",
                                     preserve_suspended=False, dry_run=True)
    real_off = core.bulk_set_due_date(col, scrambled, "11",
                                      preserve_suspended=False)
    assert dry_off["wouldResuspend"] == real_off["resuspended"] == [], \
        (dry_off, real_off)
    assert dry_off["wouldUnsuspend"] == real_off["unsuspended"], (dry_off, real_off)
    assert real_off["unsuspended"] != [], real_off
    assert queues(col, suspended_ids) == [QUEUE_REVIEW] * 3, \
        queues(col, suspended_ids)


# ============================================================================
# 6 -- the buried asymmetry is real AND disclosed.
#
#      Anki's set_due_date resurrects buried cards too. SPEC 27 deliberately
#      does NOT put those back. The failure mode to catch is a response that
#      quietly lumps buried ids into unsuspended/resuspended, which would tell
#      an eyeless caller its buried cards are safe when they are not.
# ============================================================================
def test6_buried_unburied_and_not_reburied():
    col = col6
    cids = make_cards(col, "T6", 4, "t6")
    susp, sib, man, plain = cids

    col.sched.suspend_cards([susp])
    col.sched.bury_cards([sib], manual=False)
    col.sched.bury_cards([man], manual=True)
    assert queues(col, cids) == [QUEUE_SUSPENDED, QUEUE_BURIED_SIBLING,
                                 QUEUE_BURIED_MANUAL, 0], queues(col, cids)

    pre = snapshot(col, cids)
    before_top = undo_top(col)

    r = core.bulk_set_due_date(col, cids, "6", preserve_suspended=True)
    assert_json_wire_safe(r)

    # the response separates the two populations
    assert r["unsuspended"] == [susp], r
    assert r["resuspended"] == [susp], r
    assert r["unburied"] == [sib, man], (r["unburied"], [sib, man])
    assert sib not in r["unsuspended"] and man not in r["unsuspended"], r
    assert sib not in r["resuspended"] and man not in r["resuspended"], r
    # and it makes no re-bury claim of any kind
    assert "reburied" not in r and "wouldRebury" not in r, sorted(r)

    # the collection agrees: buried cards are LIVE now, suspended one is not
    assert queues(col, [sib, man]) == [QUEUE_REVIEW, QUEUE_REVIEW], \
        queues(col, [sib, man])
    assert queues(col, [susp]) == [QUEUE_SUSPENDED], queues(col, [susp])
    assert queues(col, [plain]) == [QUEUE_REVIEW], queues(col, [plain])

    # one entry, and one undo puts the burial back (anki's own doing, but the
    # caller's single Ctrl+Z has to reach it)
    after_top = undo_top(col)
    assert_one_undo_entry(before_top, after_top, core.UNDO_BULK_DUE)
    col.undo()
    assert snapshot(col, cids) == pre, "single undo did not restore burials"
    assert queues(col, cids) == [QUEUE_SUSPENDED, QUEUE_BURIED_SIBLING,
                                 QUEUE_BURIED_MANUAL, 0], queues(col, cids)

    # dry run predicts the same split
    dry = core.bulk_set_due_date(col, cids, "6", preserve_suspended=True,
                                 dry_run=True)
    assert dry["wouldUnbury"] == [sib, man], dry
    assert dry["wouldUnsuspend"] == [susp] and dry["wouldResuspend"] == [susp], dry


# ============================================================================
# 4 -- bulkAddNotes suspend
#
#      A CLOZE note is used on purpose: it makes two cards from one note, so a
#      "one card per note" assumption in the reporting shows up here and only
#      here.
# ============================================================================
def test4_add_notes_suspend_true():
    col = col4
    col.decks.id("T4")
    before_notes, before_cards = note_count(col), card_count(col)
    before_top = undo_top(col)

    notes = [basic("T4", "t4-a"),
             cloze("T4", "{{c1::alpha}} and {{c2::beta}}"),
             basic("T4", "t4-b")]
    r = core.bulk_add_notes(col, notes, suspend=True)
    assert_json_wire_safe(r)

    assert len(r["added"]) == 3, r
    assert r["skipped"] == [], r
    assert r["undoEntry"] == core.UNDO_BULK_ADD, r

    expected = [cid for nid in r["added"] for cid in col.card_ids_of_note(nid)]
    assert len(expected) == 4, ("cloze should contribute 2 cards", expected)
    # the response reports EVERY created card, not one per note
    assert r["suspended"] == expected, (r["suspended"], expected)
    # ...and every one of them really is suspended in the DB
    assert queues(col, expected) == [QUEUE_SUSPENDED] * 4, queues(col, expected)
    assert col.db.scalar(
        "select count() from cards where queue != ? and id in (%s)"
        % ",".join(str(c) for c in expected), QUEUE_SUSPENDED) == 0

    # exactly one undo entry covers add + suspend
    after_top = undo_top(col)
    assert_one_undo_entry(before_top, after_top, core.UNDO_BULK_ADD)

    # ONE undo removes the notes ENTIRELY -- not "unsuspends them and leaves
    # them added", which is what a separate second entry would produce
    col.undo()
    assert note_count(col) == before_notes, "single undo left notes behind"
    assert card_count(col) == before_cards, "single undo left cards behind"
    assert col.db.scalar("select count() from cards where id in (%s)"
                         % ",".join(str(c) for c in expected)) == 0
    assert col.db.scalar("select count() from notes where id in (%s)"
                         % ",".join(str(n) for n in r["added"])) == 0


def test4b_add_notes_suspend_false():
    col = col4
    col.decks.id("T4")
    r = core.bulk_add_notes(col, [basic("T4", "t4-live-1"),
                                  cloze("T4", "{{c1::gamma}} {{c2::delta}}")],
                            suspend=False)
    assert r["suspended"] == [], r
    cids = [cid for nid in r["added"] for cid in col.card_ids_of_note(nid)]
    assert len(cids) == 3, cids
    assert queues(col, cids) == [0, 0, 0], queues(col, cids)
    assert all(col.get_card(c).type == TYPE_NEW for c in cids)


def test4c_add_notes_dryrun_predicts_and_writes_nothing():
    col = col4
    col.decks.id("T4")
    before_notes, before_cards = note_count(col), card_count(col)
    pre_proto = undo_proto(col)
    pre_top = undo_top(col)

    dry = core.bulk_add_notes(col, [basic("T4", "t4-dry-1"),
                                    basic("T4", "t4-dry-2"),
                                    cloze("T4", "{{c1::eps}}")],
                              suspend=True, dry_run=True)
    assert_json_wire_safe(dry)
    assert dry["wouldAdd"] == 3, dry
    assert dry["wouldSuspend"] is True, dry     # the resolved DECISION, a bool
    assert dry["skipped"] == [], dry
    assert dry["undoEntry"] is None, dry
    assert "added" not in dry and "suspended" not in dry, sorted(dry)

    # zero writes: no notes, no cards, and a BYTE-IDENTICAL undo stack proto
    assert note_count(col) == before_notes, "dryRun added notes"
    assert card_count(col) == before_cards, "dryRun added cards"
    assert undo_proto(col) == pre_proto, "dryRun touched the undo stack"
    assert undo_top(col) == pre_top, (undo_top(col), pre_top)

    # the prediction is honest about the flag in the other direction too
    dry_off = core.bulk_add_notes(col, [basic("T4", "t4-dry-3")],
                                  suspend=False, dry_run=True)
    assert dry_off["wouldSuspend"] is False, dry_off
    assert undo_proto(col) == pre_proto, "second dryRun touched the undo stack"


# ============================================================================
# 7 -- regression: the round-3 behaviors still hold
# ============================================================================
def test7a_regression_bulk_set_due_reports_unsuspended_and_changed_ids():
    col = col7
    cids = make_cards(col, "T7", 4, "t7a")
    col.sched.suspend_cards([cids[0], cids[3]])
    ghost = 424242424242              # no such card
    requested = [cids[2], ghost, cids[0], cids[3], cids[1], cids[2]]

    r = core.bulk_set_due_date(col, requested, "4", preserve_suspended=True)
    assert_json_wire_safe(r)
    # caller order, deduped, missing id dropped -- and 'changed' agrees
    assert r["changedIds"] == [cids[2], cids[0], cids[3], cids[1]], r
    assert r["changed"] == len(r["changedIds"]) == 4, r
    assert ghost not in r["changedIds"], r
    # the resurrection disclosure is still there, in changedIds order
    assert r["unsuspended"] == [cids[0], cids[3]], r
    assert r["resuspended"] == [cids[0], cids[3]], r
    assert queues(col, [cids[0], cids[3]]) == [QUEUE_SUSPENDED] * 2, \
        queues(col, [cids[0], cids[3]])


def test7b_regression_undo_status_reads_back_custom_label():
    col = col7
    cids = make_cards(col, "T7", 2, "t7b")
    before = core.undo_status(col)
    assert isinstance(before["lastStep"], int), before

    r = core.bulk_set_due_date(col, cids, "3", preserve_suspended=True,
                               undo_label="verify   round\tone\nlabel")
    # whitespace runs collapse; the house prefix is applied
    expected = core.UNDO_LABEL_PREFIX + "verify round one label"
    assert r["undoEntry"] == expected, r

    after = core.undo_status(col)
    assert_json_wire_safe(after)
    assert after["undo"] == expected, (after, expected)
    assert after["redo"] is None, after
    assert after["lastStep"] > before["lastStep"], (before, after)

    # the label the caller reads back is the label a single undo consumes
    col.undo()
    assert core.undo_status(col)["redo"] == expected, core.undo_status(col)

    # and a label that sanitizes to nothing is a parameter error, pre-write
    stack_before = undo_proto(col)
    expect_error_code(lambda: core.bulk_set_due_date(col, cids, "3",
                                                     undo_label="   "),
                      "invalid_param")
    assert undo_proto(col) == stack_before, "rejected label still moved the stack"


def test7c_regression_notes_slim_total_is_found_plus_missing():
    col = col7
    col.decks.id("T7")
    r = core.bulk_add_notes(col, [basic("T7", "slim-1"), basic("T7", "slim-2")],
                            suspend=False)
    real = r["added"]
    ghosts = [777777777777, 888888888888]
    requested = [real[0], ghosts[0], real[1], ghosts[1], real[0]]

    out = core.notes_slim(col, note_ids=requested)
    assert_json_wire_safe(out)
    # duplicates counted on BOTH sides, so the invariant is exact
    assert out["total"] == 3, out                       # real[0] twice + real[1]
    assert out["missing"] == ghosts, out
    assert len(requested) == out["total"] + len(out["missing"]), out
    assert len(out["notes"]) == 3, out
    assert [n["noteId"] for n in out["notes"]] == [real[0], real[1], real[0]], out

    # all-missing still holds the invariant (and does not report a phantom page)
    gone = core.notes_slim(col, note_ids=ghosts)
    assert gone["total"] == 0 and gone["missing"] == ghosts, gone
    assert gone["notes"] == [] and gone["nextOffset"] is None, gone
    assert len(ghosts) == gone["total"] + len(gone["missing"]), gone


# ============================================================================
# 3 -- config resolution, through the REAL util.setting() chain.
#
#      RUNS LAST: it is the only item that imports plus.py, which imports aqt.
#      Keeping it last leaves the core-purity alarm above meaningful.
#
#      This does NOT stub util.setting -- it stubs aqt.mw.addonManager.getConfig
#      and lets the shipped resolution chain run, because "the key is absent
#      from config" is a claim about util.setting's OWN fallback to
#      DEFAULT_CONFIG, and a stubbed setting() would skip exactly that.
# ============================================================================
def _load_plus():
    pkg_name = "ancp_verify_pkg"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [os.path.join(REPO, "connect_plus")]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg
    return importlib.import_module(pkg_name + ".plus")


class _FakeAddonManager:
    def __init__(self, config):
        self.config = config

    def getConfig(self, module_name):
        return self.config


class _FakeMw:
    def __init__(self, config):
        self.addonManager = _FakeAddonManager(config)


def test3_config_resolution():
    plus = _load_plus()
    util_mod = sys.modules["ancp_verify_pkg.util"]
    import aqt

    resolve = plus._resolve_suspension_param
    PRESERVE = core.CONFIG_PRESERVE_SUSPENDED
    SUSPEND = core.CONFIG_SUSPEND_NEW_CARDS

    class Inst(plus.PlusMixin):
        def collection(self):
            return col3

    inst = Inst()
    col3.decks.id("T3")
    original_mw = getattr(aqt, "mw", None)

    def set_config(config):
        aqt.mw = _FakeMw(config)

    try:
        # --- (a) key ABSENT from config -> the documented default applies.
        #     util.setting itself falls back to DEFAULT_CONFIG, so an older
        #     config.json that predates these keys still resolves to True.
        set_config({"webBindPort": 8766})               # neither key present
        assert util_mod.DEFAULT_CONFIG[PRESERVE] is True
        assert util_mod.DEFAULT_CONFIG[SUSPEND] is True
        assert util_mod.setting(PRESERVE) is True, "util.setting fallback broke"
        assert util_mod.setting(SUSPEND) is True, "util.setting fallback broke"
        assert resolve(None, PRESERVE, core.DEFAULT_PRESERVE_SUSPENDED_ON_RESCHEDULE) is True
        assert resolve(None, SUSPEND, core.DEFAULT_SUSPEND_NEW_CARDS) is True
        # end to end on the wire actions, with nothing passed
        r = inst.bulkAddNotes(notes=[basic("T3", "t3-default")])
        cid = r["suspended"][0]
        assert queues(col3, [cid]) == [QUEUE_SUSPENDED], r
        due = inst.bulkSetDueDate(cardIds=[cid], days="5")
        assert due["unsuspended"] == [cid] and due["resuspended"] == [cid], due
        assert queues(col3, [cid]) == [QUEUE_SUSPENDED], queues(col3, [cid])

        # --- (b) explicit True BEATS config False
        set_config({PRESERVE: False, SUSPEND: False})
        assert util_mod.setting(PRESERVE) is False      # config really says no
        assert util_mod.setting(SUSPEND) is False
        assert resolve(True, PRESERVE, True) is True
        assert resolve(True, SUSPEND, True) is True
        r = inst.bulkAddNotes(notes=[basic("T3", "t3-explicit-true")],
                              suspend=True)
        cid_t = r["suspended"][0]
        assert queues(col3, [cid_t]) == [QUEUE_SUSPENDED], r
        due = inst.bulkSetDueDate(cardIds=[cid_t], days="5",
                                  preserveSuspended=True)
        assert due["resuspended"] == [cid_t], due
        assert queues(col3, [cid_t]) == [QUEUE_SUSPENDED], queues(col3, [cid_t])
        # and with NOTHING passed, config False is obeyed -- proving the
        # explicit True above was not just the shipped default winning
        r = inst.bulkAddNotes(notes=[basic("T3", "t3-config-false")])
        assert r["suspended"] == [], r
        cid_f = col3.card_ids_of_note(r["added"][0])[0]
        assert queues(col3, [cid_f]) == [0], queues(col3, [cid_f])
        col3.sched.suspend_cards([cid_f])
        due = inst.bulkSetDueDate(cardIds=[cid_f], days="5")
        assert due["unsuspended"] == [cid_f] and due["resuspended"] == [], due
        assert queues(col3, [cid_f]) == [QUEUE_REVIEW], queues(col3, [cid_f])

        # --- (c) explicit False BEATS config True
        set_config({PRESERVE: True, SUSPEND: True})
        assert util_mod.setting(PRESERVE) is True
        assert resolve(False, PRESERVE, True) is False
        assert resolve(False, SUSPEND, True) is False
        r = inst.bulkAddNotes(notes=[basic("T3", "t3-explicit-false")],
                              suspend=False)
        assert r["suspended"] == [], r
        cid_x = col3.card_ids_of_note(r["added"][0])[0]
        assert queues(col3, [cid_x]) == [0], queues(col3, [cid_x])
        col3.sched.suspend_cards([cid_x])
        due = inst.bulkSetDueDate(cardIds=[cid_x], days="5",
                                  preserveSuspended=False)
        assert due["unsuspended"] == [cid_x] and due["resuspended"] == [], due
        assert queues(col3, [cid_x]) == [QUEUE_REVIEW], queues(col3, [cid_x])

        # --- unreadable config (no aqt.mw at all) -> documented default, and
        #     NOT a crash: a write action must not fail because config is late
        aqt.mw = None
        assert resolve(None, PRESERVE, core.DEFAULT_PRESERVE_SUSPENDED_ON_RESCHEDULE) is True
        assert resolve(None, SUSPEND, core.DEFAULT_SUSPEND_NEW_CARDS) is True
        r = inst.bulkAddNotes(notes=[basic("T3", "t3-no-mw")])
        assert queues(col3, r["suspended"]) == [QUEUE_SUSPENDED], r

        # --- a hand-edited NON-boolean falls back to the documented default
        set_config({PRESERVE: "false", SUSPEND: 0})
        assert resolve(None, PRESERVE, True) is True
        assert resolve(None, SUSPEND, True) is True
        # --- a bad EXPLICIT value is passed through so core rejects it,
        #     rather than this layer silently swallowing it into config
        set_config({PRESERVE: True, SUSPEND: True})
        assert resolve("yes", SUSPEND, True) == "yes"
        notes_before, cards_before = note_count(col3), card_count(col3)
        assert "suspend" in expect_error_code(
            lambda: inst.bulkAddNotes(notes=[basic("T3", "t3-bad")],
                                      suspend="yes"), "invalid_param")
        assert "preserveSuspended" in expect_error_code(
            lambda: inst.bulkSetDueDate(cardIds=[cid_x], days="5",
                                        preserveSuspended="no"), "invalid_param")
        # rejected BEFORE any write, so a typo cannot half-apply a policy
        assert (note_count(col3), card_count(col3)) == (notes_before, cards_before), \
            "a rejected suspension flag still wrote"

        # --- the three sources of the default really are in lockstep
        shipped = json.load(open(os.path.join(REPO, "connect_plus", "config.json"),
                                 encoding="utf-8"))
        for key, constant in ((PRESERVE, core.DEFAULT_PRESERVE_SUSPENDED_ON_RESCHEDULE),
                              (SUSPEND, core.DEFAULT_SUSPEND_NEW_CARDS)):
            assert constant is True, (key, constant)
            assert shipped[key] is constant, (key, shipped.get(key))
            assert util_mod.DEFAULT_CONFIG[key] is constant, key
    finally:
        aqt.mw = original_mw


if __name__ == "__main__":
    run("1  preserveSuspended=true round trip + single undo",
        test1_preserve_true_round_trip)
    run("2  preserveSuspended=false is stock behavior",
        test2_preserve_false_is_stock_behavior)
    run("4a bulkAddNotes suspend=true (cloze: 2 cards/note)",
        test4_add_notes_suspend_true)
    run("4b bulkAddNotes suspend=false leaves cards active",
        test4b_add_notes_suspend_false)
    run("4c bulkAddNotes dryRun predicts and writes nothing",
        test4c_add_notes_dryrun_predicts_and_writes_nothing)
    run("5  dryRun/real parity for bulkSetDueDate",
        test5_dryrun_real_parity)
    run("6  buried: unburied, NOT re-buried, and disclosed",
        test6_buried_unburied_and_not_reburied)
    run("7a regression: unsuspended + changedIds",
        test7a_regression_bulk_set_due_reports_unsuspended_and_changed_ids)
    run("7b regression: undoStatus reads back a custom undoLabel",
        test7b_regression_undo_status_reads_back_custom_label)
    run("7c regression: notesSlim total == found, + missing",
        test7c_regression_notes_slim_total_is_found_plus_missing)
    # last: the only item that imports aqt (see the note on test3)
    run("3  config resolution (absent key / explicit beats config)",
        test3_config_resolution)

    assert not NETWORK_ATTEMPTS, ("network was attempted", NETWORK_ATTEMPTS)

    failed = [name for name, ok, _ in RESULTS if not ok]
    print("\n%d/%d checks passed" % (len(RESULTS) - len(failed), len(RESULTS)),
          flush=True)
    if failed:
        for name in failed:
            print("FAILED: %s" % name, flush=True)
    sys.exit(1 if failed else 0)
