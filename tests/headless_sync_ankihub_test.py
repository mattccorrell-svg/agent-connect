# Headless verification round: SPEC 18 sync helpers + SPEC 19 AnkiHub bridge,
# including the signature-compat drift alarm against the INSTALLED AnkiHub
# add-on (read-only import with SKIP_INIT=1, entry point never run) and the
# aqt-side attributes plus.py relies on.
#
# Run with: "/Users/mattyc/Library/Application Support/AnkiProgramFiles/.venv/bin/python" headless_sync_ankihub_test.py
#
# ZERO NETWORK by construction AND by enforcement: a process-wide socket guard
# is installed before anything heavy loads; any connection attempt raises and
# is recorded, and the suite fails if the attempt log is non-empty. No sync is
# ever started (col.sync_collection / col.sync_status network paths are never
# called) and no suggestion function is ever CALLED — only inspect.signature'd.
# The add-on's entry_point module must never enter sys.modules.
#
# Scratch collection lives under the session scratchpad (fallback: mkdtemp);
# NEVER under ~/Library. The add-on directory is read from, never written to
# (sys.dont_write_bytecode keeps __pycache__ writes out of ~/Library).

import ast
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

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_PATH = os.path.join(REPO, "connect_plus", "core.py")
PLUS_PATH = os.path.join(REPO, "connect_plus", "plus.py")

ADDONS21 = os.path.expanduser("~/Library/Application Support/Anki2/addons21")
ADDON_PKG = "1322529746"
ADDON_DIR = os.path.join(ADDONS21, ADDON_PKG)

_PREFERRED_SCRATCH = ("/private/tmp/claude-501/-Users-mattyc-Downloads-prite-daily-main/"
                      "6b24b91e-e4dc-4cbf-934f-6e83d3ff850a/scratchpad/ancp_sa_r1")


def _pick_scratch():
    env = os.environ.get("ANCP_TEST_SCRATCH")
    if env:
        return env
    try:
        os.makedirs(_PREFERRED_SCRATCH, exist_ok=True)
        return os.path.join(_PREFERRED_SCRATCH, "col_scratch")
    except OSError:
        return tempfile.mkdtemp(prefix="ancp_sa_r1_")


SCRATCH = _pick_scratch()
assert not SCRATCH.startswith(os.path.expanduser("~/Library")), \
    "scratch dir must not be under ~/Library"
assert "Anki2" not in SCRATCH
if os.path.exists(SCRATCH):
    shutil.rmtree(SCRATCH)
os.makedirs(SCRATCH)

# never write .pyc into the (read-only to us) add-on dir under ~/Library
sys.dont_write_bytecode = True

# ---------------------------------------------------------------- core load
# load core.py standalone (no package __init__, no aqt) and verify purity
spec = importlib.util.spec_from_file_location("core", CORE_PATH)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
assert "aqt" not in sys.modules, "core.py (or its imports) pulled in aqt"
assert not any(m.startswith("PyQt6") for m in sys.modules), \
    "core.py import pulled in PyQt6"
assert ADDON_PKG not in sys.modules, "core.py must never import the AnkiHub add-on"

# ---------------------------------------------------------------- net guard
# process-wide: ANY python-level connection attempt raises and is recorded.
# (The rust backend has its own network stack, but its network entry points —
# sync_collection/sync_status/full sync — are simply never called here.)
NETWORK_ATTEMPTS = []


def _make_deny(name):
    def _deny(*args, **kwargs):
        NETWORK_ATTEMPTS.append((name, args[:2]))
        raise RuntimeError("network access blocked by headless_sync_ankihub_test "
                           "(%s)" % name)
    return _deny


socket.socket.connect = _make_deny("socket.connect")
socket.socket.connect_ex = _make_deny("socket.connect_ex")
socket.create_connection = _make_deny("socket.create_connection")
socket.getaddrinfo = _make_deny("socket.getaddrinfo")

# ---------------------------------------------------------------- anki setup
import anki.lang  # noqa: E402
anki.lang.set_lang("en_US")
import anki.sync  # noqa: E402
from anki.collection import Collection  # noqa: E402
from anki.errors import (Interrupted, NetworkError, SyncError,  # noqa: E402
                         SyncErrorKind)
from anki.sync_pb2 import SyncCollectionResponse, SyncStatusResponse  # noqa: E402

col = Collection(os.path.join(SCRATCH, "sync_ankihub.anki2"))

RESULTS = []


def run(name, fn):
    try:
        fn()
        RESULTS.append((name, True, ""))
        print("PASS  %s" % name)
    except Exception:
        tb = traceback.format_exc()
        RESULTS.append((name, False, tb))
        print("FAIL  %s\n%s" % (name, tb))


def expect_raises(fn, fragment):
    try:
        fn()
    except Exception as e:
        assert fragment in str(e), "expected %r in %r" % (fragment, str(e))
        return str(e)
    raise AssertionError("expected an exception containing %r" % fragment)


# ================================================================ part 1
# sync pure helpers (core.py)

def test1a_sync_enum_maps():
    S = SyncStatusResponse
    assert core.SYNC_STATUS_REQUIRED[S.NO_CHANGES] == "no_changes"
    assert core.SYNC_STATUS_REQUIRED[S.NORMAL_SYNC] == "normal_sync"
    assert core.SYNC_STATUS_REQUIRED[S.FULL_SYNC] == "full_sync_required"
    assert set(core.SYNC_STATUS_REQUIRED) == {0, 1, 2}
    C = SyncCollectionResponse
    assert core.SYNC_COLLECTION_REQUIRED[C.NO_CHANGES] == "no_changes"
    assert core.SYNC_COLLECTION_REQUIRED[C.NORMAL_SYNC] == "normal_sync"
    assert core.SYNC_COLLECTION_REQUIRED[C.FULL_SYNC] == "full_sync"
    # values 3 and 4, both by literal int and by installed proto constant
    assert C.FULL_DOWNLOAD == 3 and C.FULL_UPLOAD == 4
    assert core.SYNC_COLLECTION_REQUIRED[3] == "full_download"
    assert core.SYNC_COLLECTION_REQUIRED[4] == "full_upload"
    assert core.SYNC_COLLECTION_REQUIRED[C.FULL_DOWNLOAD] == "full_download"
    assert core.SYNC_COLLECTION_REQUIRED[C.FULL_UPLOAD] == "full_upload"
    assert set(core.SYNC_COLLECTION_REQUIRED) == {0, 1, 2, 3, 4}


def test1b_local_dirty_lifecycle():
    # fresh collection: ls == 0, mod == 0. mod > ls is False, but scm > ls
    # (schema stamped at creation) so the helper reports dirty — correct:
    # a never-synced collection has everything to send. SPEC 18 contract is
    # dirty = mod > ls or schema_changed, asserted exactly.
    d = core.local_sync_dirty(col)
    assert set(d) == {"lastSyncMs", "modMs", "dirty"}
    assert isinstance(d["lastSyncMs"], int) and isinstance(d["modMs"], int)
    assert isinstance(d["dirty"], bool)
    assert d["lastSyncMs"] == 0, d
    assert d["dirty"] is bool(d["modMs"] > d["lastSyncMs"] or col.schema_changed())

    # a write bumps mod above ls -> dirty specifically via mod > ls
    col.decks.id("SyncDirtyDeck")
    d2 = core.local_sync_dirty(col)
    assert d2["modMs"] > d2["lastSyncMs"], d2
    assert d2["dirty"] is True, d2

    # simulate "just synced" (ls >= mod and ls >= scm via raw col-table
    # update on the SCRATCH collection) -> clean branch
    _ls, mod, scm = col.db.first("select ls, mod, scm from col")
    col.db.execute("update col set ls = ?", max(mod, scm) + 1)
    assert col.schema_changed() in (0, False)
    d3 = core.local_sync_dirty(col)
    assert d3["dirty"] is False, d3
    assert isinstance(d3["dirty"], bool)  # bool(), not sqlite's raw 0


def test1c_classify_sync_error():
    def sync_err(kind):
        return SyncError("boom", None, None, None, kind)

    assert core.classify_sync_error(sync_err(SyncErrorKind.AUTH)) == "auth_failed"
    assert core.classify_sync_error(sync_err(SyncErrorKind.OTHER)) == "error"
    assert core.classify_sync_error(NetworkError("net down", None, None, None)) == "offline"
    assert core.classify_sync_error(Interrupted("stop", None, None, None)) == "aborted"
    assert core.classify_sync_error(RuntimeError("misc")) == "error"
    assert core.classify_sync_error(Exception("generic")) == "error"
    # SyncError is a BackendError, not a NetworkError: AUTH must not be 'offline'
    assert core.classify_sync_error(sync_err(SyncErrorKind.AUTH)) != "offline"


def test1d_bounded_sync_auth():
    auth = anki.sync.SyncAuth(hkey="k123", endpoint="https://sync.example/",
                              io_timeout_secs=60)
    b = core.bounded_sync_auth(auth, 8)
    assert b.hkey == "k123" and b.endpoint == "https://sync.example/"
    assert b.io_timeout_secs == 8
    auth2 = anki.sync.SyncAuth(hkey="k456", io_timeout_secs=60)
    b2 = core.bounded_sync_auth(auth2, 5)
    assert not b2.HasField("endpoint")
    for bad in (0, -1, True, "8", 2.5, None):
        expect_raises(lambda x=bad: core.bounded_sync_auth(auth, x),
                      "invalid parameter: timeoutSecs")


# ================================================================ part 2
# AnkiHub pure helpers (core.py), byte-exact against the installed dialog code

SUGGESTION_DIALOG_PATH = os.path.join(ADDON_DIR, "gui", "suggestion_dialog.py")


def test2a_change_type_validation():
    wire_values = ("updated_content", "new_content", "spelling/grammar",
                   "content_error", "new_card_to_add", "new_tags",
                   "updated_tags", "delete", "other")
    assert core.ANKIHUB_CHANGE_TYPES == wire_values
    for wire in wire_values:
        assert core.validate_ankihub_change_type(wire) == wire
    for bad in ("Updated content", "UPDATED_CONTENT", "bogus", "", None, 3,
                ["delete"], {"delete": 1}, True):
        expect_raises(lambda b=bad: core.validate_ankihub_change_type(b),
                      "invalid parameter: changeType")


def test2b_rationale_rules():
    assert core.ANKIHUB_RATIONALE_MAX_LENGTH == 1024
    assert core.validate_ankihub_rationale("fix typo") == "fix typo"
    # the dialog widget deletes chars while len >= 1024
    # (suggestion_dialog.py:676-677), so its effective cap — byte-matched by
    # the API — is 1023: 1023 ok, 1024 and 1025 rejected.
    ok = "x" * 1023
    assert core.validate_ankihub_rationale(ok) == ok
    expect_raises(lambda: core.validate_ankihub_rationale("x" * 1024),
                  "RATIONALE_INVALID")
    expect_raises(lambda: core.validate_ankihub_rationale("x" * 1025),
                  "RATIONALE_INVALID")
    for bad in ("", "   ", " \n\t", None, 5, ["r"]):
        expect_raises(lambda b=bad: core.validate_ankihub_rationale(b),
                      "RATIONALE_INVALID")


def test2c_dialog_source_format_still_matches():
    # derive the expected comment format from the INSTALLED add-on's own code;
    # if any of these lines changed, the byte-exact expectations below would
    # no longer be known-good
    with open(SUGGESTION_DIALOG_PATH, encoding="utf-8") as handle:
        src = handle.read()
    fold_line = ('result += f"\\nSource: {suggestion_meta.source.source_type.value}'
                 ' - {suggestion_meta.source.source_text}"')
    assert fold_line in src, "dialog fold line changed: " + fold_line
    assert "if suggestion_meta.source and suggestion_meta.source.source_text.strip():" in src
    assert 'source = f"{step} {source}"' in src  # UWorld step prefix
    for enum_line in ('AMBOSS = "AMBOSS"', 'UWORLD = "UWorld"',
                      'SOCIETY_GUIDELINES = "Society Guidelines"',
                      'DUPLICATE_NOTE = "Duplicate Note"', 'OTHER = "Other"'):
        assert enum_line in src, "SourceType enum changed: " + enum_line
    for step_opt in ('"Step 1"', '"Step 2"', '"Step 3"'):
        assert step_opt in src, "UWORLD_STEP_OPTIONS changed: " + step_opt


def test2d_comment_builder_byte_exact():
    # change suggestion, AnKing deck, each source type, exact bytes
    c = core.ankihub_comment_for_update
    assert c("Why", "updated_content",
             {"type": "AMBOSS", "text": "https://next.amboss.com/us/x"}, True) \
        == "Why\nSource: AMBOSS - https://next.amboss.com/us/x"
    for step in (1, 2, 3):
        assert c("r", "updated_content",
                 {"type": "UWorld", "text": "4211", "step": step}, True) \
            == "r\nSource: UWorld - Step %d 4211" % step
    assert c("r", "new_content",
             {"type": "Society Guidelines", "text": "https://acc.org/g"}, True) \
        == "r\nSource: Society Guidelines - https://acc.org/g"
    assert c("r", "new_content", {"type": "Other", "text": "First Aid p.123"},
             True) == "r\nSource: Other - First Aid p.123"
    assert c("dupe", "delete",
             {"type": "Duplicate Note", "text": "1601234567890"}, False) \
        == "dupe\nSource: Duplicate Note - 1601234567890"
    # blank optional source folds nothing (dialog's .strip() gate)
    assert c("dupe", "delete", {"type": "Duplicate Note", "text": "  "},
             True) == "dupe"
    # new-note builder folds identically (locked API extension)
    n = core.ankihub_comment_for_new_note
    assert n("add", {"type": "UWorld", "text": "999", "step": 3}) \
        == "add\nSource: UWorld - Step 3 999"
    assert n("add", {"type": "AMBOSS", "text": "https://a"}) \
        == "add\nSource: AMBOSS - https://a"
    assert n("add", None) == "add"
    # UWorld step shape rules
    expect_raises(lambda: c("r", "updated_content",
                            {"type": "UWorld", "text": "1"}, True),
                  "invalid parameter: source.step")
    expect_raises(lambda: c("r", "updated_content",
                            {"type": "AMBOSS", "text": "1", "step": 2}, True),
                  "invalid parameter: source.step")
    for bad_step in (0, 4, True, "2", 2.0):
        expect_raises(lambda s=bad_step: c(
            "r", "updated_content",
            {"type": "UWorld", "text": "1", "step": s}, True),
            "invalid parameter: source.step")


def test2e_source_required_decision():
    c = core.ankihub_comment_for_update
    # AnKing deck + updated_content, no source -> REQUIRED
    expect_raises(lambda: c("r", "updated_content", None, True),
                  "SOURCE_REQUIRED")
    expect_raises(lambda: c("r", "new_content", None, True), "SOURCE_REQUIRED")
    # required source present but blank text -> still SOURCE_REQUIRED
    expect_raises(lambda: c("r", "updated_content",
                            {"type": "AMBOSS", "text": "   "}, True),
                  "SOURCE_REQUIRED")
    # AnKing deck + spelling/grammar -> NOT required (and a source is rejected)
    assert c("r", "spelling/grammar", None, True) == "r"
    expect_raises(lambda: c("r", "spelling/grammar",
                            {"type": "AMBOSS", "text": "x"}, True),
                  "invalid parameter: source")
    # other (non-AnKing) deck + updated_content -> NOT required
    assert c("r", "updated_content", None, False) == "r"
    expect_raises(lambda: c("r", "updated_content",
                            {"type": "AMBOSS", "text": "x"}, False),
                  "invalid parameter: source")
    # delete: optional on any deck, Duplicate Note only
    assert c("r", "delete", None, True) == "r"
    assert c("r", "delete", None, False) == "r"
    expect_raises(lambda: c("r", "delete", {"type": "AMBOSS", "text": "x"},
                            True), "invalid parameter: source.type")
    # new-note builder: Duplicate Note cannot describe a brand-new note
    expect_raises(lambda: core.ankihub_comment_for_new_note(
        "add", {"type": "Duplicate Note", "text": "x"}),
        "invalid parameter: source.type")


# ================================================================ part 4
# aqt-side signature compat for the sync wrappers (imported BEFORE the add-on
# so venv-resolved deps win over the add-on's vendored lib/ copies)

def test4_aqt_signature_compat():
    import aqt.gui_hooks
    import aqt.mediasync
    import aqt.profiles
    import aqt.taskman

    pm = aqt.profiles.ProfileManager
    for name in ("sync_auth", "media_syncing_enabled", "set_host_number",
                 "set_current_sync_url", "clear_sync_auth"):
        assert callable(getattr(pm, name, None)), \
            "ProfileManager.%s missing" % name
    assert list(inspect.signature(pm.set_host_number).parameters) == ["self", "val"]
    assert "url" in inspect.signature(pm.set_current_sync_url).parameters

    ms = aqt.mediasync.MediaSyncer
    for name in ("is_syncing", "seconds_since_last_sync", "start_monitoring"):
        assert callable(getattr(ms, name, None)), "MediaSyncer.%s missing" % name

    for name in ("sync_status", "sync_collection", "media_sync_status"):
        assert callable(getattr(Collection, name, None)), \
            "Collection.%s missing" % name
    assert list(inspect.signature(Collection.sync_collection).parameters) == \
        ["self", "auth", "sync_media"]
    assert list(inspect.signature(Collection.sync_status).parameters) == \
        ["self", "auth"]

    tm_params = inspect.signature(aqt.taskman.TaskManager.run_in_background).parameters
    for name in ("task", "on_done", "uses_collection"):
        assert name in tm_params, "TaskManager.run_in_background lost %r" % name

    for hook in ("sync_will_start", "sync_did_finish",
                 "media_sync_did_start_or_stop"):
        assert callable(getattr(aqt.gui_hooks, hook, None)), \
            "gui_hooks.%s missing" % hook


# ================================================================ part 3
# signature-compat gate against the INSTALLED AnkiHub add-on (drift alarm).
# SKIP_INIT=1 (the add-on's own test hook, __init__.py:16/27) keeps
# entry_point — the real AnkiHub sync machinery — from ever running.

def _installed_addon_version():
    try:
        with open(os.path.join(ADDON_DIR, "manifest.json"), encoding="utf-8") as h:
            v = json.load(h).get("version")
        if v:
            return v
    except Exception:
        pass
    try:
        with open(os.path.join(ADDON_DIR, "VERSION"), encoding="utf-8") as h:
            return h.read().strip()
    except Exception:
        return "<unreadable>"


def _drift(detail):
    raise AssertionError(
        "AnkiHub addon drifted from tested version %s (installed: %s): %s"
        % (core.ANKIHUB_TESTED_ADDON_VERSION, _installed_addon_version(), detail))


def test3_ankihub_addon_signature_gate():
    if not os.path.isdir(ADDON_DIR):
        _drift("add-on directory %s is missing" % ADDON_DIR)

    os.environ["SKIP_INIT"] = "1"
    if ADDONS21 not in sys.path:
        sys.path.insert(0, ADDONS21)
    try:
        suggestions = importlib.import_module(ADDON_PKG + ".main.suggestions")
        models = importlib.import_module(ADDON_PKG + ".ankihub_client.models")
        settings = importlib.import_module(ADDON_PKG + ".settings")
    except Exception as err:
        _drift("import failed: %r" % (err,))

    # the entry point (real sync machinery) must never have run
    assert ADDON_PKG + ".entry_point" not in sys.modules, \
        "SKIP_INIT was ignored - entry_point was imported"

    # every function plus.py passes kwargs to still accepts every parameter
    for fn_name, required in sorted(core.ANKIHUB_REQUIRED_SIGNATURES.items()):
        fn = getattr(suggestions, fn_name, None)
        if fn is None:
            _drift("main.suggestions.%s is missing" % fn_name)
        try:
            params = list(inspect.signature(fn).parameters)
        except (TypeError, ValueError):
            _drift("main.suggestions.%s has an unreadable signature" % fn_name)
        missing = core.ankihub_missing_params(params, fn_name)
        if missing:
            _drift("main.suggestions.%s lacks parameter(s): %s"
                   % (fn_name, ", ".join(missing)))

    # explicit re-check of the two wrappers' full kwarg sets as plus.py calls them
    upd = set(inspect.signature(suggestions.suggest_note_update).parameters)
    if not {"note", "change_type", "comment", "media_upload_cb",
            "auto_accept"} <= upd:
        _drift("suggest_note_update signature: %s" % sorted(upd))
    new = set(inspect.signature(suggestions.suggest_new_note).parameters)
    if not {"note", "comment", "ankihub_did", "media_upload_cb",
            "auto_accept"} <= new:
        _drift("suggest_new_note signature: %s" % sorted(new))

    # SuggestionType still carries all nine wire values ((wire, label) tuples)
    st = getattr(models, "SuggestionType", None)
    if st is None:
        _drift("ankihub_client.models.SuggestionType is missing")
    wire = set()
    for member in st:
        wire.add(member.value[0] if isinstance(member.value, tuple)
                 else member.value)
    lost = sorted(set(core.ANKIHUB_CHANGE_TYPES) - wire)
    if lost:
        _drift("SuggestionType lost wire value(s): %s" % ", ".join(lost))

    # ChangeSuggestionResult still carries all four members
    results = getattr(suggestions, "ChangeSuggestionResult", None)
    if results is None:
        _drift("main.suggestions.ChangeSuggestionResult is missing")
    member_names = {member.name for member in results}
    lost_members = sorted(set(core.ANKIHUB_CHANGE_RESULTS) - member_names)
    if lost_members:
        _drift("ChangeSuggestionResult lost member(s): %s" % ", ".join(lost_members))

    # settings constants the bridge byte-matches
    if getattr(settings, "RATIONALE_FOR_CHANGE_MAX_LENGTH", None) != 1024:
        _drift("settings.RATIONALE_FOR_CHANGE_MAX_LENGTH is %r, expected 1024"
               % getattr(settings, "RATIONALE_FOR_CHANGE_MAX_LENGTH", None))
    assert settings.RATIONALE_FOR_CHANGE_MAX_LENGTH == core.ANKIHUB_RATIONALE_MAX_LENGTH
    config = getattr(settings, "config", None)
    if config is None:
        _drift("settings.config singleton is missing")
    if not hasattr(config, "anking_deck_id"):
        _drift("settings.config.anking_deck_id attribute is missing")
    if not callable(getattr(config, "is_logged_in", None)):
        _drift("settings.config.is_logged_in is missing")
    # the AnKing production deck uuid constant still present in settings source
    with open(os.path.join(ADDON_DIR, "settings.py"), encoding="utf-8") as h:
        settings_src = h.read()
    if "e77aedfe-a636-40e2-8169-2fce2673187e" not in settings_src:
        _drift("AnKing production deck uuid constant left settings.py")


# ================================================================ part 5
# wrapper static checks: ast over plus.py, no instantiation

def _plus_mixin_api_methods():
    # api-marking decorators: bare @util.api() (pre-SPEC-25) or @plus_api()
    # (SPEC 25 — plus_api wraps every action in the stable-error-code catch
    # and applies util.api() itself, so it IS the api marker now)
    with open(PLUS_PATH, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    mixin = next(node for node in tree.body
                 if isinstance(node, ast.ClassDef) and node.name == "PlusMixin")
    api_methods = {}
    for node in mixin.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            is_util_api = (isinstance(dec, ast.Call)
                           and isinstance(dec.func, ast.Attribute)
                           and dec.func.attr == "api"
                           and isinstance(dec.func.value, ast.Name)
                           and dec.func.value.id == "util")
            is_plus_api = (isinstance(dec, ast.Call)
                           and isinstance(dec.func, ast.Name)
                           and dec.func.id == "plus_api")
            if is_util_api or is_plus_api:
                api_methods[node.name] = node
    return api_methods


def _arg_spec(fn_node):
    args = fn_node.args
    names = [a.arg for a in args.args]
    defaults = {}
    for arg, default in zip(args.args[len(args.args) - len(args.defaults):],
                            args.defaults):
        defaults[arg.arg] = (default.value if isinstance(default, ast.Constant)
                             else ast.dump(default))
    return names, defaults


def test5_wrapper_static_checks():
    api_methods = _plus_mixin_api_methods()
    # PLUS_ACTIONS lists exactly 36 actions == the api-decorated mixin methods
    # (36 = 24 + round-2 SPEC 22/23: mediaExists, storeMediaFilesBulk
    #         + round-3 SPEC 26: undoStatus
    #         + round-4 SPEC 28: renameDeck, bulkSetFlag, renameTag
    #         + round-4 SPEC 29/30: filteredDeckReport, emptyFilteredDeck,
    #           getEmptyCards, deleteEmptyCards
    #         + revision-19 SPEC 32: createFilteredDeck, rebuildFilteredDeck)
    assert len(core.PLUS_ACTIONS) == 36, core.PLUS_ACTIONS
    assert len(set(core.PLUS_ACTIONS)) == 36, "duplicate action names"
    assert set(api_methods) == set(core.PLUS_ACTIONS), (
        "PLUS_ACTIONS vs @util.api methods mismatch: only-in-actions=%s "
        "only-in-mixin=%s" % (sorted(set(core.PLUS_ACTIONS) - set(api_methods)),
                              sorted(set(api_methods) - set(core.PLUS_ACTIONS))))
    assert core.PLUS_ACTIONS[-1] == "plusInfo"

    # the five new wrappers exist with SPEC 18/19-matching parameter names
    names, defaults = _arg_spec(api_methods["syncNow"])
    assert names == ["self"], names

    names, defaults = _arg_spec(api_methods["syncStatus"])
    assert names == ["self", "localOnly", "timeoutSecs"], names
    assert defaults == {"localOnly": False, "timeoutSecs": 8}, defaults

    names, defaults = _arg_spec(api_methods["ankihubStatus"])
    assert names == ["self"], names

    names, defaults = _arg_spec(api_methods["ankihubSuggestNoteUpdate"])
    assert names == ["self", "note", "changeType", "rationale", "source",
                     "autoAccept"], names
    assert defaults == {"source": None, "autoAccept": False}, defaults

    names, defaults = _arg_spec(api_methods["ankihubSuggestNewNote"])
    assert names == ["self", "note", "rationale", "source", "deckId",
                     "autoAccept", "resubmitAsChangeOnDuplicate"], names
    assert defaults == {"source": None, "deckId": None, "autoAccept": False,
                        "resubmitAsChangeOnDuplicate": True}, defaults

    # round-3 (SPEC 12/13/20/26) wrapper surface
    names, defaults = _arg_spec(api_methods["undoStatus"])
    assert names == ["self"], names

    names, defaults = _arg_spec(api_methods["renderCard"])
    assert names == ["self", "cardIds", "format", "cssMode"], names
    assert defaults == {"format": "html", "cssMode": None}, defaults

    names, defaults = _arg_spec(api_methods["notesSlim"])
    assert names[-1] == "omitEmptyFields", names
    assert defaults["omitEmptyFields"] is False, defaults

    names, defaults = _arg_spec(api_methods["checkDeckIntegrity"])
    assert names == ["self", "deckName", "includeOrphanMedia",
                     "orphanMediaLimit"], names
    # the wrapper default must be a JSON literal (actionDocs renders it with
    # json.dumps), so it is spelled out — held in lockstep with core here
    assert defaults["orphanMediaLimit"] == core.ORPHAN_MEDIA_DEFAULT_LIMIT, defaults

    # no kwarg-swallowing on the API surface
    for action, node in api_methods.items():
        assert node.args.vararg is None and node.args.kwarg is None, action


def _load_plus():
    """plus.py as a REAL module through a synthetic package (connect_plus's
    __init__.py, which boots the add-on against aqt.mw, never runs)."""
    import types
    pkg_name = "ancp_sig_pkg"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [os.path.join(REPO, "connect_plus")]
        sys.modules[pkg_name] = pkg
    return importlib.import_module(pkg_name + ".plus")


def test7_sync_status_server_checked():
    # SPEC 18.2 revision 12: serverChecked must be TRUE only when this call
    # really completed a status round trip. rslib short-circuits the request
    # whenever the collection is locally dirty (measured against an
    # unreachable endpoint: dirty answered in 0.018 ms with no socket opened,
    # clean raised NetworkError after attempting one), which is exactly
    # core.local_sync_dirty's predicate — so the flag is derived, never guessed.
    import anki.sync
    from anki.sync_pb2 import SyncStatusResponse
    plus = _load_plus()

    class FakeMediaSyncer:
        def is_syncing(self):
            return False

        def seconds_since_last_sync(self):
            return 0

    class FakePM:
        def sync_auth(self):
            return anki.sync.SyncAuth(hkey="fake-key", endpoint=None,
                                      io_timeout_secs=60)

        def set_current_sync_url(self, url):  # pragma: no cover
            raise AssertionError("unexpected endpoint rewrite: %r" % url)

    class FakeMW:
        def __init__(self, collection):
            self.col = collection
            self.pm = FakePM()
            self.media_syncer = FakeMediaSyncer()

    class FakeAC(plus.PlusMixin):
        def __init__(self, mw):
            self._mw = mw

        def window(self):
            return self._mw

    inst = FakeAC(FakeMW(col))
    canned = {"required": SyncStatusResponse.NORMAL_SYNC}
    # stub the backend probe: no socket, and the response carries no
    # round-trip flag anyway (verified — only 'required' + 'new_endpoint')
    col.sync_status = lambda auth: SyncStatusResponse(required=canned["required"])
    try:
        # dirty collection -> the backend answers locally; NOT server-verified
        col.decks.id("SyncStatusDirtyDeck")
        assert core.local_sync_dirty(col)["dirty"] is True
        out = inst.syncStatus()
        assert out["required"] == "normal_sync", out
        assert out["serverChecked"] is False, out

        # clean collection -> the probe really goes out
        _ls, mod, scm = col.db.first("select ls, mod, scm from col")
        col.db.execute("update col set ls = ?", max(mod, scm) + 1)
        assert core.local_sync_dirty(col)["dirty"] is False
        canned["required"] = SyncStatusResponse.NO_CHANGES
        out = inst.syncStatus()
        assert out["required"] == "no_changes", out
        assert out["serverChecked"] is True, out

        # localOnly never opens a socket, so it is never server-verified
        out = inst.syncStatus(localOnly=True)
        assert out["required"] == "unknown_no_network", out
        assert out["serverChecked"] is False, out

        # localOnly + schema changed -> full_sync_required, not normal_sync
        # (the backend's OWN local verdict for scm > ls; reporting
        # 'normal_sync' here under-reported a collection that cannot converge)
        ls = col.db.scalar("select ls from col")
        col.db.execute("update col set scm = ?", ls + 1)
        assert col.schema_changed()
        out = inst.syncStatus(localOnly=True)
        assert out["required"] == "full_sync_required", out
        assert out["serverChecked"] is False, out

        # plain local changes still report normal_sync
        col.db.execute("update col set scm = ?, mod = ?", ls - 1, ls + 1)
        assert not col.schema_changed()
        out = inst.syncStatus(localOnly=True)
        assert out["required"] == "normal_sync", out
    finally:
        del col.sync_status


def test5b_signature_string_docs():
    # SPEC 4.9 edge case: every actionDocs `params` string matches the
    # wrapper's real signature. plus.py is loaded as a REAL module through a
    # synthetic package (types.ModuleType with __path__ only — connect_plus's
    # __init__.py, which boots the add-on against aqt.mw, never runs), so this
    # exercises the LIVE util.api()-decorated methods and the LIVE
    # _signature_string. If util.api() ever gains a wrapper that destroys
    # inspect.signature (functools-less, or any *args/**kwargs shim), every
    # params string silently degrades — this is the alarm for that.
    plus = _load_plus()

    api_methods = _plus_mixin_api_methods()
    mixin = plus.PlusMixin()  # no __init__; never dispatched, only reflected
    for name in core.PLUS_ACTIONS:
        arg_names, ast_defaults = _arg_spec(api_methods[name])
        assert arg_names and arg_names[0] == "self", (name, arg_names)
        expected = ", ".join(
            "%s=%s" % (p, json.dumps(ast_defaults[p])) if p in ast_defaults else p
            for p in arg_names[1:])
        rendered = plus._signature_string(getattr(mixin, name))
        assert rendered == expected, (name, rendered, expected)
        # the bound method really excludes self and exposes the AST params
        assert list(inspect.signature(getattr(mixin, name)).parameters) == \
            arg_names[1:], name


# ================================================================ run
run("test1a_sync_enum_maps", test1a_sync_enum_maps)
run("test1b_local_dirty_lifecycle", test1b_local_dirty_lifecycle)
run("test1c_classify_sync_error", test1c_classify_sync_error)
run("test1d_bounded_sync_auth", test1d_bounded_sync_auth)
run("test2a_change_type_validation", test2a_change_type_validation)
run("test2b_rationale_rules", test2b_rationale_rules)
run("test2c_dialog_source_format_still_matches", test2c_dialog_source_format_still_matches)
run("test2d_comment_builder_byte_exact", test2d_comment_builder_byte_exact)
run("test2e_source_required_decision", test2e_source_required_decision)
run("test4_aqt_signature_compat", test4_aqt_signature_compat)
run("test3_ankihub_addon_signature_gate", test3_ankihub_addon_signature_gate)
run("test5_wrapper_static_checks", test5_wrapper_static_checks)
run("test5b_signature_string_docs", test5b_signature_string_docs)
run("test7_sync_status_server_checked", test7_sync_status_server_checked)


def test6_no_network_no_entry_point():
    # the whole suite made ZERO python-level connection attempts, and the
    # add-on's entry point (real sync/suggestion machinery) never loaded
    assert NETWORK_ATTEMPTS == [], NETWORK_ATTEMPTS
    assert ADDON_PKG + ".entry_point" not in sys.modules
    assert ADDON_PKG + ".gui.suggestion_dialog" not in sys.modules


run("test6_no_network_no_entry_point", test6_no_network_no_entry_point)

col.close()

print("\n===== SUMMARY =====")
n_pass = sum(1 for _, ok, _ in RESULTS if ok)
for name, ok, _ in RESULTS:
    print("%s  %s" % ("PASS" if ok else "FAIL", name))
print("%d/%d passed" % (n_pass, len(RESULTS)))
sys.exit(0 if n_pass == len(RESULTS) else 1)
