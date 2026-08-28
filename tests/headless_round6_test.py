# Headless verification for SPEC 32 — filtered-deck build (spec revision 19):
#
#   * createFilteredDeck  (32.1) — create AND build a cram deck from a search
#                                  as one undoable op; GUI-template defaults;
#                                  coded refusals where the backend silently
#                                  surprises; dry-run sizing with honest
#                                  exact/bounds semantics
#   * rebuildFilteredDeck (32.2) — empty-then-regather by the deck's SAVED
#                                  terms; both halves reported honestly;
#                                  rebuild-to-zero legal; full no-op gated
#
# Run with: <anki-venv>/bin/python headless_round6_test.py
#
# Uses a FRESH scratch collection; never touches ~/Library/Application Support/Anki2/.

import importlib
import importlib.util
import os
import shutil
import sys
import tempfile
import traceback
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = (os.environ.get("ANCP_R6_SCRATCH")
           or tempfile.mkdtemp(prefix="ancp_r6_"))
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
from anki.collection import Collection
from anki.decks import DeckId

col = Collection(os.path.join(SCRATCH, "r6.anki2"))

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


def mkfilter_raw(name, terms):
    """Create a filtered deck through the raw backend (fixture builder for
    externally-written decks: 3 terms, etc.). terms = [(search, limit, order)]."""
    fd = col.sched.get_or_create_filtered_deck(DeckId(0))
    fd.name = name
    del fd.config.search_terms[:]
    for search, limit, order in terms:
        term = fd.config.search_terms.add()
        term.search = search
        term.limit = limit
        term.order = order
    return int(col.sched.add_or_update_filtered_deck(fd).id)


def undo_snap():
    # the BACKEND status (undo/redo strings + monotonic last_step) — the
    # strict form of the bit-identical claim (SPEC 26)
    return col._backend.get_undo_status().SerializeToString()


def cards_in(did):
    return set(col.db.list("select id from cards where did = ?", did))


def code_of(fn):
    try:
        fn()
    except Exception as err:
        msg = str(err)
        assert msg.startswith("["), "unprefixed error: %r" % msg
        return msg.split("] ", 1)[0].lstrip("[")
    raise AssertionError("expected an exception")


def deck_names():
    return {d.name for d in col.decks.all_names_and_ids(include_filtered=True)}


# ============================================================================
# 1 — create: dry -> real parity (single term, exact), gather exclusions
#     live, undo round trip, response shape
# ============================================================================
def test1_create_dry_real_parity_and_exclusions():
    ns = [add_note("Home", "g%d" % i, ["gath"]) for i in range(6)]
    cids = [n.card_ids()[0] for n in ns]
    col.sched.suspend_cards([cids[5]])
    col.sched.bury_cards([cids[4]])
    # cids[3] captured by another filter first (its own unique tag)
    ns[3].tags = ["gath", "cap"]
    col.update_note(ns[3])
    capture_id = mkfilter_raw("Capture", [("tag:cap", 100, 0)])
    assert cards_in(capture_id) == {cids[3]}

    snap = undo_snap()
    dry = core.create_filtered_deck(col, "PI9 cram", "tag:gath", dry_run=True)
    assert undo_snap() == snap, "dry run wrote to the undo stack"
    assert dry == {"wouldCreate": True, "wouldGather": 3, "exact": True,
                   "wouldGatherMin": 3, "wouldGatherMax": 3,
                   "name": "PI9 cram",
                   "terms": [{"search": "tag:gath", "limit": 100,
                              "order": "random", "eligible": 3}],
                   "undoEntry": None}, dry
    assert "PI9 cram" not in deck_names(), "dry run created the deck"

    names_before = deck_names()
    real = core.create_filtered_deck(col, "PI9 cram", "tag:gath")
    assert real["cardsGathered"] == dry["wouldGather"] == 3, real
    assert real["name"] == "PI9 cram"
    assert real["terms"] == dry["terms"]
    assert real["undoEntry"] == "Agent Connect: Create Filtered Deck"
    did = real["deckId"]
    assert col.decks.is_filtered(did)
    # the exclusions were honored: suspended/buried/other-filter never gathered
    gathered = cards_in(did)
    assert gathered == {cids[0], cids[1], cids[2]}, gathered
    # cards MOVED: did = filter, odid = home
    home_id = col.decks.id_for_name("Home")
    for cid in gathered:
        row = col.db.first("select did, odid from cards where id = ?", cid)
        assert row == [did, home_id], row
    # entry on top; ONE undo deletes the deck AND returns the cards
    assert col.undo_status().undo == "Agent Connect: Create Filtered Deck"
    col.undo()
    assert deck_names() == names_before
    for cid in gathered:
        row = col.db.first("select did, odid from cards where id = ?", cid)
        assert row == [home_id, 0], row
    # cleanup for later tests
    col.sched.unsuspend_cards([cids[5]])


# ============================================================================
# 2 — create: limit binds; order vocabulary accepted/refused
# ============================================================================
def test2_create_limit_and_order():
    [add_note("Home", "lim%d" % i, ["lim"]) for i in range(5)]
    real = core.create_filtered_deck(col, "LimCram", "tag:lim", limit=2,
                                     order="due")
    assert real["cardsGathered"] == 2, real
    assert real["terms"][0]["eligible"] == 5
    assert real["terms"][0]["order"] == "due"
    assert code_of(lambda: core.create_filtered_deck(
        col, "OrderBad", "tag:lim", order="Random")) == "invalid_param"
    assert code_of(lambda: core.create_filtered_deck(
        col, "OrderBad", "tag:lim", order=1)) == "invalid_param"
    for bad_limit in (0, -3, 2 ** 32, True):
        assert code_of(lambda b=bad_limit: core.create_filtered_deck(
            col, "LimBad", "tag:lim", limit=b)) == "invalid_param"


# ============================================================================
# 3 — create: every refusal fires BEFORE anything exists
# ============================================================================
def test3_create_refusals():
    add_note("Home", "ref1", ["ref"])
    # taken name — exact and case-variant (the backend would build 'home+')
    assert code_of(lambda: core.create_filtered_deck(
        col, "Home", "tag:ref")) == "duplicate"
    assert code_of(lambda: core.create_filtered_deck(
        col, "home", "tag:ref")) == "duplicate"
    # un-normalized name
    for bad in ("", " Padded", "A:: ::B", "A::"):
        assert code_of(lambda b=bad: core.create_filtered_deck(
            col, b, "tag:ref")) == "invalid_param", bad
    # empty / whitespace / unparseable search
    assert code_of(lambda: core.create_filtered_deck(
        col, "S1", "")) == "invalid_param"
    assert code_of(lambda: core.create_filtered_deck(
        col, "S1", "   ")) == "invalid_param"
    assert code_of(lambda: core.create_filtered_deck(
        col, "S1", "tag:(")) == "invalid_param"
    # flag types
    assert code_of(lambda: core.create_filtered_deck(
        col, "S1", "tag:ref", dry_run="yes")) == "invalid_param"
    assert code_of(lambda: core.create_filtered_deck(
        col, "S1", "tag:ref", reschedule="yes")) == "invalid_param"
    # secondFilter shape
    assert code_of(lambda: core.create_filtered_deck(
        col, "S1", "tag:ref",
        second_filter=["tag:x"])) == "invalid_param"
    assert code_of(lambda: core.create_filtered_deck(
        col, "S1", "tag:ref",
        second_filter={"searchQuery": "tag:x",
                       "orderr": "due"})) == "invalid_param"
    assert code_of(lambda: core.create_filtered_deck(
        col, "S1", "tag:ref",
        second_filter={"limit": 5})) == "invalid_param"
    # zero gatherable cards: real refuses with NOTHING created, dry reports
    names = deck_names()
    snap = undo_snap()
    assert code_of(lambda: core.create_filtered_deck(
        col, "Zero", "tag:matches_nothing")) == "validation_error"
    assert deck_names() == names and undo_snap() == snap
    dry = core.create_filtered_deck(col, "Zero", "tag:matches_nothing",
                                    dry_run=True)
    assert dry["wouldCreate"] is False and dry["wouldGather"] == 0 \
        and dry["exact"] is True, dry
    # filtered parent (LimCram is a filter from test2): prechecked, coded,
    # nothing created, undo untouched
    snap = undo_snap()
    assert code_of(lambda: core.create_filtered_deck(
        col, "LimCram::Sub", "tag:ref")) == "validation_error"
    assert deck_names() == names and undo_snap() == snap
    # bad undoLabel raises before any write
    assert code_of(lambda: core.create_filtered_deck(
        col, "S1", "tag:ref", undo_label="   ")) == "invalid_param"


# ============================================================================
# 4 — create: two-term semantics — disjoint exact; overlap under a binding
#     limit -> exact: false with the real count inside the bounds
# ============================================================================
def test4_create_second_filter_bounds():
    [add_note("Home", "dA%d" % i, ["dja"]) for i in range(3)]
    [add_note("Home", "dB%d" % i, ["djb"]) for i in range(2)]
    dry = core.create_filtered_deck(
        col, "Disjoint", "tag:dja",
        second_filter={"searchQuery": "tag:djb", "limit": 10, "order": "due"},
        dry_run=True)
    assert dry["exact"] is True and dry["wouldGather"] == 5, dry
    real = core.create_filtered_deck(
        col, "Disjoint", "tag:dja",
        second_filter={"searchQuery": "tag:djb", "limit": 10, "order": "due"})
    assert real["cardsGathered"] == 5, real
    # secondFilter defaults mirror the GUI template: 20/'due'
    assert real["terms"][1]["limit"] == 10
    dflt = core.create_filtered_deck(
        col, "DfltCheck", "tag:dja",
        second_filter={"searchQuery": "tag:djb"}, dry_run=True)
    assert dflt["terms"][1]["limit"] == 20
    assert dflt["terms"][1]["order"] == "due"
    assert dflt["terms"][0]["order"] == "random"

    # overlap + binding first limit: e1=6, overlap=3, e2=5, limit1=4 ->
    # x in [1,3], g2 in [2,4], total in [6,8] — genuinely order-dependent
    ov_a = [add_note("Home", "ovA%d" % i, ["ova"]) for i in range(6)]
    for n in ov_a[:3]:
        n.tags = ["ova", "ovb"]
        col.update_note(n)
    [add_note("Home", "ovB%d" % i, ["ovb"]) for i in range(2)]
    dry = core.create_filtered_deck(
        col, "Overlap", "tag:ova", limit=4,
        second_filter={"searchQuery": "tag:ovb", "limit": 10}, dry_run=True)
    assert dry["exact"] is False, dry
    assert dry["wouldGatherMin"] == 6 and dry["wouldGatherMax"] == 8, dry
    assert dry["wouldGather"] == dry["wouldGatherMax"] == 8
    real = core.create_filtered_deck(
        col, "Overlap", "tag:ova", limit=4,
        second_filter={"searchQuery": "tag:ovb", "limit": 10})
    assert dry["wouldGatherMin"] <= real["cardsGathered"] <= \
        dry["wouldGatherMax"], real


# ============================================================================
# 5 — create: reschedule + normalized terms round-trip in the SAVED config;
#     missing parents created as regular decks, one undo removes everything
# ============================================================================
def test5_create_saved_config_and_parents():
    [add_note("Home", "rt%d" % i, ["rt"]) for i in range(2)]
    real = core.create_filtered_deck(
        col, "RTCheck", "tag:rt OR tag:never", reschedule=False)
    saved = col.sched.get_or_create_filtered_deck(DeckId(real["deckId"]))
    assert saved.config.reschedule is False
    # saved search is the parser's canonical spelling == the response echo
    assert list(saved.config.search_terms)[0].search == \
        real["terms"][0]["search"] == "tag:rt OR tag:never"

    [add_note("Home", "par%d" % i, ["par"]) for i in range(2)]
    names_before = deck_names()
    real2 = core.create_filtered_deck(col, "NewParent::Cram", "tag:par",
                                      undo_label="parents probe")
    assert real2["undoEntry"] == "Agent Connect: parents probe"
    parent_id = col.decks.id_for_name("NewParent")
    assert parent_id is not None and not col.decks.is_filtered(parent_id)
    col.undo()
    assert deck_names() == names_before, "undo left parent decks behind"


# ============================================================================
# 6 — current-deck side effect: create SELECTS the built deck (GUI parity),
#     rebuild PRESERVES the selection
# ============================================================================
def test6_current_deck():
    [add_note("Home", "cur%d" % i, ["cur"]) for i in range(2)]
    home_id = col.decks.id_for_name("Home")
    col.decks.set_current(DeckId(home_id))
    real = core.create_filtered_deck(col, "CurCram", "tag:cur")
    assert col.decks.get_current_id() == real["deckId"], \
        "create did not select the built deck"
    col.decks.set_current(DeckId(home_id))
    core.rebuild_filtered_deck(col, deck_id=real["deckId"])
    assert col.decks.get_current_id() == home_id, \
        "rebuild changed the current deck"


# ============================================================================
# 7 — rebuild: honest halves by name and id, dry parity, single undo
#     restores the previous membership
# ============================================================================
def test7_rebuild_honest_halves():
    ns = [add_note("Home", "rb%d" % i, ["rb"]) for i in range(5)]
    real = core.create_filtered_deck(col, "RBCram", "tag:rb")
    did = real["deckId"]
    assert real["cardsGathered"] == 5
    before_membership = cards_in(did)
    # shrink the matching set: one card will go home and stay
    ns[0].tags = []
    col.update_note(ns[0])

    snap = undo_snap()
    dry = core.rebuild_filtered_deck(col, deck_name="RBCram", dry_run=True)
    assert undo_snap() == snap, "dry rebuild wrote to the undo stack"
    assert dry["wouldReturn"] == 5 and dry["wouldGather"] == 4 \
        and dry["exact"] is True, dry
    assert dry["termsIgnored"] == 0
    # the deck's own cards count as re-gatherable
    assert dry["terms"][0]["eligible"] == 4

    rb = core.rebuild_filtered_deck(col, deck_name="RBCram",
                                    undo_label="rb probe")
    assert rb == {"cardsGathered": 4, "returnedFirst": 5,
                  "undoEntry": "Agent Connect: rb probe"}, rb
    assert len(cards_in(did)) == 4
    col.undo()
    assert cards_in(did) == before_membership, \
        "single undo did not restore the previous membership"
    # by-id path
    rb2 = core.rebuild_filtered_deck(col, deck_id=did)
    assert rb2["returnedFirst"] == 5 and rb2["cardsGathered"] == 4, rb2


# ============================================================================
# 8 — rebuild-to-zero legal; the full data no-op is gated (nothing written)
# ============================================================================
def test8_rebuild_to_zero_and_noop_gate():
    ns = [add_note("Home", "z%d" % i, ["zz"]) for i in range(2)]
    real = core.create_filtered_deck(col, "ZCram", "tag:zz")
    did = real["deckId"]
    for n in ns:
        n.tags = []
        col.update_note(n)
    rb = core.rebuild_filtered_deck(col, deck_id=did)
    assert rb["returnedFirst"] == 2 and rb["cardsGathered"] == 0, rb
    assert rb["undoEntry"] == "Agent Connect: Rebuild Filtered Deck"
    assert cards_in(did) == set()
    # now empty + saved terms gather 0: the gated no-op
    snap = undo_snap()
    noop = core.rebuild_filtered_deck(col, deck_id=did)
    assert noop == {"cardsGathered": 0, "returnedFirst": 0,
                    "undoEntry": None}, noop
    assert undo_snap() == snap, "no-op rebuild wrote to the undo stack"


# ============================================================================
# 9 — rebuild: selector errors verbatim from §29.2; a 3-term externally-
#     saved deck (termsIgnored); a saved term that no longer parses
# ============================================================================
def test9_rebuild_errors_and_saved_term_edges():
    assert code_of(lambda: core.rebuild_filtered_deck(col)) == "invalid_param"
    assert code_of(lambda: core.rebuild_filtered_deck(
        col, deck_name="X", deck_id=3)) == "invalid_param"
    assert code_of(lambda: core.rebuild_filtered_deck(
        col, deck_name="")) == "invalid_param"
    assert code_of(lambda: core.rebuild_filtered_deck(
        col, deck_id=True)) == "invalid_param"
    assert code_of(lambda: core.rebuild_filtered_deck(
        col, deck_name="NoSuchDeck")) == "deck_not_found"
    assert code_of(lambda: core.rebuild_filtered_deck(
        col, deck_id=99999999)) == "deck_not_found"
    assert code_of(lambda: core.rebuild_filtered_deck(
        col, deck_name="Home")) == "validation_error"
    assert code_of(lambda: core.rebuild_filtered_deck(
        col, deck_name="Home", dry_run="yes")) == "invalid_param"

    # 3 saved terms: anki gathers only the first two; the third is disclosed
    [add_note("Home", "t3a%d" % i, ["t3a"]) for i in range(2)]
    [add_note("Home", "t3b%d" % i, ["t3b"]) for i in range(2)]
    [add_note("Home", "t3c%d" % i, ["t3c"]) for i in range(2)]
    did3 = mkfilter_raw("ThreeTerms", [("tag:t3a", 5, 0), ("tag:t3b", 5, 0),
                                       ("tag:t3c", 5, 0)])
    dry = core.rebuild_filtered_deck(col, deck_id=did3, dry_run=True)
    assert dry["termsIgnored"] == 1 and len(dry["terms"]) == 2, dry
    assert dry["wouldGather"] == 4, dry  # t3c never gathered
    rb = core.rebuild_filtered_deck(col, deck_id=did3)
    assert rb["cardsGathered"] == 4, rb

    # a saved term that no longer parses (external writer): coded refusal on
    # both paths, before any undo entry — simulated by patching the saved-
    # config read, since anki itself refuses to SAVE an unparseable term
    from anki import decks_pb2
    broken = decks_pb2.FilteredDeckForUpdate()
    broken.id = did3
    broken.name = "ThreeTerms"
    term = broken.config.search_terms.add()
    term.search = "tag:("
    term.limit = 5
    term.order = 0
    original = col.sched.get_or_create_filtered_deck
    col.sched.get_or_create_filtered_deck = lambda deck_id: broken
    try:
        snap = undo_snap()
        assert code_of(lambda: core.rebuild_filtered_deck(
            col, deck_id=did3)) == "validation_error"
        assert code_of(lambda: core.rebuild_filtered_deck(
            col, deck_id=did3, dry_run=True)) == "validation_error"
        assert undo_snap() == snap
    finally:
        col.sched.get_or_create_filtered_deck = original


# ============================================================================
# 9b — regression (revision-19 fix pass): a filtered deck literally named
#      lowercase 'filtered'. The writer emits deck:filtered unquoted for that
#      name and anki's parser reads it as the in-any-filtered-deck KEYWORD
#      (case-sensitive; quoting does not escape it), so a NAME-based own-deck
#      disjunct made the residency exclusion a tautology: cards held by OTHER
#      filters counted as re-gatherable, the dry bounds missed the real count
#      (SPEC 32.2's promise), and the full-no-op gate was bypassed into a
#      phantom do-nothing undo entry (the SPEC 16.2 hazard). The pool now
#      composes the own-deck disjunct from the deck ID (did:<id>).
# ============================================================================
def test9b_rebuild_deck_named_filtered():
    n_own = add_note("Home", "kw own", ["kwown"])
    add_note("Home", "kw other", ["kwother"])
    other_did = mkfilter_raw("KWOther", [("tag:kwother", 100, 0)])
    # the deck under test, literally named 'filtered'; its saved term matches
    # BOTH tags, but the kwother card sits in KWOther and must never count
    did = mkfilter_raw("filtered", [("tag:kwown or tag:kwother", 100, 0)])
    assert col.decks.name(did) == "filtered"
    assert len(cards_in(did)) == 1 and len(cards_in(other_did)) == 1

    # phase 1 — deck holds its own card: re-gatherable, the OTHER filter's
    # card excluded (pre-fix: eligible 2 / wouldGather 2, real gathers 1)
    dry = core.rebuild_filtered_deck(col, deck_id=did, dry_run=True)
    assert dry["wouldReturn"] == 1 and dry["wouldGather"] == 1 \
        and dry["exact"] is True and dry["wouldGatherMin"] == 1 \
        and dry["wouldGatherMax"] == 1, dry
    assert dry["terms"][0]["eligible"] == 1, dry
    rb = core.rebuild_filtered_deck(col, deck_id=did)
    assert rb == {"cardsGathered": 1, "returnedFirst": 1,
                  "undoEntry": "Agent Connect: Rebuild Filtered Deck"}, rb

    # phase 2 — own card stops matching: rebuild-to-zero, dry bounds hold
    # (pre-fix: wouldGather 1 via the tautology, real gathers 0)
    n_own.tags = []
    col.update_note(n_own)
    dry_z = core.rebuild_filtered_deck(col, deck_id=did, dry_run=True)
    assert dry_z["wouldReturn"] == 1 and dry_z["wouldGather"] == 0 \
        and dry_z["exact"] is True, dry_z
    rb0 = core.rebuild_filtered_deck(col, deck_id=did)
    assert rb0["returnedFirst"] == 1 and rb0["cardsGathered"] == 0, rb0
    assert cards_in(did) == set()

    # phase 3 — EMPTY deck, saved term matching only the other filter's card:
    # the full-no-op gate fires, nothing written (pre-fix: dry wouldGather 1,
    # and the real run wrote a do-nothing 'Rebuild Filtered Deck' undo step)
    snap = undo_snap()
    dry0 = core.rebuild_filtered_deck(col, deck_id=did, dry_run=True)
    assert dry0["wouldReturn"] == 0 and dry0["wouldGather"] == 0 \
        and dry0["exact"] is True, dry0
    assert dry0["terms"][0]["eligible"] == 0, dry0
    noop = core.rebuild_filtered_deck(col, deck_id=did)
    assert noop == {"cardsGathered": 0, "returnedFirst": 0,
                    "undoEntry": None}, noop
    assert undo_snap() == snap, "no-op rebuild wrote to the undo stack"
    # the other filter's membership never moved
    assert len(cards_in(other_did)) == 1


# ============================================================================
# 10 — lockstep surface: registries, undo consts, prefix note, recipe,
#      wrapper signatures through live plusInfo, README/SPEC/SKILL artifacts
# ============================================================================
def _load_plus():
    pkg_name = "ancp_r6_pkg"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [os.path.join(REPO, "connect_plus")]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg
    return importlib.import_module(pkg_name + ".plus")


def test10_lockstep_and_wrappers():
    for name in ("createFilteredDeck", "rebuildFilteredDeck"):
        assert name in core.PLUS_ACTIONS, name
        assert core.PLUS_ACTION_SUMMARIES[name].strip(), name
        assert core.PLUS_ACTION_RETURNS[name].startswith("{"), name
        assert core.PLUS_ACTION_PRESERVES[name].strip(), name
    # 36 -> 37: revision-20 SPEC 33 adds ankihubStageOptionalTagSuggestion
    assert len(core.PLUS_ACTIONS) == 37, len(core.PLUS_ACTIONS)
    assert core.PLUS_ACTIONS[-1] == "plusInfo"
    assert core.UNDO_CREATE_FILTERED == "Agent Connect: Create Filtered Deck"
    assert core.UNDO_REBUILD_FILTERED == "Agent Connect: Rebuild Filtered Deck"
    assert "37 Plus actions" in core.PLUS_ERROR_PREFIX_NOTE
    assert core.PLUS_VERSION == "1.5.0" and core.PLUS_SPEC_REVISION == 20
    # order vocabulary is the probe-pinned label list, index == enum
    assert core.FILTERED_DECK_ORDERS == {
        "oldestReviewedFirst": 0, "random": 1, "intervalsAscending": 2,
        "intervalsDescending": 3, "lapses": 4, "added": 5, "due": 6,
        "reverseAdded": 7, "retrievabilityAscending": 8,
        "retrievabilityDescending": 9}
    labels = col.sched.filtered_deck_order_labels()
    assert len(labels) == 10, labels
    # the lifecycle recipe names both new actions and keeps the export story
    safe = next(r for r in core.PLUS_RECIPES if r["name"] == "safe deck export")
    for token in ("createFilteredDeck", "rebuildFilteredDeck",
                  "filteredDeckReport", "emptyFilteredDeck",
                  "allowFilteredOmission", "cards_in_filtered_decks"):
        assert token in safe["description"], token
    # error-code docs name the new reachable sites
    assert "createFilteredDeck" in \
        core.PLUS_ERROR_CODE_DOCS["duplicate"]["meaning"]
    assert "rebuildFilteredDeck" in \
        core.PLUS_ERROR_CODE_DOCS["validation_error"]["meaning"]

    plus = _load_plus()
    util_mod = sys.modules["ancp_r6_pkg.util"]
    orig = util_mod.setting
    try:
        util_mod.setting = lambda key: util_mod.DEFAULT_CONFIG[key]
        info = plus.PlusMixin().plusInfo()
    finally:
        util_mod.setting = orig
    docs = info["actionDocs"]
    assert docs["createFilteredDeck"]["params"] == \
        ("name, searchQuery, limit=100, order=null, secondFilter=null, "
         "reschedule=true, dryRun=false, undoLabel=null"), \
        docs["createFilteredDeck"]
    assert docs["rebuildFilteredDeck"]["params"] == \
        "deckName=null, deckId=null, dryRun=false, undoLabel=null", \
        docs["rebuildFilteredDeck"]
    assert docs["createFilteredDeck"]["preserves"] == \
        core.PLUS_ACTION_PRESERVES["createFilteredDeck"]

    # end-to-end coded envelope through the wrapper layer
    class Bridge(plus.PlusMixin):
        def collection(self):
            return col
    bridge = Bridge()
    try:
        bridge.createFilteredDeck("Home", "tag:whatever")
        raise AssertionError("expected [duplicate]")
    except Exception as err:
        assert str(err).startswith("[duplicate] "), str(err)

    # README and SPEC artifacts
    with open(os.path.join(REPO, "README.md"), encoding="utf-8") as fh:
        readme = fh.read()
    for name in ("createFilteredDeck", "rebuildFilteredDeck"):
        assert "`%s`" % name in readme, name
    assert "**37 new actions**" in readme
    with open(os.path.join(REPO, "SPEC.md"), encoding="utf-8") as fh:
        spec_text = fh.read()
    assert "Version: 1.5.0 (spec revision 20" in spec_text[:4000]
    assert "## 32. Filtered-deck build" in spec_text
    with open(os.path.join(REPO, "skills", "anki-bulk-cards", "SKILL.md"),
              encoding="utf-8") as fh:
        skill_text = fh.read()
    assert "37 Plus actions" in skill_text, \
        "SKILL.md action count drifted from the code"
    assert "36 Plus actions" not in skill_text


run("1 create: dry/real parity, exclusions, undo round trip",
    test1_create_dry_real_parity_and_exclusions)
run("2 create: limit binds, order vocabulary", test2_create_limit_and_order)
run("3 create: refusals fire before anything exists", test3_create_refusals)
run("4 create: second-filter exact/bounds semantics",
    test4_create_second_filter_bounds)
run("5 create: saved config round-trip, missing parents",
    test5_create_saved_config_and_parents)
run("6 current-deck: create selects, rebuild preserves", test6_current_deck)
run("7 rebuild: honest halves, dry parity, undo restores",
    test7_rebuild_honest_halves)
run("8 rebuild-to-zero + gated no-op", test8_rebuild_to_zero_and_noop_gate)
run("9 rebuild: selector errors, 3-term deck, broken saved term",
    test9_rebuild_errors_and_saved_term_edges)
run("9b rebuild: deck literally named 'filtered' (keyword collision)",
    test9b_rebuild_deck_named_filtered)
run("10 lockstep: registries, wrappers, README/SPEC", test10_lockstep_and_wrappers)

col.close()
print()
failures = [r for r in RESULTS if not r[1]]
print("%d/%d passed" % (len(RESULTS) - len(failures), len(RESULTS)))
sys.exit(1 if failures else 0)
