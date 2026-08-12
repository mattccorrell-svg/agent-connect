# Headless verification for the SPEC 19 AnkiHub pure helpers.
#
# Run with: "/Users/mattyc/Library/Application Support/AnkiProgramFiles/.venv/bin/python" headless_ankihub_test.py
#
# ZERO NETWORK and ZERO ADD-ON IMPORTS by construction: only the pure core.py
# helpers are exercised (change-type/rationale validation, the dialog-exact
# Source comment builder, HTTP error mapping, result mapping, signature
# feature-detect helper). The AnkiHub add-on itself is NEVER imported here —
# importing it outside a running Anki would execute its entry point. The live
# paths (ankihubStatus against the real add-on, actual suggestion submission)
# are manual-only per SPEC 19. No collection is needed: every helper under
# test is collection-free.

import importlib.util
import os
import sys
import traceback

CORE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "connect_plus", "core.py")

# load core.py standalone (no package __init__, no aqt)
spec = importlib.util.spec_from_file_location("core", CORE_PATH)
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
assert "aqt" not in sys.modules, "core.py (or its imports) pulled in aqt"
assert not any(m.startswith("PyQt6") for m in sys.modules), "core.py import pulled in PyQt6"
assert core.ANKIHUB_ADDON_PACKAGE not in sys.modules, "core.py must never import the AnkiHub add-on"

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


def expect_raises(fn, fragment):
    try:
        fn()
    except Exception as e:
        assert fragment in str(e), "expected %r in %r" % (fragment, str(e))
        return str(e)
    raise AssertionError("expected an exception containing %r" % fragment)


# ---------------------------------------------------------------- test 1
def test1_actions_registered():
    for action in ("ankihubStatus", "ankihubSuggestNoteUpdate", "ankihubSuggestNewNote"):
        assert action in core.PLUS_ACTIONS, core.PLUS_ACTIONS
    # plusInfo stays last, per file convention
    assert core.PLUS_ACTIONS[-1] == "plusInfo"


# ---------------------------------------------------------------- test 2
def test2_constants():
    assert core.ANKIHUB_ADDON_PACKAGE == "1322529746"
    assert core.ANKIHUB_TESTED_ADDON_VERSION == "2026-08-10.1"
    assert core.ANKIHUB_RATIONALE_MAX_LENGTH == 1024
    # the nine SuggestionType wire values, exactly
    assert set(core.ANKIHUB_CHANGE_TYPES) == {
        "updated_content", "new_content", "spelling/grammar", "content_error",
        "new_card_to_add", "new_tags", "updated_tags", "delete", "other"}
    assert len(core.ANKIHUB_CHANGE_TYPES) == 9
    # dialog source-type matrix
    assert core.ANKIHUB_SOURCE_TYPES_BY_CHANGE_TYPE["new_content"] == \
        ("AMBOSS", "UWorld", "Society Guidelines", "Other")
    assert core.ANKIHUB_SOURCE_TYPES_BY_CHANGE_TYPE["updated_content"] == \
        ("AMBOSS", "UWorld", "Society Guidelines", "Other")
    assert core.ANKIHUB_SOURCE_TYPES_BY_CHANGE_TYPE["delete"] == ("Duplicate Note",)
    assert core.ANKIHUB_OPTIONAL_SOURCE_TYPES == ("Duplicate Note",)
    assert set(core.ANKIHUB_SOURCE_REQUIRED_CHANGE_TYPES) == {"new_content", "updated_content"}
    assert set(core.ANKIHUB_CHANGE_RESULTS) == {
        "SUCCESS", "NO_CHANGES", "ANKIHUB_NOT_FOUND", "EMPTY_FIRST_FIELD"}


# ---------------------------------------------------------------- test 3
def test3_validate_change_type():
    for wire in core.ANKIHUB_CHANGE_TYPES:
        assert core.validate_ankihub_change_type(wire) == wire
    for bad in ("Updated content", "UPDATED_CONTENT", "", None, 3, ["delete"]):
        expect_raises(lambda b=bad: core.validate_ankihub_change_type(b),
                      "invalid parameter: changeType")


# ---------------------------------------------------------------- test 4
def test4_validate_rationale():
    assert core.validate_ankihub_rationale("fix typo") == "fix typo"
    # the dialog widget trims while len >= RATIONALE_FOR_CHANGE_MAX_LENGTH,
    # so its effective cap (and the API's) is MAX - 1 = 1023
    exactly_max = "x" * (core.ANKIHUB_RATIONALE_MAX_LENGTH - 1)
    assert core.validate_ankihub_rationale(exactly_max) == exactly_max
    for bad in ("", "   \n", None, 5, ["r"]):
        expect_raises(lambda b=bad: core.validate_ankihub_rationale(b),
                      "RATIONALE_INVALID")
    expect_raises(
        lambda: core.validate_ankihub_rationale(
            "x" * core.ANKIHUB_RATIONALE_MAX_LENGTH),
        "RATIONALE_INVALID")
    expect_raises(lambda: core.validate_ankihub_rationale("x" * 1025),
                  "RATIONALE_INVALID")


# ---------------------------------------------------------------- test 5
def test5_comment_for_update_source_rules():
    # AnKing + updated_content + AMBOSS: exact dialog fold
    comment = core.ankihub_comment_for_update(
        "rat", "updated_content", {"type": "AMBOSS", "text": "https://amboss.com/x"}, True)
    assert comment == "rat\nSource: AMBOSS - https://amboss.com/x", repr(comment)
    # UWorld: 'Step N ' prefix from the step dropdown
    comment = core.ankihub_comment_for_update(
        "rat", "new_content", {"type": "UWorld", "text": "12345", "step": 2}, True)
    assert comment == "rat\nSource: UWorld - Step 2 12345", repr(comment)
    # AnKing + new/updated content WITHOUT source -> SOURCE_REQUIRED
    for ct in ("new_content", "updated_content"):
        expect_raises(lambda c=ct: core.ankihub_comment_for_update("rat", c, None, True),
                      "SOURCE_REQUIRED")
    # required source with blank text -> SOURCE_REQUIRED
    expect_raises(lambda: core.ankihub_comment_for_update(
        "rat", "new_content", {"type": "AMBOSS", "text": "  "}, True), "SOURCE_REQUIRED")
    # non-AnKing deck: no source needed, and a passed source is REJECTED
    assert core.ankihub_comment_for_update("rat", "updated_content", None, False) == "rat"
    expect_raises(lambda: core.ankihub_comment_for_update(
        "rat", "updated_content", {"type": "AMBOSS", "text": "x"}, False),
        "invalid parameter: source")
    # change types with no source widget reject a source even on AnKing
    expect_raises(lambda: core.ankihub_comment_for_update(
        "rat", "spelling/grammar", {"type": "AMBOSS", "text": "x"}, True),
        "invalid parameter: source")
    assert core.ankihub_comment_for_update("rat", "content_error", None, True) == "rat"
    # delete: optional 'Duplicate Note' source on ANY deck; blank folds nothing
    assert core.ankihub_comment_for_update("rat", "delete", None, False) == "rat"
    assert core.ankihub_comment_for_update(
        "rat", "delete", {"type": "Duplicate Note", "text": ""}, False) == "rat"
    comment = core.ankihub_comment_for_update(
        "rat", "delete", {"type": "Duplicate Note", "text": "1601234567890"}, True)
    assert comment == "rat\nSource: Duplicate Note - 1601234567890", repr(comment)
    # delete only offers Duplicate Note
    expect_raises(lambda: core.ankihub_comment_for_update(
        "rat", "delete", {"type": "AMBOSS", "text": "x"}, True),
        "invalid parameter: source.type")


# ---------------------------------------------------------------- test 6
def test6_source_shape_validation():
    good = {"type": "AMBOSS", "text": "x"}
    # step only valid for UWorld; required for UWorld; 1-3 only; no bools
    expect_raises(lambda: core.ankihub_comment_for_update(
        "rat", "new_content", {"type": "AMBOSS", "text": "x", "step": 1}, True),
        "invalid parameter: source.step")
    expect_raises(lambda: core.ankihub_comment_for_update(
        "rat", "new_content", {"type": "UWorld", "text": "123"}, True),
        "invalid parameter: source.step")
    for bad_step in (0, 4, True, "2", 2.0):
        expect_raises(lambda s=bad_step: core.ankihub_comment_for_update(
            "rat", "new_content", {"type": "UWorld", "text": "123", "step": s}, True),
            "invalid parameter: source.step")
    # unknown keys, bad shapes
    expect_raises(lambda: core.ankihub_comment_for_update(
        "rat", "new_content", dict(good, extra=1), True),
        "invalid parameter: source: unknown key(s)")
    expect_raises(lambda: core.ankihub_comment_for_update(
        "rat", "new_content", "AMBOSS", True), "invalid parameter: source")
    expect_raises(lambda: core.ankihub_comment_for_update(
        "rat", "new_content", {"type": "UpToDate", "text": "x"}, True),
        "invalid parameter: source.type")
    expect_raises(lambda: core.ankihub_comment_for_update(
        "rat", "new_content", {"type": "AMBOSS", "text": 5}, True),
        "invalid parameter: source.text")


# ---------------------------------------------------------------- test 7
def test7_comment_for_new_note():
    assert core.ankihub_comment_for_new_note("add this card", None) == "add this card"
    comment = core.ankihub_comment_for_new_note(
        "add", {"type": "UWorld", "text": "999", "step": 3})
    assert comment == "add\nSource: UWorld - Step 3 999", repr(comment)
    # blank source text folds nothing
    assert core.ankihub_comment_for_new_note(
        "add", {"type": "Other", "text": "  "}) == "add"
    # Duplicate Note cannot describe a brand-new note
    expect_raises(lambda: core.ankihub_comment_for_new_note(
        "add", {"type": "Duplicate Note", "text": "x"}),
        "invalid parameter: source.type")
    expect_raises(lambda: core.ankihub_comment_for_new_note("", None),
                  "RATIONALE_INVALID")


# ---------------------------------------------------------------- test 8
def test8_map_http_error():
    # 400: body passthrough as compact json
    code, msg = core.map_ankihub_http_error(400, {"non_field_errors": ["bad field"]})
    assert code == "VALIDATION_ERROR" and '"bad field"' in msg
    # 400 'no changes': sync-with-AnkiHub-first advice appended
    code, msg = core.map_ankihub_http_error(
        400, {"non_field_errors":
              ["Suggestion fields and tags don't have any changes to the original note"]})
    assert code == "VALIDATION_ERROR" and "sync with AnkiHub first" in msg
    code, msg = core.map_ankihub_http_error(401, None)
    assert code == "ANKIHUB_NOT_LOGGED_IN"
    code, msg = core.map_ankihub_http_error(403, {"detail": "no active subscription"})
    assert code == "PERMISSION_DENIED" and msg == "no active subscription"
    code, msg = core.map_ankihub_http_error(403, "forbidden text")
    assert code == "PERMISSION_DENIED" and "forbidden text" in msg
    code, msg = core.map_ankihub_http_error(404, None)
    assert code == "NOTE_DELETED_ON_ANKIHUB"
    code, msg = core.map_ankihub_http_error(429, None)
    assert code == "RATE_LIMITED"
    for status in (500, 502, 503, 418):
        code, msg = core.map_ankihub_http_error(status, "boom")
        assert code == "NETWORK_ERROR" and str(status) in msg


# ---------------------------------------------------------------- test 9
def test9_map_change_result():
    assert core.map_ankihub_change_result("SUCCESS") == "success"
    assert core.map_ankihub_change_result("NO_CHANGES") == "noChanges"
    assert core.map_ankihub_change_result("ANKIHUB_NOT_FOUND") == "notFoundOnAnkiHub"
    assert core.map_ankihub_change_result("EMPTY_FIRST_FIELD") == "emptyFirstField"
    expect_raises(lambda: core.map_ankihub_change_result("SOMETHING_NEW"),
                  "INCOMPATIBLE_ANKIHUB_ADDON")


# ---------------------------------------------------------------- test 10
def test10_missing_params():
    full = ["note", "change_type", "comment", "media_upload_cb", "auto_accept", "filters"]
    assert core.ankihub_missing_params(full, "suggest_note_update") == []
    assert core.ankihub_missing_params(
        ["note", "comment"], "suggest_note_update") == \
        ["auto_accept", "change_type", "media_upload_cb"]
    assert core.ankihub_missing_params(
        ["note", "comment", "ankihub_did", "media_upload_cb", "auto_accept"],
        "suggest_new_note") == []
    assert core.ankihub_missing_params([], "has_empty_first_field") == ["note"]


run("test1_actions_registered", test1_actions_registered)
run("test2_constants", test2_constants)
run("test3_validate_change_type", test3_validate_change_type)
run("test4_validate_rationale", test4_validate_rationale)
run("test5_comment_for_update_source_rules", test5_comment_for_update_source_rules)
run("test6_source_shape_validation", test6_source_shape_validation)
run("test7_comment_for_new_note", test7_comment_for_new_note)
run("test8_map_http_error", test8_map_http_error)
run("test9_map_change_result", test9_map_change_result)
run("test10_missing_params", test10_missing_params)

# the add-on must STILL not be imported after the whole suite
assert core.ANKIHUB_ADDON_PACKAGE not in sys.modules, "a test imported the AnkiHub add-on"

print("\n===== SUMMARY =====")
n_pass = sum(1 for _, ok, _ in RESULTS if ok)
for name, ok, _ in RESULTS:
    print("%s  %s" % ("PASS" if ok else "FAIL", name))
print("%d/%d passed" % (n_pass, len(RESULTS)))
sys.exit(0 if n_pass == len(RESULTS) else 1)
