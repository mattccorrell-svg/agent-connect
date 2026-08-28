# Headless verification for SPEC 27 — suspension control (spec revision 15).
#
#   * bulkAddNotes   `suspend`           (config 'suspendNewCards', ships FALSE since rev 16)
#   * bulkSetDueDate `preserveSuspended` (config 'preserveSuspendedOnReschedule',
#                                         ships TRUE) + its new `dryRun`
#
# Both defaults are DELIBERATE deviations from Anki's own behavior, so this
# suite pins down four things the rest of the suites cannot: the deviation is
# really the default, it is really switchable, each action's re-suspension
# lands inside the SAME undo entry (one Ctrl+Z, no half-reverted state), and
# the response says what actually happened rather than what was requested.
#
# Run with: <anki-venv>/bin/python headless_suspension_test.py
#
# Uses a FRESH scratch collection; never touches ~/Library/Application Support/Anki2/.

import ast
import importlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import traceback
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = (os.environ.get("ANCP_TEST_SCRATCH")
           or tempfile.mkdtemp(prefix="ancp_susp_"))
CORE_PATH = os.path.join(REPO, "connect_plus", "core.py")

# safety guards
assert not SCRATCH.startswith(os.path.expanduser("~/Library")), "scratch dir must not be under ~/Library"
assert "Anki2" not in SCRATCH

if os.path.exists(SCRATCH):
    shutil.rmtree(SCRATCH)
os.makedirs(SCRATCH)

# load core.py standalone (no package __init__, no aqt) and verify purity
spec = importlib.util.spec_from_file_location("core", CORE_PATH)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
assert "aqt" not in sys.modules, "core.py (or its imports) pulled in aqt"
assert not any(m.startswith("PyQt6") for m in sys.modules), \
    "core.py (or its imports) pulled in PyQt6"

import anki.lang
anki.lang.set_lang("en_US")
from anki.collection import Collection

col = Collection(os.path.join(SCRATCH, "susp.anki2"))

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


def note(deck, front, back="b"):
    return {"deckName": deck, "modelName": "Basic",
            "fields": {"Front": front, "Back": back}, "tags": []}


def queues(cids):
    return [col.get_card(cid).queue for cid in cids]


def undo_snap():
    return col.undo_status().SerializeToString()


def card_rows():
    return col.db.all("select id, type, queue, due, ivl from cards order by id")


def note_count():
    return col.db.scalar("select count() from notes") or 0


def code_of(fn):
    try:
        fn()
    except Exception as err:
        return str(err).split("] ", 1)[0].lstrip("[")
    raise AssertionError("expected an exception")


# ============================================================================
# 1 — bulkAddNotes suspend=true leaves new cards suspended, one undo entry
#     (default is STOCK/live since revision 16 — pinned at the end)
# ============================================================================
def test1_add_suspends_by_default():
    col.decks.id("S1")
    before = note_count()
    r = core.bulk_add_notes(col, [note("S1", "s1-%d" % i) for i in range(3)],
                            suspend=True)

    assert len(r["added"]) == 3, r
    # every card of every added note is reported AND actually suspended
    expected = [cid for nid in r["added"] for cid in col.card_ids_of_note(nid)]
    assert r["suspended"] == expected, (r["suspended"], expected)
    assert queues(r["suspended"]) == [core.QUEUE_SUSPENDED] * 3, queues(r["suspended"])

    # ONE undo entry covers adds + suspend: a single undo removes the notes
    # entirely (not "unsuspends them and leaves them added")
    assert r["undoEntry"] == core.UNDO_BULK_ADD, r
    assert col.undo_status().undo == core.UNDO_BULK_ADD
    col.undo()
    assert note_count() == before, "single undo did not remove the batch"
    assert col.db.scalar("select count() from cards where id in (%s)"
                         % ",".join(str(c) for c in expected)) == 0, \
        "cards survived the undo"
    assert col.undo_status().undo != core.UNDO_BULK_ADD


def test2_add_suspends_every_card_of_a_multi_card_note():
    # a notetype generating 2 cards per note: 'suspended' must list BOTH, or a
    # caller reviewing a "suspended draft" gets ambushed by the reverse cards
    col.decks.id("S2")
    model = col.models.by_name("Basic (and reversed card)")
    assert model is not None, "stock notetype missing"
    r = core.bulk_add_notes(col, [{"deckName": "S2",
                                   "modelName": "Basic (and reversed card)",
                                   "fields": {"Front": "s2-a", "Back": "s2-b"},
                                   "tags": []}], suspend=True)
    cids = col.card_ids_of_note(r["added"][0])
    assert len(cids) == 2, cids
    assert r["suspended"] == list(cids), (r["suspended"], cids)
    assert queues(cids) == [core.QUEUE_SUSPENDED] * 2, queues(cids)


def test3_add_suspend_false_is_stock_anki():
    col.decks.id("S3")
    r = core.bulk_add_notes(col, [note("S3", "s3-a")], suspend=False)
    cids = col.card_ids_of_note(r["added"][0])
    assert r["suspended"] == [], r
    assert queues(cids) == [0], queues(cids)

    # explicit None means "nothing said" -> the documented default applies,
    # which since revision 16 is FALSE (stock behavior: new cards live)
    r = core.bulk_add_notes(col, [note("S3", "s3-b")], suspend=None)
    assert r["suspended"] == [], r
    assert queues(col.find_cards("s3-b")) == [0], r
    assert core.DEFAULT_SUSPEND_NEW_CARDS is False


def test4_add_suspend_is_type_checked_before_any_write():
    col.decks.id("S4")
    before, snap = note_count(), undo_snap()
    assert code_of(lambda: core.bulk_add_notes(
        col, [note("S4", "s4-a")], suspend="yes")) == "invalid_param"
    assert code_of(lambda: core.bulk_add_notes(
        col, [note("S4", "s4-a")], suspend=1)) == "invalid_param"
    assert note_count() == before, "a bad suspend value still wrote notes"
    assert undo_snap() == snap, "a bad suspend value touched the undo stack"


def test5_add_reports_the_decision_on_every_return_path():
    col.decks.id("S5")
    # empty batch: both shapes still answer the question
    assert core.bulk_add_notes(col, []) == \
        {"added": [], "suspended": [], "skipped": [], "undoEntry": None}
    assert core.bulk_add_notes(col, [], dry_run=True) == \
        {"wouldAdd": 0, "wouldSuspend": False, "skipped": [], "undoEntry": None}

    # all-skipped batch: nothing written, no empty undo entry left behind
    snap = undo_snap()
    r = core.bulk_add_notes(col, [dict(note("S5", "s5-x"), modelName="NoSuchZZZ")])
    assert r == {"added": [], "suspended": [], "skipped":
                 [{"index": 0, "reason": "model was not found: NoSuchZZZ"}],
                 "undoEntry": None}, r
    assert undo_snap() == snap, "an all-skipped batch touched the undo stack"

    # dry run predicts the decision and writes NOTHING
    before, snap = note_count(), undo_snap()
    dry = core.bulk_add_notes(col, [note("S5", "s5-a")], dry_run=True,
                              suspend=True)
    assert dry == {"wouldAdd": 1, "wouldSuspend": True, "skipped": [],
                   "undoEntry": None}, dry
    dry_off = core.bulk_add_notes(col, [note("S5", "s5-a")], dry_run=True)
    assert dry_off["wouldSuspend"] is False, dry_off   # rev-16 shipped default
    assert note_count() == before and undo_snap() == snap, "dry run wrote"

    # dry prediction matches the real run — on BOTH sides of the flag
    real = core.bulk_add_notes(col, [note("S5", "s5-a")], suspend=True)
    assert len(real["added"]) == dry["wouldAdd"] == 1, real
    assert bool(real["suspended"]) is dry["wouldSuspend"], (real, dry)
    real_off = core.bulk_add_notes(col, [note("S5", "s5-b")])
    assert bool(real_off["suspended"]) is dry_off["wouldSuspend"], \
        (real_off, dry_off)


def test6_add_suspend_respects_undo_label():
    col.decks.id("S6")
    r = core.bulk_add_notes(col, [note("S6", "s6-a")], undo_label="PI 7 draft",
                            suspend=True)
    assert r["undoEntry"] == "Agent Connect: PI 7 draft", r
    assert col.undo_status().undo == "Agent Connect: PI 7 draft"
    assert queues(r["suspended"]) == [core.QUEUE_SUSPENDED]
    # the labelled entry still covers BOTH halves
    col.undo()
    assert col.db.scalar("select count() from cards where id in (%s)"
                         % ",".join(str(c) for c in r["suspended"])) == 0


# ============================================================================
# 7 — bulkSetDueDate puts the suspensions back BY DEFAULT
# ============================================================================
def _fresh_cards(deck, n, prefix):
    r = core.bulk_add_notes(col, [note(deck, "%s-%d" % (prefix, i))
                                  for i in range(n)], suspend=False)
    return [col.card_ids_of_note(nid)[0] for nid in r["added"]]


def test7_due_date_preserves_suspension_by_default():
    col.decks.id("S7")
    cids = _fresh_cards("S7", 3, "s7")
    core.bulk_suspend(col, cids)
    assert queues(cids) == [core.QUEUE_SUSPENDED] * 3
    pre = [(c.type, c.queue, c.due, c.ivl) for c in (col.get_card(i) for i in cids)]

    r = core.bulk_set_due_date(col, cids, "5!")
    # the resurrection is still DISCLOSED, and the repair is disclosed beside it
    assert r["unsuspended"] == cids, r
    assert r["resuspended"] == cids, r
    assert r["unburied"] == [], r
    assert r["changed"] == 3 and r["changedIds"] == cids, r
    assert core.DEFAULT_PRESERVE_SUSPENDED_ON_RESCHEDULE is True

    # net effect: suspended again, but the RESCHEDULE really landed
    assert queues(cids) == [core.QUEUE_SUSPENDED] * 3, queues(cids)
    for cid in cids:
        card = col.get_card(cid)
        assert card.ivl == 3 or card.ivl == 5, card.ivl   # '5!' forces ivl 5
        assert card.type == 2, card.type
        assert card.due == col.sched.today + 5, (card.due, col.sched.today)

    # ONE undo entry for reschedule + re-suspend: a single undo restores the
    # exact pre-state, never a half-reverted one
    assert r["undoEntry"] == core.UNDO_BULK_DUE, r
    assert col.undo_status().undo == core.UNDO_BULK_DUE
    col.undo()
    post = [(c.type, c.queue, c.due, c.ivl) for c in (col.get_card(i) for i in cids)]
    assert post == pre, (post, pre)
    assert col.undo_status().undo != core.UNDO_BULK_DUE


def test8_due_date_preserve_off_is_stock_anki():
    col.decks.id("S8")
    cids = _fresh_cards("S8", 2, "s8")
    core.bulk_suspend(col, cids)
    r = core.bulk_set_due_date(col, cids, "4", preserve_suspended=False)
    assert r["unsuspended"] == cids and r["resuspended"] == [], r
    assert queues(cids) == [2, 2], queues(cids)


def test9_buried_cards_are_not_re_buried():
    # the documented ASYMMETRY (SPEC 27 / Deviation 13b): anki's unbury on
    # reschedule is desirable, only suspension is put back
    col.decks.id("S9")
    cids = _fresh_cards("S9", 3, "s9")
    core.bulk_suspend(col, cids[:1])
    col.sched.bury_cards(cids[1:2], manual=True)
    assert queues(cids) == [core.QUEUE_SUSPENDED, -3, 0], queues(cids)

    r = core.bulk_set_due_date(col, cids, "2")
    assert r["unsuspended"] == cids[:1], r
    assert r["unburied"] == cids[1:2], r
    assert r["resuspended"] == cids[:1], r        # the buried card is NOT here
    assert queues(cids) == [core.QUEUE_SUSPENDED, 2, 2], queues(cids)


def test10_due_date_dry_run_predicts_and_writes_nothing():
    col.decks.id("S10")
    cids = _fresh_cards("S10", 4, "s10")
    core.bulk_suspend(col, cids[:2])
    col.sched.bury_cards(cids[2:3], manual=True)

    rows, snap = card_rows(), undo_snap()
    dry = core.bulk_set_due_date(col, cids, "6", dry_run=True)
    assert dry == {"wouldChange": 4, "wouldChangeIds": cids,
                   "wouldUnsuspend": cids[:2], "wouldUnbury": cids[2:3],
                   "wouldResuspend": cids[:2], "undoEntry": None}, dry
    assert card_rows() == rows, "dry run changed card state"
    assert undo_snap() == snap, "dry run touched the undo stack"

    # preserve off -> the prediction changes, still zero writes
    dry_off = core.bulk_set_due_date(col, cids, "6", dry_run=True,
                                     preserve_suspended=False)
    assert dry_off["wouldResuspend"] == [], dry_off
    assert dry_off["wouldUnsuspend"] == cids[:2], dry_off
    assert card_rows() == rows and undo_snap() == snap, "dry run wrote"

    # empty / unknown-id dry run answers in the same shape
    assert core.bulk_set_due_date(col, [999999999999], "1", dry_run=True) == \
        {"wouldChange": 0, "wouldChangeIds": [], "wouldUnsuspend": [],
         "wouldUnbury": [], "wouldResuspend": [], "undoEntry": None}

    # the real run matches the prediction, key for key
    real = core.bulk_set_due_date(col, cids, "6")
    assert real["changed"] == dry["wouldChange"], (real, dry)
    assert real["changedIds"] == dry["wouldChangeIds"], (real, dry)
    assert real["unsuspended"] == dry["wouldUnsuspend"], (real, dry)
    assert real["unburied"] == dry["wouldUnbury"], (real, dry)
    assert real["resuspended"] == dry["wouldResuspend"], (real, dry)


def test11_due_date_param_errors_leave_the_stack_untouched():
    col.decks.id("S11")
    cids = _fresh_cards("S11", 1, "s11")
    rows, snap = card_rows(), undo_snap()

    assert code_of(lambda: core.bulk_set_due_date(
        col, cids, "1", preserve_suspended="no")) == "invalid_param"
    assert code_of(lambda: core.bulk_set_due_date(
        col, cids, "1", preserve_suspended=0)) == "invalid_param"
    # validation still fires under dryRun (dryRun suppresses writes, not checks)
    assert code_of(lambda: core.bulk_set_due_date(
        col, cids, "bogus", dry_run=True)) == "invalid_param"
    assert code_of(lambda: core.bulk_set_due_date(
        col, cids, "1", dry_run=True, preserve_suspended="no")) == "invalid_param"
    # dryRun is type-checked too (revision-15 fix pass). A truthy non-boolean
    # would otherwise turn a requested reschedule into a zero-write PREDICTION
    # and still answer success -- dryRun: "false" is the mistake an LLM caller
    # actually makes -- and a falsy non-boolean would write when a preview was
    # asked for.
    for bad in ("false", "no", 1, 0, [], {}):
        assert code_of(lambda: core.bulk_set_due_date(
            col, cids, "1", dry_run=bad)) == "invalid_param", bad

    assert card_rows() == rows and undo_snap() == snap


# ============================================================================
# 12 — config plumbing: the three copies of each default agree, and the
#      wrapper resolves param > config > documented default
# ============================================================================
def _default_config_literal():
    """util.DEFAULT_CONFIG read WITHOUT importing util (it imports aqt)."""
    source = open(os.path.join(REPO, "connect_plus", "util.py"),
                  encoding="utf-8").read()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "DEFAULT_CONFIG" for t in node.targets):
            out = {}
            for key, value in zip(node.value.keys, node.value.values):
                try:
                    out[ast.literal_eval(key)] = ast.literal_eval(value)
                except ValueError:
                    continue          # env-var lookups etc.
            return out
    raise AssertionError("DEFAULT_CONFIG not found in util.py")


def test12_config_defaults_are_in_lockstep():
    shipped = json.load(open(os.path.join(REPO, "connect_plus", "config.json"),
                             encoding="utf-8"))
    defaults = _default_config_literal()
    pairs = ((core.CONFIG_PRESERVE_SUSPENDED,
              core.DEFAULT_PRESERVE_SUSPENDED_ON_RESCHEDULE, True),
             (core.CONFIG_SUSPEND_NEW_CARDS, core.DEFAULT_SUSPEND_NEW_CARDS,
              False))                                     # rev-16 split
    for key, constant, want in pairs:
        assert constant is want, (key, constant, want)
        assert shipped[key] is constant, (key, shipped.get(key))
        assert defaults[key] is constant, (key, defaults.get(key))


def _load_plus():
    pkg_name = "ancp_susp_pkg"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [os.path.join(REPO, "connect_plus")]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg
    return importlib.import_module(pkg_name + ".plus")


def test13_wrapper_resolves_param_over_config_over_default():
    plus = _load_plus()
    util_mod = sys.modules["ancp_susp_pkg.util"]

    # the shipped DEFAULT_CONFIG really carries both keys, so util.setting()
    # answers even when config.json predates them
    assert util_mod.DEFAULT_CONFIG[core.CONFIG_SUSPEND_NEW_CARDS] is False
    assert util_mod.DEFAULT_CONFIG[core.CONFIG_PRESERVE_SUSPENDED] is True

    resolve = plus._resolve_suspension_param
    orig = util_mod.setting
    try:
        # explicit param wins over config, in BOTH directions...
        util_mod.setting = lambda key: False
        assert resolve(True, core.CONFIG_SUSPEND_NEW_CARDS, True) is True
        util_mod.setting = lambda key: True
        assert resolve(False, core.CONFIG_SUSPEND_NEW_CARDS, True) is False
        # ...and a BAD explicit value is passed through untouched, so core
        # raises [invalid_param] instead of this layer swallowing it
        assert resolve("yes", core.CONFIG_SUSPEND_NEW_CARDS, True) == "yes"

        # None -> config
        util_mod.setting = lambda key: False
        assert resolve(None, core.CONFIG_SUSPEND_NEW_CARDS, True) is False

        # older config.json without the key -> util.setting's own
        # DEFAULT_CONFIG fallback (this is the real code path, not a stub)
        util_mod.setting = lambda key: {}.get(key, util_mod.DEFAULT_CONFIG[key])
        assert resolve(None, core.CONFIG_SUSPEND_NEW_CARDS, True) is False
        assert resolve(None, core.CONFIG_PRESERVE_SUSPENDED, True) is True

        # unreadable config (no aqt.mw yet) -> documented default, no crash
        def boom(key):
            raise Exception("setting %s not found" % key)
        util_mod.setting = boom
        assert resolve(None, core.CONFIG_SUSPEND_NEW_CARDS, True) is True

        # hand-edited non-boolean -> documented default (documented behavior)
        util_mod.setting = lambda key: "true"
        assert resolve(None, core.CONFIG_SUSPEND_NEW_CARDS, True) is True
        util_mod.setting = lambda key: 0
        assert resolve(None, core.CONFIG_PRESERVE_SUSPENDED, True) is True
    finally:
        util_mod.setting = orig


def test14_wrapper_end_to_end_and_discoverability():
    plus = _load_plus()
    util_mod = sys.modules["ancp_susp_pkg.util"]
    orig = util_mod.setting

    class Inst(plus.PlusMixin):
        def collection(self):
            return col

    inst = Inst()
    col.decks.id("S14")
    try:
        # config says "do not suspend" -> the wire action obeys config
        util_mod.setting = lambda key: (False if key in
                                        (core.CONFIG_SUSPEND_NEW_CARDS,
                                         core.CONFIG_PRESERVE_SUSPENDED)
                                        else util_mod.DEFAULT_CONFIG[key])
        r = inst.bulkAddNotes(notes=[note("S14", "s14-a")])
        assert r["suspended"] == [], r
        assert queues(col.card_ids_of_note(r["added"][0])) == [0]

        # ...and an explicit param still overrides it
        r = inst.bulkAddNotes(notes=[note("S14", "s14-b")], suspend=True)
        assert queues(r["suspended"]) == [core.QUEUE_SUSPENDED], r

        # config opts IN to suspension (rev 16: shipped value is False,
        # so this exercises the config-True path explicitly)
        util_mod.setting = lambda key: True
        r = inst.bulkAddNotes(notes=[note("S14", "s14-c")])
        assert queues(r["suspended"]) == [core.QUEUE_SUSPENDED], r
        cid = r["suspended"][0]
        due = inst.bulkSetDueDate(cardIds=[cid], days="3")
        assert due["unsuspended"] == [cid] and due["resuspended"] == [cid], due
        assert queues([cid]) == [core.QUEUE_SUSPENDED], queues([cid])
        # the wrapper's dryRun reaches core's dry path
        dry = inst.bulkSetDueDate(cardIds=[cid], days="3", dryRun=True)
        assert dry["wouldResuspend"] == [cid] and dry["undoEntry"] is None, dry

        # a bad explicit value is a parameter error at the wire, not a silent
        # fallback to config
        assert code_of(lambda: inst.bulkAddNotes(
            notes=[note("S14", "s14-d")], suspend="yes")) == "invalid_param"
        assert code_of(lambda: inst.bulkSetDueDate(
            cardIds=[cid], days="1", preserveSuspended="no")) == "invalid_param"

        # --- discoverability: plusInfo alone must teach the deviation
        info = inst.plusInfo()
        docs = info["actionDocs"]
        assert "suspend=null" in docs["bulkAddNotes"]["params"], docs["bulkAddNotes"]
        assert "preserveSuspended=null" in docs["bulkSetDueDate"]["params"], \
            docs["bulkSetDueDate"]
        assert "dryRun=false" in docs["bulkSetDueDate"]["params"], docs["bulkSetDueDate"]
        add_summary = docs["bulkAddNotes"]["summary"]
        assert "suspended-draft" in add_summary, add_summary   # opt-in, rev 16
        assert core.CONFIG_SUSPEND_NEW_CARDS in add_summary, add_summary
        assert "suspend=true" in add_summary, add_summary
        due_summary = docs["bulkSetDueDate"]["summary"]
        assert "DEVIATION" in due_summary, due_summary         # still shipped-on
        assert core.CONFIG_PRESERVE_SUSPENDED in due_summary, due_summary
        assert "preserveSuspended=false" in due_summary, due_summary
        assert "suspended: [cardId]" in docs["bulkAddNotes"]["returns"]
        assert "wouldSuspend" in docs["bulkAddNotes"]["returns"]
        assert "resuspended" in docs["bulkSetDueDate"]["returns"]
        assert "wouldResuspend" in docs["bulkSetDueDate"]["returns"]

        recipe = next(r for r in info["recipes"]
                      if r["name"] == "suspended-draft workflow")
        assert recipe["example"]["action"] in core.PLUS_ACTIONS
        for token in ("suspendNewCards", "preserveSuspendedOnReschedule",
                      "resuspended", "undo"):
            assert token in recipe["description"], token
    finally:
        util_mod.setting = orig


# ============================================================================
# 15 — the failure paths say what ACTUALLY happened (revision-15 fix pass)
#
#      Two distinct failures hide behind one handler, and they need opposite
#      responses. If suspend_cards RAISES, the batch's undo entry is still on
#      top and the revert really happens. If suspend_cards SUCCEEDS and only
#      merge_undo_entries raises, anki's own entry sits above ours, the name
#      check in _revert_batch fails, and NOTHING is rolled back -- so a
#      '[batch_reverted]' response would be a lie that makes the caller's
#      retry duplicate the writes. Plus the same rule applied to the success
#      path: 'suspended' must be post-op state, not the ids we passed.
# ============================================================================
def _report_of(fn):
    """Run fn, return (errorCode, parsed JSON report) from the raised error."""
    try:
        fn()
    except Exception as err:
        text = str(err)
        code = text.split("] ", 1)[0].lstrip("[")
        return code, json.loads(text[text.index("{"):])
    raise AssertionError("expected an exception")


class _Boom(RuntimeError):
    pass


def test15_failure_paths_report_the_real_revert_outcome():
    col.decks.id("S15")
    orig_suspend = col.sched.suspend_cards
    orig_merge = col.merge_undo_entries

    # --- A: suspend_cards raises -> our entry is on top -> a REAL revert
    def blow_up(cids):
        raise _Boom("suspend exploded")

    before = note_count()
    col.sched.suspend_cards = blow_up
    try:
        code, report = _report_of(lambda: core.bulk_add_notes(
            col, [note("S15", "s15-a"), note("S15", "s15-b")], suspend=True))
    finally:
        col.sched.suspend_cards = orig_suspend
    assert code == "batch_reverted", (code, report)
    assert report["failedStep"] == "suspend" and report["addedBeforeRevert"] == 2, report
    assert note_count() == before, "the 'reverted' batch left notes behind"

    # --- B: suspend_cards SUCCEEDS, its merge raises -> NO revert is possible
    state = {"suspended": False}

    def flag_then_suspend(cids):
        out = orig_suspend(cids)
        state["suspended"] = True
        return out

    def merge_after_suspend_explodes(target):
        if state["suspended"]:
            raise _Boom("merge exploded")
        return orig_merge(target)

    col.sched.suspend_cards = flag_then_suspend
    col.merge_undo_entries = merge_after_suspend_explodes
    try:
        code, report = _report_of(lambda: core.bulk_add_notes(
            col, [note("S15", "s15-c")], suspend=True))
    finally:
        col.sched.suspend_cards = orig_suspend
        col.merge_undo_entries = orig_merge
        state["suspended"] = False
    assert code == "internal", (code, report)
    assert report["reverted"] is False and report["addedStillCommitted"] == 1, report
    # ...and the claim is checked against the collection, not taken on trust
    assert note_count() == before + 1, "reported NOT reverted but nothing survived"
    survivor = report["addedIds"][0]
    assert queues(col.card_ids_of_note(survivor)) == [core.QUEUE_SUSPENDED]
    col.remove_notes([survivor])
    assert note_count() == before

    # --- C: bulkSetDueDate, same two shapes
    cids = _fresh_cards("S15", 1, "s15-due")
    core.bulk_suspend(col, cids)
    pre = card_rows()

    col.sched.suspend_cards = blow_up
    try:
        code, msg = None, None
        try:
            core.bulk_set_due_date(col, cids, "9")
        except Exception as err:
            code, msg = str(err).split("] ", 1)[0].lstrip("["), str(err)
    finally:
        col.sched.suspend_cards = orig_suspend
    assert code == "batch_reverted", msg
    assert card_rows() == pre, "the 'reverted' reschedule was not actually undone"

    col.sched.suspend_cards = flag_then_suspend
    col.merge_undo_entries = merge_after_suspend_explodes
    try:
        code, report = _report_of(lambda: core.bulk_set_due_date(col, cids, "9"))
    finally:
        col.sched.suspend_cards = orig_suspend
        col.merge_undo_entries = orig_merge
        state["suspended"] = False
    assert code == "internal", (code, report)
    assert report["reverted"] is False and report["failedStep"] == "resuspend", report
    # the re-suspension itself SUCCEEDED here, so the honest post-op read is
    # 'nothing left unsuspended' -- the report is re-read, not assumed
    assert report["stillUnsuspended"] == [], report
    assert queues(cids) == [core.QUEUE_SUSPENDED]
    assert card_rows() != pre, "reported NOT reverted but the rows are pre-call"

    # --- D: the backend disagreeing with the precheck cannot be over-reported
    class _NoOpChanges(object):
        count = 0

    col.sched.suspend_cards = lambda cids: _NoOpChanges()
    try:
        r = core.bulk_add_notes(col, [note("S15", "s15-d")])
    finally:
        col.sched.suspend_cards = orig_suspend
    assert len(r["added"]) == 1, r
    # suspend_cards claimed 0 changes and changed nothing: 'suspended' reports
    # the post-op truth ([]), never the ids handed to the op
    assert r["suspended"] == [], r
    assert queues(col.card_ids_of_note(r["added"][0])) == [0]
    col.remove_notes(r["added"])


# ============================================================================
# 16 — the version fields move with the contract (revision-15 fix pass)
#
#      plusInfo is the one response a client caches. Revision 15 changed what
#      two actions DO by default, so a frozen version string would leave that
#      client no machine-readable signal at all.
# ============================================================================
def test16_version_and_spec_revision_track_the_spec():
    header = open(os.path.join(REPO, "SPEC.md"), encoding="utf-8").read(4000)
    line = next(ln for ln in header.splitlines() if ln.startswith("Version: "))
    version = line.split("Version: ", 1)[1].split(" ", 1)[0]
    revision = int(line.split("spec revision ", 1)[1].split(",", 1)[0])

    assert core.PLUS_VERSION == version, (core.PLUS_VERSION, version)
    assert core.PLUS_SPEC_REVISION == revision, (core.PLUS_SPEC_REVISION, revision)
    assert revision >= 15, "suspension control is revision 15 and up"
    assert core.PLUS_VERSION != "1.0.0", \
        "default behavior changed in revision 15; the version must move with it"

    plus = _load_plus()
    util_mod = sys.modules["ancp_susp_pkg.util"]
    orig = util_mod.setting
    try:
        util_mod.setting = lambda key: util_mod.DEFAULT_CONFIG[key]
        info = plus.PlusMixin().plusInfo()
    finally:
        util_mod.setting = orig
    assert info["version"] == core.PLUS_VERSION, info["version"]
    assert info["specRevision"] == core.PLUS_SPEC_REVISION, info["specRevision"]


# ================================================================ run
run("test1_add_suspends_by_default", test1_add_suspends_by_default)
run("test2_add_suspends_every_card_of_a_multi_card_note",
    test2_add_suspends_every_card_of_a_multi_card_note)
run("test3_add_suspend_false_is_stock_anki", test3_add_suspend_false_is_stock_anki)
run("test4_add_suspend_is_type_checked_before_any_write",
    test4_add_suspend_is_type_checked_before_any_write)
run("test5_add_reports_the_decision_on_every_return_path",
    test5_add_reports_the_decision_on_every_return_path)
run("test6_add_suspend_respects_undo_label", test6_add_suspend_respects_undo_label)
run("test7_due_date_preserves_suspension_by_default",
    test7_due_date_preserves_suspension_by_default)
run("test8_due_date_preserve_off_is_stock_anki", test8_due_date_preserve_off_is_stock_anki)
run("test9_buried_cards_are_not_re_buried", test9_buried_cards_are_not_re_buried)
run("test10_due_date_dry_run_predicts_and_writes_nothing",
    test10_due_date_dry_run_predicts_and_writes_nothing)
run("test11_due_date_param_errors_leave_the_stack_untouched",
    test11_due_date_param_errors_leave_the_stack_untouched)
run("test12_config_defaults_are_in_lockstep", test12_config_defaults_are_in_lockstep)
run("test15_failure_paths_report_the_real_revert_outcome",
    test15_failure_paths_report_the_real_revert_outcome)
# the wrapper tests import plus.py -> aqt; keep them last so the purity
# assertion at the top of this file stays meaningful for the core-path tests
run("test13_wrapper_resolves_param_over_config_over_default",
    test13_wrapper_resolves_param_over_config_over_default)
run("test14_wrapper_end_to_end_and_discoverability",
    test14_wrapper_end_to_end_and_discoverability)
run("test16_version_and_spec_revision_track_the_spec",
    test16_version_and_spec_revision_track_the_spec)

print("\n===== SUMMARY =====")
failed = [name for name, ok, _ in RESULTS if not ok]
for name, ok, _ in RESULTS:
    print("%s  %s" % ("PASS" if ok else "FAIL", name))
print("%d/%d passed" % (len(RESULTS) - len(failed), len(RESULTS)))

col.close()
if not os.environ.get("ANCP_TEST_KEEP"):
    shutil.rmtree(SCRATCH, ignore_errors=True)
sys.exit(1 if failed else 0)
