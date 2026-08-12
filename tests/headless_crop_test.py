# Independent verification (round 1) for the cropImage / cropImageOcclusionImage
# core functions in AnkiConnect Plus.
#
# Run with:
#   "/Users/mattyc/Library/Application Support/AnkiProgramFiles/.venv/bin/python" headless_crop_test.py
#
# Uses a FRESH scratch collection; never touches ~/Library/Application Support/Anki2/.

import base64
import importlib.util
import json
import os
import random
import shutil
import statistics
import struct
import sys
import tempfile
import time
import traceback
import zlib

SCRATCH = (os.environ.get("ANCP_TEST_SCRATCH")
           or tempfile.mkdtemp(prefix="ancp_crop_r1_"))
CORE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "connect_plus", "core.py")

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
BENCH = {}


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


# ------------------------------------------------------------- PNG generation
def png_from_rows(rows, w):
    """rows: list of raw RGB row bytes (len == 3*w each). 8-bit color type 2."""
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", w, len(rows), 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + r for r in rows)
    idat = zlib.compress(raw, 6)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


COL_A = (255, 0, 0)      # top-left quadrant
COL_B = (0, 255, 0)      # top-right
COL_C = (0, 0, 255)      # bottom-left
COL_D = (255, 255, 0)    # bottom-right


def quad_png(w=800, h=600):
    top = bytes(COL_A) * (w // 2) + bytes(COL_B) * (w // 2)
    bot = bytes(COL_C) * (w // 2) + bytes(COL_D) * (w // 2)
    return png_from_rows([top] * (h // 2) + [bot] * (h // 2), w)


def bench_png(w=2000, h=1500, noise_rows=64):
    """Realistic-size PNG: mostly gradient rows plus a band of incompressible
    noise sized to land the file at a few hundred KB."""
    random.seed(20260811)
    rows = []
    band_start = h // 2 - noise_rows // 2
    for y in range(h):
        if band_start <= y < band_start + noise_rows:
            rows.append(random.randbytes(3 * w))
        else:
            rows.append(bytes((y & 255, (y * 2) & 255, 255 - (y & 255))) * w)
    return png_from_rows(rows, w)


def basic_note(deck, front, back="b"):
    return {"deckName": deck, "modelName": "Basic",
            "fields": {"Front": front, "Back": back}, "tags": []}


# ---------------------------------------------------------------- test 1
def test1_crop_image_pixels_and_notes():
    col.decks.id("CropR1")
    src_bytes = quad_png()
    print("      quad source PNG: %d bytes (800x600)" % len(src_bytes))
    name = col.media.write_data("quadr1.png", src_bytes)
    assert name == "quadr1.png", name

    r = core.bulk_add_notes(col, [
        basic_note("CropR1", 'ref1 <img src="quadr1.png">'),
        basic_note("CropR1", 'ref2-not-in-noteids <img src="quadr1.png">'),
    ])
    n1, n2 = r["added"]

    rect = {"left": 0.25, "top": 0.25, "width": 0.5, "height": 0.5}
    res = core.crop_image(col, "quadr1.png", rect, note_ids=[n1])
    assert res["width"] == 400 and res["height"] == 300, res
    new = res["newFilename"]
    assert new == "quadr1-crop.png", res
    assert res["notesUpdated"] == [n1], res

    new_path = os.path.join(col.media.dir(), new)
    assert os.path.isfile(new_path), "cropped file missing"

    # ORIGINAL file untouched, byte-identical
    with open(os.path.join(col.media.dir(), "quadr1.png"), "rb") as f:
        assert f.read() == src_bytes, "original media file bytes changed"

    # dims + pixel spot-check: crop covers x 200..599, y 150..449 of the
    # quadrant image, so all four quadrant colors survive at the corners
    from PyQt6.QtGui import QImage
    img = QImage(new_path)
    assert img.width() == 400 and img.height() == 300, (img.width(), img.height())

    def px(x, y):
        c = img.pixelColor(x, y)
        return (c.red(), c.green(), c.blue())

    assert px(0, 0) == COL_A, ("corner TL", px(0, 0))          # orig (200,150)
    assert px(399, 0) == COL_B, ("corner TR", px(399, 0))      # orig (599,150)
    assert px(0, 299) == COL_C, ("corner BL", px(0, 299))      # orig (200,449)
    assert px(399, 299) == COL_D, ("corner BR", px(399, 299))  # orig (599,449)
    # quadrant boundary lands mid-crop: orig x=399 is A, x=400 is B
    assert px(199, 0) == COL_A and px(200, 0) == COL_B, (px(199, 0), px(200, 0))
    assert px(199, 299) == COL_C and px(200, 299) == COL_D, (px(199, 299), px(200, 299))

    # note in noteIds rewritten; note NOT in noteIds keeps the old reference
    assert col.get_note(n1)["Front"] == 'ref1 <img src="%s">' % new, col.get_note(n1)["Front"]
    assert col.get_note(n2)["Front"] == 'ref2-not-in-noteids <img src="quadr1.png">', \
        col.get_note(n2)["Front"]

    # undoable as ONE entry
    assert col.undo_status().undo == "AnkiConnect Plus: Crop Image", col.undo_status().undo
    col.undo()
    assert col.get_note(n1)["Front"] == 'ref1 <img src="quadr1.png">', "undo did not restore n1"
    assert col.get_note(n2)["Front"] == 'ref2-not-in-noteids <img src="quadr1.png">'
    assert col.undo_status().undo != "AnkiConnect Plus: Crop Image", \
        "crop entry still on stack after one undo (not a single merged entry)"


# ---------------------------------------------------------------- test 2
def test2_crop_image_validation():
    rect_ok = {"left": 0.25, "top": 0.25, "width": 0.5, "height": 0.5}

    # bogus filename
    expect_error(lambda: core.crop_image(col, "no-such-file-r1.png", rect_ok),
                 "media file was not found: no-such-file-r1.png")

    # zero-area rects
    expect_error(lambda: core.crop_image(
        col, "quadr1.png", {"left": 0.1, "top": 0.1, "width": 0, "height": 0.5}),
        "invalid parameter: rect: width and height must be within 0-1")
    expect_error(lambda: core.crop_image(
        col, "quadr1.png", {"left": 0.1, "top": 0.1, "width": 0.5, "height": 0}),
        "invalid parameter: rect: width and height must be within 0-1")
    # rect that clamps to an empty area (left = 1.0)
    expect_error(lambda: core.crop_image(
        col, "quadr1.png", {"left": 1.0, "top": 0.0, "width": 0.5, "height": 0.5}),
        "invalid parameter: rect: selects an empty area of quadr1.png (800x600)")

    # out-of-range rect -> per SPEC: hard errors for left/top outside 0-1 and
    # width/height outside (0,1]
    expect_error(lambda: core.crop_image(
        col, "quadr1.png", {"left": 1.5, "top": 0.0, "width": 0.5, "height": 0.5}),
        "invalid parameter: rect: left and top must be within 0-1")
    expect_error(lambda: core.crop_image(
        col, "quadr1.png", {"left": -0.1, "top": 0.0, "width": 0.5, "height": 0.5}),
        "invalid parameter: rect: left and top must be within 0-1")
    expect_error(lambda: core.crop_image(
        col, "quadr1.png", {"left": 0.0, "top": 0.0, "width": 1.2, "height": 0.5}),
        "invalid parameter: rect: width and height must be within 0-1")
    # ... but left+width > 1 is legal and CLAMPS to the edge (never pads)
    res = core.crop_image(col, "quadr1.png",
                          {"left": 0.75, "top": 0.0, "width": 0.5, "height": 0.5})
    assert res["width"] == 200 and res["height"] == 300, res

    # non-image .txt file
    col.media.write_data("notanimage-r1.txt", b"this is definitely not an image\n")
    expect_error(lambda: core.crop_image(col, "notanimage-r1.txt", rect_ok),
                 "could not load image: notanimage-r1.txt (unsupported or corrupt format)")


# ---------------------------------------------------------------- test 3
def test3_crop_io_remap():
    col.decks.id("CropIOR1")
    b64 = base64.b64encode(quad_png(200, 200)).decode("ascii")
    # crop {0.25,0.25,0.5,0.5} of 200x200 -> pixel rect (50,50,100,100)
    rects = [
        # fully inside: px 60..80 x 60..80
        {"left": 0.3, "top": 0.3, "width": 0.1, "height": 0.1, "ordinal": 1},
        # straddles the crop's LEFT edge: px x 30..70, y 80..100
        {"left": 0.15, "top": 0.4, "width": 0.2, "height": 0.1, "ordinal": 2},
        # fully outside: px 160..180
        {"left": 0.8, "top": 0.8, "width": 0.1, "height": 0.1, "ordinal": 3},
    ]
    r = core.add_image_occlusion_note(
        col, image_data_b64=b64, image_filename="crop-io-r1.png",
        occlusions=rects, header="RH", back_extra="RB",
        tags=["r1tag"], deck_name="CropIOR1")
    nid = r["noteId"]
    orig_cards = sorted(r["cardIds"])
    assert len(orig_cards) == 3, r
    orig = core.get_image_occlusion_note(col, nid)
    orig_filename = orig["imageFilename"]
    with open(os.path.join(col.media.dir(), orig_filename), "rb") as f:
        orig_bytes = f.read()

    res = core.crop_image_occlusion_image(
        col, nid, {"left": 0.25, "top": 0.25, "width": 0.5, "height": 0.5})
    # implemented semantics: kept INCLUDES clipped; kept+dropped == original count
    assert res["occlusionsKept"] == 2, res
    assert res["occlusionsClipped"] == 1, res
    assert res["occlusionsDropped"] == 1, res

    # card count consistent (empty-card gotcha: dropped ordinal's card remains)
    assert sorted(res["cardIds"]) == orig_cards, res
    n_cards = col.db.scalar("select count() from cards where nid = ?", nid)
    assert n_cards == 3, n_cards

    # note's image points at the new file; new file has cropped dims; original intact
    got = core.get_image_occlusion_note(col, nid)
    assert got["imageFilename"] == res["newFilename"], got
    from PyQt6.QtGui import QImage
    img = QImage(os.path.join(col.media.dir(), res["newFilename"]))
    assert img.width() == 100 and img.height() == 100, (img.width(), img.height())
    with open(os.path.join(col.media.dir(), orig_filename), "rb") as f:
        assert f.read() == orig_bytes, "original media file changed"

    # remapped rects vs hand-computed values (within 1e-4)
    by_ord = {e["ordinal"]: e for e in got["occlusions"]}
    assert sorted(by_ord) == [1, 2], by_ord
    expected = {
        1: {"left": 0.1, "top": 0.1, "width": 0.2, "height": 0.2},
        2: {"left": 0.0, "top": 0.3, "width": 0.2, "height": 0.2},
    }
    for o, want in expected.items():
        for key, val in want.items():
            assert abs(by_ord[o][key] - val) < 1e-4, (o, key, by_ord[o][key], val)
    # clipped edge landed exactly on the crop boundary
    assert abs(by_ord[2]["left"]) < 1e-4, by_ord[2]
    assert got["header"] == "RH" and got["backExtra"] == "RB" and got["tags"] == ["r1tag"], got

    # SINGLE undo entry reverts the whole operation
    assert col.undo_status().undo == "AnkiConnect Plus: Crop IO Image", col.undo_status().undo
    col.undo()
    assert col.undo_status().undo != "AnkiConnect Plus: Crop IO Image", \
        "crop-IO entry still on stack after one undo (not a single merged entry)"
    back = core.get_image_occlusion_note(col, nid)
    assert back["imageFilename"] == orig_filename, back
    back_by_ord = {e["ordinal"]: e for e in back["occlusions"]}
    assert sorted(back_by_ord) == [1, 2, 3], back_by_ord
    for want in rects:
        for key in ("left", "top", "width", "height"):
            assert abs(back_by_ord[want["ordinal"]][key] - want[key]) < 1e-4, \
                (want["ordinal"], key)
    n_cards = col.db.scalar("select count() from cards where nid = ?", nid)
    assert n_cards == 3, n_cards


# ---------------------------------------------------------------- test 4
def test4_crop_io_all_dropped_refusal():
    b64 = base64.b64encode(quad_png(200, 200)).decode("ascii")
    r = core.add_image_occlusion_note(
        col, image_data_b64=b64, image_filename="crop-io-r1-alldrop.png",
        occlusions=[{"left": 0.1, "top": 0.1, "width": 0.1, "height": 0.1, "ordinal": 1}],
        deck_name="CropIOR1")
    nid = r["noteId"]
    fields_before = list(col.get_note(nid).fields)
    undo_before = col.undo_status().undo
    expect_error(lambda: core.crop_image_occlusion_image(
        col, nid, {"left": 0.5, "top": 0.5, "width": 0.5, "height": 0.5}),
        "crop would remove all occlusions on note %d" % nid)
    assert list(col.get_note(nid).fields) == fields_before, "refusal modified the note"
    assert col.undo_status().undo == undo_before, "refusal left an undo entry"


# ---------------------------------------------------------------- test 5
def test5_benchmark_core_vs_stock():
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QRect
    from PyQt6.QtGui import QImage

    col.decks.id("BenchR1")
    src_bytes = bench_png()
    print("      bench source PNG: %d bytes (2000x1500)" % len(src_bytes))
    assert 100_000 <= len(src_bytes) <= 900_000, \
        "bench PNG not 'a few hundred KB': %d bytes" % len(src_bytes)

    rect = {"left": 0.25, "top": 0.25, "width": 0.5, "height": 0.5}
    N = 5  # timed runs per pipeline (+1 warmup each)

    # independent source file + note per run so every run does identical fresh work
    a_files, a_notes, b_files, b_notes = [], [], [], []
    for i in range(N + 1):
        fa = col.media.write_data("bench-a%d.png" % i, src_bytes)
        fb = col.media.write_data("bench-b%d.png" % i, src_bytes)
        a_files.append(fa)
        b_files.append(fb)
        r = core.bulk_add_notes(col, [
            basic_note("BenchR1", 'bench <img src="%s">' % fa),
            basic_note("BenchR1", 'bench <img src="%s">' % fb),
        ])
        a_notes.append(r["added"][0])
        b_notes.append(r["added"][1])

    # (a) our core path: load -> crop -> write_data -> note update, one call
    def run_core(i):
        t0 = time.perf_counter()
        res = core.crop_image(col, a_files[i], rect, note_ids=[a_notes[i]])
        elapsed = (time.perf_counter() - t0) * 1000
        assert res["width"] == 1000 and res["height"] == 750, res
        assert res["notesUpdated"] == [a_notes[i]], res
        return elapsed

    # (b) faithful stock-AnkiConnect client pipeline simulation:
    #     retrieveMediaFile (read + b64 encode + JSON envelope) -> client JSON
    #     parse + b64 decode -> client-side Qt crop (same code) -> re-encode PNG
    #     -> b64 + JSON storeMediaFile request -> server JSON parse + b64 decode
    #     + write_data -> separate updateNoteFields-style call.
    #     HTTP/socket round-trip costs (3 requests) are NOT simulated, so this
    #     is a LOWER BOUND on the real stock pipeline.
    def run_stock(i):
        nid = b_notes[i]
        fname_src = b_files[i]
        t0 = time.perf_counter()
        # server: retrieveMediaFile
        with open(os.path.join(col.media.dir(), fname_src), "rb") as f:
            data = f.read()
        resp = json.dumps({"result": base64.b64encode(data).decode("ascii"), "error": None})
        # client: parse + decode
        raw = base64.b64decode(json.loads(resp)["result"])
        # client: same Qt crop code
        img = QImage.fromData(raw)
        assert not img.isNull()
        w, h = img.width(), img.height()
        cx = max(0, min(int(round(rect["left"] * w)), w))
        cy = max(0, min(int(round(rect["top"] * h)), h))
        cw = min(int(round(rect["width"] * w)), w - cx)
        ch = min(int(round(rect["height"] * h)), h - cy)
        cropped = img.copy(QRect(cx, cy, cw, ch))
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        assert cropped.save(buf, "png")
        buf.close()
        out = bytes(ba)
        # client: storeMediaFile request
        newname = fname_src[:-4] + "-crop.png"
        req = json.dumps({"action": "storeMediaFile",
                          "params": {"filename": newname,
                                     "data": base64.b64encode(out).decode("ascii")}})
        # server: decode + write
        p = json.loads(req)["params"]
        stored = col.media.write_data(p["filename"], base64.b64decode(p["data"]))
        # client -> server: separate updateNoteFields-style call
        req2 = json.dumps({"action": "updateNoteFields",
                           "params": {"note": {"id": nid,
                                               "fields": {"Front": 'bench <img src="%s">' % stored}}}})
        p2 = json.loads(req2)["params"]["note"]
        note = col.get_note(p2["id"])
        for fld, val in p2["fields"].items():
            note[fld] = val
        col.update_note(note)
        elapsed = (time.perf_counter() - t0) * 1000
        # same end state as (a)
        cimg = QImage(os.path.join(col.media.dir(), stored))
        assert cimg.width() == 1000 and cimg.height() == 750
        assert col.get_note(nid)["Front"] == 'bench <img src="%s">' % stored
        return elapsed

    run_core(N)   # warmup (Qt image plugins, zlib, caches)
    run_stock(N)  # warmup
    core_ms = [run_core(i) for i in range(N)]
    stock_ms = [run_stock(i) for i in range(N)]

    med_core = statistics.median(core_ms)
    med_stock = statistics.median(stock_ms)
    BENCH["plusCrop_ms"] = round(med_core, 1)
    BENCH["stockPipeline_ms"] = round(med_stock, 1)
    BENCH["speedup"] = round(med_stock / med_core, 2)
    print("      core cropImage runs (ms):   %s" % [round(x, 1) for x in core_ms])
    print("      stock pipeline runs (ms):   %s" % [round(x, 1) for x in stock_ms])
    print("      MEDIAN core=%.1fms stock=%.1fms speedup=%.2fx"
          % (med_core, med_stock, med_stock / med_core))


run("test1_crop_image_pixels_and_notes", test1_crop_image_pixels_and_notes)
run("test2_crop_image_validation", test2_crop_image_validation)
run("test3_crop_io_remap", test3_crop_io_remap)
run("test4_crop_io_all_dropped_refusal", test4_crop_io_all_dropped_refusal)
run("test5_benchmark_core_vs_stock", test5_benchmark_core_vs_stock)

col.close()

print("\n===== SUMMARY =====")
n_pass = sum(1 for _, ok, _ in RESULTS if ok)
for name, ok, _ in RESULTS:
    print("%s  %s" % ("PASS" if ok else "FAIL", name))
print("%d/%d passed" % (n_pass, len(RESULTS)))
print("BENCH: %s" % json.dumps(BENCH))
sys.exit(0 if n_pass == len(RESULTS) else 1)
