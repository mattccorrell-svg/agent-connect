# Feature request: optional-tag suggestion endpoints

Written 2026-08-18, from the BSOM → AnKing curriculum mapping project.

## The problem

The BSOM project maps each Foundations PI onto existing AnKing cards and publishes
the mapping as an AnkiHub Optional Tag group (`AnkiHub_Optional::BSOM::...`).

Everything up to publication is already scriptable:

- selecting candidate notes  → `ankipool.py`
- deciding which to include  → an LLM pass, then human review
- applying the tag locally   → AnkiConnect Plus `addTags`

Publication is not. It is `Browser → select notes → right click → "Suggest
Optional Tags"` — a Qt menu action. So an otherwise automated workflow ends with
hand-selecting 90 notes in the Browser, once per PI, every week, forever.

**The requirement is that an AI agent manages this pipeline end to end**, not that
a human clicks faster. A curriculum is 20–30 PIs a semester and the project is
meant to outlive its author and be handed to the next class. A step that only a
human hand can perform is the step that kills it — it is where the backlog forms
when the maintainer has an exam week, and it is the reason a successor quietly
stops maintaining the group. Every other stage of this pipeline can be run,
audited, and re-run by an agent. Publication has to be too, or the automation
stops being automation and becomes a to-do list.

## The hook already exists

```
ankihub_client/ankihub_client.py:1277   def suggest_optional_tags(...)
ankihub_client/ankihub_client.py:1293   def _suggest_optional_tags_for_deck_extension(...)
gui/browser/browser.py:520              def _on_suggest_optional_tags_action(browser)
gui/optional_tag_suggestion_dialog.py   the dialog the menu action opens
main/optional_tag_suggestions.py        the logic behind it
```

`suggest_optional_tags()` is a plain method on the add-on's own client. The GUI
action is a thin wrapper around it. Nothing needs reimplementing — call the same
function the menu calls, with the same authenticated session.

## Endpoint 1 — `suggestOptionalTags`

Submit directly. This is the one that removes the work.

```
POST  { "action": "suggestOptionalTags",
        "params": { "tag": "AnkiHub_Optional::BSOM::StayingAlive::MCQ_3::PI_12_Male_Reproductive",
                    "notes": [1483845152253, 1489115655836, ...],
                    "applyTag": true } }

->    { "result": { "tagged": 87, "submitted": 87, "extensionId": 1234 },
        "error": null }
```

Behavior:

- `applyTag: true` adds the tag locally first (skip if already applied)
- resolve the tag's group to its deck extension, the way the dialog does
- call the add-on's own `suggest_optional_tags()` with the note set
- return counts, not a bare success flag — a partial submission must be visible

Guard rails, all of them cheap:

- reject any tag not starting with `AnkiHub_Optional::`
- reject if the AnkiHub add-on is absent or not logged in
- reject if any note id does not exist, before submitting anything —
  publishing a partial set is worse than publishing nothing
- reject a submission above some sane per-call ceiling (a few hundred notes);
  a runaway loop should fail, not publish
- log every submission locally with tag, note count, and timestamp, so there is
  a record of what was pushed and when

## Endpoint 2 — `stageOptionalTagSuggestion`

Same inputs, but instead of submitting: apply the tag, open the Browser with
exactly those notes selected, open AnkiHub's suggestion dialog, and stop. The
human reads what is about to go out and presses submit.

Worth having alongside endpoint 1. Use it for the first tag of a new group, or
any time the note set has not been reviewed yet. Endpoint 1 for the routine case
once the pipeline is trusted.

## One note on AnkiHub's terms

Their ToS (effective 2025-01-14) prohibits "any automated use of our resources,
including... using scripts to create or post content." Read literally that covers
endpoint 1; read by intent it is aimed at scraping and spam, not a group owner
submitting their own reviewed curation at human scale through the add-on's own
authenticated client.

The practical risk is not legal, it is account-level: this group is meant to
serve a whole class, so it is worth not having it flagged. One email settles it
permanently, and AnkiHub actively recruits tagging contributors (contact
`ahmed@ankihub.net`, they pay in free Premium):

> A student-maintained curriculum mapping group publishes 20–30 optional tags per
> semester, each covering 50–100 notes, all human-reviewed before submission. May
> we submit these programmatically through the add-on's own client, or should each
> go through the Browser dialog?

Build both endpoints now. Send the email when convenient.
