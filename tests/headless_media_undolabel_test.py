# Headless verification for the ROUND-2 field-feedback items A, B, D:
# mediaExists (SPEC 22), storeMediaFilesBulk (SPEC 23), and the undoLabel
# param threaded through every undo-creating write action (SPEC 24) —
# including the undoEntry reporting contract (the response always carries the
# ACTUAL final undo entry name; defaults unchanged when undoLabel is null).
#
# Run with: <anki-venv>/bin/python headless_media_undolabel_test.py
#
# Uses a FRESH scratch collection; never touches ~/Library/Application
# Support/Anki2/. ZERO NETWORK by construction AND by enforcement (socket
# guard installed before anki loads; the suite fails on any attempt).

import base64
import importlib.util
import os
import shutil
import socket
import struct
import sys
import tempfile
import traceback
import zlib

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_PATH = os.path.join(REPO, "connect_plus", "core.py")

_PREFERRED_SCRATCH = os.path.join(tempfile.gettempdir(), "ancp_r2_abd")


def _pick_scratch():
    env = os.environ.get("ANCP_TEST_SCRATCH")
    if env:
        return env
    try:
        os.makedirs(_PREFERRED_SCRATCH, exist_ok=True)
        return os.path.join(_PREFERRED_SCRATCH, "col_scratch")
    except OSError:
        return tempfile.mkdtemp(prefix="ancp_r2_abd_")


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
        raise RuntimeError("network access blocked by headless_media_undolabel_test "
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

col = Collection(os.path.join(SCRATCH, "r2.anki2"))

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


def expect_error(fn, *fragments):
    try:
        fn()
    except Exception as e:
        for frag in fragments:
            assert frag in str(e), "error %r missing fragment %r" % (str(e), frag)
        return str(e)
    raise AssertionError("expected an exception containing %r" % (fragments,))


def undo_snap():
    return col.undo_status().SerializeToString()


def notes_snap():
    return col.db.all("select id, mod, usn from notes order by id")


def note_count():
    return col.db.scalar("select count() from notes") or 0


def basic_note(deck, front, back="b"):
    return {"deckName": deck, "modelName": "Basic",
            "fields": {"Front": front, "Back": back}, "tags": []}


def make_png(w=16, h=16, rgb=b"\x80\x40\xc0"):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    row = b"\x00" + rgb * w
    idat = zlib.compress(row * h)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


LABEL = "AnkiConnect Plus: "


# ---------------------------------------------------------------- mediaExists
def test1_media_exists():
    fname = col.media.write_data("me-present.png", make_png())
    assert fname == "me-present.png", fname
    n_snap, u_snap = notes_snap(), undo_snap()
    media_before = sorted(os.listdir(col.media.dir()))

    # revision 12 (round-3 field feedback): every entry carries actualName —
    # null when the requested spelling IS the stored one
    r = core.media_exists(col, ["me-present.png", "me-absent.png", "sub/me.png",
                                "/abs/me.png", "", "me-present.png"])
    assert r == {"results": [
        {"filename": "me-present.png", "exists": True, "actualName": None},
        {"filename": "me-absent.png", "exists": False, "actualName": None},
        {"filename": "sub/me.png", "exists": False, "actualName": None},
        {"filename": "/abs/me.png", "exists": False, "actualName": None},
        {"filename": "", "exists": False, "actualName": None},
        {"filename": "me-present.png", "exists": True, "actualName": None},
    ]}, r

    # case drift: on a case-INSENSITIVE volume (APFS/NTFS) os.path.isfile says
    # yes for a spelling that will 404 on AnkiWeb/Linux/iOS — actualName is the
    # channel that makes it visible. On a case-sensitive volume the same probe
    # honestly reports exists:false, so both outcomes are accepted; what must
    # never happen is exists:true with actualName None for a drifted spelling.
    drifted = core.media_exists(col, ["ME-PRESENT.PNG"])["results"][0]
    if drifted["exists"]:
        assert drifted["actualName"] == "me-present.png", drifted
    else:
        assert drifted["actualName"] is None, drifted

    assert core.media_exists(col, []) == {"results": []}

    # non-string entries are a HARD parameter error (not per-item)
    expect_error(lambda: core.media_exists(col, ["a.png", 5]),
                 "invalid parameter: filenames: list of strings required")
    expect_error(lambda: core.media_exists(col, "a.png"),
                 "invalid parameter: filenames: list of strings required")

    # pure read: notes, undo stack, media dir all untouched
    assert notes_snap() == n_snap and undo_snap() == u_snap
    assert sorted(os.listdir(col.media.dir())) == media_before


# ---------------------------------------------------------------- storeMediaFilesBulk
def test2_store_media_files_bulk():
    u_snap = undo_snap()
    png_a = make_png(rgb=b"\x11\x22\x33")
    png_b = make_png(rgb=b"\x99\x88\x77")

    src_path = os.path.join(SCRATCH, "smf-src.png")
    with open(src_path, "wb") as handle:
        handle.write(png_b)

    r = core.store_media_files_bulk(col, [
        {"filename": "smf-a.png", "data": base64.b64encode(png_a).decode("ascii")},
        {"filename": "smf-from-path.png", "path": src_path},
    ])
    assert r == {"stored": [
        {"requested": "smf-a.png", "actual": "smf-a.png"},
        {"requested": "smf-from-path.png", "actual": "smf-from-path.png"},
    ]}, r
    with open(os.path.join(col.media.dir(), "smf-a.png"), "rb") as handle:
        assert handle.read() == png_a
    with open(os.path.join(col.media.dir(), "smf-from-path.png"), "rb") as handle:
        assert handle.read() == png_b

    # same name + same bytes -> dedup to the same name (no new file)
    media_before = sorted(os.listdir(col.media.dir()))
    r = core.store_media_files_bulk(col, [
        {"filename": "smf-a.png", "data": base64.b64encode(png_a).decode("ascii")}])
    assert r == {"stored": [{"requested": "smf-a.png", "actual": "smf-a.png"}]}, r
    assert sorted(os.listdir(col.media.dir())) == media_before, "dedup created a file"

    # same name + DIFFERENT bytes -> anki renames; 'actual' surfaces it
    r = core.store_media_files_bulk(col, [
        {"filename": "smf-a.png", "data": base64.b64encode(png_b).decode("ascii")}])
    item = r["stored"][0]
    assert item["requested"] == "smf-a.png" and item["actual"] != "smf-a.png", r
    assert os.path.isfile(os.path.join(col.media.dir(), item["actual"]))
    with open(os.path.join(col.media.dir(), "smf-a.png"), "rb") as handle:
        assert handle.read() == png_a, "original bytes were overwritten"

    # media writes are not undoable: undo stack bit-identical throughout
    assert undo_snap() == u_snap


def test3_store_media_files_bulk_item_errors():
    ok_b64 = base64.b64encode(make_png()).decode("ascii")
    r = core.store_media_files_bulk(col, [
        "not-a-dict",
        {"data": ok_b64},
        {"filename": "sub/x.png", "data": ok_b64},
        {"filename": "x.png", "data": ok_b64, "path": "/tmp/x.png"},
        {"filename": "x.png"},
        {"filename": "x.png", "data": "!!!not-base64!!!"},
        {"filename": "x.png", "path": "relative/path.png"},
        {"filename": "x.png", "path": os.path.join(SCRATCH, "no-such-file.png")},
        {"filename": "x.png", "data": ok_b64, "bogus": 1},
        {"filename": "smf-ok.png", "data": ok_b64},
    ])
    stored = r["stored"]
    assert len(stored) == 10, r
    assert stored[0] == {"requested": None,
                         "error": "invalid parameter: files[0]: object required"}, stored[0]
    assert stored[1] == {"requested": None,
                         "error": "invalid parameter: files[1].filename: string required"}, stored[1]
    assert stored[2] == {"requested": "sub/x.png",
                         "error": "invalid parameter: files[2].filename: bare media filename required"}, stored[2]
    assert stored[3] == {"requested": "x.png",
                         "error": "invalid parameter: files[3]: exactly one of data or path required"}, stored[3]
    assert stored[4] == {"requested": "x.png",
                         "error": "invalid parameter: files[4]: exactly one of data or path required"}, stored[4]
    assert stored[5] == {"requested": "x.png",
                         "error": "invalid parameter: files[5].data: invalid base64"}, stored[5]
    assert stored[6] == {"requested": "x.png",
                         "error": "invalid parameter: files[6].path: absolute path required"}, stored[6]
    assert stored[7]["requested"] == "x.png" and \
        "media source file was not found" in stored[7]["error"], stored[7]
    assert stored[8] == {"requested": "x.png",
                         "error": "invalid parameter: files[8]: unknown key(s): bogus"}, stored[8]
    # a later valid item still succeeds after earlier failures (per-item, in order)
    assert stored[9] == {"requested": "smf-ok.png", "actual": "smf-ok.png"}, stored[9]

    assert core.store_media_files_bulk(col, []) == {"stored": []}
    expect_error(lambda: core.store_media_files_bulk(col, "nope"),
                 "invalid parameter: files: list required")


# ---------------------------------------------------------------- undoLabel: bulk note actions
def test4_undolabel_bulk_add():
    col.decks.id("R2Label")
    before = note_count()
    r = core.bulk_add_notes(col, [basic_note("R2Label", "ul-add-%d" % i) for i in range(3)],
                            undo_label="PI 7 import")
    assert r["undoEntry"] == LABEL + "PI 7 import", r
    assert col.undo_status().undo == LABEL + "PI 7 import"
    col.undo()
    assert note_count() == before, "labeled undo did not revert the batch"

    # default name unchanged when undoLabel is omitted
    r = core.bulk_add_notes(col, [basic_note("R2Label", "ul-add-def")])
    assert r["undoEntry"] == "AnkiConnect Plus: Bulk Add", r
    assert col.undo_status().undo == "AnkiConnect Plus: Bulk Add"

    # sanitization: whitespace runs (newlines included) collapse; 80-char cap
    r = core.bulk_add_notes(col, [basic_note("R2Label", "ul-add-ws")],
                            undo_label="  fix\n\n  cloze\ttypos  ")
    assert r["undoEntry"] == LABEL + "fix cloze typos", r
    r = core.bulk_add_notes(col, [basic_note("R2Label", "ul-add-cap")],
                            undo_label="x" * 200)
    assert r["undoEntry"] == LABEL + "x" * 80, r

    # bad labels are parameter errors raised BEFORE any write
    n_before = note_count()
    u_snap = undo_snap()
    expect_error(lambda: core.bulk_add_notes(
        col, [basic_note("R2Label", "ul-add-bad")], undo_label=123),
        "invalid parameter: undoLabel: string required")
    expect_error(lambda: core.bulk_add_notes(
        col, [basic_note("R2Label", "ul-add-bad")], undo_label="  \n  "),
        "invalid parameter: undoLabel: non-empty string required")
    assert note_count() == n_before and undo_snap() == u_snap


def test5_undolabel_update_tags_replace():
    col.decks.id("R2Label")
    added = core.bulk_add_notes(
        col, [basic_note("R2Label", "ul-upd-%d" % i) for i in range(2)])["added"]

    r = core.bulk_update_note_fields(
        col, [{"id": added[0], "fields": {"Back": "b2"}}], undo_label="fix backs")
    assert r["undoEntry"] == LABEL + "fix backs", r
    assert col.undo_status().undo == LABEL + "fix backs"
    col.undo()
    assert col.get_note(added[0])["Back"] == "b", "labeled undo did not revert"

    # dryRun with a label still creates nothing and reports undoEntry: null
    u_snap = undo_snap()
    r = core.bulk_update_note_fields(
        col, [{"id": added[0], "fields": {"Back": "b3"}}], dry_run=True,
        undo_label="dry label")
    assert r["undoEntry"] is None and r["wouldUpdate"] == [added[0]], r
    assert undo_snap() == u_snap, "dry run touched the undo stack"

    r = core.bulk_add_tags(col, added, ["r2::label"], undo_label="tag pass 1")
    assert r["undoEntry"] == LABEL + "tag pass 1", r
    assert col.undo_status().undo == LABEL + "tag pass 1"

    r = core.bulk_replace_in_fields(col, note_ids=added, field="Front",
                                    find="ul-upd", replace="ul-UPD",
                                    undo_label="rename fronts")
    assert r["undoEntry"] == LABEL + "rename fronts", r
    assert col.undo_status().undo == LABEL + "rename fronts"
    col.undo()
    assert col.get_note(added[0])["Front"].startswith("ul-upd")
    # nothing-written path: undoEntry null even with a label
    r = core.bulk_replace_in_fields(col, note_ids=added, field="Front",
                                    find="no-such-text", replace="x",
                                    undo_label="noop label")
    assert r["changed"] == [] and r["undoEntry"] is None, r


def test6_undolabel_scheduler():
    col.decks.id("R2Sched")
    # suspend=False: revision 15 (SPEC 27) suspends new cards by default, and
    # this test is about undo LABELS on the scheduler actions — it needs the
    # two cards to start at queue 0 so bulkSuspend has something to change.
    added = core.bulk_add_notes(
        col, [basic_note("R2Sched", "ul-sched-%d" % i) for i in range(2)],
        suspend=False)["added"]
    cids = col.db.list("select id from cards where nid in (%s)" %
                       ",".join(str(n) for n in added))

    r = core.bulk_suspend(col, cids, undo_label="bench the leeches")
    assert r == {"changed": 2, "changedIds": cids,
                 "undoEntry": LABEL + "bench the leeches"}, r
    assert col.undo_status().undo == LABEL + "bench the leeches"
    r = core.bulk_suspend(col, cids, suspend=False)
    assert r["undoEntry"] == "AnkiConnect Plus: Bulk Suspend", r

    r = core.bulk_set_due_date(col, cids, "0", undo_label="due today")
    # revision 15 (SPEC 27): additive 'resuspended' key
    assert r == {"changed": 2, "changedIds": cids, "unsuspended": [],
                 "unburied": [], "resuspended": [],
                 "undoEntry": LABEL + "due today"}, r
    assert col.undo_status().undo == LABEL + "due today"
    # bad days string still leaves the undo stack untouched, label or not
    u_snap = undo_snap()
    expect_error(lambda: core.bulk_set_due_date(col, cids, "x", undo_label="never"),
                 "invalid parameter: days")
    assert undo_snap() == u_snap


# ---------------------------------------------------------------- undoLabel: IO actions
def test7_undolabel_image_occlusion():
    col.decks.id("R2IO")
    rects = [{"left": 0.1, "top": 0.1, "width": 0.3, "height": 0.3},
             {"left": 0.5, "top": 0.5, "width": 0.3, "height": 0.3}]

    # default path: response now reports the ACTUAL backend entry name
    r = core.add_image_occlusion_note(
        col, image_data_b64=base64.b64encode(make_png()).decode("ascii"),
        image_filename="ul-io-def.png", occlusions=rects, deck_name="R2IO")
    assert isinstance(r["undoEntry"], str) and r["undoEntry"], r
    assert not r["undoEntry"].startswith(LABEL), r
    assert r["undoEntry"] == col.undo_status().undo, r

    # labeled path: custom entry wraps add + deck move; one undo reverts all
    before = note_count()
    r = core.add_image_occlusion_note(
        col, image_data_b64=base64.b64encode(make_png()).decode("ascii"),
        image_filename="ul-io-lab.png", occlusions=rects, deck_name="R2IO",
        undo_label="lab 9 figure")
    assert r["undoEntry"] == LABEL + "lab 9 figure", r
    assert col.undo_status().undo == LABEL + "lab 9 figure"
    assert note_count() == before + 1
    nid_labeled = r["noteId"]
    col.undo()
    assert note_count() == before, "labeled IO undo did not remove the note"
    assert col.db.scalar("select count() from cards where nid = ?", nid_labeled) == 0

    # updateImageOcclusionNote: default reports actual name; label overrides
    r = core.add_image_occlusion_note(
        col, image_data_b64=base64.b64encode(make_png()).decode("ascii"),
        image_filename="ul-io-upd.png", occlusions=rects, deck_name="R2IO")
    nid = r["noteId"]
    r = core.update_image_occlusion_note(col, nid, header="H1")
    assert isinstance(r["undoEntry"], str) and r["undoEntry"], r
    assert not r["undoEntry"].startswith(LABEL), r
    assert r["undoEntry"] == col.undo_status().undo, r

    r = core.update_image_occlusion_note(col, nid, header="H2",
                                         undo_label="retitle IO")
    assert r == {"undoEntry": LABEL + "retitle IO"}, r
    assert col.undo_status().undo == LABEL + "retitle IO"
    assert core.get_image_occlusion_note(col, nid)["header"] == "H2"
    col.undo()
    assert core.get_image_occlusion_note(col, nid)["header"] == "H1", \
        "labeled IO update undo did not revert the header"

    # no-op update (SPEC 4.6/24, revision 11): values identical to the note's
    # current state -> zero undoable writes -> undoEntry null, and an
    # UNRELATED entry already on the stack is neither reported nor disturbed
    core.bulk_add_tags(col, [nid], "noop-marker")
    marker = col.undo_status().undo
    assert marker == LABEL + "Bulk Tags", marker
    u_snap = undo_snap()
    r = core.update_image_occlusion_note(col, nid, header="H1")  # already H1
    assert r == {"undoEntry": None}, r
    assert undo_snap() == u_snap, "no-op IO update disturbed the undo stack"
    # labeled no-op: no empty do-nothing custom entry may be left behind
    r = core.update_image_occlusion_note(col, nid, header="H1",
                                         undo_label="relabel noop")
    assert r == {"undoEntry": None}, r
    assert col.undo_status().undo == marker, \
        "labeled no-op IO update left an empty custom entry on the stack"
    assert undo_snap() == u_snap
    # every param omitted (full backfill) is the ultimate no-op
    r = core.update_image_occlusion_note(col, nid)
    assert r == {"undoEntry": None}, r
    assert undo_snap() == u_snap
    assert core.get_image_occlusion_note(col, nid)["header"] == "H1"


# ---------------------------------------------------------------- undoLabel: crop actions
def test8_undolabel_crop():
    col.decks.id("R2Crop")
    fname = col.media.write_data("ul-crop.png", make_png(40, 40))
    added = core.bulk_add_notes(col, [{
        "deckName": "R2Crop", "modelName": "Basic",
        "fields": {"Front": 'crop me <img src="ul-crop.png">', "Back": "b"},
        "tags": []}])["added"]

    r = core.crop_image(col, fname, {"left": 0, "top": 0, "width": 0.5, "height": 0.5},
                        note_ids=added, undo_label="trim scan")
    assert r["notesUpdated"] == added, r
    assert r["undoEntry"] == LABEL + "trim scan", r
    assert col.undo_status().undo == LABEL + "trim scan"
    col.undo()
    assert 'src="ul-crop.png"' in col.get_note(added[0])["Front"], \
        "labeled crop undo did not restore the reference"

    # no notes rewritten -> no undo entry -> undoEntry null even with a label
    u_snap = undo_snap()
    r = core.crop_image(col, fname, {"left": 0, "top": 0, "width": 0.5, "height": 0.5},
                        undo_label="orphan crop")
    assert r["undoEntry"] is None, r
    assert undo_snap() == u_snap

    # cropImageOcclusionImage: always one (relabelable) entry
    rects = [{"left": 0.1, "top": 0.1, "width": 0.2, "height": 0.2},
             {"left": 0.6, "top": 0.6, "width": 0.2, "height": 0.2}]
    io = core.add_image_occlusion_note(
        col, image_data_b64=base64.b64encode(make_png(40, 40)).decode("ascii"),
        image_filename="ul-crop-io.png", occlusions=rects, deck_name="R2Crop")
    before_img = core.get_image_occlusion_note(col, io["noteId"])["imageFilename"]
    r = core.crop_image_occlusion_image(
        col, io["noteId"], {"left": 0, "top": 0, "width": 0.6, "height": 0.6},
        undo_label="crop io base")
    assert r["undoEntry"] == LABEL + "crop io base", r
    assert col.undo_status().undo == LABEL + "crop io base"
    col.undo()
    assert core.get_image_occlusion_note(col, io["noteId"])["imageFilename"] == before_img, \
        "labeled IO crop undo did not restore the base image"

    # default crop name unchanged
    r = core.crop_image_occlusion_image(
        col, io["noteId"], {"left": 0, "top": 0, "width": 0.6, "height": 0.6})
    assert r["undoEntry"] == "AnkiConnect Plus: Crop IO Image", r


# ---------------------------------------------------------------- undoStatus
def test10_undo_status():
    # SPEC 26 (round-3 field feedback): until now undoEntry was the API's own
    # REPORT of what it set, with no way for a caller to observe the stack —
    # the reporter tried driving Anki's menu bar with AppleScript and was
    # blocked by assistive-access permissions. undoStatus is that observation.
    col.decks.id("R2Undo")
    added = core.bulk_add_notes(
        col, [basic_note("R2Undo", "undostatus-1")],
        undo_label="observe me")["added"]
    assert len(added) == 1, added

    s = core.undo_status(col)
    assert set(s) == {"undo", "redo", "lastStep"}, s
    assert s["undo"] == LABEL + "observe me", s
    assert s["redo"] is None, s
    assert isinstance(s["lastStep"], int), s
    # it agrees with the proto, and reading it changes nothing
    snap = undo_snap()
    assert core.undo_status(col) == s, "undoStatus is not stable"
    assert undo_snap() == snap, "undoStatus touched the undo stack"

    # after an undo the entry moves to redo, and lastStep advances
    col.undo()
    s2 = core.undo_status(col)
    assert s2["redo"] == LABEL + "observe me", s2
    assert s2["undo"] != LABEL + "observe me", s2
    assert s2["lastStep"] > s["lastStep"], (s, s2)
    # empty strings from the proto are normalized to null, never ""
    assert s2["undo"] is None or s2["undo"].strip(), s2


# ---------------------------------------------------------------- discoverability
def test9_actions_registered():
    assert "mediaExists" in core.PLUS_ACTIONS
    assert "storeMediaFilesBulk" in core.PLUS_ACTIONS
    # 37 = 26 + round-3 SPEC 26 undoStatus + round-4 SPEC 28 + SPEC 29/30
    #      + revision-19 SPEC 32 (createFilteredDeck, rebuildFilteredDeck)
    #      + revision-20 SPEC 33 (ankihubStageOptionalTagSuggestion)
    assert len(core.PLUS_ACTIONS) == 37, len(core.PLUS_ACTIONS)
    assert "undoStatus" in core.PLUS_ACTIONS
    assert set(core.PLUS_ACTIONS) == set(core.PLUS_ACTION_SUMMARIES)
    assert core.PLUS_ACTION_SUMMARIES["mediaExists"]
    assert core.PLUS_ACTION_SUMMARIES["storeMediaFilesBulk"]
    assert core.PLUS_ACTION_SUMMARIES["undoStatus"]


run("test1_media_exists", test1_media_exists)
run("test2_store_media_files_bulk", test2_store_media_files_bulk)
run("test3_store_media_files_bulk_item_errors", test3_store_media_files_bulk_item_errors)
run("test4_undolabel_bulk_add", test4_undolabel_bulk_add)
run("test5_undolabel_update_tags_replace", test5_undolabel_update_tags_replace)
run("test6_undolabel_scheduler", test6_undolabel_scheduler)
run("test7_undolabel_image_occlusion", test7_undolabel_image_occlusion)
run("test8_undolabel_crop", test8_undolabel_crop)
run("test10_undo_status", test10_undo_status)
run("test9_actions_registered", test9_actions_registered)

col.close()

assert NETWORK_ATTEMPTS == [], "network attempted: %r" % (NETWORK_ATTEMPTS,)

failed = [name for name, ok, _ in RESULTS if not ok]
print()
print("%d/%d tests passed" % (len(RESULTS) - len(failed), len(RESULTS)))
if failed:
    print("FAILED: %s" % ", ".join(failed))
    sys.exit(1)
