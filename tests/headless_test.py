# Headless verification round 1 for AnkiConnect Plus core.py
# Run with: "/Users/mattyc/Library/Application Support/AnkiProgramFiles/.venv/bin/python" headless_test.py
#
# Uses a FRESH scratch collection; never touches ~/Library/Application Support/Anki2/.

import base64
import importlib.util
import json
import os
import shutil
import struct
import sys
import time
import traceback
import zlib

SCRATCH = ("/private/tmp/claude-501/-Users-mattyc-Downloads-prite-daily-main/"
           "6b24b91e-e4dc-4cbf-934f-6e83d3ff850a/scratchpad/ancp_test_r1")
CORE_PATH = "/Users/mattyc/Downloads/anki-connect-plus/connect_plus/core.py"

# safety guards
assert not SCRATCH.startswith(os.path.expanduser("~/Library")), "scratch dir must not be under ~/Library"
assert "Anki2" not in SCRATCH

if os.path.exists(SCRATCH):
    shutil.rmtree(SCRATCH)
os.makedirs(SCRATCH)

# load core.py standalone (no package __init__, no aqt)
spec = importlib.util.spec_from_file_location("core", CORE_PATH)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
assert "aqt" not in sys.modules, "core.py (or its imports) pulled in aqt"

import anki.lang
anki.lang.set_lang("en_US")
from anki.collection import Collection

col = Collection(os.path.join(SCRATCH, "test.anki2"))

RESULTS = []
TIMINGS = {}


def note_count():
    return col.db.scalar("select count() from notes") or 0


def basic_note(deck, front, back="b"):
    return {"deckName": deck, "modelName": "Basic",
            "fields": {"Front": front, "Back": back}, "tags": []}


def make_png(w=16, h=16):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    row = b"\x00" + b"\x80\x40\xc0" * w
    idat = zlib.compress(row * h)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


def run(name, fn):
    try:
        fn()
        RESULTS.append((name, True, ""))
        print("PASS  %s" % name)
    except Exception:
        tb = traceback.format_exc()
        RESULTS.append((name, False, tb))
        print("FAIL  %s\n%s" % (name, tb))


# ---------------------------------------------------------------- test 1
def test1_bulk500():
    col.decks.id("Bulk500")
    before = note_count()
    notes = [basic_note("Bulk500", "bulk500-front-%03d" % i, "back-%03d" % i)
             for i in range(500)]
    t0 = time.perf_counter()
    result = core.bulk_add_notes(col, notes)
    elapsed = time.perf_counter() - t0
    TIMINGS["bulk500_s"] = round(elapsed, 3)
    print("      bulk500 took %.3fs" % elapsed)
    assert elapsed < 10, "500-note bulk add took %.2fs (target < 10s)" % elapsed
    assert len(result["added"]) == 500, result
    assert result["skipped"] == [], result
    assert result["undoEntry"] == "AnkiConnect Plus: Bulk Add", result
    assert len(set(result["added"])) == 500, "note ids not unique"
    assert note_count() == before + 500, "note count mismatch after add"
    # ONE merged entry on top of the undo stack
    status = col.undo_status()
    assert status.undo == "AnkiConnect Plus: Bulk Add", "undo top is %r" % status.undo
    # a single undo reverts all 500
    col.undo()
    assert note_count() == before, "undo did not revert all 500"
    assert col.undo_status().undo != "AnkiConnect Plus: Bulk Add", \
        "bulk entry still on undo stack after undo (was not a single merged entry)"


# ---------------------------------------------------------------- test 2
def test2_dupes():
    col.decks.id("DupeDeck")
    notes = [basic_note("DupeDeck", "dupe-front-%d" % i) for i in range(10)]
    r1 = core.bulk_add_notes(col, notes)
    assert len(r1["added"]) == 10 and r1["skipped"] == [], r1
    before = note_count()
    r2 = core.bulk_add_notes(col, [dict(n) for n in notes], allow_duplicates=False)
    assert r2["added"] == [], r2
    assert len(r2["skipped"]) == 10, r2
    for i, s in enumerate(r2["skipped"]):
        assert s["index"] == i and s["reason"] == "duplicate", r2["skipped"]
    assert r2["undoEntry"] is None, r2
    assert note_count() == before, "dupe re-add changed note count"


# ---------------------------------------------------------------- test 3
def test3_atomicity():
    col.decks.id("AtomDeck")

    # 3a. Per SPEC 4.1, a bad model name is a VALIDATION skip, never a hard
    # error, even with atomic=true: the other 19 are added and item 10 lands
    # in skipped. (The orchestrator's literal expectation of a raise+rollback
    # here contradicts SPEC.md; SPEC semantics are asserted.)
    notes = [basic_note("AtomDeck", "atom-front-%02d" % i) for i in range(20)]
    notes[9]["modelName"] = "NoSuchModel"
    before = note_count()
    r = core.bulk_add_notes(col, notes, atomic=True)
    assert len(r["added"]) == 19, r
    assert r["skipped"] == [{"index": 9, "reason": "model was not found: NoSuchModel"}], r
    assert note_count() == before + 19
    col.undo()  # clean up the 19
    assert note_count() == before

    # 3b. TRUE atomicity: an injected hard error mid-batch with atomic=true
    # must raise and roll the whole batch back.
    notes = [basic_note("AtomDeck", "atomhard-front-%02d" % i) for i in range(20)]
    before = note_count()
    original_add = col.add_note
    state = {"n": 0}

    def failing_add(note, did):
        state["n"] += 1
        if state["n"] == 10:
            raise RuntimeError("injected hard error")
        return original_add(note, did)

    col.add_note = failing_add
    try:
        raised = None
        try:
            core.bulk_add_notes(col, notes, atomic=True)
        except Exception as e:
            raised = e
    finally:
        del col.add_note  # restore the class method

    assert raised is not None, "atomic hard error did not raise"
    msg = str(raised)
    prefix = "bulkAddNotes failed (batch reverted): "
    assert msg.startswith(prefix), msg
    report = json.loads(msg[len(prefix):])
    assert report["failedIndex"] == 9, report
    assert report["addedBeforeRevert"] == 9, report
    assert note_count() == before, \
        "note count changed after atomic revert: %d -> %d" % (before, note_count())

    # 3c. Same injection, atomic=false: 19 added, the failed one in skipped.
    notes = [basic_note("AtomDeck", "atomsoft-front-%02d" % i) for i in range(20)]
    before = note_count()
    state["n"] = 0
    col.add_note = failing_add
    try:
        r = core.bulk_add_notes(col, notes, atomic=False)
    finally:
        del col.add_note
    assert len(r["added"]) == 19, r
    assert len(r["skipped"]) == 1 and r["skipped"][0]["index"] == 9, r
    assert "injected hard error" in r["skipped"][0]["reason"], r
    assert note_count() == before + 19


# ---------------------------------------------------------------- test 4
def test4_update_and_tags():
    col.decks.id("UpdDeck")
    r = core.bulk_add_notes(col, [basic_note("UpdDeck", "upd-front-%d" % i) for i in range(3)])
    assert len(r["added"]) == 3, r
    n0, n1, n2 = r["added"]

    # happy path: fields-only, fields+tags, tags-only
    r = core.bulk_update_note_fields(col, [
        {"id": n0, "fields": {"Back": "newback0"}},
        {"id": n1, "fields": {"Back": "newback1"}, "tags": ["updtag"]},
        {"id": n2, "tags": ["tagonly"]},
    ])
    assert r["updated"] == [n0, n1, n2], r
    assert r["skipped"] == [], r
    assert r["undoEntry"] == "AnkiConnect Plus: Bulk Update", r
    assert col.get_note(n0)["Back"] == "newback0"
    assert col.get_note(n1)["Back"] == "newback1"
    assert col.get_note(n1).tags == ["updtag"]
    assert col.get_note(n2).tags == ["tagonly"]

    # one bad id, atomic=false -> reported in skipped, good one applied
    bad = 4444444444444
    r = core.bulk_update_note_fields(col, [
        {"id": n0, "fields": {"Back": "newback0b"}},
        {"id": bad, "fields": {"Back": "x"}},
    ], atomic=False)
    assert r["updated"] == [n0], r
    assert r["skipped"] == [{"index": 1, "reason": "note was not found: %d" % bad}], r
    assert col.get_note(n0)["Back"] == "newback0b"

    # bulkAddTags happy path
    r = core.bulk_add_tags(col, [n0, n1, n2], "bulkA bulkB")
    assert r["updated"] == [n0, n1, n2], r
    assert r["skipped"] == [], r
    assert r["undoEntry"] == "AnkiConnect Plus: Bulk Tags", r
    for nid in (n0, n1, n2):
        note = col.get_note(nid)
        assert note.has_tag("bulkA") and note.has_tag("bulkB"), note.tags

    # already-tagged notes are not rewritten and appear in neither list
    r = core.bulk_add_tags(col, [n0], ["bulkA"])
    assert r["updated"] == [] and r["skipped"] == [] and r["undoEntry"] is None, r

    # one bad id, atomic=false -> skipped
    r = core.bulk_add_tags(col, [n0, bad], "bulkC", atomic=False)
    assert r["updated"] == [n0], r
    assert r["skipped"] == [{"index": 1, "reason": "note was not found: %d" % bad}], r


# ---------------------------------------------------------------- test 5
def test5_image_occlusion():
    col.decks.id("IODeck")
    png = make_png()
    b64 = base64.b64encode(png).decode("ascii")
    rects = [
        {"left": 0.1, "top": 0.1, "width": 0.2, "height": 0.2, "ordinal": 1},
        {"left": 0.5, "top": 0.1, "width": 0.2, "height": 0.2, "ordinal": 2},
        {"left": 0.1, "top": 0.5, "width": 0.3, "height": 0.3, "ordinal": 3},
    ]
    r = core.add_image_occlusion_note(
        col, image_data_b64=b64, image_filename="ancp_io_test.png",
        occlusions=rects, header="H", back_extra="B",
        tags=["iotag"], deck_name="IODeck")
    nid = r["noteId"]
    card_ids = r["cardIds"]
    assert isinstance(nid, int) and nid > 0, r
    assert len(card_ids) == 3, "expected 3 cards (hide-all-guess-one), got %r" % (card_ids,)

    # cards landed in the requested deck
    io_did = col.decks.id_for_name("IODeck")
    dids = set(col.db.list("select distinct did from cards where nid = ?", nid))
    assert dids == {io_did}, "cards in decks %r, expected {%r}" % (dids, io_did)

    got = core.get_image_occlusion_note(col, nid)
    # media file exists under the (possibly renamed) stored filename
    assert got["imageFilename"], got
    assert os.path.isfile(os.path.join(col.media.dir(), got["imageFilename"])), \
        "media file missing: %s" % got["imageFilename"]
    assert got["header"] == "H" and got["backExtra"] == "B", got
    assert got["tags"] == ["iotag"], got
    assert got["occludeInactive"] is True, got

    def rects_by_ordinal(entries):
        out = {}
        for e in entries:
            assert e["shape"] == "rect", e
            out[e["ordinal"]] = e
        return out

    by_ord = rects_by_ordinal(got["occlusions"])
    assert sorted(by_ord) == [1, 2, 3], by_ord
    for want in rects:
        have = by_ord[want["ordinal"]]
        for key in ("left", "top", "width", "height"):
            assert abs(have[key] - want[key]) < 1e-4, \
                "ordinal %d %s: got %r want %r" % (want["ordinal"], key, have[key], want[key])

    # move ordinal-2 rect, round-trip again
    moved = [dict(x) for x in rects]
    moved[1]["left"] = 0.62
    core.update_image_occlusion_note(col, nid, occlusions=moved, header="H2")
    got2 = core.get_image_occlusion_note(col, nid)
    assert got2["header"] == "H2", got2
    assert got2["backExtra"] == "B", got2         # omitted param kept
    assert got2["tags"] == ["iotag"], got2        # omitted param kept
    by_ord2 = rects_by_ordinal(got2["occlusions"])
    assert abs(by_ord2[2]["left"] - 0.62) < 1e-4, by_ord2[2]
    assert abs(by_ord2[2]["top"] - 0.1) < 1e-4, by_ord2[2]
    for o in (1, 3):
        for key in ("left", "top", "width", "height"):
            assert abs(by_ord2[o][key] - by_ord[o][key]) < 1e-4, (o, key)
    n_cards = col.db.scalar("select count() from cards where nid = ?", nid)
    assert n_cards == 3, "card count changed after rect move: %d" % n_cards


# ------------------------------------------------- shared error-assert helper
def expect_error(fn, *fragments):
    try:
        fn()
    except Exception as e:
        for frag in fragments:
            assert frag in str(e), "error %r missing fragment %r" % (str(e), frag)
        return str(e)
    raise AssertionError("expected an exception containing %r" % (fragments,))


# ---------------------------------------------------------------- test 8
def test8_crop_image():
    col.decks.id("CropDeck")
    src = col.media.write_data("ancp-crop-src.png", make_png(16, 16))
    assert src == "ancp-crop-src.png", src

    r = core.bulk_add_notes(col, [
        {"deckName": "CropDeck", "modelName": "Basic", "tags": [],
         "fields": {"Front": 'crop-ref <img src="ancp-crop-src.png">', "Back": "b"}},
        # boundary-guard decoy: the src filename appears only inside a longer name
        {"deckName": "CropDeck", "modelName": "Basic", "tags": [],
         "fields": {"Front": 'decoy <img src="xancp-crop-src.png">', "Back": "b"}},
        {"deckName": "CropDeck", "modelName": "Basic", "tags": [],
         "fields": {"Front": "no occurrence here", "Back": "b"}},
    ])
    assert len(r["added"]) == 3, r
    n_ref, n_decoy, n_none = r["added"]

    # crop with noteIds (duplicate id exercises dedup); 16x16 * 0.5 rect -> 8x8
    rect = {"left": 0.25, "top": 0.25, "width": 0.5, "height": 0.5}
    res = core.crop_image(col, "ancp-crop-src.png", rect,
                          note_ids=[n_ref, n_decoy, n_none, n_ref])
    assert res["width"] == 8 and res["height"] == 8, res
    new = res["newFilename"]
    assert new == "ancp-crop-src-crop.png", res
    assert res["notesUpdated"] == [n_ref], res

    # exact pixel dims of the stored crop; original file still present
    from PyQt6.QtGui import QImage
    img = QImage(os.path.join(col.media.dir(), new))
    assert img.width() == 8 and img.height() == 8, (img.width(), img.height())
    assert os.path.isfile(os.path.join(col.media.dir(), "ancp-crop-src.png")), \
        "original media file was removed"

    # rewrite hit the referencing note only; decoy + no-occurrence untouched
    assert col.get_note(n_ref)["Front"] == 'crop-ref <img src="%s">' % new
    assert col.get_note(n_decoy)["Front"] == 'decoy <img src="xancp-crop-src.png">'
    assert col.get_note(n_none)["Front"] == "no occurrence here"

    # single undo restores the field
    assert col.undo_status().undo == "AnkiConnect Plus: Crop Image", col.undo_status().undo
    col.undo()
    assert col.get_note(n_ref)["Front"] == 'crop-ref <img src="ancp-crop-src.png">'

    # repeat crop with identical params dedups to the same newFilename
    res2 = core.crop_image(col, "ancp-crop-src.png", rect)
    assert res2["newFilename"] == new, res2
    assert res2["notesUpdated"] == [], res2

    # clamp, never pad: rect extending past the right/bottom edge crops to it
    res3 = core.crop_image(col, "ancp-crop-src.png",
                           {"left": 0.5, "top": 0.5, "width": 1.0, "height": 1.0})
    assert res3["width"] == 8 and res3["height"] == 8, res3

    # error cases (no writes expected)
    before_notes = note_count()
    expect_error(lambda: core.crop_image(
        col, "ancp-crop-src.png", {"left": 1.0, "top": 0.0, "width": 0.5, "height": 0.5}),
        "invalid parameter: rect: selects an empty area of ancp-crop-src.png (16x16)")
    expect_error(lambda: core.crop_image(col, "ancp-no-such-file.png", rect),
                 "media file was not found: ancp-no-such-file.png")
    expect_error(lambda: core.crop_image(col, "sub/ancp-crop-src.png", rect),
                 "invalid parameter: filename: bare media filename required")
    expect_error(lambda: core.crop_image(
        col, "ancp-crop-src.png", {"left": "x", "top": 0, "width": 0.5, "height": 0.5}),
        "invalid parameter: rect: left must be a number")
    assert note_count() == before_notes


# ---------------------------------------------------------------- test 9
def test9_crop_io_image():
    col.decks.id("CropIODeck")
    b64 = base64.b64encode(make_png(100, 100)).decode("ascii")
    rects = [
        # fully inside the 50x50 crop -> kept, unclipped
        {"left": 0.1, "top": 0.1, "width": 0.2, "height": 0.2, "ordinal": 1},
        # straddles the crop's right edge (x 40..60 vs crop 0..50) -> kept + clipped
        {"left": 0.4, "top": 0.1, "width": 0.2, "height": 0.2, "ordinal": 2},
        # fully outside -> dropped (and its card goes empty)
        {"left": 0.6, "top": 0.6, "width": 0.2, "height": 0.2, "ordinal": 3},
    ]
    r = core.add_image_occlusion_note(
        col, image_data_b64=b64, image_filename="ancp-crop-io.png",
        occlusions=rects, header="CH", back_extra="CB",
        tags=["croptag"], deck_name="CropIODeck")
    nid = r["noteId"]
    orig_card_ids = r["cardIds"]
    assert len(orig_card_ids) == 3, r
    orig = core.get_image_occlusion_note(col, nid)
    orig_filename = orig["imageFilename"]

    res = core.crop_image_occlusion_image(
        col, nid, {"left": 0.0, "top": 0.0, "width": 0.5, "height": 0.5})
    assert res["occlusionsKept"] == 2, res
    assert res["occlusionsClipped"] == 1, res
    assert res["occlusionsDropped"] == 1, res
    # empty-card gotcha: ordinal 3's now-empty card id still appears in cardIds
    assert sorted(res["cardIds"]) == sorted(orig_card_ids), res

    # new media file has the cropped dims; original file untouched
    from PyQt6.QtGui import QImage
    img = QImage(os.path.join(col.media.dir(), res["newFilename"]))
    assert img.width() == 50 and img.height() == 50, (img.width(), img.height())
    assert os.path.isfile(os.path.join(col.media.dir(), orig_filename)), \
        "original media file was removed"

    got = core.get_image_occlusion_note(col, nid)
    assert got["imageFilename"] == res["newFilename"], got
    assert got["header"] == "CH" and got["backExtra"] == "CB", got
    assert got["tags"] == ["croptag"], got
    by_ord = {e["ordinal"]: e for e in got["occlusions"]}
    assert sorted(by_ord) == [1, 2], by_ord
    # ordinal 1 remaps exactly: (0.1,0.1,0.2,0.2) of 100px -> /50px frame
    for key, want in (("left", 0.2), ("top", 0.2), ("width", 0.4), ("height", 0.4)):
        assert abs(by_ord[1][key] - want) < 1e-4, (key, by_ord[1])
    # ordinal 2 clipped: right edge lands exactly on the crop boundary
    for key, want in (("left", 0.8), ("top", 0.2), ("width", 0.2), ("height", 0.4)):
        assert abs(by_ord[2][key] - want) < 1e-4, (key, by_ord[2])
    assert abs((by_ord[2]["left"] + by_ord[2]["width"]) - 1.0) < 1e-4, by_ord[2]

    # single undo restores BOTH the image filename and the original rects
    assert col.undo_status().undo == "AnkiConnect Plus: Crop IO Image", col.undo_status().undo
    col.undo()
    back = core.get_image_occlusion_note(col, nid)
    assert back["imageFilename"] == orig_filename, back
    back_by_ord = {e["ordinal"]: e for e in back["occlusions"]}
    assert sorted(back_by_ord) == [1, 2, 3], back_by_ord
    for want in rects:
        for key in ("left", "top", "width", "height"):
            assert abs(back_by_ord[want["ordinal"]][key] - want[key]) < 1e-4, \
                (want["ordinal"], key, back_by_ord[want["ordinal"]])

    # all-outside -> refusal with zero note changes
    fields_before = list(col.get_note(nid).fields)
    expect_error(lambda: core.crop_image_occlusion_image(
        col, nid, {"left": 0.85, "top": 0.85, "width": 0.1, "height": 0.1}),
        "crop would remove all occlusions on note %d" % nid)
    assert list(col.get_note(nid).fields) == fields_before, "refusal modified the note"

    # mixed per-shape oi (hand-built string: oi=1 on c1 only) -> refusal, untouched
    mixed = ("{{c1::image-occlusion:rect:left=.1:top=.1:width=.2:height=.2:oi=1}}<br>"
             "{{c2::image-occlusion:rect:left=.5:top=.5:width=.2:height=.2}}")
    r2 = core.add_image_occlusion_note(
        col, image_data_b64=b64, image_filename="ancp-crop-io-mixed.png",
        occlusions=mixed, deck_name="CropIODeck")
    nid2 = r2["noteId"]
    assert core.get_image_occlusion_note(col, nid2)["occludeInactive"] is True
    fields_before2 = list(col.get_note(nid2).fields)
    expect_error(lambda: core.crop_image_occlusion_image(
        col, nid2, {"left": 0.0, "top": 0.0, "width": 0.5, "height": 0.5}),
        "cropImageOcclusionImage cannot preserve mixed oi flags on note %d" % nid2)
    assert list(col.get_note(nid2).fields) == fields_before2, "mixed-oi refusal modified the note"

    # non-IO note rejected
    r3 = core.bulk_add_notes(col, [basic_note("CropIODeck", "not-an-io-note")])
    expect_error(lambda: core.crop_image_occlusion_image(
        col, r3["added"][0], {"left": 0.0, "top": 0.0, "width": 0.5, "height": 0.5}),
        "note is not an image occlusion note: %d" % r3["added"][0])


# ---------------------------------------------------------------- test 6
def test6_query_revlog():
    col.decks.id("RevA")
    col.decks.id("RevB")
    r = core.bulk_add_notes(col, [basic_note("RevA", "rev-front-A"),
                                  basic_note("RevB", "rev-front-B")])
    assert len(r["added"]) == 2, r
    nidA, nidB = r["added"]
    cidA = col.db.scalar("select id from cards where nid = ?", nidA)
    cidB = col.db.scalar("select id from cards where nid = ?", nidB)

    base = 1754900000000
    # (id, cid): 3 reviews on cardA, 2 on cardB, interleaved chronologically
    rows = [
        (base + 0,    cidA), (base + 1000, cidA), (base + 2000, cidB),
        (base + 3000, cidA), (base + 4000, cidB),
    ]
    # raw INSERT allowed here ONLY because this is a throwaway scratch collection
    col.db.executemany(
        "insert into revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type)"
        " values (?, ?, -1, 3, 1, -600, 2500, 4200, 1)",
        [(rid, cid) for rid, cid in rows])

    # no filters
    r = core.query_revlog(col)
    assert len(r["rows"]) == 5, r
    ids = [row["id"] for row in r["rows"]]
    assert ids == sorted(ids) == [rid for rid, _ in rows], ids
    for row in r["rows"]:
        assert row["reviewedAt"] == row["id"], row
        assert row["ease"] == 3 and row["factor"] == 2500 and row["timeMs"] == 4200, row
        expect_nid = nidA if row["cardId"] == cidA else nidB
        assert row["noteId"] == expect_nid, row

    # by cardIds
    r = core.query_revlog(col, card_ids=[cidA])
    assert [row["id"] for row in r["rows"]] == [base, base + 1000, base + 3000], r
    assert all(row["cardId"] == cidA for row in r["rows"]), r

    # by deckName
    r = core.query_revlog(col, deck_name="RevA")
    assert [row["id"] for row in r["rows"]] == [base, base + 1000, base + 3000], r
    r = core.query_revlog(col, deck_name="RevB")
    assert [row["id"] for row in r["rows"]] == [base + 2000, base + 4000], r

    # by sinceMs (inclusive) / untilMs (exclusive)
    r = core.query_revlog(col, since_ms=base + 2000)
    assert [row["id"] for row in r["rows"]] == [base + 2000, base + 3000, base + 4000], r
    r = core.query_revlog(col, since_ms=base + 2000, until_ms=base + 4000)
    assert [row["id"] for row in r["rows"]] == [base + 2000, base + 3000], r

    # limit: first N chronologically
    r = core.query_revlog(col, limit=2)
    assert [row["id"] for row in r["rows"]] == [base, base + 1000], r


# ---------------------------------------------------------------- test 7
def test7_create_backup():
    r = core.create_backup(col, force=True)
    assert r == {"created": True}, r
    backups_dir = os.path.join(os.path.dirname(col.path), "backups")
    files = [f for f in os.listdir(backups_dir)
             if f.startswith("backup-") and f.endswith(".colpkg")]
    assert files, "no backup-*.colpkg in %s (contents: %r)" % (
        backups_dir, os.listdir(backups_dir))
    print("      backup file: %s" % os.path.join(backups_dir, sorted(files)[-1]))


run("test1_bulk500", test1_bulk500)
run("test2_dupes", test2_dupes)
run("test3_atomicity", test3_atomicity)
run("test4_update_and_tags", test4_update_and_tags)
run("test5_image_occlusion", test5_image_occlusion)
run("test6_query_revlog", test6_query_revlog)
run("test7_create_backup", test7_create_backup)
run("test8_crop_image", test8_crop_image)
run("test9_crop_io_image", test9_crop_io_image)

col.close()

print("\n===== SUMMARY =====")
n_pass = sum(1 for _, ok, _ in RESULTS if ok)
for name, ok, _ in RESULTS:
    print("%s  %s" % ("PASS" if ok else "FAIL", name))
print("%d/%d passed" % (n_pass, len(RESULTS)))
print("TIMINGS: %s" % json.dumps(TIMINGS))
sys.exit(0 if n_pass == len(RESULTS) else 1)
