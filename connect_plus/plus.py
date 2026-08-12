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

import functools
import importlib
import inspect
import json
import os
import sys
import time
import uuid

import anki.collection
import anki.errors
import anki.notes
import aqt.gui_hooks

from . import core, util


def _signature_string(method):
    """Render a bound wrapper's signature as a JSON-flavored one-liner for
    plusInfo's actionDocs, e.g. "notes, atomic=true, dryRun=false" (bound
    methods already exclude self)."""
    parts = []
    for param in inspect.signature(method).parameters.values():
        if param.default is inspect.Parameter.empty:
            parts.append(param.name)
        else:
            try:
                default = json.dumps(param.default)
            except (TypeError, ValueError):
                default = repr(param.default)
            parts.append('{}={}'.format(param.name, default))
    return ', '.join(parts)


def plus_api():
    """@util.api() plus the SPEC 25 stable-error-code guarantee.

    Wraps the action so every exception leaving it is a core.PlusError whose
    str() is '[code] message'. core/plus raise PlusError directly with the
    right code; anything else is unexpected and leaves as '[internal] ' with
    the original message body unchanged, except two recognized boundaries:
    upstream self.collection()'s 'collection is not available' maps to
    [collection_unavailable] (retryable — open a profile), and a TypeError
    from the dispatch splat failing to bind the request's params to the
    action's real signature (unexpected/missing argument) maps to
    [invalid_param] — that one is a caller mistake, not an add-on bug.

    functools.wraps keeps the wrapped signature reachable (__wrapped__), so
    plusInfo's actionDocs still reflect the real parameter list.

    self is declared positional-only so a request whose params object carries
    a "self" key cannot fail bound-method binding BEFORE this wrapper runs
    (which would let the raw TypeError escape unprefixed); it lands in
    **kwargs instead, and the binding failure moves to the inner func(...)
    call, where the tb_next-is-None branch maps it to [invalid_param].
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, /, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except core.PlusError:
                raise
            except TypeError as e:
                if e.__traceback__ is not None and e.__traceback__.tb_next is None:
                    # raised AT our call expression (no deeper frame): the
                    # params failed to bind — unexpected keyword / missing
                    # required argument from the JSON request
                    raise core.PlusError('invalid_param', str(e)) from None
                raise core.PlusError('internal', str(e)) from e
            except Exception as e:
                if str(e) == 'collection is not available':
                    # upstream self.collection() before a profile is open
                    raise core.PlusError('collection_unavailable', str(e)) from e
                raise core.PlusError('internal', str(e)) from e
        return util.api()(wrapper)
    return decorator


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


    @plus_api()
    def bulkAddNotes(self, notes, atomic=True, allowDuplicates=False, dryRun=False,
                     undoLabel=None):
        if not isinstance(notes, list):
            raise core.PlusError('invalid_param', 'invalid parameter: notes: list required')
        if dryRun:
            # dry run writes NOTHING: media embedding stores files, so it is
            # skipped and fields are validated as submitted (SPEC 15)
            prepared = notes
        else:
            prepared = [self._plusEmbedNoteMedia(note) for note in notes]
        return core.bulk_add_notes(self.collection(), prepared, atomic=atomic,
                                   allow_duplicates=allowDuplicates, dry_run=dryRun,
                                   undo_label=undoLabel)


    @plus_api()
    def bulkUpdateNoteFields(self, notes, atomic=True, dryRun=False, diff=False,
                             maxPreview=20, undoLabel=None):
        return core.bulk_update_note_fields(self.collection(), notes, atomic=atomic,
                                            dry_run=dryRun, diff=diff,
                                            max_preview=maxPreview, undo_label=undoLabel)


    @plus_api()
    def bulkAddTags(self, noteIds, tags, atomic=True, dryRun=False, undoLabel=None):
        return core.bulk_add_tags(self.collection(), noteIds, tags, atomic=atomic,
                                  dry_run=dryRun, undo_label=undoLabel)


    @plus_api()
    def addImageOcclusionNote(self, image, occlusions, deckName, header='', backExtra='', tags=None, hideAllGuessOne=True, undoLabel=None):
        if not isinstance(image, dict):
            raise core.PlusError('invalid_param', 'invalid parameter: image: object required')
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
            hide_all_guess_one=hideAllGuessOne,
            undo_label=undoLabel
        )


    @plus_api()
    def getImageOcclusionNote(self, noteId):
        return core.get_image_occlusion_note(self.collection(), noteId)


    @plus_api()
    def updateImageOcclusionNote(self, noteId, occlusions=None, header=None, backExtra=None, tags=None, hideAllGuessOne=True, undoLabel=None):
        return core.update_image_occlusion_note(
            self.collection(),
            noteId,
            occlusions=occlusions,
            header=header,
            back_extra=backExtra,
            tags=tags,
            hide_all_guess_one=hideAllGuessOne,
            undo_label=undoLabel
        )


    @plus_api()
    def cropImage(self, filename, rect, noteIds=None, undoLabel=None):
        return core.crop_image(self.collection(), filename, rect, note_ids=noteIds,
                               undo_label=undoLabel)


    @plus_api()
    def cropImageOcclusionImage(self, noteId, rect, undoLabel=None):
        return core.crop_image_occlusion_image(self.collection(), noteId, rect,
                                               undo_label=undoLabel)


    @plus_api()
    def queryRevlog(self, cardIds=None, noteIds=None, deckName=None, sinceMs=None, untilMs=None, limit=5000, offset=0):
        return core.query_revlog(
            self.collection(),
            card_ids=cardIds,
            note_ids=noteIds,
            deck_name=deckName,
            since_ms=sinceMs,
            until_ms=untilMs,
            limit=limit,
            offset=offset
        )


    @plus_api()
    def createBackup(self, force=True):
        return core.create_backup(self.collection(), force=force)


    @plus_api()
    def renderCard(self, cardIds, format='html'):
        return core.render_card(self.collection(), cardIds, render_format=format)


    @plus_api()
    def notesSlim(self, query=None, noteIds=None, fields=None, stripHtml=True,
                  maxFieldLength=400, offset=0, limit=200):
        return core.notes_slim(
            self.collection(),
            query=query,
            note_ids=noteIds,
            fields=fields,
            strip_html=stripHtml,
            max_field_length=maxFieldLength,
            offset=offset,
            limit=limit
        )


    @plus_api()
    def mediaThumbnails(self, filenames, maxDim=320, format='jpeg', quality=70):
        return core.media_thumbnails(self.collection(), filenames, max_dim=maxDim,
                                     image_format=format, quality=quality)


    @plus_api()
    def mediaExists(self, filenames):
        return core.media_exists(self.collection(), filenames)


    @plus_api()
    def storeMediaFilesBulk(self, files):
        return core.store_media_files_bulk(self.collection(), files)


    @plus_api()
    def bulkSuspend(self, cardIds, suspend=True, undoLabel=None):
        return core.bulk_suspend(self.collection(), cardIds, suspend=suspend,
                                 undo_label=undoLabel)


    @plus_api()
    def bulkSetDueDate(self, cardIds, days, undoLabel=None):
        return core.bulk_set_due_date(self.collection(), cardIds, days,
                                      undo_label=undoLabel)


    @plus_api()
    def exportDeckApkg(self, deckName, outPath=None, includeScheduling=True, includeMedia=True):
        return core.export_deck_apkg(
            self.collection(),
            deckName,
            out_path=outPath,
            include_scheduling=includeScheduling,
            include_media=includeMedia
        )


    @plus_api()
    def checkDeckIntegrity(self, deckName, includeOrphanMedia=False):
        return core.check_deck_integrity(self.collection(), deckName,
                                         include_orphan_media=includeOrphanMedia)


    @plus_api()
    def bulkReplaceInFields(self, query=None, noteIds=None, field=None, find=None,
                            replace=None, isRegex=False, caseSensitive=True,
                            dryRun=False, atomic=True, maxPreview=20, undoLabel=None):
        return core.bulk_replace_in_fields(
            self.collection(),
            query=query,
            note_ids=noteIds,
            field=field,
            find=find,
            replace=replace,
            is_regex=isRegex,
            case_sensitive=caseSensitive,
            dry_run=dryRun,
            atomic=atomic,
            max_preview=maxPreview,
            undo_label=undoLabel
        )


    #
    # Sync (SPEC 18): async job + polling; normal sync only, zero dialogs.
    # The job dict is mutated ONLY on the Qt main thread: HTTP handlers run
    # there (SPEC 3.1) and taskman marshals on_done there (aqt/taskman.py:86-88).
    #

    def _plusSyncJob(self):
        # PlusMixin has no __init__, so the job slot is created lazily
        job = getattr(self, '_plusSyncJobState', None)
        if job is None:
            job = {'state': 'idle', 'startedMs': None, 'result': None, 'error': None}
            self._plusSyncJobState = job
        return job


    def _plusSyncWatchMedia(self, job):
        # media_syncing -> done|error. col.media_sync_status() take()s and
        # join()s the FINISHED backend media task (rslib/src/backend/sync.rs),
        # so a media-sync failure raises exactly ONCE, to the first caller
        # that observes it (probe-verified: first call raises, every later
        # call returns active=False cleanly). aqt's
        # mw.media_syncer.start_monitoring() is deliberately NOT used: its
        # monitor thread would consume that single raise before we could
        # (making media_sync_failed unreachable) and then pop a show_info
        # dialog on failure (aqt/mediasync.py:89-96) — this add-on is zero
        # dialogs. Instead plus owns the error: this watcher mirrors aqt's
        # monitor loop (aqt/mediasync.py:57-65) and lets the failure raise
        # into its future. media_sync_did_start_or_stop is fired around the
        # watch so the toolbar sync icon still tracks.
        mw = self.window()
        collection = mw.col
        if collection is None:
            # cannot verify the media phase without a collection; an
            # unverified media sync is never reported 'done'
            job['state'] = 'error'
            job['error'] = {'code': 'media_sync_failed',
                            'message': 'collection closed before the media '
                                       'sync could be verified'}
            return
        aqt.gui_hooks.media_sync_did_start_or_stop(True)

        def watch():
            # worker thread (uses_collection=False: media status polling
            # must not queue behind collection ops)
            while True:
                resp = collection.media_sync_status()  # raises on failure
                if not resp.active:
                    return
                time.sleep(0.25)

        def onWatchDone(future):
            # main thread (marshalled by taskman)
            try:
                future.result()
            except Exception as err:
                job['state'] = 'error'
                job['error'] = {'code': 'media_sync_failed',
                                'message': str(err)}
            else:
                job['state'] = 'done'
            aqt.gui_hooks.media_sync_did_start_or_stop(False)

        mw.taskman.run_in_background(watch, onWatchDone, uses_collection=False)


    def _plusSyncFinishGui(self):
        # post-sync bookkeeping, mirroring aqt/sync.py:105-125 and
        # aqt/main.py:1098-1111 (incl. _refresh_after_sync) — runs on error
        # paths too, exactly like aqt
        mw = self.window()
        if mw.col is not None:
            mw.col.models._clear_cache()
        aqt.gui_hooks.sync_did_finish()
        if mw.col is not None:
            mw.reset()
            mw.toolbar.redraw()
            mw.flags.require_refresh()


    def _plusSyncDone(self, future, syncMedia):
        # on_done: main thread (marshalled by taskman)
        mw = self.window()
        job = self._plusSyncJob()
        if mw.col is not None:
            mw.col._load_scheduler()  # scheduler version may have changed
        try:
            out = future.result()
        except Exception as err:
            code = core.classify_sync_error(err)
            if code == 'auth_failed':
                # mirror aqt.sync.handle_sync_error: stale keys are dropped
                mw.pm.clear_sync_auth()
            job['state'] = 'error'
            job['error'] = {'code': code, 'message': str(err)}
            self._plusSyncFinishGui()
            return

        mw.pm.set_host_number(out.host_number)
        if out.new_endpoint:
            mw.pm.set_current_sync_url(out.new_endpoint)
        job['result'] = {'serverMessage': out.server_message,
                         'hostNumber': out.host_number}
        if out.required != out.NO_CHANGES:
            # a full sync is NEVER run unattended (SPEC 18, Deviation #9d)
            job['state'] = 'error'
            job['error'] = {
                'code': 'full_sync_required',
                'message': 'server requires {}; refusing to run a full sync '
                           'unattended - resolve it in Anki'.format(
                               core.SYNC_COLLECTION_REQUIRED.get(out.required, out.required)),
            }
        elif syncMedia:
            # sync_collection already started the backend media sync; watch
            # it ourselves — plus must be the single consumer of the one-shot
            # failure signal (see _plusSyncWatchMedia)
            job['state'] = 'media_syncing'
            self._plusSyncWatchMedia(job)
        else:
            job['state'] = 'done'
        self._plusSyncFinishGui()


    @plus_api()
    def syncNow(self):
        mw = self.window()
        if mw.col is None:
            return {'started': False, 'reason': 'collection_unavailable'}
        auth = mw.pm.sync_auth()
        if auth is None:
            return {'started': False, 'reason': 'not_logged_in'}
        job = self._plusSyncJob()
        if job['state'] in ('syncing', 'media_syncing'):
            return {'started': False, 'reason': 'already_syncing'}
        if mw.media_syncer.is_syncing():
            # aqt's own auto/periodic media sync owns the media queue:
            # state, not an error (SPEC 18.1)
            return {'started': False, 'reason': 'media_sync_in_progress'}

        syncMedia = mw.pm.media_syncing_enabled()
        collection = mw.col
        job.update(state='syncing', startedMs=int(time.time() * 1000),
                   result=None, error=None)
        aqt.gui_hooks.sync_will_start()
        mw.taskman.run_in_background(
            lambda: collection.sync_collection(auth, syncMedia),
            lambda future: self._plusSyncDone(future, syncMedia))
        return {'started': True, 'mediaSync': syncMedia}


    @plus_api()
    def syncStatus(self, localOnly=False, timeoutSecs=8):
        if not isinstance(localOnly, bool):
            raise core.PlusError('invalid_param', 'invalid parameter: localOnly: boolean required')
        if isinstance(timeoutSecs, bool) or not isinstance(timeoutSecs, int) \
                or not (1 <= timeoutSecs <= 300):
            raise core.PlusError('invalid_param', 'invalid parameter: timeoutSecs: int 1-300 required')

        mw = self.window()
        job = self._plusSyncJob()
        auth = mw.pm.sync_auth()
        status = {
            'loggedIn': auth is not None,
            'job': dict(job),
            'mediaSyncing': mw.media_syncer.is_syncing(),
            'mediaSecondsSinceLastSync': mw.media_syncer.seconds_since_last_sync(),
            'lastSyncMs': None,
            'modMs': None,
            'required': None,
        }
        if job['state'] == 'syncing':
            # the backend holds the collection lock for the whole sync: any
            # col/col.db touch here would block the Qt main thread until the
            # sync finished (SPEC 18.2, Deviation #9b)
            return status

        collection = mw.col
        local = None
        if collection is not None:
            local = core.local_sync_dirty(collection)
            status['lastSyncMs'] = local['lastSyncMs']
            status['modMs'] = local['modMs']
        if auth is None:
            status['required'] = 'not_logged_in'
            return status
        if collection is None:
            status['required'] = 'error'
            return status
        if localOnly:
            status['required'] = 'normal_sync' if local['dirty'] else 'unknown_no_network'
            return status

        try:
            resp = collection.sync_status(core.bounded_sync_auth(auth, timeoutSecs))
        except Exception as err:
            code = core.classify_sync_error(err)
            # passive probe: NEVER clears auth (mirrors aqt get_sync_status,
            # Deviation #9a); 'aborted' has no place in required (#9c)
            status['required'] = code if code in ('offline', 'auth_failed') else 'error'
            return status
        if resp.new_endpoint:
            mw.pm.set_current_sync_url(resp.new_endpoint)
        status['required'] = core.SYNC_STATUS_REQUIRED.get(resp.required, 'error')
        return status


    #
    # AnkiHub suggestion bridge (SPEC 19): reuses the installed AnkiHub
    # add-on's own suggestion functions — nothing AnkiHub is re-implemented
    # here. Deliberately NO bulk suggestion action (etiquette guardrail).
    # The suggest actions run synchronously on the Qt main thread, the same
    # context as the add-on's own single-note dialog flow
    # (gui/suggestion_dialog.py:339-391). The stored AnkiHub token is NEVER
    # read — only settings.config.is_logged_in().
    #

    def _plusAnkiHubVersion(self):
        # manifest.json 'version', falling back to the VERSION file
        try:
            folder = self.window().addonManager.addonsFolder(core.ANKIHUB_ADDON_PACKAGE)
        except Exception:
            return None
        try:
            with open(os.path.join(folder, 'manifest.json'), encoding='utf-8') as handle:
                version = json.load(handle).get('version')
            if isinstance(version, str) and version:
                return version
        except Exception:
            pass
        try:
            with open(os.path.join(folder, 'VERSION'), encoding='utf-8') as handle:
                return handle.read().strip() or None
        except Exception:
            return None


    def _plusAnkiHubIncompatible(self, problems):
        raise core.PlusError(
            'incompatible_ankihub_addon',
            'INCOMPATIBLE_ANKIHUB_ADDON: installed AnkiHub add-on version {} '
            'does not match what this bridge was built against (tested: {}): '
            '{}'.format(self._plusAnkiHubVersion(),
                        core.ANKIHUB_TESTED_ADDON_VERSION, '; '.join(problems)))


    def _plusAnkiHubImport(self):
        # Access the add-on modules Anki has ALREADY loaded. When the package
        # is in sys.modules, import_module is a cached no-op; when it is not
        # (add-on enabled without a restart), importing it ourselves would run
        # its entry_point (real AnkiHub sync machinery) — never attempted.
        pkg = core.ANKIHUB_ADDON_PACKAGE
        manager = self.window().addonManager
        if pkg not in manager.allAddons():
            raise core.PlusError('incompatible_ankihub_addon',
                                 'ANKIHUB_ADDON_MISSING: the AnkiHub add-on ({}) '
                                 'is not installed'.format(pkg))
        if not manager.isEnabled(pkg):
            raise core.PlusError('incompatible_ankihub_addon',
                                 'ANKIHUB_ADDON_DISABLED: the AnkiHub add-on is '
                                 'installed but disabled')
        if pkg not in sys.modules:
            raise core.PlusError('incompatible_ankihub_addon',
                                 'ANKIHUB_ADDON_DISABLED: the AnkiHub add-on is '
                                 'enabled but was not loaded this session - '
                                 'restart Anki')
        modules = {}
        try:
            for alias, name in (('suggestions', '.main.suggestions'),
                                ('models', '.ankihub_client.models'),
                                ('client', '.ankihub_client.ankihub_client'),
                                ('settings', '.settings'),
                                ('db', '.db'),
                                ('media_sync', '.gui.media_sync')):
                modules[alias] = importlib.import_module(pkg + name)
        except Exception as err:
            self._plusAnkiHubIncompatible(['import failed: {}'.format(err)])
        return modules


    def _plusAnkiHubProblems(self, modules):
        # feature detection before every call: inspect.signature on every
        # function this bridge passes kwargs to, plus the enums/singletons it
        # reads. Empty list = compatible.
        problems = []
        for name in sorted(core.ANKIHUB_REQUIRED_SIGNATURES):
            fn = getattr(modules['suggestions'], name, None)
            if fn is None:
                problems.append('main.suggestions.{} is missing'.format(name))
                continue
            try:
                params = list(inspect.signature(fn).parameters)
            except (TypeError, ValueError):
                problems.append('main.suggestions.{} has an unreadable '
                                'signature'.format(name))
                continue
            missing = core.ankihub_missing_params(params, name)
            if missing:
                problems.append('main.suggestions.{} lacks parameter(s): '
                                '{}'.format(name, ', '.join(missing)))
        suggestionType = getattr(modules['models'], 'SuggestionType', None)
        if suggestionType is None:
            problems.append('models.SuggestionType is missing')
        else:
            wireValues = set()
            for member in suggestionType:
                value = member.value[0] if isinstance(member.value, tuple) else member.value
                wireValues.add(value)
            missingTypes = sorted(set(core.ANKIHUB_CHANGE_TYPES) - wireValues)
            if missingTypes:
                problems.append('SuggestionType lost wire value(s): '
                                '{}'.format(', '.join(missingTypes)))
        results = getattr(modules['suggestions'], 'ChangeSuggestionResult', None)
        if results is None:
            problems.append('main.suggestions.ChangeSuggestionResult is missing')
        else:
            memberNames = {member.name for member in results}
            missingResults = sorted(set(core.ANKIHUB_CHANGE_RESULTS) - memberNames)
            if missingResults:
                problems.append('ChangeSuggestionResult lost member(s): '
                                '{}'.format(', '.join(missingResults)))
        for attr in ('AnkiHubHTTPError', 'AnkiHubRequestException'):
            if getattr(modules['client'], attr, None) is None:
                problems.append('ankihub_client.{} is missing'.format(attr))
        mediaSync = getattr(modules['media_sync'], 'media_sync', None)
        if mediaSync is None or not callable(getattr(mediaSync, 'start_media_upload', None)):
            problems.append('gui.media_sync.media_sync.start_media_upload is missing')
        config = getattr(modules['settings'], 'config', None)
        if config is None or not callable(getattr(config, 'is_logged_in', None)):
            problems.append('settings.config.is_logged_in is missing')
        elif not hasattr(config, 'anking_deck_id'):
            # read unguarded by the AnKing SOURCE_REQUIRED gate in
            # ankihubSuggestNoteUpdate (None is a legitimate value there, so
            # only absence is a problem)
            problems.append('settings.config.anking_deck_id is missing')
        database = getattr(modules['db'], 'ankihub_db', None)
        for name in ('ankihub_nid_for_anki_nid', 'ankihub_did_for_anki_nid',
                     'ankihub_did_for_note_type'):
            if database is None or not callable(getattr(database, name, None)):
                problems.append('db.ankihub_db.{} is missing'.format(name))
        return problems


    def _plusAnkiHubModules(self):
        modules = self._plusAnkiHubImport()
        problems = self._plusAnkiHubProblems(modules)
        if problems:
            self._plusAnkiHubIncompatible(problems)
        return modules


    def _plusAnkiHubSuggestionType(self, modules, wireValue):
        for member in modules['models'].SuggestionType:
            value = member.value[0] if isinstance(member.value, tuple) else member.value
            if value == wireValue:
                return member
        self._plusAnkiHubIncompatible(
            ["SuggestionType has no wire value '{}'".format(wireValue)])


    def _plusAnkiHubNote(self, note):
        if isinstance(note, bool) or not isinstance(note, int):
            raise core.PlusError('invalid_param', 'invalid parameter: note: int note id required')
        try:
            return self.collection().get_note(anki.notes.NoteId(note))
        except anki.errors.NotFoundError:
            raise core.PlusError('not_found', 'note was not found: {}'.format(note))


    def _plusAnkiHubLoginCheck(self, modules):
        if not modules['settings'].config.is_logged_in():
            # local logged-out state -> not_logged_in; a server 401 (stored
            # token rejected) maps to auth_failed instead (SPEC 25)
            raise core.PlusError('not_logged_in',
                                 'ANKIHUB_NOT_LOGGED_IN: log in through the '
                                 'AnkiHub add-on first')


    def _plusAnkiHubHttpError(self, err):
        try:
            body = err.response.json()
        except Exception:
            body = (err.response.text or '')[:500]
        code, message = core.map_ankihub_http_error(err.response.status_code, body)
        # message keeps the SPEC 19 taxonomy code verbatim; the SPEC 25
        # machine prefix is layered on top via ANKIHUB_CODE_TO_PLUS_CODE
        return core.PlusError(core.ANKIHUB_CODE_TO_PLUS_CODE[code],
                              '{}: {}'.format(code, message))


    @plus_api()
    def ankihubStatus(self):
        # read-only probe: NEVER network, never raises for a missing/disabled
        # add-on, never imports an add-on Anki did not load itself
        pkg = core.ANKIHUB_ADDON_PACKAGE
        manager = self.window().addonManager
        installed = pkg in manager.allAddons()
        enabled = bool(installed and manager.isEnabled(pkg))
        status = {
            'installed': installed,
            'enabled': enabled,
            'loggedIn': False,
            'addonVersion': self._plusAnkiHubVersion() if installed else None,
            'testedAddonVersion': core.ANKIHUB_TESTED_ADDON_VERSION,
            'appUrl': None,
            'decks': [],
            'compatible': False,
        }
        if not enabled or pkg not in sys.modules:
            return status
        try:
            modules = self._plusAnkiHubImport()
        except Exception as err:
            status['problems'] = [str(err)]
            return status
        problems = self._plusAnkiHubProblems(modules)
        status['compatible'] = not problems
        if problems:
            status['problems'] = problems
        try:
            config = modules['settings'].config
            status['loggedIn'] = bool(config.is_logged_in())
            status['appUrl'] = config.app_url
            ankingId = config.anking_deck_id
            for ankihubDeckId in config.deck_ids():
                deck = config.deck_config(ankihubDeckId)
                if deck is None:
                    continue
                relation = getattr(deck, 'user_relation', None)
                status['decks'].append({
                    'ankihubDeckId': str(ankihubDeckId),
                    'ankiDeckId': int(deck.anki_id),
                    'name': deck.name,
                    'userRelation': getattr(relation, 'value', relation),
                    'isAnkingDeck': ankihubDeckId == ankingId,
                })
        except Exception as err:
            status['compatible'] = False
            status.setdefault('problems', []).append(
                'config read failed: {}'.format(err))
        return status


    @plus_api()
    def ankihubSuggestNoteUpdate(self, note, changeType, rationale, source=None,
                                 autoAccept=False):
        if not isinstance(autoAccept, bool):
            raise core.PlusError('invalid_param', 'invalid parameter: autoAccept: boolean required')
        changeType = core.validate_ankihub_change_type(changeType)
        core.validate_ankihub_rationale(rationale)
        modules = self._plusAnkiHubModules()
        self._plusAnkiHubLoginCheck(modules)
        ankiNote = self._plusAnkiHubNote(note)
        database = modules['db'].ankihub_db
        if database.ankihub_nid_for_anki_nid(ankiNote.id) is None:
            raise core.PlusError('not_found',
                                 'NOT_AN_ANKIHUB_NOTE: note {} is not on AnkiHub '
                                 '(or is deleted there) - use ankihubSuggestNewNote '
                                 'for brand-new notes'.format(note))
        deckId = database.ankihub_did_for_anki_nid(ankiNote.id)
        forAnking = (deckId is not None
                     and deckId == modules['settings'].config.anking_deck_id)
        comment = core.ankihub_comment_for_update(rationale, changeType, source,
                                                  forAnking)
        suggestionType = self._plusAnkiHubSuggestionType(modules, changeType)
        client = modules['client']
        try:
            # synchronous, main thread — mirrors the add-on's own dialog flow;
            # side effect: newly-added media is content-hash renamed across
            # the collection before background S3 upload (SPEC 19)
            result = modules['suggestions'].suggest_note_update(
                note=ankiNote,
                change_type=suggestionType,
                comment=comment,
                media_upload_cb=modules['media_sync'].media_sync.start_media_upload,
                auto_accept=autoAccept,
            )
        except client.AnkiHubHTTPError as err:
            raise self._plusAnkiHubHttpError(err)
        except client.AnkiHubRequestException as err:
            raise core.PlusError('network_error', 'NETWORK_ERROR: {}'.format(err))
        return {'result': core.map_ankihub_change_result(result.name),
                'comment': comment}


    def _plusAnkiHubResubmit(self, modules, err, ankiNote, targetDeck, comment,
                             autoAccept, allowResubmit):
        # duplicate-anki_id 400 -> resubmit as a change suggestion, mirroring
        # the add-on's own conflict dialog (suggestion_dialog.py:208-228:
        # change type UPDATED_CONTENT, same comment). Returns the action
        # result, or None when this is not that conflict (caller then maps
        # the original error generically).
        if err.response.status_code != 400:
            return None
        try:
            body = err.response.json()
        except Exception:
            return None
        parsed = modules['suggestions'].parse_duplicate_anki_id_error(body)
        if parsed is None:
            return None
        conflictingId, wasDeleted = parsed
        if wasDeleted:
            raise core.PlusError('not_found',
                                 'NOTE_DELETED_ON_ANKIHUB: this note was deleted '
                                 'on AnkiHub - no new suggestions can be made for it')
        if conflictingId is None or not allowResubmit:
            return None
        client = modules['client']
        try:
            result = modules['suggestions'].resubmit_new_note_as_change_suggestion(
                note=ankiNote,
                ah_did=targetDeck,
                conflicting_ah_nid=conflictingId,
                change_type=self._plusAnkiHubSuggestionType(modules, 'updated_content'),
                comment=comment,
                auto_accept=autoAccept,
            )
        except client.AnkiHubHTTPError as resubmitErr:
            raise self._plusAnkiHubHttpError(resubmitErr)
        except client.AnkiHubRequestException as resubmitErr:
            raise core.PlusError('network_error', 'NETWORK_ERROR: {}'.format(resubmitErr))
        return {'result': core.map_ankihub_change_result(result.name),
                'resubmittedAsChange': True}


    @plus_api()
    def ankihubSuggestNewNote(self, note, rationale, source=None, deckId=None,
                              autoAccept=False, resubmitAsChangeOnDuplicate=True):
        if not isinstance(autoAccept, bool):
            raise core.PlusError('invalid_param', 'invalid parameter: autoAccept: boolean required')
        if not isinstance(resubmitAsChangeOnDuplicate, bool):
            raise core.PlusError('invalid_param', 'invalid parameter: resubmitAsChangeOnDuplicate: '
                            'boolean required')
        core.validate_ankihub_rationale(rationale)
        modules = self._plusAnkiHubModules()
        self._plusAnkiHubLoginCheck(modules)
        ankiNote = self._plusAnkiHubNote(note)
        database = modules['db'].ankihub_db
        if database.ankihub_nid_for_anki_nid(ankiNote.id) is not None:
            raise core.PlusError('validation_error',
                                 'VALIDATION_ERROR: note {} is already on AnkiHub '
                                 '- use ankihubSuggestNoteUpdate'.format(note))
        if deckId is not None:
            if not isinstance(deckId, str):
                raise core.PlusError('invalid_param', 'invalid parameter: deckId: AnkiHub deck uuid '
                                'string required')
            try:
                targetDeck = uuid.UUID(deckId)
            except ValueError:
                raise core.PlusError('invalid_param', 'invalid parameter: deckId: AnkiHub deck uuid '
                                'string required')
        else:
            targetDeck = database.ankihub_did_for_note_type(ankiNote.mid)
            if targetDeck is None:
                raise core.PlusError('not_found',
                                     "NOT_AN_ANKIHUB_NOTE: the note's notetype is "
                                     'not linked to any AnkiHub deck - pass deckId '
                                     'explicitly')
        comment = core.ankihub_comment_for_new_note(rationale, source)
        if modules['suggestions'].has_empty_first_field(ankiNote):
            # mirrors the dialog's pre-submit check (suggestion_dialog.py:368)
            return {'result': 'emptyFirstField', 'resubmittedAsChange': False}
        client = modules['client']
        try:
            submitted = modules['suggestions'].suggest_new_note(
                note=ankiNote,
                comment=comment,
                ankihub_did=targetDeck,
                media_upload_cb=modules['media_sync'].media_sync.start_media_upload,
                auto_accept=autoAccept,
            )
        except client.AnkiHubHTTPError as err:
            handled = self._plusAnkiHubResubmit(
                modules, err, ankiNote, targetDeck, comment, autoAccept,
                resubmitAsChangeOnDuplicate)
            if handled is not None:
                return handled
            raise self._plusAnkiHubHttpError(err)
        except client.AnkiHubRequestException as err:
            raise core.PlusError('network_error', 'NETWORK_ERROR: {}'.format(err))
        return {'result': 'success' if submitted else 'noChanges',
                'resubmittedAsChange': False}


    @plus_api()
    def plusInfo(self):
        # actionDocs = the discoverability surface (SPEC 4.9): one-line summary
        # from core.PLUS_ACTION_SUMMARIES + params read live off the wrapper
        # signatures at call time. No collection access — plusInfo must keep
        # working before a profile is open.
        actionDocs = {}
        for name in core.PLUS_ACTIONS:
            actionDocs[name] = {
                'summary': core.PLUS_ACTION_SUMMARIES.get(name, ''),
                'params': _signature_string(getattr(self, name)),
            }
        return {
            'name': 'AnkiConnect Plus',
            'version': core.PLUS_VERSION,
            'apiVersion': util.setting('apiVersion'),
            'actions': list(core.PLUS_ACTIONS),
            'actionDocs': actionDocs,
            # named call patterns callers repeatedly failed to discover from
            # per-action docs alone (SPEC 4.9, revision 10)
            'recipes': [dict(recipe) for recipe in core.PLUS_RECIPES],
            'docs': {
                'plus': core.DOCS_PLUS,
                'upstream': core.DOCS_UPSTREAM,
                'upstreamSource': core.DOCS_UPSTREAM_SOURCE,
            },
        }
