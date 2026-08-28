# INDEPENDENT round-1 verification of SPEC 32 (spec revision 19, v1.4.0):
# createFilteredDeck / rebuildFilteredDeck, driven through the REAL PlusMixin
# wrappers (the wire surface minus HTTP), against a fresh scratch collection.
#
# Written by the verifier, not the implementer: fixtures and expectations are
# built from SPEC 32's own text and from anki's probe-pinned behavior, so
# agreement here is corroboration rather than an echo of the implementation's
# suite (tests/headless_round6_test.py).
#
#   1. createFilteredDeck happy path on a 20-card seed: 6 tag matches
#      gathered, the suspended match NOT gathered, gathered cards' did ==
#      the new deck / odid == home, non-gathered rows byte-identical,
#      response shape and the create-selects side effect; single undo
#      deletes the deck AND returns every card (SPEC's one-entry claim).
#   2. limit=3 caps the gather; order honored BEHAVIORALLY (added vs
#      reverseAdded pick opposite ends of the pool under a binding limit)
#      and in the deck's saved config; two disjoint terms sum exactly.
#   3. dryRun: wouldGather == what the real call then gathers, NO deck
#      created, card table untouched, undo proto byte-identical.
#   4. Zero matches -> real run [validation_error] with nothing created
#      (dry run reports wouldCreate: false instead of raising — SPEC 32.1);
#      all-suspended pool refused the same way; bad search syntax ->
#      [invalid_param]; taken name (regular deck, case variant, existing
#      filter) -> [duplicate]; bad order -> [invalid_param] naming every
#      valid value; plus the documented limit/name/secondFilter refusals.
#   5. rebuildFilteredDeck: counts honest (returnedFirst pre-op,
#      cardsGathered post-op) after adding matches; regathered dids
#      correct; deckId variant; suspended-inside goes home STILL suspended
#      and is not re-gathered; rebuild preserves the current-deck
#      selection; regular-deck/missing/selector refusals; rebuild-to-zero
#      legal; the full data no-op gated with the undo proto byte-identical.
#   6. Lifecycle: create -> filteredDeckReport sees it -> exportDeckApkg on
#      the home deck refuses [cards_in_filtered_decks] -> emptyFilteredDeck
#      returns the cards -> export succeeds. One test, the full loop.
#   7. Lockstep: PLUS_VERSION 1.5.0, PLUS_SPEC_REVISION 20, 37 actions,
#      SPEC.md header agrees, both new actions' served returns docs name
#      every top-level key of every REAL captured response shape (real,
#      dry, no-op), and the served preserves lines are the ones tests 1/5
#      verified empirically.
#
# Run with: <anki-venv>/bin/python headless_filtercreate_test.py
#
# Scratch collection under the session scratchpad (ancp_fd_v1), overridable
# via ANCP_FD_SCRATCH, tempfile fallback if unwritable. NEVER touches
# ~/Library/Application Support/Anki2/. A process-wide socket deny-guard
# makes any network attempt an immediate failure.

import importlib
import importlib.util
import os
import shutil
import socket
import sys
import tempfile
import traceback
import types

# ---------------------------------------------------------------------------
# socket deny-guard: installed BEFORE anki/aqt are importable, so nothing in
# this suite can open a network connection, resolve a name, or listen.
# ---------------------------------------------------------------------------


def _deny(name):
    def guard(*args, **kwargs):
        raise AssertionError("network denied in headless filtercreate test: %s" % name)
    return guard


socket.socket.connect = _deny("socket.connect")
socket.socket.connect_ex = _deny("socket.connect_ex")
socket.socket.bind = _deny("socket.bind")
socket.create_connection = _deny("socket.create_connection")
socket.getaddrinfo = _deny("socket.getaddrinfo")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_PATH = os.path.join(REPO, "connect_plus", "core.py")
_DEFAULT_SCRATCH = os.path.join(tempfile.gettempdir(), "ancp_fd_v1")
SCRATCH = os.environ.get("ANCP_FD_SCRATCH") or _DEFAULT_SCRATCH

assert not SCRATCH.startswith(os.path.expanduser("~/Library")), \
    "scratch dir must never live under ~/Library"
assert "Anki2" not in SCRATCH, "scratch dir must never shadow a real Anki profile"

try:
    if os.path.exists(SCRATCH):
        shutil.rmtree(SCRATCH)
    os.makedirs(SCRATCH)
except OSError:
    # the session-pinned path is gone (reboot cleaned /private/tmp): fall
    # back to a fresh tempdir so the weekly health check stays runnable
    SCRATCH = tempfile.mkdtemp(prefix="ancp_fd_")

sys.dont_write_bytecode = True

# ---------------------------------------------------------------------------
# load core.py STANDALONE first and re-verify its aqt-free purity
# ---------------------------------------------------------------------------
_spec = importlib.util.spec_from_file_location("fd_core", CORE_PATH)
core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core)
assert "aqt" not in sys.modules, "core.py (or its imports) pulled in aqt"
assert not any(m.startswith("PyQt6") for m in sys.modules), \
    "core.py (or its imports) pulled in PyQt6"

import anki.lang
anki.lang.set_lang("en_US")
from anki.collection import Collection
from anki.decks import DeckId

col = Collection(os.path.join(SCRATCH, "fd.anki2"))

# ---------------------------------------------------------------------------
# the live PlusMixin surface, headless (the contract-test bridge pattern)
# ---------------------------------------------------------------------------
PKG = "ancp_fd_pkg"


def load_plus():
    if PKG not in sys.modules:
        pkg = types.ModuleType(PKG)
        pkg.__path__ = [os.path.join(REPO, "connect_plus")]
        pkg.__package__ = PKG
        sys.modules[PKG] = pkg
    return importlib.import_module(PKG + ".plus")


plus = load_plus()


class Bridge(plus.PlusMixin):
    def collection(self):
        return col


bridge = Bridge()


def stubbed_info():
    """plusInfo() with util.setting served from DEFAULT_CONFIG (headless)."""
    util_mod = sys.modules[PKG + ".util"]
    orig = util_mod.setting
    util_mod.setting = lambda key: util_mod.DEFAULT_CONFIG[key]
    try:
        return bridge.plusInfo()
    finally:
        util_mod.setting = orig


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


# ---------------------------------------------------------------------------
# fixtures + observers
# ---------------------------------------------------------------------------

def add_basic(deck, front, tags=()):
    n = col.new_note(col.models.by_name("Basic"))
    n["Front"] = front
    n["Back"] = "b"
    n.tags = list(tags)
    col.add_note(n, col.decks.id(deck))
    return n


def cid_of(note):
    return col.card_ids_of_note(note.id)[0]


# full persisted card state minus the bookkeeping columns (mod/usn move on
# any write by design and prove nothing about preservation)
STATE_COLS = ("id, nid, did, odid, ord, type, queue, due, ivl, factor, "
              "reps, lapses, left, odue, flags, data")


def rows_for(cids):
    if not cids:
        return []
    return col.db.all(
        "select {} from cards where id in ({}) order by id".format(
            STATE_COLS, ",".join(str(int(c)) for c in cids)))


def all_card_rows():
    return col.db.all("select {} from cards order by id".format(STATE_COLS))


def card_loc(cid):
    """(did, odid, queue) — the residency + suspension triple."""
    return col.db.first(
        "select did, odid, queue from cards where id = ?", cid)


def cards_in(did):
    return set(col.db.list("select id from cards where did = ?", did))


def undo_snap():
    # the BACKEND undo status proto, serialized — the strict reading of the
    # SPEC's "undo status byte-identical" dry-run claim
    return col._backend.get_undo_status().SerializeToString()


def deck_ids_snapshot():
    return {d.id for d in col.decks.all_names_and_ids(include_filtered=True)}


def plus_error(fn):
    """Run fn, demand a refusal, return (code, message-after-prefix)."""
    try:
        fn()
    except Exception as err:
        text = str(err)
        assert text.startswith("["), "unprefixed error: %r" % text
        code, _, message = text.partition("] ")
        return code.lstrip("["), message
    raise AssertionError("expected a refusal, call succeeded")


CREATE_LABEL = "Agent Connect: Create Filtered Deck"
REBUILD_LABEL = "Agent Connect: Rebuild Filtered Deck"

# real captured responses, locked against the served returns docs in test 7
CAPTURED = {}
FD1 = {}
FD7 = {}


# ===========================================================================
# 1 — createFilteredDeck happy path on a 20-card seed + single-undo round trip
# ===========================================================================
def test1_create_happy_path():
    home = col.decks.id("FD1Home")
    tagged, untagged = [], []
    for i in range(20):
        # 7 tag matches among 20 cards; the 7th match gets suspended below
        tags = ("fd1",) if i < 7 else ()
        note = add_basic("FD1Home", "fd1-%02d" % i, tags)
        (tagged if tags else untagged).append(cid_of(note))
    suspended_cid = tagged[6]
    col.sched.suspend_cards([suspended_cid])
    expected = set(tagged[:6])

    assert len(tagged) + len(untagged) == 20
    before_untouched = rows_for(untagged + [suspended_cid])
    before_gathered = {
        row[0]: row for row in rows_for(sorted(expected))}

    resp = bridge.createFilteredDeck(name="FD1 Cram", searchQuery="tag:fd1")
    CAPTURED["create_real"] = resp

    # response shape — every key, no extras (SPEC 32.1 returns block)
    assert set(resp) == {"deckId", "name", "cardsGathered", "terms",
                         "undoEntry"}, resp
    fdid = resp["deckId"]
    assert isinstance(fdid, int) and col.decks.name(fdid) == "FD1 Cram"
    assert resp["name"] == "FD1 Cram"
    assert resp["cardsGathered"] == 6, resp
    assert resp["undoEntry"] == CREATE_LABEL, resp

    # terms echo: normalized search, resolved defaults, honest eligibility
    assert len(resp["terms"]) == 1, resp["terms"]
    term = resp["terms"][0]
    assert set(term) == {"search", "limit", "order", "eligible"}, term
    assert term["search"] == col.build_search_string("tag:fd1"), term
    assert term["limit"] == 100 and term["order"] == "random", term
    assert term["eligible"] == 6, term

    # gathered cards: exactly the 6 unsuspended matches, did = filter,
    # odid = home
    assert cards_in(fdid) == expected, (cards_in(fdid), expected)
    for cid in expected:
        did, odid, queue = card_loc(cid)
        assert did == fdid and odid == home, (cid, did, odid)
        assert queue != -1, "gather touched suspension of %d" % cid

    # the suspended match was NOT gathered and its row is untouched;
    # the 13 non-matches are untouched (preserves: scheduling of
    # non-gathered cards)
    assert rows_for(untagged + [suspended_cid]) == before_untouched, \
        "non-gathered card rows changed across create"
    sdid, sodid, squeue = card_loc(suspended_cid)
    assert (sdid, sodid, squeue) == (home, 0, -1)

    # gathered cards' intervals/ease/reps/lapses/flags preserved (SPEC 32.1
    # preserves line) — residency and due bookkeeping legitimately move
    for row in rows_for(sorted(expected)):
        before = before_gathered[row[0]]
        # columns: 0 id ... 8 ivl, 9 factor, 10 reps, 11 lapses, 14 flags
        for idx in (8, 9, 10, 11, 14):
            assert row[idx] == before[idx], \
                "card %d col %d changed on gather" % (row[0], idx)

    # NOT preserved (documented): the build op selects the built deck
    assert col.decks.get_current_id() == fdid, "create did not select"

    # exactly one undo entry, carrying the documented label
    assert col.undo_status().undo == CREATE_LABEL, col.undo_status().undo

    FD1.update(home=home, fdid=fdid, expected=expected,
               suspended=suspended_cid, all_cids=set(tagged) | set(untagged))


def test1b_single_undo_round_trip():
    # SPEC 32.1: ONE undo entry — a single col.undo() deletes the deck AND
    # returns every gathered card
    col.undo()
    assert col.decks.id_for_name("FD1 Cram") is None, "undo left the deck"
    for cid in FD1["expected"]:
        did, odid, _ = card_loc(cid)
        assert did == FD1["home"] and odid == 0, (cid, did, odid)
    assert cards_in(FD1["home"]) == FD1["all_cids"]
    sdid, sodid, squeue = card_loc(FD1["suspended"])
    assert (sdid, sodid, squeue) == (FD1["home"], 0, -1)


# ===========================================================================
# 2 — limit caps the gather; order honored behaviorally + in saved config;
#     two disjoint terms sum exactly
# ===========================================================================
def test2_limit_and_order():
    notes = [add_basic("FD2Home", "fd2-%d" % i, ("fd2",)) for i in range(5)]
    by_added = [cid_of(n) for n in sorted(notes, key=lambda n: n.id)]

    # order=added under a binding limit: the 2 OLDEST-added matches
    r1 = bridge.createFilteredDeck(name="FD2 AddCram", searchQuery="tag:fd2",
                                   limit=3, order="added")
    assert r1["cardsGathered"] == 3, r1
    assert cards_in(r1["deckId"]) == set(by_added[:3]), \
        (cards_in(r1["deckId"]), by_added)
    assert r1["terms"][0]["limit"] == 3
    assert r1["terms"][0]["order"] == "added"
    assert r1["terms"][0]["eligible"] == 5

    # the saved config carries the requested term (read-only backend read)
    saved = col.sched.get_or_create_filtered_deck(deck_id=DeckId(r1["deckId"]))
    saved_terms = list(saved.config.search_terms)
    assert len(saved_terms) == 1
    assert saved_terms[0].search == col.build_search_string("tag:fd2")
    assert saved_terms[0].limit == 3
    assert saved_terms[0].order == core.FILTERED_DECK_ORDERS["added"]

    col.undo()
    assert col.decks.id_for_name("FD2 AddCram") is None

    # order=reverseAdded picks the opposite end of the same pool — the
    # order parameter demonstrably reached the gather
    r2 = bridge.createFilteredDeck(name="FD2 RevCram", searchQuery="tag:fd2",
                                   limit=3, order="reverseAdded")
    assert r2["cardsGathered"] == 3
    assert cards_in(r2["deckId"]) == set(by_added[-3:]), \
        (cards_in(r2["deckId"]), by_added)
    assert set(by_added[:3]) != set(by_added[-3:])
    col.undo()
    assert col.decks.id_for_name("FD2 RevCram") is None

    # two DISJOINT terms: totals add exactly; secondFilter defaults 20/due
    for i in range(2):
        add_basic("FD2Home", "fd2b-%d" % i, ("fd2b",))
    dry = bridge.createFilteredDeck(
        name="FD2 TwoTerm", searchQuery="tag:fd2",
        secondFilter={"searchQuery": "tag:fd2b"}, dryRun=True)
    assert dry["exact"] is True and dry["wouldGather"] == 7, dry
    assert dry["wouldGatherMin"] == dry["wouldGatherMax"] == 7, dry
    real = bridge.createFilteredDeck(
        name="FD2 TwoTerm", searchQuery="tag:fd2",
        secondFilter={"searchQuery": "tag:fd2b"})
    assert real["cardsGathered"] == 7, real
    assert len(real["terms"]) == 2
    assert real["terms"][1]["search"] == col.build_search_string("tag:fd2b")
    assert real["terms"][1]["limit"] == 20, real["terms"]
    assert real["terms"][1]["order"] == "due", real["terms"]
    assert real["terms"][1]["eligible"] == 2
    col.undo()
    assert col.decks.id_for_name("FD2 TwoTerm") is None


# ===========================================================================
# 3 — dryRun: wouldGather == the real call's gather; NOTHING created;
#     undo proto byte-identical
# ===========================================================================
def test3_dry_run_parity():
    notes = [add_basic("FD3Home", "fd3-%d" % i, ("fd3",)) for i in range(4)]
    col.sched.suspend_cards([cid_of(notes[3])])  # eligible = 3

    rows_before = all_card_rows()
    decks_before = deck_ids_snapshot()
    snap = undo_snap()

    dry = bridge.createFilteredDeck(name="FD3 Cram", searchQuery="tag:fd3",
                                    dryRun=True)
    CAPTURED["create_dry"] = dry

    assert set(dry) == {"wouldCreate", "wouldGather", "exact",
                        "wouldGatherMin", "wouldGatherMax", "name", "terms",
                        "undoEntry"}, dry
    assert dry["wouldCreate"] is True
    assert dry["exact"] is True
    assert dry["wouldGather"] == dry["wouldGatherMin"] == \
        dry["wouldGatherMax"] == 3, dry
    assert dry["name"] == "FD3 Cram"
    assert dry["undoEntry"] is None
    assert dry["terms"][0]["eligible"] == 3

    # provably wrote nothing
    assert undo_snap() == snap, "dry run moved the undo status"
    assert col.decks.id_for_name("FD3 Cram") is None, "dry run created a deck"
    assert deck_ids_snapshot() == decks_before, "dry run changed the deck set"
    assert all_card_rows() == rows_before, "dry run touched card rows"

    # the real call gathers exactly what the dry run predicted
    real = bridge.createFilteredDeck(name="FD3 Cram", searchQuery="tag:fd3")
    assert real["cardsGathered"] == dry["wouldGather"] == 3, \
        (real, dry["wouldGather"])


# ===========================================================================
# 4 — refusals: zero matches, all-suspended pool, bad search, duplicate
#     names, bad order, limit/name/secondFilter parameter errors
# ===========================================================================
def test4_refusals():
    snap = undo_snap()
    decks_before = deck_ids_snapshot()

    # zero matches, real run: [validation_error], NOTHING created
    code, message = plus_error(lambda: bridge.createFilteredDeck(
        name="FD4 Zero", searchQuery="tag:fd4-no-such-tag"))
    assert code == "validation_error", (code, message)
    assert "no cards would be gathered" in message, message
    assert col.decks.id_for_name("FD4 Zero") is None

    # zero matches, dry run: reported, not raised (SPEC 32.1)
    dry = bridge.createFilteredDeck(name="FD4 Zero",
                                    searchQuery="tag:fd4-no-such-tag",
                                    dryRun=True)
    assert dry["wouldCreate"] is False and dry["wouldGather"] == 0, dry
    assert dry["exact"] is True and dry["wouldGatherMax"] == 0, dry

    # matches exist but ALL are suspended -> same refusal (anki's own
    # gather rule, surfaced as the coded refusal)
    s_notes = [add_basic("FD4Home", "fd4s-%d" % i, ("fd4s",))
               for i in range(2)]
    col.sched.suspend_cards([cid_of(n) for n in s_notes])
    code, message = plus_error(lambda: bridge.createFilteredDeck(
        name="FD4 Susp", searchQuery="tag:fd4s"))
    assert code == "validation_error", (code, message)
    assert col.decks.id_for_name("FD4 Susp") is None
    dry = bridge.createFilteredDeck(name="FD4 Susp", searchQuery="tag:fd4s",
                                    dryRun=True)
    assert dry["wouldCreate"] is False and dry["terms"][0]["eligible"] == 0

    # bad search syntax -> [invalid_param] naming searchQuery
    for bad in ('"unclosed', "is:zzzbogus", "tag:(oops"):
        code, message = plus_error(lambda q=bad: bridge.createFilteredDeck(
            name="FD4 Bad", searchQuery=q))
        assert code == "invalid_param", (bad, code, message)
        assert "searchQuery" in message, (bad, message)

    # taken name -> [duplicate]: against a regular deck, its case variant,
    # and an existing filtered deck
    col.decks.id("FD4Dup")
    for name in ("FD4Dup", "fd4dup"):
        code, message = plus_error(lambda n=name: bridge.createFilteredDeck(
            name=n, searchQuery="tag:fd1"))
        assert code == "duplicate", (name, code, message)
        assert "deck already exists" in message, message
    filt = bridge.createFilteredDeck(name="FD4 Cram", searchQuery="tag:fd1")
    code, message = plus_error(lambda: bridge.createFilteredDeck(
        name="FD4 Cram", searchQuery="tag:fd1"))
    assert code == "duplicate", (code, message)
    col.undo()
    assert col.decks.id_for_name("FD4 Cram") is None

    # bad order -> [invalid_param] naming every valid value
    code, message = plus_error(lambda: bridge.createFilteredDeck(
        name="FD4 Ord", searchQuery="tag:fd1", order="bogus"))
    assert code == "invalid_param", (code, message)
    assert "order" in message, message
    for valid in core.FILTERED_DECK_ORDERS:
        assert valid in message, (valid, message)
    # the vocabulary is closed AND case-sensitive
    code, _ = plus_error(lambda: bridge.createFilteredDeck(
        name="FD4 Ord", searchQuery="tag:fd1", order="Random"))
    assert code == "invalid_param"

    # limit bounds and types
    for bad_limit in (0, -1, True, 2 ** 32, "5"):
        code, message = plus_error(
            lambda l=bad_limit: bridge.createFilteredDeck(
                name="FD4 Lim", searchQuery="tag:fd1", limit=l))
        assert code == "invalid_param", (bad_limit, code, message)
        assert "limit" in message, message

    # empty search refused explicitly (would mean the whole collection)
    for empty in ("", "   "):
        code, message = plus_error(lambda q=empty: bridge.createFilteredDeck(
            name="FD4 Emp", searchQuery=q))
        assert code == "invalid_param", (code, message)
        assert "searchQuery" in message

    # un-normalized name components refused up front
    for bad_name in ("Bad ::Pad", "::Lead", "A:: B", "A::"):
        code, message = plus_error(lambda n=bad_name: bridge.createFilteredDeck(
            name=n, searchQuery="tag:fd1"))
        assert code == "invalid_param", (bad_name, code, message)
        assert "name" in message

    # secondFilter: unknown keys refused (a typo'd order must not vanish)
    code, message = plus_error(lambda: bridge.createFilteredDeck(
        name="FD4 SF", searchQuery="tag:fd1",
        secondFilter={"searchQuery": "tag:fd1", "oops": 1}))
    assert code == "invalid_param", (code, message)
    assert "oops" in message, message

    # dryRun type-checked like every other flag
    code, message = plus_error(lambda: bridge.createFilteredDeck(
        name="FD4 DR", searchQuery="tag:fd1", dryRun="yes"))
    assert code == "invalid_param" and "dryRun" in message

    # every refusal above fired BEFORE any undo entry existed, and created
    # nothing (the suspend fixture write is the only legitimate delta)
    assert col.undo_status().undo != CREATE_LABEL, \
        "a refusal left a Create Filtered Deck undo entry"
    assert deck_ids_snapshot() - decks_before == \
        {col.decks.id_for_name("FD4Dup"), col.decks.id_for_name("FD4Home")}, \
        "a refusal created a deck"


# ===========================================================================
# 5 — rebuildFilteredDeck: honest counts, deckId variant, suspension
#     preserved through going home, current-deck preserved, refusals,
#     rebuild-to-zero, gated full no-op
# ===========================================================================
def test5_rebuild():
    home = col.decks.id("FD7Home")
    first = [add_basic("FD7Home", "fd7-%d" % i, ("fd7",)) for i in range(4)]
    made = bridge.createFilteredDeck(name="FD7 Cram", searchQuery="tag:fd7")
    fdid = made["deckId"]
    assert made["cardsGathered"] == 4

    # grow the pool AFTER the create
    later = [add_basic("FD7Home", "fd7-late-%d" % i, ("fd7",))
             for i in range(3)]
    all_cids = {cid_of(n) for n in first} | {cid_of(n) for n in later}

    # dry run first: predicts both halves, writes nothing
    snap = undo_snap()
    dry = bridge.rebuildFilteredDeck(deckName="FD7 Cram", dryRun=True)
    CAPTURED["rebuild_dry"] = dry
    assert set(dry) == {"wouldReturn", "wouldGather", "exact",
                        "wouldGatherMin", "wouldGatherMax", "terms",
                        "termsIgnored", "undoEntry"}, dry
    assert dry["wouldReturn"] == 4 and dry["wouldGather"] == 7, dry
    assert dry["exact"] is True and dry["termsIgnored"] == 0, dry
    assert dry["undoEntry"] is None
    assert dry["terms"][0]["eligible"] == 7, dry["terms"]
    assert undo_snap() == snap, "rebuild dry run moved the undo status"

    # real rebuild by NAME: returnedFirst = pre-op residency, cardsGathered
    # = post-op residency; regathered dids correct; current deck preserved
    col.decks.set_current(DeckId(home))
    real = bridge.rebuildFilteredDeck(deckName="FD7 Cram")
    CAPTURED["rebuild_real"] = real
    assert set(real) == {"cardsGathered", "returnedFirst", "undoEntry"}, real
    assert real["returnedFirst"] == 4 and real["cardsGathered"] == 7, real
    assert real["undoEntry"] == REBUILD_LABEL
    assert col.undo_status().undo == REBUILD_LABEL
    assert cards_in(fdid) == all_cids, (cards_in(fdid), all_cids)
    for cid in all_cids:
        did, odid, _ = card_loc(cid)
        assert did == fdid and odid == home, (cid, did, odid)
    assert col.decks.get_current_id() == home, "rebuild changed current deck"

    # deckId variant
    by_id = bridge.rebuildFilteredDeck(deckId=fdid)
    assert by_id["returnedFirst"] == 7 and by_id["cardsGathered"] == 7, by_id

    # a card suspended INSIDE the deck goes home on the empty half, STILL
    # suspended, and is not re-gathered (the SPEC 32.2 preserves line)
    victim = sorted(all_cids)[0]
    col.sched.suspend_cards([victim])
    vdid, _, vqueue = card_loc(victim)
    assert vdid == fdid and vqueue == -1, \
        "suspend evicted the card from the filter (unexpected on 25.09.4)"
    before = {row[0]: row for row in rows_for([victim])}
    r3 = bridge.rebuildFilteredDeck(deckName="FD7 Cram")
    assert r3["returnedFirst"] == 7, r3   # counted while still resident
    assert r3["cardsGathered"] == 6, r3   # never re-gathered
    vdid, vodid, vqueue = card_loc(victim)
    assert (vdid, vodid, vqueue) == (home, 0, -1), \
        "suspension not preserved through going home: %r" % ((vdid, vodid,
                                                              vqueue),)
    row = rows_for([victim])[0]
    for idx in (8, 9, 10, 11, 14):  # ivl, factor, reps, lapses, flags
        assert row[idx] == before[victim][idx], idx
    assert victim not in cards_in(fdid)

    FD7.update(home=home, fdid=fdid, victim=victim)


def test5b_rebuild_refusals_and_noops():
    # regular deck -> the house [validation_error]
    col.decks.id("FD8Reg")
    code, message = plus_error(
        lambda: bridge.rebuildFilteredDeck(deckName="FD8Reg"))
    assert code == "validation_error", (code, message)
    assert "not a filtered deck" in message, message

    # missing deck, by name and by id
    code, message = plus_error(
        lambda: bridge.rebuildFilteredDeck(deckName="FD8 NoSuchDeck"))
    assert code == "deck_not_found", (code, message)
    code, _ = plus_error(lambda: bridge.rebuildFilteredDeck(deckId=987654321))
    assert code == "deck_not_found"

    # selector family: exactly one of deckName/deckId; bool is not an int
    code, message = plus_error(lambda: bridge.rebuildFilteredDeck())
    assert code == "invalid_param" and "exactly one" in message
    code, _ = plus_error(lambda: bridge.rebuildFilteredDeck(
        deckName="FD8Reg", deckId=1))
    assert code == "invalid_param"
    code, _ = plus_error(lambda: bridge.rebuildFilteredDeck(deckId=True))
    assert code == "invalid_param"
    code, _ = plus_error(lambda: bridge.rebuildFilteredDeck(
        deckName="FD8Reg", dryRun="yes"))
    assert code == "invalid_param"

    # rebuild-to-zero: deck held cards, terms now match nothing -> legal,
    # cardsGathered 0, deck left empty, real undo entry
    notes = [add_basic("FD8Home", "fd8-%d" % i, ("fd8",)) for i in range(2)]
    made = bridge.createFilteredDeck(name="FD8 Cram", searchQuery="tag:fd8")
    fdid = made["deckId"]
    assert made["cardsGathered"] == 2
    home = col.decks.id_for_name("FD8Home")
    for n in notes:
        note = col.get_note(n.id)
        note.tags = []
        col.update_note(note)
    tz = bridge.rebuildFilteredDeck(deckName="FD8 Cram")
    assert tz["returnedFirst"] == 2 and tz["cardsGathered"] == 0, tz
    assert tz["undoEntry"] == REBUILD_LABEL
    assert cards_in(fdid) == set()
    assert col.decks.id_for_name("FD8 Cram") == fdid, "deck vanished"
    for n in notes:
        did, odid, _ = card_loc(cid_of(n))
        assert did == home and odid == 0

    # full data no-op (empty deck, terms gather 0): reported, nothing
    # written, undo status byte-identical
    snap = undo_snap()
    noop = bridge.rebuildFilteredDeck(deckName="FD8 Cram")
    CAPTURED["rebuild_noop"] = noop
    assert noop == {"cardsGathered": 0, "returnedFirst": 0,
                    "undoEntry": None}, noop
    assert undo_snap() == snap, "the gated no-op wrote an undo step"


# ===========================================================================
# 6 — the full lifecycle in one test: create -> report -> export refused ->
#     empty -> export succeeds
# ===========================================================================
def test6_lifecycle():
    home = col.decks.id("LC::Home")
    notes = [add_basic("LC::Home", "lc-%d" % i, ("lc",)) for i in range(5)]
    cids = {cid_of(n) for n in notes}

    made = bridge.createFilteredDeck(name="LC Cram", searchQuery="tag:lc")
    fdid = made["deckId"]
    assert made["cardsGathered"] == 5

    # filteredDeckReport sees the new deck with the right counts, unscoped
    # and scoped to the home subtree
    report = bridge.filteredDeckReport()
    row = next(r for r in report["filteredDecks"]
               if r["filteredDeck"] == "LC Cram")
    assert row["filteredDeckId"] == fdid
    assert row["cardCount"] == 5, row
    assert row["homeDecks"] == {"LC::Home": 5}, row
    scoped = bridge.filteredDeckReport(deckName="LC::Home")
    assert scoped["totalCards"] == 5, scoped
    assert [r["filteredDeck"] for r in scoped["filteredDecks"]] == ["LC Cram"]

    # exporting the home deck now refuses fail-closed
    out = os.path.join(SCRATCH, "lc_export.apkg")
    code, message = plus_error(lambda: bridge.exportDeckApkg(
        deckName="LC::Home", outPath=out))
    assert code == "cards_in_filtered_decks", (code, message)
    assert "LC Cram" in message, message
    assert not os.path.exists(out), "refused export still wrote a file"

    # emptyFilteredDeck returns the cards home
    emptied = bridge.emptyFilteredDeck(deckName="LC Cram")
    assert emptied["returned"] == 5, emptied
    assert emptied["homeDecks"] == {"LC::Home": 5}, emptied
    for cid in cids:
        did, odid, _ = card_loc(cid)
        assert did == home and odid == 0, (cid, did, odid)
    assert bridge.filteredDeckReport(deckName="LC::Home")["totalCards"] == 0

    # and now the export succeeds, clean
    result = bridge.exportDeckApkg(deckName="LC::Home", outPath=out)
    assert set(result) == {"path", "sizeBytes", "notesExported", "warnings"}, \
        result
    assert result["path"] == out and os.path.exists(out)
    assert result["sizeBytes"] == os.path.getsize(out) > 0
    assert result["notesExported"] == 5, result
    assert result["warnings"] == [], result


# ===========================================================================
# 7 — lockstep: version/revision/action-count, SPEC header, served returns
#     docs name every top-level key of every captured response shape, and
#     the served preserves lines are the empirically verified ones
# ===========================================================================
def test7_lockstep():
    assert core.PLUS_VERSION == "1.5.0", core.PLUS_VERSION
    assert core.PLUS_SPEC_REVISION == 20, core.PLUS_SPEC_REVISION
    # 36 -> 37: revision-20 SPEC 33 adds ankihubStageOptionalTagSuggestion
    assert len(core.PLUS_ACTIONS) == 37, len(core.PLUS_ACTIONS)
    assert len(set(core.PLUS_ACTIONS)) == 37, "duplicate action names"
    for action in ("createFilteredDeck", "rebuildFilteredDeck"):
        assert action in core.PLUS_ACTIONS, action

    # the SPEC.md header names the same version + revision
    with open(os.path.join(REPO, "SPEC.md"), encoding="utf-8") as handle:
        head = handle.read(8192)
    assert "Version: 1.5.0 (spec revision 20" in head, \
        "SPEC.md header disagrees with core constants"

    info = stubbed_info()
    assert info["version"] == "1.5.0" and info["specRevision"] == 20
    assert len(info["actions"]) == 37
    assert set(info["actions"]) == set(core.PLUS_ACTIONS)
    assert len(info["actionDocs"]) == 37

    # both actions' docs served complete; preserves is the same line the
    # empirical tests above verified (suspension/burial never gathered,
    # non-gathered rows untouched — tests 1/5)
    for action in ("createFilteredDeck", "rebuildFilteredDeck"):
        docs = info["actionDocs"][action]
        for facet in ("summary", "params", "returns", "preserves"):
            assert docs.get(facet), (action, facet)
        assert docs["preserves"] == core.PLUS_ACTION_PRESERVES[action]
    create_docs = info["actionDocs"]["createFilteredDeck"]
    rebuild_docs = info["actionDocs"]["rebuildFilteredDeck"]
    assert "never gathered" in create_docs["preserves"]
    assert "membership" in rebuild_docs["preserves"]
    # live wrapper signatures serve the documented defaults
    for fragment in ("name", "searchQuery", "limit=100", "order=null",
                     "secondFilter=null", "reschedule=true", "dryRun=false",
                     "undoLabel=null"):
        assert fragment in create_docs["params"], (fragment,
                                                   create_docs["params"])
    for fragment in ("deckName=null", "deckId=null", "dryRun=false",
                     "undoLabel=null"):
        assert fragment in rebuild_docs["params"], (fragment,
                                                    rebuild_docs["params"])

    # returns docs verified against REAL captured responses: the key sets
    # match SPEC 32's documented shapes exactly, and every top-level key is
    # named in the served returns text
    expected_shapes = {
        ("create_real", "createFilteredDeck"):
            {"deckId", "name", "cardsGathered", "terms", "undoEntry"},
        ("create_dry", "createFilteredDeck"):
            {"wouldCreate", "wouldGather", "exact", "wouldGatherMin",
             "wouldGatherMax", "name", "terms", "undoEntry"},
        ("rebuild_real", "rebuildFilteredDeck"):
            {"cardsGathered", "returnedFirst", "undoEntry"},
        ("rebuild_noop", "rebuildFilteredDeck"):
            {"cardsGathered", "returnedFirst", "undoEntry"},
        ("rebuild_dry", "rebuildFilteredDeck"):
            {"wouldReturn", "wouldGather", "exact", "wouldGatherMin",
             "wouldGatherMax", "terms", "termsIgnored", "undoEntry"},
    }
    for (capture, action), keys in expected_shapes.items():
        resp = CAPTURED[capture]
        assert set(resp) == keys, (capture, set(resp), keys)
        doc = info["actionDocs"][action]["returns"]
        for key in resp:
            assert key in doc, \
                "returns doc for %s does not name %r (%s)" % (action, key,
                                                              capture)
    # the term-row keys are documented too
    for action in ("createFilteredDeck", "rebuildFilteredDeck"):
        doc = info["actionDocs"][action]["returns"]
        for key in ("search", "limit", "order", "eligible"):
            assert key in doc, (action, key)


# ===========================================================================

run("1  create: 20-card seed, 6 gathered, suspended excluded, dids/odids, "
    "preserves, selects, shape", test1_create_happy_path)
run("1b create: single undo deletes the deck and returns every card",
    test1b_single_undo_round_trip)
run("2  create: limit caps; order honored (added vs reverseAdded) + saved "
    "config; disjoint two-term exact", test2_limit_and_order)
run("3  create dryRun: parity with the real gather, nothing created, undo "
    "proto byte-identical", test3_dry_run_parity)
run("4  create refusals: zero-match, all-suspended, bad search, duplicate, "
    "bad order, param family", test4_refusals)
run("5  rebuild: honest counts by name/id, suspension preserved going home, "
    "current deck preserved", test5_rebuild)
run("5b rebuild refusals + rebuild-to-zero + gated full no-op",
    test5b_rebuild_refusals_and_noops)
run("6  lifecycle: create -> report -> export refused -> empty -> export "
    "clean", test6_lifecycle)
run("7  lockstep: 1.5.0 / rev 20 / 37 actions; returns docs vs captured "
    "shapes; served preserves", test7_lockstep)

col.close()

failures = [name for name, ok, _ in RESULTS if not ok]
print("%d/%d passed" % (len(RESULTS) - len(failures), len(RESULTS)), flush=True)
sys.exit(1 if failures else 0)
