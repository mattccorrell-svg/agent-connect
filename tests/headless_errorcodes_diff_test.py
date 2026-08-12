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
        "batch_reverted": False, "collection_unavailable": True,
        "sync_in_progress": True, "not_logged_in": False, "auth_failed": False,
        "offline": True, "full_sync_required": False, "network_error": True,
        "rate_limited": True, "permission_denied": False,
        "validation_error": False, "incompatible_ankihub_addon": False,
        "source_required": False, "rationale_invalid": False, "internal": False,
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

    r = core.bulk_update_note_fields(col, [
        {"id": n0, "fields": {"Front": "D0", "Back": "b0"}},   # Back unchanged -> omitted
        {"id": n1, "fields": {"Front": "d1"}},                 # full no-op -> unchanged
        {"id": n2, "tags": ["cef"]},                           # tags-only -> no preview entry
        {"id": 4242424242, "fields": {"Front": "x"}},          # skipped
    ], dry_run=True, diff=True)
    assert r["wouldUpdate"] == [n0, n2], r
    assert r["unchanged"] == [n1], r
    assert r["skipped"][0]["reason"] == "note was not found: 4242424242", r
    assert r["preview"] == [
        {"noteId": n0, "field": "Front", "before": "d0", "after": "D0"},
    ], r
    assert r["previewTruncated"] is False and r["undoEntry"] is None, r

    # cap: one entry PER CHANGED FIELD, previewTruncated when entries remain
    r = core.bulk_update_note_fields(col, [
        {"id": n0, "fields": {"Front": "X0", "Back": "Y0"}},
        {"id": n1, "fields": {"Front": "X1"}},
    ], dry_run=True, diff=True, max_preview=2)
    assert len(r["preview"]) == 2 and r["previewTruncated"] is True, r
    assert r["preview"][0]["noteId"] == n0 and r["preview"][1]["noteId"] == n0, r
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


run("test1_error_code_vocabulary", test1_error_code_vocabulary)
run("test2_raise_site_codes", test2_raise_site_codes)
run("test3_per_item_errors_not_prefixed", test3_per_item_errors_not_prefixed)
run("test4_diff_preview", test4_diff_preview)
run("test5_discoverability_lock_core", test5_discoverability_lock_core)
run("test6_wrapper_layer", test6_wrapper_layer)


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
