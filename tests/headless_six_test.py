# Headless verification round 1 for the six new features (SPEC 12-17):
# renderCard, notesSlim, mediaThumbnails, dryRun on the bulk actions,
# bulkSuspend + bulkSetDueDate, exportDeckApkg.
#
# Run with: <anki-venv>/bin/python headless_six_test.py
#
# Uses a FRESH scratch collection; never touches ~/Library/Application Support/Anki2/.

import base64
import importlib.util
import json
import os
import random
import shutil
import struct
import sys
import tempfile
import traceback
import zipfile
import zlib

SCRATCH = (os.environ.get("ANCP_TEST_SCRATCH")
           or tempfile.mkdtemp(prefix="ancp_six_r1_"))
OUT_DIR = os.path.join(SCRATCH, "out")
CORE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "connect_plus", "core.py")

# safety guards
assert not SCRATCH.startswith(os.path.expanduser("~/Library")), "scratch dir must not be under ~/Library"
assert "Anki2" not in SCRATCH

if os.path.exists(SCRATCH):
    shutil.rmtree(SCRATCH)
os.makedirs(OUT_DIR)

# load core.py standalone (no package __init__, no aqt)
spec = importlib.util.spec_from_file_location("core", CORE_PATH)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
assert "aqt" not in sys.modules, "core.py (or its imports) pulled in aqt"

import anki.lang
anki.lang.set_lang("en_US")
from anki.collection import Collection

col = Collection(os.path.join(SCRATCH, "six.anki2"))

RESULTS = []


def note_count():
    return col.db.scalar("select count() from notes") or 0


def media_count():
    return len(os.listdir(col.media.dir()))


def undo_snap():
    # UndoStatus is a proto message; serialized bytes give the bit-identical
    # comparison SPEC 15/16 promise
    return col.undo_status().SerializeToString()


def basic_note(deck, front, back="b"):
    return {"deckName": deck, "modelName": "Basic",
            "fields": {"Front": front, "Back": back}, "tags": []}


def make_png(w=16, h=16, noise=False):
    rnd = random.Random(42)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    if noise:
        # incompressible pixel data: the on-disk PNG stays big, so the
        # "thumbnail is smaller than the original" assertion is meaningful
        raw = b"".join(b"\x00" + rnd.randbytes(w * 3) for _ in range(h))
    else:
        raw = (b"\x00" + b"\x80\x40\xc0" * w) * h
    idat = zlib.compress(raw)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


def expect_error(fn, *fragments):
    try:
        fn()
    except Exception as e:
        for frag in fragments:
            assert frag in str(e), "error %r missing fragment %r" % (str(e), frag)
        return str(e)
    raise AssertionError("expected an exception containing %r" % (fragments,))


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
def test1_render_card():
    col.decks.id("RenderDeck")
    r = core.bulk_add_notes(col, [
        {"deckName": "RenderDeck", "modelName": "Basic", "tags": [],
         "fields": {"Front": "render-front-XYZ [sound:ancp-six-beep.mp3]",
                    "Back": "render-back-QRS"}},
        {"deckName": "RenderDeck", "modelName": "Cloze", "tags": [],
         "fields": {"Text": "The capital of {{c1::France}} is Paris.",
                    "Back Extra": ""}},
    ])
    assert len(r["added"]) == 2, r
    nid_basic, nid_cloze = r["added"]
    cid_basic = col.card_ids_of_note(nid_basic)[0]
    cid_cloze = col.card_ids_of_note(nid_cloze)[0]
    bogus = 999999999999

    snap = undo_snap()
    out = core.render_card(col, [cid_basic, bogus, cid_cloze])
    assert undo_snap() == snap, "renderCard touched the undo stack"
    cards = out["cards"]
    assert len(cards) == 3, out

    # Basic: template applied, css separate, names right
    b = cards[0]
    assert b["cardId"] == cid_basic, b
    assert "error" not in b, b
    assert "render-front-XYZ" in b["question"], b["question"]
    # [sound:...] rendered as backend av marker, not the raw tag (SPEC 12)
    assert "[anki:play:q:0]" in b["question"], b["question"]
    assert "[sound:" not in b["question"], b["question"]
    # answer is the applied template ({{FrontSide}}<hr id=answer>{{Back}}),
    # not the raw Back field
    assert "render-back-QRS" in b["answer"], b["answer"]
    assert "<hr id=answer>" in b["answer"], b["answer"]
    assert b["answer"] != "render-back-QRS", "answer template not applied"
    assert b["css"].strip(), "css empty"
    assert "<style>" not in b["question"] and "<style>" not in b["answer"], b
    assert b["deckName"] == "RenderDeck", b
    assert b["modelName"] == "Basic", b
    assert b["ord"] == 0, b

    # bogus id: per-item error, batch continues
    e = cards[1]
    assert e == {"cardId": bogus, "error": "card was not found: %d" % bogus}, e

    # Cloze: c1 visibly hidden on the question (modern renderer keeps the
    # answer text in a data-cloze attribute, so we assert on the visible
    # [...] replacement and the cloze span, not on text absence)
    c = cards[2]
    assert "error" not in c, c
    assert 'class="cloze"' in c["question"], c["question"]
    assert ">[...]<" in c["question"], c["question"]
    assert "{{c1::" not in c["question"], "cloze template not applied: %r" % c["question"]
    assert "France" in c["answer"], c["answer"]
    assert c["modelName"] == "Cloze" and c["deckName"] == "RenderDeck", c
    assert c["css"].strip(), c

    # spec revision 7: format='text' returns visible text only (notesSlim
    # conventions), format='body' strips script/style blocks but keeps HTML
    out = core.render_card(col, [cid_basic], render_format="text")
    t = out["cards"][0]
    assert "render-front-XYZ" in t["question"], t["question"]
    assert "<" not in t["question"] and "<" not in t["answer"], t
    assert "render-back-QRS" in t["answer"], t["answer"]
    # revision 12 (SPEC 12): format='text' defaults to cssMode='omit' — css is
    # meaningless in a text render and measured 90-95% of the payload
    assert "css" not in t, t
    assert "cssByNotetype" not in out, out
    # ...but an explicit cssMode always wins, in either direction
    t2 = core.render_card(col, [cid_basic], render_format="text",
                          css_mode="perCard")["cards"][0]
    assert t2["css"].strip(), t2
    h_omit = core.render_card(col, [cid_basic], css_mode="omit")["cards"][0]
    assert "css" not in h_omit, h_omit

    # cssMode='byNotetype': css hoisted ONCE per notetype, none per card, and
    # every card carries 'notetype' (present in all modes)
    out_by = core.render_card(col, [cid_basic, cid_cloze, bogus],
                              css_mode="byNotetype")
    assert set(out_by["cssByNotetype"]) == {"Basic", "Cloze"}, out_by["cssByNotetype"]
    assert out_by["cssByNotetype"]["Basic"] == b["css"], out_by["cssByNotetype"]
    for card in out_by["cards"]:
        assert "css" not in card, card
        if "error" not in card:
            assert card["notetype"] == card["modelName"], card
    assert b["notetype"] == "Basic" and t["notetype"] == "Basic", (b, t)
    expect_error(lambda: core.render_card(col, [cid_basic], css_mode="nope"),
                 "invalid parameter: cssMode: one of perCard, byNotetype, omit required")
    scripted = ('<script>var leak = 1;</script>front-kept'
                '<style>.x { color: red }</style>')
    assert core._render_format_text(col, scripted, "body") == "front-kept", \
        core._render_format_text(col, scripted, "body")
    assert core._render_format_text(col, scripted, "html") == scripted
    expect_error(lambda: core.render_card(col, [cid_basic], render_format="raw"),
                 "invalid parameter: format: one of html, body, text required")

    # empty list
    assert core.render_card(col, []) == {"cards": []}
    # hard error: non-int element
    expect_error(lambda: core.render_card(col, [cid_basic, "x"]),
                 "invalid parameter: cardIds: ints required")


# ---------------------------------------------------------------- test 2
SLIM_IDS = []


def test2_notes_slim_query_and_fields():
    col.decks.id("SlimDeck")
    r = core.bulk_add_notes(col, [
        basic_note("SlimDeck", "slim-front-%02d" % i, "slim-back-%02d" % i)
        for i in range(25)])
    assert len(r["added"]) == 25, r
    SLIM_IDS.extend(r["added"])

    snap = undo_snap()
    # query form: all 25, ascending noteId order
    out = core.notes_slim(col, query="deck:SlimDeck")
    assert undo_snap() == snap, "notesSlim touched the undo stack"
    assert out["total"] == 25, out["total"]
    assert out["nextOffset"] is None, out["nextOffset"]
    got_ids = [n["noteId"] for n in out["notes"]]
    assert got_ids == sorted(SLIM_IDS), "query path not in ascending id order"
    assert out["notes"][0]["modelName"] == "Basic", out["notes"][0]
    assert out["notes"][0]["fields"]["Front"] == "slim-front-00", out["notes"][0]

    # noteIds form: caller order preserved
    rev = list(reversed(SLIM_IDS))
    out = core.notes_slim(col, note_ids=rev)
    assert [n["noteId"] for n in out["notes"]] == rev, "caller order not preserved"
    assert out["total"] == 25, out["total"]

    # duplicates returned twice AND counted twice in total
    out = core.notes_slim(col, note_ids=[SLIM_IDS[0], SLIM_IDS[0]])
    assert [n["noteId"] for n in out["notes"]] == [SLIM_IDS[0]] * 2, out
    assert out["total"] == 2 and out["missing"] == [], out

    # SPEC 13 revision 12 (DELIBERATE BREAKING CHANGE, round-3 field report):
    # under noteIds 'total' now counts the ids FOUND, not the ids requested —
    # it used to report 2 here while returning one note, with no channel at
    # all for the stale id. The stale ids are named in 'missing', and
    # len(noteIds) == total + len(missing) holds on every page.
    stale = 4444444444444
    stale2 = 4444444444445
    out = core.notes_slim(col, note_ids=[SLIM_IDS[0], stale])
    assert out["total"] == 1, out
    assert out["missing"] == [stale], out
    assert [n["noteId"] for n in out["notes"]] == [SLIM_IDS[0]], out
    assert out["nextOffset"] is None, out

    out = core.notes_slim(col, note_ids=[SLIM_IDS[0], stale, SLIM_IDS[1], stale2])
    assert out["total"] == 2 and out["missing"] == [stale, stale2], out
    assert len([SLIM_IDS[0], stale, SLIM_IDS[1], stale2]) == \
        out["total"] + len(out["missing"]), out

    # the reported pager trap: an all-stale request must not hand back a
    # nextOffset pointing at another page that can only be empty
    out = core.notes_slim(col, note_ids=[stale, stale, stale2], limit=2)
    assert out["total"] == 0 and out["notes"] == [], out
    assert out["missing"] == [stale, stale, stale2], out
    assert out["nextOffset"] is None, out
    # ...while a real note past the window still yields a nextOffset
    out = core.notes_slim(col, note_ids=[stale, stale, SLIM_IDS[0]], limit=2)
    assert out["total"] == 1 and out["notes"] == [], out
    assert out["nextOffset"] == 2, out
    page2 = core.notes_slim(col, note_ids=[stale, stale, SLIM_IDS[0]], limit=2,
                            offset=2)
    assert [n["noteId"] for n in page2["notes"]] == [SLIM_IDS[0]], page2
    assert page2["nextOffset"] is None and page2["total"] == 1, page2

    # query path: unchanged semantics (match count) + always-present missing
    out = core.notes_slim(col, query="deck:SlimDeck", limit=10)
    assert out["total"] == 25 and out["missing"] == [], out
    assert out["nextOffset"] == 10, out

    # fields projection: only the named field, unknown name silently absent
    out = core.notes_slim(col, note_ids=[SLIM_IDS[0]], fields=["Front", "NoSuchField"])
    assert list(out["notes"][0]["fields"].keys()) == ["Front"], out["notes"][0]

    # stripHtml really strips tags but keeps the text (and media filenames)
    col.decks.id("SlimHtmlDeck")
    r = core.bulk_add_notes(col, [
        {"deckName": "SlimHtmlDeck", "modelName": "Basic", "tags": [],
         "fields": {"Front": 'slim-html <b>bold</b><div>second line</div><img src="ancp-six-pic.png">',
                    "Back": "b"}}])
    hid = r["added"][0]
    out = core.notes_slim(col, note_ids=[hid])
    front = out["notes"][0]["fields"]["Front"]
    assert "<" not in front and ">" not in front, front
    assert "bold" in front and "second line" in front, front
    assert "bold second line" in front, "div boundary not a single space: %r" % front
    assert "ancp-six-pic.png" in front, "media filename not preserved: %r" % front

    # stripHtml=false returns the raw HTML
    out = core.notes_slim(col, note_ids=[hid], strip_html=False)
    assert out["notes"][0]["fields"]["Front"] == \
        'slim-html <b>bold</b><div>second line</div><img src="ancp-six-pic.png">', out

    # maxFieldLength truncates AFTER stripping, with the … marker; 0 disables;
    # spec revision 7: truncatedFields names the cut fields explicitly
    out = core.notes_slim(col, note_ids=[hid], max_field_length=9)
    front = out["notes"][0]["fields"]["Front"]
    assert front == "slim-html…", front
    assert len(front) == 10, front
    assert out["notes"][0]["truncatedFields"] == ["Front"], out["notes"][0]
    out = core.notes_slim(col, note_ids=[hid], max_field_length=0)
    assert out["notes"][0]["fields"]["Front"].endswith("ancp-six-pic.png"), out
    assert out["notes"][0]["truncatedFields"] == [], out["notes"][0]

    # omitEmptyFields (SPEC 13, revision 12): default false keeps every field,
    # true drops the ones whose EMITTED value is '' — including a field whose
    # markup strips to nothing
    r = core.bulk_add_notes(col, [
        {"deckName": "SlimHtmlDeck", "modelName": "Basic", "tags": [],
         "fields": {"Front": "slim-omit-front", "Back": "<br>"}}])
    oid = r["added"][0]
    out = core.notes_slim(col, note_ids=[oid])
    assert list(out["notes"][0]["fields"]) == ["Front", "Back"], out["notes"][0]
    assert out["notes"][0]["fields"]["Back"] == "", out["notes"][0]
    out = core.notes_slim(col, note_ids=[oid], omit_empty_fields=True)
    assert list(out["notes"][0]["fields"]) == ["Front"], out["notes"][0]
    # ...but raw HTML '<br>' is NOT empty, so it survives with stripHtml=false
    out = core.notes_slim(col, note_ids=[oid], omit_empty_fields=True,
                          strip_html=False)
    assert out["notes"][0]["fields"]["Back"] == "<br>", out["notes"][0]
    expect_error(lambda: core.notes_slim(col, note_ids=[oid], omit_empty_fields="yes"),
                 "invalid parameter: omitEmptyFields: boolean required")


# ---------------------------------------------------------------- test 3
def test3_notes_slim_pagination_and_errors():
    # walk all 25 in pages of 7: sizes 7,7,7,4, ids covered exactly once
    seen = []
    offset = 0
    sizes = []
    next_offsets = []
    for _ in range(10):
        out = core.notes_slim(col, query="deck:SlimDeck", offset=offset, limit=7)
        assert out["total"] == 25, "total drifted: %r" % out["total"]
        sizes.append(len(out["notes"]))
        next_offsets.append(out["nextOffset"])
        seen.extend(n["noteId"] for n in out["notes"])
        if out["nextOffset"] is None:
            break
        assert out["nextOffset"] == offset + 7, out["nextOffset"]
        offset = out["nextOffset"]
    assert sizes == [7, 7, 7, 4], sizes
    assert next_offsets == [7, 14, 21, None], next_offsets
    assert len(seen) == 25 and len(set(seen)) == 25, "pagination missed/duplicated notes"
    assert set(seen) == set(SLIM_IDS), "pagination returned wrong ids"

    # both params and neither -> clean errors
    expect_error(lambda: core.notes_slim(col, query="deck:SlimDeck", note_ids=[1]),
                 "invalid parameter: query: exactly one of query or noteIds required")
    expect_error(lambda: core.notes_slim(col),
                 "invalid parameter: query: exactly one of query or noteIds required")
    # bad search syntax -> query error
    expect_error(lambda: core.notes_slim(col, query="deck:(("),
                 "invalid parameter: query:")


# ---------------------------------------------------------------- test 4
def test4_media_thumbnails():
    big = col.media.write_data("ancp-six-big.png", make_png(2000, 1500, noise=True))
    small = col.media.write_data("ancp-six-small.png", make_png(50, 50))
    assert big == "ancp-six-big.png" and small == "ancp-six-small.png", (big, small)
    big_size = os.path.getsize(os.path.join(col.media.dir(), big))
    media_before = media_count()
    snap = undo_snap()

    out = core.media_thumbnails(
        col, [big, "ancp-six-gone.png", small, "sub/ancp-six-big.png"], max_dim=320)
    assert undo_snap() == snap, "mediaThumbnails touched the undo stack"
    assert media_count() == media_before, "mediaThumbnails wrote to the media dir"
    thumbs = out["thumbnails"]
    assert len(thumbs) == 4, out
    assert [t["filename"] for t in thumbs] == \
        [big, "ancp-six-gone.png", small, "sub/ancp-six-big.png"], thumbs

    from PyQt6.QtGui import QImage

    # 2000x1500 -> 320x240: max side == 320, 4:3 aspect preserved
    t = thumbs[0]
    assert "error" not in t, t
    assert t["width"] == 320 and t["height"] == 240, (t["width"], t["height"])
    data = base64.b64decode(t["data"])
    assert data[:2] == b"\xff\xd8", "jpeg magic missing"
    img = QImage.fromData(data)
    assert not img.isNull(), "thumbnail did not decode"
    assert img.width() == 320 and img.height() == 240, (img.width(), img.height())
    assert len(data) < big_size, "thumbnail (%d) not smaller than original (%d)" % (len(data), big_size)

    # missing file mixed in -> per-item error, batch continued
    assert thumbs[1] == {"filename": "ancp-six-gone.png",
                         "error": "media file was not found: ancp-six-gone.png"}, thumbs[1]

    # 50x50 source with maxDim 320 -> NOT upscaled
    t = thumbs[2]
    assert "error" not in t, t
    assert t["width"] == 50 and t["height"] == 50, "small image was upscaled: %r" % t
    img = QImage.fromData(base64.b64decode(t["data"]))
    assert img.width() == 50 and img.height() == 50, (img.width(), img.height())

    # path-y filename -> per-item error
    assert thumbs[3]["error"] == "invalid parameter: filenames: bare media filename required", thumbs[3]

    # png format works
    out = core.media_thumbnails(col, [big], max_dim=320, image_format="png")
    t = out["thumbnails"][0]
    assert t["width"] == 320 and t["height"] == 240, t
    data = base64.b64decode(t["data"])
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "png magic missing"
    img = QImage.fromData(data)
    assert not img.isNull() and img.width() == 320, (img.isNull(), img.width())

    # hard errors: nothing processed
    expect_error(lambda: core.media_thumbnails(col, [big], image_format="gif"),
                 "invalid parameter: format: jpeg or png required")
    expect_error(lambda: core.media_thumbnails(col, [big], quality=101),
                 "invalid parameter: quality: int 0-100 required")
    expect_error(lambda: core.media_thumbnails(col, [big], max_dim=0),
                 "invalid parameter: maxDim: must be >= 1")
    assert core.media_thumbnails(col, []) == {"thumbnails": []}


# ---------------------------------------------------------------- test 5
DRY_NOTE_IDS = []


def test5_dry_run_add():
    col.decks.id("DryDeck")
    r = core.bulk_add_notes(col, [basic_note("DryDeck", "dry-dupe-front")])
    assert len(r["added"]) == 1, r

    batch = [
        basic_note("DryDeck", "dry-valid-1"),
        basic_note("DryDeck", "dry-valid-2"),
        basic_note("DryDeck", "dry-dupe-front"),        # duplicate of the seed
        dict(basic_note("DryDeck", "dry-bad-model"), modelName="NoSuchModelZZZ"),
    ]
    want_skipped = [
        {"index": 2, "reason": "duplicate"},
        {"index": 3, "reason": "model was not found: NoSuchModelZZZ"},
    ]

    notes_before = note_count()
    media_before = media_count()
    snap = undo_snap()
    dry = core.bulk_add_notes(col, batch, dry_run=True)
    # revision 15 (SPEC 27): the dry shape gained 'wouldSuspend' — the RESOLVED
    # suspend decision (a bool, not a count: card ids do not exist yet). Since
    # revision 16 the shipped default is stock behavior, so it is False here.
    assert dry == {"wouldAdd": 2, "wouldSuspend": False, "skipped": want_skipped,
                   "undoEntry": None}, dry
    assert note_count() == notes_before, "dry run added notes"
    assert media_count() == media_before, "dry run touched media"
    assert undo_snap() == snap, "dry run touched the undo stack"

    # same batch for real: the dry prediction must match exactly
    real = core.bulk_add_notes(col, batch)
    assert len(real["added"]) == dry["wouldAdd"] == 2, real
    assert real["skipped"] == dry["skipped"], (real["skipped"], dry["skipped"])
    assert real["undoEntry"] == "Agent Connect: Bulk Add", real
    assert note_count() == notes_before + 2
    DRY_NOTE_IDS.extend(real["added"])

    # empty batch dry run
    assert core.bulk_add_notes(col, [], dry_run=True) == \
        {"wouldAdd": 0, "wouldSuspend": False, "skipped": [], "undoEntry": None}
    # ...and the decision is reported for the switched-off case too
    assert core.bulk_add_notes(col, [], dry_run=True, suspend=False) == \
        {"wouldAdd": 0, "wouldSuspend": False, "skipped": [], "undoEntry": None}
    # hard param errors still raise under dryRun
    expect_error(lambda: core.bulk_add_notes(col, "nope", dry_run=True),
                 "invalid parameter: notes: list required")


# ---------------------------------------------------------------- test 6
def test6_dry_run_update_and_tags():
    n1, n2 = DRY_NOTE_IDS
    bad = 4444444444444

    # --- bulkUpdateNoteFields dry run
    batch = [
        {"id": n1, "fields": {"Back": "dry-new-back"}},
        {"id": bad, "fields": {"Back": "x"}},
        {"id": n2, "fields": {"NoSuchField": "x"}},
    ]
    want_skipped = [
        {"index": 1, "reason": "note was not found: %d" % bad},
        {"index": 2, "reason": "field was not found in note: NoSuchField"},
    ]
    back_before = col.get_note(n1)["Back"]
    snap = undo_snap()
    dry = core.bulk_update_note_fields(col, batch, dry_run=True)
    # spec revision 7: dry shape gained 'unchanged' (empty here — n1 changes)
    assert dry == {"wouldUpdate": [n1], "unchanged": [], "skipped": want_skipped,
                   "undoEntry": None}, dry
    assert col.get_note(n1)["Back"] == back_before, "dry update wrote a field"
    assert undo_snap() == snap, "dry update touched the undo stack"

    real = core.bulk_update_note_fields(col, batch)
    assert real["updated"] == dry["wouldUpdate"] == [n1], real
    assert real["unchanged"] == [], real
    assert real["skipped"] == dry["skipped"], real
    assert col.get_note(n1)["Back"] == "dry-new-back"

    # spec revision 7 no-op rule: re-running the identical batch writes
    # nothing — n1 lands in 'unchanged', undoEntry is null, and the undo
    # stack is bit-identical (no phantom entry); dry mirrors exactly
    snap = undo_snap()
    rerun_dry = core.bulk_update_note_fields(col, batch, dry_run=True)
    assert rerun_dry == {"wouldUpdate": [], "unchanged": [n1],
                         "skipped": want_skipped, "undoEntry": None}, rerun_dry
    rerun = core.bulk_update_note_fields(col, batch)
    assert rerun == {"updated": [], "unchanged": [n1], "skipped": want_skipped,
                     "suspensionPreserved": True, "schedulingPreserved": True,
                     "undoEntry": None}, rerun
    assert undo_snap() == snap, "no-op update touched the undo stack"
    # tags-only no-op: replacing the tag list with its current value
    tags_now = col.get_note(n1).tags
    rerun = core.bulk_update_note_fields(col, [{"id": n1, "tags": list(tags_now)}])
    assert rerun == {"updated": [], "unchanged": [n1], "skipped": [],
                     "suspensionPreserved": True, "schedulingPreserved": True,
                     "undoEntry": None}, rerun
    assert undo_snap() == snap, "tags-only no-op touched the undo stack"

    # hard param error still raises under dryRun
    expect_error(lambda: core.bulk_update_note_fields(col, "nope", dry_run=True),
                 "invalid parameter: notes: list required")

    # --- bulkAddTags dry run
    r = core.bulk_add_tags(col, [n1], "dryT")           # n1 now already tagged
    assert r["updated"] == [n1], r
    tags_before = col.get_note(n2).tags
    snap = undo_snap()
    dry = core.bulk_add_tags(col, [n1, n2, bad], "dryT", dry_run=True)
    # n1 already has every tag: in NEITHER list (same as real mode)
    assert dry == {"wouldUpdate": [n2],
                   "skipped": [{"index": 2, "reason": "note was not found: %d" % bad}],
                   "undoEntry": None}, dry
    assert col.get_note(n2).tags == tags_before, "dry addTags wrote tags"
    assert undo_snap() == snap, "dry addTags touched the undo stack"

    real = core.bulk_add_tags(col, [n1, n2, bad], "dryT")
    assert real["updated"] == dry["wouldUpdate"] == [n2], real
    assert real["skipped"] == dry["skipped"], real
    assert col.get_note(n2).has_tag("dryT")


# ---------------------------------------------------------------- test 7
def test7_bulk_suspend():
    col.decks.id("SuspDeck")
    # suspend=False: revision 15 (SPEC 27) makes bulkAddNotes suspend the cards
    # it creates BY DEFAULT. This test's subject is bulkSuspend, so the fixture
    # opts out to keep starting from queue 0 — the assertions below are unchanged.
    r = core.bulk_add_notes(col, [basic_note("SuspDeck", "susp-front-%d" % i)
                                  for i in range(5)], suspend=False)
    assert len(r["added"]) == 5, r
    cids = [col.card_ids_of_note(nid)[0] for nid in r["added"]]

    def queues():
        return {cid: col.get_card(cid).queue for cid in cids}

    assert all(q == 0 for q in queues().values()), queues()
    bogus = 999999999999

    # suspend 5 (+1 bogus, +1 duplicate id) -> changed 5, queues -1
    # (revision 12: additive 'changedIds' names the cards actually written —
    # deduplicated, bogus id dropped, precheck order)
    r = core.bulk_suspend(col, cids + [bogus, cids[0]])
    assert r == {"changed": 5, "changedIds": cids,
                 "undoEntry": "Agent Connect: Bulk Suspend"}, r
    assert all(q == -1 for q in queues().values()), queues()
    assert col.undo_status().undo == "Agent Connect: Bulk Suspend"

    # one undo reverts all 5 and pops the entry
    col.undo()
    assert all(q == 0 for q in queues().values()), queues()
    assert col.undo_status().undo != "Agent Connect: Bulk Suspend"

    # re-suspend, then suspending already-suspended is a clean no-op
    r = core.bulk_suspend(col, cids)
    assert r["changed"] == 5, r
    snap = undo_snap()
    r = core.bulk_suspend(col, cids)
    assert r == {"changed": 0, "changedIds": [], "undoEntry": None}, r
    assert undo_snap() == snap, "no-op suspend touched the undo stack"

    # unsuspend restores the queues
    r = core.bulk_suspend(col, cids, suspend=False)
    assert r == {"changed": 5, "changedIds": cids,
                 "undoEntry": "Agent Connect: Bulk Suspend"}, r
    assert all(q == 0 for q in queues().values()), queues()

    # unsuspend with nothing suspended -> no-op, stack untouched
    snap = undo_snap()
    r = core.bulk_suspend(col, cids, suspend=False)
    assert r == {"changed": 0, "changedIds": [], "undoEntry": None}, r
    assert undo_snap() == snap

    # empty list; bad params
    assert core.bulk_suspend(col, []) == {"changed": 0, "changedIds": [],
                                          "undoEntry": None}
    expect_error(lambda: core.bulk_suspend(col, [cids[0], "x"]),
                 "invalid parameter: cardIds: ints required")
    expect_error(lambda: core.bulk_suspend(col, cids, suspend="yes"),
                 "invalid parameter: suspend: boolean required")


# ---------------------------------------------------------------- test 8
def test8_bulk_set_due_date():
    col.decks.id("DueDeck")
    # suspend=False for the same reason as test7: this test is about due dates,
    # and revision 15 would otherwise hand it four suspended cards.
    r = core.bulk_add_notes(col, [basic_note("DueDeck", "due-front-%d" % i)
                                  for i in range(4)], suspend=False)
    assert len(r["added"]) == 4, r
    c0, c1, c2, c3 = [col.card_ids_of_note(nid)[0] for nid in r["added"]]
    today = col.sched.today

    # '0' -> due today, new card becomes a review card; one undo restores it
    orig = col.get_card(c0)
    orig_state = (orig.type, orig.queue, orig.due, orig.ivl)
    r = core.bulk_set_due_date(col, [c0], "0")
    # revision 15 (SPEC 27): additive 'resuspended' key, [] when nothing was
    # revived (this card was never suspended)
    assert r == {"changed": 1, "changedIds": [c0], "unsuspended": [],
                 "unburied": [], "resuspended": [],
                 "undoEntry": "Agent Connect: Bulk Due Date"}, r
    card = col.get_card(c0)
    assert card.type == 2 and card.queue == 2, (card.type, card.queue)
    assert card.due == today, (card.due, today)
    assert col.undo_status().undo == "Agent Connect: Bulk Due Date"
    col.undo()
    card = col.get_card(c0)
    assert (card.type, card.queue, card.due, card.ivl) == orig_state, \
        "undo did not restore the new-card state"

    # '1-3' -> each due within [today+1, today+3]; duplicate id counted once
    r = core.bulk_set_due_date(col, [c1, c2, c3, c1], "1-3")
    assert r == {"changed": 3, "changedIds": [c1, c2, c3], "unsuspended": [],
                 "unburied": [], "resuspended": [],
                 "undoEntry": "Agent Connect: Bulk Due Date"}, r
    for cid in (c1, c2, c3):
        card = col.get_card(cid)
        assert card.type == 2 and card.queue == 2, (cid, card.type, card.queue)
        assert today + 1 <= card.due <= today + 3, (cid, card.due, today)

    # '3!' -> due in 3 days AND interval forced to 3
    r = core.bulk_set_due_date(col, [c0], "3!")
    assert r["changed"] == 1, r
    card = col.get_card(c0)
    assert card.due == today + 3 and card.ivl == 3, (card.due, card.ivl)

    # 'abc' -> clean error, nothing changed, undo stack bit-identical
    rows_before = col.db.all("select id, type, queue, due, ivl from cards order by id")
    snap = undo_snap()
    expect_error(lambda: core.bulk_set_due_date(col, [c0, c1], "abc"),
                 "invalid parameter: days: abc")
    assert undo_snap() == snap, "bad days string touched the undo stack"
    assert col.db.all("select id, type, queue, due, ivl from cards order by id") == rows_before, \
        "bad days string changed card state"

    # SPEC 16.2 revision 12: set_due_date RESURRECTS suspended and buried
    # cards — the round-3 field report's worst-consequence finding (suspend
    # your leeches, reschedule the deck, silently un-suspend them). The
    # revived ids must be disclosed.
    assert core.bulk_suspend(col, [c1])["changed"] == 1
    col.sched.bury_cards([c2], manual=True)
    assert col.get_card(c1).queue == -1 and col.get_card(c2).queue == -3, \
        (col.get_card(c1).queue, col.get_card(c2).queue)
    # preserve_suspended=False: this block asserts ANKI's own resurrection
    # behavior, which revision 15 (SPEC 27) now undoes by default. Naming the
    # opt-out explicitly keeps the alarm below meaningful — it must still fire
    # if a future Anki stops resurrecting. The preserve-on path is covered by
    # tests/headless_suspension_test.py.
    r = core.bulk_set_due_date(col, [c1, c2, c3], "2", preserve_suspended=False)
    assert r["unsuspended"] == [c1], r
    assert r["unburied"] == [c2], r
    assert r["resuspended"] == [], r
    assert r["changedIds"] == [c1, c2, c3] and r["changed"] == 3, r
    assert col.get_card(c1).queue == 2 and col.get_card(c2).queue == 2, \
        "set_due_date no longer resurrects; the disclosure needs rechecking"

    # documented: it ALWAYS writes, even for a byte-identical repeat (no no-op
    # suppression — '1-7' is nondeterministic by construction), so a repeat
    # still creates an undo entry
    before = col.undo_status().last_step
    r = core.bulk_set_due_date(col, [c3], "2")
    assert r["changed"] == 1 and r["unsuspended"] == [] and r["unburied"] == [], r
    assert col.undo_status().last_step > before, "no-op repeat created no undo step"

    # only-bogus ids -> no-op; bad params
    assert core.bulk_set_due_date(col, [999999999999], "0") == \
        {"changed": 0, "changedIds": [], "unsuspended": [], "unburied": [],
         "resuspended": [], "undoEntry": None}
    expect_error(lambda: core.bulk_set_due_date(col, [c0], 5),
                 "invalid parameter: days: string like")
    expect_error(lambda: core.bulk_set_due_date(col, [c0], ""),
                 "invalid parameter: days: string like")


# ---------------------------------------------------------------- test 9
def test9_export_deck_apkg():
    col.decks.id("ExpDeck")
    col.decks.id("ExpDeck::Sub")
    media_name = col.media.write_data("ancp-six-exp.png", make_png(16, 16))
    assert media_name == "ancp-six-exp.png", media_name
    r = core.bulk_add_notes(col, [
        basic_note("ExpDeck", "exp-front-1"),
        {"deckName": "ExpDeck", "modelName": "Basic", "tags": [],
         "fields": {"Front": 'exp-front-media <img src="%s">' % media_name, "Back": "b"}},
        basic_note("ExpDeck::Sub", "exp-front-sub"),
    ])
    assert len(r["added"]) == 3, r

    out_path = os.path.join(OUT_DIR, "exp.apkg")
    snap = undo_snap()
    res = core.export_deck_apkg(col, "ExpDeck", out_path=out_path)
    assert undo_snap() == snap, "export touched the undo stack"
    assert res["path"] == out_path, res
    assert os.path.isfile(out_path), "apkg not written"
    assert res["sizeBytes"] == os.path.getsize(out_path) > 0, res
    # subdeck note included: 2 parent + 1 sub
    assert res["notesExported"] == 3, res
    with zipfile.ZipFile(out_path) as z:
        assert "media" in z.namelist(), z.namelist()

    # export twice -> -2 suffix, first file untouched
    first_bytes = open(out_path, "rb").read()
    res2 = core.export_deck_apkg(col, "ExpDeck", out_path=out_path)
    assert res2["path"] == os.path.join(OUT_DIR, "exp-2.apkg"), res2
    assert os.path.isfile(res2["path"]), res2
    assert open(out_path, "rb").read() == first_bytes, "first export was overwritten"

    # unknown deck / bad out dir -> error, no file written
    expect_error(lambda: core.export_deck_apkg(col, "NoSuchDeckZZZ", out_path=out_path),
                 "deck was not found: NoSuchDeckZZZ")
    expect_error(lambda: core.export_deck_apkg(
        col, "ExpDeck", out_path=os.path.join(SCRATCH, "no-such-dir", "x.apkg")),
        "output directory was not found:")
    expect_error(lambda: core.export_deck_apkg(col, "ExpDeck", out_path=OUT_DIR),
                 "invalid parameter: outPath: is a directory:")

    # IMPORT the apkg into a second fresh scratch collection
    import_dir = os.path.join(SCRATCH, "import")
    os.makedirs(import_dir)
    from anki.collection import ImportAnkiPackageOptions, ImportAnkiPackageRequest
    col2 = Collection(os.path.join(import_dir, "imp.anki2"))
    try:
        col2.import_anki_package(ImportAnkiPackageRequest(
            package_path=res["path"],
            options=ImportAnkiPackageOptions(with_scheduling=True)))
        assert (col2.db.scalar("select count() from notes") or 0) == 3, \
            "imported note count wrong"
        fronts = [flds.split("\x1f")[0]
                  for (flds,) in col2.db.all("select flds from notes")]
        assert "exp-front-1" in fronts, fronts
        assert 'exp-front-media <img src="%s">' % media_name in fronts, fronts
        assert "exp-front-sub" in fronts, fronts
        assert col2.decks.id_for_name("ExpDeck::Sub") is not None, \
            "subdeck did not arrive"
        assert os.path.isfile(os.path.join(col2.media.dir(), media_name)), \
            "media file did not arrive in the imported collection"
    finally:
        col2.close()


run("test1_render_card", test1_render_card)
run("test2_notes_slim_query_and_fields", test2_notes_slim_query_and_fields)
run("test3_notes_slim_pagination_and_errors", test3_notes_slim_pagination_and_errors)
run("test4_media_thumbnails", test4_media_thumbnails)
run("test5_dry_run_add", test5_dry_run_add)
run("test6_dry_run_update_and_tags", test6_dry_run_update_and_tags)
run("test7_bulk_suspend", test7_bulk_suspend)
run("test8_bulk_set_due_date", test8_bulk_set_due_date)
run("test9_export_deck_apkg", test9_export_deck_apkg)

col.close()

print("\n===== SUMMARY =====")
n_pass = sum(1 for _, ok, _ in RESULTS if ok)
for name, ok, _ in RESULTS:
    print("%s  %s" % ("PASS" if ok else "FAIL", name))
print("%d/%d passed" % (n_pass, len(RESULTS)))
sys.exit(0 if n_pass == len(RESULTS) else 1)
