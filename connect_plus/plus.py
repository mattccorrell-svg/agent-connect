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

import anki.collection
import anki.notes

from . import core, util


#
# Plus actions
#

class PlusMixin:
    def _plusEmbedNoteMedia(self, note):
        if not isinstance(note, dict):
            return note
        if not any(key in note for key in ('audio', 'video', 'picture')):
            return note

        collection = self.collection()
        modelName = note.get('modelName')
        model = collection.models.by_name(modelName) if isinstance(modelName, str) and modelName else None
        if model is None:
            return note

        fields = note.get('fields') or {}
        if not isinstance(fields, dict):
            # pass through untouched so core reports the validation skip
            return note
        ankiNote = anki.notes.Note(collection, model)
        for name, value in fields.items():
            if name in ankiNote and isinstance(value, str):
                ankiNote[name] = value
        self.addMediaFromNote(ankiNote, note)

        prepared = {key: value for key, value in note.items() if key not in ('audio', 'video', 'picture')}
        preparedFields = dict(fields)
        for name in ankiNote.keys():
            if name in preparedFields:
                # never fold back over a non-string original: core must still
                # see it and report 'string required' instead of '' data loss
                if isinstance(preparedFields[name], str):
                    preparedFields[name] = ankiNote[name]
            elif ankiNote[name]:
                preparedFields[name] = ankiNote[name]
        prepared['fields'] = preparedFields
        return prepared


    @util.api()
    def bulkAddNotes(self, notes, atomic=True, allowDuplicates=False):
        if not isinstance(notes, list):
            raise Exception('invalid parameter: notes: list required')
        prepared = [self._plusEmbedNoteMedia(note) for note in notes]
        return core.bulk_add_notes(self.collection(), prepared, atomic=atomic, allow_duplicates=allowDuplicates)


    @util.api()
    def bulkUpdateNoteFields(self, notes, atomic=True):
        return core.bulk_update_note_fields(self.collection(), notes, atomic=atomic)


    @util.api()
    def bulkAddTags(self, noteIds, tags, atomic=True):
        return core.bulk_add_tags(self.collection(), noteIds, tags, atomic=atomic)


    @util.api()
    def addImageOcclusionNote(self, image, occlusions, deckName, header='', backExtra='', tags=None, hideAllGuessOne=True):
        if not isinstance(image, dict):
            raise Exception('invalid parameter: image: object required')
        return core.add_image_occlusion_note(
            self.collection(),
            image_path=image.get('path'),
            image_data_b64=image.get('data'),
            image_filename=image.get('filename'),
            occlusions=occlusions,
            header=header,
            back_extra=backExtra,
            tags=tags,
            deck_name=deckName,
            hide_all_guess_one=hideAllGuessOne
        )


    @util.api()
    def getImageOcclusionNote(self, noteId):
        return core.get_image_occlusion_note(self.collection(), noteId)


    @util.api()
    def updateImageOcclusionNote(self, noteId, occlusions=None, header=None, backExtra=None, tags=None, hideAllGuessOne=True):
        return core.update_image_occlusion_note(
            self.collection(),
            noteId,
            occlusions=occlusions,
            header=header,
            back_extra=backExtra,
            tags=tags,
            hide_all_guess_one=hideAllGuessOne
        )


    @util.api()
    def cropImage(self, filename, rect, noteIds=None):
        return core.crop_image(self.collection(), filename, rect, note_ids=noteIds)


    @util.api()
    def cropImageOcclusionImage(self, noteId, rect):
        return core.crop_image_occlusion_image(self.collection(), noteId, rect)


    @util.api()
    def queryRevlog(self, cardIds=None, noteIds=None, deckName=None, sinceMs=None, untilMs=None, limit=5000):
        return core.query_revlog(
            self.collection(),
            card_ids=cardIds,
            note_ids=noteIds,
            deck_name=deckName,
            since_ms=sinceMs,
            until_ms=untilMs,
            limit=limit
        )


    @util.api()
    def createBackup(self, force=True):
        return core.create_backup(self.collection(), force=force)


    @util.api()
    def plusInfo(self):
        return {
            'name': 'AnkiConnect Plus',
            'version': core.PLUS_VERSION,
            'apiVersion': util.setting('apiVersion'),
            'actions': list(core.PLUS_ACTIONS),
            'docs': {
                'plus': core.DOCS_PLUS,
                'upstream': core.DOCS_UPSTREAM,
                'upstreamSource': core.DOCS_UPSTREAM_SOURCE,
            },
        }
