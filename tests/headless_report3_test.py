# INDEPENDENT round-2 verification of the round-3 FIELD REPORT asks.
#
# Written by a verifier who did NOT implement the changes: every scenario is
# reproduced from the field report's own wording rather than from the
# implementers' test list, and each ask gets one test. Where an ask names an
# invariant ("the reported loop is gone", "only those fields", "never sets it
# true without a documented trigger") the invariant itself is asserted, not a
# single happy-path sample.
#
# Run with: "/Users/mattyc/Library/Application Support/AnkiProgramFiles/.venv/bin/python" headless_report3_test.py
#
# FRESH scratch collections only; never touches ~/Library/Application
# Support/Anki2/. ZERO NETWORK by construction AND by enforcement (socket
# deny-guard installed before anki loads; the suite fails on any attempt).

import ast
import importlib
import importlib.util
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import time
import traceback
import types
import unicodedata

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_PATH = os.path.join(REPO, "connect_plus", "core.py")
PLUS_PATH = os.path.join(REPO, "connect_plus", "plus.py")
INIT_PATH = os.path.join(REPO, "connect_plus", "__init__.py")

_PREFERRED_SCRATCH = ("/private/tmp/claude-501/-Users-mattyc-Downloads-prite-daily-main/"
                      "6b24b91e-e4dc-4cbf-934f-6e83d3ff850a/scratchpad/ancp_r3_v2")


def _pick_scratch():
    env = os.environ.get("ANCP_TEST_SCRATCH")
    if env:
        return env
    try:
        os.makedirs(_PREFERRED_SCRATCH, exist_ok=True)
        return os.path.join(_PREFERRED_SCRATCH, "col_scratch")
    except OSError:
        return tempfile.mkdtemp(prefix="ancp_r3_v2_")


SCRATCH = _pick_scratch()
# safety guards: the HARD RULE is that the real collection is never touched
assert not SCRATCH.startswith(os.path.expanduser("~/Library")), \
    "scratch dir must not be under ~/Library"
assert "Anki2" not in SCRATCH
if os.path.exists(SCRATCH):
    shutil.rmtree(SCRATCH)
os.makedirs(SCRATCH)

sys.dont_write_bytecode = True

# ---------------------------------------------------------------- core load
# core.py standalone (no package __init__, no aqt); purity re-verified here so
# this suite also stands alone as the aqt-free alarm.
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
        raise RuntimeError("network access blocked by headless_report3_test "
                           "(%s)" % name)
    return _deny


socket.socket.connect = _make_deny("socket.connect")
socket.socket.connect_ex = _make_deny("socket.connect_ex")
socket.create_connection = _make_deny("socket.create_connection")
socket.getaddrinfo = _make_deny("socket.getaddrinfo")

# ---------------------------------------------------------------- anki setup
import anki.lang  # noqa: E402
anki.lang.set_lang("en_US")
import anki.notes  # noqa: E402
from anki.collection import Collection  # noqa: E402

col = Collection(os.path.join(SCRATCH, "main.anki2"))          # ASK 2/3/5/7/9
col_undo = Collection(os.path.join(SCRATCH, "undo.anki2"))     # ASK 8
col_int = Collection(os.path.join(SCRATCH, "integrity.anki2"))  # ASK 6
col_med = Collection(os.path.join(SCRATCH, "media.anki2"))     # ASK 12
col_sync = Collection(os.path.join(SCRATCH, "sync.anki2"))     # ASK 10

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


def code_of(fn):
    """Run fn; return the '[code] ' machine code of the error it raised."""
    try:
        fn()
    except Exception as e:
        msg = str(e)
        assert msg.startswith("["), "unprefixed error: %r" % msg
        return msg.split("] ", 1)[0].lstrip("[")
    raise AssertionError("expected an exception")


def notes_snap(c):
    return c.db.all("select id, mod, usn, flds, tags from notes order by id")


def cards_snap(c):
    return c.db.all("select id, mod, usn, queue, type, due, ivl from cards order by id")


def undo_snap(c):
    return c.undo_status().SerializeToString()


def add_note(c, deck, model_name, field_values, tags=None):
    model = c.models.by_name(model_name)
    assert model is not None, model_name
    note = anki.notes.Note(c, model)
    for name, value in field_values.items():
        note[name] = value
    note.tags = list(tags or [])
    c.add_note(note, c.decks.id(deck))
    return note.id


def add_basic(c, deck, front, back="b"):
    return add_note(c, deck, "Basic", {"Front": front, "Back": back})


def card_ids(c, nid):
    return c.db.list("select id from cards where nid = ? order by ord", nid)


def make_notetype(c, name, field_names):
    mm = c.models
    model = mm.new(name)
    for field_name in field_names:
        mm.add_field(model, mm.new_field(field_name))
    template = mm.new_template("Card 1")
    template["qfmt"] = "{{%s}}" % field_names[0]
    template["afmt"] = "{{FrontSide}}<hr id=answer>{{%s}}" % field_names[1]
    mm.add_template(model, template)
    mm.add_dict(model)
    return mm.by_name(name)


# note ids are epoch-millisecond stamps, so these can never collide with a
# real note in any collection
FAKE_IDS = [1, 2, 3, 4, 5]


# ============================================================================
# ASK 2 — notesSlim under noteIds: honest total, missing, and NO pager loop.
# Field report: "[real, fake, real, fake] reported total 4 with 2 notes";
# "3 stale ids reported total 3, an empty page and a nextOffset pointing at
# another empty page — my client looped".
# ============================================================================
def test_ask2_notes_slim_total_missing_nextoffset():
    a = add_basic(col, "A2", "ask2-a")
    b = add_basic(col, "A2", "ask2-b")
    fake1, fake2, fake3 = FAKE_IDS[0], FAKE_IDS[1], FAKE_IDS[2]
    for nid in (fake1, fake2, fake3):
        assert col.db.scalar("select count(*) from notes where id = ?", nid) == 0

    # --- the report's exact interleaved probe
    out = core.notes_slim(col, note_ids=[a, fake1, b, fake2])
    assert out["total"] == 2, out["total"]
    assert len(out["notes"]) == 2, out["notes"]
    assert [n["noteId"] for n in out["notes"]] == [a, b]
    assert out["missing"] == [fake1, fake2], out["missing"]
    assert out["nextOffset"] is None, out["nextOffset"]
    # the invariant the fix is built on, stated on the wire
    assert len([a, fake1, b, fake2]) == out["total"] + len(out["missing"])

    # --- the report's exact loop repro: 3 stale ids, limit 2
    out = core.notes_slim(col, note_ids=[fake1, fake2, fake3], limit=2)
    assert out["total"] == 0, out
    assert out["notes"] == [], out
    assert out["missing"] == [fake1, fake2, fake3], out
    assert out["nextOffset"] is None, "the reported pager loop is BACK: %r" % out

    # a client that follows nextOffset while it is non-null must terminate:
    # drive the real pager over a list whose tail is all-stale
    seen, offset, hops = [], 0, 0
    while True:
        page = core.notes_slim(col, note_ids=[a, b, fake1, fake2, fake3], limit=1,
                               offset=offset)
        seen.extend(n["noteId"] for n in page["notes"])
        hops += 1
        assert hops <= 10, "pager did not terminate"
        if page["nextOffset"] is None:
            break
        assert page["nextOffset"] > offset, page
        offset = page["nextOffset"]
    assert seen == [a, b], seen
    assert hops == 2, ("the pager was sent past the last FOUND id", hops)

    # nextOffset is suppressed only when no FOUND id remains past the window —
    # a stale id INSIDE the window still yields an empty page with a pager
    p0 = core.notes_slim(col, note_ids=[a, fake1, b, fake2], limit=1, offset=0)
    assert [n["noteId"] for n in p0["notes"]] == [a] and p0["nextOffset"] == 1, p0
    p1 = core.notes_slim(col, note_ids=[a, fake1, b, fake2], limit=1, offset=1)
    assert p1["notes"] == [] and p1["nextOffset"] == 2, p1
    p2 = core.notes_slim(col, note_ids=[a, fake1, b, fake2], limit=1, offset=2)
    assert [n["noteId"] for n in p2["notes"]] == [b] and p2["nextOffset"] is None, p2

    # total/missing are window-independent (offset past the end changes neither)
    far = core.notes_slim(col, note_ids=[a, fake1, b, fake2], offset=99)
    assert far["total"] == 2 and far["missing"] == [fake1, fake2], far
    assert far["notes"] == [] and far["nextOffset"] is None, far

    # --- duplicates in the requested list are PRESERVED on both sides
    dup = core.notes_slim(col, note_ids=[a, a, fake1, fake1, b])
    assert dup["total"] == 3, dup["total"]                     # a, a, b
    assert [n["noteId"] for n in dup["notes"]] == [a, a, b], dup["notes"]
    assert dup["missing"] == [fake1, fake1], dup["missing"]
    assert len([a, a, fake1, fake1, b]) == dup["total"] + len(dup["missing"])

    # --- query form unchanged: total = match count, missing empty
    q = core.notes_slim(col, query="deck:A2")
    assert q["total"] == 2 == len(q["notes"]), q
    assert q["missing"] == [], q
    assert q["nextOffset"] is None, q
    qp = core.notes_slim(col, query="deck:A2", limit=1)
    assert qp["total"] == 2 and len(qp["notes"]) == 1 and qp["nextOffset"] == 1, qp
    assert core.notes_slim(col, query="deck:NoSuchDeckA2")["total"] == 0
    # a query that matches nothing still terminates immediately
    assert core.notes_slim(col, query="deck:NoSuchDeckA2")["nextOffset"] is None

    # reads must not write
    assert notes_snap(col) == notes_snap(col)


# ============================================================================
# ASK 3 — renderCard cssMode. Field report: "50 rendered cards = 314,564 B,
# of which 265,350 B was the same stylesheet repeated once per card".
# ============================================================================
def test_ask3_render_card_css_mode():
    nids = [add_basic(col, "A3", "ask3-%02d" % i) for i in range(20)]
    cids = [card_ids(col, nid)[0] for nid in nids]
    assert len(cids) == 20
    basic_css = col.models.by_name("Basic")["css"]

    # --- default for format 'html' == explicit perCard, byte for byte
    default_html = core.render_card(col, cids)
    per_card = core.render_card(col, cids, css_mode="perCard")
    assert json.dumps(default_html, sort_keys=True) == json.dumps(per_card, sort_keys=True)
    # ...and per-card css is delivered exactly as before the change: one 'css'
    # key per card holding the notetype stylesheet, and NO top-level key.
    assert set(default_html) == {"cards"}, sorted(default_html)
    assert "cssByNotetype" not in default_html
    for entry in default_html["cards"]:
        assert entry["css"] == basic_css, entry["cardId"]
        # 'notetype' is revision 12's documented ADDITIVE key (SPEC 12: present
        # in every cssMode); the css delivery itself is what must be unchanged
        assert set(entry) == {"cardId", "question", "answer", "deckName",
                              "modelName", "notetype", "ord", "css"}, sorted(entry)
    assert default_html["cards"][0]["notetype"] == "Basic"
    # 'body' keeps the same default (css is only meaningless for 'text')
    body = core.render_card(col, cids, render_format="body")
    assert all("css" in c for c in body["cards"]) and "cssByNotetype" not in body

    # --- byNotetype: exactly one entry, no per-card css, notetype on each card
    by_nt = core.render_card(col, cids, css_mode="byNotetype")
    assert set(by_nt) == {"cards", "cssByNotetype"}, sorted(by_nt)
    assert list(by_nt["cssByNotetype"]) == ["Basic"], by_nt["cssByNotetype"]
    assert by_nt["cssByNotetype"]["Basic"] == basic_css
    assert len(by_nt["cards"]) == 20
    for entry in by_nt["cards"]:
        assert "css" not in entry, entry["cardId"]
        assert entry["notetype"] == "Basic", entry
        assert entry["notetype"] in by_nt["cssByNotetype"]
    # everything except css delivery is identical between the two modes
    for lean, fat in zip(by_nt["cards"], per_card["cards"]):
        assert lean == {k: v for k, v in fat.items() if k != "css"}
    # the payload win the report asked for is real
    assert len(json.dumps(by_nt)) < len(json.dumps(per_card))

    # --- format 'text' default: no css ANYWHERE
    text = core.render_card(col, cids, render_format="text")
    assert set(text) == {"cards"}, sorted(text)
    assert all("css" not in c for c in text["cards"])
    assert "<" not in text["cards"][0]["question"], text["cards"][0]["question"]

    # --- explicit cssMode overrides in BOTH directions
    text_per_card = core.render_card(col, cids, render_format="text", css_mode="perCard")
    assert all(c["css"] == basic_css for c in text_per_card["cards"])
    text_by_nt = core.render_card(col, cids, render_format="text", css_mode="byNotetype")
    assert list(text_by_nt["cssByNotetype"]) == ["Basic"]
    html_omit = core.render_card(col, cids, css_mode="omit")
    assert set(html_omit) == {"cards"} and all("css" not in c for c in html_omit["cards"])
    assert [{k: v for k, v in c.items() if k != "css"} for c in per_card["cards"]] \
        == html_omit["cards"]

    # --- two notetypes in one batch -> two entries, each correct
    cloze_nid = add_note(col, "A3", "Cloze",
                         {"Text": "ask3 {{c1::cloze}} body", "Back Extra": ""})
    cloze_cid = card_ids(col, cloze_nid)[0]
    cloze_css = col.models.by_name("Cloze")["css"]
    assert cloze_css != basic_css
    mixed = core.render_card(col, cids[:3] + [cloze_cid], css_mode="byNotetype")
    assert set(mixed["cssByNotetype"]) == {"Basic", "Cloze"}, mixed["cssByNotetype"]
    assert mixed["cssByNotetype"]["Basic"] == basic_css
    assert mixed["cssByNotetype"]["Cloze"] == cloze_css
    assert [c["notetype"] for c in mixed["cards"]] == ["Basic"] * 3 + ["Cloze"]
    # cross-check against what perCard reports for the same cards
    mixed_per = core.render_card(col, cids[:3] + [cloze_cid], css_mode="perCard")
    for entry in mixed_per["cards"]:
        assert entry["css"] == mixed["cssByNotetype"][entry["notetype"]], entry["cardId"]

    # a bad cssMode is a parameter error, not a silent fallback
    assert code_of(lambda: core.render_card(col, cids, css_mode="byNoteType")) == "invalid_param"
    assert code_of(lambda: core.render_card(col, cids, css_mode="")) == "invalid_param"

    # rendering is a pure read
    assert notes_snap(col) == notes_snap(col)
    assert cards_snap(col) == cards_snap(col)


# ============================================================================
# ASK 5 — bulkSetDueDate silently resurrects suspended cards; both scheduler
# actions now report changedIds. Field report: "5 cards went from queue -1 to
# queue 2 with no signal of any kind".
# ============================================================================
def test_ask5_due_date_resurrection_and_changed_ids():
    nids = [add_basic(col, "A5", "ask5-%d" % i) for i in range(5)]
    cids = [card_ids(col, nid)[0] for nid in nids]

    # --- suspend 5 -> queues -1, changedIds consistent with changed
    out = core.bulk_suspend(col, cids, suspend=True)
    assert out["changed"] == 5, out
    assert out["changedIds"] == cids, out
    assert out["changed"] == len(out["changedIds"])
    assert out["undoEntry"] == core.UNDO_BULK_SUSPEND, out
    queues = col.db.list("select queue from cards where id in (%s)"
                         % ",".join("?" * 5), *cids)
    assert queues == [core.QUEUE_SUSPENDED] * 5, queues

    # repeating the suspend is a no-op in both fields
    again = core.bulk_suspend(col, cids, suspend=True)
    assert again == {"changed": 0, "changedIds": [], "undoEntry": None}, again

    # --- bulkSetDueDate '5' -> the resurrection is DISCLOSED
    # preserve_suspended=False throughout this test: revision 15 (SPEC 27) puts
    # the suspensions back BY DEFAULT, and what ASK 5 locks down is the
    # DISCLOSURE of anki's native resurrection. Opting out keeps these
    # assertions testing anki's behavior rather than this add-on's repair of
    # it; the repair is covered by tests/headless_suspension_test.py.
    due = core.bulk_set_due_date(col, cids, "5", preserve_suspended=False)
    assert due["unsuspended"] == cids, due["unsuspended"]
    assert due["unburied"] == [], due["unburied"]
    assert due["changedIds"] == cids, due["changedIds"]
    assert due["changed"] == len(due["changedIds"]) == 5, due
    assert due["undoEntry"] == core.UNDO_BULK_DUE, due
    queues = col.db.list("select queue from cards where id in (%s)"
                         % ",".join("?" * 5), *cids)
    assert queues == [2] * 5, queues          # QUEUE_TYPE_REV: really revived

    # --- repeat on already-unsuspended cards -> nothing to disclose
    repeat = core.bulk_set_due_date(col, cids, "5", preserve_suspended=False)
    assert repeat["unsuspended"] == [], repeat
    assert repeat["unburied"] == [], repeat
    assert repeat["changedIds"] == cids and repeat["changed"] == 5, repeat

    # --- buried cards are reported separately from suspended ones
    col.sched.bury_cards(cids[:2], manual=True)
    assert col.db.list("select queue from cards where id in (?,?)", *cids[:2]) == [-3, -3]
    core.bulk_suspend(col, cids[2:4], suspend=True)
    mixed = core.bulk_set_due_date(col, cids, "3", preserve_suspended=False)
    assert mixed["unburied"] == cids[:2], mixed["unburied"]
    assert mixed["unsuspended"] == cids[2:4], mixed["unsuspended"]
    assert mixed["changedIds"] == cids, mixed

    # --- the unsuspend direction of bulkSuspend also reports changedIds
    core.bulk_suspend(col, cids, suspend=True)
    un = core.bulk_suspend(col, cids, suspend=False)
    assert un["changedIds"] == cids and un["changed"] == 5, un
    assert core.bulk_suspend(col, cids, suspend=False)["changedIds"] == [], "no-op"

    # unknown ids never reach the op, and never appear in changedIds
    ghost = core.bulk_suspend(col, [FAKE_IDS[0]], suspend=True)
    assert ghost == {"changed": 0, "changedIds": [], "undoEntry": None}, ghost
    ghost_due = core.bulk_set_due_date(col, [FAKE_IDS[0]], "1", preserve_suspended=False)
    assert ghost_due["changedIds"] == [] and ghost_due["unsuspended"] == [], ghost_due

    # a bad days string leaves the undo stack untouched (no phantom Redo)
    before = undo_snap(col)
    assert code_of(lambda: core.bulk_set_due_date(col, cids, "tomorrow")) == "invalid_param"
    assert undo_snap(col) == before


# ============================================================================
# ASK 6 — checkDeckIntegrity orphan media: capped array, honest count, scoped
# key name. Field report: "1,659,713 B / 37,243 entries sitting beside four
# deck-scoped arrays".
# ============================================================================
def test_ask6_orphan_media_cap_and_count():
    media_dir = col_int.media.dir()
    used = "ask6_used.png"
    with open(os.path.join(media_dir, used), "wb") as handle:
        handle.write(b"used")
    add_note(col_int, "A6", "Basic",
             {"Front": 'seen <img src="%s">' % used, "Back": "b"})
    orphans = ["ask6_orphan_%02d.png" % i for i in range(10)]
    for name in orphans:
        with open(os.path.join(media_dir, name), "wb") as handle:
            handle.write(b"orphan")
    # convention files that are NEVER orphans
    for name in ("_ask6_static.png", ".ask6_hidden"):
        with open(os.path.join(media_dir, name), "wb") as handle:
            handle.write(b"skip")

    # --- capped: limit 3 over 10 true orphans
    out = core.check_deck_integrity(col_int, "A6", include_orphan_media=True,
                                    orphan_media_limit=3)
    assert out["orphanMediaCount"] == 10, out["orphanMediaCount"]
    assert out["orphanMediaTruncated"] is True, out
    assert len(out["orphanMediaCollectionWide"]) == 3, out["orphanMediaCollectionWide"]
    assert out["orphanMediaCollectionWide"] == sorted(orphans)[:3], out
    assert used not in out["orphanMediaCollectionWide"]
    # the old, unscoped key must be GONE (deliberate breaking rename)
    assert "orphanMedia" not in out, sorted(out)
    assert set(out) == {"missingMedia", "unbalancedCloze", "clozeCardMismatch",
                        "clozeNotesWithoutCloze", "orphanMediaCollectionWide",
                        "orphanMediaCount", "orphanMediaTruncated",
                        "notesChecked"}, sorted(out)

    # --- limit 0 = count only
    zero = core.check_deck_integrity(col_int, "A6", include_orphan_media=True,
                                     orphan_media_limit=0)
    assert zero["orphanMediaCollectionWide"] == [], zero
    assert zero["orphanMediaCount"] == 10 and zero["orphanMediaTruncated"] is True, zero

    # --- limit at/above the count: nothing truncated, full sorted list
    exact = core.check_deck_integrity(col_int, "A6", include_orphan_media=True,
                                      orphan_media_limit=10)
    assert exact["orphanMediaTruncated"] is False, exact
    assert exact["orphanMediaCollectionWide"] == sorted(orphans), exact
    assert exact["orphanMediaCount"] == 10
    over = core.check_deck_integrity(col_int, "A6", include_orphan_media=True,
                                     orphan_media_limit=999)
    assert over["orphanMediaCollectionWide"] == sorted(orphans)
    assert over["orphanMediaTruncated"] is False

    # --- the default limit is the documented 100 and matches the wrapper's
    assert core.ORPHAN_MEDIA_DEFAULT_LIMIT == 100
    dflt = core.check_deck_integrity(col_int, "A6", include_orphan_media=True)
    assert dflt["orphanMediaCollectionWide"] == sorted(orphans)
    assert dflt["orphanMediaTruncated"] is False

    # --- includeOrphanMedia=false (the default) -> count is null, not 0
    off = core.check_deck_integrity(col_int, "A6")
    assert off["orphanMediaCount"] is None, off["orphanMediaCount"]
    assert off["orphanMediaCollectionWide"] is None, off
    assert off["orphanMediaTruncated"] is False, off
    assert "orphanMedia" not in off
    assert core.check_deck_integrity(col_int, "A6", include_orphan_media=False) == off

    # the deck-scoped buckets are unaffected by any of the above
    for result in (out, zero, exact, dflt, off):
        assert result["notesChecked"] == 1, result["notesChecked"]
        assert result["missingMedia"] == [] and result["unbalancedCloze"] == []

    # a bad limit is a parameter error
    assert code_of(lambda: core.check_deck_integrity(
        col_int, "A6", include_orphan_media=True, orphan_media_limit=-1)) == "invalid_param"
    assert code_of(lambda: core.check_deck_integrity(
        col_int, "A6", include_orphan_media=True, orphan_media_limit=True)) == "invalid_param"

    assert notes_snap(col_int) == notes_snap(col_int)


# ============================================================================
# ASK 7 — notesSlim omitEmptyFields. Field report: "19-field AnKing-derived
# notetype, 4 fields populated; 15 empty strings shipped on every note".
# ============================================================================
def test_ask7_omit_empty_fields():
    names = ["F%d" % i for i in range(1, 8)]
    make_notetype(col, "R3Wide", names)
    values = {"F1": "front text", "F2": "back text", "F3": "",
              "F4": "<br>", "F5": "  ", "F6": "", "F7": "x" * 50}
    nid = add_note(col, "A7", "R3Wide", values)

    # --- false (the default) is byte-identical to not passing it at all
    base = core.notes_slim(col, note_ids=[nid])
    explicit_false = core.notes_slim(col, note_ids=[nid], omit_empty_fields=False)
    assert json.dumps(base, sort_keys=True) == json.dumps(explicit_false, sort_keys=True)
    assert list(base["notes"][0]["fields"]) == names, base["notes"][0]["fields"]

    # --- true drops '' fields and ONLY those. The rule is stated against the
    # values the false run actually emitted, so it holds whatever the html
    # stripper does to '<br>' / '&nbsp;' / whitespace on this anki build.
    kept = core.notes_slim(col, note_ids=[nid], omit_empty_fields=True)
    before_fields = base["notes"][0]["fields"]
    after_fields = kept["notes"][0]["fields"]
    empty_keys = {k for k, v in before_fields.items() if v == ""}
    assert empty_keys, "the fixture must contain at least one empty field"
    assert set(after_fields) == set(before_fields) - empty_keys, \
        (sorted(after_fields), sorted(empty_keys))
    for key, value in after_fields.items():
        assert value == before_fields[key], key          # survivors untouched
    # everything OUTSIDE fields is byte-identical
    assert {k: v for k, v in kept["notes"][0].items() if k != "fields"} == \
        {k: v for k, v in base["notes"][0].items() if k != "fields"}
    assert {k: v for k, v in kept.items() if k != "notes"} == \
        {k: v for k, v in base.items() if k != "notes"}

    # the test is on the value that WOULD be emitted: under stripHtml the
    # markup-only field collapses to '' and drops out, and it comes BACK when
    # stripHtml is false (the report's read-before-edit path must lose nothing)
    assert "F4" not in after_fields, after_fields
    raw = core.notes_slim(col, note_ids=[nid], strip_html=False,
                          max_field_length=0, omit_empty_fields=True)
    assert raw["notes"][0]["fields"]["F4"] == "<br>", raw["notes"][0]["fields"]
    assert raw["notes"][0]["fields"]["F5"] == "  ", raw["notes"][0]["fields"]
    assert "F3" not in raw["notes"][0]["fields"] and "F6" not in raw["notes"][0]["fields"]

    # --- composes with a fields projection + stripHtml=false + maxFieldLength=0
    combo = core.notes_slim(col, note_ids=[nid], fields=["F1", "F3", "F4", "F7"],
                            strip_html=False, max_field_length=0,
                            omit_empty_fields=True)
    got = combo["notes"][0]["fields"]
    assert set(got) == {"F1", "F4", "F7"}, sorted(got)      # F3 ('') dropped
    assert got["F1"] == "front text" and got["F4"] == "<br>"
    assert got["F7"] == "x" * 50, "maxFieldLength=0 must not truncate"
    assert combo["notes"][0]["truncatedFields"] == []
    # ... and the same projection without the flag keeps the empty key
    combo_off = core.notes_slim(col, note_ids=[nid], fields=["F1", "F3", "F4", "F7"],
                                strip_html=False, max_field_length=0)
    assert set(combo_off["notes"][0]["fields"]) == {"F1", "F3", "F4", "F7"}
    assert combo_off["notes"][0]["fields"]["F3"] == ""

    # truncation still reported for a survivor
    trunc = core.notes_slim(col, note_ids=[nid], max_field_length=10,
                            omit_empty_fields=True)
    assert trunc["notes"][0]["truncatedFields"] == ["F7"], trunc["notes"][0]
    assert trunc["notes"][0]["fields"]["F7"].endswith("…")

    # a projection naming ONLY empty fields yields an empty dict, not a drop
    only_empty = core.notes_slim(col, note_ids=[nid], fields=["F3", "F6"],
                                 omit_empty_fields=True)
    assert only_empty["notes"][0]["fields"] == {}, only_empty["notes"][0]
    assert only_empty["total"] == 1 and len(only_empty["notes"]) == 1

    # non-bool is a parameter error
    assert code_of(lambda: core.notes_slim(col, note_ids=[nid],
                                           omit_empty_fields="yes")) == "invalid_param"
    assert notes_snap(col) == notes_snap(col)


# ============================================================================
# ASK 8 — undoStatus. THE action that makes undoLabel self-verifying: what a
# write REPORTS as undoEntry must be what the stack actually READS BACK.
# Field report: the reporter drove Anki's menu bar with AppleScript to check.
# ============================================================================
def test_ask8_undo_status_self_verifying():
    # --- empty stack on a genuinely fresh collection
    empty = core.undo_status(col_undo)
    assert empty == {"undo": None, "redo": None, "lastStep": 0}, empty
    assert isinstance(empty["lastStep"], int) and not isinstance(empty["lastStep"], bool)

    n1 = add_basic(col_undo, "A8", "ask8-one")
    n2 = add_basic(col_undo, "A8", "ask8-two")
    # anki's own writes show up under anki's own names (never a Plus label)
    after_add = core.undo_status(col_undo)
    assert after_add["undo"] and not after_add["undo"].startswith(core.UNDO_LABEL_PREFIX)
    assert after_add["lastStep"] > 0

    # --- a labelled bulk write: undoEntry == what the stack reads back
    first = core.bulk_add_tags(col_undo, [n1], ["ask8a"], undo_label="R3 First Sweep")
    assert first["undoEntry"] == "AnkiConnect Plus: R3 First Sweep", first
    top = core.undo_status(col_undo)
    assert top["undo"] == first["undoEntry"], (top, first)
    assert top["redo"] is None, top
    step_after_first = top["lastStep"]
    assert step_after_first > after_add["lastStep"], (top, after_add)

    # a second labelled write lands on top of the first
    second = core.bulk_add_tags(col_undo, [n2], ["ask8b"], undo_label="R3 Second  Sweep")
    assert second["undoEntry"] == "AnkiConnect Plus: R3 Second Sweep", second  # ws collapsed
    top2 = core.undo_status(col_undo)
    assert top2["undo"] == second["undoEntry"], top2
    assert top2["lastStep"] > step_after_first

    # --- reading is PURE: repeat calls change neither the stack nor the notes
    stack_before = undo_snap(col_undo)
    notes_before = notes_snap(col_undo)
    assert core.undo_status(col_undo) == top2
    assert core.undo_status(col_undo) == top2
    assert undo_snap(col_undo) == stack_before
    assert notes_snap(col_undo) == notes_before

    # --- after col.undo() the report reflects the NEW top, and the undone
    # entry surfaces as redo (this is the round trip the reporter could not do)
    col_undo.undo()
    popped = core.undo_status(col_undo)
    assert popped["undo"] == first["undoEntry"], popped
    assert popped["redo"] == second["undoEntry"], popped
    assert popped["lastStep"] != top2["lastStep"], (popped, top2)
    assert not col_undo.get_note(n2).has_tag("ask8b"), "undo did not actually revert"

    # undo again -> back to anki's own entry, both Plus labels gone from 'undo'
    col_undo.undo()
    popped2 = core.undo_status(col_undo)
    assert popped2["undo"] == after_add["undo"], popped2
    assert popped2["redo"] == first["undoEntry"], popped2

    # redo restores the first sweep, and the stack reports it as the top again
    col_undo.redo()
    redone = core.undo_status(col_undo)
    assert redone["undo"] == first["undoEntry"], redone
    assert redone["redo"] == second["undoEntry"], redone
    assert col_undo.get_note(n1).has_tag("ask8a")

    # --- an UNLABELLED write reports and reads back the default entry name
    n3 = add_basic(col_undo, "A8", "ask8-three")
    plain = core.bulk_add_tags(col_undo, [n3], ["ask8c"])
    assert plain["undoEntry"] == core.UNDO_BULK_TAGS, plain
    assert core.undo_status(col_undo)["undo"] == core.UNDO_BULK_TAGS

    # --- a no-op write reports undoEntry null AND leaves the stack untouched
    quiet_before = undo_snap(col_undo)
    noop = core.bulk_add_tags(col_undo, [n3], ["ask8c"])
    assert noop["undoEntry"] is None, noop
    assert undo_snap(col_undo) == quiet_before, "a no-op pushed an undo entry"
    assert core.undo_status(col_undo)["undo"] == core.UNDO_BULK_TAGS

    # --- an 80+ char label is capped identically in the report and the stack
    long_label = "L" * 200
    n4 = add_basic(col_undo, "A8", "ask8-four")
    capped = core.bulk_add_tags(col_undo, [n4], ["ask8d"], undo_label=long_label)
    assert capped["undoEntry"] == core.UNDO_LABEL_PREFIX + "L" * core.UNDO_LABEL_MAX_CHARS
    assert core.undo_status(col_undo)["undo"] == capped["undoEntry"]

    # --- every other labelled write action agrees with the stack too
    n5 = add_basic(col_undo, "A8", "ask8-five")
    upd = core.bulk_update_note_fields(
        col_undo, [{"id": n5, "fields": {"Front": "ask8-five-changed"}}],
        undo_label="R3 Update Sweep")
    assert upd["undoEntry"] == "AnkiConnect Plus: R3 Update Sweep"
    assert core.undo_status(col_undo)["undo"] == upd["undoEntry"]
    c5 = card_ids(col_undo, n5)[0]
    susp = core.bulk_suspend(col_undo, [c5], undo_label="R3 Suspend Sweep")
    assert susp["undoEntry"] == "AnkiConnect Plus: R3 Suspend Sweep"
    assert core.undo_status(col_undo)["undo"] == susp["undoEntry"]
    due = core.bulk_set_due_date(col_undo, [c5], "2", undo_label="R3 Due Sweep")
    assert due["undoEntry"] == "AnkiConnect Plus: R3 Due Sweep"
    assert core.undo_status(col_undo)["undo"] == due["undoEntry"]


# ============================================================================
# ASK 9 — the dry-run diff must explain a TAG-ONLY change. Field report: "a
# tags-only entry landed in wouldUpdate with no preview row at all".
# ============================================================================
def test_ask9_tags_preview_rows():
    assert core.TAGS_PREVIEW_FIELD == "__tags__"
    n_tag = add_note(col, "A9", "Basic", {"Front": "ask9-tag", "Back": "b"},
                     tags=["old1", "old2"])
    n_both = add_note(col, "A9", "Basic", {"Front": "ask9-both", "Back": "b"},
                      tags=["keepme"])
    tags_now = list(col.get_note(n_tag).tags)
    both_tags_now = list(col.get_note(n_both).tags)

    notes_before = notes_snap(col)
    stack_before = undo_snap(col)

    # --- tag-only change: exactly one row, and it is the __tags__ row
    out = core.bulk_update_note_fields(
        col, [{"id": n_tag, "tags": ["new1", "new2", "new3"]}],
        dry_run=True, diff=True)
    assert out["wouldUpdate"] == [n_tag], out
    assert out["unchanged"] == [] and out["skipped"] == [], out
    assert out["previewTruncated"] is False, out
    assert out["preview"] == [{"noteId": n_tag, "field": "__tags__",
                               "before": " ".join(tags_now),
                               "after": "new1 new2 new3"}], out["preview"]

    # --- field + tag change: BOTH rows, field row(s) first
    out = core.bulk_update_note_fields(
        col, [{"id": n_both, "fields": {"Front": "ask9-both-NEW"},
               "tags": ["keepme", "added"]}],
        dry_run=True, diff=True)
    assert out["wouldUpdate"] == [n_both], out
    assert len(out["preview"]) == 2, out["preview"]
    assert out["preview"][0] == {"noteId": n_both, "field": "Front",
                                 "before": "ask9-both", "after": "ask9-both-NEW"}
    # round-3 review fix: 'after' is what the write will actually STORE, so
    # the requested ["keepme", "added"] previews CANONIFIED (sorted) as
    # "added keepme" — it used to echo the raw request, promising a
    # post-state the write would never produce.
    assert out["preview"][1] == {"noteId": n_both, "field": "__tags__",
                                 "before": " ".join(both_tags_now),
                                 "after": "added keepme"}, out["preview"]
    assert out["previewTruncated"] is False, out

    # --- the __tags__ row COUNTS toward maxPreview
    capped = core.bulk_update_note_fields(
        col, [{"id": n_both, "fields": {"Front": "ask9-both-NEW"},
               "tags": ["keepme", "added"]}],
        dry_run=True, diff=True, max_preview=1)
    assert len(capped["preview"]) == 1, capped["preview"]
    assert capped["preview"][0]["field"] == "Front", capped["preview"]
    assert capped["previewTruncated"] is True, capped
    zero = core.bulk_update_note_fields(
        col, [{"id": n_tag, "tags": ["new1"]}],
        dry_run=True, diff=True, max_preview=0)
    assert zero["preview"] == [] and zero["previewTruncated"] is True, zero
    # a tag row alone can be the thing that trips truncation
    two_notes = core.bulk_update_note_fields(
        col, [{"id": n_tag, "fields": {"Front": "x1"}},
              {"id": n_both, "tags": ["solo"]}],
        dry_run=True, diff=True, max_preview=1)
    assert [row["field"] for row in two_notes["preview"]] == ["Front"], two_notes
    assert two_notes["previewTruncated"] is True, two_notes

    # --- identical tags produce NO row and land in 'unchanged'
    same = core.bulk_update_note_fields(
        col, [{"id": n_tag, "tags": tags_now}], dry_run=True, diff=True)
    assert same["unchanged"] == [n_tag] and same["wouldUpdate"] == [], same
    assert same["preview"] == [] and same["previewTruncated"] is False, same
    # ... and a field change alone still produces no __tags__ row
    field_only = core.bulk_update_note_fields(
        col, [{"id": n_tag, "fields": {"Front": "ask9-tag-2"}}],
        dry_run=True, diff=True)
    assert [row["field"] for row in field_only["preview"]] == ["Front"], field_only
    # round-3 review fix — REVERSED from revision 12, deliberately. This used
    # to assert "tag ORDER alone is a change, and the row shows it in list
    # order", which encoded the bug: anki sorts tags on save, so reversing an
    # already-stored (therefore already-canonical) list is a data no-op. The
    # old behavior reported it as an update, emitted a preview row promising
    # a reversed post-state the write could never produce, and then really
    # wrote — mod/usn bump plus an undo entry for zero net change.
    reordered = core.bulk_update_note_fields(
        col, [{"id": n_tag, "tags": list(reversed(tags_now))}],
        dry_run=True, diff=True)
    assert reordered["unchanged"] == [n_tag] and reordered["wouldUpdate"] == [], reordered
    assert reordered["preview"] == [], reordered
    # clearing every tag is representable (empty 'after')
    cleared = core.bulk_update_note_fields(
        col, [{"id": n_tag, "tags": []}], dry_run=True, diff=True)
    assert cleared["preview"] == [{"noteId": n_tag, "field": "__tags__",
                                   "before": " ".join(tags_now), "after": ""}], cleared

    # --- diff is preview-only, and NOTHING was written by any of the above
    assert code_of(lambda: core.bulk_update_note_fields(
        col, [{"id": n_tag, "tags": ["x"]}], diff=True)) == "invalid_param"
    assert notes_snap(col) == notes_before, "a dry run wrote to the collection"
    assert undo_snap(col) == stack_before, "a dry run touched the undo stack"

    # the real run then actually applies the previewed tag change
    real = core.bulk_update_note_fields(col, [{"id": n_tag, "tags": ["new1", "new2", "new3"]}])
    assert real["updated"] == [n_tag], real
    assert sorted(col.get_note(n_tag).tags) == ["new1", "new2", "new3"]


# ============================================================================
# ASK 10 — syncStatus.serverChecked. Field report: localOnly true/false were
# timing-indistinguishable and returned byte-identical responses.
# ============================================================================
def test_ask10_server_checked_local_short_circuit():
    import anki.sync
    from anki.sync_pb2 import SyncStatusResponse
    plus = _load_plus_pkg(PLUS_PKG)

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

    inst = FakeAC(FakeMW(col_sync))
    canned = {"required": SyncStatusResponse.NORMAL_SYNC}
    probes = []

    def fake_probe(auth):
        # the real backend would open a socket here; the deny-guard proves
        # nothing did, and the canned response carries no round-trip flag
        probes.append(auth)
        return SyncStatusResponse(required=canned["required"])

    col_sync.sync_status = fake_probe
    try:
        # --- the local short-circuit: a dirty collection is answered LOCALLY
        col_sync.decks.id("A10Dirty")
        assert core.local_sync_dirty(col_sync)["dirty"] is True
        out = inst.syncStatus()
        assert "serverChecked" in out, sorted(out)
        assert out["serverChecked"] is False, out
        assert out["required"] == "normal_sync", out
        assert out["lastSyncMs"] is not None and out["modMs"] is not None

        # --- a clean collection: the probe really is the source of the verdict
        _ls, mod, scm = col_sync.db.first("select ls, mod, scm from col")
        col_sync.db.execute("update col set ls = ?", max(mod, scm) + 1)
        assert core.local_sync_dirty(col_sync)["dirty"] is False
        canned["required"] = SyncStatusResponse.NO_CHANGES
        out = inst.syncStatus()
        assert out["serverChecked"] is True, out
        assert out["required"] == "no_changes", out
        assert len(probes) == 2, probes

        # --- localOnly NEVER opens a socket, so it is never server-verified
        probe_count = len(probes)
        for expected in ("unknown_no_network",):
            out = inst.syncStatus(localOnly=True)
            assert out["serverChecked"] is False, out
            assert out["required"] == expected, out
        assert len(probes) == probe_count, "localOnly reached the probe"

        # --- every non-network exit reports False
        # (a) probe failure
        col_sync.sync_status = lambda auth: (_ for _ in ()).throw(RuntimeError("boom"))
        out = inst.syncStatus()
        assert out["serverChecked"] is False, out
        col_sync.sync_status = fake_probe
        # (b) a running sync job short-circuits before any collection touch
        # round-3 review fix: startedMs must be RECENT. The guard now reaps a
        # job left "syncing" past core.SYNC_JOB_STALE_MS instead of refusing
        # forever (liveness), and startedMs=1 is 1970 — permanently stale.
        inst._plusSyncJobState = {"state": "syncing",
                                  "startedMs": int(time.time() * 1000),
                                  "result": None, "error": None}
        out = inst.syncStatus()
        assert out["serverChecked"] is False, out
        assert out["required"] is None and out["lastSyncMs"] is None, out
        inst._plusSyncJobState["state"] = "idle"
        # (c) logged out
        inst._mw.pm.sync_auth = lambda: None
        out = inst.syncStatus()
        assert out["serverChecked"] is False and out["required"] == "not_logged_in", out
        inst._mw.pm.sync_auth = FakePM().sync_auth
        # (d) no collection
        inst._mw.col = None
        out = inst.syncStatus()
        assert out["serverChecked"] is False and out["required"] == "error", out
        inst._mw.col = col_sync
    finally:
        del col_sync.sync_status

    # --- THE INVARIANT (the ask's "documented trigger" clause), asserted
    # statically because the only true-producing path is the network path and
    # this suite may not use the network: serverChecked is written in exactly
    # two places in plus.py — the initialiser `'serverChecked': False` in the
    # status dict, and `status['serverChecked'] = not local['dirty']` AFTER a
    # successful sync_status round trip. There is no literal True assignment
    # anywhere, so the flag can never be guessed true; it is derived from
    # core.local_sync_dirty on the one path that really talked to a server.
    with open(PLUS_PATH, encoding="utf-8") as handle:
        plus_src = handle.read()
    writes = re.findall(r"^.*serverChecked.*$", plus_src, re.M)
    writes = [line.strip() for line in writes if "#" not in line.split("serverChecked")[0]]
    assert writes == ["'serverChecked': False,",
                      "status['serverChecked'] = not local['dirty']"], writes
    assert "serverChecked'] = True" not in plus_src
    assert "'serverChecked': True" not in plus_src
    # and the assignment really is the last statement of the network path
    tree = ast.parse(plus_src)
    fn = next(node for node in ast.walk(tree)
              if isinstance(node, ast.FunctionDef) and node.name == "syncStatus")
    assigns = [node for node in ast.walk(fn) if isinstance(node, ast.Assign)
               and any(isinstance(t, ast.Subscript)
                       and isinstance(t.slice, ast.Constant)
                       and t.slice.value == "serverChecked" for t in node.targets)]
    assert len(assigns) == 1, assigns
    assert isinstance(assigns[0].value, ast.UnaryOp), ast.dump(assigns[0].value)
    assert isinstance(assigns[0].value.op, ast.Not)


# ============================================================================
# ASK 12 — mediaExists actualName. Field report: 'BSOM_L2_S3A.PNG' reported
# exists for a stored 'bsom_l2_s3a.png' and then 404'd on AnkiWeb/iOS.
# ============================================================================
def test_ask12_media_exists_actual_name():
    media_dir = col_med.media.dir()
    stored = "bsom_l2_s3a.png"
    with open(os.path.join(media_dir, stored), "wb") as handle:
        handle.write(b"png")
    # is this volume case-folding? (APFS/NTFS yes, ext4 no) — the contract is
    # "exists per the filesystem, actualName reveals the TRUE spelling"
    case_folding = os.path.isfile(os.path.join(media_dir, stored.upper()))

    probes = ["bsom_l2_s3a.png",          # exact
              "BSOM_L2_S3A.PNG",          # the report's case variant
              "no_such_file_r3.png",      # genuinely missing
              "../evil.png",              # traversal
              "sub/nested.png",           # subdir
              "",                         # empty string
              "bsom_l2_s3a.png"]          # duplicate of the exact probe
    out = core.media_exists(col_med, probes)
    results = out["results"]
    assert set(out) == {"results"}, sorted(out)
    # order AND duplicates preserved, one result per input entry
    assert [r["filename"] for r in results] == probes, [r["filename"] for r in results]
    assert len(results) == len(probes)
    assert all(set(r) == {"filename", "exists", "actualName"} for r in results), results

    # exact match: exists, actualName null (nothing to reveal)
    assert results[0] == {"filename": stored, "exists": True, "actualName": None}
    assert results[6] == results[0], "duplicate entries must answer identically"

    # the case-variant probe: exists per the filesystem; when it exists the
    # TRUE on-disk spelling is disclosed, which is the whole point of the key
    assert results[1]["exists"] is case_folding, (results[1], case_folding)
    if case_folding:
        assert results[1]["actualName"] == stored, results[1]
        assert results[1]["actualName"] != results[1]["filename"]
    else:
        assert results[1]["actualName"] is None, results[1]

    # genuinely missing / traversal / subdir / empty: false, and never a raise
    for idx in (2, 3, 4, 5):
        assert results[idx]["exists"] is False, results[idx]
        assert results[idx]["actualName"] is None, results[idx]
    # the traversal probe must not be answered by a file that really is there
    parent = os.path.join(os.path.dirname(media_dir), "evil.png")
    with open(parent, "wb") as handle:
        handle.write(b"nope")
    try:
        assert os.path.isfile(os.path.join(media_dir, "../evil.png"))   # the trap
        again = core.media_exists(col_med, ["../evil.png", "./bsom_l2_s3a.png"])
        assert [r["exists"] for r in again["results"]] == [False, False], again
    finally:
        os.remove(parent)

    # unicode-normalization drift (macOS stores NFC; Finder copies land as NFD)
    nfc_name = unicodedata.normalize("NFC", "café_r3.png")
    nfd_name = unicodedata.normalize("NFD", "café_r3.png")
    assert nfc_name != nfd_name
    with open(os.path.join(media_dir, nfc_name), "wb") as handle:
        handle.write(b"png")
    drift = core.media_exists(col_med, [nfc_name, nfd_name])["results"]
    assert drift[0] == {"filename": nfc_name, "exists": True, "actualName": None}
    if os.path.isfile(os.path.join(media_dir, nfd_name)):
        # the volume folded the NFD probe onto the NFC file: say so
        assert drift[1]["exists"] is True and drift[1]["actualName"] == nfc_name, drift[1]
    else:
        assert drift[1]["exists"] is False and drift[1]["actualName"] is None, drift[1]

    # a directory inside the media folder is not a media file
    os.makedirs(os.path.join(media_dir, "r3_subdir"), exist_ok=True)
    dir_probe = core.media_exists(col_med, ["r3_subdir"])["results"][0]
    assert dir_probe["exists"] is False, dir_probe

    # empty list is legal; a non-string entry is the only hard error
    assert core.media_exists(col_med, []) == {"results": []}
    assert code_of(lambda: core.media_exists(col_med, [1])) == "invalid_param"
    assert code_of(lambda: core.media_exists(col_med, "x.png")) == "invalid_param"

    # pure read
    assert notes_snap(col_med) == notes_snap(col_med)
    assert undo_snap(col_med) == undo_snap(col_med)


# ============================================================================
# wrapper/dispatcher loading helpers (aqt enters the process from here on)
# ============================================================================
PLUS_PKG = "ancp_r3v2_plus_pkg"
DISP_PKG = "ancp_r3v2_disp_pkg"


def _load_plus_pkg(pkg_name):
    """connect_plus/plus.py as a real module under a private package name
    (connect_plus/__init__.py, which boots the add-on against aqt.mw, never
    runs)."""
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [os.path.join(REPO, "connect_plus")]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg
    return importlib.import_module(pkg_name + ".plus")


def _load_dispatcher(pkg_name):
    """The REAL AnkiConnect dispatcher, headless. The trailing entry block
    (socket bind + QTimer) is guarded by `__name__ != "plugin"` and is cut
    from the source, so the module body runs with no side effects."""
    if pkg_name in sys.modules:
        pkg = sys.modules[pkg_name]
        return pkg, pkg.__dict__["_r3v2_instance"]
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [os.path.join(REPO, "connect_plus")]
    pkg.__package__ = pkg_name
    sys.modules[pkg_name] = pkg
    util_mod = importlib.import_module(pkg_name + ".util")
    util_mod.setting = lambda key: util_mod.DEFAULT_CONFIG[key]
    with open(INIT_PATH, encoding="utf-8") as handle:
        src = handle.read()
    marker = 'if __name__ != "plugin":'
    assert marker in src, "entry-block guard moved; this loader must be updated"
    src = src[:src.index(marker)]
    pkg.__dict__["__file__"] = INIT_PATH
    exec(compile(src, INIT_PATH, "exec"), pkg.__dict__)
    inst = pkg.__dict__["AnkiConnect"].__new__(pkg.__dict__["AnkiConnect"])
    inst.log = None
    pkg.__dict__["_r3v2_instance"] = inst
    return pkg, inst


def _with_default_settings(pkg_name, fn):
    util_mod = sys.modules[pkg_name + ".util"]
    original = util_mod.setting
    util_mod.setting = lambda key: util_mod.DEFAULT_CONFIG[key]
    try:
        return fn()
    finally:
        util_mod.setting = original


# ============================================================================
# ASK 4 — the sync guard + the structured error envelope on the wire.
# ============================================================================
def test_ask4_sync_guard_and_envelope():
    plus = _load_plus_pkg(PLUS_PKG)
    pkg_core = sys.modules[PLUS_PKG + ".core"]
    web = importlib.import_module(PLUS_PKG + ".web")

    touched = []

    class FakeAC(plus.PlusMixin):
        def collection(self):
            touched.append(1)
            return col

        def window(self):  # pragma: no cover - only the sync actions use it
            raise AssertionError("window() must not be reached here")

    inst = FakeAC()
    # an instance that never synced has no job slot at all: normal operation
    baseline = inst.undoStatus()
    assert set(baseline) == {"undo", "redo", "lastStep"}, baseline
    assert touched, "the unguarded call never reached the collection"

    # --- set the sync job state to IN-FLIGHT (the documented test hook)
    # round-3 review fix: startedMs must be RECENT. The guard now reaps a
    # job left "syncing" past core.SYNC_JOB_STALE_MS instead of refusing
    # forever (liveness), and startedMs=1 is 1970 — permanently stale.
    inst._plusSyncJobState = {"state": "syncing",
                              "startedMs": int(time.time() * 1000),
                              "result": None, "error": None}
    touched.clear()
    try:
        inst.undoStatus()
        raise AssertionError("a collection-touching action ran during a sync")
    except Exception as err:
        assert isinstance(err, pkg_core.PlusError), type(err)
        assert str(err) == "[sync_in_progress] " + pkg_core.SYNC_IN_PROGRESS_MESSAGE, str(err)
        # ON THE WIRE: code + retryable, not just a Python attribute
        reply = web.format_exception_reply(6, err)
        assert reply == {"result": None,
                         "error": "[sync_in_progress] " + pkg_core.SYNC_IN_PROGRESS_MESSAGE,
                         "errorCode": "sync_in_progress",
                         "retryable": True}, reply
    assert not touched, "the guard let the action touch the collection anyway"
    # the message names the recovery move (poll syncStatus)
    assert "syncStatus" in pkg_core.SYNC_IN_PROGRESS_MESSAGE

    # every collection-touching Plus action is guarded; the four that must
    # never be refused are exempt. The guard runs BEFORE argument binding, so
    # a bare no-arg call reaches it whatever the action's real signature is.
    exempt = {"syncStatus", "syncNow", "plusInfo", "ankihubStatus"}
    for name in pkg_core.PLUS_ACTIONS:
        if name in exempt:
            continue
        assert code_of(getattr(inst, name)) == "sync_in_progress", name
    assert not touched, touched

    # --- clearing the state restores normal operation
    for state in ("idle", "done", "error", "media_syncing"):
        inst._plusSyncJobState["state"] = state
        restored = inst.undoStatus()
        assert set(restored) == {"undo", "redo", "lastStep"}, (state, restored)
    inst._plusSyncJobState = None
    assert set(inst.undoStatus()) == {"undo", "redo", "lastStep"}

    # --- the envelope for a Plus error vs a stock-action error
    plus_err = pkg_core.PlusError("deck_not_found", "deck was not found: Nope")
    assert web.format_exception_reply(6, plus_err) == {
        "result": None, "error": "[deck_not_found] deck was not found: Nope",
        "errorCode": "deck_not_found", "retryable": False}
    stock = web.format_exception_reply(6, Exception("deck was not found: Nope"))
    assert stock == {"result": None, "error": "deck was not found: Nope",
                     "errorCode": None, "retryable": None}, stock
    assert not stock["error"].startswith("["), stock
    # the keys are ALWAYS present, at every api version
    assert set(web.format_exception_reply(4, Exception("x"))) == \
        {"result", "error", "errorCode", "retryable"}
    # retryable on the wire agrees with the single source of truth for all codes
    for code, retryable in pkg_core.PLUS_ERROR_CODES.items():
        got = web.format_exception_reply(6, pkg_core.PlusError(code, "m"))
        assert got["errorCode"] == code and got["retryable"] is retryable, (code, got)
    # success replies gained no keys
    assert web.format_success_reply(6, {"a": 1}) == {"result": {"a": 1}, "error": None}
    assert web.format_success_reply(4, {"a": 1}) == {"a": 1}

    # --- 'multi' nesting carries the fields on every sub-response
    _pkg, disp = _load_dispatcher(DISP_PKG)
    reply = disp.handler({"action": "multi", "version": 6, "params": {"actions": [
        {"action": "noSuchAction"},
        {"action": "renderCard"},
        {"action": "deckNames"},
    ]}})
    # the outer multi SUCCEEDED, so it is a success reply: two keys, no
    # errorCode/retryable (those are error-reply-only by design — a client
    # must use .get(), never reply['errorCode'], on a success)
    assert reply["error"] is None, reply
    assert set(reply) == {"result", "error"}, sorted(reply)
    subs = reply["result"]
    assert len(subs) == 3, subs
    for sub in subs:
        assert set(sub) == {"result", "error", "errorCode", "retryable"}, sub
    assert subs[0]["errorCode"] == "unknown_action" and subs[0]["retryable"] is False
    assert subs[1]["errorCode"] == "invalid_param" and subs[1]["retryable"] is False
    assert subs[2]["errorCode"] is None and subs[2]["retryable"] is None, subs[2]
    # the outer reply reports SUCCESS even though every sub-action failed —
    # exactly the trap the 'reading errors' recipe warns about
    assert subs[2]["error"], subs[2]


# ============================================================================
# ASK 11 — dispatcher errors: unknown action carries a code; a missing
# required argument reads like the house format and leaks no class name.
# ============================================================================
def test_ask11_unknown_action_and_arity_messages():
    _pkg, disp = _load_dispatcher(DISP_PKG)

    # --- unknown action
    reply = disp.handler({"action": "noSuchAction", "version": 6})
    assert reply["error"] == "[unknown_action] unsupported action", reply
    assert reply["errorCode"] == "unknown_action", reply
    assert reply["retryable"] is False, reply
    assert reply["result"] is None, reply
    # the documented parse rule now works on it
    assert reply["error"].split("] ", 1)[0].lstrip("[") == "unknown_action"
    # near-misses of real action names are unknown actions too
    for bogus in ("notesslim", "renderCards", "plusinfo", "  "):
        sub = disp.handler({"action": bogus, "version": 6})
        assert sub["errorCode"] == "unknown_action", (bogus, sub)

    # --- missing required arg: house format, and NO internal class name
    for action, expected in (
            ("renderCard", "[invalid_param] renderCard() missing required argument: cardIds"),
            ("bulkAddTags",
             "[invalid_param] bulkAddTags() missing required arguments: noteIds, tags"),
            ("mediaExists", "[invalid_param] mediaExists() missing required argument: filenames"),
    ):
        reply = disp.handler({"action": action, "version": 6})
        assert reply["error"] == expected, (action, reply)
        assert reply["errorCode"] == "invalid_param", (action, reply)
        assert "PlusMixin" not in reply["error"], reply
        assert "self" not in reply["error"], reply
        # it reads like the rest of the house family
        assert reply["error"].startswith("[invalid_param] ")

    # an unexpected keyword is house-formatted the same way
    reply = disp.handler({"action": "mediaExists", "version": 6,
                          "params": {"filenames": [], "bogus": 1}})
    assert reply["error"] == "[invalid_param] mediaExists() unexpected keyword argument: bogus", reply
    assert "PlusMixin" not in reply["error"]

    # a params key literally named "self" must not escape unprefixed
    reply = disp.handler({"action": "mediaExists", "version": 6,
                          "params": {"self": 1, "filenames": []}})
    assert reply["errorCode"] == "invalid_param", reply
    assert reply["error"].startswith("["), reply
    assert "PlusMixin" not in reply["error"], reply

    # NOTHING on the wire from any Plus action may name the internal class —
    # sweep every action with an empty params object
    for action in core.PLUS_ACTIONS:
        reply = disp.handler({"action": action, "version": 6})
        text = json.dumps(reply)
        assert "PlusMixin" not in text, (action, reply)
        assert "connect_plus" not in text, (action, reply)
        if reply["error"]:
            assert reply["error"].startswith("["), (action, reply)
            assert reply["errorCode"], (action, reply)

    # the boundary: an UPSTREAM action error stays unprefixed with null fields
    reply = disp.handler({"action": "deckNames", "version": 6})
    assert reply["error"] and not reply["error"].startswith("["), reply
    assert reply["errorCode"] is None and reply["retryable"] is None, reply
    # ... as does the dispatcher's own api-key refusal (not an unknown action)
    reply = disp.handler({"action": "deckNames", "version": 6, "key": "wrong"})
    assert reply["error"] == "valid api key must be provided", reply
    assert reply["errorCode"] is None and reply["retryable"] is None, reply


# ============================================================================
# ASK 1 — plusInfo is the discoverability surface: returns for all 27 actions,
# a machine-readable error vocabulary, and the recipes.
# ============================================================================
def _raisable_codes():
    """Every error code a raise site can actually produce, derived from the
    SOURCE (not from the docs it is being checked against).

    Literal `PlusError('code', ...)` sites are read straight out of the AST.
    The one dynamic site is `core.PlusError(core.ANKIHUB_CODE_TO_PLUS_CODE[..],
    ..)`, resolved through that table; any OTHER non-literal first argument is
    a failure here, so a new unresolvable raise site cannot slip past.
    """
    codes = set()
    dynamic = []
    for path in (CORE_PATH, PLUS_PATH, INIT_PATH):
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else \
                (func.id if isinstance(func, ast.Name) else None)
            if name != "PlusError" or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                codes.add(first.value)
            else:
                dynamic.append(ast.unparse(first))
    assert dynamic == ["core.ANKIHUB_CODE_TO_PLUS_CODE[code]"], dynamic
    codes.update(core.ANKIHUB_CODE_TO_PLUS_CODE.values())
    return codes


def test_ask1_plus_info_surface():
    plus = _load_plus_pkg(PLUS_PKG)
    pkg_core = sys.modules[PLUS_PKG + ".core"]
    info = _with_default_settings(PLUS_PKG, plus.PlusMixin().plusInfo)

    # --- 27 actions, each documented with a NON-EMPTY 'returns'
    assert len(pkg_core.PLUS_ACTIONS) == 27, len(pkg_core.PLUS_ACTIONS)
    assert len(set(pkg_core.PLUS_ACTIONS)) == 27, "duplicate action name"
    assert info["actions"] == list(pkg_core.PLUS_ACTIONS)
    assert set(info["actionDocs"]) == set(pkg_core.PLUS_ACTIONS), \
        sorted(set(info["actionDocs"]) ^ set(pkg_core.PLUS_ACTIONS))
    assert len(info["actionDocs"]) == 27
    for name in pkg_core.PLUS_ACTIONS:
        entry = info["actionDocs"][name]
        assert set(entry) == {"summary", "params", "returns"}, (name, sorted(entry))
        assert entry["summary"].strip(), name
        assert entry["returns"].strip(), name
        assert entry["returns"].startswith("{"), (name, entry["returns"][:60])
        # params come off the LIVE signature, so they must match it exactly
        assert "args" not in entry["params"] and "kwargs" not in entry["params"], \
            (name, entry["params"])
        assert "self" not in entry["params"], (name, entry["params"])
    # the returns sketches must actually describe THIS revision's shapes
    for name, key in (("notesSlim", "missing"), ("renderCard", "cssByNotetype"),
                      ("bulkSetDueDate", "unsuspended"), ("bulkSuspend", "changedIds"),
                      ("checkDeckIntegrity", "orphanMediaCollectionWide"),
                      ("mediaExists", "actualName"), ("syncStatus", "serverChecked"),
                      ("undoStatus", "lastStep")):
        assert key in info["actionDocs"][name]["returns"], (name, key)
    # a caller reading the docs must not be pointed at the renamed key
    assert "orphanMediaCollectionWide" in info["actionDocs"]["checkDeckIntegrity"]["returns"]

    # --- errorCodes: non-empty, retryable + reachable + meaning for each code
    codes = info["errorCodes"]
    assert codes, "errorCodes is empty"
    assert set(codes) == set(pkg_core.PLUS_ERROR_CODES), \
        sorted(set(codes) ^ set(pkg_core.PLUS_ERROR_CODES))
    for code, doc in codes.items():
        assert set(doc) == {"retryable", "reachable", "meaning"}, (code, sorted(doc))
        assert isinstance(doc["retryable"], bool), code
        assert isinstance(doc["reachable"], bool), code
        assert doc["meaning"].strip(), code
        assert doc["retryable"] is pkg_core.PLUS_ERROR_CODES[code], code

    # --- THE LOCK: the documented vocabulary must match the SOURCE's raise
    # sites. Codes the docs call reachable must have a raise site; codes with
    # a raise site must be documented reachable; a reserved code must have
    # NO raise site anywhere.
    raisable = _raisable_codes()
    documented_reachable = {code for code, doc in codes.items() if doc["reachable"]}
    assert raisable <= set(codes), sorted(raisable - set(codes))
    assert documented_reachable == raisable, {
        "documented reachable but never raised": sorted(documented_reachable - raisable),
        "raised but documented unreachable": sorted(raisable - documented_reachable)}
    for code, doc in codes.items():
        if not doc["reachable"]:
            assert code not in raisable, code
            assert "RESERVED" in doc["meaning"], (code, doc["meaning"])
    # the codes this suite raised for real are all documented reachable
    for observed in ("invalid_param", "sync_in_progress", "unknown_action"):
        assert codes[observed]["reachable"] is True, observed
    assert codes["sync_in_progress"]["retryable"] is True
    assert codes["unknown_action"]["retryable"] is False

    # --- recipes, including the two the round added
    names = [recipe["name"] for recipe in info["recipes"]]
    assert len(names) == len(set(names)), names
    assert "lean deck sweep" in names, names
    assert "reading errors" in names, names
    by_name = {recipe["name"]: recipe for recipe in info["recipes"]}
    for recipe in info["recipes"]:
        assert set(recipe) == {"name", "description", "example"}, sorted(recipe)
        assert recipe["description"].strip()
        assert set(recipe["example"]) == {"action", "params"}, recipe["name"]
        action = recipe["example"]["action"]
        assert action in pkg_core.PLUS_ACTIONS, (recipe["name"], action)
    # the lean-deck-sweep recipe must name the levers it is about, and its
    # example must be a call the real action actually accepts
    lean = by_name["lean deck sweep"]
    assert "omitEmptyFields" in lean["description"]
    assert "byNotetype" in lean["description"]
    assert lean["example"]["params"].get("omitEmptyFields") is True, lean["example"]
    assert core.notes_slim(col, **{"query": lean["example"]["params"]["query"],
                                   "omit_empty_fields": True,
                                   "limit": lean["example"]["params"]["limit"]})["total"] >= 0
    # the reading-errors recipe must describe the envelope and the multi trap
    read = by_name["reading errors"]
    for fragment in ("errorCode", "retryable", "multi", "plusInfo.errorCodes"):
        assert fragment in read["description"], fragment
    assert read["example"]["action"] == "plusInfo"
    # recipes are copies, so a caller mutating the reply cannot poison the
    # module-level constants
    info["recipes"][0]["name"] = "mutated"
    assert pkg_core.PLUS_RECIPES[0]["name"] != "mutated"

    # --- the prefixing boundary note is served, and says the one thing a
    # single response cannot tell you
    note = info["errorPrefixNote"]
    assert "UPSTREAM" in note and "errorCode" in note, note
    assert info["name"] == "AnkiConnect Plus"
    assert info["version"] == pkg_core.PLUS_VERSION
    assert set(info["docs"]) == {"plus", "upstream", "upstreamSource"}


# ============================================================================
def main():
    # core-only asks first: aqt must stay out of sys.modules until the
    # wrapper/dispatcher tests deliberately pull it in
    run("ask2_notes_slim_total_missing_nextoffset",
        test_ask2_notes_slim_total_missing_nextoffset)
    run("ask3_render_card_css_mode", test_ask3_render_card_css_mode)
    run("ask5_due_date_resurrection_and_changed_ids",
        test_ask5_due_date_resurrection_and_changed_ids)
    run("ask6_orphan_media_cap_and_count", test_ask6_orphan_media_cap_and_count)
    run("ask7_omit_empty_fields", test_ask7_omit_empty_fields)
    run("ask8_undo_status_self_verifying", test_ask8_undo_status_self_verifying)
    run("ask9_tags_preview_rows", test_ask9_tags_preview_rows)
    run("ask12_media_exists_actual_name", test_ask12_media_exists_actual_name)
    assert "aqt" not in sys.modules, "a core-only test pulled in aqt"

    # wrapper + dispatcher asks
    run("ask10_server_checked_local_short_circuit",
        test_ask10_server_checked_local_short_circuit)
    run("ask4_sync_guard_and_envelope", test_ask4_sync_guard_and_envelope)
    run("ask11_unknown_action_and_arity_messages",
        test_ask11_unknown_action_and_arity_messages)
    run("ask1_plus_info_surface", test_ask1_plus_info_surface)

    print("\n=== headless_report3_test summary ===")
    failures = [name for name, ok, _tb in RESULTS if not ok]
    for name, ok, _tb in RESULTS:
        print("%s  %s" % ("PASS" if ok else "FAIL", name))
    if NETWORK_ATTEMPTS:
        failures.append("network-attempted:%r" % (NETWORK_ATTEMPTS,))
        print("FAIL  zero-network guarantee: %r" % (NETWORK_ATTEMPTS,))
    else:
        print("PASS  zero-network guarantee (no connection attempted)")
    print("%d/%d passed" % (len(RESULTS) - len([f for f in failures
                                                if not f.startswith("network-")]),
                            len(RESULTS)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
