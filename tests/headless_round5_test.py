# Headless verification for SPEC 31 — spec revision 18 (round-5 field feedback).
#
#   1. The stale-default sweep: no actionDocs text claims the revision-15
#      defaults; the corrected bulkAddNotes returns doc speaks config-language
#      and points at effectiveConfig; the two swept SPEC lines are fixed.
#   2. PLUS_ACTION_PRESERVES lockstep: exactly the side-effectful subset,
#      served by plusInfo only for those actions.
#   3. The §31.1 probe claims re-verified LIVE: suspend keeps filtered-deck
#      residency, set_due_date evicts, a cloze-adding field edit leaves
#      existing card rows byte-identical, a tags-only update moves nothing.
#   4. The §31.2 post-checks: present + true on real runs (zero-write batches
#      included), ABSENT on dry runs, and honestly FALSE when a rigged
#      collection moves cards during the write.
#   5. The §31.4 dry-run gaps: renameTag dry notesUpdated predicts the real
#      backend count; renameDeck dry configWillBePreserved is the static true.
#   6. effectiveConfig: value+source through the same ladder the writes use,
#      against a FAITHFUL aqt model (getConfig = shipped config.json merged
#      under user meta.json keys; addonMeta = the user store alone) —
#      headless/no-mw, VIRGIN-install, user-config, partial, absent-key and
#      non-boolean-typo paths.
#
# Run with: <anki-venv>/bin/python headless_round5_test.py
#
# Uses a FRESH scratch collection; never touches ~/Library/Application Support/Anki2/.

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
SCRATCH = (os.environ.get("ANCP_R5_SCRATCH")
           or tempfile.mkdtemp(prefix="ancp_r5_"))
CORE_PATH = os.path.join(REPO, "connect_plus", "core.py")

assert not SCRATCH.startswith(os.path.expanduser("~/Library")), \
    "scratch dir must not be under ~/Library"
assert "Anki2" not in SCRATCH

if os.path.exists(SCRATCH):
    shutil.rmtree(SCRATCH)
os.makedirs(SCRATCH)

# load core.py standalone (no package __init__, no aqt) and verify purity
spec = importlib.util.spec_from_file_location("core", CORE_PATH)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
assert "aqt" not in sys.modules, "core.py (or its imports) pulled in aqt"

import anki.lang
anki.lang.set_lang("en_US")
from anki.collection import Collection
from anki.decks import DeckId

col = Collection(os.path.join(SCRATCH, "r5.anki2"))

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


def card_rows(nid):
    return col.db.all(
        "select id, did, odid, queue, type, due, ivl from cards where nid = ? order by ord",
        nid)


def mkfilter(name, search):
    f = col.sched.get_or_create_filtered_deck(DeckId(0))
    f.config.search_terms[0].search = search
    f.name = name
    return col.sched.add_or_update_filtered_deck(f).id


def _load_plus():
    pkg_name = "ancp_r5_pkg"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [os.path.join(REPO, "connect_plus")]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg
    return importlib.import_module(pkg_name + ".plus")


# The side-effectful subset of PLUS_ACTIONS: every action that writes the
# collection, writes files, or submits to a server. The complement is the
# read-only set, whose actionDocs must NOT carry 'preserves'.
SIDE_EFFECTFUL = {
    "bulkAddNotes", "bulkUpdateNoteFields", "bulkAddTags",
    "addImageOcclusionNote", "updateImageOcclusionNote",
    "cropImage", "cropImageOcclusionImage", "storeMediaFilesBulk",
    "bulkSuspend", "bulkSetDueDate", "bulkReplaceInFields",
    "renameDeck", "bulkSetFlag", "renameTag",
    "emptyFilteredDeck", "deleteEmptyCards",
    "createFilteredDeck", "rebuildFilteredDeck",
    "createBackup", "exportDeckApkg", "syncNow",
    "ankihubSuggestNoteUpdate", "ankihubSuggestNewNote",
    # revision-20 SPEC 33: writes the staged notes' tag lists locally
    "ankihubStageOptionalTagSuggestion",
}


# ============================================================================
# 1 — the stale-default sweep (ITEM 1a + 1c): the revision-15 leftovers are
#     gone from every doc surface, and the fixed lines speak config-language
# ============================================================================
def test1_stale_default_sweep():
    # the exact leftover the round-5 report tripped over
    bad = core.PLUS_ACTION_RETURNS["bulkAddNotes"]
    assert "defaults to true" not in bad, bad
    assert "normally returns" not in bad, bad
    assert "suspendNewCards" in bad and "SHIPS false" in bad, bad
    assert "effectiveConfig" in bad, bad

    # sweep EVERY summary and returns sketch for revision-15 default claims.
    # "SHIPS true" stays legal — preserveSuspendedOnReschedule really does.
    forbidden = ("defaults to true", "defaults to TRUE",
                 "normally returns a non-empty")
    for registry in (core.PLUS_ACTION_SUMMARIES, core.PLUS_ACTION_RETURNS):
        for name, text in registry.items():
            for phrase in forbidden:
                assert phrase not in text, (name, phrase)

    # the two summaries point at effectiveConfig
    assert "effectiveConfig" in core.PLUS_ACTION_SUMMARIES["bulkAddNotes"]
    assert "effectiveConfig" in core.PLUS_ACTION_SUMMARIES["bulkSetDueDate"]
    # ...and plusInfo's own discovery summary names the revision-18 surfaces
    # (round-5 review: a caller reading only summaries must learn both exist)
    assert "effectiveConfig" in core.PLUS_ACTION_SUMMARIES["plusInfo"]
    assert "preserves" in core.PLUS_ACTION_SUMMARIES["plusInfo"]
    # ...and bulkSetDueDate's summary no longer states a bare non-config TRUE
    assert "defaults to config key 'preserveSuspendedOnReschedule'" in \
        core.PLUS_ACTION_SUMMARIES["bulkSetDueDate"]

    # the suspended-draft recipe teaches effectiveConfig
    recipe = next(r for r in core.PLUS_RECIPES
                  if r["name"] == "suspended-draft workflow")
    assert "effectiveConfig" in recipe["description"], recipe["description"]

    # the two swept SPEC lines: §27.2's table row ships false, §15's ladder
    # ends false, and the old spellings are gone
    spec_text = open(os.path.join(REPO, "SPEC.md"), encoding="utf-8").read()
    assert "| `suspendNewCards` | `true` |" not in spec_text
    assert "config `suspendNewCards` → `true`" not in spec_text
    assert "## 31." in spec_text, "SPEC 31 missing"
    for token in ("effectiveConfig", "configWillBePreserved",
                  "suspensionPreserved", "schedulingPreserved"):
        assert token in spec_text, token

    # version/revision moved (revision-20 minor bump: new capability)
    assert core.PLUS_VERSION == "1.5.0", core.PLUS_VERSION
    assert core.PLUS_SPEC_REVISION == 20, core.PLUS_SPEC_REVISION

    # README + config.md name the new surfaces
    readme = open(os.path.join(REPO, "README.md"), encoding="utf-8").read()
    for token in ("effectiveConfig", "suspensionPreserved",
                  "schedulingPreserved", "configWillBePreserved"):
        assert token in readme, "README missing %s" % token
    config_md = open(os.path.join(REPO, "connect_plus", "config.md"),
                     encoding="utf-8").read()
    assert "effectiveConfig" in config_md


# ============================================================================
# 2 — PLUS_ACTION_PRESERVES lockstep: exactly the side-effectful subset,
#     non-empty, key claims present, changeDeck (upstream) out of scope
# ============================================================================
def test2_preserves_lockstep():
    assert set(core.PLUS_ACTION_PRESERVES) == SIDE_EFFECTFUL, \
        sorted(set(core.PLUS_ACTION_PRESERVES) ^ SIDE_EFFECTFUL)
    assert set(core.PLUS_ACTION_PRESERVES) <= set(core.PLUS_ACTIONS)
    for name, text in core.PLUS_ACTION_PRESERVES.items():
        assert isinstance(text, str) and text.strip(), name

    # the probe-backed claims are actually stated
    assert "filtered" in core.PLUS_ACTION_PRESERVES["bulkSuspend"], \
        "bulkSuspend must state filtered-deck residency survives"
    assert "home" in core.PLUS_ACTION_PRESERVES["bulkSetDueDate"], \
        "bulkSetDueDate must state the filtered-deck eviction"
    assert "cloze" in core.PLUS_ACTION_PRESERVES["bulkUpdateNoteFields"]
    assert "cloze" in core.PLUS_ACTION_PRESERVES["bulkReplaceInFields"]
    assert "RENAMED" in core.PLUS_ACTION_PRESERVES["ankihubSuggestNoteUpdate"]
    assert core.PLUS_ACTION_PRESERVES["ankihubSuggestNoteUpdate"] == \
        core.PLUS_ACTION_PRESERVES["ankihubSuggestNewNote"]
    assert "FULL sync" in core.PLUS_ACTION_PRESERVES["syncNow"]

    # upstream stock actions are out of scope (SPEC 31.2 scope note)
    assert "changeDeck" not in core.PLUS_ACTION_PRESERVES
    # read-only actions never carry an entry
    for name in ("notesSlim", "renderCard", "queryRevlog", "undoStatus",
                 "filteredDeckReport", "getEmptyCards", "plusInfo",
                 "syncStatus", "ankihubStatus", "checkDeckIntegrity",
                 "mediaExists", "mediaThumbnails", "getImageOcclusionNote"):
        assert name not in core.PLUS_ACTION_PRESERVES, name


# ============================================================================
# 3 — the §31.1 probe claims, LIVE (the same probes that justified the text)
# ============================================================================
def test3_preserves_claims_probed_live():
    # (a) bulkSuspend keeps filtered-deck residency: only queue changes
    n1 = add_basic("R5P1", "p1")
    cid1 = col.card_ids_of_note(n1.id)[0]
    col.sched.set_due_date([cid1], "0")   # review card so the filter pulls it
    fid1 = mkfilter("R5P1F", "deck:R5P1")
    pre = card_rows(n1.id)[0]
    assert pre[1] == fid1 and pre[2] != 0, "fixture: card must sit in the filter"
    r = core.bulk_suspend(col, [cid1], suspend=True)
    assert r["changed"] == 1, r
    post = card_rows(n1.id)[0]
    assert post[1] == pre[1] and post[2] == pre[2], \
        "suspend moved the card out of the filtered deck: %r -> %r" % (pre, post)
    assert post[3] == core.QUEUE_SUSPENDED
    assert (post[5], post[6]) == (pre[5], pre[6]), "suspend touched due/ivl"
    col.undo()

    # (b) bulkSetDueDate EVICTS from the filtered deck (did=odid, odid=0)
    n2 = add_basic("R5P2", "p2")
    cid2 = col.card_ids_of_note(n2.id)[0]
    col.sched.set_due_date([cid2], "0")
    home_did = col.decks.id_for_name("R5P2")
    mkfilter("R5P2F", "deck:R5P2")
    pre = card_rows(n2.id)[0]
    assert pre[2] == home_did, "fixture: odid must be the home deck"
    r = core.bulk_set_due_date(col, [cid2], "5")
    assert r["changed"] == 1, r
    post = card_rows(n2.id)[0]
    assert post[1] == home_did and post[2] == 0, \
        "set_due_date no longer evicts from filtered decks: %r" % (post,)

    # (c) a cloze-adding field edit: existing card rows byte-identical, the
    #     new card appears in the note's own deck, post-checks report True
    n3 = add_cloze("R5P3", "{{c1::a}} {{c2::b}}")
    cids = col.card_ids_of_note(n3.id)
    col.sched.set_due_date([cids[0]], "7!")
    pre = card_rows(n3.id)
    r = core.bulk_update_note_fields(
        col, [{"id": n3.id, "fields": {"Text": "{{c1::a}} {{c2::b}} {{c3::c}}"}}])
    assert r["updated"] == [n3.id], r
    assert r["suspensionPreserved"] is True and r["schedulingPreserved"] is True, r
    post = card_rows(n3.id)
    assert len(post) == len(pre) + 1, "c3 card was not generated"
    assert post[:len(pre)] == pre, "existing card rows moved on a field edit"
    assert post[-1][1] == col.decks.id_for_name("R5P3"), "new card wrong deck"

    # (d) tags-only update: zero card movement
    pre = card_rows(n3.id)
    r = core.bulk_add_tags(col, [n3.id], "r5tag")
    assert r["updated"] == [n3.id], r
    assert card_rows(n3.id) == pre, "a tags-only update moved cards"


# ============================================================================
# 4 — §31.2 post-checks: present+true on real runs, absent on dry runs, and
#     honestly FALSE when the write path is rigged to move cards
# ============================================================================
class RiggedCol:
    """Delegates everything to the real collection, but moves the written
    note's cards right AFTER the action's undo merge completes (a raw db
    write inside update_note would invalidate the pending merge target) —
    the exact silent movement the post-check exists to catch."""

    SQL = "update cards set queue = -1, due = due + 500 where nid = ?"

    def __init__(self, real):
        self._real = real
        self._pending_nid = None

    def __getattr__(self, name):
        return getattr(self._real, name)

    def update_note(self, note):
        self._pending_nid = note.id
        return self._real.update_note(note)

    def merge_undo_entries(self, target):
        out = self._real.merge_undo_entries(target)
        if self._pending_nid is not None:
            self._real.db.execute(self.SQL, self._pending_nid)
            self._pending_nid = None
        return out


def test4_preservation_post_checks():
    # real run with writes: both keys present and true
    n1 = add_basic("R5Q", "q1", "old")
    r = core.bulk_update_note_fields(
        col, [{"id": n1.id, "fields": {"Back": "new"}}])
    assert r["suspensionPreserved"] is True, r
    assert r["schedulingPreserved"] is True, r

    # zero-write batch: keys still present (true — nothing moved nothing)
    r = core.bulk_update_note_fields(
        col, [{"id": n1.id, "fields": {"Back": "new"}}])
    assert r["updated"] == [] and r["unchanged"] == [n1.id], r
    assert r["suspensionPreserved"] is True and r["schedulingPreserved"] is True, r

    # dry runs carry NEITHER key (nothing written -> no fact to verify)
    dry = core.bulk_update_note_fields(
        col, [{"id": n1.id, "fields": {"Back": "newer"}}], dry_run=True)
    assert "suspensionPreserved" not in dry and "schedulingPreserved" not in dry, dry

    # bulkReplaceInFields: same contract
    n2 = add_basic("R5Q", "cat cat", "b")
    r = core.bulk_replace_in_fields(col, note_ids=[n2.id], field="Front",
                                    find="cat", replace="rat")
    assert r["changed"] == [n2.id], r
    assert r["suspensionPreserved"] is True and r["schedulingPreserved"] is True, r
    dry = core.bulk_replace_in_fields(col, note_ids=[n2.id], field="Front",
                                      find="rat", replace="mat", dry_run=True)
    assert "suspensionPreserved" not in dry and "schedulingPreserved" not in dry, dry

    # HONESTY: a rigged write that suspends + reschedules the note's cards
    # must be reported false on both booleans — never papered over
    n3 = add_basic("R5Q", "rig", "old")
    rig = RiggedCol(col)
    r = core.bulk_update_note_fields(
        rig, [{"id": n3.id, "fields": {"Back": "moved"}}])
    assert r["updated"] == [n3.id], r
    assert r["suspensionPreserved"] is False, r
    assert r["schedulingPreserved"] is False, r
    col.db.execute("update cards set queue = 0, due = due - 500 where nid = ?", n3.id)

    # rigged replace: same alarms
    n4 = add_basic("R5Q", "dog dog", "b")
    r = core.bulk_replace_in_fields(rig, note_ids=[n4.id], field="Front",
                                    find="dog", replace="fox")
    assert r["changed"] == [n4.id], r
    assert r["suspensionPreserved"] is False and r["schedulingPreserved"] is False, r
    col.db.execute("update cards set queue = 0, due = due - 500 where nid = ?", n4.id)

    # a due-only rig trips scheduling but NOT suspension (facet split)
    class DueRig(RiggedCol):
        SQL = "update cards set due = due + 77 where nid = ?"

    n5 = add_basic("R5Q", "facet", "old")
    r = core.bulk_update_note_fields(
        DueRig(col), [{"id": n5.id, "fields": {"Back": "moved"}}])
    assert r["suspensionPreserved"] is True, r
    assert r["schedulingPreserved"] is False, r
    col.db.execute("update cards set due = due - 77 where nid = ?", n5.id)


# ============================================================================
# 5 — §31.4 dry-run gaps: renameTag notesUpdated, renameDeck
#     configWillBePreserved
# ============================================================================
def test5_dry_run_gaps():
    # renameTag: dry notesUpdated predicts the real backend count
    t1 = add_basic("R5T", "t1", tags=["r5x::lab1"])
    t2 = add_basic("R5T", "t2", tags=["r5x::lab1::sub"])
    t3 = add_basic("R5T", "t3", tags=["r5x::lab10"])  # must never count
    t4 = add_basic("R5T", "t4", tags=["R5X::LAB1"])   # unicase match counts
    dry = core.rename_tag(col, "r5x::lab1", "r5x::lab01", dry_run=True)
    assert dry["notesUpdated"] == 3, dry
    assert set(dry) == {"notesUpdated", "wouldRewrite", "merged", "undoEntry"}, \
        sorted(dry)
    real = core.rename_tag(col, "r5x::lab1", "r5x::lab01")
    assert real["notesUpdated"] == dry["notesUpdated"], (real, dry)
    assert set(real) == {"notesUpdated", "tagsRewritten", "merged", "undoEntry"}, \
        sorted(real)
    assert col.get_note(t3.id).tags == ["r5x::lab10"], "lab10 was touched"

    # byte-identical no-op dry: notesUpdated 0
    dry = core.rename_tag(col, "r5x::lab01", "r5x::lab01", dry_run=True)
    assert dry == {"notesUpdated": 0, "wouldRewrite": [], "merged": [],
                   "undoEntry": None}, dry

    # all-ghost dry: notesUpdated 0 (registered, carried by no note — the
    # round-4 fixture: add a tagged note, then delete it; the registry keeps
    # the tag)
    ghost = add_basic("R5T", "ghost", tags=["r5ghost::only"])
    col.remove_notes([ghost.id])
    assert "r5ghost::only" in col.tags.all()
    dry = core.rename_tag(col, "r5ghost::only", "r5spirit", dry_run=True)
    assert dry["notesUpdated"] == 0 and dry["wouldRewrite"] == [], dry

    # renameDeck: dry carries the static configWillBePreserved: true; the
    # real run carries the post-check key instead
    col.decks.id("R5D::Sub")
    dry = core.rename_deck(col, "R5D", "R5E", dry_run=True)
    assert dry["configWillBePreserved"] is True, dry
    assert set(dry) == {"wouldRename", "configWillBePreserved",
                        "cardsAffected", "undoEntry"}, sorted(dry)
    real = core.rename_deck(col, "R5D", "R5E")
    assert "configWillBePreserved" not in real and real["configPreserved"] is True, real
    # byte-identical dry no-op: same key set, still true
    dry = core.rename_deck(col, "R5E", "R5E", dry_run=True)
    assert dry == {"wouldRename": [], "configWillBePreserved": True,
                   "cardsAffected": 0, "undoEntry": None}, dry


# ============================================================================
# 6 — effectiveConfig: resolved through the write actions' own ladder, with
#     honest sources against a FAITHFUL aqt getConfig/addonMeta model;
#     headless/no-mw, virgin-install, user-config, partial, absent-key, typo
# ============================================================================
def test6_effective_config():
    plus = _load_plus()
    util_mod = sys.modules["ancp_r5_pkg.util"]
    orig_setting = util_mod.setting
    orig_aqt = util_mod.aqt

    def entry_shape(info):
        eff = info["effectiveConfig"]
        assert set(eff) == {core.CONFIG_SUSPEND_NEW_CARDS,
                            core.CONFIG_PRESERVE_SUSPENDED}, sorted(eff)
        for row in eff.values():
            assert set(row) == {"value", "source"}, row
            assert isinstance(row["value"], bool), row
            assert row["source"] in ("user_config", "shipped_default"), row
        return eff

    try:
        # (a) headless with a readable DEFAULT_CONFIG (key not user-supplied):
        # shipped values, source shipped_default — aqt.mw is None here, so the
        # user-store probe cannot claim user_config
        util_mod.setting = lambda key: util_mod.DEFAULT_CONFIG[key]
        info = plus.PlusMixin().plusInfo()
        eff = entry_shape(info)
        assert eff[core.CONFIG_SUSPEND_NEW_CARDS] == \
            {"value": core.DEFAULT_SUSPEND_NEW_CARDS, "source": "shipped_default"}, eff
        assert eff[core.CONFIG_PRESERVE_SUSPENDED] == \
            {"value": core.DEFAULT_PRESERVE_SUSPENDED_ON_RESCHEDULE,
             "source": "shipped_default"}, eff

        # (b) TRUE no-mw path: util.setting raises -> shipped default values.
        # plusInfo reads apiVersion through util.setting too, so patch
        # setting selectively instead of raising for every key
        def selective(key):
            if key == "apiVersion":
                return util_mod.DEFAULT_CONFIG[key]
            raise Exception("setting %s not found" % key)
        util_mod.setting = selective
        eff = entry_shape(plus.PlusMixin().plusInfo())
        assert eff[core.CONFIG_SUSPEND_NEW_CARDS]["value"] is \
            core.DEFAULT_SUSPEND_NEW_CARDS
        assert eff[core.CONFIG_SUSPEND_NEW_CARDS]["source"] == "shipped_default"

        # From here on: the REAL accessor against a FAITHFUL aqt model.
        # aqt 25.09.4 aqt/addons.py: getConfig returns the shipped
        # config.json defaults with meta.json's user 'config' keys merged
        # OVER them; addonMeta returns the meta.json dict alone;
        # addonFromModule takes the module path's first segment. The round-5
        # review found the old stub (getConfig returning ONLY user keys) hid
        # a source-attribution blocker: this add-on SHIPS both SPEC-27 keys
        # in config.json, so a merged-view probe sees a boolean for every
        # key on every intact install and answered 'user_config'
        # unconditionally.
        with open(os.path.join(REPO, "connect_plus", "config.json"),
                  encoding="utf-8") as f:
            shipped = json.load(f)
        assert isinstance(shipped[core.CONFIG_SUSPEND_NEW_CARDS], bool)
        assert isinstance(shipped[core.CONFIG_PRESERVE_SUSPENDED], bool)
        meta = {}  # the meta.json dict; user config lives at meta["config"]

        def fake_get_config(name):
            merged = dict(shipped)
            merged.update(meta.get("config", {}))
            return merged

        util_mod.setting = orig_setting  # the real accessor, against the stub
        util_mod.aqt = types.SimpleNamespace(mw=types.SimpleNamespace(
            addonManager=types.SimpleNamespace(
                getConfig=fake_get_config,
                addonMeta=lambda addon: dict(meta),
                addonFromModule=lambda module: module.split(".")[0])))

        # (c) VIRGIN install — no meta.json user config at all. getConfig
        # still returns booleans for both keys (the shipped ones); the
        # source must say so: shipped values, shipped_default BOTH. This is
        # the decisive case the old only-user-keys stub could not express.
        meta.clear()
        eff = entry_shape(plus.PlusMixin().plusInfo())
        assert eff[core.CONFIG_SUSPEND_NEW_CARDS] == \
            {"value": shipped[core.CONFIG_SUSPEND_NEW_CARDS],
             "source": "shipped_default"}, eff
        assert eff[core.CONFIG_PRESERVE_SUSPENDED] == \
            {"value": shipped[core.CONFIG_PRESERVE_SUSPENDED],
             "source": "shipped_default"}, eff

        # (d) user config carries booleans -> user_config, and the value is
        # EXACTLY what a parameterless wrapper write would resolve
        meta["config"] = {"suspendNewCards": True,
                          "preserveSuspendedOnReschedule": False}
        eff = entry_shape(plus.PlusMixin().plusInfo())
        assert eff[core.CONFIG_SUSPEND_NEW_CARDS] == \
            {"value": True, "source": "user_config"}, eff
        assert eff[core.CONFIG_PRESERVE_SUSPENDED] == \
            {"value": False, "source": "user_config"}, eff
        # lockstep: the write path resolves the same values from None
        assert plus._resolve_suspension_param(
            None, core.CONFIG_SUSPEND_NEW_CARDS,
            core.DEFAULT_SUSPEND_NEW_CARDS) is True
        assert plus._resolve_suspension_param(
            None, core.CONFIG_PRESERVE_SUSPENDED,
            core.DEFAULT_PRESERVE_SUSPENDED_ON_RESCHEDULE) is False

        # (e) PARTIAL user config — one key user-set, the other only
        # shipped: attribution is per KEY, not per install (the review's
        # real-world case: meta.json = {"config": {"suspendNewCards": true}})
        meta["config"] = {"suspendNewCards": True}
        eff = entry_shape(plus.PlusMixin().plusInfo())
        assert eff[core.CONFIG_SUSPEND_NEW_CARDS] == \
            {"value": True, "source": "user_config"}, eff
        assert eff[core.CONFIG_PRESERVE_SUSPENDED] == \
            {"value": shipped[core.CONFIG_PRESERVE_SUSPENDED],
             "source": "shipped_default"}, eff

        # (f) key absent from user config (unrelated keys stored) -> the
        # merged value is the SHIPPED default, not a user choice
        meta["config"] = {"webBindPort": 8766}
        eff = entry_shape(plus.PlusMixin().plusInfo())
        assert eff[core.CONFIG_SUSPEND_NEW_CARDS] == \
            {"value": core.DEFAULT_SUSPEND_NEW_CARDS,
             "source": "shipped_default"}, eff

        # (g) non-boolean typo in the USER store -> resolution ignores it:
        # shipped value, shipped_default source (never user_config for a
        # value not used)
        meta["config"] = {"suspendNewCards": "yes"}
        eff = entry_shape(plus.PlusMixin().plusInfo())
        assert eff[core.CONFIG_SUSPEND_NEW_CARDS] == \
            {"value": core.DEFAULT_SUSPEND_NEW_CARDS,
             "source": "shipped_default"}, eff
        assert plus._resolve_suspension_param(
            None, core.CONFIG_SUSPEND_NEW_CARDS,
            core.DEFAULT_SUSPEND_NEW_CARDS) is core.DEFAULT_SUSPEND_NEW_CARDS
    finally:
        util_mod.setting = orig_setting
        util_mod.aqt = orig_aqt


# ============================================================================
# 7 — plusInfo serves the preserves surface: side-effectful actions verbatim,
#     read-only actions without the key
# ============================================================================
def test7_plusinfo_preserves_surface():
    plus = _load_plus()
    util_mod = sys.modules["ancp_r5_pkg.util"]
    orig = util_mod.setting
    try:
        util_mod.setting = lambda key: util_mod.DEFAULT_CONFIG[key]
        info = plus.PlusMixin().plusInfo()
    finally:
        util_mod.setting = orig
    docs = info["actionDocs"]
    for name in core.PLUS_ACTIONS:
        if name in SIDE_EFFECTFUL:
            assert docs[name].get("preserves") == \
                core.PLUS_ACTION_PRESERVES[name], name
            assert set(docs[name]) == {"summary", "params", "returns",
                                       "preserves"}, (name, sorted(docs[name]))
        else:
            assert "preserves" not in docs[name], name
            assert set(docs[name]) == {"summary", "params", "returns"}, \
                (name, sorted(docs[name]))
    # the returns sketches document the revision-18 keys
    assert "suspensionPreserved" in docs["bulkUpdateNoteFields"]["returns"]
    assert "suspensionPreserved" in docs["bulkReplaceInFields"]["returns"]
    assert "configWillBePreserved" in docs["renameDeck"]["returns"]
    assert "notesUpdated" in docs["renameTag"]["returns"]
    # plusInfo's own returns sketch names both new top-level surfaces
    assert "effectiveConfig" in docs["plusInfo"]["returns"]
    assert "preserves" in docs["plusInfo"]["returns"]


# ================================================================ run
run("test1_stale_default_sweep", test1_stale_default_sweep)
run("test2_preserves_lockstep", test2_preserves_lockstep)
run("test3_preserves_claims_probed_live", test3_preserves_claims_probed_live)
run("test4_preservation_post_checks", test4_preservation_post_checks)
run("test5_dry_run_gaps", test5_dry_run_gaps)
run("test6_effective_config", test6_effective_config)
run("test7_plusinfo_preserves_surface", test7_plusinfo_preserves_surface)

col.close()

failed = [name for name, ok, _tb in RESULTS if not ok]
print()
print("%d/%d passed" % (len(RESULTS) - len(failed), len(RESULTS)))
if failed:
    print("FAILED:", ", ".join(failed))
    sys.exit(1)
