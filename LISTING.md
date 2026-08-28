# AnkiWeb listing copy — Agent Connect

**Title:** Agent Connect

**Support page / homepage:** https://github.com/mattccorrell-svg/anki-connect-plus

---

## Description (paste into AnkiWeb)

**A fork of [AnkiConnect](https://foosoft.net/projects/anki-connect/) by Alex Yatskov (FooSoft Productions), GPLv3. Not affiliated with or endorsed by the original author.**

Agent Connect keeps everything AnkiConnect does and adds 37 actions built for driving Anki from a script or an AI agent — where the work is done in bulk, and where a mistake is expensive.

**What it adds**

- **Bulk writes that are one transaction and one undo.** 500 notes in ~0.06s. Ctrl+Z reverts the whole batch. Name the batch with `undoLabel` so your Undo menu is readable.
- **Dry runs.** Every bulk action takes `dryRun: true`: full validation, a complete report of what *would* change, and zero writes.
- **Answers that describe what happened.** Actions distinguish `updated` from `unchanged`, `changed` from `unsuspended`, `total` from `missing`. A batch that "succeeded" while skipping 40 notes says so.
- **Image occlusion from the API** — create, read, and update IO notes; crop an image and have its masks remapped with it.
- **Deck maintenance** — `checkDeckIntegrity` (missing media, unbalanced cloze, empty cards, orphan media), `renameDeck` (whole subtree, options presets preserved), segment-aware `renameTag` (renaming `lab1` never touches `lab10`), regex find/replace with a preview.
- **Filtered decks** — create, rebuild, report, empty.
- **Verified sync** — `syncNow` runs in the background; `syncStatus` tells you whether the collection *actually* matches AnkiWeb.
- **Exports that refuse to be silently wrong** — a deck export stops if cards are sitting in a filtered deck, instead of quietly omitting them.
- **Self-documenting** — call `plusInfo` for every action's parameters, return shape, error codes, and usage recipes. Machine-readable error codes with a `retryable` flag.

**Getting started**

Runs on `http://localhost:8766` (stock AnkiConnect uses 8765, so both can run side by side). Same request format as AnkiConnect:

    POST http://localhost:8766
    {"action": "plusInfo", "version": 6, "params": {}}

Start with `plusInfo` — it is the complete reference.

**Security**

It listens on localhost only and ships with no password, exactly like AnkiConnect. Anything that can reach the port can modify your collection. **Do not expose it to the internet or a shared network.** Set `apiKey` in the add-on config if other software on your machine shouldn't have access.

**Requirements and caveats**

- Requires **Anki 25.09 or newer**.
- Developed and tested on **macOS**. It should be portable, but Windows and Linux are untested — reports welcome on GitHub.
- The three `ankihub*` actions are **experimental**: they depend on the third-party AnkiHub add-on and may break when it updates. Everything else works without AnkiHub installed.
- One deliberate difference from stock Anki: rescheduling a suspended card normally un-suspends it. This add-on puts the suspension back and tells you it did. Switch it off with `preserveSuspendedOnReschedule: false` in the config.

**Source and license**

GPLv3, same as the original. Full source, specification, and 24 test suites: https://github.com/mattccorrell-svg/anki-connect-plus
