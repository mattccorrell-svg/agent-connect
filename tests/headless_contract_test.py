# INDEPENDENT round-1 verification of the revision-18 contract (v1.3.1).
#
# Written by the verifier, not the implementer: fixtures, rigs and assertions
# are built fresh from SPEC 31 / 27 and the shipped artifacts, so agreement
# here is corroboration rather than an echo of the implementation's own suite.
#
#   1. Stale-claim sweep held on the LIVE surface: plusInfo (constructed
#      headless through the real PlusMixin with a stubbed config read) serves
#      bulkAddNotes docs with no 'defaults to true' / 'ships true' claim, and
#      summary/params/returns agree with each other AND with the shipped
#      config.json / util.DEFAULT_CONFIG / core defaults (revision-16 split).
#   2. effectiveConfig: user store {suspendNewCards: true} -> value true,
#      source 'user_config'; virgin install -> shipped false + 'shipped_default';
#      a config change lands on the NEXT plusInfo call of the SAME instance
#      (call-time resolution, no caching); no-mw -> shipped values,
#      'shipped_default' (the SPEC 31.3 documented nuance).
#   3. suspensionPreserved/schedulingPreserved on bulkUpdateNoteFields and
#      bulkReplaceInFields, driven through the WRAPPERS: 3-note edit with one
#      suspended note -> both true, the suspended card still queue -1; keys
#      absent from dry responses; and the forced-false alarm — a delegating
#      collection proxy that unsuspends the written note's cards mid-call
#      (after the undo merge; a raw write inside update_note would invalidate
#      the pending merge target) must be REPORTED false, proving the booleans
#      are computed, not hardcoded.
#   4. Dry-run parity: renameTag dry notesUpdated == the following real run's
#      backend count, with a note carrying TWO affected tags counted once;
#      renameDeck dry carries configWillBePreserved: true, the real run still
#      carries the configPreserved post-check and the options preset really
#      survives (verified by id, against a non-default preset).
#   5. 'preserves' claims, empirical, one representative claim per action for
#      FIVE mutating actions: bulkUpdateNoteFields (existing card rows
#      byte-identical across a field edit), bulkAddTags (scheduling + card
#      set untouched), renameTag (the entire cards table untouched, sibling
#      tags kept), deleteEmptyCards (surviving card's scheduling untouched,
#      note never deleted), bulkSetFlag (due/ivl untouched; only the user
#      bits of the flags byte change — a pre-set non-user bit survives).
#   6. Lockstep: PLUS_VERSION 1.3.1, PLUS_SPEC_REVISION 18, the SPEC.md
#      header agrees, 34 actions, and plusInfo serves the same three.
#
# Run with: "/Users/mattyc/Library/Application Support/AnkiProgramFiles/.venv/bin/python" headless_contract_test.py
#
# Scratch collection under the session scratchpad (ancp_r5_v1), overridable
# via ANCP_CONTRACT_SCRATCH, tempfile fallback if unwritable. NEVER touches
# ~/Library/Application Support/Anki2/. A process-wide socket deny-guard
# makes any network attempt an immediate failure.

import importlib
import importlib.util
import json
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
        raise AssertionError("network denied in headless contract test: %s" % name)
    return guard


socket.socket.connect = _deny("socket.connect")
socket.socket.connect_ex = _deny("socket.connect_ex")
socket.socket.bind = _deny("socket.bind")
socket.create_connection = _deny("socket.create_connection")
socket.getaddrinfo = _deny("socket.getaddrinfo")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_PATH = os.path.join(REPO, "connect_plus", "core.py")
_DEFAULT_SCRATCH = ("/private/tmp/claude-501/-Users-mattyc-Downloads-prite-daily-main/"
                    "6b24b91e-e4dc-4cbf-934f-6e83d3ff850a/scratchpad/ancp_r5_v1")
SCRATCH = os.environ.get("ANCP_CONTRACT_SCRATCH") or _DEFAULT_SCRATCH

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
    SCRATCH = tempfile.mkdtemp(prefix="ancp_contract_")

# ---------------------------------------------------------------------------
# load core.py STANDALONE first and re-verify its aqt-free purity
# ---------------------------------------------------------------------------
_spec = importlib.util.spec_from_file_location("contract_core", CORE_PATH)
core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(core)
assert "aqt" not in sys.modules, "core.py (or its imports) pulled in aqt"

import anki.lang
anki.lang.set_lang("en_US")
from anki.collection import Collection

col = Collection(os.path.join(SCRATCH, "contract.anki2"))

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
# fixtures
# ---------------------------------------------------------------------------

def add_basic(deck, front, back="b", tags=()):
    n = col.new_note(col.models.by_name("Basic"))
    n["Front"] = front
    n["Back"] = back
    n.tags = list(tags)
    col.add_note(n, col.decks.id(deck))
    return n


def add_cloze(deck, text):
    n = col.new_note(col.models.by_name("Cloze"))
    n["Text"] = text
    col.add_note(n, col.decks.id(deck))
    return n


# full persisted card state minus the bookkeeping columns (mod/usn move on
# any write by design and prove nothing about preservation)
STATE_COLS = ("id, nid, did, odid, ord, type, queue, due, ivl, factor, "
              "reps, lapses, left, odue, flags, data")


def rows_of(nid):
    return col.db.all(
        "select {} from cards where nid = ? order by ord".format(STATE_COLS), nid)


def all_card_rows():
    return col.db.all(
        "select {} from cards order by id".format(STATE_COLS))


PKG = "ancp_contract_pkg"


def load_plus():
    """Import connect_plus.plus under a private package name (the package
    __init__ builds GUI hooks, so the module is loaded directly)."""
    if PKG not in sys.modules:
        pkg = types.ModuleType(PKG)
        pkg.__path__ = [os.path.join(REPO, "connect_plus")]
        pkg.__package__ = PKG
        sys.modules[PKG] = pkg
    return importlib.import_module(PKG + ".plus")


def make_bridge(plus, collection):
    """A minimal live object serving the PlusMixin surface headless."""
    class Bridge(plus.PlusMixin):
        def collection(self):
            return collection
    return Bridge()


def stubbed_info(plus, collection=None):
    """plusInfo() with util.setting served from DEFAULT_CONFIG (headless)."""
    util_mod = sys.modules[PKG + ".util"]
    orig = util_mod.setting
    util_mod.setting = lambda key: util_mod.DEFAULT_CONFIG[key]
    try:
        return make_bridge(plus, collection).plusInfo()
    finally:
        util_mod.setting = orig


def shipped_config():
    with open(os.path.join(REPO, "connect_plus", "config.json"),
              encoding="utf-8") as handle:
        return json.load(handle)


# ===========================================================================
# 1 — stale-claim sweep on the LIVE plusInfo surface + revision-16 split
#     consistency across summary/params/returns AND the shipped artifacts
# ===========================================================================
def test1_live_stale_claim_sweep():
    plus = load_plus()
    info = stubbed_info(plus)
    doc = info["actionDocs"]["bulkAddNotes"]

    # the round-5 report's exact poison, checked on the wire surface itself:
    # nothing in bulkAddNotes' docs may claim the revision-15 default
    blob = json.dumps(doc).lower()
    assert "defaults to true" not in blob, doc
    assert "ships true" not in blob, doc
    assert "normally returns" not in blob, doc

    # 'defaults to true' must be gone from EVERY action's live docs; 'ships
    # true' stays legal ONLY where it is true (preserveSuspendedOnReschedule)
    for name, entry in info["actionDocs"].items():
        entry_blob = json.dumps(entry).lower()
        assert "defaults to true" not in entry_blob, name
        if "ships true" in entry_blob:
            assert "preservesuspended" in entry_blob.replace(" ", ""), \
                "'ships true' outside the preserveSuspended context: %s" % name

    # mutual consistency of the three doc facets with the revision-16 split:
    # params (live signature) says suspend=null — config decides, not a
    # hardcoded true; summary and returns both name the config key, its
    # shipped-false value, and point at effectiveConfig
    assert "suspend=null" in doc["params"], doc["params"]
    for facet in ("summary", "returns"):
        text = doc[facet]
        assert "suspendNewCards" in text, (facet, text)
        assert "ships false" in text.lower(), (facet, text)
        assert "effectiveConfig" in text, (facet, text)
    assert "suspended" in doc["returns"], doc["returns"]

    # ...and the claims are TRUE in the shipped artifacts, not just the prose:
    # config.json, util.DEFAULT_CONFIG and the core defaults all ship
    # suspendNewCards=false / preserveSuspendedOnReschedule=true
    util_mod = sys.modules[PKG + ".util"]
    shipped = shipped_config()
    assert shipped["suspendNewCards"] is False, shipped
    assert util_mod.DEFAULT_CONFIG["suspendNewCards"] is False
    assert core.DEFAULT_SUSPEND_NEW_CARDS is False
    assert shipped["preserveSuspendedOnReschedule"] is True, shipped
    assert util_mod.DEFAULT_CONFIG["preserveSuspendedOnReschedule"] is True
    assert core.DEFAULT_PRESERVE_SUSPENDED_ON_RESCHEDULE is True
    # the other half of the split states ITS true shipped default
    due_doc = json.dumps(info["actionDocs"]["bulkSetDueDate"]).lower()
    assert "preservesuspendedonreschedule" in due_doc
    assert "ships true" in due_doc


# ===========================================================================
# 2 — effectiveConfig: honest value+source, call-time resolution, no-mw
# ===========================================================================
def test2_effective_config():
    plus = load_plus()
    util_mod = sys.modules[PKG + ".util"]
    orig_setting = util_mod.setting
    orig_aqt = util_mod.aqt
    shipped = shipped_config()
    meta = {}  # the faithful meta.json model; user config sits at meta['config']

    def fake_get_config(name):
        # aqt 25.09.4 semantics: shipped config.json with the user's saved
        # keys merged over it
        merged = dict(shipped)
        merged.update(meta.get("config", {}))
        return merged

    def eff_of(info):
        eff = info["effectiveConfig"]
        assert set(eff) == {"suspendNewCards", "preserveSuspendedOnReschedule"}, eff
        for row in eff.values():
            assert set(row) == {"value", "source"}, row
            assert isinstance(row["value"], bool), row
            assert row["source"] in ("user_config", "shipped_default"), row
        return eff

    try:
        util_mod.setting = orig_setting  # the REAL accessor throughout
        util_mod.aqt = types.SimpleNamespace(mw=types.SimpleNamespace(
            addonManager=types.SimpleNamespace(
                getConfig=fake_get_config,
                addonMeta=lambda addon: dict(meta),
                addonFromModule=lambda module: module.split(".")[0])))
        bridge = make_bridge(plus, None)

        # (a) no user config: shipped values, shipped_default on BOTH keys
        eff = eff_of(bridge.plusInfo())
        assert eff["suspendNewCards"] == \
            {"value": False, "source": "shipped_default"}, eff
        assert eff["preserveSuspendedOnReschedule"] == \
            {"value": True, "source": "shipped_default"}, eff

        # (b) the user saves {suspendNewCards: true}: the NEXT plusInfo call
        # on the SAME instance reports value true, source user_config —
        # call-time resolution, nothing cached at construction or first call
        meta["config"] = {"suspendNewCards": True}
        eff = eff_of(bridge.plusInfo())
        assert eff["suspendNewCards"] == \
            {"value": True, "source": "user_config"}, eff
        # per-key attribution: the other key is still only shipped
        assert eff["preserveSuspendedOnReschedule"] == \
            {"value": True, "source": "shipped_default"}, eff
        # lockstep with the write path: a parameterless write resolves the
        # same value through the same ladder
        assert plus._resolve_suspension_param(
            None, core.CONFIG_SUSPEND_NEW_CARDS,
            core.DEFAULT_SUSPEND_NEW_CARDS) is True

        # (c) ...and removing it lands on the very next call too
        meta.pop("config")
        eff = eff_of(bridge.plusInfo())
        assert eff["suspendNewCards"] == \
            {"value": False, "source": "shipped_default"}, eff

        # (d) no mw at all (true headless): the resolver answers the shipped
        # defaults with shipped_default — SPEC 31.3's documented nuance
        util_mod.aqt = types.SimpleNamespace(mw=None)
        assert plus._resolve_suspension_config(
            core.CONFIG_SUSPEND_NEW_CARDS, core.DEFAULT_SUSPEND_NEW_CARDS) == \
            (False, "shipped_default")
        assert plus._resolve_suspension_config(
            core.CONFIG_PRESERVE_SUSPENDED,
            core.DEFAULT_PRESERVE_SUSPENDED_ON_RESCHEDULE) == \
            (True, "shipped_default")
        # the full plusInfo dict agrees (apiVersion served so the call can
        # complete; the SPEC 27 keys still go through the raising accessor)
        def selective(key):
            if key == "apiVersion":
                return util_mod.DEFAULT_CONFIG[key]
            raise Exception("setting %s not found" % key)
        util_mod.setting = selective
        eff = eff_of(bridge.plusInfo())
        assert eff["suspendNewCards"] == \
            {"value": False, "source": "shipped_default"}, eff
        assert eff["preserveSuspendedOnReschedule"] == \
            {"value": True, "source": "shipped_default"}, eff
    finally:
        util_mod.setting = orig_setting
        util_mod.aqt = orig_aqt


# ===========================================================================
# 3 — §31.2 post-checks through the WRAPPERS + the forced-false alarm
# ===========================================================================
class UnsuspendRig:
    """Delegating collection proxy that silently UNSUSPENDS the written
    note's cards mid-call — the exact class of bug the post-check alarms on.
    The raw write happens after merge_undo_entries: a raw db write inside
    update_note would invalidate the pending merge target."""

    def __init__(self, real):
        self._real = real
        self._pending = None

    def __getattr__(self, name):
        return getattr(self._real, name)

    def update_note(self, note):
        self._pending = note.id
        return self._real.update_note(note)

    def merge_undo_entries(self, target):
        out = self._real.merge_undo_entries(target)
        if self._pending is not None:
            self._real.db.execute(
                "update cards set queue = 0 where nid = ? and queue = -1",
                self._pending)
            self._pending = None
        return out


def test3_postchecks_and_alarm():
    plus = load_plus()
    bridge = make_bridge(plus, col)

    na = add_basic("VC3", "a one", "old")
    nb = add_basic("VC3", "b one", "old")
    nc = add_basic("VC3", "c one", "old")
    cid_c = col.card_ids_of_note(nc.id)[0]
    r = core.bulk_suspend(col, [cid_c], suspend=True)
    assert r["changed"] == 1, r
    assert col.get_card(cid_c).queue == -1

    # bulkUpdateNoteFields, wrapper: 3 notes, one suspended -> both true
    r = bridge.bulkUpdateNoteFields(
        [{"id": na.id, "fields": {"Back": "new"}},
         {"id": nb.id, "fields": {"Back": "new"}},
         {"id": nc.id, "fields": {"Back": "new"}}])
    assert sorted(r["updated"]) == sorted([na.id, nb.id, nc.id]), r
    assert r["suspensionPreserved"] is True, r
    assert r["schedulingPreserved"] is True, r
    assert col.get_card(cid_c).queue == -1, "the edit unsuspended the card"

    # bulkReplaceInFields, wrapper: same three notes, same contract
    r = bridge.bulkReplaceInFields(noteIds=[na.id, nb.id, nc.id],
                                   field="Front", find="one", replace="two")
    assert sorted(r["changed"]) == sorted([na.id, nb.id, nc.id]), r
    assert r["suspensionPreserved"] is True, r
    assert r["schedulingPreserved"] is True, r
    assert col.get_card(cid_c).queue == -1, "the replace unsuspended the card"

    # dry responses carry NEITHER key (nothing written, no fact to verify)
    dry = bridge.bulkUpdateNoteFields(
        [{"id": na.id, "fields": {"Back": "newer"}}], dryRun=True)
    assert "suspensionPreserved" not in dry, dry
    assert "schedulingPreserved" not in dry, dry
    dry = bridge.bulkReplaceInFields(noteIds=[na.id], field="Front",
                                     find="two", replace="three", dryRun=True)
    assert "suspensionPreserved" not in dry, dry
    assert "schedulingPreserved" not in dry, dry

    # FORCED-FALSE ALARM: rig the write path to unsuspend mid-call; the
    # booleans must be computed from the collection, never hardcoded true
    nd = add_basic("VC3", "d rig", "old")
    cid_d = col.card_ids_of_note(nd.id)[0]
    core.bulk_suspend(col, [cid_d], suspend=True)
    assert col.get_card(cid_d).queue == -1
    rig_bridge = make_bridge(plus, UnsuspendRig(col))
    r = rig_bridge.bulkUpdateNoteFields([{"id": nd.id, "fields": {"Back": "rigged"}}])
    assert r["updated"] == [nd.id], r
    assert r["suspensionPreserved"] is False, \
        "the alarm did not fire on a mid-call unsuspension: %r" % (r,)
    assert r["schedulingPreserved"] is False, \
        "queue is part of the scheduling triple; a flip must trip both: %r" % (r,)
    assert col.get_card(cid_d).queue == 0, "rig failed to move the card"

    # same alarm through bulkReplaceInFields
    ne = add_basic("VC3", "e rig rig", "old")
    cid_e = col.card_ids_of_note(ne.id)[0]
    core.bulk_suspend(col, [cid_e], suspend=True)
    r = rig_bridge.bulkReplaceInFields(noteIds=[ne.id], field="Front",
                                       find="rig", replace="fix")
    assert r["changed"] == [ne.id], r
    assert r["suspensionPreserved"] is False, r
    assert r["schedulingPreserved"] is False, r


# ===========================================================================
# 4 — §31.4 dry-run parity: renameTag notesUpdated, renameDeck
#     configWillBePreserved (against a real non-default preset)
# ===========================================================================
def test4_dry_run_parity():
    plus = load_plus()
    bridge = make_bridge(plus, col)

    # a note carrying TWO affected tags must count ONCE
    n1 = add_basic("VC4", "t1", tags=["vt::a", "vt::b"])
    n2 = add_basic("VC4", "t2", tags=["vt::a"])
    n3 = add_basic("VC4", "t3", tags=["vt"])
    n4 = add_basic("VC4", "t4", tags=["vt10"])  # segment guard: never counted
    dry = bridge.renameTag("vt", "vtx", dryRun=True)
    assert dry["notesUpdated"] == 3, dry
    assert dry["undoEntry"] is None, dry
    real = bridge.renameTag("vt", "vtx")
    assert real["notesUpdated"] == dry["notesUpdated"], (dry, real)
    assert real["undoEntry"], real
    assert set(col.get_note(n1.id).tags) == {"vtx::a", "vtx::b"}, \
        col.get_note(n1.id).tags
    assert col.get_note(n3.id).tags == ["vtx"], col.get_note(n3.id).tags
    assert col.get_note(n4.id).tags == ["vt10"], "vt10 was rewritten"

    # renameDeck: assign a NON-default options preset so configPreserved is
    # a real observation, then dry (static key) and real (post-check key)
    did = col.decks.id("VDeckA::Kid")
    root_did = col.decks.id_for_name("VDeckA")
    conf = col.decks.add_config("contract-preset")
    conf_id = conf["id"]
    deck = col.decks.get(root_did)
    deck["conf"] = conf_id
    col.decks.save(deck)
    add_basic("VDeckA::Kid", "vd1")

    dry = bridge.renameDeck("VDeckA", "VDeckB", dryRun=True)
    assert dry["configWillBePreserved"] is True, dry
    assert "configPreserved" not in dry, dry
    assert dry["undoEntry"] is None, dry
    assert {p["from"] for p in dry["wouldRename"]} == {"VDeckA", "VDeckA::Kid"}, dry

    real = bridge.renameDeck("VDeckA", "VDeckB")
    assert "configWillBePreserved" not in real, real
    assert real["configPreserved"] is True, real
    # the post-check told the truth: same preset id, names moved, ids stable
    assert col.decks.get(root_did)["conf"] == conf_id
    assert col.decks.get(root_did)["name"] == "VDeckB"
    assert col.decks.id_for_name("VDeckB::Kid") == did


# ===========================================================================
# 5 — five 'preserves' claims verified empirically (one per action)
# ===========================================================================
def test5_preserves_claims_empirical():
    # (a) bulkUpdateNoteFields: a field edit leaves every EXISTING card row
    # byte-identical (scheduling, suspension, flags, deck, identity)
    n1 = add_basic("VC5", "p one", "old")
    cid1 = col.card_ids_of_note(n1.id)[0]
    col.sched.set_due_date([cid1], "5!")
    col.set_user_flag_for_cards(1, [cid1])
    before = rows_of(n1.id)
    r = core.bulk_update_note_fields(
        col, [{"id": n1.id, "fields": {"Back": "edited"}}])
    assert r["updated"] == [n1.id], r
    assert rows_of(n1.id) == before, \
        "a field edit moved existing card state: %r -> %r" % (before, rows_of(n1.id))

    # (b) bulkAddTags: scheduling untouched, card set does not grow
    before = rows_of(n1.id)
    r = core.bulk_add_tags(col, [n1.id], "contract::tagged")
    assert r["updated"] == [n1.id], r
    assert rows_of(n1.id) == before, "a tags-only update moved card state"
    assert len(rows_of(n1.id)) == len(before), "a tags-only update grew the card set"
    assert "contract::tagged" in col.get_note(n1.id).tags

    # (c) renameTag: the ENTIRE cards table untouched; sibling tags kept
    n2 = add_basic("VC5", "p two", tags=["pv::x", "keep::other"])
    cid2 = col.card_ids_of_note(n2.id)[0]
    col.sched.set_due_date([cid2], "3!")
    before_all = all_card_rows()
    r = core.rename_tag(col, "pv::x", "pv::y")
    assert r["notesUpdated"] == 1, r
    assert all_card_rows() == before_all, "renameTag touched the cards table"
    assert set(col.get_note(n2.id).tags) == {"pv::y", "keep::other"}, \
        col.get_note(n2.id).tags

    # (d) deleteEmptyCards: deletes exactly the empty card; the surviving
    # card's scheduling untouched; the note is never deleted
    n3 = add_cloze("VC5", "{{c1::alpha}} {{c2::beta}}")
    cids3 = col.card_ids_of_note(n3.id)
    assert len(cids3) == 2
    col.sched.set_due_date([cids3[0]], "4!")
    note3 = col.get_note(n3.id)
    note3["Text"] = "{{c1::alpha}} beta"   # c2 card goes empty (fixture edit)
    col.update_note(note3)
    survivor_before = [row for row in rows_of(n3.id) if row[0] == cids3[0]]
    r = core.delete_empty_cards(col, note_ids=[n3.id])
    assert r["deletedCardIds"] == [cids3[1]], r
    assert r["cardsDeleted"] == 1, r
    assert r["notesPreserved"] is True, r
    survivor_after = [row for row in rows_of(n3.id) if row[0] == cids3[0]]
    assert survivor_after == survivor_before, \
        "deleteEmptyCards moved the surviving card's state"
    assert col.get_note(n3.id) is not None  # NotFoundError would fail the test

    # (e) bulkSetFlag: due/ivl (and everything else) untouched; only the
    # USER bits of the flags byte change — a pre-set non-user bit survives
    n4 = add_basic("VC5", "p four")
    cid4 = col.card_ids_of_note(n4.id)[0]
    col.sched.set_due_date([cid4], "6!")
    col.db.execute("update cards set flags = flags | 8 where id = ?", cid4)
    n5 = add_basic("VC5", "p five (control)")
    control_before = rows_of(n5.id)
    before = rows_of(n4.id)[0]
    r = core.bulk_set_flag(col, [cid4], 2)
    assert r["updated"] == [cid4], r
    after = rows_of(n4.id)[0]
    assert after[:-2] == before[:-2] and after[-1] == before[-1], \
        "bulkSetFlag touched more than the flags byte: %r -> %r" % (before, after)
    flags = after[-2]
    assert flags & 0b111 == 2, "user flag not set: %r" % flags
    assert flags & 8 == 8, "the non-user flag bit was clobbered: %r" % flags
    assert rows_of(n5.id) == control_before, "an untargeted card changed"


# ===========================================================================
# 6 — lockstep: version/revision constants, SPEC header, action count 34
# ===========================================================================
def test6_lockstep():
    assert core.PLUS_VERSION == "1.3.1", core.PLUS_VERSION
    assert core.PLUS_SPEC_REVISION == 18, core.PLUS_SPEC_REVISION

    with open(os.path.join(REPO, "SPEC.md"), encoding="utf-8") as handle:
        header = handle.readline() + handle.read(4096)
    assert "Version: 1.3.1 (spec revision 18" in header, \
        "SPEC.md header disagrees with core constants"

    assert len(core.PLUS_ACTIONS) == 34, len(core.PLUS_ACTIONS)
    assert len(set(core.PLUS_ACTIONS)) == 34, "duplicate action names"

    plus = load_plus()
    info = stubbed_info(plus)
    assert info["version"] == "1.3.1", info["version"]
    assert info["specRevision"] == 18, info["specRevision"]
    assert info["actions"] == list(core.PLUS_ACTIONS)
    assert len(info["actions"]) == 34
    # every action is documented on the live surface; wrappers all exist
    for name in core.PLUS_ACTIONS:
        entry = info["actionDocs"][name]
        assert entry["summary"].strip(), name
        assert entry["returns"].strip(), name
        assert isinstance(entry["params"], str), name


def main():
    print("scratch: %s" % SCRATCH, flush=True)
    run("1 live stale-claim sweep + revision-16 split consistency",
        test1_live_stale_claim_sweep)
    run("2 effectiveConfig honest sources + call-time resolution",
        test2_effective_config)
    run("3 preservation post-checks + forced-false alarm",
        test3_postchecks_and_alarm)
    run("4 dry-run parity: renameTag count, renameDeck config keys",
        test4_dry_run_parity)
    run("5 preserves claims verified empirically (5 actions)",
        test5_preserves_claims_empirical)
    run("6 version/revision/action-count lockstep", test6_lockstep)

    col.close()
    failures = [name for name, ok, _ in RESULTS if not ok]
    print("%d/%d passed" % (len(RESULTS) - len(failures), len(RESULTS)), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
