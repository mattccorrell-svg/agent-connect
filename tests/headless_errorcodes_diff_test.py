# Headless verification for the ROUND-2 field-feedback items C, E, F:
# bulkUpdateNoteFields dryRun diff preview (SPEC 4.2/15, revision 10),
# stable '[code] ' error prefixes on every raised Plus error (SPEC 25),
# and the discoverability lock (SPEC 4.9 recipes + the SPEC 13
# raw-fidelity-field-projection naming).
#
# Run with: "/Users/mattyc/Library/Application Support/AnkiProgramFiles/.venv/bin/python" headless_errorcodes_diff_test.py
#
# Uses a FRESH scratch collection; never touches ~/Library/Application
# Support/Anki2/. ZERO NETWORK by construction AND by enforcement (socket
# guard installed before anki loads; the suite fails on any attempt).

import importlib
import importlib.util
import json
import os
import shutil
import socket
import sys
import tempfile
import time
import traceback
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_PATH = os.path.join(REPO, "connect_plus", "core.py")

_PREFERRED_SCRATCH = ("/private/tmp/claude-501/-Users-mattyc-Downloads-prite-daily-main/"
                      "6b24b91e-e4dc-4cbf-934f-6e83d3ff850a/scratchpad/ancp_r2_cef")


def _pick_scratch():
    env = os.environ.get("ANCP_TEST_SCRATCH")
    if env:
        return env
    try:
        os.makedirs(_PREFERRED_SCRATCH, exist_ok=True)
        return os.path.join(_PREFERRED_SCRATCH, "col_scratch")
    except OSError:
        return tempfile.mkdtemp(prefix="ancp_r2_cef_")


SCRATCH = _pick_scratch()
# safety guards
assert not SCRATCH.startswith(os.path.expanduser("~/Library")), \
    "scratch dir must not be under ~/Library"
assert "Anki2" not in SCRATCH
if os.path.exists(SCRATCH):
    shutil.rmtree(SCRATCH)
os.makedirs(SCRATCH)

sys.dont_write_bytecode = True

# ---------------------------------------------------------------- core load
# load core.py standalone (no package __init__, no aqt) and verify purity
spec = importlib.util.spec_from_file_location("core", CORE_PATH)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
assert "aqt" not in sys.modules, "core.py (or its imports) pulled in aqt"
assert not any(m.startswith("PyQt6") for m in sys.modules), \
    "core.py import pulled in PyQt6"

# ---------------------------------------------------------------- net guard
NETWORK_ATTEMPTS = []


def _make_deny(name):
    def _deny(*args, **kwargs):
        NETWORK_ATTEMPTS.append((name, args[:2]))
        raise RuntimeError("network access blocked by headless_errorcodes_diff_test "
                           "(%s)" % name)
    return _deny


socket.socket.connect = _make_deny("socket.connect")
socket.socket.connect_ex = _make_deny("socket.connect_ex")
socket.create_connection = _make_deny("socket.create_connection")
socket.getaddrinfo = _make_deny("socket.getaddrinfo")

# ---------------------------------------------------------------- anki setup
import anki.lang  # noqa: E402
anki.lang.set_lang("en_US")
from anki.collection import Collection  # noqa: E402

col = Collection(os.path.join(SCRATCH, "cef.anki2"))

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


def raised_code(fn):
    """Run fn, return (code, full message) parsed from its '[code] ' error."""
    try:
        fn()
    except Exception as e:
        msg = str(e)
        assert msg.startswith("["), "unprefixed error: %r" % msg
        return msg.split("] ", 1)[0].lstrip("["), msg
    raise AssertionError("expected an exception")


def undo_snap():
    return col.undo_status().SerializeToString()


def notes_snap():
    return col.db.all("select id, mod, usn, flds, tags from notes order by id")


def basic_note(deck, front, back="b"):
    return {"deckName": deck, "modelName": "Basic",
            "fields": {"Front": front, "Back": back}, "tags": []}


# ---------------------------------------------------------------- E: vocabulary
def test1_error_code_vocabulary():
    expected = {
        "not_found": False, "invalid_param": False, "deck_not_found": False,
        "duplicate": False, "unsupported_format": False, "io_error": False,
        # revision 17 slice 2: exportDeckApkg's fail-closed refusal (SPEC
        # 17/29.3) — born reachable, not retryable (the caller must change
        # something: empty the filter or pass allowFilteredOmission)
        "cards_in_filtered_decks": False,
        "batch_reverted": False, "collection_unavailable": True,
        "sync_in_progress": True, "not_logged_in": False, "auth_failed": False,
        "offline": True, "full_sync_required": False, "network_error": True,
        "rate_limited": True, "permission_denied": False,
        "validation_error": False, "incompatible_ankihub_addon": False,
        "source_required": False, "rationale_invalid": False, "internal": False,
        # revision 13 (round-3 ASK 11a): the dispatcher's unknown-action error
        # is now the one non-action error carrying a code, so this closed-set
        # lock grows by exactly one member.
        "unknown_action": False,
    }
    assert core.PLUS_ERROR_CODES == expected, core.PLUS_ERROR_CODES

    e = core.PlusError("deck_not_found", "deck was not found: X")
    assert str(e) == "[deck_not_found] deck was not found: X", str(e)
    assert e.code == "deck_not_found" and e.message == "deck was not found: X"
    assert e.retryable is False
    assert core.PlusError("offline", "x").retryable is True
    assert isinstance(e, Exception)
    # a typo'd code is an add-on bug and must fail loudly at raise time
    try:
        core.PlusError("no_such_code", "x")
        raise AssertionError("bogus code accepted")
    except ValueError as err:
        assert "unknown plus error code" in str(err)

    # every AnkiHub HTTP taxonomy code maps into the vocabulary
    assert set(core.ANKIHUB_CODE_TO_PLUS_CODE) == {
        "VALIDATION_ERROR", "ANKIHUB_NOT_LOGGED_IN", "PERMISSION_DENIED",
        "NOTE_DELETED_ON_ANKIHUB", "RATE_LIMITED", "NETWORK_ERROR"}
    for code in core.ANKIHUB_CODE_TO_PLUS_CODE.values():
        assert code in core.PLUS_ERROR_CODES, code
    assert core.ANKIHUB_CODE_TO_PLUS_CODE["ANKIHUB_NOT_LOGGED_IN"] == "auth_failed"


# ---------------------------------------------------------------- E: raise sites
def test2_raise_site_codes():
    col.decks.id("CEFDeck")
    added = core.bulk_add_notes(
        col, [basic_note("CEFDeck", "cef-%d" % i) for i in range(3)])["added"]

    # invalid_param family (house 'invalid parameter:' style)
    code, msg = raised_code(lambda: core.notes_slim(col))
    assert (code, msg) == ("invalid_param",
                           "[invalid_param] invalid parameter: query: exactly one of "
                           "query or noteIds required"), (code, msg)
    assert raised_code(lambda: core.bulk_add_tags(col, "x", "t"))[0] == "invalid_param"
    assert raised_code(lambda: core.sanitize_undo_label(5))[0] == "invalid_param"
    assert raised_code(lambda: core.bulk_set_due_date(col, [], "abc"))[0] == "invalid_param"

    # deck_not_found
    code, msg = raised_code(lambda: core.export_deck_apkg(col, "NoSuchDeckCEF"))
    assert code == "deck_not_found" and msg.endswith("deck was not found: NoSuchDeckCEF"), msg
    assert raised_code(lambda: core.check_deck_integrity(col, "NoSuchDeckCEF"))[0] == "deck_not_found"
    assert raised_code(lambda: core.query_revlog(col, deck_name="NoSuchDeckCEF"))[0] == "deck_not_found"

    # not_found
    assert raised_code(lambda: core.update_image_occlusion_note(col, 4242424242))[0] == "not_found"
    assert raised_code(lambda: core.crop_image(
        col, "cef-no-such.png", {"left": 0, "top": 0, "width": 1, "height": 1}))[0] == "not_found"

    # validation_error: well-formed request, wrong kind of note
    code, msg = raised_code(lambda: core.update_image_occlusion_note(col, added[0]))
    assert code == "validation_error" and "not an image occlusion note" in msg, msg

    # unsupported_format: a non-image media file cannot be crop-loaded
    fname = col.media.write_data("cef-not-an-image.txt", b"plain text bytes")
    code, msg = raised_code(lambda: core.crop_image(
        col, fname, {"left": 0, "top": 0, "width": 1, "height": 1}))
    assert code == "unsupported_format" and "could not load image" in msg, msg

    # AnkiHub pure-helper codes
    assert raised_code(lambda: core.validate_ankihub_rationale(""))[0] == "rationale_invalid"
    assert raised_code(lambda: core.validate_ankihub_rationale("x" * 2000))[0] == "rationale_invalid"
    assert raised_code(lambda: core.validate_ankihub_change_type("nope"))[0] == "invalid_param"
    assert raised_code(lambda: core.ankihub_comment_for_update(
        "r", "updated_content", None, True))[0] == "source_required"
    assert raised_code(lambda: core.ankihub_comment_for_update(
        "r", "other", {"type": "Other", "text": "t"}, False))[0] == "invalid_param"
    assert raised_code(lambda: core.map_ankihub_change_result("WAT"))[0] == "incompatible_ankihub_addon"

    # batch_reverted: prefix + the JSON report still parses after the house prefix
    original_update = col.update_note
    state = {"n": 0}

    def failing_update(note, *args, **kwargs):
        state["n"] += 1
        if state["n"] == 2:
            raise Exception("injected cef hard error")
        return original_update(note, *args, **kwargs)

    col.update_note = failing_update
    try:
        raised = None
        try:
            core.bulk_update_note_fields(col, [
                {"id": added[0], "fields": {"Back": "cef-x"}},
                {"id": added[1], "fields": {"Back": "cef-y"}},
            ])
        except Exception as e:
            raised = e
    finally:
        del col.update_note
    assert raised is not None
    msg = str(raised)
    prefix = "[batch_reverted] bulkUpdateNoteFields failed (batch reverted): "
    assert msg.startswith(prefix), msg
    report = json.loads(msg[len(prefix):])
    assert report["failedIndex"] == 1 and "injected cef hard error" in report["error"], report
    assert col.get_note(added[0])["Back"] == "b", "atomic revert failed"


# ---------------------------------------------------------------- E: per-item errors unprefixed
def test3_per_item_errors_not_prefixed():
    # per-item error STRINGS embedded in results are not raises: no prefix
    t = core.media_thumbnails(col, ["cef-gone.png"])["thumbnails"][0]
    assert t["error"] == "media file was not found: cef-gone.png", t

    s = core.store_media_files_bulk(col, [{"filename": "sub/x.png", "data": "aGk="}])["stored"][0]
    assert s["error"].startswith("invalid parameter:"), s
    assert not s["error"].startswith("["), s

    r = core.bulk_add_notes(col, [basic_note("NoSuchDeckCEF", "cef-skip")])
    assert r["skipped"][0]["reason"] == "deck was not found: NoSuchDeckCEF", r

    c = core.render_card(col, [4242424242])["cards"][0]
    assert c["error"] == "card was not found: 4242424242", c


# ---------------------------------------------------------------- C: diff preview
def test4_diff_preview():
    col.decks.id("DiffDeck")
    added = core.bulk_add_notes(col, [
        basic_note("DiffDeck", "d0", back="b0"),
        basic_note("DiffDeck", "d1", back="b1"),
        basic_note("DiffDeck", "d2", back="b2"),
    ])["added"]
    n0, n1, n2 = added
    n_snap, u_snap = notes_snap(), undo_snap()

    # revision 12 (round-3 field feedback, INVERTED assertion): a tags-only
    # entry used to land in wouldUpdate with NO preview row — 4 wouldUpdate
    # entries, 3 rows, and a reviewer with no way to see why. Tag changes now
    # emit one row under the reserved field name '__tags__'.
    r = core.bulk_update_note_fields(col, [
        {"id": n0, "fields": {"Front": "D0", "Back": "b0"}},   # Back unchanged -> omitted
        {"id": n1, "fields": {"Front": "d1"}},                 # full no-op -> unchanged
        {"id": n2, "tags": ["cef"]},                           # tags-only -> ONE __tags__ row
        {"id": 4242424242, "fields": {"Front": "x"}},          # skipped
    ], dry_run=True, diff=True)
    assert r["wouldUpdate"] == [n0, n2], r
    assert r["unchanged"] == [n1], r
    assert r["skipped"][0]["reason"] == "note was not found: 4242424242", r
    assert r["preview"] == [
        {"noteId": n0, "field": "Front", "before": "d0", "after": "D0"},
        {"noteId": n2, "field": "__tags__", "before": "", "after": "cef"},
    ], r
    assert r["previewTruncated"] is False and r["undoEntry"] is None, r
    # every wouldUpdate note is now represented in the preview
    assert {row["noteId"] for row in r["preview"]} == set(r["wouldUpdate"]), r

    # a note changing BOTH fields and tags gets both rows, fields first, and
    # an unchanged tag list contributes nothing (the dry run above wrote
    # nothing, so n2's stored tags are still empty)
    r = core.bulk_update_note_fields(col, [
        {"id": n2, "fields": {"Front": "D2"}, "tags": ["cef", "extra"]},
        {"id": n0, "fields": {"Front": "D0b"}, "tags": []},   # tags already []
    ], dry_run=True, diff=True)
    assert r["preview"] == [
        {"noteId": n2, "field": "Front", "before": "d2", "after": "D2"},
        {"noteId": n2, "field": "__tags__", "before": "", "after": "cef extra"},
        {"noteId": n0, "field": "Front", "before": "d0", "after": "D0b"},
    ], r

    # cap: one entry PER CHANGED FIELD, previewTruncated when entries remain
    r = core.bulk_update_note_fields(col, [
        {"id": n0, "fields": {"Front": "X0", "Back": "Y0"}},
        {"id": n1, "fields": {"Front": "X1"}},
    ], dry_run=True, diff=True, max_preview=2)
    assert len(r["preview"]) == 2 and r["previewTruncated"] is True, r
    assert r["preview"][0]["noteId"] == n0 and r["preview"][1]["noteId"] == n0, r
    # tag rows count toward maxPreview like any other row
    r = core.bulk_update_note_fields(col, [
        {"id": n0, "fields": {"Front": "X0"}, "tags": ["capped"]},
        {"id": n1, "fields": {"Front": "X1"}},
    ], dry_run=True, diff=True, max_preview=2)
    assert [row["field"] for row in r["preview"]] == ["Front", "__tags__"], r
    assert r["previewTruncated"] is True, r
    # maxPreview=0: empty preview, truncation signalled
    r = core.bulk_update_note_fields(col, [{"id": n0, "fields": {"Front": "X"}}],
                                     dry_run=True, diff=True, max_preview=0)
    assert r["preview"] == [] and r["previewTruncated"] is True, r

    # dry WITHOUT diff: pre-revision-10 shape, no preview keys
    r = core.bulk_update_note_fields(col, [{"id": n0, "fields": {"Front": "X"}}],
                                     dry_run=True)
    assert "preview" not in r and "previewTruncated" not in r, r

    # all of the above wrote NOTHING
    assert notes_snap() == n_snap and undo_snap() == u_snap, \
        "diff preview touched the collection"

    # diff is a preview feature: rejected without dryRun, before any write
    code, msg = raised_code(lambda: core.bulk_update_note_fields(
        col, [{"id": n0, "fields": {"Front": "X"}}], diff=True))
    assert msg == "[invalid_param] invalid parameter: diff: only valid with dryRun", msg
    assert raised_code(lambda: core.bulk_update_note_fields(
        col, [], dry_run=True, diff="yes"))[0] == "invalid_param"
    assert raised_code(lambda: core.bulk_update_note_fields(
        col, [], dry_run=True, diff=True, max_preview=-1))[0] == "invalid_param"
    assert notes_snap() == n_snap and undo_snap() == u_snap

    # dry-then-write: the real run (no diff) matches the dry prediction
    entries = [{"id": n0, "fields": {"Front": "D0-final"}},
               {"id": n1, "fields": {"Front": "d1"}}]
    dry = core.bulk_update_note_fields(col, entries, dry_run=True, diff=True)
    real = core.bulk_update_note_fields(col, entries)
    assert real["updated"] == dry["wouldUpdate"] == [n0], (dry, real)
    assert real["unchanged"] == dry["unchanged"] == [n1], (dry, real)
    assert col.get_note(n0)["Front"] == dry["preview"][0]["after"] == "D0-final"
    col.undo()


# ---------------------------------------------------------------- F: recipes + naming (core side)
def test5_discoverability_lock_core():
    names = [r["name"] for r in core.PLUS_RECIPES]
    for want in ("raw field projection", "verified-sync contract",
                 "dry-run-then-write pattern", "undo-label convention"):
        assert want in names, names
    for recipe in core.PLUS_RECIPES:
        assert set(recipe) == {"name", "description", "example"}, recipe
        assert recipe["description"].strip(), recipe
        assert recipe["example"].get("action") in core.PLUS_ACTIONS, recipe
        assert isinstance(recipe["example"].get("params"), dict), recipe

    # the raw recipe names the exact three-knob combination
    raw = next(r for r in core.PLUS_RECIPES if r["name"] == "raw field projection")
    assert "stripHtml=false" in raw["description"], raw
    assert "maxFieldLength=0" in raw["description"], raw
    assert "fields=[...]" in raw["description"], raw
    assert raw["example"]["params"]["stripHtml"] is False
    assert raw["example"]["params"]["maxFieldLength"] == 0
    assert isinstance(raw["example"]["params"]["fields"], list)

    # notesSlim's actionDocs summary carries the same naming (SPEC 13)
    slim = core.PLUS_ACTION_SUMMARIES["notesSlim"]
    assert "raw-fidelity field projection" in slim.lower(), slim
    assert "stripHtml=false" in slim and "maxFieldLength=0" in slim, slim


# ---------------------------------------------------------------- wrapper layer (imports plus.py -> aqt; keep last)
def test6_wrapper_layer():
    assert "aqt" not in sys.modules, "an earlier core-path test pulled in aqt"

    pkg_name = "ancp_cef_pkg"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [os.path.join(REPO, "connect_plus")]
        sys.modules[pkg_name] = pkg
    plus = importlib.import_module(pkg_name + ".plus")

    util_mod = sys.modules[pkg_name + ".util"]
    orig_setting = util_mod.setting
    util_mod.setting = lambda key: util_mod.DEFAULT_CONFIG[key]
    try:
        info = plus.PlusMixin().plusInfo()
    finally:
        util_mod.setting = orig_setting

    # F: plusInfo gains top-level recipes (same objects as core.PLUS_RECIPES)
    assert [r["name"] for r in info["recipes"]] == [r["name"] for r in core.PLUS_RECIPES]
    assert info["recipes"][0]["example"]["action"] == "notesSlim"

    # C: the wrapper signature carries the new params (actionDocs surface)
    docs = info["actionDocs"]
    params = docs["bulkUpdateNoteFields"]["params"]
    assert "diff=false" in params and "maxPreview=20" in params, params
    assert "undoLabel=null" in params, params
    # the plus_api wrapper must not hide any real signature behind *args
    for name in core.PLUS_ACTIONS:
        assert "args" not in docs[name]["params"], (name, docs[name])

    # E at the wrapper boundary
    class FakeAC(plus.PlusMixin):
        def collection(self):
            raise Exception("collection is not available")

    inst = FakeAC()

    def code_of(fn):
        try:
            fn()
        except Exception as err:
            return str(err).split("] ", 1)[0].lstrip("[")
        raise AssertionError("expected an exception")

    # upstream no-profile error -> retryable collection_unavailable
    assert code_of(lambda: inst.mediaExists(filenames=["x.png"])) == "collection_unavailable"
    # dispatch-splat binding failures -> invalid_param (caller mistake)
    assert code_of(lambda: inst.mediaExists(bogus=1)) == "invalid_param"
    assert code_of(lambda: inst.bulkAddTags(noteIds=[1])) == "invalid_param"
    # a params key "self" must not escape unprefixed: the wrapper's
    # positional-only self routes it into **kwargs, and the inner call's
    # binding failure hits the tb_next-is-None TypeError branch
    assert code_of(lambda: inst.mediaExists(**{"self": 1, "filenames": []})) \
        == "invalid_param"
    # PlusError raised below the wrapper passes through untouched
    try:
        inst.bulkAddNotes(notes="nope")
        raise AssertionError("expected an exception")
    except Exception as e:
        assert str(e) == "[invalid_param] invalid parameter: notes: list required", str(e)

    # anything unexpected -> internal, message body unchanged
    class BoomAC(plus.PlusMixin):
        def collection(self):
            raise RuntimeError("kaboom")

    try:
        BoomAC().mediaExists(filenames=["x.png"])
        raise AssertionError("expected an exception")
    except Exception as e:
        assert str(e) == "[internal] kaboom", str(e)

    # a TypeError raised DEEPER than the call boundary is internal, not invalid_param
    class DeepTypeErrAC(plus.PlusMixin):
        def collection(self):
            raise TypeError("deep type error")

    assert code_of(lambda: DeepTypeErrAC().mediaExists(filenames=["x.png"])) == "internal"


# ============================================================================
# ROUND-3 field feedback: the error surface (ASK 4, ASK 11, ASK 1).
# ============================================================================

def _load_plus_pkg(pkg_name):
    """Load connect_plus/{core,plus,web}.py under a private package name."""
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [os.path.join(REPO, "connect_plus")]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg
    return importlib.import_module(pkg_name + ".plus")


def _load_dispatcher(pkg_name):
    """Load the REAL AnkiConnect dispatcher headless.

    connect_plus/__init__.py ends in an entry block that binds the web-server
    socket and starts a QTimer; that block is guarded by `__name__ != "plugin"`
    and is cut from the source here, so the module body (which is what the
    dispatcher lives in) executes with no side effects at all. util.setting is
    pre-patched to the shipped defaults because aqt.mw is None headless.
    """
    path = os.path.join(REPO, "connect_plus", "__init__.py")
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [os.path.join(REPO, "connect_plus")]
    pkg.__package__ = pkg_name
    sys.modules[pkg_name] = pkg
    util_mod = importlib.import_module(pkg_name + ".util")
    util_mod.setting = lambda key: util_mod.DEFAULT_CONFIG[key]
    with open(path, encoding="utf-8") as handle:
        src = handle.read()
    marker = 'if __name__ != "plugin":'
    assert marker in src, "entry-block guard moved; this loader must be updated"
    src = src[:src.index(marker)]
    pkg.__dict__["__file__"] = path
    exec(compile(src, path, "exec"), pkg.__dict__)
    inst = pkg.__dict__["AnkiConnect"].__new__(pkg.__dict__["AnkiConnect"])
    inst.log = None
    return pkg, inst


# ------------------------------------------------- ASK 4: structured envelope
def test8_structured_error_envelope():
    _load_plus_pkg("ancp_r3_err_pkg")
    web = importlib.import_module("ancp_r3_err_pkg.web")
    pkg_core = sys.modules["ancp_r3_err_pkg.core"]

    # a Plus error puts code AND retryable on the wire; the string is unchanged
    err = pkg_core.PlusError("collection_unavailable", "collection is not available")
    reply = web.format_exception_reply(6, err)
    assert reply == {"result": None,
                     "error": "[collection_unavailable] collection is not available",
                     "errorCode": "collection_unavailable",
                     "retryable": True}, reply

    # a non-retryable one
    reply = web.format_exception_reply(6, pkg_core.PlusError("not_found", "note was not found: 1"))
    assert reply["errorCode"] == "not_found" and reply["retryable"] is False, reply

    # anything that is not a PlusError (every upstream action error) keeps its
    # verbatim string and gets explicit nulls — the keys are ALWAYS present so
    # a client can branch on a stable shape
    reply = web.format_exception_reply(6, Exception("guru meditation"))
    assert reply == {"result": None, "error": "guru meditation",
                     "errorCode": None, "retryable": None}, reply
    # ... at every api version, including the v4 legacy path
    assert set(web.format_exception_reply(4, Exception("x"))) == \
        {"result", "error", "errorCode", "retryable"}

    # success replies are untouched (no new keys, v4 still returns raw)
    assert web.format_success_reply(6, {"a": 1}) == {"result": {"a": 1}, "error": None}
    assert web.format_success_reply(4, {"a": 1}) == {"a": 1}

    # retryable on the wire must agree with the vocabulary for every code
    for code, retryable in pkg_core.PLUS_ERROR_CODES.items():
        got = web.format_exception_reply(6, pkg_core.PlusError(code, "m"))
        assert got["errorCode"] == code and got["retryable"] is retryable, (code, got)


# ------------------------------- ASK 11a + ASK 4: dispatcher & multi nesting
def test9_dispatcher_boundary():
    pkg, inst = _load_dispatcher("ancp_r3_disp_pkg")

    # (a) an unknown action is now the ONE dispatcher error carrying a code
    reply = inst.handler({"action": "noSuchAction", "version": 6})
    assert reply == {"result": None, "error": "[unknown_action] unsupported action",
                     "errorCode": "unknown_action", "retryable": False}, reply
    # the documented parse rule works on it (it did not before revision 13)
    assert reply["error"].split("] ", 1)[0].lstrip("[") == "unknown_action"

    # (b) the prefixing BOUNDARY: upstream errors stay verbatim + null/null.
    # the api-key refusal is raised by the dispatcher itself but is not an
    # unknown action, so it is deliberately NOT prefixed.
    reply = inst.handler({"action": "deckNames", "version": 6, "key": "wrong"})
    assert reply["error"] == "valid api key must be provided", reply
    assert reply["errorCode"] is None and reply["retryable"] is None, reply
    # an upstream ACTION that raises: unprefixed, no code (aqt.mw is None here)
    reply = inst.handler({"action": "deckNames", "version": 6})
    assert reply["error"] and not reply["error"].startswith("["), reply
    assert reply["errorCode"] is None and reply["retryable"] is None, reply

    # (c) multi: each sub-response is a FULL envelope with the same four keys
    reply = inst.handler({"action": "multi", "version": 6, "params": {"actions": [
        {"action": "noSuchAction"},
        {"action": "renderCard"},
        {"action": "deckNames"},
    ]}})
    assert reply["error"] is None, reply          # the outer multi itself succeeded
    subs = reply["result"]
    assert len(subs) == 3, subs
    for sub in subs:
        assert set(sub) == {"result", "error", "errorCode", "retryable"}, sub
    assert subs[0]["errorCode"] == "unknown_action" and subs[0]["retryable"] is False
    assert subs[1]["errorCode"] == "invalid_param" and subs[1]["retryable"] is False
    assert subs[2]["errorCode"] is None and subs[2]["retryable"] is None

    # (d) ASK 11b end-to-end: no internal class name reaches the wire
    assert "PlusMixin" not in subs[1]["error"], subs[1]
    assert subs[1]["error"] == \
        "[invalid_param] renderCard() missing required argument: cardIds", subs[1]


# ---------------------------------------- ASK 11b: arity messages, house style
def test10_arity_message_house_format():
    plus = _load_plus_pkg("ancp_r3_err_pkg")
    norm = plus._normalize_arity_message

    assert norm("PlusMixin.renderCard() missing 1 required positional argument: 'cardIds'") \
        == "renderCard() missing required argument: cardIds"
    assert norm("PlusMixin.bulkReplaceInFields() missing 2 required positional "
                "arguments: 'find' and 'replace'") \
        == "bulkReplaceInFields() missing required arguments: find, replace"
    assert norm("PlusMixin.f() missing 3 required positional arguments: 'a', 'b' and 'c'") \
        == "f() missing required arguments: a, b, c"
    assert norm("PlusMixin.f() missing 1 required keyword-only argument: 'a'") \
        == "f() missing required argument: a"
    assert norm("PlusMixin.mediaExists() got an unexpected keyword argument 'bogus'") \
        == "mediaExists() unexpected keyword argument: bogus"
    # unrecognized forms keep their text but never keep the class name
    assert norm("PlusMixin.mediaExists() got multiple values for argument 'self'") \
        == "mediaExists() got multiple values for argument 'self'"
    # a message with no qualifier at all is returned untouched
    assert norm("invalid parameter: field: string required") == \
        "invalid parameter: field: string required"

    # and the wrapper actually applies it, still coded invalid_param
    class FakeAC(plus.PlusMixin):
        def collection(self):
            raise Exception("collection is not available")

    try:
        FakeAC().renderCard()
        raise AssertionError("expected an exception")
    except Exception as e:
        assert str(e) == "[invalid_param] renderCard() missing required argument: cardIds", str(e)


# --------------------------------- ASK 4: sync_in_progress is REACHABLE now
def test11_sync_guard_reachable():
    plus = _load_plus_pkg("ancp_r3_err_pkg")
    pkg_core = sys.modules["ancp_r3_err_pkg.core"]
    util_mod = sys.modules["ancp_r3_err_pkg.util"]

    # the four actions that must NEVER be refused: syncStatus/syncNow are how a
    # caller observes and drives the sync, plusInfo/ankihubStatus touch no
    # collection. Everything else is guarded.
    EXEMPT = {"syncStatus", "syncNow", "plusInfo", "ankihubStatus"}

    class FakeAC(plus.PlusMixin):
        def collection(self):
            raise AssertionError("guarded action reached the collection during a sync")

    inst = FakeAC()
    # the test hook the locked design calls for: set the job state directly on a
    # constructed mixin — no real sync, no network, no Qt.
    # round-3 review fix: startedMs must be RECENT. The guard now reaps a
    # job left "syncing" past core.SYNC_JOB_STALE_MS instead of refusing
    # forever (liveness), and startedMs=1 is 1970 — permanently stale.
    inst._plusSyncJobState = {"state": "syncing",
                              "startedMs": int(time.time() * 1000),
                              "result": None, "error": None}

    def code_of(fn):
        try:
            fn()
        except Exception as err:
            return str(err).split("] ", 1)[0].lstrip("[")
        return None

    # the guard runs BEFORE argument binding, so a bare call reaches it for
    # every guarded action regardless of that action's required params
    for name in pkg_core.PLUS_ACTIONS:
        if name in EXEMPT:
            continue
        assert code_of(getattr(inst, name)) == "sync_in_progress", name

    # the message is stable and points at the recovery move
    try:
        inst.undoStatus()
        raise AssertionError("expected an exception")
    except Exception as e:
        assert str(e) == "[sync_in_progress] " + pkg_core.SYNC_IN_PROGRESS_MESSAGE, str(e)
        assert "syncStatus" in str(e)
    # and it is flagged retryable, so a client knows to poll rather than fail
    assert pkg_core.PLUS_ERROR_CODES["sync_in_progress"] is True

    # the exempt four are NOT refused (they fail for unrelated headless
    # reasons — window()/mw is absent — which is exactly the point)
    for name in ("syncStatus", "syncNow", "ankihubStatus"):
        assert code_of(getattr(inst, name)) != "sync_in_progress", name
    orig = util_mod.setting
    util_mod.setting = lambda key: util_mod.DEFAULT_CONFIG[key]
    try:
        assert inst.plusInfo()["name"] == "AnkiConnect Plus"   # works mid-sync
    finally:
        util_mod.setting = orig

    # 'media_syncing' is deliberately NOT guarded: sync_collection has returned
    # and the collection mutex is free (stock Anki lets you review here too)
    inst._plusSyncJobState["state"] = "media_syncing"
    assert code_of(lambda: inst.undoStatus()) != "sync_in_progress"
    # ... and once the job is idle/done the guard is gone entirely
    for state in ("idle", "done", "error"):
        inst._plusSyncJobState["state"] = state
        assert code_of(lambda: inst.undoStatus()) != "sync_in_progress", state
    # an instance that never synced has no job slot at all
    assert code_of(lambda: FakeAC().undoStatus()) != "sync_in_progress"


# ------------------------- ASK 1: plusInfo returns + errorCodes + boundary note
def test12_plusinfo_returns_and_error_codes():
    plus = _load_plus_pkg("ancp_r3_err_pkg")
    pkg_core = sys.modules["ancp_r3_err_pkg.core"]
    util_mod = sys.modules["ancp_r3_err_pkg.util"]

    orig = util_mod.setting
    util_mod.setting = lambda key: util_mod.DEFAULT_CONFIG[key]
    try:
        info = plus.PlusMixin().plusInfo()
    finally:
        util_mod.setting = orig

    # (i) 'returns' for all 36 actions, no strays, none empty
    assert set(pkg_core.PLUS_ACTION_RETURNS) == set(pkg_core.PLUS_ACTIONS), \
        sorted(set(pkg_core.PLUS_ACTION_RETURNS) ^ set(pkg_core.PLUS_ACTIONS))
    assert len(pkg_core.PLUS_ACTIONS) == 36, len(pkg_core.PLUS_ACTIONS)
    for name in pkg_core.PLUS_ACTIONS:
        entry = info["actionDocs"][name]
        # revision 18: side-effectful actions carry a fourth key, 'preserves'
        want = {"summary", "params", "returns"}
        if name in pkg_core.PLUS_ACTION_PRESERVES:
            want.add("preserves")
        assert set(entry) == want, (name, sorted(entry))
        assert entry["returns"].strip(), name
        assert entry["returns"].startswith("{"), (name, entry["returns"][:40])

    # the two shapes the field report measured callers guessing WRONG
    assert "rows:" in info["actionDocs"]["queryRevlog"]["returns"]
    assert "'entries'" in info["actionDocs"]["queryRevlog"]["returns"]  # names the trap
    assert info["actionDocs"]["renderCard"]["returns"].startswith("{cards:")
    # and the round-3 shape changes are all described
    assert "missing" in info["actionDocs"]["notesSlim"]["returns"]
    assert "unsuspended" in info["actionDocs"]["bulkSetDueDate"]["returns"]
    assert "orphanMediaCollectionWide" in info["actionDocs"]["checkDeckIntegrity"]["returns"]
    assert "serverChecked" in info["actionDocs"]["syncStatus"]["returns"]
    assert "actualName" in info["actionDocs"]["mediaExists"]["returns"]

    # (ii) errorCodes covers the FULL vocabulary incl. unknown_action, with
    # retryable read from the single source of truth
    codes = info["errorCodes"]
    assert set(codes) == set(pkg_core.PLUS_ERROR_CODES), \
        sorted(set(codes) ^ set(pkg_core.PLUS_ERROR_CODES))
    assert "unknown_action" in codes
    for code, entry in codes.items():
        assert set(entry) == {"retryable", "reachable", "meaning"}, (code, sorted(entry))
        assert entry["retryable"] is pkg_core.PLUS_ERROR_CODES[code], code
        assert isinstance(entry["reachable"], bool), code
        assert isinstance(entry["meaning"], str) and entry["meaning"].strip(), code

    # the reserved-vs-reachable split is the thing ASK 4 asked to be honest
    # about: a caller must not build retry logic on an unreachable code
    reserved = {c for c, e in codes.items() if not e["reachable"]}
    # revision 17: 'duplicate' moved to reachable (renameDeck's occupied-name
    # refusal, SPEC 28.1) — a deliberate contract change, so the lock moves
    assert reserved == {"io_error", "offline", "full_sync_required"}, \
        sorted(reserved)
    assert codes["duplicate"]["reachable"] is True
    assert codes["duplicate"]["retryable"] is False
    for code in reserved:
        assert "RESERVED" in codes[code]["meaning"], code
    # sync_in_progress moved from reserved to reachable in revision 13
    assert codes["sync_in_progress"]["reachable"] is True
    assert codes["sync_in_progress"]["retryable"] is True
    assert "syncStatus" in codes["sync_in_progress"]["meaning"]
    # every retryable code a client can actually hit
    retryable_reachable = sorted(c for c, e in codes.items()
                                 if e["retryable"] and e["reachable"])
    assert retryable_reachable == ["collection_unavailable", "network_error",
                                   "rate_limited", "sync_in_progress"], retryable_reachable

    # (iii) the prefixing-boundary note, and the two new recipes
    note = info["errorPrefixNote"]
    assert note == pkg_core.PLUS_ERROR_PREFIX_NOTE
    for token in ("unknown-action", "UPSTREAM", "errorCode", "null"):
        assert token in note, token
    names = [r["name"] for r in info["recipes"]]
    assert "lean deck sweep" in names and "reading errors" in names, names
    reading = next(r for r in info["recipes"] if r["name"] == "reading errors")
    for token in ("errorCode", "retryable", "multi", "plusInfo.errorCodes"):
        assert token in reading["description"], token


run("test1_error_code_vocabulary", test1_error_code_vocabulary)
run("test2_raise_site_codes", test2_raise_site_codes)
run("test3_per_item_errors_not_prefixed", test3_per_item_errors_not_prefixed)
run("test4_diff_preview", test4_diff_preview)
run("test5_discoverability_lock_core", test5_discoverability_lock_core)
run("test6_wrapper_layer", test6_wrapper_layer)
run("test8_structured_error_envelope", test8_structured_error_envelope)
run("test9_dispatcher_boundary", test9_dispatcher_boundary)
run("test10_arity_message_house_format", test10_arity_message_house_format)
run("test11_sync_guard_reachable", test11_sync_guard_reachable)
run("test12_plusinfo_returns_and_error_codes", test12_plusinfo_returns_and_error_codes)


def test7_no_network():
    assert NETWORK_ATTEMPTS == [], NETWORK_ATTEMPTS


run("test7_no_network", test7_no_network)

col.close()

failed = [name for name, ok, _ in RESULTS if not ok]
print()
print("%d/%d tests passed" % (len(RESULTS) - len(failed), len(RESULTS)))
if failed:
    print("FAILED: %s" % ", ".join(failed))
    sys.exit(1)
