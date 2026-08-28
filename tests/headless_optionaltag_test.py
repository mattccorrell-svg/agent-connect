# Headless verification for SPEC 33 — staged optional-tag suggestion
# (spec revision 20, v1.5.0): ankihubStageOptionalTagSuggestion.
#
# Run with: <anki-venv>/bin/python headless_optionaltag_test.py
#
# ZERO NETWORK and ZERO REAL ADD-ON IMPORTS by construction: the AnkiHub
# add-on package is FAKED in sys.modules (plus.py reaches add-on modules
# through importlib.import_module, which short-circuits on sys.modules).
# THE STAGING WORLDS SEED NO gui/ MODULE AT ALL — the trimmed action's
# contract is that it never imports anything from the add-on's gui/ package,
# so a green happy-path run against a fake with no gui modules IS the proof
# (an attempted import would fail -> [incompatible_ankihub_addon] -> red).
# The fake suggestion functions raise if ever CALLED: feature detection may
# only read their signatures. Uses a FRESH scratch collection; never touches
# ~/Library/Application Support/Anki2/.

import contextlib
import importlib
import importlib.util
import inspect
import json
import os
import shutil
import sys
import tempfile
import traceback
import types
import uuid as uuid_mod

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = (os.environ.get("ANCP_OPT_SCRATCH")
           or tempfile.mkdtemp(prefix="ancp_opt_"))
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
assert core.ANKIHUB_ADDON_PACKAGE not in sys.modules, \
    "core.py must never import the AnkiHub add-on"

import anki.lang
anki.lang.set_lang("en_US")
import anki.notes
from anki.collection import Collection

col = Collection(os.path.join(SCRATCH, "opt.anki2"))

PKG = "ancp_opt_pkg"


def load_plus():
    """connect_plus.plus as a REAL module through a synthetic package (the
    package __init__, which boots the add-on against aqt.mw, never runs)."""
    if PKG not in sys.modules:
        pkg = types.ModuleType(PKG)
        pkg.__path__ = [os.path.join(REPO, "connect_plus")]
        pkg.__package__ = PKG
        sys.modules[PKG] = pkg
    return importlib.import_module(PKG + ".plus")


plus = load_plus()
import aqt  # after the purity assert; plus.py already pulled it in

ADDON = core.ANKIHUB_ADDON_PACKAGE
DECK_UUID = uuid_mod.UUID("e77aedfe-a636-40e2-8169-2fce2673187e")
OTHER_UUID = uuid_mod.UUID("11111111-2222-3333-4444-555555555555")
TAG = "AnkiHub_Optional::BSOM::MCQ_03::PI_027_Pancreas"

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


def expect_raises(fn, fragment):
    try:
        fn()
    except Exception as e:
        assert fragment in str(e), "expected %r in %r" % (fragment, str(e))
        return e
    raise AssertionError("expected an exception containing %r" % fragment)


def add_note(front, tags=()):
    model = col.models.by_name("Basic")
    n = col.new_note(model)
    n["Front"] = front
    n["Back"] = "b"
    n.tags = list(tags)
    col.add_note(n, col.decks.id("OptStage"))
    return int(n.id)


def note_tags(nid):
    return list(col.get_note(anki.notes.NoteId(nid)).tags)


# ---------------------------------------------------------------------------
# Fake AnkiHub add-on harness. Every NON-GUI module plus.py's gui=False path
# imports is seeded in sys.modules; nothing real is touched, and NO module
# under <addon>.gui is seeded unless a test explicitly opts in (only the
# ankihubStatus compatibility check needs media_sync — status imports with
# gui=True). The fake suggestion functions RAISE if called — the stage
# action must never call an AnkiHub client method.
# ---------------------------------------------------------------------------

class Harness:
    def __init__(self, dids, logged_in=True):
        self.dids = list(dids)
        self.logged_in = logged_in
        self.client_calls = []     # any forbidden client call lands here


def _never(name, calls):
    def fn(*args, **kwargs):  # pragma: no cover - reaching this is the bug
        calls.append(name)
        raise AssertionError("AnkiHub client path %s must never be called "
                             "by the stage action" % name)
    return fn


def build_fake_modules(harness, include_gui=False, omit_db_module=False,
                       omit_dids_fn=False):
    import enum

    mods = {}

    suggestions = types.ModuleType(ADDON + ".main.suggestions")
    # exact tested signatures — feature detection reads these, never calls

    def suggest_note_update(note, change_type, comment, media_upload_cb,
                            auto_accept):
        raise AssertionError("suggest_note_update must not be called")

    def suggest_new_note(note, comment, ankihub_did, media_upload_cb,
                         auto_accept):
        raise AssertionError("suggest_new_note must not be called")

    def resubmit_new_note_as_change_suggestion(note, ah_did,
                                               conflicting_ah_nid,
                                               change_type, comment,
                                               auto_accept):
        raise AssertionError("resubmit must not be called")

    def has_empty_first_field(note):
        raise AssertionError("has_empty_first_field must not be called")

    def parse_duplicate_anki_id_error(errors):
        raise AssertionError("parse_duplicate_anki_id_error must not be called")

    class ChangeSuggestionResult(enum.Enum):
        SUCCESS = 1
        NO_CHANGES = 2
        ANKIHUB_NOT_FOUND = 3
        EMPTY_FIRST_FIELD = 4

    suggestions.suggest_note_update = suggest_note_update
    suggestions.suggest_new_note = suggest_new_note
    suggestions.resubmit_new_note_as_change_suggestion = \
        resubmit_new_note_as_change_suggestion
    suggestions.has_empty_first_field = has_empty_first_field
    suggestions.parse_duplicate_anki_id_error = parse_duplicate_anki_id_error
    suggestions.ChangeSuggestionResult = ChangeSuggestionResult
    mods[ADDON + ".main.suggestions"] = suggestions

    models = types.ModuleType(ADDON + ".ankihub_client.models")

    class SuggestionType(enum.Enum):
        UPDATED_CONTENT = ("updated_content", "Updated content")
        NEW_CONTENT = ("new_content", "New content")
        SPELLING_GRAMMAR = ("spelling/grammar", "Spelling/Grammar")
        CONTENT_ERROR = ("content_error", "Content error")
        NEW_CARD_TO_ADD = ("new_card_to_add", "New card to add")
        NEW_TAGS = ("new_tags", "New tags")
        UPDATED_TAGS = ("updated_tags", "Updated tags")
        DELETE = ("delete", "Delete")
        OTHER = ("other", "Other")

    models.SuggestionType = SuggestionType
    mods[ADDON + ".ankihub_client.models"] = models

    client = types.ModuleType(ADDON + ".ankihub_client.ankihub_client")

    class AnkiHubHTTPError(Exception):
        def __init__(self, response):
            super().__init__("http %s" % response.status_code)
            self.response = response

    class AnkiHubRequestException(Exception):
        pass

    client.AnkiHubHTTPError = AnkiHubHTTPError
    client.AnkiHubRequestException = AnkiHubRequestException
    mods[ADDON + ".ankihub_client.ankihub_client"] = client

    settings = types.ModuleType(ADDON + ".settings")
    settings.config = types.SimpleNamespace(
        is_logged_in=lambda: harness.logged_in,
        anking_deck_id=None,
        app_url="https://fake.invalid",
        deck_ids=lambda: [],
    )
    mods[ADDON + ".settings"] = settings

    if not omit_db_module:
        db = types.ModuleType(ADDON + ".db")
        database = types.SimpleNamespace(
            ankihub_nid_for_anki_nid=lambda nid: None,
            ankihub_did_for_anki_nid=lambda nid: None,
            ankihub_did_for_note_type=lambda mid: None,
        )
        if not omit_dids_fn:
            database.ankihub_dids_for_anki_nids = \
                lambda nids: list(harness.dids)
        db.ankihub_db = database
        mods[ADDON + ".db"] = db

    if include_gui:
        # ONLY for ankihubStatus (imports with gui=True). Staging worlds
        # never seed this: the trimmed action must never import gui/.
        media_sync = types.ModuleType(ADDON + ".gui.media_sync")
        media_sync.media_sync = types.SimpleNamespace(
            start_media_upload=_never("start_media_upload",
                                      harness.client_calls))
        mods[ADDON + ".gui.media_sync"] = media_sync

    mods[ADDON] = types.ModuleType(ADDON)
    return mods, client


class FakeAddonManager:
    def __init__(self, installed=True, enabled=True):
        self.installed = installed
        self.enabled = enabled

    def allAddons(self):
        return [ADDON] if self.installed else []

    def isEnabled(self, pkg):
        return self.enabled

    def addonsFolder(self, pkg):
        return os.path.join(SCRATCH, "no-such-addon-folder")


class FakeDialogManager:
    """The Browser seam: records aqt.dialogs.open calls (the ONLY window the
    trimmed action may open) and returns a sentinel."""

    def __init__(self):
        self.opens = []
        self.browsers = []

    def open(self, name, *args, **kwargs):
        self.opens.append((name, args, kwargs))
        browser = types.SimpleNamespace(kind="fake-browser")
        self.browsers.append(browser)
        return browser


def make_bridge(installed=True, enabled=True):
    mw = types.SimpleNamespace(addonManager=FakeAddonManager(installed, enabled))

    class Bridge(plus.PlusMixin):
        def collection(self):
            return col

        def window(self):
            return mw

    bridge = Bridge()
    bridge._fake_mw = mw
    return bridge


@contextlib.contextmanager
def fake_ankihub(harness, **build_kwargs):
    """Seed the fake add-on modules in sys.modules and patch aqt.dialogs;
    restore both on exit. plus.py's importlib.import_module short-circuits
    on sys.modules, so the real add-on is never touched."""
    mods, client = build_fake_modules(harness, **build_kwargs)
    for name in mods:
        assert name not in sys.modules, "real module already loaded: " + name
    sys.modules.update(mods)
    orig_dialogs = aqt.dialogs
    fake_dialogs = FakeDialogManager()
    aqt.dialogs = fake_dialogs
    try:
        yield types.SimpleNamespace(client=client, dialogs=fake_dialogs)
    finally:
        aqt.dialogs = orig_dialogs
        for name in mods:
            sys.modules.pop(name, None)


def stubbed_info():
    util_mod = sys.modules[PKG + ".util"]
    orig = util_mod.setting
    util_mod.setting = lambda key: util_mod.DEFAULT_CONFIG[key]
    try:
        return plus.PlusMixin().plusInfo()
    finally:
        util_mod.setting = orig


def undo_snapshot():
    return core.undo_status(col)


# ===========================================================================
# 1 — registry + docs lockstep: the 37th action, version/revision, recipe,
#     README/SPEC/SKILL counts, undo-label + nextStep constants
# ===========================================================================
def test1_registry_lockstep():
    name = "ankihubStageOptionalTagSuggestion"
    assert name in core.PLUS_ACTIONS, core.PLUS_ACTIONS
    assert core.PLUS_ACTIONS[-1] == "plusInfo"
    # 36 -> 37: revision-20 SPEC 33 adds this suite's action
    assert len(core.PLUS_ACTIONS) == 37, len(core.PLUS_ACTIONS)
    assert len(set(core.PLUS_ACTIONS)) == 37, "duplicate action names"

    assert core.PLUS_VERSION == "1.5.0", core.PLUS_VERSION
    assert core.PLUS_SPEC_REVISION == 20, core.PLUS_SPEC_REVISION

    summary = core.PLUS_ACTION_SUMMARIES[name]
    assert "HUMAN" in summary and "Submit" in summary, summary
    assert "NEVER submits" in summary, summary
    assert "STOPS" in summary, summary
    assert "dryRun" in summary, summary
    returns = core.PLUS_ACTION_RETURNS[name]
    assert returns.startswith("{"), returns
    for key in ("tagged", "alreadyTagged", "ankihubDeckId", "browserOpened",
                "nextStep", "undoEntry", "wouldTag", "wouldOpenBrowser"):
        assert key in returns, key
    # the trimmed contract has NO dialog keys anywhere in the served docs
    assert "dialogOpened" not in returns and "wouldOpenDialog" not in returns
    preserves = core.PLUS_ACTION_PRESERVES[name]
    assert "tag lists" in preserves and "Browser" in preserves, preserves
    assert "NOT touched" in preserves, preserves
    assert "dialog" not in preserves or "AnkiHub's own UI" in preserves, preserves

    # constants + undo-entry lockstep
    assert core.ANKIHUB_OPTIONAL_TAG_PREFIX == "AnkiHub_Optional::"
    assert core.ANKIHUB_OPTIONAL_TAG_NOTE_CEILING == 500
    assert core.UNDO_STAGE_OPTIONAL_TAG == "Agent Connect: Stage Optional Tag"
    assert core.sanitize_undo_label(core.ANKIHUB_STAGE_TAG_LABEL) == \
        core.UNDO_STAGE_OPTIONAL_TAG
    assert core.ANKIHUB_STAGE_NEXT_STEP == \
        "right-click the selection -> AnkiHub -> Suggest Optional Tags"
    # revision-20 trim: the dialog-era constants are GONE
    assert not hasattr(core, "ANKIHUB_DIALOG_REQUIRED_PARAMS")
    assert not hasattr(core, "ANKIHUB_STAGE_TAG_KEPT_SUFFIX")

    # the ToS rationale + written-permission path ship in a served recipe,
    # and the recipe hands the human their exact remaining move
    recipe = next(r for r in core.PLUS_RECIPES
                  if r["name"] == "staged optional-tag publication")
    desc = recipe["description"]
    assert "Terms of Service" in desc, desc
    assert "automated use" in desc, desc
    assert "ahmed@ankihub.net" in desc, desc
    assert "WRITTEN permission" in desc, desc
    assert "Suggest Optional" in desc, desc
    assert "STOPS" in desc, desc
    assert recipe["example"]["action"] == name

    # the prefix-note count moved with the registry
    assert "%d Plus actions" % len(core.PLUS_ACTIONS) in core.PLUS_ERROR_PREFIX_NOTE

    # SPEC / README / SKILL lockstep
    with open(os.path.join(REPO, "SPEC.md"), encoding="utf-8") as fh:
        spec_text = fh.read()
    assert "Version: 1.5.0 (spec revision 20" in spec_text[:8192]
    assert "## 33. Staged optional-tag suggestion" in spec_text
    assert "GUI-COUPLED" in spec_text
    with open(os.path.join(REPO, "README.md"), encoding="utf-8") as fh:
        readme = fh.read()
    assert "`%s`" % name in readme
    assert "**37 new actions**" in readme
    assert "**36 new actions**" not in readme
    with open(os.path.join(REPO, "skills", "anki-bulk-cards", "SKILL.md"),
              encoding="utf-8") as fh:
        skill_text = fh.read()
    assert "37 Plus actions" in skill_text


# ===========================================================================
# 2 — ToS/permission-boundary regression grep: neither an AnkiHub optional-
#     tag client method NOR the dialog class NOR its module is named
#     anywhere in the shipped code (the blocker gate, locked forever;
#     the revision-20 trim added the dialog names to the forbidden list)
# ===========================================================================
def test2_tos_regression_grep():
    # assembled by concatenation so THIS file never matches its own gate
    forbidden = ["suggest_optional" + "_tags",
                 "_suggest_optional" + "_tags_for_deck_extension",
                 "prevalidate_tag" + "_groups",
                 "get_deck" + "_extensions",
                 "_send" + "_request",
                 "OptionalTags" + "SuggestionDialog",
                 "optional_tag" + "_suggestion_dialog"]
    scanned = 0
    for root, dirs, files in os.walk(os.path.join(REPO, "connect_plus")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fname in files:
            if not fname.endswith((".py", ".md", ".json")):
                continue
            path = os.path.join(root, fname)
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            scanned += 1
            for needle in forbidden:
                assert needle not in text, (path, needle)
    assert scanned >= 5, "connect_plus scan found too few files"

    # the action's own code path imports NOTHING from the add-on's gui/
    # package: no '.gui' string can appear in its source (the import helper
    # it calls with gui=False builds gui names only on the gui=True branch)
    fn = plus.PlusMixin.ankihubStageOptionalTagSuggestion
    source = inspect.getsource(getattr(fn, "__wrapped__", fn))
    assert ".gui" not in source, "the staging action references a gui module"
    for needle in forbidden:
        assert needle not in source, needle


# ===========================================================================
# 3 — pure validators: tag shape/prefix/segments, note-id dedup + ceiling
# ===========================================================================
def test3_validators():
    v = core.validate_ankihub_optional_tag
    assert v(TAG) == TAG
    assert v("AnkiHub_Optional::G::T") == "AnkiHub_Optional::G::T"
    assert v("AnkiHub_Optional::A::B::C::D") == "AnkiHub_Optional::A::B::C::D"

    for bad in (None, 5, [], "", "   "):
        expect_raises(lambda b=bad: v(b), "invalid parameter: tag")
    err = expect_raises(lambda: v("AnkiHub_Optional::BSOM::PI 1"),
                        "invalid parameter: tag")
    assert "whitespace" in str(err)
    # semantic refusals are [validation_error] and name the rule
    err = expect_raises(lambda: v("ankihub_optional::BSOM::X"),
                        "[validation_error]")
    assert "canonical" in str(err)
    expect_raises(lambda: v("Other::BSOM::X"), "[validation_error]")
    for short in ("AnkiHub_Optional::BSOM", "AnkiHub_Optional::::X",
                  "AnkiHub_Optional::BSOM::"):
        err = expect_raises(lambda s=short: v(s), "[validation_error]")
        assert "segments" in str(err), str(err)

    ids = core.validate_ankihub_optional_tag_note_ids
    assert ids([3, 1, 3, 2, 1]) == [3, 1, 2], "dedup must keep first occurrence"
    for bad in (None, [], "x", 7, [1, "2"], [1, True]):
        expect_raises(lambda b=bad: ids(b), "invalid parameter: noteIds")
    cap = core.ANKIHUB_OPTIONAL_TAG_NOTE_CEILING
    assert len(ids(list(range(1, cap + 1)))) == cap  # 500 unique passes
    err = expect_raises(lambda: ids(list(range(1, cap + 2))),
                        "invalid parameter: noteIds")
    assert str(cap) in str(err) and "501 unique" in str(err)
    # 501 entries but 500 UNIQUE ids: the ceiling counts the real workload
    assert len(ids(list(range(1, cap + 1)) + [1])) == cap


# ===========================================================================
# 4 — cheap validation precedes everything: bad params refuse before the
#     add-on manager (window()) or the collection is ever touched
# ===========================================================================
def test4_cheap_validation_first():
    class Untouchable(plus.PlusMixin):
        def collection(self):
            raise AssertionError("collection touched during cheap validation")

        def window(self):
            raise AssertionError("addonManager touched during cheap validation")

    b = Untouchable()
    act = b.ankihubStageOptionalTagSuggestion
    expect_raises(lambda: act(TAG, [1], dryRun="yes"),
                  "[invalid_param] invalid parameter: dryRun")
    expect_raises(lambda: act(TAG, [1], undoLabel=5),
                  "[invalid_param] invalid parameter: undoLabel")
    expect_raises(lambda: act("nope", [1]), "[validation_error]")
    expect_raises(lambda: act(TAG, []), "[invalid_param] invalid parameter: noteIds")
    cap = core.ANKIHUB_OPTIONAL_TAG_NOTE_CEILING
    expect_raises(lambda: act(TAG, list(range(1, cap + 2))),
                  "[invalid_param] invalid parameter: noteIds")


# ===========================================================================
# 5 — add-on guards: missing/unloaded add-on, module import failure,
#     missing dids function; ankihubStatus (gui=True path) still compatible
# ===========================================================================
def test5_addon_guards():
    nid = add_note("guard1")
    act = lambda bridge: bridge.ankihubStageOptionalTagSuggestion(TAG, [nid])

    # not installed
    err = expect_raises(lambda: act(make_bridge(installed=False)),
                        "[incompatible_ankihub_addon]")
    assert "ANKIHUB_ADDON_MISSING" in str(err)
    # installed + enabled but not loaded this session (nothing in sys.modules)
    err = expect_raises(lambda: act(make_bridge()),
                        "[incompatible_ankihub_addon]")
    assert "restart Anki" in str(err)

    # loaded, but a required NON-GUI module is absent (older add-on) ->
    # import fails on the gui=False path too
    h = Harness([DECK_UUID])
    with fake_ankihub(h, omit_db_module=True):
        err = expect_raises(lambda: act(make_bridge()),
                            "[incompatible_ankihub_addon]")
        assert "import failed" in str(err)

    # db lost ankihub_dids_for_anki_nids (the revision-20 detector addition)
    h = Harness([DECK_UUID])
    with fake_ankihub(h, omit_dids_fn=True):
        err = expect_raises(lambda: act(make_bridge()),
                            "[incompatible_ankihub_addon]")
        assert "ankihub_dids_for_anki_nids is missing" in str(err)

    # ankihubStatus imports with gui=True (it reports for the WHOLE bridge,
    # media_sync included) and stays compatible with the full fake
    h = Harness([DECK_UUID])
    with fake_ankihub(h, include_gui=True):
        status = make_bridge().ankihubStatus()
        assert status["compatible"] is True, status

    # nothing was ever tagged or opened by any of the refusals above
    assert note_tags(nid) == []


# ===========================================================================
# 6 — login + local db checks, all before any write or UI: logged-out,
#     first-missing-note all-or-nothing, 0-deck and 2-deck refusals
# ===========================================================================
def test6_login_and_local_checks():
    n1 = add_note("local1")
    n2 = add_note("local2")
    before = undo_snapshot()

    # logged out -> [not_logged_in], nothing written, nothing opened
    h = Harness([DECK_UUID], logged_in=False)
    with fake_ankihub(h) as ctx:
        err = expect_raises(
            lambda: make_bridge().ankihubStageOptionalTagSuggestion(TAG, [n1, n2]),
            "[not_logged_in]")
        assert "ANKIHUB_NOT_LOGGED_IN" in str(err)
        assert ctx.dialogs.opens == []
    assert note_tags(n1) == [] and note_tags(n2) == []

    # one missing note refuses the WHOLE request (all-or-nothing)
    h = Harness([DECK_UUID])
    with fake_ankihub(h) as ctx:
        err = expect_raises(
            lambda: make_bridge().ankihubStageOptionalTagSuggestion(
                TAG, [n1, 999999999999, n2]),
            "[not_found]")
        assert "note was not found: 999999999999" in str(err)
        assert ctx.dialogs.opens == []
    assert note_tags(n1) == [] and note_tags(n2) == []

    # zero AnkiHub decks -> [not_found] NOT_AN_ANKIHUB_NOTE
    h = Harness([])
    with fake_ankihub(h):
        err = expect_raises(
            lambda: make_bridge().ankihubStageOptionalTagSuggestion(TAG, [n1]),
            "[not_found]")
        assert "NOT_AN_ANKIHUB_NOTE" in str(err)

    # two AnkiHub decks -> [validation_error]
    h = Harness([DECK_UUID, OTHER_UUID])
    with fake_ankihub(h):
        err = expect_raises(
            lambda: make_bridge().ankihubStageOptionalTagSuggestion(TAG, [n1, n2]),
            "[validation_error]")
        assert "span 2 AnkiHub decks" in str(err)

    assert note_tags(n1) == [] and note_tags(n2) == []
    assert undo_snapshot() == before, "a refused staging wrote an undo entry"


# ===========================================================================
# 7 — dryRun: full validation chain, honest prediction, ZERO writes, zero
#     Browser opens
# ===========================================================================
def test7_dry_run():
    n1 = add_note("dry1")
    n2 = add_note("dry2", tags=[TAG])  # already carries the tag
    before = undo_snapshot()

    h = Harness([DECK_UUID])
    with fake_ankihub(h) as ctx:
        out = make_bridge().ankihubStageOptionalTagSuggestion(
            TAG, [n1, n2], dryRun=True)
        assert out == {"wouldTag": [n1], "alreadyTagged": [n2],
                       "ankihubDeckId": str(DECK_UUID),
                       "wouldOpenBrowser": True, "undoEntry": None}, out
        assert ctx.dialogs.opens == [], "dryRun opened a Browser"
    assert note_tags(n1) == [], "dryRun wrote a tag"
    assert undo_snapshot() == before, "dryRun wrote an undo entry"

    # dry/real key sets side by side (SPEC 31.4): dry uses would* spellings
    assert "wouldTag" in core.PLUS_ACTION_RETURNS["ankihubStageOptionalTagSuggestion"]


# ===========================================================================
# 8 — real path: tag written (ONE undo entry), Browser opened with the
#     1-tuple nid: search in request order, THEN STOP — nextStep tells the
#     human their move; no dialog machinery exists to open anything else
# ===========================================================================
def test8_real_path():
    n1 = add_note("real1")
    n2 = add_note("real2")
    before = undo_snapshot()

    h = Harness([DECK_UUID])
    with fake_ankihub(h) as ctx:
        bridge = make_bridge()
        out = bridge.ankihubStageOptionalTagSuggestion(TAG, [n1, n2])
        assert out == {"tagged": [n1, n2], "alreadyTagged": [],
                       "ankihubDeckId": str(DECK_UUID),
                       "browserOpened": True,
                       "nextStep": core.ANKIHUB_STAGE_NEXT_STEP,
                       "undoEntry": core.UNDO_STAGE_OPTIONAL_TAG}, out

        # the tag is really on the notes, as ONE undo entry
        assert note_tags(n1) == [TAG] and note_tags(n2) == [TAG]
        after = undo_snapshot()
        assert after["undo"] == core.UNDO_STAGE_OPTIONAL_TAG, after
        assert after["lastStep"] == before["lastStep"] + 1, \
            "the tag write must be exactly one undo entry"

        # Browser: one open, 1-TUPLE search, parented at the fake mw — and
        # NOTHING ELSE opened (the Browser is the only window this action
        # may touch; there is no dialog step anymore)
        assert len(ctx.dialogs.opens) == 1
        name, args, kwargs = ctx.dialogs.opens[0]
        assert name == "Browser"
        assert args == (bridge._fake_mw,)
        assert kwargs == {"search": ("nid:%d,%d" % (n1, n2),)}
        search = kwargs["search"]
        assert isinstance(search, tuple) and len(search) == 1, \
            "search must be a 1-tuple (aqt splats it into search_for_terms)"

        # the trim left no mixin dialog state behind
        assert not hasattr(bridge, "_plusStagedTagDialog")

        # idempotent re-staging: no write, no new entry, Browser reopens
        out2 = bridge.ankihubStageOptionalTagSuggestion(TAG, [n1, n2])
        assert out2["tagged"] == [] and out2["alreadyTagged"] == [n1, n2]
        assert out2["undoEntry"] is None and out2["browserOpened"] is True
        assert out2["nextStep"] == core.ANKIHUB_STAGE_NEXT_STEP
        assert undo_snapshot() == after, "a no-op re-staging wrote an entry"
        assert len(ctx.dialogs.opens) == 2, "re-staging must reopen the Browser"

        # undoLabel override names the entry the house way
        n4 = add_note("real4")
        out4 = bridge.ankihubStageOptionalTagSuggestion(
            TAG, [n4], undoLabel="PI 27 staging")
        assert out4["undoEntry"] == "Agent Connect: PI 27 staging"
        assert undo_snapshot()["undo"] == "Agent Connect: PI 27 staging"

        # a single undo reverts the last staging's tag write
        col.undo()
        assert note_tags(n4) == []

        # no forbidden client call ever happened
        assert h.client_calls == []


# ===========================================================================
# 9 — the trim is total: no dialog plumbing survives on the mixin, and the
#     staging worlds prove the action runs green with NO gui/ module seeded
# ===========================================================================
def test9_trim_is_total():
    # the dialog-era helper and reference slot are gone from the class
    assert not hasattr(plus.PlusMixin, "_plusReleaseStagedTagDialog")
    assert not hasattr(plus.PlusMixin, "_plusStagedTagDialog")

    # every staging call in this suite ran against a fake add-on with NO
    # <addon>.gui.* module in sys.modules (build_fake_modules default);
    # re-prove here on a fresh happy path and assert nothing gui-shaped
    # entered sys.modules during it
    n1 = add_note("trim1")
    h = Harness([DECK_UUID])
    with fake_ankihub(h):
        assert not any(m.startswith(ADDON + ".gui")
                       for m in sys.modules), "gui module pre-seeded?"
        out = make_bridge().ankihubStageOptionalTagSuggestion(TAG, [n1])
        assert out["tagged"] == [n1] and out["browserOpened"] is True
        assert not any(m.startswith(ADDON + ".gui") for m in sys.modules), \
            "the staging action imported a gui/ module"
    col.undo()  # leave the collection tidy


# ===========================================================================
# 10 — served surface: wrapper signature string, actionDocs entry complete,
#      plusInfo action list carries the 37th action
# ===========================================================================
def test10_served_surface():
    name = "ankihubStageOptionalTagSuggestion"
    info = stubbed_info()
    assert name in info["actions"]
    assert len(info["actions"]) == 37
    doc = info["actionDocs"][name]
    assert doc["params"] == "tag, noteIds, dryRun=false, undoLabel=null", doc
    assert doc["summary"] == core.PLUS_ACTION_SUMMARIES[name]
    assert doc["returns"] == core.PLUS_ACTION_RETURNS[name]
    assert doc["preserves"] == core.PLUS_ACTION_PRESERVES[name]
    recipes = {r["name"] for r in info["recipes"]}
    assert "staged optional-tag publication" in recipes

    # the wrapper's exposed signature really is what actionDocs printed
    sig = inspect.signature(plus.PlusMixin.ankihubStageOptionalTagSuggestion)
    assert [p for p in sig.parameters] == \
        ["self", "tag", "noteIds", "dryRun", "undoLabel"]
    assert sig.parameters["dryRun"].default is False
    assert sig.parameters["undoLabel"].default is None


run("1  registry + docs lockstep (37 actions, 1.5.0/rev 20, recipe, counts)",
    test1_registry_lockstep)
run("2  boundary grep: no posting method, no dialog class, no gui import",
    test2_tos_regression_grep)
run("3  pure validators: tag shape/prefix/segments, dedup + 500 ceiling",
    test3_validators)
run("4  cheap validation precedes add-on/collection access",
    test4_cheap_validation_first)
run("5  add-on guards + feature detection (dids fn; status gui=True path)",
    test5_addon_guards)
run("6  login + all-or-nothing local checks, nothing written on refusal",
    test6_login_and_local_checks)
run("7  dryRun: full chain, zero writes, zero UI",
    test7_dry_run)
run("8  real path: one undo entry, 1-tuple Browser search, then STOP",
    test8_real_path)
run("9  trim is total: no dialog plumbing, no gui/ import at runtime",
    test9_trim_is_total)
run("10 served surface: params string, actionDocs, plusInfo",
    test10_served_surface)

col.close()
print()
failures = [r for r in RESULTS if not r[1]]
print("%d/%d passed" % (len(RESULTS) - len(failures), len(RESULTS)))
sys.exit(1 if failures else 0)
