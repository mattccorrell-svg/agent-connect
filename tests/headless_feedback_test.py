# Headless verification round 1 for the FIELD-FEEDBACK contract: the response
# shapes an LLM agent leaned on during a day of real use (2,618-note deck,
# ~1,500 writes). Covers queryRevlog pagination at the default-limit boundary,
# renderCard formats, bulkUpdateNoteFields no-op buckets, notesSlim
# truncatedFields, plusInfo actionDocs, checkDeckIntegrity bucketing, and
# bulkReplaceInFields (literal/regex/dryRun/atomic).
#
# Run with: <anki-venv>/bin/python headless_feedback_test.py
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
import struct
import sys
import tempfile
import traceback
import types
import zlib

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_PATH = os.path.join(REPO, "connect_plus", "core.py")

_PREFERRED_SCRATCH = os.path.join(tempfile.gettempdir(), "ancp_fb_r1")


def _pick_scratch():
    env = os.environ.get("ANCP_TEST_SCRATCH")
    if env:
        return env
    try:
        os.makedirs(_PREFERRED_SCRATCH, exist_ok=True)
        return os.path.join(_PREFERRED_SCRATCH, "col_scratch")
    except OSError:
        return tempfile.mkdtemp(prefix="ancp_fb_r1_")


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
        raise RuntimeError("network access blocked by headless_feedback_test "
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

col = Collection(os.path.join(SCRATCH, "feedback.anki2"))

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
    # UndoStatus proto bytes: the bit-identical undo-stack comparison
    return col.undo_status().SerializeToString()


def notes_snap():
    # id/mod/usn of every note: the "nothing was written" proof for reads
    return col.db.all("select id, mod, usn from notes order by id")


def add_note(deck, model_name, field_values, tags=None):
    import anki.notes
    model = col.models.by_name(model_name)
    assert model is not None, model_name
    note = anki.notes.Note(col, model)
    for name, value in field_values.items():
        note[name] = value
    note.tags = list(tags or [])
    col.add_note(note, col.decks.id(deck))
    return note.id


def add_basic(deck, front, back="b"):
    return add_note(deck, "Basic", {"Front": front, "Back": back})


def add_cloze(deck, text, extra=""):
    return add_note(deck, "Cloze", {"Text": text, "Back Extra": extra})


def card_ids(nid):
    return col.db.list("select id from cards where nid = ? order by ord", nid)


def field_value(nid, name):
    return col.get_note(nid)[name]


def make_png(w=8, h=8):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    idat = zlib.compress((b"\x00" + b"\x80\x40\xc0" * w) * h)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


# ---------------------------------------------------------------- test 1
# queryRevlog at the DEFAULT-limit boundary: the field agent hit exactly this
# ("5,541 rows, first call silently looked complete") — the contract is
# rows/total/truncated/nextOffset must expose the cut.
def test1_revlog_default_limit_boundary():
    nidA = add_basic("RevFB_A", "rev-fb-front-A")
    nidB = add_basic("RevFB_B", "rev-fb-front-B")
    cidA = card_ids(nidA)[0]
    cidB = card_ids(nidB)[0]

    base = 1755000000000
    b_ids = [base + i for i in range(5000)]           # 5000 rows on cardB
    a_ids = [base + 1000000 + 10 * i for i in range(541)]  # 541 rows on cardA
    assert b_ids[-1] < a_ids[0]
    # raw INSERT allowed here ONLY because this is a throwaway scratch collection
    col.db.executemany(
        "insert into revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type)"
        " values (?, ?, -1, 3, 1, -600, 2500, 4200, 1)",
        [(rid, cidB) for rid in b_ids] + [(rid, cidA) for rid in a_ids])
    assert col.db.scalar("select count(*) from revlog") == 5541

    # default limit (5000) on 5541 rows: page 1 signals the cut explicitly
    r = core.query_revlog(col)
    assert len(r["rows"]) == 5000, len(r["rows"])
    assert r["total"] == 5541, r["total"]
    assert r["truncated"] is True, r
    assert r["nextOffset"] == 5000, r
    assert [row["id"] for row in r["rows"]] == b_ids
    # full row shape on one row
    first = r["rows"][0]
    assert first == {"id": base, "cardId": cidB, "noteId": nidB, "ease": 3,
                     "interval": 1, "lastInterval": -600, "factor": 2500,
                     "timeMs": 4200, "type": 1, "reviewedAt": base}, first

    # resume at nextOffset: the 541-row tail, no further page
    r2 = core.query_revlog(col, offset=5000)
    assert len(r2["rows"]) == 541, len(r2["rows"])
    assert r2["total"] == 5541, r2
    assert r2["truncated"] is False and r2["nextOffset"] is None, r2
    assert [row["id"] for row in r2["rows"]] == a_ids
    assert all(row["cardId"] == cidA and row["noteId"] == nidA
               for row in r2["rows"])

    # exactly-limit case: a filter matching exactly N == limit rows is a
    # complete result, NOT a truncated one
    r3 = core.query_revlog(col, card_ids=[cidA], limit=541)
    assert len(r3["rows"]) == 541 and r3["total"] == 541, r3["total"]
    assert r3["truncated"] is False and r3["nextOffset"] is None, r3

    # filters + offset compose: cardIds + sinceMs (inclusive) + untilMs
    # (exclusive) + offset/limit page the FILTERED set
    r4 = core.query_revlog(col, card_ids=[cidB], since_ms=base + 1000,
                           until_ms=base + 4500, offset=10, limit=50)
    assert r4["total"] == 3500, r4["total"]
    assert [row["id"] for row in r4["rows"]] == \
        [base + 1010 + i for i in range(50)], r4["rows"][0]
    assert r4["truncated"] is True and r4["nextOffset"] == 60, r4

    # deckName filter + offset: exact non-truncated tail of the deck's rows
    r5 = core.query_revlog(col, deck_name="RevFB_A", offset=500)
    assert [row["id"] for row in r5["rows"]] == a_ids[500:], len(r5["rows"])
    assert r5["total"] == 541, r5
    assert r5["truncated"] is False and r5["nextOffset"] is None, r5


# ---------------------------------------------------------------- test 2
# renderCard formats: html keeps template <script>/<style> verbatim, body
# removes exactly those blocks, text is tag-free with media filenames kept.
RENDER_SCRIPT_Q = "<script>var fbq = 1;</script>"
RENDER_STYLE_Q = "<style>.fbq { color: red }</style>"
RENDER_SCRIPT_A = "<script>var fba = 2;</script>"


def test2_render_card_formats():
    mm = col.models
    nt = mm.copy(mm.by_name("Basic"), add=False)
    nt["name"] = "FBRender"
    nt["tmpls"][0]["qfmt"] = (RENDER_SCRIPT_Q + RENDER_STYLE_Q
                              + "<b>{{Front}}</b>")
    nt["tmpls"][0]["afmt"] = ("{{FrontSide}}<hr id=answer>"
                              + RENDER_SCRIPT_A + "<i>{{Back}}</i>")
    mm.add(nt)

    nid = add_note("FBRenderDeck", "FBRender",
                   {"Front": 'render-QQ <img src="fb-render.png"> tail',
                    "Back": "render-AA"})
    cid = card_ids(nid)[0]

    snap = undo_snap()
    out_default = core.render_card(col, [cid])
    out_html = core.render_card(col, [cid], render_format="html")
    assert undo_snap() == snap, "renderCard touched the undo stack"
    # format omitted == format='html'
    assert out_default == out_html, (out_default, out_html)

    h = out_html["cards"][0]
    assert "error" not in h, h
    # scripts/styles from the template survive VERBATIM under 'html'
    assert RENDER_SCRIPT_Q in h["question"], h["question"]
    assert RENDER_STYLE_Q in h["question"], h["question"]
    assert RENDER_SCRIPT_A in h["answer"], h["answer"]
    assert "render-QQ" in h["question"] and "render-AA" in h["answer"], h

    b = core.render_card(col, [cid], render_format="body")["cards"][0]
    for text in (b["question"], b["answer"]):
        assert "<script" not in text, text
        assert "<style" not in text, text
    # visible markup survives 'body'
    assert "<b>" in b["question"] and "render-QQ" in b["question"], b["question"]
    assert '<img src="fb-render.png">' in b["question"], b["question"]
    assert "<i>" in b["answer"] and "render-AA" in b["answer"], b["answer"]

    t = core.render_card(col, [cid], render_format="text")["cards"][0]
    assert "<" not in t["question"] and ">" not in t["question"], t["question"]
    assert "<" not in t["answer"] and ">" not in t["answer"], t["answer"]
    # media filename kept, field text kept
    assert "fb-render.png" in t["question"], t["question"]
    assert "render-QQ" in t["question"], t["question"]
    assert "render-AA" in t["answer"], t["answer"]

    # bogus format value: clear validation error naming the options
    expect_error(lambda: core.render_card(col, [cid], render_format="markdown"),
                 "invalid parameter: format: one of html, body, text required")


# ---------------------------------------------------------------- test 3
# bulkUpdateNoteFields: byte-identical writes are never written (unchanged
# bucket, untouched undo stack); mixed batches bucket exactly; dryRun mirrors.
def test3_bulk_update_unchanged_buckets():
    n1 = add_basic("FBUpd", "keep-front", "keep-back")

    # byte-identical write -> unchanged, updated empty, undo stack IDENTICAL
    snap = undo_snap()
    out = core.bulk_update_note_fields(
        col, [{"id": n1, "fields": {"Front": "keep-front", "Back": "keep-back"}}])
    assert out == {"updated": [], "unchanged": [n1], "skipped": [],
                   "suspensionPreserved": True, "schedulingPreserved": True,
                   "undoEntry": None}, out
    assert undo_snap() == snap, "identical write touched the undo stack"
    assert field_value(n1, "Front") == "keep-front"

    # one-of-two-fields-differ -> the note IS written and lands in updated
    n2 = add_basic("FBUpd", "aaa", "old")
    out = core.bulk_update_note_fields(
        col, [{"id": n2, "fields": {"Front": "aaa", "Back": "new"}}])
    assert out == {"updated": [n2], "unchanged": [], "skipped": [],
                   "suspensionPreserved": True, "schedulingPreserved": True,
                   "undoEntry": core.UNDO_BULK_UPDATE}, out
    assert field_value(n2, "Back") == "new"
    assert field_value(n2, "Front") == "aaa"

    # mixed batch: changed + identical + bogus id -> three buckets, exact
    n3 = add_basic("FBUpd", "ccc", "before")
    bogus = 987654321
    batch = [
        {"id": n3, "fields": {"Back": "after"}},
        {"id": n1, "fields": {"Front": "keep-front", "Back": "keep-back"}},
        {"id": bogus, "fields": {"Back": "x"}},
    ]
    # dryRun mirrors the real run with wouldUpdate, writes nothing
    snap = undo_snap()
    dry = core.bulk_update_note_fields(col, batch, dry_run=True)
    assert dry == {"wouldUpdate": [n3], "unchanged": [n1],
                   "skipped": [{"index": 2,
                                "reason": "note was not found: %d" % bogus}],
                   "undoEntry": None}, dry
    assert undo_snap() == snap, "dry run touched the undo stack"
    assert field_value(n3, "Back") == "before", "dry run wrote"

    real = core.bulk_update_note_fields(col, batch)
    assert real == {"updated": [n3], "unchanged": [n1],
                    "skipped": dry["skipped"],
                    "suspensionPreserved": True, "schedulingPreserved": True,
                    "undoEntry": core.UNDO_BULK_UPDATE}, real
    assert real["updated"] == dry["wouldUpdate"], (real, dry)
    assert field_value(n3, "Back") == "after"


# ---------------------------------------------------------------- test 4
# notesSlim truncatedFields: names exactly the cut fields; raw mode is
# byte-identical.
def test4_notes_slim_truncated_fields():
    long_text = "F" * 50
    nid = add_basic("FBSlim", long_text, "hi")

    out = core.notes_slim(col, note_ids=[nid], max_field_length=10)
    note = out["notes"][0]
    # exactly the long field is listed; the short one is not
    assert note["truncatedFields"] == ["Front"], note
    assert note["fields"]["Front"] == "F" * 10 + "…", note["fields"]
    assert note["fields"]["Back"] == "hi", note["fields"]

    # nothing truncated -> empty list (default maxFieldLength=400)
    out = core.notes_slim(col, note_ids=[nid])
    assert out["notes"][0]["truncatedFields"] == [], out["notes"][0]
    assert out["notes"][0]["fields"]["Front"] == long_text

    # stripHtml=false returns the RAW field HTML byte-identically
    raw = 'raw <b>bold</b> &amp; <img src="fb-slim.png"> end'
    nid2 = add_basic("FBSlim", raw, "<div>back raw</div>")
    out = core.notes_slim(col, note_ids=[nid2], strip_html=False,
                          max_field_length=0)
    note = out["notes"][0]
    assert note["fields"]["Front"] == raw, note["fields"]["Front"]
    assert note["fields"]["Back"] == "<div>back raw</div>", note["fields"]
    assert note["truncatedFields"] == [], note
    # raw mode with a generous cap: still byte-identical, still untruncated
    out = core.notes_slim(col, note_ids=[nid2], strip_html=False)
    assert out["notes"][0]["fields"]["Front"] == raw
    assert out["notes"][0]["truncatedFields"] == [], out["notes"][0]


# ---------------------------------------------------------------- test 5
# checkDeckIntegrity: each seeded defect lands in exactly the right list
# (and only there); orphan scan honors cross-deck references; read-only.
def test5_integrity_buckets():
    used = col.media.write_data("fb-used.png", make_png())
    assert used == "fb-used.png", used
    orphan = col.media.write_data("fb-orphan.png", make_png(4, 4))
    assert orphan == "fb-orphan.png", orphan
    other = col.media.write_data("fb-otherdeck.png", make_png(4, 4))
    assert other == "fb-otherdeck.png", other

    n_missing = add_basic("FBIntegrity", 'x <img src="fb-nowhere.png"> y', "b")
    n_unbal = add_basic("FBIntegrity", "unbal {{c3:: brace", "b")
    n_drift = add_cloze("FBIntegrity", "{{c1::x}} {{c2::y}}")
    n_healthy = add_basic("FBIntegrity", 'ok <img src="fb-used.png">', "fine")
    # referenced ONLY from another deck: must never count as orphan
    n_else = add_basic("FBElsewhereInt", 'other <img src="fb-otherdeck.png">', "b")

    cids = card_ids(n_drift)
    assert len(cids) == 2, cids
    col.remove_cards_and_orphaned_notes([cids[1]])  # kill the c2 card

    undo_before = undo_snap()
    notes_before = notes_snap()

    out = core.check_deck_integrity(col, "FBIntegrity")
    # every bucket exact -> each seeded note is in its list and ONLY there
    assert out["missingMedia"] == [{"noteId": n_missing, "field": "Front",
                                    "filename": "fb-nowhere.png"}], out["missingMedia"]
    assert out["unbalancedCloze"] == [{"noteId": n_unbal, "field": "Front"}], \
        out["unbalancedCloze"]
    assert out["clozeCardMismatch"] == [{"noteId": n_drift,
                                         "expectedOrds": [0, 1],
                                         "actualOrds": [0]}], out["clozeCardMismatch"]
    assert out["clozeNotesWithoutCloze"] == [], out["clozeNotesWithoutCloze"]
    # includeOrphanMedia=false -> the collection-wide array AND its count are
    # null (revision 12: renamed from 'orphanMedia' — DELIBERATE BREAKING
    # CHANGE — because it is the ONE non-deck-scoped list in this report)
    assert "orphanMedia" not in out, out
    assert out["orphanMediaCollectionWide"] is None, out
    assert out["orphanMediaCount"] is None, out
    assert out["orphanMediaTruncated"] is False, out
    assert out["notesChecked"] == 4, out["notesChecked"]
    # the healthy note and the other-deck note appear in no defect list
    flagged = ({e["noteId"] for e in out["missingMedia"]}
               | {e["noteId"] for e in out["unbalancedCloze"]}
               | {e["noteId"] for e in out["clozeCardMismatch"]}
               | set(out["clozeNotesWithoutCloze"]))
    assert n_healthy not in flagged and n_else not in flagged, flagged

    out2 = core.check_deck_integrity(col, "FBIntegrity", include_orphan_media=True)
    orphans = out2["orphanMediaCollectionWide"]
    assert isinstance(orphans, list), out2
    assert "fb-orphan.png" in orphans, orphans
    # referenced from ANOTHER deck -> not an orphan (scan is collection-wide)
    assert "fb-otherdeck.png" not in orphans, orphans
    assert "fb-used.png" not in orphans, orphans
    # the count is the FULL collection-wide size, the array is capped
    assert out2["orphanMediaCount"] == len(orphans), out2
    assert out2["orphanMediaTruncated"] is False, out2
    capped = core.check_deck_integrity(col, "FBIntegrity", include_orphan_media=True,
                                       orphan_media_limit=0)
    assert capped["orphanMediaCollectionWide"] == [], capped
    assert capped["orphanMediaCount"] == out2["orphanMediaCount"], capped
    assert capped["orphanMediaTruncated"] is True, capped
    expect_error(lambda: core.check_deck_integrity(col, "FBIntegrity",
                                                   orphan_media_limit=-1),
                 "invalid parameter: orphanMediaLimit: int >= 0 required")
    # defect buckets identical with the orphan scan on
    for key in ("missingMedia", "unbalancedCloze", "clozeCardMismatch",
                "clozeNotesWithoutCloze", "notesChecked"):
        assert out2[key] == out[key], (key, out2[key])

    # read-only proof: undo stack and note rows byte/row-identical
    assert undo_snap() == undo_before, "checkDeckIntegrity touched the undo stack"
    assert notes_snap() == notes_before, "checkDeckIntegrity modified notes"


# ---------------------------------------------------------------- test 6
# bulkReplaceInFields: exact buckets, regex backrefs, case folding, dryRun
# preview cap, atomic revert, missing-field skip, invalid regex rejection.
def test6_replace_contract():
    # literal replace: some notes match, one does not, one lacks the field
    r1 = add_basic("FBRep", "alpha one")
    r2 = add_basic("FBRep", "two alpha alpha")
    r3 = add_basic("FBRep", "beta")
    cz = add_cloze("FBRep", "{{c1::alpha cloze}}")
    out = core.bulk_replace_in_fields(col, query="deck:FBRep", field="Front",
                                      find="alpha", replace="gamma")
    assert out["changed"] == sorted([r1, r2]), out
    assert out["unchanged"] == [r3], out
    assert out["matchesTotal"] == 3, out
    # missing field -> skipped with reason (not an error, not unchanged)
    assert out["skipped"] == [{"noteId": cz,
                               "reason": "field was not found in note: Front"}], out
    assert out["undoEntry"] == core.UNDO_BULK_REPLACE, out
    assert field_value(r1, "Front") == "gamma one"
    assert field_value(r2, "Front") == "two gamma gamma"
    assert field_value(r3, "Front") == "beta"
    assert field_value(cz, "Text") == "{{c1::alpha cloze}}"

    # regex with backreference
    rx = add_basic("FBRex", "code 12-345 mid 6-7 end")
    out = core.bulk_replace_in_fields(col, note_ids=[rx], field="Front",
                                      find=r"(\d+)-(\d+)", replace=r"\2-\1",
                                      is_regex=True)
    assert out["changed"] == [rx] and out["matchesTotal"] == 2, out
    assert field_value(rx, "Front") == "code 345-12 mid 7-6 end"

    # caseSensitive=false literal
    ry = add_basic("FBRex", "Delta DELTA delta")
    out = core.bulk_replace_in_fields(col, note_ids=[ry], field="Front",
                                      find="DELTA", replace="x",
                                      case_sensitive=False)
    assert out["matchesTotal"] == 3, out
    assert field_value(ry, "Front") == "x x x"

    # invalid regex: clear error, nothing written, undo stack untouched
    rz = add_basic("FBRexBad", "abc")
    snap = undo_snap()
    expect_error(lambda: core.bulk_replace_in_fields(
        col, note_ids=[rz], field="Front", find="(unclosed", replace="b",
        is_regex=True), "invalid parameter: find: invalid regex:")
    assert field_value(rz, "Front") == "abc", "invalid regex wrote"
    assert undo_snap() == snap, "invalid regex touched the undo stack"

    # dryRun: correct before/after preview, capped by maxPreview, read-only
    d1 = add_basic("FBDry", "cat cat")
    d2 = add_basic("FBDry", "one cat")
    d3 = add_basic("FBDry", "dog")
    snap = undo_snap()
    dry = core.bulk_replace_in_fields(col, query="deck:FBDry", field="Front",
                                      find="cat", replace="rat", dry_run=True,
                                      max_preview=1)
    assert dry == {"wouldChange": sorted([d1, d2]), "matchesTotal": 3,
                   "unchanged": [d3], "skipped": [],
                   "preview": [{"noteId": min(d1, d2), "before": "cat cat",
                                "after": "rat rat"}],
                   "previewTruncated": True, "undoEntry": None}, dry
    assert field_value(d1, "Front") == "cat cat", "dry run wrote"
    assert undo_snap() == snap, "dry run touched the undo stack"
    # uncapped preview covers every would-change note, in order
    dry2 = core.bulk_replace_in_fields(col, query="deck:FBDry", field="Front",
                                       find="cat", replace="rat", dry_run=True)
    assert dry2["preview"] == [
        {"noteId": d1, "before": "cat cat", "after": "rat rat"},
        {"noteId": d2, "before": "one cat", "after": "one rat"},
    ], dry2["preview"]
    assert dry2["previewTruncated"] is False, dry2

    # atomic revert on an injected failure mid-batch
    a1 = add_basic("FBAtom", "hit one")
    a2 = add_basic("FBAtom", "hit two")
    original_update = col.update_note
    state = {"n": 0}

    def failing_update(note, *args, **kwargs):
        state["n"] += 1
        if state["n"] == 2:
            raise Exception("injected fb hard error")
        return original_update(note, *args, **kwargs)

    col.update_note = failing_update
    try:
        raised = None
        try:
            core.bulk_replace_in_fields(col, query="deck:FBAtom", field="Front",
                                        find="hit", replace="miss")
        except Exception as e:
            raised = e
    finally:
        del col.update_note
    assert raised is not None, "atomic hard error did not raise"
    msg = str(raised)
    prefix = "[batch_reverted] bulkReplaceInFields failed (batch reverted): "
    assert msg.startswith(prefix), msg
    report = json.loads(msg[len(prefix):])
    assert report["failedNoteId"] == a2, report
    assert report["changedBeforeRevert"] == 1, report
    assert "injected fb hard error" in report["error"], report
    assert field_value(a1, "Front") == "hit one", "atomic revert failed"
    assert field_value(a2, "Front") == "hit two"
    assert col.undo_status().undo != core.UNDO_BULK_REPLACE


# ---------------------------------------------------------------- test 7
# plusInfo actionDocs: the discoverability surface the field agent reads
# first. This is the ONLY test that imports plus.py (and therefore aqt), so
# it runs last; everything above ran aqt-free.
def test7_plus_info_action_docs():
    assert "aqt" not in sys.modules, "an earlier core-path test pulled in aqt"

    pkg_name = "ancp_fb_pkg"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [os.path.join(REPO, "connect_plus")]
        sys.modules[pkg_name] = pkg
    plus = importlib.import_module(pkg_name + ".plus")

    # plusInfo must work before a profile is open; util.setting normally
    # reads aqt.mw's config, so serve the shipped defaults here
    util_mod = sys.modules[pkg_name + ".util"]
    orig_setting = util_mod.setting
    util_mod.setting = lambda key: util_mod.DEFAULT_CONFIG[key]
    try:
        info = plus.PlusMixin().plusInfo()
    finally:
        util_mod.setting = orig_setting

    assert info["name"] == "AnkiConnect Plus", info["name"]
    assert info["version"] == core.PLUS_VERSION
    assert info["actions"] == list(core.PLUS_ACTIONS)

    docs = info["actionDocs"]
    # all 37 actions documented, no strays (37 = 24 + round-2 SPEC 22/23:
    # mediaExists, storeMediaFilesBulk + round-3 SPEC 26: undoStatus
    # + round-4 SPEC 28: renameDeck, bulkSetFlag, renameTag
    # + round-4 SPEC 29/30: filteredDeckReport, emptyFilteredDeck,
    #   getEmptyCards, deleteEmptyCards
    # + revision-19 SPEC 32: createFilteredDeck, rebuildFilteredDeck
    # + revision-20 SPEC 33: ankihubStageOptionalTagSuggestion)
    assert len(core.PLUS_ACTIONS) == 37, core.PLUS_ACTIONS
    assert set(docs) == set(core.PLUS_ACTIONS), \
        sorted(set(docs) ^ set(core.PLUS_ACTIONS))
    assert len(docs) == 37, len(docs)

    # summary non-empty for EVERY action; params never leak 'self'
    for name in core.PLUS_ACTIONS:
        entry = docs[name]
        assert isinstance(entry["summary"], str) and entry["summary"].strip(), \
            "empty summary for %s" % name
        assert isinstance(entry["params"], str), name
        assert "self" not in [p.strip().split("=")[0]
                              for p in entry["params"].split(",")], entry

    # notesSlim's params string names the knobs the agent needs, with defaults
    slim = docs["notesSlim"]["params"]
    assert "stripHtml=true" in slim, slim
    assert "maxFieldLength=400" in slim, slim


# ---------------------------------------------------------------- run
run("test1_revlog_default_limit_boundary", test1_revlog_default_limit_boundary)
run("test2_render_card_formats", test2_render_card_formats)
run("test3_bulk_update_unchanged_buckets", test3_bulk_update_unchanged_buckets)
run("test4_notes_slim_truncated_fields", test4_notes_slim_truncated_fields)
run("test5_integrity_buckets", test5_integrity_buckets)
run("test6_replace_contract", test6_replace_contract)
run("test7_plus_info_action_docs", test7_plus_info_action_docs)


def test8_no_network():
    assert NETWORK_ATTEMPTS == [], NETWORK_ATTEMPTS


run("test8_no_network", test8_no_network)

col.close()

print("\n===== SUMMARY =====")
n_pass = sum(1 for _, ok, _ in RESULTS if ok)
for name, ok, _ in RESULTS:
    print("%s  %s" % ("PASS" if ok else "FAIL", name))
print("%d/%d passed" % (n_pass, len(RESULTS)))
sys.exit(0 if n_pass == len(RESULTS) else 1)
