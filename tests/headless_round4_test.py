# Headless verification for SPEC 28 — the round-4 maintenance actions
# (spec revision 17):
#
#   * renameDeck  (28.1) — whole-subtree in-place rename; presets/desc/collapse
#                          survive (post-checked, not assumed); [duplicate]
#                          refusal instead of the backend's silent auto-rename
#   * bulkSetFlag (28.2) — set/clear card flags; updated/unchanged split from
#                          the cards' REAL pre-op flags
#   * renameTag   (28.3) — segment-aware subtree rename on col.tags.rename;
#                          lab1 -> lab01 never touches lab10 (THE lock)
#
# All three: one merged undo entry, undoLabel, dryRun with a bit-identical
# undo snapshot, house '[code] ' errors.
#
# Run with: <anki-venv>/bin/python headless_round4_test.py
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
SCRATCH = (os.environ.get("ANCP_TEST_SCRATCH")
           or tempfile.mkdtemp(prefix="ancp_r4_"))
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

col = Collection(os.path.join(SCRATCH, "r4.anki2"))

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
    return n.id


def undo_snap():
    return col.undo_status().SerializeToString()


def deck_name(did):
    return col.decks.get(did, default=False)["name"]


def code_of(fn):
    try:
        fn()
    except Exception as err:
        msg = str(err)
        assert msg.startswith("["), "unprefixed error: %r" % msg
        return msg.split("] ", 1)[0].lstrip("[")
    raise AssertionError("expected an exception")


def _load_plus():
    pkg_name = "ancp_r4_pkg"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [os.path.join(REPO, "connect_plus")]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg
    return importlib.import_module(pkg_name + ".plus")


# ============================================================================
# 1 — renameDeck: whole subtree, ONE undo entry, presets/desc survive and are
#     POST-CHECKED, single undo restores every name
# ============================================================================
def test1_rename_deck_subtree_preserves_config():
    a = col.decks.id("R1A")
    b = col.decks.id("R1A::Child")
    g = col.decks.id("R1A::Child::Grand")
    conf = col.decks.add_config("R4Preset")
    d = col.decks.get(b, default=False)
    col.decks.set_config_id_for_deck_dict(d, conf["id"])
    d = col.decks.get(b, default=False)
    d["desc"] = "child description"
    col.decks.save(d)
    add_note("R1A", "r1-a")
    add_note("R1A::Child", "r1-c")

    r = core.rename_deck(col, "R1A", "R1B")
    assert r["renamed"] == [
        {"from": "R1A", "to": "R1B"},
        {"from": "R1A::Child", "to": "R1B::Child"},
        {"from": "R1A::Child::Grand", "to": "R1B::Child::Grand"},
    ], r
    assert r["configPreserved"] is True, r
    assert r["cardsAffected"] == 2, r
    assert r["undoEntry"] == core.UNDO_RENAME_DECK, r

    # the post-check is honest: the preset id REALLY survived, desc too
    post = col.decks.get(b, default=False)
    assert post["conf"] == conf["id"], (post["conf"], conf["id"])
    assert post["desc"] == "child description", post
    # ids stable
    assert deck_name(a) == "R1B" and deck_name(g) == "R1B::Child::Grand"

    # ONE entry; a single undo restores every name
    assert col.undo_status().undo == core.UNDO_RENAME_DECK
    col.undo()
    assert deck_name(a) == "R1A"
    assert deck_name(b) == "R1A::Child"
    assert deck_name(g) == "R1A::Child::Grand"
    assert col.decks.get(b, default=False)["conf"] == conf["id"]


# ============================================================================
# 2 — renameDeck dryRun: prediction matches the real run, zero writes
# ============================================================================
def test2_rename_deck_dry_run():
    col.decks.id("R2A::Sub")
    before = undo_snap()
    dry = core.rename_deck(col, "R2A", "R2B", dry_run=True)
    assert undo_snap() == before, "dry run touched the undo stack"
    assert dry == {"wouldRename": [{"from": "R2A", "to": "R2B"},
                                   {"from": "R2A::Sub", "to": "R2B::Sub"}],
                   "configWillBePreserved": True,
                   "cardsAffected": 0, "undoEntry": None}, dry
    assert col.decks.id_for_name("R2B") is None, "dry run renamed the deck"

    real = core.rename_deck(col, "R2A", "R2B")
    assert real["renamed"] == dry["wouldRename"], (real, dry)
    assert real["cardsAffected"] == dry["cardsAffected"]


# ============================================================================
# 3 — renameDeck refusals: [duplicate] (root and via-descendant), byte-
#     identical no-op, [deck_not_found], invalid params — all before any write
# ============================================================================
def test3_rename_deck_refusals():
    col.decks.id("R3A::Kid")
    col.decks.id("R3Occupied")
    # R3Other will exist because anki auto-creates it as R3Other::Kid's parent
    col.decks.id("R3Other::Kid")
    before = undo_snap()

    assert code_of(lambda: core.rename_deck(col, "R3A", "R3Occupied")) == "duplicate"
    # dry path refuses identically (SPEC 15 shared-validation invariant)
    assert code_of(lambda: core.rename_deck(col, "R3A", "R3Occupied",
                                            dry_run=True)) == "duplicate"
    # a collision reached through a DESCENDANT's implied name
    assert code_of(lambda: core.rename_deck(col, "R3A", "R3Other")) == "duplicate"

    # fix pass: a newName equal to an existing DESCENDANT of the renamed deck
    # is refused too (pairwise self-identity) — the old subtree-membership
    # exemption let this ride the backend's silent ensure-unique auto-'+'
    # ('R3A::Kid+') while the dry run predicted 'R3A::Kid'
    assert code_of(lambda: core.rename_deck(col, "R3A", "R3A::Kid")) == "duplicate"
    assert code_of(lambda: core.rename_deck(col, "R3A", "R3A::Kid",
                                            dry_run=True)) == "duplicate"

    assert code_of(lambda: core.rename_deck(col, "NoSuchDeck", "X")) == "deck_not_found"
    assert code_of(lambda: core.rename_deck(col, "R3A", "")) == "invalid_param"
    assert code_of(lambda: core.rename_deck(col, "", "X")) == "invalid_param"
    assert code_of(lambda: core.rename_deck(col, "R3A", "X",
                                            dry_run="false")) == "invalid_param"

    # fix pass: un-normalized newName refused up front on BOTH paths — the
    # backend silently strips padding and fills empty components ('blank'),
    # which would make the dry-run's string-math prediction a lie (SPEC 15)
    for bad in ("R3B ", " R3B", "R3B::", "::R3B", "R3B:: ::C"):
        assert code_of(lambda b=bad: core.rename_deck(col, "R3A", b)) == \
            "invalid_param", bad
        assert code_of(lambda b=bad: core.rename_deck(col, "R3A", b,
                                                      dry_run=True)) == \
            "invalid_param", bad

    # byte-identical newName: data no-op
    r = core.rename_deck(col, "R3A", "R3A")
    assert r == {"renamed": [], "configPreserved": True, "cardsAffected": 0,
                 "undoEntry": None}, r

    assert undo_snap() == before, "a refused/no-op rename touched the undo stack"
    assert deck_name(col.decks.id_for_name("R3A::Kid")) == "R3A::Kid"


# ============================================================================
# 4 — renameDeck: case-only rename is a real rename (no '+' suffix), and a
#     rename under an existing parent is a move; undoLabel honored
# ============================================================================
def test4_rename_deck_case_move_label():
    did = col.decks.id("r4case")
    r = core.rename_deck(col, "r4case", "R4CASE")
    assert r["renamed"] == [{"from": "r4case", "to": "R4CASE"}], r
    assert deck_name(did) == "R4CASE"

    col.decks.id("R4Parent")
    r = core.rename_deck(col, "R4CASE", "R4Parent::R4CASE",
                         undo_label="move under parent")
    assert r["undoEntry"] == "AnkiConnect Plus: move under parent", r
    assert deck_name(did) == "R4Parent::R4CASE"
    assert col.undo_status().undo == "AnkiConnect Plus: move under parent"
    col.undo()
    assert deck_name(did) == "R4CASE"

    # fix pass: CLEAN self-nesting stays legal under the pairwise-identity
    # duplicate check — no existing 'R4Nest::Inner', so every predicted
    # target resolves to None and the backend recreates the missing parent
    nest = col.decks.id("R4Nest")
    r = core.rename_deck(col, "R4Nest", "R4Nest::Inner")
    assert r["renamed"] == [{"from": "R4Nest", "to": "R4Nest::Inner"}], r
    assert deck_name(nest) == "R4Nest::Inner"


# ============================================================================
# 5 — bulkSetFlag: set/split/clear, dedupe + unknown ids dropped, repeat is a
#     reported no-op with the undo stack untouched, single undo restores
# ============================================================================
def test5_bulk_set_flag():
    n1 = add_note("R5", "f1")
    n2 = add_note("R5", "f2")
    c1 = col.card_ids_of_note(n1)[0]
    c2 = col.card_ids_of_note(n2)[0]

    r = core.bulk_set_flag(col, [c1, c2, c1, 999], 2)
    assert r == {"updated": [c1, c2], "unchanged": [],
                 "undoEntry": core.UNDO_BULK_FLAG}, r
    assert col.get_card(c1).user_flag() == 2 and col.get_card(c2).user_flag() == 2

    # repeat: pure no-op — reported, nothing written, undo stack untouched
    before = undo_snap()
    r = core.bulk_set_flag(col, [c1, c2], 2)
    assert r == {"updated": [], "unchanged": [c1, c2], "undoEntry": None}, r
    assert undo_snap() == before

    # partial split from REAL current values
    r = core.bulk_set_flag(col, [c1, c2], 5)
    assert r["updated"] == [c1, c2] and r["unchanged"] == []
    r = core.bulk_set_flag(col, [c1], 5)
    assert r == {"updated": [], "unchanged": [c1], "undoEntry": None}, r

    # single undo restores the previous flags (5 -> 2)
    assert col.undo_status().undo == core.UNDO_BULK_FLAG
    col.undo()
    assert col.get_card(c1).user_flag() == 2, col.get_card(c1).user_flag()

    # clear (flag 0) — the inbox-emptying move the round-4 report asked for
    r = core.bulk_set_flag(col, [c1, c2], 0)
    assert r["updated"] == [c1, c2], r
    assert col.get_card(c1).user_flag() == 0 and col.get_card(c2).user_flag() == 0


# ============================================================================
# 6 — bulkSetFlag: dryRun zero-write prediction; validation before any write
# ============================================================================
def test6_bulk_set_flag_dry_and_validation():
    n = add_note("R6", "f3")
    cid = col.card_ids_of_note(n)[0]
    core.bulk_set_flag(col, [cid], 1)

    before = undo_snap()
    dry = core.bulk_set_flag(col, [cid, 999], 4, dry_run=True)
    assert dry == {"wouldUpdate": [cid], "unchanged": [], "undoEntry": None}, dry
    assert undo_snap() == before
    assert col.get_card(cid).user_flag() == 1, "dry run wrote a flag"
    real = core.bulk_set_flag(col, [cid, 999], 4)
    assert real["updated"] == dry["wouldUpdate"], (real, dry)

    before = undo_snap()
    for bad in (8, -1, True, "2", None):
        assert code_of(lambda b=bad: core.bulk_set_flag(col, [cid], b)) == "invalid_param"
    assert code_of(lambda: core.bulk_set_flag(col, "nope", 2)) == "invalid_param"
    assert code_of(lambda: core.bulk_set_flag(col, [cid], 2,
                                              dry_run="yes")) == "invalid_param"
    assert undo_snap() == before
    assert col.get_card(cid).user_flag() == 4

    # empty/unknown-only input: the no-op shape
    assert core.bulk_set_flag(col, [999], 2) == \
        {"updated": [], "unchanged": [], "undoEntry": None}


# ============================================================================
# 7 — renameTag: THE prefix-safety lock — lab1 -> lab01 rewrites lab1 and
#     lab1::* (case-insensitively) and NEVER lab10; one undo restores
# ============================================================================
def test7_rename_tag_prefix_safety():
    t1 = add_note("R7", "t1", ["x::lab1"])
    t2 = add_note("R7", "t2", ["x::lab1::sub"])
    t3 = add_note("R7", "t3", ["x::lab10"])
    t4 = add_note("R7", "t4", ["X::LAB1"])  # registry-matched to x::lab1
    lab10_row = col.db.first("select tags from notes where id = ?", t3)

    before = undo_snap()
    dry = core.rename_tag(col, "x::lab1", "x::lab01", dry_run=True)
    # the preview lists the exact pairs — and NOT lab10 (the whole point)
    assert dry == {"notesUpdated": 3,
                   "wouldRewrite": [{"from": "x::lab1", "to": "x::lab01"},
                                    {"from": "x::lab1::sub", "to": "x::lab01::sub"}],
                   "merged": [], "undoEntry": None}, dry
    assert not any("lab10" in p["from"] for p in dry["wouldRewrite"])
    assert undo_snap() == before, "dry run touched the undo stack"

    r = core.rename_tag(col, "x::lab1", "x::lab01")
    # backend's own count: t1 + t2 + t4 (case-insensitive), never t3
    assert r["notesUpdated"] == 3, r
    assert r["tagsRewritten"] == dry["wouldRewrite"], r
    assert r["merged"] == [] and r["undoEntry"] == core.UNDO_RENAME_TAG, r
    assert col.get_note(t1).tags == ["x::lab01"]
    assert col.get_note(t2).tags == ["x::lab01::sub"]
    assert col.get_note(t4).tags == ["x::lab01"]
    # lab10: byte-untouched row
    assert col.db.first("select tags from notes where id = ?", t3) == lab10_row
    assert "x::lab10" in col.tags.all()

    assert col.undo_status().undo == core.UNDO_RENAME_TAG
    col.undo()
    assert col.get_note(t1).tags == ["x::lab1"]
    assert col.get_note(t2).tags == ["x::lab1::sub"]
    # redo the rename so later tests see a stable registry
    core.rename_tag(col, "x::lab1", "x::lab01")


# ============================================================================
# 8 — renameTag: merge disclosure, [not_found], spacey newTag refused before
#     any write, byte-identical no-op, case-only rename, ghost-tag gate
# ============================================================================
def test8_rename_tag_edges():
    add_note("R8", "m1", ["r8::old"])
    add_note("R8", "m2", ["r8::new"])  # pre-existing target -> merge
    dry = core.rename_tag(col, "r8::old", "r8::new", dry_run=True)
    assert dry["merged"] == ["r8::new"], dry
    r = core.rename_tag(col, "r8::old", "r8::new")
    assert r["merged"] == ["r8::new"], r
    assert r["notesUpdated"] == 1 and r["tagsRewritten"] == \
        [{"from": "r8::old", "to": "r8::new"}], r

    before = undo_snap()
    assert code_of(lambda: core.rename_tag(col, "nosuchtag", "y")) == "not_found"
    assert code_of(lambda: core.rename_tag(col, "r8::new", "two words")) == "invalid_param"
    assert code_of(lambda: core.rename_tag(col, "two words", "y")) == "invalid_param"
    assert code_of(lambda: core.rename_tag(col, "r8::new", "")) == "invalid_param"
    assert code_of(lambda: core.rename_tag(col, "r8::new", "y",
                                           dry_run=1)) == "invalid_param"
    # byte-identical: data no-op
    assert core.rename_tag(col, "r8::new", "r8::new") == \
        {"notesUpdated": 0, "tagsRewritten": [], "merged": [], "undoEntry": None}
    assert undo_snap() == before, "a refused/no-op rename touched the undo stack"

    # case-only rename is a real rename and the registry shows the new spelling
    add_note("R8", "m3", ["casey"])
    r = core.rename_tag(col, "casey", "CASEY")
    assert r["notesUpdated"] == 1, r
    assert r["tagsRewritten"] == [{"from": "casey", "to": "CASEY"}], r
    assert "CASEY" in col.tags.all() and "casey" not in col.tags.all()

    # ghost gate: a registered tag carried by NO note is not renamed by the
    # backend; the report says so and the undo stack stays BIT-IDENTICAL
    # (no empty entry is created, so no phantom Redo item — SPEC 28.3)
    ghost = add_note("R8", "m4", ["ghost::one"])
    col.remove_notes([ghost])
    assert "ghost::one" in col.tags.all()
    before = undo_snap()
    r = core.rename_tag(col, "ghost", "spirit")
    assert r == {"notesUpdated": 0, "tagsRewritten": [], "merged": [],
                 "undoEntry": None}, r
    assert undo_snap() == before, "ghost rename left an undo artifact"
    assert "ghost::one" in col.tags.all()
    dry = core.rename_tag(col, "ghost", "spirit", dry_run=True)
    assert dry == {"notesUpdated": 0, "wouldRewrite": [], "merged": [],
                   "undoEntry": None}, dry


# ============================================================================
# 9 — undoLabel on bulkSetFlag/renameTag; a dry run with a label still
#     reports undoEntry null; bad labels raise before any write
# ============================================================================
def test9_undo_labels():
    n = add_note("R9", "l1", ["r9::tag"])
    cid = col.card_ids_of_note(n)[0]

    r = core.bulk_set_flag(col, [cid], 7, undo_label="clear the inbox")
    assert r["undoEntry"] == "AnkiConnect Plus: clear the inbox", r
    assert col.undo_status().undo == "AnkiConnect Plus: clear the inbox"

    r = core.rename_tag(col, "r9::tag", "r9::done", undo_label="tag sweep")
    assert r["undoEntry"] == "AnkiConnect Plus: tag sweep", r
    assert col.undo_status().undo == "AnkiConnect Plus: tag sweep"

    before = undo_snap()
    dry = core.bulk_set_flag(col, [cid], 3, dry_run=True, undo_label="dry label")
    assert dry["undoEntry"] is None
    assert undo_snap() == before
    assert code_of(lambda: core.bulk_set_flag(col, [cid], 3,
                                              undo_label="   ")) == "invalid_param"
    assert code_of(lambda: core.rename_deck(col, "R9", "R9X",
                                            undo_label=7)) == "invalid_param"
    assert undo_snap() == before


# ============================================================================
# 10 — lockstep surface: PLUS_ACTIONS/summaries/returns carry the three, the
#      real plus.py wrappers dispatch them with the SPEC 28 signatures, and
#      'duplicate' is documented reachable
# ============================================================================
def test10_lockstep_and_wrappers():
    for name in ("renameDeck", "bulkSetFlag", "renameTag"):
        assert name in core.PLUS_ACTIONS, name
        assert core.PLUS_ACTION_SUMMARIES[name].strip(), name
        assert core.PLUS_ACTION_RETURNS[name].startswith("{"), name
    # 36 -> 37: revision-20 SPEC 33 adds ankihubStageOptionalTagSuggestion
    assert len(core.PLUS_ACTIONS) == 37, len(core.PLUS_ACTIONS)
    assert core.PLUS_ACTIONS[-1] == "plusInfo"
    assert core.UNDO_RENAME_DECK == "AnkiConnect Plus: Rename Deck"
    assert core.UNDO_BULK_FLAG == "AnkiConnect Plus: Bulk Flag"
    assert core.UNDO_RENAME_TAG == "AnkiConnect Plus: Rename Tag"
    # revision 17: the occupied-name refusal made 'duplicate' reachable
    assert core.PLUS_ERROR_CODE_DOCS["duplicate"]["reachable"] is True
    assert core.PLUS_ERROR_CODES["duplicate"] is False  # still not retryable
    assert "37 Plus actions" in core.PLUS_ERROR_PREFIX_NOTE

    plus = _load_plus()
    util_mod = sys.modules["ancp_r4_pkg.util"]
    orig = util_mod.setting
    try:
        util_mod.setting = lambda key: util_mod.DEFAULT_CONFIG[key]
        info = plus.PlusMixin().plusInfo()
    finally:
        util_mod.setting = orig
    docs = info["actionDocs"]
    assert docs["renameDeck"]["params"] == \
        "oldName, newName, dryRun=false, undoLabel=null", docs["renameDeck"]
    assert docs["bulkSetFlag"]["params"] == \
        "cardIds, flag, dryRun=false, undoLabel=null", docs["bulkSetFlag"]
    assert docs["renameTag"]["params"] == \
        "oldTag, newTag, dryRun=false, undoLabel=null", docs["renameTag"]
    assert "lab10" in docs["renameTag"]["returns"]

    # end-to-end through the real wrapper: the '[code] ' envelope holds
    class Inst(plus.PlusMixin):
        def collection(self):
            return col

    inst = Inst()
    col.decks.id("R10Wrap")
    r = inst.renameDeck(oldName="R10Wrap", newName="R10Wrapped")
    assert r["renamed"] == [{"from": "R10Wrap", "to": "R10Wrapped"}], r
    try:
        inst.renameTag(oldTag="definitely::missing", newTag="x")
        raise AssertionError("expected an exception")
    except Exception as e:
        assert str(e) == "[not_found] tag was not found: definitely::missing", str(e)

    # docs artifacts name the three actions (README table + SPEC 28)
    readme = open(os.path.join(REPO, "README.md"), encoding="utf-8").read()
    spec_text = open(os.path.join(REPO, "SPEC.md"), encoding="utf-8").read()
    for name in ("renameDeck", "bulkSetFlag", "renameTag"):
        assert "`%s`" % name in readme, "README does not document %s" % name
    assert "## 28." in spec_text, "SPEC 28 missing"


# ================================================================ run
run("test1_rename_deck_subtree_preserves_config",
    test1_rename_deck_subtree_preserves_config)
run("test2_rename_deck_dry_run", test2_rename_deck_dry_run)
run("test3_rename_deck_refusals", test3_rename_deck_refusals)
run("test4_rename_deck_case_move_label", test4_rename_deck_case_move_label)
run("test5_bulk_set_flag", test5_bulk_set_flag)
run("test6_bulk_set_flag_dry_and_validation", test6_bulk_set_flag_dry_and_validation)
run("test7_rename_tag_prefix_safety", test7_rename_tag_prefix_safety)
run("test8_rename_tag_edges", test8_rename_tag_edges)
run("test9_undo_labels", test9_undo_labels)
run("test10_lockstep_and_wrappers", test10_lockstep_and_wrappers)

col.close()

failed = [name for name, ok, _tb in RESULTS if not ok]
print()
print("%d/%d passed" % (len(RESULTS) - len(failed), len(RESULTS)))
if failed:
    print("FAILED:", ", ".join(failed))
    sys.exit(1)
