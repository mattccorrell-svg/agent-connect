# Copyright 2016-2021 Alex Yatskov
# Copyright (C) 2026 Matthew Correll (AnkiConnect Plus modifications)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

"""Business logic for the AnkiConnect Plus actions.

Part of AnkiConnect Plus, a fork of AnkiConnect by Alex Yatskov (FooSoft
Productions) — https://foosoft.net/projects/anki-connect/

Every public function is a pure function over anki.collection.Collection;
this module never imports aqt so it stays headless-testable.
"""

import base64
import binascii
import json
import os

import anki.collection
import anki.notes
import anki.utils
from anki.errors import NotFoundError

PLUS_VERSION = "1.0.0"
PLUS_ACTIONS = ["bulkAddNotes", "bulkUpdateNoteFields", "bulkAddTags",
                "addImageOcclusionNote", "getImageOcclusionNote",
                "updateImageOcclusionNote", "queryRevlog", "createBackup", "plusInfo"]
DOCS_UPSTREAM = "https://foosoft.net/projects/anki-connect/"
DOCS_UPSTREAM_SOURCE = "https://git.sr.ht/~foosoft/anki-connect"
DOCS_PLUS = "https://github.com/mattccorrell-svg/anki-connect-plus#readme"

UNDO_BULK_ADD = 'AnkiConnect Plus: Bulk Add'
UNDO_BULK_UPDATE = 'AnkiConnect Plus: Bulk Update'
UNDO_BULK_TAGS = 'AnkiConnect Plus: Bulk Tags'

IO_STOCK_KIND = 6

# SQLite allows at most 32766 bound variables per statement; chunk IN-lists
# well below that so fixed parameters (mid, dids, since/until, limit) still fit.
SQL_IN_CHUNK = 15000


#
# Shared helpers
#

def io_num(v):
    s = '{:.4f}'.format(float(v))
    if s.startswith('0.'):
        s = s[1:]
    return s


def serialize_occlusions(shapes, hide_all_guess_one=True):
    if not isinstance(shapes, list):
        raise Exception('invalid parameter: occlusions: string or array required')
    if not shapes:
        raise Exception('invalid parameter: occlusions: at least one occlusion required')

    clozes = []
    for i, shape in enumerate(shapes):
        if not isinstance(shape, dict):
            raise Exception('invalid parameter: occlusions[{}]: object required'.format(i))
        for key in ('left', 'top', 'width', 'height'):
            value = shape.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise Exception('invalid parameter: occlusions[{}]: {} must be a number'.format(i, key))
        left, top = shape['left'], shape['top']
        width, height = shape['width'], shape['height']
        if not (0 <= left <= 1) or not (0 <= top <= 1):
            raise Exception('invalid parameter: occlusions[{}]: left and top must be within 0-1'.format(i))
        if not (0 < width <= 1) or not (0 < height <= 1):
            raise Exception('invalid parameter: occlusions[{}]: width and height must be within 0-1'.format(i))
        # io_num serializes at 4 decimal places; reject sizes that would
        # round to a zero-width/zero-height rect despite passing the range check
        if float('{:.4f}'.format(float(width))) == 0 or float('{:.4f}'.format(float(height))) == 0:
            raise Exception('invalid parameter: occlusions[{}]: width and height must be at least 0.00005'.format(i))
        ordinal = shape.get('ordinal', i + 1)
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0:
            raise Exception('invalid parameter: occlusions[{}]: ordinal must be a non-negative integer'.format(i))

        properties = 'left={}:top={}:width={}:height={}'.format(
            io_num(left), io_num(top), io_num(width), io_num(height))
        if hide_all_guess_one:
            properties += ':oi=1'
        clozes.append('{{{{c{}::image-occlusion:rect:{}}}}}'.format(ordinal, properties))

    return '<br>'.join(clozes)


def parse_io_response_occlusions(resp_note):
    entries = []
    for occlusion in resp_note.occlusions:
        for shape in occlusion.shapes:
            properties = {prop.name: prop.value for prop in shape.properties}
            entry = {'ordinal': occlusion.ordinal, 'shape': shape.shape}
            if shape.shape == 'rect':
                try:
                    for key in ('left', 'top', 'width', 'height'):
                        entry[key] = float(properties.pop(key))
                except (KeyError, ValueError):
                    entry = {'ordinal': occlusion.ordinal, 'shape': shape.shape,
                             'properties': {prop.name: prop.value for prop in shape.properties}}
                else:
                    if properties:
                        entry['properties'] = properties
            else:
                entry['properties'] = properties
            entries.append(entry)
    return entries


def find_io_notetype_id(col):
    for notetype in col.models.all():
        if notetype.get('originalStockKind') == IO_STOCK_KIND:
            return notetype['id']
    notetype = col.models.by_name('Image Occlusion')
    if notetype is not None:
        return notetype['id']
    raise Exception('image occlusion notetype not found')


def _revert_batch(col, undo_name):
    # Reverts the batch's merged undo entry. Also called when zero ops merged
    # into the entry: undoing an empty custom entry is a data no-op but pops
    # it off the stack, so we never leave a do-nothing item in the Undo menu
    # (SPEC Deviation #7).
    if col.undo_status().undo == undo_name:
        col.undo()


def _pop_empty_undo(col, target, written, undo_name):
    # Non-atomic path: the lazily created entry stayed empty because every
    # write after its creation failed; drop it so the UI matches undoEntry=null.
    if target is not None and not written:
        _revert_batch(col, undo_name)


def _batch_error(action, undo_name, count_key, index, error, count, skipped):
    report = {'failedIndex': index, 'error': str(error), count_key: count, 'skipped': skipped}
    return Exception('{} failed (batch reverted): {}'.format(action, json.dumps(report, separators=(',', ':'))))


def _validate_tag_list(tags, name):
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise Exception('invalid parameter: {}: list of strings required'.format(name))


#
# Bulk actions
#

def bulk_add_notes(col, notes, atomic=True, allow_duplicates=False):
    if not isinstance(notes, list):
        raise Exception('invalid parameter: notes: list required')
    if not notes:
        return {'added': [], 'skipped': [], 'undoEntry': None}
    for i, note in enumerate(notes):
        if not isinstance(note, dict):
            raise Exception('invalid parameter: notes[{}]: object required'.format(i))

    # resolution pass: no writes
    resolved = []
    for i, note in enumerate(notes):
        modelName = note.get('modelName')
        if modelName is not None and not isinstance(modelName, str):
            resolved.append({'skip': 'invalid parameter: notes[{}].modelName: string required'.format(i)})
            continue
        model = col.models.by_name(modelName) if modelName else None
        if model is None:
            resolved.append({'skip': 'model was not found: {}'.format(modelName)})
            continue
        deckName = note.get('deckName')
        if deckName is not None and not isinstance(deckName, str):
            resolved.append({'skip': 'invalid parameter: notes[{}].deckName: string required'.format(i)})
            continue
        did = col.decks.id_for_name(deckName) if deckName else None
        if did is None:
            resolved.append({'skip': 'deck was not found: {}'.format(deckName)})
            continue

        fields = note.get('fields') or {}
        if not isinstance(fields, dict):
            resolved.append({'skip': 'invalid parameter: notes[{}].fields: object required'.format(i)})
            continue
        fieldNames = {fld['name'] for fld in model['flds']}
        unknown = next((name for name in fields if name not in fieldNames), None)
        if unknown is not None:
            resolved.append({'skip': 'field was not found in model: {}'.format(unknown)})
            continue
        badValue = next((name for name, value in fields.items() if not isinstance(value, str)), None)
        if badValue is not None:
            resolved.append({'skip': 'invalid parameter: notes[{}].fields.{}: string required'.format(i, badValue)})
            continue

        tags = note.get('tags') or []
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            resolved.append({'skip': 'invalid parameter: notes[{}].tags: list of strings required'.format(i)})
            continue

        options = note.get('options') or {}
        allow = options.get('allowDuplicate', allow_duplicates) if isinstance(options, dict) else allow_duplicates
        if not isinstance(allow, bool):
            resolved.append({'skip': 'invalid parameter: notes[{}].options.allowDuplicate: boolean required'.format(i)})
            continue

        firstField = model['flds'][0]['name']
        stripped = anki.utils.strip_html_media(fields.get(firstField, ''))
        if not stripped.strip():
            resolved.append({'skip': 'empty first field'})
            continue

        resolved.append({
            'model': model,
            'did': did,
            'fields': fields,
            'tags': tags,
            'allow': allow,
            'csum': anki.utils.field_checksum(fields.get(firstField, '')),
            'stripped': stripped,
        })

    # duplicate precheck: one read-only select per distinct mid
    csumsByMid = {}
    for entry in resolved:
        if 'skip' not in entry:
            csumsByMid.setdefault(entry['model']['id'], set()).add(entry['csum'])

    existingByMid = {}
    for mid, csums in csumsByMid.items():
        existing = set()
        csumList = sorted(csums)
        for start in range(0, len(csumList), SQL_IN_CHUNK):
            chunk = csumList[start:start + SQL_IN_CHUNK]
            placeholders = ','.join('?' * len(chunk))
            rows = col.db.all(
                'select csum, flds from notes where mid = ? and csum in ({})'.format(placeholders),
                mid, *chunk)
            existing.update(anki.utils.strip_html_media(flds.split('\x1f')[0]) for _, flds in rows)
        existingByMid[mid] = existing

    seen = set()
    for entry in resolved:
        if 'skip' in entry:
            continue
        key = (entry['model']['id'], entry['stripped'])
        if not entry['allow']:
            if entry['stripped'] in existingByMid.get(entry['model']['id'], set()):
                entry['skip'] = 'duplicate'
                continue
            if key in seen:
                entry['skip'] = 'duplicate (within batch)'
                continue
        seen.add(key)

    # write pass
    added = []
    skipped = []
    target = None
    for i, entry in enumerate(resolved):
        if 'skip' in entry:
            skipped.append({'index': i, 'reason': entry['skip']})
            continue
        try:
            ankiNote = anki.notes.Note(col, entry['model'])
            for name, value in entry['fields'].items():
                ankiNote[name] = value
            ankiNote.tags = list(entry['tags'])
            if target is None:
                target = col.add_custom_undo_entry(UNDO_BULK_ADD)
            col.add_note(ankiNote, entry['did'])
            col.merge_undo_entries(target)
            added.append(ankiNote.id)
        except Exception as e:
            if atomic:
                _revert_batch(col, UNDO_BULK_ADD)
                raise _batch_error('bulkAddNotes', UNDO_BULK_ADD, 'addedBeforeRevert', i, e, len(added), skipped)
            skipped.append({'index': i, 'reason': str(e)})

    _pop_empty_undo(col, target, added, UNDO_BULK_ADD)
    return {'added': added, 'skipped': skipped, 'undoEntry': UNDO_BULK_ADD if added else None}


def bulk_update_note_fields(col, notes, atomic=True):
    if not isinstance(notes, list):
        raise Exception('invalid parameter: notes: list required')

    updated = []
    skipped = []
    target = None
    for i, entry in enumerate(notes):
        if not isinstance(entry, dict):
            skipped.append({'index': i, 'reason': 'invalid parameter: notes[{}]: object required'.format(i)})
            continue
        nid = entry.get('id')
        if isinstance(nid, bool) or not isinstance(nid, int):
            skipped.append({'index': i, 'reason': 'invalid parameter: notes[{}]: id required'.format(i)})
            continue
        fields = entry.get('fields')
        tags = entry.get('tags')
        if fields is None and tags is None:
            skipped.append({'index': i, 'reason': 'invalid parameter: notes[{}]: fields or tags required'.format(i)})
            continue
        if fields is not None and not isinstance(fields, dict):
            skipped.append({'index': i, 'reason': 'invalid parameter: notes[{}].fields: object required'.format(i)})
            continue
        if tags is not None and (not isinstance(tags, list) or not all(isinstance(t, str) for t in tags)):
            skipped.append({'index': i, 'reason': 'invalid parameter: notes[{}].tags: list of strings required'.format(i)})
            continue

        try:
            ankiNote = col.get_note(nid)
        except NotFoundError:
            skipped.append({'index': i, 'reason': 'note was not found: {}'.format(nid)})
            continue

        # validate the whole entry before mutating the note
        if fields is not None:
            unknown = next((name for name in fields if name not in ankiNote), None)
            if unknown is not None:
                skipped.append({'index': i, 'reason': 'field was not found in note: {}'.format(unknown)})
                continue
            badValue = next((name for name, value in fields.items() if not isinstance(value, str)), None)
            if badValue is not None:
                skipped.append({'index': i, 'reason': 'invalid parameter: notes[{}].fields.{}: string required'.format(i, badValue)})
                continue

        try:
            if fields is not None:
                for name, value in fields.items():
                    ankiNote[name] = value
            if tags is not None:
                ankiNote.tags = list(tags)
            if target is None:
                target = col.add_custom_undo_entry(UNDO_BULK_UPDATE)
            col.update_note(ankiNote)
            col.merge_undo_entries(target)
            updated.append(nid)
        except Exception as e:
            if atomic:
                _revert_batch(col, UNDO_BULK_UPDATE)
                raise _batch_error('bulkUpdateNoteFields', UNDO_BULK_UPDATE, 'updatedBeforeRevert', i, e, len(updated), skipped)
            skipped.append({'index': i, 'reason': str(e)})

    _pop_empty_undo(col, target, updated, UNDO_BULK_UPDATE)
    return {'updated': updated, 'skipped': skipped, 'undoEntry': UNDO_BULK_UPDATE if updated else None}


def bulk_add_tags(col, note_ids, tags, atomic=True):
    if not isinstance(note_ids, list):
        raise Exception('invalid parameter: noteIds: list required')
    if not all(isinstance(nid, int) and not isinstance(nid, bool) for nid in note_ids):
        raise Exception('invalid parameter: noteIds: ints required')
    if isinstance(tags, str):
        tagList = tags.split()
    elif isinstance(tags, list) and all(isinstance(t, str) for t in tags):
        tagList = [t for tag in tags for t in tag.split()]
    else:
        raise Exception('invalid parameter: tags: string or list of strings required')
    if not tagList:
        raise Exception('invalid parameter: tags: at least one tag required')

    updated = []
    skipped = []
    target = None
    for i, nid in enumerate(note_ids):
        try:
            ankiNote = col.get_note(nid)
        except NotFoundError:
            skipped.append({'index': i, 'reason': 'note was not found: {}'.format(nid)})
            continue
        missing = [t for t in tagList if not ankiNote.has_tag(t)]
        if not missing:
            continue
        try:
            for t in missing:
                ankiNote.add_tag(t)
            if target is None:
                target = col.add_custom_undo_entry(UNDO_BULK_TAGS)
            col.update_note(ankiNote)
            col.merge_undo_entries(target)
            updated.append(nid)
        except Exception as e:
            if atomic:
                _revert_batch(col, UNDO_BULK_TAGS)
                raise _batch_error('bulkAddTags', UNDO_BULK_TAGS, 'updatedBeforeRevert', i, e, len(updated), skipped)
            skipped.append({'index': i, 'reason': str(e)})

    _pop_empty_undo(col, target, updated, UNDO_BULK_TAGS)
    return {'updated': updated, 'skipped': skipped, 'undoEntry': UNDO_BULK_TAGS if updated else None}


#
# Image occlusion
#

def add_image_occlusion_note(col, image_path=None, image_data_b64=None, image_filename=None,
                             occlusions=None, header="", back_extra="",
                             tags=None, deck_name=None, hide_all_guess_one=True):
    if (image_path is None) == (image_data_b64 is None):
        raise Exception('invalid parameter: image: exactly one of path or data required')

    if isinstance(occlusions, str):
        occlusionsStr = occlusions
    elif isinstance(occlusions, list):
        occlusionsStr = serialize_occlusions(occlusions, hide_all_guess_one)
    else:
        raise Exception('invalid parameter: occlusions: string or array required')

    if not isinstance(header, str):
        raise Exception('invalid parameter: header: string required')
    if not isinstance(back_extra, str):
        raise Exception('invalid parameter: backExtra: string required')
    tags = tags or []
    _validate_tag_list(tags, 'tags')

    if deck_name is not None and not isinstance(deck_name, str):
        raise Exception('invalid parameter: deckName: string required')
    did = col.decks.id_for_name(deck_name) if deck_name else None
    if did is None:
        raise Exception('deck was not found: {}'.format(deck_name))

    imageData = None
    if image_data_b64 is not None:
        if not image_filename or not isinstance(image_filename, str):
            raise Exception('invalid parameter: image.filename: required with data')
        if not isinstance(image_data_b64, str):
            raise Exception('invalid parameter: image.data: string required')
        try:
            # tolerate MIME/RFC-2045 line-wrapped base64 (as upstream's lenient
            # media path does) while still rejecting garbage via validate=True
            imageData = base64.b64decode(''.join(image_data_b64.split()), validate=True)
        except (binascii.Error, ValueError):
            raise Exception('invalid parameter: image.data: invalid base64')
    else:
        if not isinstance(image_path, str) or not os.path.isfile(image_path):
            raise Exception('image file was not found: {}'.format(image_path))

    # all validation done; writes start here
    col.add_image_occlusion_notetype()
    notetypeId = find_io_notetype_id(col)

    if imageData is not None:
        fname = col.media.write_data(image_filename, imageData)
        imagePath = os.path.join(col.media.dir(), fname)
    else:
        imagePath = image_path

    before = col.db.scalar('select max(id) from notes') or 0
    col.add_image_occlusion_note(notetypeId, imagePath, occlusionsStr, header, back_extra, list(tags))
    nid = col.db.scalar('select id from notes where id > ?', before)
    if nid is None:
        raise Exception('image occlusion note was not created')
    cardIds = col.db.list('select id from cards where nid = ? order by ord', nid)

    currentDids = set(col.db.list('select distinct did from cards where nid = ?', nid))
    if cardIds and currentDids != {did}:
        target = col.undo_status().last_step
        col.set_deck(cardIds, did)
        col.merge_undo_entries(target)

    return {'noteId': nid, 'cardIds': cardIds}


def get_image_occlusion_note(col, note_id):
    if isinstance(note_id, bool) or not isinstance(note_id, int):
        raise Exception('invalid parameter: noteId: int required')

    resp = col.get_image_occlusion_note(note_id)
    if resp.WhichOneof('value') != 'note':
        raise Exception('could not read image occlusion note {}: {}'.format(note_id, resp.error))

    note = resp.note
    return {
        'imageFilename': note.image_file_name,
        'occlusions': parse_io_response_occlusions(note),
        'header': note.header,
        'backExtra': note.back_extra,
        'tags': list(note.tags),
        'occludeInactive': note.occlude_inactive,
    }


def update_image_occlusion_note(col, note_id, occlusions=None, header=None,
                                back_extra=None, tags=None, hide_all_guess_one=True):
    if isinstance(note_id, bool) or not isinstance(note_id, int):
        raise Exception('invalid parameter: noteId: int required')
    try:
        ankiNote = col.get_note(note_id)
    except NotFoundError:
        raise Exception('note was not found: {}'.format(note_id))
    if ankiNote.note_type().get('originalStockKind') != IO_STOCK_KIND:
        raise Exception('note is not an image occlusion note: {}'.format(note_id))

    if occlusions is None:
        occlusionsStr = None
    elif isinstance(occlusions, str):
        occlusionsStr = occlusions
    elif isinstance(occlusions, list):
        occlusionsStr = serialize_occlusions(occlusions, hide_all_guess_one)
    else:
        raise Exception('invalid parameter: occlusions: string or array required')
    if header is not None and not isinstance(header, str):
        raise Exception('invalid parameter: header: string required')
    if back_extra is not None and not isinstance(back_extra, str):
        raise Exception('invalid parameter: backExtra: string required')
    if tags is not None:
        _validate_tag_list(tags, 'tags')

    # the backend updater requires every field; backfill omitted ones from the note
    indexes = col._backend.get_image_occlusion_fields(ankiNote.mid)
    if occlusionsStr is None:
        occlusionsStr = ankiNote.fields[indexes.occlusions]
    if header is None:
        header = ankiNote.fields[indexes.header]
    if back_extra is None:
        back_extra = ankiNote.fields[indexes.back_extra]
    if tags is None:
        tags = ankiNote.tags

    col.update_image_occlusion_note(note_id, occlusionsStr, header, back_extra, list(tags))


#
# Review history
#

def query_revlog(col, card_ids=None, note_ids=None, deck_name=None,
                 since_ms=None, until_ms=None, limit=5000):
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise Exception('invalid parameter: limit: must be >= 1')

    def validated_ids(name, values):
        if not isinstance(values, list) or not all(isinstance(v, int) and not isinstance(v, bool) for v in values):
            raise Exception('invalid parameter: {}: ints required'.format(name))
        return values

    # id filters are chunked to stay under SQLite's bound-variable cap; each
    # (card chunk x note chunk) combination selects a disjoint set of rows,
    # so the per-query results union cleanly and only need a re-sort + trim.
    card_chunks = [None]
    if card_ids is not None:
        card_ids = validated_ids('cardIds', card_ids)
        if not card_ids:
            return {'rows': []}
        card_chunks = [card_ids[i:i + SQL_IN_CHUNK] for i in range(0, len(card_ids), SQL_IN_CHUNK)]

    note_chunks = [None]
    if note_ids is not None:
        note_ids = validated_ids('noteIds', note_ids)
        if not note_ids:
            return {'rows': []}
        note_chunks = [note_ids[i:i + SQL_IN_CHUNK] for i in range(0, len(note_ids), SQL_IN_CHUNK)]

    baseConditions = []
    baseArgs = []

    if deck_name is not None:
        if not isinstance(deck_name, str):
            raise Exception('invalid parameter: deckName: string required')
        did = col.decks.id_for_name(deck_name)
        if did is None:
            raise Exception('deck was not found: {}'.format(deck_name))
        # id-based descendant lookup: immune to the caller's deckName casing
        # (id_for_name matches case-insensitively, stored names may differ)
        dids = sorted(set(col.decks.deck_and_child_ids(did)))
        baseConditions.append('(case when c.odid != 0 then c.odid else c.did end) in ({})'.format(','.join('?' * len(dids))))
        baseArgs.extend(dids)

    if since_ms is not None:
        if isinstance(since_ms, bool) or not isinstance(since_ms, int):
            raise Exception('invalid parameter: sinceMs: int required')
        baseConditions.append('r.id >= ?')
        baseArgs.append(since_ms)

    if until_ms is not None:
        if isinstance(until_ms, bool) or not isinstance(until_ms, int):
            raise Exception('invalid parameter: untilMs: int required')
        baseConditions.append('r.id < ?')
        baseArgs.append(until_ms)

    rawRows = []
    for cardChunk in card_chunks:
        for noteChunk in note_chunks:
            conditions = list(baseConditions)
            args = list(baseArgs)
            if cardChunk is not None:
                conditions.append('r.cid in ({})'.format(','.join('?' * len(cardChunk))))
                args.extend(cardChunk)
            if noteChunk is not None:
                conditions.append('c.nid in ({})'.format(','.join('?' * len(noteChunk))))
                args.extend(noteChunk)
            sql = ('select r.id, r.cid, c.nid, r.ease, r.ivl, r.lastIvl, r.factor, r.time, r.type '
                   'from revlog r left join cards c on c.id = r.cid where 1=1')
            for condition in conditions:
                sql += ' and ' + condition
            sql += ' order by r.id asc limit ?'
            args.append(limit)
            rawRows.extend(col.db.all(sql, *args))

    if len(card_chunks) * len(note_chunks) > 1:
        # each chunk query returned its own first `limit` rows; the global
        # first `limit` rows are contained in their union
        rawRows.sort(key=lambda row: row[0])
        del rawRows[limit:]

    rows = []
    for rid, cid, nid, ease, ivl, lastIvl, factor, timeMs, rtype in rawRows:
        rows.append({
            'id': rid,
            'cardId': cid,
            'noteId': nid,
            'ease': ease,
            'interval': ivl,
            'lastInterval': lastIvl,
            'factor': factor,
            'timeMs': timeMs,
            'type': rtype,
            'reviewedAt': rid,
        })
    return {'rows': rows}


#
# Backup
#

def create_backup(col, force=True):
    if not isinstance(force, bool):
        raise Exception('invalid parameter: force: boolean required')

    folder = os.path.join(os.path.dirname(col.path), 'backups')
    os.makedirs(folder, exist_ok=True)
    created = col.create_backup(backup_folder=folder, force=force, wait_for_completion=True)
    return {'created': created}
