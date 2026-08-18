# Regression tests for the ROUND-3 REVIEW fix pass.
#
# One test per finding the round-3 review raised, written to fail against the
# pre-fix code. The theme is the project's guiding principle: the response a
# caller reads must match what the add-on actually DID. Four of these findings
# were exactly that bug — a documented shape that the code did not emit, a
# preview promising a post-state the write would not produce, a counter
# documented as monotonic that silently reset, and a retryable error code that
# could never become satisfiable.
#
# Run with: "/Users/mattyc/Library/Application Support/AnkiProgramFiles/.venv/bin/python" headless_round3review_test.py
#
# FRESH scratch collections only; never touches ~/Library/Application
# Support/Anki2/. Zero network by construction and by enforcement.

import base64
import importlib
import importlib.util
import io
import os
import re
import shutil
import socket
import struct
import sys
import tempfile
import time
import traceback
import types
import zlib

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE_PATH = os.path.join(REPO, "connect_plus", "core.py")
INIT_PATH = os.path.join(REPO, "connect_plus", "__init__.py")
SPEC_PATH = os.path.join(REPO, "SPEC.md")
README_PATH = os.path.join(REPO, "README.md")
PLUS_PKG = "ancp_r3rev_pkg"

SCRATCH = (os.environ.get("ANCP_TEST_SCRATCH")
           or tempfile.mkdtemp(prefix="ancp_r3rev_"))
assert not SCRATCH.startswith(os.path.expanduser("~/Library")), \
    "scratch dir must not be under ~/Library"
assert "Anki2" not in SCRATCH
if os.path.exists(SCRATCH):
    shutil.rmtree(SCRATCH)
os.makedirs(SCRATCH)
sys.dont_write_bytecode = True

# ---------------------------------------------------------------- core load
spec = importlib.util.spec_from_file_location("core", CORE_PATH)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
assert "aqt" not in sys.modules, "core.py (or its imports) pulled in aqt"

# ---------------------------------------------------------------- net guard
NETWORK_ATTEMPTS = []


def _make_deny(name):
    def _deny(*args, **kwargs):
        NETWORK_ATTEMPTS.append((name, args[:2]))
        raise RuntimeError("network access blocked by headless_round3review_test "
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

col = Collection(os.path.join(SCRATCH, "main.anki2"))
col_undo = Collection(os.path.join(SCRATCH, "undo.anki2"))

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


def add_note(c, deck, model_name, field_values, tags=None):
    model = c.models.by_name(model_name)
    note = anki.notes.Note(c, model)
    for name, value in field_values.items():
        note[name] = value
    note.tags = list(tags or [])
    c.add_note(note, c.decks.id(deck))
    return note.id


def make_png(w=16, h=16):
    def chunk(t, d):
        return (struct.pack(">I", len(d)) + t + d
                + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    idat = zlib.compress((b"\x00" + b"\x80\x40\xc0" * w) * h)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


def _load_plus_pkg(pkg_name):
    """connect_plus/plus.py as a real module under a private package name."""
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [os.path.join(REPO, "connect_plus")]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg
    return importlib.import_module(pkg_name + ".plus")


def _load_dispatcher(pkg_name):
    """The REAL AnkiConnect dispatcher, headless (entry block cut)."""
    if pkg_name in sys.modules and "_r3rev_instance" in sys.modules[pkg_name].__dict__:
        pkg = sys.modules[pkg_name]
        return pkg, pkg.__dict__["_r3rev_instance"]
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [os.path.join(REPO, "connect_plus")]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg
    pkg = sys.modules[pkg_name]
    util_mod = importlib.import_module(pkg_name + ".util")
    util_mod.setting = lambda key: util_mod.DEFAULT_CONFIG[key]
    with io.open(INIT_PATH, encoding="utf-8") as handle:
        src = handle.read()
    marker = 'if __name__ != "plugin":'
    assert marker in src, "entry-block guard moved; this loader must be updated"
    pkg.__dict__["__file__"] = INIT_PATH
    exec(compile(src[:src.index(marker)], INIT_PATH, "exec"), pkg.__dict__)
    inst = pkg.__dict__["AnkiConnect"].__new__(pkg.__dict__["AnkiConnect"])
    inst.log = None
    pkg.__dict__["_r3rev_instance"] = inst
    return pkg, inst


# ============================================================================
# FINDING 1 + 5 — the sync guard could deadlock permanently.
#
# _plusSyncDone ran three statements that can raise BEFORE any job['state']
# assignment, with no try/finally. A raise inside a taskman on_done callback
# is swallowed, so the job stayed at 'syncing' forever and all 23 guarded
# actions kept returning a [sync_in_progress] documented as RETRYABLE that
# could never become satisfiable — until Anki was restarted.
#
# The pre-fix test only set and cleared _plusSyncJobState['state'] by hand and
# never drove the state machine at all, which is why this survived.
# ============================================================================
class _FakeModels:
    def _clear_cache(self):
        pass


class _FakeCol:
    def __init__(self, raise_on_scheduler=False):
        self.models = _FakeModels()
        self.raise_on_scheduler = raise_on_scheduler
        self.scheduler_loads = 0

    def _load_scheduler(self):
        self.scheduler_loads += 1
        if self.raise_on_scheduler:
            raise RuntimeError("profile closed: _load_scheduler failed")


class _FakePM:
    def __init__(self, raise_on_host=False, raise_on_clear=False):
        self.raise_on_host = raise_on_host
        self.raise_on_clear = raise_on_clear
        self.cleared = 0
        self.host_number = None

    def set_host_number(self, value):
        if self.raise_on_host:
            raise RuntimeError("profile closed: set_host_number failed")
        self.host_number = value

    def set_current_sync_url(self, value):
        pass

    def clear_sync_auth(self):
        self.cleared += 1
        if self.raise_on_clear:
            raise RuntimeError("profile closed: clear_sync_auth failed")


class _FakeToolbar:
    def redraw(self):
        pass


class _FakeFlags:
    def require_refresh(self):
        pass


class _FakeMw:
    def __init__(self, col_obj=None, pm=None):
        self.col = col_obj
        self.pm = pm or _FakePM()
        self.toolbar = _FakeToolbar()
        self.flags = _FakeFlags()

    def reset(self):
        pass


class _FakeFuture:
    """future.result() either returns a SyncOutput-alike or raises."""
    def __init__(self, out=None, exc=None):
        self._out = out
        self._exc = exc

    def result(self):
        if self._exc is not None:
            raise self._exc
        return self._out


class _FakeSyncOut:
    NO_CHANGES = 0

    def __init__(self, required=0, host_number=3, new_endpoint=""):
        self.required = required
        self.host_number = host_number
        self.new_endpoint = new_endpoint
        self.server_message = "hello"


def _auth_error():
    """An anki SyncError that classify_sync_error maps to 'auth_failed'."""
    import anki.errors
    return anki.errors.SyncError("denied", None, None, None,
                                 anki.errors.SyncErrorKind.AUTH)


def _syncing_job(started=None):
    return {"state": "syncing",
            "startedMs": int(time.time() * 1000) if started is None else started,
            "result": None, "error": None}


def test_finding1_sync_done_always_leaves_syncing():
    plus = _load_plus_pkg(PLUS_PKG)
    pkg_core = sys.modules[PLUS_PKG + ".core"]

    def make(mw):
        class FakeAC(plus.PlusMixin):
            def window(self):
                if mw is None:
                    raise RuntimeError("no main window")
                return mw

            def collection(self):
                return col
        inst = FakeAC()
        inst._plusSyncJobState = _syncing_job()
        return inst

    good_out = _FakeSyncOut()

    # every way _plusSyncDone can blow up before it used to assign a state
    cases = [
        ("col._load_scheduler raises",
         _FakeMw(_FakeCol(raise_on_scheduler=True)), _FakeFuture(out=good_out)),
        ("pm.set_host_number raises",
         _FakeMw(_FakeCol(), _FakePM(raise_on_host=True)), _FakeFuture(out=good_out)),
        ("self.window() raises",
         None, _FakeFuture(out=good_out)),
        ("pm.clear_sync_auth raises on the auth_failed path",
         _FakeMw(_FakeCol(), _FakePM(raise_on_clear=True)),
         _FakeFuture(exc=_auth_error())),
        ("future.result raises something unclassified",
         _FakeMw(_FakeCol()), _FakeFuture(exc=RuntimeError("kaboom"))),
        ("mw.col is None (profile closed mid-sync)",
         _FakeMw(None), _FakeFuture(out=good_out)),
    ]

    for label, mw, future in cases:
        inst = make(mw)
        # the callback must not propagate: taskman would swallow it anyway,
        # and the job would be stranded
        inst._plusSyncDone(future, syncMedia=False)
        job = inst._plusSyncJobState
        assert job["state"] != "syncing", (label, job)
        assert job["state"] in ("done", "error", "media_syncing"), (label, job)
        if job["state"] == "error":
            assert set(job["error"]) == {"code", "message"}, (label, job)
            assert job["error"]["code"], (label, job)

        # ...and the guard really lets a guarded action through afterwards,
        # which is the whole point of the liveness contract
        try:
            inst.undoStatus()
        except pkg_core.PlusError as err:
            raise AssertionError(
                "%s: guard still refusing after _plusSyncDone: %s" % (label, err))

    # sanity: the happy path is untouched by the new wrapper
    inst = make(_FakeMw(_FakeCol()))
    inst._plusSyncDone(_FakeFuture(out=good_out), syncMedia=False)
    job = inst._plusSyncJobState
    assert job["state"] == "done", job
    assert job["result"] == {"serverMessage": "hello", "hostNumber": 3}, job
    assert job["error"] is None, job
    assert inst.window().pm.host_number == 3, "pm bookkeeping was skipped"
    assert inst.window().col.scheduler_loads == 1, "scheduler reload was skipped"

    # a required full sync is still refused, and still terminal
    inst = make(_FakeMw(_FakeCol()))
    inst._plusSyncDone(_FakeFuture(out=_FakeSyncOut(required=2)), syncMedia=False)
    job = inst._plusSyncJobState
    assert job["state"] == "error", job
    assert job["error"]["code"] == "full_sync_required", job

    # the auth_failed path still classifies and still clears stored auth
    mw = _FakeMw(_FakeCol())
    inst = make(mw)
    inst._plusSyncDone(_FakeFuture(exc=_auth_error()), syncMedia=False)
    assert inst._plusSyncJobState["error"]["code"] == "auth_failed", \
        inst._plusSyncJobState
    assert mw.pm.cleared == 1, "stale sync auth was not cleared"


def test_finding1_stale_job_is_reaped_not_refused_forever():
    """The backstop for a completion callback that never arrives at all."""
    plus = _load_plus_pkg(PLUS_PKG)
    pkg_core = sys.modules[PLUS_PKG + ".core"]
    assert pkg_core.SYNC_JOB_STALE_MS > 0

    class FakeAC(plus.PlusMixin):
        def collection(self):
            return col

        def window(self):
            return _FakeMw(_FakeCol())

    # (a) a FRESH 'syncing' job still refuses — the guard is not weakened
    inst = FakeAC()
    inst._plusSyncJobState = _syncing_job()
    try:
        inst.undoStatus()
        raise AssertionError("a fresh syncing job must still refuse")
    except pkg_core.PlusError as err:
        assert err.code == "sync_in_progress", err

    # (b) one past the ceiling is REAPED into a terminal state, not merely
    # ignored — so the guard, syncNow and syncStatus all agree afterwards
    stale = int(time.time() * 1000) - pkg_core.SYNC_JOB_STALE_MS - 1000
    inst._plusSyncJobState = _syncing_job(started=stale)
    inst.undoStatus()   # must not raise
    job = inst._plusSyncJobState
    assert job["state"] == "error", job
    # the SPEC 18 job-error vocabulary is unchanged: no new code was invented
    assert job["error"]["code"] == "error", job
    assert "3600 seconds" in job["error"]["message"], job

    # (c) a 'syncing' job with no startedMs at all is unaccountable state and
    # reaps immediately rather than blocking forever
    inst._plusSyncJobState = {"state": "syncing", "startedMs": None,
                              "result": None, "error": None}
    inst.undoStatus()
    assert inst._plusSyncJobState["state"] == "error", inst._plusSyncJobState

    # (d) the documented recovery loop terminates: syncStatus reports the
    # reaped state rather than parroting 'syncing' forever
    reaped = {"state": "syncing", "startedMs": stale, "result": None, "error": None}
    assert plus._reap_stale_sync_job(reaped) is True
    assert reaped["state"] == "error", reaped
    for state in ("idle", "done", "error", "media_syncing"):
        untouched = {"state": state, "startedMs": stale, "result": None, "error": None}
        assert plus._reap_stale_sync_job(untouched) is False, state
        assert untouched["state"] == state, state


# ============================================================================
# FINDING 2 — undoStatus.lastStep silently reset to 0.
#
# col.undo_status() is `self._check_backend_undo_status() or UndoStatus()`,
# and _check_backend_undo_status returns None whenever BOTH undo and redo are
# empty — so the wrapper synthesizes a default proto with last_step = 0. The
# contract (core.py, SPEC 26) promises a monotonic counter.
# ============================================================================
def test_finding2_last_step_is_the_backend_counter():
    c = col_undo
    nid = add_note(c, "R4", "Basic", {"Front": "undo-1", "Back": "b"})
    assert nid

    before = core.undo_status(c)
    assert before["lastStep"] > 0, before
    assert before["undo"] == "Add Note", before

    # fix_integrity (Check Database) clears the stack but NOT the counter
    c.fix_integrity()
    after = core.undo_status(c)
    assert after["undo"] is None and after["redo"] is None, after
    assert after["lastStep"] >= before["lastStep"], \
        "lastStep went BACKWARDS across a stack clear: %r -> %r" % (before, after)
    # this is the exact regression: the wrapper reported 0 here
    backend = c._backend.get_undo_status()
    assert after["lastStep"] == backend.last_step, (after, backend.last_step)
    assert after["lastStep"] != 0, \
        "lastStep reset to 0 — undo_status is reading the wrapper again"

    # add_config does the same (upstream cloneDeckConfigId calls it)
    c.decks.add_config("r4conf")
    cleared = core.undo_status(c)
    assert cleared["lastStep"] >= after["lastStep"], (after, cleared)

    # still read-only: two calls in a row are identical and change nothing
    twice = core.undo_status(c)
    assert twice == cleared, (cleared, twice)

    # and the normal path is unchanged
    add_note(c, "R4", "Basic", {"Front": "undo-2", "Back": "b"})
    grown = core.undo_status(c)
    assert grown["undo"] == "Add Note", grown
    assert grown["lastStep"] > cleared["lastStep"], (cleared, grown)


# ============================================================================
# FINDING 3 — the __tags__ dry-run preview promised the RAW request, but the
# write has the backend canonify tags (split / strip / case-insensitive dedup
# / case-insensitive sort / registry spelling). The same raw-vs-canonified
# mismatch in the no-op check meant an identical repeat of any non-canonical
# request always re-wrote the note for zero net change.
# ============================================================================
def test_finding3_tag_preview_matches_what_is_stored():
    # Each case gets a FRESH collection: anki's canonify consults the tag
    # registry, so a case would otherwise inherit the tag spellings the
    # previous case registered (that dependence is itself asserted below).
    cases = [
        (["beta", "alpha"], ["alpha", "beta"]),          # sorted
        (["alpha", "alpha"], ["alpha"]),                 # de-duplicated
        (["  alpha  "], ["alpha"]),                      # stripped
        (["alpha", "BETA", "beta"], ["alpha", "BETA"]),  # ci dedup, 1st wins
        (["gamma delta"], ["delta", "gamma"]),           # 1 request -> 2 tags
        (["Zed", "apple"], ["apple", "Zed"]),            # sort is ci
        ([""], []),                                      # nothing at all
        (["a::B", "A::b"], ["a::B"]),                    # hierarchy is just text
    ]
    for i, (requested, expected) in enumerate(cases):
        case_col = Collection(os.path.join(SCRATCH, "canon%d.anki2" % i))
        try:
            nid = add_note(case_col, "R4Tags", "Basic",
                           {"Front": "canon-%d" % i, "Back": "b"})
            predicted = core.canonify_tags(
                requested, core.tag_registry_map(case_col))
            assert predicted == expected, (requested, predicted, expected)

            out = core.bulk_update_note_fields(
                case_col, [{"id": nid, "tags": requested}],
                dry_run=True, diff=True)
            rows = [r for r in out["preview"]
                    if r["field"] == core.TAGS_PREVIEW_FIELD]

            core.bulk_update_note_fields(case_col, [{"id": nid, "tags": requested}])
            stored = case_col.get_note(nid).tags

            # THE contract: the preview's 'after' is what the write really stored
            assert predicted == stored, \
                "predictor drifted from the backend: %r -> %r, stored %r" % (
                    requested, predicted, stored)
            if rows:
                assert rows[0]["after"] == " ".join(stored), \
                    (requested, rows[0], stored)
            else:
                assert stored == [], (requested, out, stored)
        finally:
            case_col.close()

    # the registry rule: an existing tag's REGISTERED spelling wins over the
    # requested case, so the preview must show the registered spelling
    reg_nid = add_note(col, "R4Tags", "Basic",
                       {"Front": "canon-reg", "Back": "b"}, tags=["Registered"])
    assert "Registered" in col.tags.all()
    other = add_note(col, "R4Tags", "Basic", {"Front": "canon-reg2", "Back": "b"})
    out = core.bulk_update_note_fields(
        col, [{"id": other, "tags": ["REGISTERED"]}], dry_run=True, diff=True)
    row = [r for r in out["preview"] if r["field"] == core.TAGS_PREVIEW_FIELD][0]
    assert row["after"] == "Registered", row
    core.bulk_update_note_fields(col, [{"id": other, "tags": ["REGISTERED"]}])
    assert col.get_note(other).tags == ["Registered"], col.get_note(other).tags
    assert reg_nid

    # the no-op half: an identical repeat of a NON-canonical request must be
    # 'unchanged' and must not write (measured before the fix: 'updated' every
    # time, with a mod/usn bump and an undo entry for no net data change)
    for requested in (["gamma delta"], ["beta", "alpha"], ["alpha", "alpha"],
                      ["  alpha  "], ["Zed", "apple"]):
        nid = add_note(col, "R4Tags", "Basic",
                       {"Front": "repeat-%s" % "-".join(requested), "Back": "b"})
        first = core.bulk_update_note_fields(col, [{"id": nid, "tags": requested}])
        assert first["updated"] == [nid], (requested, first)
        mod_before = col.db.scalar("select mod from notes where id = ?", nid)
        usn_before = col.db.scalar("select usn from notes where id = ?", nid)
        step_before = core.undo_status(col)["lastStep"]

        second = core.bulk_update_note_fields(col, [{"id": nid, "tags": requested}])
        assert second["updated"] == [] and second["unchanged"] == [nid], \
            (requested, second)
        assert second["undoEntry"] is None, (requested, second)
        assert col.db.scalar("select mod from notes where id = ?", nid) == mod_before
        assert col.db.scalar("select usn from notes where id = ?", nid) == usn_before
        assert core.undo_status(col)["lastStep"] == step_before, \
            "%r: the no-op repeat still created an undo entry" % (requested,)

        # dry run agrees with the real run, as SPEC 15 requires
        dry = core.bulk_update_note_fields(
            col, [{"id": nid, "tags": requested}], dry_run=True, diff=True)
        assert dry["wouldUpdate"] == [] and dry["unchanged"] == [nid], (requested, dry)
        assert dry["preview"] == [], (requested, dry)

    # a genuine change is still reported, previewed and written
    nid = add_note(col, "R4Tags", "Basic", {"Front": "real-change", "Back": "b"},
                   tags=["keep"])
    dry = core.bulk_update_note_fields(
        col, [{"id": nid, "tags": ["keep", "Added"]}], dry_run=True, diff=True)
    row = [r for r in dry["preview"] if r["field"] == core.TAGS_PREVIEW_FIELD][0]
    assert row == {"noteId": nid, "field": "__tags__",
                   "before": "keep", "after": "Added keep"}, row
    core.bulk_update_note_fields(col, [{"id": nid, "tags": ["keep", "Added"]}])
    assert col.get_note(nid).tags == ["Added", "keep"], col.get_note(nid).tags


# ============================================================================
# FINDING 9 — plusInfo's 'returns' sketch for bulkReplaceInFields documented
# skipped: [{index, reason}], but the action emits noteId. The pre-fix test
# only checked the sketch was non-empty and started with '{', which is exactly
# why the drift survived. This one runs each action and compares the KEYS.
# ============================================================================
_SKIPPED_RE = re.compile(r"skipped: \[\{([^}]*)\}\]")


def _documented_skipped_keys(sketch):
    found = _SKIPPED_RE.findall(sketch)
    assert found, "no skipped[] shape documented in: %r" % sketch[:120]
    return [frozenset(part.strip() for part in group.split(",") if part.strip())
            for group in found]


def test_finding9_skipped_shapes_match_the_documented_sketch():
    dead = 1  # an id no note will ever have
    live = add_note(col, "R4Skip", "Basic", {"Front": "skip-live", "Back": "b"})

    drivers = {
        "bulkAddNotes": lambda: core.bulk_add_notes(
            col, [{"deckName": "R4Skip", "modelName": "NoSuchModel",
                   "fields": {"Front": "x"}}], atomic=False),
        "bulkUpdateNoteFields": lambda: core.bulk_update_note_fields(
            col, [{"id": dead, "fields": {"Front": "x"}}], atomic=False),
        "bulkAddTags": lambda: core.bulk_add_tags(
            col, [dead], ["t"], atomic=False),
        "bulkReplaceInFields": lambda: core.bulk_replace_in_fields(
            col, note_ids=[dead], field="Front", find="a", replace="b",
            atomic=False),
    }

    for action, drive in drivers.items():
        sketch = core.PLUS_ACTION_RETURNS[action]
        documented = _documented_skipped_keys(sketch)
        # every skipped[] sketch inside one action's 'returns' (real run AND
        # dryRun) must describe the same shape
        assert len(set(documented)) == 1, (action, documented)
        expected = documented[0]

        result = drive()
        assert result["skipped"], (action, result)
        for entry in result["skipped"]:
            assert frozenset(entry) == expected, \
                "%s emits skipped keys %r, plusInfo documents %r" % (
                    action, sorted(entry), sorted(expected))

        # ...and the dry run agrees, since SPEC 15 shares the validation path
        dry = None
        if action == "bulkAddNotes":
            dry = core.bulk_add_notes(
                col, [{"deckName": "R4Skip", "modelName": "NoSuchModel",
                       "fields": {"Front": "x"}}], atomic=False, dry_run=True)
        elif action == "bulkUpdateNoteFields":
            dry = core.bulk_update_note_fields(
                col, [{"id": dead, "fields": {"Front": "x"}}],
                atomic=False, dry_run=True)
        elif action == "bulkAddTags":
            dry = core.bulk_add_tags(col, [dead], ["t"], atomic=False, dry_run=True)
        elif action == "bulkReplaceInFields":
            dry = core.bulk_replace_in_fields(
                col, note_ids=[dead], field="Front", find="a", replace="b",
                atomic=False, dry_run=True)
        for entry in dry["skipped"]:
            assert frozenset(entry) == expected, (action, "dryRun", sorted(entry))

    # the specific drift: bulkReplaceInFields is keyed noteId, NOT index, and
    # the sketch now says so out loud
    assert _documented_skipped_keys(
        core.PLUS_ACTION_RETURNS["bulkReplaceInFields"])[0] == frozenset(
            {"noteId", "reason"})
    assert "NOT index" in core.PLUS_ACTION_RETURNS["bulkReplaceInFields"]
    assert live


# ============================================================================
# FINDING 10 — the getImageOcclusionNote sketch presented 'properties' as the
# rect/non-rect discriminator, but every rect this add-on creates by default
# also carries properties {"oi": "1"}.
# ============================================================================
def test_finding10_rect_occlusions_carry_properties():
    col.decks.id("R4IO")
    b64 = base64.b64encode(make_png()).decode("ascii")
    added = core.add_image_occlusion_note(
        col, image_data_b64=b64, image_filename="ancp_r3rev_io.png",
        occlusions=[{"left": 0.1, "top": 0.1, "width": 0.2, "height": 0.2,
                     "ordinal": 1}],
        header="H", back_extra="B", deck_name="R4IO")
    got = core.get_image_occlusion_note(col, added["noteId"])
    rect = got["occlusions"][0]
    assert rect["shape"] == "rect", rect
    assert "left" in rect, rect
    # the measured fact the sketch used to deny
    assert rect.get("properties") == {"oi": "1"}, rect

    sketch = core.PLUS_ACTION_RETURNS["getImageOcclusionNote"]
    assert "properties?" in sketch, sketch
    assert "oi" in sketch, sketch
    assert "'left'" in sketch, sketch   # the real discriminator is named
    spec_text = io.open(SPEC_PATH, encoding="utf-8").read()
    assert '"oi": "1"' in spec_text, "SPEC 4.5 still omits the oi property"


# ============================================================================
# FINDING 11 — the 'reading errors' recipe claimed every multi sub-response is
# a full four-key envelope. True for FAILING sub-actions only: a succeeding
# one is {result, error} at version >= 5, and the BARE result at version <= 4
# (which is what a sub-action that omits "version" gets).
# ============================================================================
def test_finding11_multi_success_sub_responses():
    pkg, inst = _load_dispatcher("ancp_r3rev_disp")

    reply = inst.handler({"action": "multi", "version": 6, "params": {"actions": [
        {"action": "noSuchAction", "version": 6},   # fails: four keys
        {"action": "version", "version": 6},        # succeeds at v6: two keys
        {"action": "version"},                      # succeeds, no version: bare
    ]}})
    assert reply["error"] is None, reply
    subs = reply["result"]
    assert len(subs) == 3, subs

    assert set(subs[0]) == {"result", "error", "errorCode", "retryable"}, subs[0]
    assert subs[0]["errorCode"] == "unknown_action", subs[0]

    assert set(subs[1]) == {"result", "error"}, subs[1]
    assert subs[1]["error"] is None, subs[1]
    assert "errorCode" not in subs[1], \
        "a SUCCEEDING sub-response must not be assumed to carry errorCode"

    assert not isinstance(subs[2], dict), \
        "a sub-action omitting 'version' gets the bare result (handler defaults to 4)"

    # the runtime-served recipe must now say all of that
    recipe = [r for r in core.PLUS_RECIPES if r["name"] == "reading errors"][0]
    text = recipe["description"]
    assert "INDEPENDENTLY" in text, text
    assert "error: null}" in text or "error: " in text, text
    assert "bare result" in text, text
    assert "defaults version to 4" in text, text
    assert pkg


# ============================================================================
# FINDING 4 + 13 — PLUS_ERROR_PREFIX_NOTE blamed every null errorCode on the
# ~90 upstream ACTIONS, but the dispatcher's api-key refusal and schema
# validation failures are also uncoded. That refusal is the first error a
# misconfigured client hits.
# ============================================================================
def test_finding4_prefix_note_names_every_uncoded_path():
    note = core.PLUS_ERROR_PREFIX_NOTE
    assert "valid api key must be provided" in note, note
    assert "schema" in note.lower(), note
    assert "does NOT prove" in note or "does not prove" in note, note

    # and it is the truth: the refusal really is uncoded on the wire
    pkg, inst = _load_dispatcher("ancp_r3rev_disp")
    reply = inst.handler({"action": "deckNames", "version": 6, "key": "wrong"})
    assert reply["error"] == "valid api key must be provided", reply
    assert reply["errorCode"] is None and reply["retryable"] is None, reply
    assert pkg

    # plusInfo serves the note verbatim
    plus = _load_plus_pkg(PLUS_PKG)
    util_mod = sys.modules[PLUS_PKG + ".util"]
    original = util_mod.setting
    util_mod.setting = lambda key: util_mod.DEFAULT_CONFIG[key]
    try:
        info = plus.PlusMixin().plusInfo()
    finally:
        util_mod.setting = original
    assert info["errorPrefixNote"] == core.PLUS_ERROR_PREFIX_NOTE


# ============================================================================
# FINDING 6 + 12 — documentation claims that were measurably false.
# ============================================================================
def test_finding6_and_12_doc_claims():
    spec_text = io.open(SPEC_PATH, encoding="utf-8").read()
    readme_text = io.open(README_PATH, encoding="utf-8").read()

    # (6) revision 13 is NOT "entirely additive": it changed two error strings
    assert "entirely additive — no breaking contract changes" not in spec_text, \
        "SPEC still claims revision 13 is entirely additive"
    assert "Every pre-existing key, default and error string is byte-unchanged" \
        not in spec_text, "SPEC still claims every error string is byte-unchanged"
    for needle in ("[unknown_action] unsupported action",
                   "[invalid_param] renderCard() missing required argument"):
        assert needle in spec_text, "SPEC does not name the changed string: %s" % needle
        assert needle in readme_text, "README does not name the changed string: %s" % needle
    assert "exactly two, both deliberate" not in readme_text, \
        "README's round-3 heading still claims exactly two breaking changes"
    assert "FOUR, all deliberate" in readme_text, \
        "README's round-3 list was not corrected"

    # (12) rationale_invalid needs no AnkiHub add-on: it is validated BEFORE
    # the add-on import in both wrappers. Assert that on the SOURCE, so the
    # doc row and the code cannot drift apart again.
    plus_src = io.open(os.path.join(REPO, "connect_plus", "plus.py"),
                       encoding="utf-8").read()
    for wrapper in ("def ankihubSuggestNoteUpdate", "def ankihubSuggestNewNote"):
        start = plus_src.index(wrapper)
        body = plus_src[start:start + 2000]
        validate_at = body.index("validate_ankihub_rationale")
        modules_at = body.index("_plusAnkiHubModules")
        assert validate_at < modules_at, \
            "%s now imports the AnkiHub add-on before validating the rationale" % wrapper
    assert "| `rationale_invalid` | no | yes |" in spec_text, \
        "SPEC still marks rationale_invalid as AnkiHub-only (yes*)"
    assert "| `source_required` | no | yes* |" in spec_text, \
        "source_required is genuinely AnkiHub-only and must keep its star"


# ============================================================================
# FINDING 7 — notesSlim's per-page full-list scan is O(N^2/L). Not changed
# (the window-independence is the point); the COST is now disclosed.
# ============================================================================
def test_finding7_paging_cost_is_disclosed():
    spec_text = io.open(SPEC_PATH, encoding="utf-8").read()
    readme_text = io.open(README_PATH, encoding="utf-8").read()
    for text, where in ((spec_text, "SPEC"), (readme_text, "README"),
                        (core.PLUS_ACTION_RETURNS["notesSlim"], "plusInfo")):
        assert "O(N" in text and "/L)" in text, where
        assert "first page" in text.lower(), where

    # the invariant the cost buys is still true on every page
    ids = [add_note(col, "R4Page", "Basic", {"Front": "p%d" % i, "Back": "b"})
           for i in range(5)]
    requested = ids + [1, 2]
    seen = []
    offset = 0
    while offset is not None:
        page = core.notes_slim(col, note_ids=requested, offset=offset, limit=2)
        assert page["total"] == 5, page
        assert page["missing"] == [1, 2], page
        assert len(requested) == page["total"] + len(page["missing"])
        seen.extend(n["noteId"] for n in page["notes"])
        offset = page["nextOffset"]
    assert seen == ids, (seen, ids)


# ============================================================================
if __name__ == "__main__":
    import anki.errors  # noqa: F401  (used by the sync cases above)

    run("finding1_sync_done_always_leaves_syncing",
        test_finding1_sync_done_always_leaves_syncing)
    run("finding1_stale_job_is_reaped_not_refused_forever",
        test_finding1_stale_job_is_reaped_not_refused_forever)
    run("finding2_last_step_is_the_backend_counter",
        test_finding2_last_step_is_the_backend_counter)
    run("finding3_tag_preview_matches_what_is_stored",
        test_finding3_tag_preview_matches_what_is_stored)
    run("finding4_prefix_note_names_every_uncoded_path",
        test_finding4_prefix_note_names_every_uncoded_path)
    run("finding6_and_12_doc_claims", test_finding6_and_12_doc_claims)
    run("finding7_paging_cost_is_disclosed", test_finding7_paging_cost_is_disclosed)
    run("finding9_skipped_shapes_match_the_documented_sketch",
        test_finding9_skipped_shapes_match_the_documented_sketch)
    run("finding10_rect_occlusions_carry_properties",
        test_finding10_rect_occlusions_carry_properties)
    run("finding11_multi_success_sub_responses",
        test_finding11_multi_success_sub_responses)

    print("\n=== headless_round3review_test summary ===")
    failures = 0
    for name, ok, tb in RESULTS:
        print("%s  %s" % ("PASS" if ok else "FAIL", name))
        if not ok:
            failures += 1
    if NETWORK_ATTEMPTS:
        failures += 1
        print("FAIL  zero-network guarantee: %r" % (NETWORK_ATTEMPTS,))
    else:
        print("PASS  zero-network guarantee (no connection attempted)")
    print("%d/%d passed" % (len(RESULTS) - failures + (0 if NETWORK_ATTEMPTS else 0),
                            len(RESULTS)))
    for c in (col, col_undo):
        c.close()
    sys.exit(1 if failures else 0)
