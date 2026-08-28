# INDEPENDENT verification for SPEC 33 (spec revision 20, v1.5.0):
# ankihubStageOptionalTagSuggestion — the staged, HUMAN-submitted optional-tag
# flow, TRIMMED (revision-20 review) to stop at the Browser selection: the
# action validates, tags (one undoable batch), opens the Browser on exactly
# the staged notes, and STOPS. The human right-clicks the selection ->
# AnkiHub -> "Suggest Optional Tags" and presses Submit — every touch of
# AnkiHub's code and servers is a human click. Written by the verifier,
# deliberately NOT derived from the builder's headless_optionaltag_test.py:
# same seams (they are the implementation's seams), independent scenarios
# and instrumentation.
#
# Run with: <anki-venv>/bin/python headless_stagetags_test.py
#
# ZERO NETWORK — by construction AND by enforcement. This action's whole
# premise is that nothing talks to AnkiHub, so a process-wide socket
# deny-guard is installed BEFORE anki/aqt load: every python-level connection
# attempt raises and is recorded, and the suite FAILS if the attempt log is
# non-empty at the end. The AnkiHub add-on package is FAKED in sys.modules
# (plus.py reaches add-on modules via importlib.import_module, which
# short-circuits on sys.modules); the REAL add-on under ~/Library is never
# imported, read, or written. THE FAKE SEEDS NO MODULE UNDER <addon>.gui —
# the trimmed action must import nothing from the add-on's gui/ package, so
# green staging runs against a gui-less fake ARE the proof, and an exit gate
# asserts no <addon>.gui* module ever entered sys.modules. The Browser seam
# (aqt.dialogs) is stubbed with a recorder; the live Browser open remains
# UNTESTED here by design (human-witnessed test).
#
# Scratch collection lives under the session scratchpad (fallback: mkdtemp);
# NEVER under ~/Library.

import contextlib
import importlib
import importlib.util
import inspect
import json
import os
import shutil
import socket
import sys
import tempfile
import traceback
import types
import uuid as uuid_mod

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_PATH = os.path.join(REPO, "connect_plus", "core.py")

_PREFERRED_SCRATCH = os.path.join(tempfile.gettempdir(), "ancp_st_v1")


def _pick_scratch():
    env = os.environ.get("ANCP_ST_SCRATCH")
    if env:
        return env
    try:
        os.makedirs(_PREFERRED_SCRATCH, exist_ok=True)
        return os.path.join(_PREFERRED_SCRATCH, "col_scratch")
    except OSError:
        return tempfile.mkdtemp(prefix="ancp_st_v1_")


SCRATCH = _pick_scratch()
assert not SCRATCH.startswith(os.path.expanduser("~/Library")), \
    "scratch dir must not be under ~/Library"
assert "Anki2" not in SCRATCH
if os.path.exists(SCRATCH):
    shutil.rmtree(SCRATCH)
os.makedirs(SCRATCH)

sys.dont_write_bytecode = True

# ---------------------------------------------------------------- net guard
# MANDATORY for this suite: installed before anything heavy loads. Any
# python-level connection attempt raises AND is recorded; the suite fails on
# a non-empty log. (The rust backend has its own stack, but its network entry
# points — sync/full-sync — are never called here.)
NETWORK_ATTEMPTS = []


def _make_deny(name):
    def _deny(*args, **kwargs):
        NETWORK_ATTEMPTS.append((name, args[:2]))
        raise RuntimeError("network access blocked by headless_stagetags_test "
                           "(%s)" % name)
    return _deny


socket.socket.connect = _make_deny("socket.connect")
socket.socket.connect_ex = _make_deny("socket.connect_ex")
socket.create_connection = _make_deny("socket.create_connection")
socket.getaddrinfo = _make_deny("socket.getaddrinfo")

# ---------------------------------------------------------------- core load
# core.py standalone (no package __init__, no aqt) + purity asserts
spec = importlib.util.spec_from_file_location("core", CORE_PATH)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
assert "aqt" not in sys.modules, "core.py (or its imports) pulled in aqt"
assert core.ANKIHUB_ADDON_PACKAGE not in sys.modules, \
    "core.py must never import the AnkiHub add-on"

import anki.lang  # noqa: E402
anki.lang.set_lang("en_US")
import anki.notes  # noqa: E402
from anki.collection import Collection  # noqa: E402

col = Collection(os.path.join(SCRATCH, "stage.anki2"))

# plus.py as a real module through a synthetic package (connect_plus's
# __init__, which boots the add-on against aqt.mw, never runs)
PKG = "ancp_st_pkg"
pkg_mod = types.ModuleType(PKG)
pkg_mod.__path__ = [os.path.join(REPO, "connect_plus")]
pkg_mod.__package__ = PKG
sys.modules[PKG] = pkg_mod
plus = importlib.import_module(PKG + ".plus")
import aqt  # noqa: E402  (plus.py already pulled it in)

ADDON = core.ANKIHUB_ADDON_PACKAGE
ACTION = "ankihubStageOptionalTagSuggestion"
TAG = "AnkiHub_Optional::BSOM::MCQ_03::PI_027_Pancreas"
DECK_UUID = uuid_mod.UUID("0f5e7a3c-9d21-4b6e-8c44-2ab90d17e6f5")

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


def expect_plus_error(fn, code, fragment=None):
    """The call must raise a PlusError-shaped exception with .code == code,
    str() carrying the '[code] ' prefix and (optionally) the fragment."""
    try:
        fn()
    except Exception as e:
        assert getattr(e, "code", None) == code, \
            "expected code %r, got %r (%s)" % (code, getattr(e, "code", None), e)
        assert str(e).startswith("[%s] " % code), str(e)
        if fragment is not None:
            assert fragment in str(e), "expected %r in %r" % (fragment, str(e))
        return e
    raise AssertionError("expected a [%s] error" % code)


def add_note(front, tags=()):
    model = col.models.by_name("Basic")
    note = col.new_note(model)
    note["Front"] = front
    note["Back"] = "back"
    note.tags = list(tags)
    col.add_note(note, col.decks.id("StageTags"))
    return int(note.id)


def note_tags(nid):
    return sorted(col.get_note(anki.notes.NoteId(nid)).tags)


def tags_snapshot(nids):
    """Byte-comparable snapshot of the notes' tag lists."""
    return json.dumps({str(nid): note_tags(nid) for nid in nids}, sort_keys=True)


def undo_snapshot():
    """Byte-comparable snapshot of the undo stack (backend truth)."""
    return json.dumps(core.undo_status(col), sort_keys=True)


# ---------------------------------------------------------------------------
# Fake add-on harness — instrumented recorders, independent of the builder's.
# The forbidden AnkiHub client surface raises AND records if ever touched.
# NO gui/ module is ever seeded: the trimmed action must not import any.
# ---------------------------------------------------------------------------

class Recorder:
    def __init__(self):
        self.browser_opens = []     # (name, args, kwargs) per aqt.dialogs.open
        self.browsers = []          # browser sentinels returned
        self.forbidden_calls = []   # any AnkiHub client-path call
        self.login_checks = 0


def _forbidden(name, recorder):
    def fn(*args, **kwargs):
        recorder.forbidden_calls.append(name)
        raise AssertionError(
            "forbidden AnkiHub client path called by the stage action: " + name)
    return fn


def build_fake_addon(recorder, dids, logged_in=True, omit_dids_fn=False):
    import enum
    mods = {}

    suggestions = types.ModuleType(ADDON + ".main.suggestions")

    def suggest_note_update(note, change_type, comment, media_upload_cb,
                            auto_accept):
        return _forbidden("suggest_note_update", recorder)()

    def suggest_new_note(note, comment, ankihub_did, media_upload_cb,
                         auto_accept):
        return _forbidden("suggest_new_note", recorder)()

    def resubmit_new_note_as_change_suggestion(note, ah_did,
                                               conflicting_ah_nid, change_type,
                                               comment, auto_accept):
        return _forbidden("resubmit_new_note_as_change_suggestion", recorder)()

    def has_empty_first_field(note):
        return _forbidden("has_empty_first_field", recorder)()

    def parse_duplicate_anki_id_error(errors):
        return _forbidden("parse_duplicate_anki_id_error", recorder)()

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

    def is_logged_in():
        recorder.login_checks += 1
        return logged_in

    settings.config = types.SimpleNamespace(
        is_logged_in=is_logged_in,
        anking_deck_id=None,
    )
    mods[ADDON + ".settings"] = settings

    db = types.ModuleType(ADDON + ".db")
    database = types.SimpleNamespace(
        ankihub_nid_for_anki_nid=lambda nid: None,
        ankihub_did_for_anki_nid=lambda nid: None,
        ankihub_did_for_note_type=lambda mid: None,
    )
    if not omit_dids_fn:
        database.ankihub_dids_for_anki_nids = lambda nids: list(dids)
    db.ankihub_db = database
    mods[ADDON + ".db"] = db

    # deliberately NO <addon>.gui.* module here — see the header contract

    mods[ADDON] = types.ModuleType(ADDON)
    return mods, client


class RecordingAddonManager:
    """Records every touch so guard-order tests can assert 'never reached'."""

    def __init__(self, installed=True, enabled=True):
        self.installed = installed
        self.enabled = enabled
        self.calls = []

    def allAddons(self):
        self.calls.append("allAddons")
        return [ADDON] if self.installed else []

    def isEnabled(self, pkg):
        self.calls.append("isEnabled")
        return self.enabled

    def addonsFolder(self, pkg):
        self.calls.append("addonsFolder")
        return os.path.join(SCRATCH, "no-addon-here")


class FakeDialogs:
    def __init__(self, recorder):
        self._recorder = recorder

    def open(self, name, *args, **kwargs):
        self._recorder.browser_opens.append((name, args, kwargs))
        browser = types.SimpleNamespace(kind="stagetags-fake-browser",
                                        n=len(self._recorder.browsers))
        self._recorder.browsers.append(browser)
        return browser


def make_bridge(manager):
    mw = types.SimpleNamespace(addonManager=manager)

    class Bridge(plus.PlusMixin):
        def collection(self):
            return col

        def window(self):
            return mw

    bridge = Bridge()
    bridge._test_mw = mw
    return bridge


@contextlib.contextmanager
def staged_world(dids=(DECK_UUID,), installed=True, enabled=True,
                 loaded=True, logged_in=True, **build_kwargs):
    """Seed the fake add-on package + patch aqt.dialogs; restore on exit.
    loaded=False leaves sys.modules untouched (the 'restart Anki' path)."""
    recorder = Recorder()
    mods, client = build_fake_addon(recorder, dids, logged_in=logged_in,
                                    **build_kwargs)
    seeded = []
    if loaded:
        for name, mod in mods.items():
            assert name not in sys.modules, "real module already loaded: " + name
            sys.modules[name] = mod
            seeded.append(name)
    orig_dialogs = aqt.dialogs
    fake_dialogs = FakeDialogs(recorder)
    aqt.dialogs = fake_dialogs
    bridge = make_bridge(RecordingAddonManager(installed, enabled))
    try:
        yield types.SimpleNamespace(bridge=bridge, recorder=recorder,
                                    client=client,
                                    manager=bridge._test_mw.addonManager)
    finally:
        aqt.dialogs = orig_dialogs
        for name in seeded:
            sys.modules.pop(name, None)
        # the recorder outlives the context only through the caller; the
        # forbidden-call ledger is checked globally at the end too
        FORBIDDEN_LEDGERS.append(recorder.forbidden_calls)


FORBIDDEN_LEDGERS = []


# ===========================================================================
# 1 — validation refusals: codes per SPEC 33 ([invalid_param] for shape,
#     [validation_error] for semantics), all before any write
# ===========================================================================
def test1_param_validation_codes():
    nid = add_note("v1")
    with staged_world() as world:
        act = world.bridge.ankihubStageOptionalTagSuggestion
        before = tags_snapshot([nid])
        undo_before = undo_snapshot()

        # tag WITHOUT the AnkiHub_Optional:: prefix — the SPEC 33 contract
        # routes this semantic refusal to [validation_error] (shape errors
        # are [invalid_param])
        expect_plus_error(lambda: act("BSOM::MCQ_03::PI_027", [nid]),
                          "validation_error", "must start with")
        expect_plus_error(lambda: act("ankihub_optional::BSOM::X", [nid]),
                          "validation_error", "canonical")
        # <3 segments / empty segment: still validation_error
        expect_plus_error(lambda: act("AnkiHub_Optional::OnlyGroup", [nid]),
                          "validation_error", "segments")
        expect_plus_error(lambda: act("AnkiHub_Optional::BSOM::", [nid]),
                          "validation_error", "segments")
        # shape errors -> invalid_param
        expect_plus_error(lambda: act("", [nid]), "invalid_param",
                          "invalid parameter: tag")
        expect_plus_error(lambda: act(None, [nid]), "invalid_param",
                          "invalid parameter: tag")
        expect_plus_error(lambda: act("AnkiHub_Optional::BSOM::PI 27", [nid]),
                          "invalid_param", "whitespace")
        # empty / malformed noteIds -> invalid_param
        expect_plus_error(lambda: act(TAG, []), "invalid_param",
                          "invalid parameter: noteIds")
        expect_plus_error(lambda: act(TAG, "12,34"), "invalid_param",
                          "invalid parameter: noteIds")
        expect_plus_error(lambda: act(TAG, [nid, True]), "invalid_param",
                          "invalid parameter: noteIds")
        # ceiling: 501 unique -> invalid_param naming the cap
        cap = core.ANKIHUB_OPTIONAL_TAG_NOTE_CEILING
        err = expect_plus_error(lambda: act(TAG, list(range(1, cap + 2))),
                                "invalid_param", "invalid parameter: noteIds")
        assert str(cap) in str(err), str(err)
        # dryRun / undoLabel shapes
        expect_plus_error(lambda: act(TAG, [nid], dryRun="yes"),
                          "invalid_param", "dryRun")
        expect_plus_error(lambda: act(TAG, [nid], undoLabel=7),
                          "invalid_param", "undoLabel")
        expect_plus_error(lambda: act(TAG, [nid], undoLabel="   "),
                          "invalid_param", "undoLabel")

        # none of the refusals wrote anything or touched the Browser seam
        assert tags_snapshot([nid]) == before
        assert undo_snapshot() == undo_before
        assert world.recorder.browser_opens == []

    # validator boundary, direct: 500 unique passes, dedup keeps first seen
    ids = core.validate_ankihub_optional_tag_note_ids
    cap = core.ANKIHUB_OPTIONAL_TAG_NOTE_CEILING
    assert ids(list(range(1, cap + 1))) == list(range(1, cap + 1))
    assert ids([7, 3, 7, 1, 3]) == [7, 3, 1]


# ===========================================================================
# 2 — cheap validation precedes the add-on guard: bad params refuse while
#     the addon manager and collection are provably untouched
# ===========================================================================
def test2_cheap_validation_first():
    class UntouchableBridge(plus.PlusMixin):
        def collection(self):
            raise AssertionError("collection touched during cheap validation")

        def window(self):
            raise AssertionError("window/addonManager touched during cheap validation")

    act = UntouchableBridge().ankihubStageOptionalTagSuggestion
    expect_plus_error(lambda: act("Wrong::Prefix::X", [1]), "validation_error")
    expect_plus_error(lambda: act(TAG, []), "invalid_param")
    expect_plus_error(lambda: act(TAG, [1], dryRun=1), "invalid_param")
    expect_plus_error(lambda: act(TAG, [1], undoLabel=""), "invalid_param")


# ===========================================================================
# 3 — add-on guard paths: the documented [incompatible_ankihub_addon] for
#     missing / disabled / unloaded, and the revision-20 dids-fn detection
# ===========================================================================
def test3_addon_guard_paths():
    nid = add_note("g1")
    before = tags_snapshot([nid])

    # not installed
    with staged_world(installed=False) as world:
        err = expect_plus_error(
            lambda: world.bridge.ankihubStageOptionalTagSuggestion(TAG, [nid]),
            "incompatible_ankihub_addon", "ANKIHUB_ADDON_MISSING")
        assert world.recorder.browser_opens == []
    # installed but disabled
    with staged_world(enabled=False) as world:
        expect_plus_error(
            lambda: world.bridge.ankihubStageOptionalTagSuggestion(TAG, [nid]),
            "incompatible_ankihub_addon", "ANKIHUB_ADDON_DISABLED")
    # installed + enabled but never loaded this session (not in sys.modules)
    with staged_world(loaded=False) as world:
        expect_plus_error(
            lambda: world.bridge.ankihubStageOptionalTagSuggestion(TAG, [nid]),
            "incompatible_ankihub_addon", "restart Anki")
    # revision-20 feature detection: ankihub_dids_for_anki_nids gone
    with staged_world(omit_dids_fn=True) as world:
        expect_plus_error(
            lambda: world.bridge.ankihubStageOptionalTagSuggestion(TAG, [nid]),
            "incompatible_ankihub_addon", "ankihub_dids_for_anki_nids")

    assert tags_snapshot([nid]) == before, "guard paths must write nothing"


# ===========================================================================
# 4 — login + local-db guards, all-or-nothing: [not_logged_in] before any
#     UI; one missing nid refuses the WHOLE call naming it, tag snapshot
#     proves nothing was written; 0/2-deck refusals
# ===========================================================================
def test4_login_and_local_db_guards():
    a = add_note("ao1")
    b = add_note("ao2")
    missing = max(a, b) + 987654
    before = tags_snapshot([a, b])
    undo_before = undo_snapshot()

    # logged out: refused BEFORE any write or UI
    with staged_world(logged_in=False) as world:
        expect_plus_error(
            lambda: world.bridge.ankihubStageOptionalTagSuggestion(TAG, [a, b]),
            "not_logged_in", "ANKIHUB_NOT_LOGGED_IN")
        assert world.recorder.login_checks == 1
        assert world.recorder.browser_opens == []

    # one missing nid among real ones, missing LAST: the whole call refuses
    # with [not_found] naming the id, and the real notes' tags are untouched
    with staged_world() as world:
        err = expect_plus_error(
            lambda: world.bridge.ankihubStageOptionalTagSuggestion(
                TAG, [a, b, missing]),
            "not_found", "note was not found: %d" % missing)
        assert world.recorder.browser_opens == []
    assert tags_snapshot([a, b]) == before, \
        "all-or-nothing violated: a tag was written despite a missing note"
    assert undo_snapshot() == undo_before

    # dryRun with the same missing nid refuses identically (validation runs)
    with staged_world() as world:
        expect_plus_error(
            lambda: world.bridge.ankihubStageOptionalTagSuggestion(
                TAG, [a, missing, b], dryRun=True),
            "not_found", "note was not found: %d" % missing)
    assert tags_snapshot([a, b]) == before

    # zero AnkiHub decks -> [not_found] NOT_AN_ANKIHUB_NOTE
    with staged_world(dids=()) as world:
        expect_plus_error(
            lambda: world.bridge.ankihubStageOptionalTagSuggestion(TAG, [a, b]),
            "not_found", "NOT_AN_ANKIHUB_NOTE")
    # two AnkiHub decks -> [validation_error] naming the count
    other = uuid_mod.UUID("7d3c1a2b-4e5f-4a6b-8c9d-0e1f2a3b4c5d")
    with staged_world(dids=(DECK_UUID, other)) as world:
        err = expect_plus_error(
            lambda: world.bridge.ankihubStageOptionalTagSuggestion(TAG, [a, b]),
            "validation_error", "2 AnkiHub")
        assert "split the call" in str(err)
    assert tags_snapshot([a, b]) == before
    assert undo_snapshot() == undo_before


# ===========================================================================
# 5 — dryRun: full prediction {wouldTag, alreadyTagged, ankihubDeckId,
#     wouldOpenBrowser, undoEntry:null}; ZERO writes (tag + undo snapshots
#     byte-identical) and the Browser seam provably not invoked
# ===========================================================================
DRY_RESULT = {}


def test5_dryrun_predicts_writes_nothing():
    c = add_note("dry1")
    d = add_note("dry2", tags=[TAG])   # already carries the staged tag
    e = add_note("dry3")
    before = tags_snapshot([c, d, e])
    undo_before = undo_snapshot()

    with staged_world() as world:
        result = world.bridge.ankihubStageOptionalTagSuggestion(
            TAG, [c, d, e, c], dryRun=True)   # dupe c: dedup first-seen
        assert result["wouldTag"] == [c, e], result
        assert result["alreadyTagged"] == [d], result
        assert result["ankihubDeckId"] == str(DECK_UUID), result
        assert result["wouldOpenBrowser"] is True, result
        assert result["undoEntry"] is None, result
        assert set(result) == {"wouldTag", "alreadyTagged", "ankihubDeckId",
                               "wouldOpenBrowser", "undoEntry"}, result
        # seam provably untouched
        assert world.recorder.browser_opens == [], "dryRun opened the Browser"
        DRY_RESULT.update(result)

    # zero writes: byte-identical snapshots
    assert tags_snapshot([c, d, e]) == before, "dryRun wrote tags"
    assert undo_snapshot() == undo_before, "dryRun touched the undo stack"


# ===========================================================================
# 6 — real staging (GUI stubbed at the implementation's seam): tag applied
#     to all, ONE undo entry under the default label, Browser 1-tuple
#     search in request order, then STOP — nextStep served verbatim and
#     nothing else opened; no dialog plumbing exists on the mixin
# ===========================================================================
REAL_RESULT = {}


def test6_real_staging_happy_path():
    f = add_note("real1")
    g = add_note("real2")
    h = add_note("real3")
    nids = [g, f, h]                    # deliberate non-sorted order
    undo_before = core.undo_status(col)

    with staged_world() as world:
        result = world.bridge.ankihubStageOptionalTagSuggestion(TAG, nids)
        rec = world.recorder

        # response shape — the trimmed revision-20 contract
        assert result["tagged"] == [g, f, h], result
        assert result["alreadyTagged"] == [], result
        assert result["ankihubDeckId"] == str(DECK_UUID), result
        assert result["browserOpened"] is True, result
        assert result["nextStep"] == core.ANKIHUB_STAGE_NEXT_STEP, result
        assert result["nextStep"] == ("right-click the selection -> AnkiHub "
                                      "-> Suggest Optional Tags"), result
        assert result["undoEntry"] == "Agent Connect: Stage Optional Tag", result
        assert set(result) == {"tagged", "alreadyTagged", "ankihubDeckId",
                               "browserOpened", "nextStep", "undoEntry"}, result
        REAL_RESULT.update(result)

        # the tag landed on every staged note
        for nid in nids:
            assert TAG in note_tags(nid), (nid, note_tags(nid))

        # ONE undo entry, default label, exactly one step forward
        after = core.undo_status(col)
        assert after["undo"] == "Agent Connect: Stage Optional Tag", after
        assert after["lastStep"] == undo_before["lastStep"] + 1, \
            (undo_before, after)

        # Browser seam: exactly one open, 1-TUPLE nid: search in request order
        assert len(rec.browser_opens) == 1, rec.browser_opens
        name, args, kwargs = rec.browser_opens[0]
        assert name == "Browser"
        assert args == (world.bridge._test_mw,), args
        assert kwargs == {"search": ("nid:%d,%d,%d" % (g, f, h),)}, kwargs
        assert isinstance(kwargs["search"], tuple) and len(kwargs["search"]) == 1

        # STOP means stop: no dialog reference slot appears on the bridge,
        # and the trim removed the release helper from the class entirely
        assert not hasattr(world.bridge, "_plusStagedTagDialog")
        assert not hasattr(plus.PlusMixin, "_plusReleaseStagedTagDialog")

    # a SINGLE col.undo() removes the tag from ALL staged notes
    col.undo()
    for nid in nids:
        assert TAG not in note_tags(nid), (nid, note_tags(nid))


# ===========================================================================
# 7 — alreadyTagged split on re-run + undoLabel honored + no-op restage
#     (the documented recovery flow: re-running is always safe, the Browser
#     selection simply reopens)
# ===========================================================================
def test7_rerun_split_undolabel_and_noop():
    p = add_note("split1")
    q = add_note("split2")
    r = add_note("split3", tags=[TAG])   # pre-tagged by hand

    # custom undoLabel honored (sanitize prefixes the house name)
    with staged_world() as world:
        result = world.bridge.ankihubStageOptionalTagSuggestion(
            TAG, [p, q, r], undoLabel="stage PI 27")
        assert result["tagged"] == [p, q], result
        assert result["alreadyTagged"] == [r], result
        assert result["undoEntry"] == "Agent Connect: stage PI 27", result
        assert result["browserOpened"] is True, result
        assert core.undo_status(col)["undo"] == "Agent Connect: stage PI 27"
        assert len(world.recorder.browser_opens) == 1

    # re-run of the identical call: reported no-op write, Browser still opens
    # with the same selection — the "reopen to submit" recovery flow
    undo_before = undo_snapshot()
    tag_before = tags_snapshot([p, q, r])
    with staged_world() as world:
        result = world.bridge.ankihubStageOptionalTagSuggestion(TAG, [p, q, r])
        assert result["tagged"] == [], result
        assert result["alreadyTagged"] == [p, q, r], result
        assert result["undoEntry"] is None, result
        assert result["browserOpened"] is True, result
        assert result["nextStep"] == core.ANKIHUB_STAGE_NEXT_STEP, result
        assert len(world.recorder.browser_opens) == 1, \
            "no-op restage must still reopen the Browser"
        name, args, kwargs = world.recorder.browser_opens[0]
        assert kwargs == {"search": ("nid:%d,%d,%d" % (p, q, r),)}, kwargs
    assert undo_snapshot() == undo_before, \
        "no-op restage must leave no do-nothing undo entry"
    assert tags_snapshot([p, q, r]) == tag_before


# ===========================================================================
# 8 — ToS/permission boundary as a test: the shipped code never names the
#     add-on client's optional-tag entry points NOR the dialog class NOR its
#     module; the action's source references no gui module; no fake client
#     path was ever called; no <addon>.gui* module ever entered sys.modules
# ===========================================================================
def test8_tos_boundary():
    # assembled at runtime so THIS file can never satisfy its own grep
    forbidden = [
        "suggest_optional" + "_tags",
        "prevalidate_tag" + "_groups",
        "_suggest_optional" + "_tags_for_deck_extension",
        "get_deck" + "_extensions",
        "OptionalTags" + "SuggestionDialog",
        "optional_tag" + "_suggestion_dialog",
    ]
    shipped = []
    for root, dirs, files in os.walk(os.path.join(REPO, "connect_plus")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for fname in files:
            if fname.endswith((".py", ".md", ".json")):
                shipped.append(os.path.join(root, fname))
    assert len(shipped) >= 6, shipped
    for path in shipped:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        for needle in forbidden:
            assert needle not in text, \
                "ToS boundary violated: %r found in %s" % (needle, path)

    # the action's own source, directly (belt beside the repo grep): none of
    # the forbidden names, and NO '.gui' import can be formed from it — the
    # '1322529746.gui...' module names were only ever built by the import
    # helper's gui=True branch, which this action does not take
    fn = plus.PlusMixin.ankihubStageOptionalTagSuggestion
    source = inspect.getsource(getattr(fn, "__wrapped__", fn))
    for needle in forbidden:
        assert needle not in source, needle
    assert ".gui" not in source, "the action's source references a gui module"
    assert "gui=False" in source, "the action must import with gui=False"

    # no scenario above ever reached a fake AnkiHub client path
    for ledger in FORBIDDEN_LEDGERS:
        assert ledger == [], "forbidden AnkiHub client call recorded: %r" % ledger

    # no module under the add-on's gui/ package ever entered sys.modules —
    # the fake never seeds one, so any hit means a REAL import happened
    gui_mods = [m for m in sys.modules if m.startswith(ADDON + ".gui")]
    assert gui_mods == [], gui_mods

    # and no scenario opened a socket (also re-asserted at exit)
    assert NETWORK_ATTEMPTS == [], NETWORK_ATTEMPTS


# ===========================================================================
# 9 — lockstep: 37 actions, 1.5.0 / revision 20, SPEC header, served docs
#     match the CAPTURED shapes, GUI-coupled caveat served, undo-label +
#     nextStep constants, recipe, README count, dialog keys GONE
# ===========================================================================
def test9_lockstep_and_served_docs():
    assert ACTION in core.PLUS_ACTIONS
    assert len(core.PLUS_ACTIONS) == 37, len(core.PLUS_ACTIONS)
    assert len(set(core.PLUS_ACTIONS)) == 37
    assert core.PLUS_ACTIONS[-1] == "plusInfo"
    assert core.PLUS_VERSION == "1.5.0", core.PLUS_VERSION
    assert core.PLUS_SPEC_REVISION == 20, core.PLUS_SPEC_REVISION

    with open(os.path.join(REPO, "SPEC.md"), encoding="utf-8") as fh:
        head = fh.read(8192)
    assert "Version: 1.5.0 (spec revision 20" in head, head[:200]

    # undo-label + nextStep lockstep; dialog-era constants are gone
    assert core.UNDO_STAGE_OPTIONAL_TAG == "Agent Connect: Stage Optional Tag"
    assert core.sanitize_undo_label(core.ANKIHUB_STAGE_TAG_LABEL) == \
        core.UNDO_STAGE_OPTIONAL_TAG
    assert core.ANKIHUB_STAGE_NEXT_STEP == \
        "right-click the selection -> AnkiHub -> Suggest Optional Tags"
    assert not hasattr(core, "ANKIHUB_DIALOG_REQUIRED_PARAMS")
    assert not hasattr(core, "ANKIHUB_STAGE_TAG_KEPT_SUFFIX")

    # served plusInfo (util.setting needs aqt.mw; patch to shipped defaults —
    # the documented headless resolution)
    util_mod = sys.modules[PKG + ".util"]
    orig_setting = util_mod.setting
    util_mod.setting = lambda key: util_mod.DEFAULT_CONFIG[key]
    try:
        info = plus.PlusMixin().plusInfo()
    finally:
        util_mod.setting = orig_setting

    assert info["version"] == "1.5.0"
    assert info["specRevision"] == 20
    assert info["actions"] == list(core.PLUS_ACTIONS)
    assert len(info["actionDocs"]) == 37

    doc = info["actionDocs"][ACTION]
    # GUI-coupled caveat is SERVED (summary carries it verbatim), and the
    # summary tells the human their move
    assert "GUI-COUPLED" in doc["summary"], doc["summary"]
    assert "NEVER submits" in doc["summary"]
    assert "ZERO AnkiHub calls" in doc["summary"], doc["summary"]
    assert "ToS" in doc["summary"] or "Terms" in doc["summary"], doc["summary"]
    assert "Suggest Optional Tags" in doc["summary"], doc["summary"]
    # params doc reflects the real signature
    assert doc["params"] == "tag, noteIds, dryRun=false, undoLabel=null", doc["params"]

    # returns doc names EXACTLY the captured real + dry keys — and none of
    # the dialog-era keys
    returns = doc["returns"]
    assert REAL_RESULT and DRY_RESULT, "capture tests did not run"
    for key in REAL_RESULT:
        assert key in returns, "real key %r missing from returns doc" % key
    for key in DRY_RESULT:
        assert key in returns, "dry key %r missing from returns doc" % key
    assert "dialogOpened" not in returns and "wouldOpenDialog" not in returns
    # and the dry caveat: nothing written, nothing opens
    assert "nothing is written and nothing opens" in returns, returns
    assert "default 'Agent Connect: Stage Optional Tag'" in returns

    # preserves: honest, mentions the tag-list exception, the zero-AnkiHub
    # boundary, and the one GUI side effect (Browser search replaced)
    preserves = doc["preserves"]
    assert "tag lists" in preserves
    assert "NOT touched" in preserves
    assert "Browser" in preserves

    # every code §33 can raise is a served, documented code (the AnkiHub
    # HTTP taxonomy codes stay served for the two suggest actions, but §33
    # itself can no longer reach them — it makes no AnkiHub calls)
    served = set(info["errorCodes"])
    for code in ("invalid_param", "validation_error", "not_found",
                 "incompatible_ankihub_addon", "not_logged_in",
                 "batch_reverted", "sync_in_progress", "collection_unavailable"):
        assert code in served, code

    # the ToS recipe is served with the permission path and the human's move
    recipe = next(r for r in info["recipes"]
                  if r["name"] == "staged optional-tag publication")
    assert recipe["example"]["action"] == ACTION
    assert "Terms of Service" in recipe["description"]
    assert "ahmed@ankihub.net" in recipe["description"]
    assert "Suggest Optional" in recipe["description"]

    # README moved its count and names the action
    with open(os.path.join(REPO, "README.md"), encoding="utf-8") as fh:
        readme = fh.read()
    assert "`%s`" % ACTION in readme
    assert "**37 new actions**" in readme
    assert "**36 new actions**" not in readme


run("test1_param_validation_codes", test1_param_validation_codes)
run("test2_cheap_validation_first", test2_cheap_validation_first)
run("test3_addon_guard_paths", test3_addon_guard_paths)
run("test4_login_and_local_db_guards", test4_login_and_local_db_guards)
run("test5_dryrun_predicts_writes_nothing", test5_dryrun_predicts_writes_nothing)
run("test6_real_staging_happy_path", test6_real_staging_happy_path)
run("test7_rerun_split_undolabel_and_noop", test7_rerun_split_undolabel_and_noop)
run("test8_tos_boundary", test8_tos_boundary)
run("test9_lockstep_and_served_docs", test9_lockstep_and_served_docs)

col.close()

# hard exit gates: the real add-on stayed out of sys.modules, no gui/ module
# of the add-on ever loaded, and the socket guard recorded ZERO attempts
FINAL = []
if ADDON in sys.modules:
    FINAL.append("the real AnkiHub add-on entered sys.modules")
GUI_MODS = [m for m in sys.modules if m.startswith(ADDON + ".gui")]
if GUI_MODS:
    FINAL.append("an AnkiHub gui/ module entered sys.modules: %r" % GUI_MODS)
if NETWORK_ATTEMPTS:
    FINAL.append("network attempts recorded: %r" % NETWORK_ATTEMPTS)
for ledger in FORBIDDEN_LEDGERS:
    if ledger:
        FINAL.append("forbidden AnkiHub client call: %r" % ledger)

print("\n===== SUMMARY =====")
n_pass = sum(1 for _, ok, _ in RESULTS if ok)
for name, ok, _ in RESULTS:
    print("%s  %s" % ("PASS" if ok else "FAIL", name))
for problem in FINAL:
    print("FAIL  exit-gate: %s" % problem)
print("%d/%d passed; network attempts: %d" % (n_pass, len(RESULTS),
                                              len(NETWORK_ATTEMPTS)))
sys.exit(0 if (n_pass == len(RESULTS) and not FINAL) else 1)
