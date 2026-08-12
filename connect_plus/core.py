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
import datetime
import json
import os
import re

import anki.collection
import anki.notes
import anki.utils
from anki.errors import InvalidInput, NotFoundError, SearchError

PLUS_VERSION = "1.0.0"
PLUS_ACTIONS = ["bulkAddNotes", "bulkUpdateNoteFields", "bulkAddTags",
                "addImageOcclusionNote", "getImageOcclusionNote",
                "updateImageOcclusionNote", "queryRevlog", "createBackup",
                # crop a media image into a NEW media file (original kept), optionally rewriting notes to reference it
                "cropImage",
                # crop an IO note's base image and remap its occlusion rects into the cropped frame, one undo entry
                "cropImageOcclusionImage",
                # render cards' question/answer HTML + css through Anki's own template pipeline (read-only)
                "renderCard",
                # compact, paginated, HTML-stripped note reader built for LLM consumption (read-only)
                "notesSlim",
                # base64 thumbnails of media images: aspect-preserved, never upscaled (read-only)
                "mediaThumbnails",
                # suspend or unsuspend cards as one undoable batch
                "bulkSuspend",
                # reschedule cards' due dates ('0', '1-7', '3!') as one undoable batch
                "bulkSetDueDate",
                # export a deck (and its subdecks) to a .apkg file, never overwriting
                "exportDeckApkg",
                "plusInfo"]
DOCS_UPSTREAM = "https://foosoft.net/projects/anki-connect/"
DOCS_UPSTREAM_SOURCE = "https://git.sr.ht/~foosoft/anki-connect"
DOCS_PLUS = "https://github.com/mattccorrell-svg/anki-connect-plus#readme"

UNDO_BULK_ADD = 'AnkiConnect Plus: Bulk Add'
UNDO_BULK_UPDATE = 'AnkiConnect Plus: Bulk Update'
UNDO_BULK_TAGS = 'AnkiConnect Plus: Bulk Tags'
UNDO_CROP_IMAGE = 'AnkiConnect Plus: Crop Image'
UNDO_CROP_IO = 'AnkiConnect Plus: Crop IO Image'
UNDO_BULK_SUSPEND = 'AnkiConnect Plus: Bulk Suspend'
UNDO_BULK_DUE = 'AnkiConnect Plus: Bulk Due Date'

# cards.queue: -1 = suspended; any negative queue (-1 suspended, -2 sibling-
# buried, -3 manually buried) is restored by the backend unsuspend op (SPEC 16)
QUEUE_SUSPENDED = -1

# default target folder for exportDeckApkg when outPath is omitted (SPEC 17)
EXPORT_DEFAULT_DIR = os.path.expanduser('~/Downloads')

IO_STOCK_KIND = 6

# Formats QImageWriter can encode on this Qt build (probe-verified, SPEC 11.3).
# QImage can READ more (gif/svg/svgz/pdf/tga); crops of those re-encode as PNG.
CROP_WRITE_FORMATS = {'bmp', 'cur', 'heic', 'heif', 'icns', 'ico', 'jfif', 'jp2',
                      'jpeg', 'jpg', 'pbm', 'pgm', 'png', 'ppm', 'tif', 'tiff',
                      'wbmp', 'webp', 'xbm', 'xpm'}

# pixel tolerance when deciding whether a remapped occlusion rect was actually
# trimmed by the crop (absorbs float noise from the 4-decimal stored coords)
CLIP_EPS_PX = 1e-6

# SQLite allows at most 32766 bound variables per statement; chunk IN-lists
# well below that so fixed parameters (mid, dids, since/until, limit) still fit.
SQL_IN_CHUNK = 15000

# read-only action caps (SPEC 13, 14): oversized requests are clamped, not rejected
NOTES_SLIM_LIMIT_CAP = 2000
THUMBNAIL_DIM_CAP = 1024
THUMBNAIL_FORMATS = {'jpeg', 'png'}


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

def bulk_add_notes(col, notes, atomic=True, allow_duplicates=False, dry_run=False):
    if not isinstance(notes, list):
        raise Exception('invalid parameter: notes: list required')
    if not notes:
        if dry_run:
            return {'wouldAdd': 0, 'skipped': [], 'undoEntry': None}
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

    # dry run: everything above IS the real path's validation (resolution pass
    # + duplicate precheck, both read-only); stop at the zero-write boundary
    # so the two paths cannot drift (SPEC 15)
    if dry_run:
        skipped = [{'index': i, 'reason': entry['skip']}
                   for i, entry in enumerate(resolved) if 'skip' in entry]
        return {'wouldAdd': len(resolved) - len(skipped), 'skipped': skipped, 'undoEntry': None}

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


def bulk_update_note_fields(col, notes, atomic=True, dry_run=False):
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

        # dry run: full per-entry validation done, nothing read past this point
        # touches the collection or the in-memory Note (SPEC 15)
        if dry_run:
            updated.append(nid)
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

    if dry_run:
        return {'wouldUpdate': updated, 'skipped': skipped, 'undoEntry': None}
    _pop_empty_undo(col, target, updated, UNDO_BULK_UPDATE)
    return {'updated': updated, 'skipped': skipped, 'undoEntry': UNDO_BULK_UPDATE if updated else None}


def bulk_add_tags(col, note_ids, tags, atomic=True, dry_run=False):
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
        # dry run: same no-op detection as the real path, zero writes (SPEC 15)
        if dry_run:
            updated.append(nid)
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

    if dry_run:
        return {'wouldUpdate': updated, 'skipped': skipped, 'undoEntry': None}
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
# Image cropping (SPEC 11)
#

def _validate_crop_rect(rect):
    if not isinstance(rect, dict):
        raise Exception('invalid parameter: rect: object required')
    for key in ('left', 'top', 'width', 'height'):
        value = rect.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise Exception('invalid parameter: rect: {} must be a number'.format(key))
    left, top = float(rect['left']), float(rect['top'])
    width, height = float(rect['width']), float(rect['height'])
    if not (0 <= left <= 1) or not (0 <= top <= 1):
        raise Exception('invalid parameter: rect: left and top must be within 0-1')
    if not (0 < width <= 1) or not (0 < height <= 1):
        raise Exception('invalid parameter: rect: width and height must be within 0-1')
    return left, top, width, height


def _crop_media_image(col, filename, rect):
    """Load a media image, crop it per the normalized rect, and encode the
    result. Pure read: returns (newName, data, (cx, cy, cw, ch), imgW, imgH)
    without writing anything; callers store data via col.media.write_data.

    PyQt6 is imported lazily so importing this module stays Qt-free; QImage
    load/crop/save needs no Q(Gui)Application on this build (probe-verified).
    """
    left, top, width, height = _validate_crop_rect(rect)
    if not isinstance(filename, str) or not filename:
        raise Exception('invalid parameter: filename: string required')
    if os.path.basename(filename) != filename:
        raise Exception('invalid parameter: filename: bare media filename required')
    path = os.path.join(col.media.dir(), filename)
    if not os.path.isfile(path):
        raise Exception('media file was not found: {}'.format(filename))

    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QRect
    from PyQt6.QtGui import QImage

    img = QImage(path)
    if img.isNull() or img.width() < 1 or img.height() < 1:
        raise Exception('could not load image: {} (unsupported or corrupt format)'.format(filename))
    imgW, imgH = img.width(), img.height()

    # QImage.copy PADS (does not clamp) when the rect leaves the image, and
    # padded output is explicitly forbidden -> clamp the pixel rect ourselves
    cx = max(0, min(int(round(left * imgW)), imgW))
    cy = max(0, min(int(round(top * imgH)), imgH))
    cw = min(int(round(width * imgW)), imgW - cx)
    ch = min(int(round(height * imgH)), imgH - cy)
    if cw < 1 or ch < 1:
        raise Exception('invalid parameter: rect: selects an empty area of {} ({}x{})'.format(
            filename, imgW, imgH))

    cropped = img.copy(QRect(cx, cy, cw, ch))

    stem, ext = os.path.splitext(filename)
    fmt = ext[1:].lower()
    if fmt in CROP_WRITE_FORMATS:
        newName = '{}-crop{}'.format(stem, ext)
    else:
        fmt = 'png'  # readable but not writable format (gif/svg/pdf/...): re-encode
        newName = '{}-crop.png'.format(stem)

    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    ok = cropped.save(buf, fmt)
    buf.close()
    if not ok:
        raise Exception('could not encode cropped image as {}: {}'.format(fmt, filename))
    return newName, bytes(ba), (cx, cy, cw, ch), imgW, imgH


def crop_image(col, filename, rect, note_ids=None):
    notes = []
    if note_ids is not None:
        if not isinstance(note_ids, list) or not all(
                isinstance(nid, int) and not isinstance(nid, bool) for nid in note_ids):
            raise Exception('invalid parameter: noteIds: ints required')
        for nid in dict.fromkeys(note_ids):  # dedupe: one Note object per id
            try:
                notes.append(col.get_note(nid))
            except NotFoundError:
                raise Exception('note was not found: {}'.format(nid))

    newName, data, (_cx, _cy, cw, ch), _imgW, _imgH = _crop_media_image(col, filename, rect)

    # writes start here; the original media file is never touched
    fname = col.media.write_data(newName, data)

    # boundary-guarded so 'a.png' never matches inside 'banana.png'; the
    # callable replacement inserts the new name literally (no \-escape parsing)
    pattern = re.compile(r'(?<![\w./\\-])' + re.escape(filename) + r'(?![\w.-])')
    updated = []
    target = None
    for ankiNote in notes:
        changed = False
        for i, value in enumerate(ankiNote.fields):
            newValue, count = pattern.subn(lambda match: fname, value)
            if count:
                ankiNote.fields[i] = newValue
                changed = True
        if not changed:
            continue
        if target is None:
            target = col.add_custom_undo_entry(UNDO_CROP_IMAGE)
        try:
            col.update_note(ankiNote)
            col.merge_undo_entries(target)
        except Exception as e:
            _revert_batch(col, UNDO_CROP_IMAGE)
            raise Exception('cropImage failed (note updates reverted): {}'.format(e))
        updated.append(ankiNote.id)

    return {'newFilename': fname, 'width': cw, 'height': ch, 'notesUpdated': updated}


def crop_image_occlusion_image(col, note_id, rect):
    if isinstance(note_id, bool) or not isinstance(note_id, int):
        raise Exception('invalid parameter: noteId: int required')
    try:
        ankiNote = col.get_note(note_id)
    except NotFoundError:
        raise Exception('note was not found: {}'.format(note_id))
    if ankiNote.note_type().get('originalStockKind') != IO_STOCK_KIND:
        raise Exception('note is not an image occlusion note: {}'.format(note_id))

    ioNote = get_image_occlusion_note(col, note_id)
    filename = ioNote['imageFilename']
    if not filename:
        raise Exception('image occlusion note has no image file: {}'.format(note_id))

    # refuse anything the rect-only serializer (SPEC 5) cannot re-emit losslessly
    shapes = ioNote['occlusions']
    oiValues = set()
    for entry in shapes:
        if entry['shape'] != 'rect':
            raise Exception('cropImageOcclusionImage supports rect occlusions only; '
                            'note {} contains a {} shape'.format(note_id, entry['shape']))
        if 'left' not in entry:
            raise Exception('could not parse rect occlusion on note {}'.format(note_id))
        properties = entry.get('properties') or {}
        extra = sorted(set(properties) - {'oi'})
        if extra:
            raise Exception('cropImageOcclusionImage cannot preserve occlusion properties {} '
                            'on note {}'.format(', '.join(extra), note_id))
        oiValues.add(properties.get('oi'))
    # serialize_occlusions applies one note-level oi flag to every shape; mixed
    # per-shape oi (only possible on hand-edited fields -- Anki's editor sets
    # oi globally) cannot be represented, so refuse rather than homogenize
    if len(oiValues) > 1:
        raise Exception('cropImageOcclusionImage cannot preserve mixed oi flags '
                        'on note {}'.format(note_id))

    newName, data, (cx, cy, cw, ch), imgW, imgH = _crop_media_image(col, filename, rect)

    # remap in pixel space of the ORIGINAL image (SPEC 11.2)
    kept = []
    clippedCount = 0
    droppedCount = 0
    for entry in shapes:
        x0 = entry['left'] * imgW
        y0 = entry['top'] * imgH
        x1 = x0 + entry['width'] * imgW
        y1 = y0 + entry['height'] * imgH
        nx0, ny0 = max(x0, cx), max(y0, cy)
        nx1, ny1 = min(x1, cx + cw), min(y1, cy + ch)
        newWidth = (nx1 - nx0) / cw
        newHeight = (ny1 - ny0) / ch
        # entirely outside the crop, or a sliver that io_num's 4-decimal
        # serialization would collapse to zero size: unrepresentable -> drop
        if (nx1 <= nx0 or ny1 <= ny0
                or float('{:.4f}'.format(newWidth)) == 0
                or float('{:.4f}'.format(newHeight)) == 0):
            droppedCount += 1
            continue
        if (x0 < nx0 - CLIP_EPS_PX or y0 < ny0 - CLIP_EPS_PX
                or x1 > nx1 + CLIP_EPS_PX or y1 > ny1 + CLIP_EPS_PX):
            clippedCount += 1
        kept.append({'left': (nx0 - cx) / cw, 'top': (ny0 - cy) / ch,
                     'width': newWidth, 'height': newHeight,
                     'ordinal': entry['ordinal']})

    if not kept:
        raise Exception('crop would remove all occlusions on note {}'.format(note_id))

    occlusionsStr = serialize_occlusions(kept, hide_all_guess_one=ioNote['occludeInactive'])

    indexes = col._backend.get_image_occlusion_fields(ankiNote.mid)
    header = ankiNote.fields[indexes.header]
    backExtra = ankiNote.fields[indexes.back_extra]

    # media write first: not undoable, but it only ADDS a new file
    fname = col.media.write_data(newName, data)

    target = col.add_custom_undo_entry(UNDO_CROP_IO)
    try:
        # same raw format the backend itself writes to the Image field
        ankiNote.fields[indexes.image] = '<img src="{}">'.format(fname)
        col.update_note(ankiNote)
        col.merge_undo_entries(target)
        col.update_image_occlusion_note(note_id, occlusionsStr, header, backExtra, list(ankiNote.tags))
        col.merge_undo_entries(target)
    except Exception as e:
        _revert_batch(col, UNDO_CROP_IO)
        raise Exception('cropImageOcclusionImage failed (changes reverted): {}'.format(e))

    cardIds = col.db.list('select id from cards where nid = ? order by ord', note_id)
    return {'newFilename': fname, 'occlusionsKept': len(kept),
            'occlusionsClipped': clippedCount, 'occlusionsDropped': droppedCount,
            'cardIds': cardIds}


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


#
# Card rendering (SPEC 12)
#

def render_card(col, card_ids):
    if not isinstance(card_ids, list) or not all(
            isinstance(cid, int) and not isinstance(cid, bool) for cid in card_ids):
        raise Exception('invalid parameter: cardIds: ints required')

    cards = []
    for cid in card_ids:
        try:
            card = col.get_card(cid)
        except NotFoundError:
            cards.append({'cardId': cid, 'error': 'card was not found: {}'.format(cid)})
            continue
        try:
            out = card.render_output()
            cards.append({
                'cardId': cid,
                # rendered template HTML WITHOUT the <style> wrapper; css ships
                # separately so clients can wrap (or not) themselves
                'question': out.question_text,
                'answer': out.answer_text,
                'css': out.css,
                # current_deck_id() = odid or did: home deck for filtered cards
                'deckName': col.decks.name(card.current_deck_id()),
                'modelName': card.note_type()['name'],
                'ord': card.ord,
            })
        except Exception as e:
            cards.append({'cardId': cid, 'error': 'could not render card {}: {}'.format(cid, e)})
    return {'cards': cards}


#
# Slim note reads (SPEC 13)
#

def notes_slim(col, query=None, note_ids=None, fields=None, strip_html=True,
               max_field_length=400, offset=0, limit=200):
    if (query is None) == (note_ids is None):
        raise Exception('invalid parameter: query: exactly one of query or noteIds required')
    if query is not None and not isinstance(query, str):
        raise Exception('invalid parameter: query: string required')
    if note_ids is not None and (not isinstance(note_ids, list) or not all(
            isinstance(nid, int) and not isinstance(nid, bool) for nid in note_ids)):
        raise Exception('invalid parameter: noteIds: ints required')
    if fields is not None:
        _validate_tag_list(fields, 'fields')
    if not isinstance(strip_html, bool):
        raise Exception('invalid parameter: stripHtml: boolean required')
    if isinstance(max_field_length, bool) or not isinstance(max_field_length, int) or max_field_length < 0:
        raise Exception('invalid parameter: maxFieldLength: int >= 0 required')
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise Exception('invalid parameter: offset: int >= 0 required')
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise Exception('invalid parameter: limit: must be >= 1')
    limit = min(limit, NOTES_SLIM_LIMIT_CAP)

    if query is not None:
        try:
            # order=False is the fastest path; sorting ids ourselves gives a
            # deterministic ascending-noteId (creation) order for pagination
            ids = sorted(col.find_notes(query, order=False))
        except SearchError as e:
            raise Exception('invalid parameter: query: {}'.format(e))
    else:
        ids = list(note_ids)  # caller order preserved, duplicates included

    total = len(ids)
    wanted = set(fields) if fields is not None else None

    notes = []
    for nid in ids[offset:offset + limit]:
        try:
            ankiNote = col.get_note(nid)
        except NotFoundError:
            # noteIds path only: stale id, omitted from the page (SPEC 13);
            # total still counts it, so pages may run short of limit
            continue
        model = ankiNote.note_type()
        outFields = {}
        for fld in model['flds']:
            name = fld['name']
            if wanted is not None and name not in wanted:
                continue
            text = ankiNote[name]
            if strip_html:
                # module-level anki.utils.html_to_text_line routes through the
                # collection-less current_i18n backend and raises headless;
                # the open collection's backend works everywhere (SPEC 13)
                text = col._backend.html_to_text_line(text=text, preserve_media_filenames=True)
            if max_field_length and len(text) > max_field_length:
                text = text[:max_field_length] + '…'
            outFields[name] = text
        notes.append({
            'noteId': ankiNote.id,
            'modelName': model['name'],
            'tags': list(ankiNote.tags),
            'fields': outFields,
        })

    nextOffset = offset + limit if offset + limit < total else None
    return {'total': total, 'notes': notes, 'nextOffset': nextOffset}


#
# Media thumbnails (SPEC 14)
#

def media_thumbnails(col, filenames, max_dim=320, image_format='jpeg', quality=70):
    """Pure read: encodes scaled-down copies to base64, writes nothing.

    PyQt6 is imported lazily so importing this module stays Qt-free; QImage
    load/scale/save needs no Q(Gui)Application on this build (probe-verified).
    """
    if not isinstance(filenames, list) or not all(isinstance(f, str) for f in filenames):
        raise Exception('invalid parameter: filenames: list of strings required')
    if isinstance(max_dim, bool) or not isinstance(max_dim, int) or max_dim < 1:
        raise Exception('invalid parameter: maxDim: must be >= 1')
    max_dim = min(max_dim, THUMBNAIL_DIM_CAP)
    if image_format not in THUMBNAIL_FORMATS:
        raise Exception('invalid parameter: format: jpeg or png required')
    if isinstance(quality, bool) or not isinstance(quality, int) or not (0 <= quality <= 100):
        raise Exception('invalid parameter: quality: int 0-100 required')
    if not filenames:
        return {'thumbnails': []}

    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PyQt6.QtGui import QImage

    mediaDir = col.media.dir()
    thumbnails = []
    for filename in filenames:
        if not filename or os.path.basename(filename) != filename:
            thumbnails.append({'filename': filename,
                               'error': 'invalid parameter: filenames: bare media filename required'})
            continue
        path = os.path.join(mediaDir, filename)
        if not os.path.isfile(path):
            thumbnails.append({'filename': filename,
                               'error': 'media file was not found: {}'.format(filename)})
            continue
        img = QImage(path)
        if img.isNull() or img.width() < 1 or img.height() < 1:
            thumbnails.append({'filename': filename,
                               'error': 'could not load image: {} (unsupported or corrupt format)'.format(filename)})
            continue
        # scale only when a side exceeds the cap: this conditional is the
        # never-upscale guarantee (QImage.scaled itself happily upscales)
        if img.width() > max_dim or img.height() > max_dim:
            img = img.scaled(max_dim, max_dim, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        ok = img.save(buf, image_format, quality if image_format == 'jpeg' else -1)
        buf.close()
        if not ok:
            thumbnails.append({'filename': filename,
                               'error': 'could not encode thumbnail as {}: {}'.format(image_format, filename)})
            continue
        thumbnails.append({
            'filename': filename,
            'data': base64.b64encode(bytes(ba)).decode('ascii'),
            'width': img.width(),
            'height': img.height(),
        })
    return {'thumbnails': thumbnails}


#
# Scheduler bulk ops (SPEC 16)
#

def _existing_cards(col, card_ids):
    """Dedupe card ids (first occurrence wins) and drop ids with no card,
    returning [(cid, queue)]. Read-only. Keeps backend behavior on unknown
    ids out of the contract entirely (SPEC 16)."""
    if not isinstance(card_ids, list) or not all(
            isinstance(cid, int) and not isinstance(cid, bool) for cid in card_ids):
        raise Exception('invalid parameter: cardIds: ints required')
    existing = []
    for cid in dict.fromkeys(card_ids):
        try:
            existing.append((cid, col.get_card(cid).queue))
        except NotFoundError:
            continue
    return existing


def bulk_suspend(col, card_ids, suspend=True):
    if not isinstance(suspend, bool):
        raise Exception('invalid parameter: suspend: boolean required')
    existing = _existing_cards(col, card_ids)

    if suspend:
        # suspending an already-suspended card is a no-op; buried cards DO
        # change (queue -2/-3 -> -1), so they count as pending
        pending = [cid for cid, queue in existing if queue != QUEUE_SUSPENDED]
    else:
        # the backend restore op unsuspends AND unburies: every negative
        # queue changes, so all of them count as pending (SPEC Deviation #8)
        pending = [cid for cid, queue in existing if queue < 0]
    if not pending:
        return {'changed': 0, 'undoEntry': None}

    target = col.add_custom_undo_entry(UNDO_BULK_SUSPEND)
    try:
        if suspend:
            # OpChangesWithCount: backend-authoritative changed count
            changed = col.sched.suspend_cards(pending).count
        else:
            # unsuspend returns plain OpChanges (no count); the pending
            # precheck is the changed count (SPEC Deviation #8)
            col.sched.unsuspend_cards(pending)
            changed = len(pending)
        col.merge_undo_entries(target)
    except Exception as e:
        _revert_batch(col, UNDO_BULK_SUSPEND)
        raise Exception('bulkSuspend failed (batch reverted): {}'.format(e))

    if not changed:
        # data no-op: pop the empty custom entry so the Undo menu stays clean
        _revert_batch(col, UNDO_BULK_SUSPEND)
        return {'changed': 0, 'undoEntry': None}
    return {'changed': changed, 'undoEntry': UNDO_BULK_SUSPEND}


def bulk_set_due_date(col, card_ids, days):
    if not isinstance(days, str) or not days:
        raise Exception('invalid parameter: days: string like "0" or "1-7" required')
    # pre-validate the backend grammar ("0", "5", "1-7", "3!", "1-7!") BEFORE
    # any undo entry exists: if InvalidInput fired after add_custom_undo_entry,
    # popping the empty entry via col.undo() would push a phantom Redo item
    # (SPEC 16.2 promises the undo stack is left untouched on a bad days string).
    # ASCII digits only: the backend regex accepts unicode digits but its int
    # parse then rejects them, so [0-9] is the true accepted alphabet.
    if not re.fullmatch(r'[0-9]+(?:-[0-9]+)?!?', days):
        raise Exception('invalid parameter: days: {}'.format(days))
    existing = _existing_cards(col, card_ids)
    if not existing:
        return {'changed': 0, 'undoEntry': None}
    ids = [cid for cid, _queue in existing]

    target = col.add_custom_undo_entry(UNDO_BULK_DUE)
    try:
        col.sched.set_due_date(ids, days)
        col.merge_undo_entries(target)
    except InvalidInput as e:
        # bad days string: the op never ran, pop the empty custom entry
        _revert_batch(col, UNDO_BULK_DUE)
        raise Exception('invalid parameter: days: {}'.format(e))
    except Exception as e:
        _revert_batch(col, UNDO_BULK_DUE)
        raise Exception('bulkSetDueDate failed (batch reverted): {}'.format(e))

    # set_due_date returns plain OpChanges (no count); it applies to every
    # existing card regardless of state (SPEC Deviation #8)
    return {'changed': len(ids), 'undoEntry': UNDO_BULK_DUE}


#
# Deck export (SPEC 17)
#

def export_deck_apkg(col, deck_name, out_path=None, include_scheduling=True,
                     include_media=True):
    if not isinstance(deck_name, str) or not deck_name:
        raise Exception('invalid parameter: deckName: string required')
    if out_path is not None and (not isinstance(out_path, str) or not out_path):
        raise Exception('invalid parameter: outPath: string required')
    if not isinstance(include_scheduling, bool):
        raise Exception('invalid parameter: includeScheduling: boolean required')
    if not isinstance(include_media, bool):
        raise Exception('invalid parameter: includeMedia: boolean required')
    did = col.decks.id_for_name(deck_name)
    if did is None:
        raise Exception('deck was not found: {}'.format(deck_name))

    if out_path is None:
        # sanitize: unicode word chars, dot, dash survive; '::' and anything
        # else collapse to single dashes
        stem = re.sub(r'[^\w.-]+', '-', deck_name).strip('-.') or 'deck'
        out_path = os.path.join(EXPORT_DEFAULT_DIR, '{}-{}.apkg'.format(
            stem, datetime.date.today().isoformat()))
    else:
        out_path = os.path.expanduser(out_path)
        # outPath must be a FILE path: a directory (or trailing slash) would
        # make splitext see no extension and the collision loop would write a
        # surprise sibling like '<dir>-2' (or a file literally named '-2')
        if os.path.isdir(out_path) or not os.path.basename(out_path):
            raise Exception(
                'invalid parameter: outPath: is a directory: {}'.format(out_path))
    outDir = os.path.dirname(out_path) or '.'
    if not os.path.isdir(outDir):
        raise Exception('output directory was not found: {}'.format(outDir))

    # never overwrite: append -2, -3, ... before the extension (race-free:
    # handlers are serialized on the main thread, SPEC 3.1)
    base, ext = os.path.splitext(out_path)
    serial = 2
    while os.path.exists(out_path):
        out_path = '{}-{}{}'.format(base, serial, ext)
        serial += 1

    options = anki.collection.ExportAnkiPackageOptions(
        with_scheduling=include_scheduling,
        # deck presets are NOT exported (matches Anki's own dialog default);
        # importing presets would mutate the receiving collection's config
        with_deck_configs=False,
        with_media=include_media,
        legacy=False,  # modern package format (Anki 2.1.50+)
    )
    notes = col.export_anki_package(out_path=out_path, options=options,
                                    limit=anki.collection.DeckIdLimit(did))
    return {'path': out_path, 'sizeBytes': os.path.getsize(out_path),
            'notesExported': notes}
