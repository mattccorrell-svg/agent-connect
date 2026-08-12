# Headless verification for the SPEC 18 sync helpers (syncStatus / syncNow).
#
# Run with: "/Users/mattyc/Library/Application Support/AnkiProgramFiles/.venv/bin/python" headless_sync_test.py
#
# ZERO NETWORK by construction: only the pure core.py helpers are exercised
# (enum maps, bounded auth copy, local dirtiness select, error classification).
# The network paths (col.sync_status / col.sync_collection round-trips) are
# never called here — they are verified manually against a live logged-in
# Anki, per SPEC 18.2. The plus.py job state machine needs a running aqt and
# is likewise out of scope for this suite.
#
# Uses a FRESH scratch collection; never touches ~/Library/Application Support/Anki2/.

import importlib.util
import os
import shutil
import sys
import tempfile
import traceback

SCRATCH = (os.environ.get("ANCP_TEST_SCRATCH")
           or tempfile.mkdtemp(prefix="ancp_sync_r1_"))
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
assert not any(m.startswith("PyQt6") for m in sys.modules), "core.py import pulled in PyQt6"

import anki.lang
anki.lang.set_lang("en_US")
import anki.sync
from anki.collection import Collection
from anki.errors import Interrupted, NetworkError, SyncError, SyncErrorKind
from anki.sync_pb2 import SyncCollectionResponse, SyncStatusResponse

col = Collection(os.path.join(SCRATCH, "sync.anki2"))

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


# ---------------------------------------------------------------- test 1
def test1_actions_registered():
    assert "syncStatus" in core.PLUS_ACTIONS, core.PLUS_ACTIONS
    assert "syncNow" in core.PLUS_ACTIONS, core.PLUS_ACTIONS
    # plusInfo stays last, per file convention
    assert core.PLUS_ACTIONS[-1] == "plusInfo"


# ---------------------------------------------------------------- test 2
def test2_enum_maps_match_proto():
    # SPEC 18: maps must cover and agree with the installed sync_pb2 values
    S = SyncStatusResponse
    assert core.SYNC_STATUS_REQUIRED[S.NO_CHANGES] == "no_changes"
    assert core.SYNC_STATUS_REQUIRED[S.NORMAL_SYNC] == "normal_sync"
    assert core.SYNC_STATUS_REQUIRED[S.FULL_SYNC] == "full_sync_required"
    assert set(core.SYNC_STATUS_REQUIRED) == {0, 1, 2}
    C = SyncCollectionResponse
    assert core.SYNC_COLLECTION_REQUIRED[C.NO_CHANGES] == "no_changes"
    assert core.SYNC_COLLECTION_REQUIRED[C.NORMAL_SYNC] == "normal_sync"
    assert core.SYNC_COLLECTION_REQUIRED[C.FULL_SYNC] == "full_sync"
    assert core.SYNC_COLLECTION_REQUIRED[C.FULL_DOWNLOAD] == "full_download"
    assert core.SYNC_COLLECTION_REQUIRED[C.FULL_UPLOAD] == "full_upload"
    assert set(core.SYNC_COLLECTION_REQUIRED) == {0, 1, 2, 3, 4}


# ---------------------------------------------------------------- test 3
def test3_bounded_sync_auth():
    auth = anki.sync.SyncAuth(hkey="k123", endpoint="https://sync.example/",
                              io_timeout_secs=60)
    b = core.bounded_sync_auth(auth, 8)
    assert b.hkey == "k123"
    assert b.endpoint == "https://sync.example/"
    assert b.io_timeout_secs == 8
    # unset endpoint reads as '' from the proto and must map back to unset
    auth2 = anki.sync.SyncAuth(hkey="k456", io_timeout_secs=60)
    assert auth2.endpoint == ""
    b2 = core.bounded_sync_auth(auth2, 5)
    assert not b2.HasField("endpoint")
    assert b2.hkey == "k456" and b2.io_timeout_secs == 5
    # bad timeouts raise house-style
    for bad in (0, -1, True, "8", 2.5):
        try:
            core.bounded_sync_auth(auth, bad)
        except Exception as e:
            assert "invalid parameter: timeoutSecs" in str(e), str(e)
        else:
            raise AssertionError("timeout %r accepted" % (bad,))


# ---------------------------------------------------------------- test 4
def test4_local_sync_dirty():
    d = core.local_sync_dirty(col)
    assert set(d) == {"lastSyncMs", "modMs", "dirty"}
    assert isinstance(d["lastSyncMs"], int) and isinstance(d["modMs"], int)
    assert isinstance(d["dirty"], bool)
    # a never-synced collection has ls == 0; any write makes mod > ls
    col.decks.id("SyncDirtyDeck")
    d2 = core.local_sync_dirty(col)
    assert d2["dirty"] is True, d2
    assert d2["modMs"] > d2["lastSyncMs"], d2
    # simulate "just synced": ls = mod via the backend-sanctioned db path is
    # NOT available headless without a real sync, so only the dirty branch is
    # asserted here; the clean branch is a live-Anki manual check (SPEC 18.2)


# ---------------------------------------------------------------- test 5
def test5_classify_sync_error():
    def sync_err(kind):
        return SyncError("boom", None, None, None, kind)

    assert core.classify_sync_error(sync_err(SyncErrorKind.AUTH)) == "auth_failed"
    assert core.classify_sync_error(sync_err(SyncErrorKind.OTHER)) == "error"
    assert core.classify_sync_error(NetworkError("net down", None, None, None)) == "offline"
    assert core.classify_sync_error(Interrupted("stop", None, None, None)) == "aborted"
    assert core.classify_sync_error(RuntimeError("misc")) == "error"
    # SyncError subclasses BackendError, NOT NetworkError: order-of-checks probe
    assert core.classify_sync_error(sync_err(SyncErrorKind.AUTH)) != "offline"


run("test1_actions_registered", test1_actions_registered)
run("test2_enum_maps_match_proto", test2_enum_maps_match_proto)
run("test3_bounded_sync_auth", test3_bounded_sync_auth)
run("test4_local_sync_dirty", test4_local_sync_dirty)
run("test5_classify_sync_error", test5_classify_sync_error)

col.close()

print("\n===== SUMMARY =====")
n_pass = sum(1 for _, ok, _ in RESULTS if ok)
for name, ok, _ in RESULTS:
    print("%s  %s" % ("PASS" if ok else "FAIL", name))
print("%d/%d passed" % (n_pass, len(RESULTS)))
sys.exit(0 if n_pass == len(RESULTS) else 1)
