# Headless INDEPENDENT verification of the round-4 "GUI gap" work (spec
# revision 17) — written by a separate verifier against the field report's own
# scenarios, deliberately NOT reusing the implementers' test fixtures:
#
#   1. renameDeck    — parent + 3 children, each with a CUSTOM options preset
#                      and description; pairs exact, presets/descriptions
#                      re-checked from the collection (not trusted from the
#                      response), cardsAffected recounted odid-aware, ONE undo
#                      entry with a custom undoLabel, single undo restores all
#                      names; dryRun byte-identical; [duplicate] refusal;
#                      the Lab 1..Lab 12 zero-pad scenario end-to-end
#                      (21 subdecks on a non-default preset).
#   2. filtered + export — the 141-card near-miss reproduced at 20/6 scale:
#                      filteredDeckReport census, exportDeckApkg fail-closed
#                      ([cards_in_filtered_decks], NO file), allowFilteredOmission
#                      escape hatch with warnings, a REAL import into a second
#                      scratch collection showing the 14 surviving notes,
#                      emptyFilteredDeck remediation, clean export warnings [].
#   3. empty cards   — c1+c2 note edited to c1-only; getEmptyCards vs
#                      checkDeckIntegrity.clozeCardMismatch cross-checked;
#                      deleteEmptyCards dry/real/undo; all-empty-note last-card
#                      protection; noteIds=null sweep.
#   4. bulkSetFlag   — 3/2 updated/unchanged split from real pre-op flags,
#                      undoLabel, one undo, flag 0 clear, 8/-1 refusals, dry.
#   5. renameTag     — x::lab1 -> x::lab01 with x::lab10 untouched and
#                      x::lab1::sub followed; pairs exact; notesUpdated
#                      recounted; dry preview parity; undo restores.
#   6. plusInfo      — action count (code truth: 36 = 27 + slice1 3 + slice2 4
#                      + revision-19 SPEC 32's 2; the verification briefing said
#                      32 — code, SPEC and README all agree on 36, asserted in
#                      lockstep here), returns
#                      docs spot-verified against REAL captured responses,
#                      errorCodes coverage, PLUS_VERSION/PLUS_SPEC_REVISION
#                      lockstep with the SPEC.md header.
#
# Run with: "/Users/mattyc/Library/Application Support/AnkiProgramFiles/.venv/bin/python" headless_guigap_test.py
#
# FRESH scratch collections; never touches ~/Library/Application Support/Anki2/.
# ZERO NETWORK by construction AND enforcement (socket deny-guard below).

import importlib
import importlib.util
import os
import shutil
import socket
import sys
import tempfile
import traceback
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_PATH = os.path.join(REPO, "connect_plus", "core.py")

_PREFERRED_SCRATCH = ("/private/tmp/claude-501/-Users-mattyc-Downloads-prite-daily-main/"
                      "6b24b91e-e4dc-4cbf-934f-6e83d3ff850a/scratchpad/ancp_r4_v1")


def _pick_scratch():
    env = os.environ.get("ANCP_TEST_SCRATCH")
    if env:
        return env
    try:
        os.makedirs(_PREFERRED_SCRATCH, exist_ok=True)
        return os.path.join(_PREFERRED_SCRATCH, "col_scratch")
    except OSError:
        return tempfile.mkdtemp(prefix="ancp_guigap_")


SCRATCH = _pick_scratch()
# HARD RULE: the real collection is never touched
assert not SCRATCH.startswith(os.path.expanduser("~/Library")), \
    "scratch dir must not be under ~/Library"
assert "Anki2" not in SCRATCH
if os.path.exists(SCRATCH):
    shutil.rmtree(SCRATCH)
os.makedirs(SCRATCH)

sys.dont_write_bytecode = True

# ------------------------------------------------------------------ core load
# core.py standalone (no package __init__, no aqt); purity re-verified so this
# suite also stands alone as an aqt-free alarm for the pure layer.
spec = importlib.util.spec_from_file_location("core", CORE_PATH)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
assert "aqt" not in sys.modules, "core.py (or its imports) pulled in aqt"
assert not any(m.startswith("PyQt6") for m in sys.modules), \
    "core.py (or its imports) pulled in PyQt6"

# ------------------------------------------------------------------ net guard
NETWORK_ATTEMPTS = []


def _make_deny(name):
    def _deny(*args, **kwargs):
        NETWORK_ATTEMPTS.append((name, args[:2]))
        raise RuntimeError("network access blocked by headless_guigap_test "
                          "(%s)" % name)
    return _deny


socket.socket.connect = _make_deny("socket.connect")
socket.socket.connect_ex = _make_deny("socket.connect_ex")
socket.create_connection = _make_deny("socket.create_connection")
socket.getaddrinfo = _make_deny("socket.getaddrinfo")

# ------------------------------------------------------------------ anki setup
import anki.lang  # noqa: E402
anki.lang.set_lang("en_US")
from anki.collection import Collection, ImportAnkiPackageRequest  # noqa: E402
from anki.decks import DeckId  # noqa: E402
from anki.errors import NotFoundError  # noqa: E402

col_main = Collection(os.path.join(SCRATCH, "main.anki2"))    # scenarios 1/4/5
col_filt = Collection(os.path.join(SCRATCH, "filt.anki2"))    # scenario 2
col_empty = Collection(os.path.join(SCRATCH, "empty.anki2"))  # scenario 3

EXPORT_DIR = os.path.join(SCRATCH, "exports")
os.makedirs(EXPORT_DIR)

RESULTS = []
OBSERVED_CODES = set()   # every '[code]' this suite provoked
CAPTURED = {}            # action -> [real response dicts] for the returns check


def run(name, fn):
    try:
        fn()
        RESULTS.append((name, True, ""))
        print("PASS  %s" % name, flush=True)
    except Exception:
        RESULTS.append((name, False, traceback.format_exc()))
        print("FAIL  %s" % name, flush=True)
        print(traceback.format_exc(), flush=True)


def capture(action, resp):
    CAPTURED.setdefault(action, []).append(resp)
    return resp


def add_note(col, deck, front, tags=()):
    n = col.new_note(col.models.by_name("Basic"))
    n["Front"] = front
    n["Back"] = "b"
    n.tags = list(tags)
    col.add_note(n, col.decks.id(deck))
    return n


def add_cloze(col, deck, text):
    n = col.new_note(col.models.by_name("Cloze"))
    n["Text"] = text
    col.add_note(n, col.decks.id(deck))
    return n


def mkfilter(col, name, search, limit=100):
    fd = col.sched.get_or_create_filtered_deck(DeckId(0))
    fd.name = name
    del fd.config.search_terms[:]
    term = fd.config.search_terms.add()
    term.search = search
    term.limit = limit
    term.order = 0
    return int(col.sched.add_or_update_filtered_deck(fd).id)


def snap(col):
    # the BACKEND undo status (undo/redo strings + monotonic last_step): the
    # strict bytes behind "dryRun writes nothing"
    return col._backend.get_undo_status().SerializeToString()


def code_of(fn):
    try:
        fn()
    except Exception as err:
        msg = str(err)
        assert msg.startswith("["), "unprefixed error: %r" % msg
        code = msg.split("] ", 1)[0].lstrip("[")
        OBSERVED_CODES.add(code)
        return code
    raise AssertionError("expected an exception")


def card_rows(col, nid):
    return col.db.all(
        "select id, ord, did, odid from cards where nid = ? order by ord", nid)


def deck_names(col):
    return sorted(d["name"] for d in col.decks.all())


# ============================================================================
# Scenario 1 — renameDeck
# ============================================================================

P1_CFG = {}    # deck name -> (deck id, custom config id, description)
P1_SUBTREE_IDS = []


def _setup_p1():
    for name, n_cards in [("P1", 2), ("P1::c1", 3), ("P1::c2", 4), ("P1::c3", 5)]:
        did = col_main.decks.id(name)
        cfg = col_main.decks.add_config_returning_id("cfg %s" % name)
        deck = col_main.decks.get(did)
        col_main.decks.set_config_id_for_deck_dict(deck, cfg)
        deck = col_main.decks.get(did)
        deck["desc"] = "description of %s" % name
        col_main.decks.save(deck)
        for i in range(n_cards):
            add_note(col_main, name, "%s card %d" % (name, i))
        P1_CFG[name] = (did, cfg, "description of %s" % name)
        P1_SUBTREE_IDS.append(did)
    # one card of P1::c1 VISITS a filtered deck: cardsAffected must still count
    # it (home is in the subtree even while did points at the filter)
    visitor_cid = col_main.db.scalar(
        "select id from cards where did = ? order by id limit 1",
        P1_CFG["P1::c1"][0])
    fid = mkfilter(col_main, "V1", "cid:%d" % visitor_cid, limit=1)
    assert col_main.db.scalar(
        "select count() from cards where did = ?", fid) == 1, \
        "setup: filter V1 failed to pull its card"


def _real_subtree_card_count():
    ids = ",".join(str(x) for x in P1_SUBTREE_IDS)
    return col_main.db.scalar(
        "select count() from cards where did in ({0}) or odid in ({0})".format(ids))


EXPECT_PAIRS = [
    {"from": "P1", "to": "Q1"},
    {"from": "P1::c1", "to": "Q1::c1"},
    {"from": "P1::c2", "to": "Q1::c2"},
    {"from": "P1::c3", "to": "Q1::c3"},
]


def test01_rename_deck_dry_then_real():
    _setup_p1()
    assert _real_subtree_card_count() == 14, "setup: expected 14 cards"

    names_before = deck_names(col_main)
    before = snap(col_main)
    dry = core.rename_deck(col_main, "P1", "Q1", dry_run=True)
    assert snap(col_main) == before, "dryRun wrote to the undo stack"
    assert deck_names(col_main) == names_before, "dryRun changed deck names"
    assert dry["wouldRename"] == EXPECT_PAIRS, dry
    assert dry["cardsAffected"] == 14, dry
    assert dry["undoEntry"] is None, dry

    pre_step = col_main._backend.get_undo_status().last_step
    resp = capture("renameDeck",
                   core.rename_deck(col_main, "P1", "Q1",
                                    undo_label="zero pad sweep"))
    assert resp["renamed"] == EXPECT_PAIRS, resp
    assert resp["configPreserved"] is True, resp
    assert resp["cardsAffected"] == 14, resp
    assert resp["undoEntry"] == "AnkiConnect Plus: zero pad sweep", resp

    # do NOT trust configPreserved: re-read every deck by id ourselves
    for old_name, (did, cfg, desc) in P1_CFG.items():
        deck = col_main.decks.get(did, default=False)
        assert deck is not None, old_name
        assert deck["name"] == "Q1" + old_name[len("P1"):], deck["name"]
        assert deck["conf"] == cfg, (old_name, deck["conf"], cfg)
        assert deck["desc"] == desc, (old_name, deck["desc"])
    # the visitor card's HOME (odid) followed because home deck ids are stable
    assert col_main.db.scalar(
        "select count() from cards where odid = ?", P1_CFG["P1::c1"][0]) == 1

    # ONE undo entry: it is on top under the custom label, and a SINGLE undo
    # restores every name
    status = col_main._backend.get_undo_status()
    assert status.undo == "AnkiConnect Plus: zero pad sweep", status.undo
    assert status.last_step == pre_step + 1, \
        "expected exactly one new undo step, got %d -> %d" % (pre_step,
                                                             status.last_step)
    col_main.undo()
    for old_name, (did, cfg, desc) in P1_CFG.items():
        deck = col_main.decks.get(did, default=False)
        assert deck["name"] == old_name, (old_name, deck["name"])
        assert deck["conf"] == cfg
        assert deck["desc"] == desc
    status = col_main._backend.get_undo_status()
    assert status.redo == "AnkiConnect Plus: zero pad sweep", status.redo
    assert status.undo != "AnkiConnect Plus: zero pad sweep"

    # capture a dry response too, for the plusInfo returns check
    capture("renameDeck", core.rename_deck(col_main, "P1", "Q1", dry_run=True))


def test02_rename_deck_refusals():
    col_main.decks.id("TakenD")
    names_before = deck_names(col_main)
    before = snap(col_main)

    # occupied target: refused on both paths, [duplicate]
    assert code_of(lambda: core.rename_deck(col_main, "P1", "TakenD")) == "duplicate"
    assert code_of(lambda: core.rename_deck(col_main, "P1", "TakenD",
                                            dry_run=True)) == "duplicate"
    # renaming onto its own descendant: pairwise self-identity tightening
    assert code_of(lambda: core.rename_deck(col_main, "P1", "P1::c1")) == "duplicate"
    # un-normalized newName refused up front (both paths)
    assert code_of(lambda: core.rename_deck(col_main, "P1", "P1x ::y")) == "invalid_param"
    assert code_of(lambda: core.rename_deck(col_main, "P1", "P1x::")) == "invalid_param"
    assert code_of(lambda: core.rename_deck(col_main, "P1", " P1x",
                                            dry_run=True)) == "invalid_param"
    # missing deck
    assert code_of(lambda: core.rename_deck(col_main, "NopeDeck", "Z")) == "deck_not_found"
    # the exact house message shape on the duplicate refusal
    try:
        core.rename_deck(col_main, "P1", "TakenD")
        raise AssertionError("expected duplicate refusal")
    except Exception as e:
        assert str(e) == "[duplicate] deck already exists: TakenD", str(e)

    # byte-identical rename is a data no-op
    noop = core.rename_deck(col_main, "P1", "P1")
    assert noop == {"renamed": [], "configPreserved": True, "cardsAffected": 0,
                    "undoEntry": None}, noop

    assert deck_names(col_main) == names_before, "a refusal changed deck names"
    assert snap(col_main) == before, "a refusal/no-op touched the undo stack"


def test03_rename_deck_lab_zero_pad():
    # the field report's motivating case: Lab 1..Lab 12 zero-padded so the
    # deck list sorts, on a tree whose decks all share a NON-default preset
    preset = col_main.decks.add_config_returning_id("R4 Lab preset")
    subdecks = ["HA2R4::Lab %d" % n for n in range(1, 13)] + \
               ["HA2R4::Extra %d" % n for n in range(1, 10)]
    assert len(subdecks) == 21
    all_decks = ["HA2R4"] + subdecks
    ids_by_name = {}
    for name in all_decks:
        did = col_main.decks.id(name)
        deck = col_main.decks.get(did)
        col_main.decks.set_config_id_for_deck_dict(deck, preset)
        ids_by_name[name] = did
    for n in range(1, 13):
        add_note(col_main, "HA2R4::Lab %d" % n, "lab%d q" % n)

    # the zero-pad footgun itself: Lab 1 -> Lab 10 is OCCUPIED and must refuse
    assert code_of(lambda: core.rename_deck(
        col_main, "HA2R4::Lab 1", "HA2R4::Lab 10")) == "duplicate"

    for n in range(1, 10):
        resp = core.rename_deck(col_main, "HA2R4::Lab %d" % n,
                                "HA2R4::Lab 0%d" % n)
        assert resp["renamed"] == [{"from": "HA2R4::Lab %d" % n,
                                    "to": "HA2R4::Lab 0%d" % n}], resp
        assert resp["configPreserved"] is True, resp
        assert resp["cardsAffected"] == 1, resp
        assert resp["undoEntry"] == core.UNDO_RENAME_DECK, resp

    expected = {"HA2R4"} \
        | {"HA2R4::Lab 0%d" % n for n in range(1, 10)} \
        | {"HA2R4::Lab %d" % n for n in (10, 11, 12)} \
        | {"HA2R4::Extra %d" % n for n in range(1, 10)}
    actual = {d["name"] for d in col_main.decks.all()
              if d["name"] == "HA2R4" or d["name"].startswith("HA2R4::")}
    assert actual == expected, actual.symmetric_difference(expected)

    # presets intact after the whole sweep, ids stable across every rename
    for name, did in ids_by_name.items():
        deck = col_main.decks.get(did, default=False)
        assert deck is not None and deck["conf"] == preset, (name, deck)
    assert col_main.decks.id_for_name("HA2R4::Lab 01") == ids_by_name["HA2R4::Lab 1"]
    assert col_main.decks.id_for_name("HA2R4::Lab 10") == ids_by_name["HA2R4::Lab 10"]
    # Lab 10's own single card is untouched in place
    assert col_main.decks.card_count(ids_by_name["HA2R4::Lab 10"],
                                     include_subdecks=True) == 1


# ============================================================================
# Scenario 4 — bulkSetFlag
# ============================================================================

FLAG_CIDS = []


def test04_bulk_set_flag():
    for i in range(5):
        add_note(col_main, "FlagsR4", "flag card %d" % i)
    FLAG_CIDS.extend(col_main.db.list(
        "select c.id from cards c join notes n on n.id = c.nid "
        "where c.did = ? order by c.id", col_main.decks.id("FlagsR4")))
    assert len(FLAG_CIDS) == 5
    c1, c2, c3, c4, c5 = FLAG_CIDS
    col_main.set_user_flag_for_cards(1, [c1, c2])   # 2 already carry flag 1

    def flags():
        return [col_main.get_card(cid).user_flag() for cid in FLAG_CIDS]

    assert flags() == [1, 1, 0, 0, 0]
    before = snap(col_main)

    # dry: precheck split predicted, NOTHING written (dup + unknown id thrown in)
    dry = core.bulk_set_flag(col_main, [c1, c2, c3, c4, c5, c3, 99999999999],
                             1, dry_run=True)
    assert dry == {"wouldUpdate": [c3, c4, c5], "unchanged": [c1, c2],
                   "undoEntry": None}, dry
    assert snap(col_main) == before, "dryRun wrote"
    assert flags() == [1, 1, 0, 0, 0], "dryRun changed flags"

    # real: updated 3 / unchanged 2 from the REAL pre-op flags, custom label
    resp = capture("bulkSetFlag",
                   core.bulk_set_flag(col_main,
                                      [c1, c2, c3, c4, c5, c3, 99999999999], 1,
                                      undo_label="flag sweep"))
    assert resp == {"updated": [c3, c4, c5], "unchanged": [c1, c2],
                    "undoEntry": "AnkiConnect Plus: flag sweep"}, resp
    assert flags() == [1, 1, 1, 1, 1]
    assert col_main._backend.get_undo_status().undo == "AnkiConnect Plus: flag sweep"

    # ONE undo reverts exactly the three writes
    col_main.undo()
    assert flags() == [1, 1, 0, 0, 0]
    assert col_main._backend.get_undo_status().redo == "AnkiConnect Plus: flag sweep"

    # flag 0 clears (only the two flagged cards are writes)
    resp0 = core.bulk_set_flag(col_main, FLAG_CIDS, 0)
    assert resp0 == {"updated": [c1, c2], "unchanged": [c3, c4, c5],
                     "undoEntry": core.UNDO_BULK_FLAG}, resp0
    assert flags() == [0, 0, 0, 0, 0]

    # all-unchanged is a reported data no-op: nothing written, no entry
    before0 = snap(col_main)
    noop = core.bulk_set_flag(col_main, FLAG_CIDS, 0)
    assert noop == {"updated": [], "unchanged": FLAG_CIDS, "undoEntry": None}, noop
    assert snap(col_main) == before0, "no-op wrote"

    # refusals
    assert code_of(lambda: core.bulk_set_flag(col_main, FLAG_CIDS, 8)) == "invalid_param"
    assert code_of(lambda: core.bulk_set_flag(col_main, FLAG_CIDS, -1)) == "invalid_param"
    assert code_of(lambda: core.bulk_set_flag(col_main, FLAG_CIDS, True)) == "invalid_param"
    assert code_of(lambda: core.bulk_set_flag(col_main, "cards", 1)) == "invalid_param"
    assert code_of(lambda: core.bulk_set_flag(col_main, [c1, 1.5], 1)) == "invalid_param"
    assert flags() == [0, 0, 0, 0, 0]

    capture("bulkSetFlag", core.bulk_set_flag(col_main, FLAG_CIDS, 2, dry_run=True))


# ============================================================================
# Scenario 5 — renameTag
# ============================================================================

def test05_rename_tag():
    n1 = add_note(col_main, "TagsR4", "t1", tags=["x::lab1"])
    n2 = add_note(col_main, "TagsR4", "t2", tags=["x::lab10"])
    n3 = add_note(col_main, "TagsR4", "t3", tags=["x::lab1::sub"])
    n4 = add_note(col_main, "TagsR4", "t4", tags=["x::lab1", "x::lab1::sub"])

    expect_pairs = sorted([("x::lab1", "x::lab01"),
                           ("x::lab1::sub", "x::lab01::sub")])

    def tags_of(n):
        return sorted(col_main.get_note(n.id).tags)

    before = snap(col_main)
    registry_before = sorted(col_main.tags.all())

    # dry: subtree followed, lab10 EXCLUDED, nothing written
    dry = core.rename_tag(col_main, "x::lab1", "x::lab01", dry_run=True)
    assert sorted((p["from"], p["to"]) for p in dry["wouldRewrite"]) == \
        expect_pairs, dry
    assert all(p["from"] != "x::lab10" for p in dry["wouldRewrite"]), dry
    assert dry["merged"] == [] and dry["undoEntry"] is None, dry
    assert snap(col_main) == before, "dryRun wrote"
    assert sorted(col_main.tags.all()) == registry_before, "dryRun changed registry"
    assert tags_of(n1) == ["x::lab1"]

    # real: notesUpdated recounted independently (n1, n3, n4 = 3 notes)
    assert len(col_main.find_notes("tag:x::lab1")) == 3
    resp = capture("renameTag",
                   core.rename_tag(col_main, "x::lab1", "x::lab01"))
    assert resp["notesUpdated"] == 3, resp
    assert sorted((p["from"], p["to"]) for p in resp["tagsRewritten"]) == \
        expect_pairs, resp
    assert resp["merged"] == [], resp
    assert resp["undoEntry"] == core.UNDO_RENAME_TAG, resp

    assert tags_of(n1) == ["x::lab01"]
    assert tags_of(n2) == ["x::lab10"], "lab10 was corrupted by the rename"
    assert tags_of(n3) == ["x::lab01::sub"]
    assert tags_of(n4) == ["x::lab01", "x::lab01::sub"]
    registry = col_main.tags.all()
    assert "x::lab01" in registry and "x::lab01::sub" in registry
    assert "x::lab1" not in registry and "x::lab1::sub" not in registry
    assert "x::lab10" in registry
    assert len(col_main.find_notes("tag:x::lab01")) == 3
    assert len(col_main.find_notes("tag:x::lab10")) == 1

    # ONE undo restores notes and registry
    assert col_main._backend.get_undo_status().undo == core.UNDO_RENAME_TAG
    col_main.undo()
    assert tags_of(n1) == ["x::lab1"]
    assert tags_of(n2) == ["x::lab10"]
    assert tags_of(n3) == ["x::lab1::sub"]
    assert tags_of(n4) == ["x::lab1", "x::lab1::sub"]
    assert len(col_main.find_notes("tag:x::lab1")) == 3
    assert len(col_main.find_notes("tag:x::lab01")) == 0

    # refusals
    assert code_of(lambda: core.rename_tag(col_main, "zz::missing", "zz::x")) == "not_found"
    assert code_of(lambda: core.rename_tag(col_main, "x::lab1", "a b")) == "invalid_param"
    assert code_of(lambda: core.rename_tag(col_main, 5, "x")) == "invalid_param"

    capture("renameTag",
            core.rename_tag(col_main, "x::lab1", "x::lab01", dry_run=True))


# ============================================================================
# Scenario 2 — filtered decks + export (the 141-card near-miss, 20/6 scale)
# ============================================================================

FILT = {}


def test06_filtered_report_and_export_refusal():
    home_did = col_filt.decks.id("HomeR4")
    fronts = []
    for i in range(20):
        front = "h%02d" % i
        fronts.append(front)
        add_note(col_filt, "HomeR4", front,
                 tags=["pull"] if i % 3 == 2 else [])
    pulled_fronts = {f for i, f in enumerate(fronts) if i % 3 == 2}
    assert len(pulled_fronts) == 6
    add_note(col_filt, "OtherR4", "elsewhere")

    fid = mkfilter(col_filt, "FiltR4", "deck:HomeR4 tag:pull")
    assert col_filt.db.scalar(
        "select count() from cards where did = ?", fid) == 6, \
        "setup: expected the filter to pull exactly 6 cards"
    assert col_filt.db.scalar(
        "select count() from cards where did = ? and odid = ?",
        fid, home_did) == 6, "setup: visitors must be homed in HomeR4"
    FILT.update(home_did=home_did, fid=fid, pulled_fronts=pulled_fronts,
                all_fronts=set(fronts))

    # census: unscoped, home-scoped, filter-named — read-only
    before = snap(col_filt)
    rep = capture("filteredDeckReport", core.filtered_deck_report(col_filt))
    assert rep == {"filteredDecks": [
        {"filteredDeck": "FiltR4", "filteredDeckId": fid, "cardCount": 6,
         "homeDecks": {"HomeR4": 6}}], "totalCards": 6}, rep
    scoped = core.filtered_deck_report(col_filt, deck_name="HomeR4")
    assert scoped == rep, scoped
    other = core.filtered_deck_report(col_filt, deck_name="OtherR4")
    assert other == {"filteredDecks": [], "totalCards": 0}, other
    own = core.filtered_deck_report(col_filt, deck_name="FiltR4")
    assert own == rep, own
    assert code_of(lambda: core.filtered_deck_report(
        col_filt, deck_name="NopeR4")) == "deck_not_found"
    assert snap(col_filt) == before, "filteredDeckReport wrote"

    # fail-closed export: house error naming the count, NO file written
    out1 = os.path.join(EXPORT_DIR, "refused.apkg")
    try:
        core.export_deck_apkg(col_filt, "HomeR4", out_path=out1)
        raise AssertionError("expected [cards_in_filtered_decks]")
    except Exception as e:
        msg = str(e)
        assert msg.startswith("[cards_in_filtered_decks] "), msg
        OBSERVED_CODES.add("cards_in_filtered_decks")
        assert getattr(e, "retryable", None) is False, "refusal must not be retryable"
        assert "6 cards" in msg, msg
        assert "FiltR4: 6" in msg, msg
        assert "6 such notes" in msg, msg
        assert "emptyFilteredDeck" in msg and "allowFilteredOmission=true" in msg, msg
    assert not os.path.exists(out1), "refused export still wrote a file"
    assert os.listdir(EXPORT_DIR) == [], "refused export wrote something"
    assert snap(col_filt) == before, "refused export touched the undo stack"


def test07_export_allowed_omission_then_import_proves_loss():
    out2 = os.path.join(EXPORT_DIR, "allowed.apkg")
    resp = capture("exportDeckApkg",
                   core.export_deck_apkg(col_filt, "HomeR4", out_path=out2,
                                         allow_filtered_omission=True))
    assert resp["path"] == out2, resp
    assert os.path.exists(out2)
    assert resp["sizeBytes"] == os.path.getsize(out2), resp
    assert resp["notesExported"] == 14, resp
    assert resp["warnings"] == [{"code": "cards_in_filtered_decks", "count": 6,
                                 "decks": {"FiltR4": 6}, "notesOmitted": 6}], resp

    # the omission made VISIBLE: a real import into a second scratch collection
    dst = Collection(os.path.join(SCRATCH, "import_target.anki2"))
    try:
        dst.import_anki_package(ImportAnkiPackageRequest(package_path=out2))
        assert dst.db.scalar("select count() from notes") == 14
        assert dst.db.scalar("select count() from cards") == 14
        arrived = {flds.split("\x1f")[0]
                   for (flds,) in dst.db.all("select flds from notes")}
        assert arrived == FILT["all_fronts"] - FILT["pulled_fronts"], arrived
        assert not (arrived & FILT["pulled_fronts"]), \
            "a filtered-away note arrived anyway"
    finally:
        dst.close()


def test08_empty_filtered_deck_then_clean_export():
    fid, home_did = FILT["fid"], FILT["home_did"]

    before = snap(col_filt)
    dry = core.empty_filtered_deck(col_filt, deck_name="FiltR4", dry_run=True)
    assert dry == {"wouldReturn": 6, "homeDecks": {"HomeR4": 6},
                   "undoEntry": None}, dry
    assert snap(col_filt) == before, "dryRun wrote"
    assert col_filt.db.scalar("select count() from cards where did = ?", fid) == 6

    resp = capture("emptyFilteredDeck",
                   core.empty_filtered_deck(col_filt, deck_name="FiltR4",
                                            undo_label="send home"))
    assert resp == {"returned": 6, "homeDecks": {"HomeR4": 6},
                    "undoEntry": "AnkiConnect Plus: send home"}, resp
    assert col_filt.db.scalar("select count() from cards where did = ?", fid) == 0
    assert col_filt.db.scalar(
        "select count() from cards where did = ? and odid = 0", home_did) == 20, \
        "cards did not all land home with odid cleared"
    assert col_filt._backend.get_undo_status().undo == "AnkiConnect Plus: send home"

    # single undo restores the filter's residents
    col_filt.undo()
    assert col_filt.db.scalar("select count() from cards where did = ?", fid) == 6
    assert col_filt.db.scalar(
        "select count() from cards where did = ? and odid = ?",
        fid, home_did) == 6

    # re-run via the deckId path (deck resolution parity), default label
    resp2 = core.empty_filtered_deck(col_filt, deck_id=fid)
    assert resp2 == {"returned": 6, "homeDecks": {"HomeR4": 6},
                     "undoEntry": core.UNDO_EMPTY_FILTERED}, resp2

    # already-empty: gated data no-op, no phantom undo entry
    before2 = snap(col_filt)
    noop = capture("emptyFilteredDeck",
                   core.empty_filtered_deck(col_filt, deck_name="FiltR4"))
    assert noop == {"returned": 0, "homeDecks": {}, "undoEntry": None}, noop
    assert snap(col_filt) == before2, "already-empty case wrote"

    # refusals: regular deck, param shapes
    assert code_of(lambda: core.empty_filtered_deck(
        col_filt, deck_name="HomeR4")) == "validation_error"
    assert code_of(lambda: core.empty_filtered_deck(
        col_filt, deck_name="FiltR4", deck_id=fid)) == "invalid_param"
    assert code_of(lambda: core.empty_filtered_deck(col_filt)) == "invalid_param"
    assert code_of(lambda: core.empty_filtered_deck(
        col_filt, deck_id=424242)) == "deck_not_found"
    assert code_of(lambda: core.empty_filtered_deck(
        col_filt, deck_name="ZilchR4")) == "deck_not_found"

    # after remediation the export sails through, warnings []
    out3 = os.path.join(EXPORT_DIR, "clean.apkg")
    clean = capture("exportDeckApkg",
                    core.export_deck_apkg(col_filt, "HomeR4", out_path=out3))
    assert clean["notesExported"] == 20, clean
    assert clean["warnings"] == [], clean
    assert os.path.exists(out3)

    capture("emptyFilteredDeck",
            core.empty_filtered_deck(col_filt, deck_name="FiltR4", dry_run=True))


# ============================================================================
# Scenario 3 — empty cards (col_empty)
# ============================================================================

EC = {}


def test09_empty_cards_report_and_integrity_crosscheck():
    note_a = add_cloze(col_empty, "EDeck", "{{c1::alpha}} {{c2::beta}}")
    note_b = add_cloze(col_empty, "EDeck", "{{c1::gamma}} {{c2::delta}}")
    note_c = add_note(col_empty, "EDeck", "plain basic")
    col_empty.decks.id("OtherE")  # empty scope target

    a_cards = {ord_: cid for cid, ord_, _d, _o in card_rows(col_empty, note_a.id)}
    b_cards = {ord_: cid for cid, ord_, _d, _o in card_rows(col_empty, note_b.id)}
    assert sorted(a_cards) == [0, 1] and sorted(b_cards) == [0, 1]
    EC.update(a=note_a.id, b=note_b.id, c=note_c.id,
              a0=a_cards[0], a1=a_cards[1], b0=b_cards[0], b1=b_cards[1])

    # A: c1+c2 -> c1-only (ord-1 card orphaned); B: -> no clozes (all empty)
    note_a["Text"] = "{{c1::alpha}} kept, beta gone"
    col_empty.update_note(note_a)
    note_b["Text"] = "no clozes remain here"
    col_empty.update_note(note_b)

    before = snap(col_empty)
    rep = capture("getEmptyCards", core.get_empty_cards(col_empty))
    assert snap(col_empty) == before, "getEmptyCards wrote"
    assert rep["total"] == 2 and len(rep["notes"]) == 2, rep
    by_note = {n["noteId"]: n for n in rep["notes"]}
    ent_a = by_note[EC["a"]]
    assert ent_a["ords"] == [1], ent_a
    assert ent_a["willDeleteCards"] == [EC["a1"]], ent_a
    assert len(ent_a["willDeleteCards"]) == 1, ent_a  # "willDeleteCards 1"
    assert ent_a["protectedCard"] is None, ent_a
    ent_b = by_note[EC["b"]]
    assert ent_b["ords"] == [0, 1], ent_b
    assert ent_b["protectedCard"] == EC["b0"], ent_b
    assert ent_b["willDeleteCards"] == [EC["b1"]], ent_b

    # deck scoping
    scoped = core.get_empty_cards(col_empty, deck_name="EDeck")
    assert {n["noteId"] for n in scoped["notes"]} == {EC["a"], EC["b"]}, scoped
    empty_scope = core.get_empty_cards(col_empty, deck_name="OtherE")
    assert empty_scope == {"notes": [], "total": 0}, empty_scope
    assert code_of(lambda: core.get_empty_cards(
        col_empty, deck_name="NopeE")) == "deck_not_found"
    assert code_of(lambda: core.get_empty_cards(
        col_empty, deck_name=9)) == "invalid_param"

    # the OTHER audit must agree: checkDeckIntegrity.clozeCardMismatch
    audit = core.check_deck_integrity(col_empty, "EDeck")
    mismatch = {e["noteId"]: e for e in audit["clozeCardMismatch"]}
    assert set(mismatch) == {EC["a"], EC["b"]}, \
        "the two audits disagree: %r vs %r" % (sorted(mismatch),
                                               sorted(by_note))
    assert mismatch[EC["a"]] == {"noteId": EC["a"], "expectedOrds": [0],
                                 "actualOrds": [0, 1]}, mismatch
    assert mismatch[EC["b"]] == {"noteId": EC["b"], "expectedOrds": [],
                                 "actualOrds": [0, 1]}, mismatch
    assert audit["clozeNotesWithoutCloze"] == [EC["b"]], audit
    assert snap(col_empty) == before, "checkDeckIntegrity wrote"


def test10_delete_empty_cards():
    a, b, c = EC["a"], EC["b"], EC["c"]
    a0, a1, b0, b1 = EC["a0"], EC["a1"], EC["b0"], EC["b1"]

    def note_exists(nid):
        try:
            col_empty.get_note(nid)
            return True
        except NotFoundError:
            return False

    # dry: exact prediction, nothing written
    before = snap(col_empty)
    dry = core.delete_empty_cards(col_empty, note_ids=[a], dry_run=True)
    assert dry == {"wouldDelete": [a1], "notesAffected": 1, "protected": [],
                   "skipped": [], "undoEntry": None}, dry
    assert snap(col_empty) == before, "dryRun wrote"
    assert len(card_rows(col_empty, a)) == 2

    # real: ONLY the orphan goes; note + c1 card survive
    resp = capture("deleteEmptyCards",
                   core.delete_empty_cards(col_empty, note_ids=[a],
                                           undo_label="empty sweep A"))
    assert resp == {"cardsDeleted": 1, "deletedCardIds": [a1],
                    "notesAffected": 1, "protected": [], "notesPreserved": True,
                    "skipped": [], "undoEntry": "AnkiConnect Plus: empty sweep A"}, resp
    assert note_exists(a), "the note itself was deleted"
    assert [(cid, ord_) for cid, ord_, _d, _o in card_rows(col_empty, a)] == \
        [(a0, 0)], "surviving cards wrong"
    assert len(card_rows(col_empty, b)) == 2, "note B was touched"

    # one undo entry restores the deleted card
    assert col_empty._backend.get_undo_status().undo == "AnkiConnect Plus: empty sweep A"
    col_empty.undo()
    assert {cid for cid, _o, _d, _od in card_rows(col_empty, a)} == {a0, a1}, \
        "undo did not restore the orphan card"

    # requested ids outside the report are SKIPPED with reasons, and an
    # all-skip call is a data no-op (no phantom undo entry)
    before2 = snap(col_empty)
    sk = core.delete_empty_cards(col_empty, note_ids=[c, 4242424242424])
    assert sk["cardsDeleted"] == 0 and sk["deletedCardIds"] == [], sk
    assert sk["undoEntry"] is None and sk["notesPreserved"] is True, sk
    assert sk["skipped"] == [{"noteId": c, "reason": "no empty cards"},
                             {"noteId": 4242424242424,
                              "reason": "note was not found"}], sk
    assert snap(col_empty) == before2, "all-skip call wrote"

    # noteIds=null sweeps everything found, honoring last-card protection
    sweep_dry = capture("deleteEmptyCards",
                        core.delete_empty_cards(col_empty, dry_run=True))
    assert sorted(sweep_dry["wouldDelete"]) == sorted([a1, b1]), sweep_dry
    assert sweep_dry["notesAffected"] == 2, sweep_dry
    assert sweep_dry["protected"] == [{"noteId": b, "cardId": b0}], sweep_dry
    sweep = capture("deleteEmptyCards", core.delete_empty_cards(col_empty))
    assert sweep["cardsDeleted"] == 2, sweep
    assert sorted(sweep["deletedCardIds"]) == sorted([a1, b1]), sweep
    assert sweep["notesAffected"] == 2, sweep
    assert sweep["protected"] == [{"noteId": b, "cardId": b0}], sweep
    assert sweep["notesPreserved"] is True, sweep
    assert sweep["undoEntry"] == core.UNDO_DELETE_EMPTY, sweep
    assert note_exists(a) and note_exists(b) and note_exists(c), \
        "a note was deleted despite the protection"
    assert [cid for cid, _o, _d, _od in card_rows(col_empty, a)] == [a0]
    assert [cid for cid, _o, _d, _od in card_rows(col_empty, b)] == [b0], \
        "note B lost its protected last card"

    # the protected last card is NEVER deletable: acting on B again is a
    # data no-op that still reports the protection
    before3 = snap(col_empty)
    again = core.delete_empty_cards(col_empty, note_ids=[b])
    assert again["cardsDeleted"] == 0 and again["undoEntry"] is None, again
    assert again["protected"] == [{"noteId": b, "cardId": b0}], again
    assert snap(col_empty) == before3, "protected-only call wrote"
    sweep2 = core.delete_empty_cards(col_empty)   # a global sweep agrees
    assert sweep2["cardsDeleted"] == 0 and sweep2["undoEntry"] is None, sweep2
    assert note_exists(b) and len(card_rows(col_empty, b)) == 1

    # refusals
    assert code_of(lambda: core.delete_empty_cards(
        col_empty, note_ids="all")) == "invalid_param"
    assert code_of(lambda: core.delete_empty_cards(
        col_empty, note_ids=[a], dry_run="yes")) == "invalid_param"


# ============================================================================
# Scenario 6 — plusInfo + doc lockstep (loads plus.py -> aqt; keep LAST)
# ============================================================================

NEW_ACTIONS = ["renameDeck", "bulkSetFlag", "renameTag", "filteredDeckReport",
               "emptyFilteredDeck", "getEmptyCards", "deleteEmptyCards"]

EXPECT_PARAMS = {
    "renameDeck": "oldName, newName, dryRun=false, undoLabel=null",
    "bulkSetFlag": "cardIds, flag, dryRun=false, undoLabel=null",
    "renameTag": "oldTag, newTag, dryRun=false, undoLabel=null",
    "filteredDeckReport": "deckName=null",
    "emptyFilteredDeck": "deckName=null, deckId=null, dryRun=false, undoLabel=null",
    "getEmptyCards": "deckName=null",
    "deleteEmptyCards": "noteIds=null, dryRun=false, undoLabel=null",
}


def test11_plusinfo_and_doc_lockstep():
    assert "aqt" not in sys.modules, "a core-path test pulled in aqt"

    # ---- code-level registry truth. The verification briefing said "32
    # actions"; the code says 36 (27 at v1.2.0 + 3 slice-1 + 4 slice-2 +
    # 2 revision-19 filtered-deck build), and
    # SPEC.md's own revision entries say 27 -> 30 -> 34 -> 36. Lock the internally
    # consistent truth; the briefing's number is reported as stale.
    assert len(core.PLUS_ACTIONS) == 36, len(core.PLUS_ACTIONS)
    assert len(set(core.PLUS_ACTIONS)) == 36, "duplicate action names"
    for name in NEW_ACTIONS:
        assert name in core.PLUS_ACTIONS, name
    assert set(core.PLUS_ACTION_SUMMARIES) == set(core.PLUS_ACTIONS)
    assert set(core.PLUS_ACTION_RETURNS) == set(core.PLUS_ACTIONS)
    assert core.PLUS_VERSION == "1.4.0", core.PLUS_VERSION
    assert core.PLUS_SPEC_REVISION == 19, core.PLUS_SPEC_REVISION
    assert "%d Plus actions" % len(core.PLUS_ACTIONS) in core.PLUS_ERROR_PREFIX_NOTE

    # ---- SPEC.md header lockstep
    with open(os.path.join(REPO, "SPEC.md"), encoding="utf-8") as fh:
        spec_head = fh.read(20000)
    want = "Version: %s (spec revision %d," % (core.PLUS_VERSION,
                                               core.PLUS_SPEC_REVISION)
    assert want in spec_head, "SPEC.md header does not carry %r" % want
    assert "**36**" in spec_head, "SPEC.md header lost the 36-action count"

    # ---- README lockstep: every new action has a table row; the export
    # escape hatch is documented
    with open(os.path.join(REPO, "README.md"), encoding="utf-8") as fh:
        readme = fh.read()
    for name in NEW_ACTIONS:
        assert "`%s`" % name in readme, "README.md does not mention %s" % name
    assert "allowFilteredOmission" in readme
    assert "cards_in_filtered_decks" in readme

    # ---- live plusInfo through the real wrapper layer
    pkg_name = "ancp_guigap_pkg"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [os.path.join(REPO, "connect_plus")]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg
    plus = importlib.import_module(pkg_name + ".plus")
    util_mod = sys.modules[pkg_name + ".util"]
    orig_setting = util_mod.setting
    util_mod.setting = lambda key: util_mod.DEFAULT_CONFIG[key]
    try:
        info = plus.PlusMixin().plusInfo()
    finally:
        util_mod.setting = orig_setting

    assert info["version"] == core.PLUS_VERSION == "1.4.0", info["version"]
    assert info["specRevision"] == core.PLUS_SPEC_REVISION == 19
    assert info["actions"] == list(core.PLUS_ACTIONS)
    assert len(info["actions"]) == 36

    # every action documented, returns non-empty, params never hidden
    for name in core.PLUS_ACTIONS:
        doc = info["actionDocs"][name]
        assert doc["summary"].strip(), "empty summary: %s" % name
        assert doc["returns"].strip(), "empty returns: %s" % name
        assert "args" not in doc["params"], (name, doc["params"])
    for name, params in EXPECT_PARAMS.items():
        assert info["actionDocs"][name]["params"] == params, \
            (name, info["actionDocs"][name]["params"])
    assert "allowFilteredOmission=false" in \
        info["actionDocs"]["exportDeckApkg"]["params"]

    # returns docs are TRUE: every top-level key of every REAL response this
    # suite captured must be named in that action's returns sketch
    assert set(CAPTURED) == {"renameDeck", "bulkSetFlag", "renameTag",
                             "filteredDeckReport", "emptyFilteredDeck",
                             "getEmptyCards", "deleteEmptyCards",
                             "exportDeckApkg"}, sorted(CAPTURED)
    for action, responses in CAPTURED.items():
        returns_doc = info["actionDocs"][action]["returns"]
        for resp in responses:
            for key in resp:
                assert key in returns_doc, \
                    "%s returned key %r missing from its returns doc" % (action, key)
    # row/nested keys the docs promise
    assert all(k in info["actionDocs"]["filteredDeckReport"]["returns"]
               for k in ("filteredDeck", "filteredDeckId", "cardCount", "homeDecks"))
    assert all(k in info["actionDocs"]["getEmptyCards"]["returns"]
               for k in ("noteId", "ords", "willDeleteCards", "protectedCard"))
    assert all(k in info["actionDocs"]["exportDeckApkg"]["returns"]
               for k in ("notesOmitted", "foreign_cards_in_scope_filters"))

    # errorCodes: the new codes are present, reachable, correctly flagged,
    # and every code this suite provoked is in the served vocabulary
    ec = info["errorCodes"]
    assert set(ec) == set(core.PLUS_ERROR_CODES)
    assert ec["duplicate"]["retryable"] is False
    assert ec["duplicate"]["reachable"] is True
    assert "renameDeck" in ec["duplicate"]["meaning"]
    assert ec["cards_in_filtered_decks"]["retryable"] is False
    assert ec["cards_in_filtered_decks"]["reachable"] is True
    assert "exportDeckApkg" in ec["cards_in_filtered_decks"]["meaning"]
    for code in OBSERVED_CODES:
        assert code in ec, "observed code %r not served by plusInfo" % code
        assert ec[code]["reachable"] is True, \
            "observed code %r documented unreachable" % code
    expected_observed = {"duplicate", "invalid_param", "deck_not_found",
                         "not_found", "validation_error",
                         "cards_in_filtered_decks"}
    assert expected_observed <= OBSERVED_CODES, \
        OBSERVED_CODES.symmetric_difference(expected_observed)

    # recipes gained the two round-4 patterns
    recipe_names = [r["name"] for r in info["recipes"]]
    assert "safe deck export" in recipe_names, recipe_names
    assert "empty-cards cleanup" in recipe_names, recipe_names

    # ---- wrapper wire smoke: each new wrapper routes to core with the house
    # '[code] ' contract intact end-to-end
    class MainAC(plus.PlusMixin):
        def collection(self):
            return col_main

    class FiltAC(plus.PlusMixin):
        def collection(self):
            return col_filt

    class EmptyAC(plus.PlusMixin):
        def collection(self):
            return col_empty

    try:
        MainAC().renameDeck(oldName="P1", newName="TakenD")
        raise AssertionError("expected [duplicate]")
    except Exception as e:
        assert str(e) == "[duplicate] deck already exists: TakenD", str(e)
        assert getattr(e, "code", None) == "duplicate"
    try:
        MainAC().bulkSetFlag(cardIds=[1], flag=9)
        raise AssertionError("expected [invalid_param]")
    except Exception as e:
        assert str(e) == "[invalid_param] invalid parameter: flag: integer 0-7 required", str(e)
    assert code_of(lambda: MainAC().renameTag(oldTag="zz::none", newTag="zz::x")) \
        == "not_found"
    assert code_of(lambda: FiltAC().emptyFilteredDeck(deckName="HomeR4")) \
        == "validation_error"
    rep = FiltAC().filteredDeckReport()
    assert rep["filteredDecks"][0]["filteredDeck"] == "FiltR4"
    assert FiltAC().getEmptyCards() == {"notes": [], "total": 0}
    sk = EmptyAC().deleteEmptyCards(noteIds=[123456789012])
    assert sk["skipped"] == [{"noteId": 123456789012,
                              "reason": "note was not found"}], sk


# ============================================================================

def main():
    tests = [
        ("renameDeck: dry preview + real rename, presets/desc/undo", test01_rename_deck_dry_then_real),
        ("renameDeck: duplicate/normalization refusals + no-op", test02_rename_deck_refusals),
        ("renameDeck: Lab 1..12 zero-pad, 21 subdecks, presets intact", test03_rename_deck_lab_zero_pad),
        ("bulkSetFlag: 3/2 split, label, undo, clear, refusals", test04_bulk_set_flag),
        ("renameTag: lab1->lab01 subtree, lab10 untouched, undo", test05_rename_tag),
        ("filtered: report census + export fail-closed, no file", test06_filtered_report_and_export_refusal),
        ("export: allowFilteredOmission warnings + real import shows 14", test07_export_allowed_omission_then_import_proves_loss),
        ("emptyFilteredDeck: dry/real/undo/no-op/refusals + clean export", test08_empty_filtered_deck_then_clean_export),
        ("empty cards: report + integrity cross-check", test09_empty_cards_report_and_integrity_crosscheck),
        ("deleteEmptyCards: orphan, protection, sweep, skipped", test10_delete_empty_cards),
        ("plusInfo: 36 actions, returns truth, codes, SPEC/README lockstep", test11_plusinfo_and_doc_lockstep),
    ]
    for name, fn in tests:
        run(name, fn)

    assert not NETWORK_ATTEMPTS, "network attempted: %r" % NETWORK_ATTEMPTS

    for c in (col_main, col_filt, col_empty):
        try:
            c.close()
        except Exception:
            pass

    failed = [r for r in RESULTS if not r[1]]
    print()
    print("guigap: %d/%d scenario groups passed" % (len(RESULTS) - len(failed),
                                                    len(RESULTS)))
    if failed:
        for name, _ok, tb in failed:
            print("FAILED: %s" % name)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
