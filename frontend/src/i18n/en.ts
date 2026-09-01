/**
 * The English catalogue, and the contract every other locale must satisfy.
 *
 * `TranslationKey` is derived from this object, so a locale that misses a key or invents
 * one fails `tsc` rather than rendering a blank space in front of a reader.
 */

export const en = {
  'app.tagline': 'English video → editable German dub',
  'app.localBadge': 'Runs on this machine',
  'app.skipToContent': 'Skip to content',

  'nav.projects': 'Projects',
  'nav.help': 'How it works',
  'nav.about': 'About',

  'theme.label': 'Theme',
  'theme.light': 'Light',
  'theme.dark': 'Dark',
  'theme.system': 'System',

  'language.label': 'Interface language',
  // Stated wherever the language menu appears: the dub itself is not affected.
  'language.note': 'Changes this interface only. Dubs are always English to German.',

  'home.title': 'Turn an English video into a German dub',
  'home.subtitle': 'Paste a YouTube URL. Every segment stays editable and resumable.',
  'home.urlLabel': 'YouTube URL',
  'home.analyze': 'Analyze',
  'home.recent': 'Recent projects',
  'home.loading': 'Loading projects…',
  'home.emptyTitle': 'No projects yet',
  'home.emptyBody': 'Paste a video URL above to start your first dub.',
  'home.delete': 'Delete',
  'home.confirmDelete': 'Delete “{title}” and all of its generated files?',
  'home.degraded': 'This environment cannot produce a real dub yet.',
  'home.degradedHelp': 'Run {command} to see what is missing.',
  'home.newToThis': 'New here? Read how the pipeline works.',

  'home.stop': 'Stop',
  'home.stopHint': 'Stop this dub now. Finished stages are kept and you can resume later.',
  'home.reset': 'Delete everything',
  'home.resetHint':
    'Removes every project and all generated files from this machine. This cannot be undone.',
  'home.confirmReset':
    'Delete all {count} project(s) and every file they produced? This cannot be undone.',
  'home.resetDone': 'Everything was deleted.',
  'home.deleteHint': 'Delete this project and its files.',
  'home.busy': 'working',

  'voice.label': 'German narrator',
  'voice.play': 'Hear this voice',
  'voice.loading': 'Loading…',
  'voice.notDownloaded': 'downloads on first use',
  'voice.hint': 'Pick a voice, then press play to hear it before you start.',
  'voice.sampleFailed': 'That sample could not be played. The voice may still be downloading.',

  'project.analyze': 'Analyze source',
  'project.analyzeHint': "Reads the source's title, length and captions without downloading it.",
  'project.start': 'Create German dub',
  'project.startHint': 'Runs the whole pipeline. You can stop it at any time and resume later.',
  'project.cancel': 'Stop processing',
  'project.cancelHint':
    'Stops at the next safe point and terminates the tool currently running. Finished stages are kept.',
  'project.resume': 'Resume unfinished work',
  'project.resumeHint': 'Continues from the last stage that finished.',
  'project.download': 'Download',
  'project.downloadHint': 'The dubbed video, with the original audio kept as a second track.',

  'processing.title': 'Processing',
  'processing.percentComplete': '{percent}% complete',
  'processing.progressLabel': 'Dub progress',

  'segments.title': 'Review segments',
  'segments.subtitle': 'Select a row, correct one text field, and regenerate what follows.',
  'segments.loading': 'Loading segments…',
  'segments.total': '{count} total',
  'segments.approved': '{count} approved',
  'segments.flagged': '{count} flagged',
  'segments.failed': '{count} failed',
  'segments.time': 'Time',
  'segments.english': 'English',
  'segments.german': 'German',
  'segments.fit': 'Fit',
  'segments.notTranslated': 'Not translated',
  'segments.editLabel': 'Edit segment {number}',
  'segments.filterLabel': 'Show',
  'segments.filterAll': 'All',
  'segments.filterFlagged': 'Flagged',
  'segments.filterUnapproved': 'Needs review',
  'segments.filterFailed': 'Failed',
  'segments.noMatches': 'No segments match this filter.',
  'segments.showingCount': 'Showing {shown} of {total}',

  'help.title': 'How GermanDubI works',
  'help.lede':
    'You paste a link, the pipeline does the mechanical work, and you keep control of the German. Nothing is thrown away between stages: every intermediate result is saved, so a change re-runs only what depends on it.',
  'help.walkthroughTitle': 'The workflow, end to end',
  'help.step1Title': 'Paste a URL and press Analyze',
  'help.step1Body':
    'The source is inspected without downloading it, so you see the title, length and whether it has captions in a second or two.',
  'help.step2Title': 'Press Create German dub',
  'help.step2Body':
    'The pipeline downloads the media, transcribes the English, translates it, speaks the German, fits it to the original timing and mixes it back under the picture.',
  'help.step3Title': 'Watch it run, or come back later',
  'help.step3Body':
    'Progress is saved as it goes. Closing the tab or restarting the machine does not lose a run; it resumes from the last finished stage.',
  'help.step4Title': 'Review and correct the German',
  'help.step4Body':
    'Every segment is editable. Correct a translation and only that segment is spoken again, along with whatever depends on it.',
  'help.step5Title': 'Approve and export',
  'help.step5Body':
    'Approving every segment completes the project. The export keeps the original audio as a second track, plus German and English subtitles.',
  'help.stagesTitle': 'The sixteen stages',
  'help.stagesLede':
    'A run is a dependency graph rather than one long script. That is what lets a single stage be re-run after an edit.',
  'help.stage.probe': "Reads the source's details without downloading it",
  'help.stage.acquire': 'Downloads the video and any captions',
  'help.stage.normalize': 'Extracts the audio at a consistent rate',
  'help.stage.transcribe': 'Turns the English speech into text',
  'help.stage.align': 'Gives every word a position in time',
  'help.stage.segment': 'Groups the text into dubbing segments',
  'help.stage.separate': 'Splits voice from background, when available',
  'help.stage.translate': 'Translates each segment into German',
  'help.stage.prosody': "Measures the narrator's pace and pauses",
  'help.stage.synthesize': 'Speaks the German with a local voice',
  'help.stage.fit': 'Adjusts timing so the German fits its gap',
  'help.stage.assemble': 'Places every segment on one track',
  'help.stage.mix': 'Blends the German over the original audio',
  'help.stage.subtitle': 'Writes German and English subtitle files',
  'help.stage.qa': 'Checks the result for timing problems',
  'help.stage.export': 'Muxes everything into the final video',
  'help.timingTitle': 'How long it takes',
  'help.timingBody':
    'On a CPU-only machine a 40-minute video takes roughly 8 minutes, about a fifth of its running time. Speech recognition and synthesis dominate; the rest is mostly moving bytes.',
  'help.editTitle': 'What you can change',
  'help.editBody':
    'The German text of any segment. Everything downstream of your edit is recomputed and nothing upstream is touched, so correcting a name near the end does not re-transcribe the video.',
  'help.queueTitle': 'Adding a second video',
  'help.queueBody':
    'You can paste another URL at any time, including while a dub is running. One video is processed at a time and the rest wait their turn, so nothing competes for the machine and each project keeps its own files. A waiting project says so on its own page, with its position in the queue. Inspecting a source jumps ahead of a running dub, so a URL you have just pasted is analysed in seconds rather than after the dub finishes.',
  'help.logTitle': 'When something goes wrong',
  'help.logBody':
    'The server keeps a log. An unexpected failure shows a reference; search the log for it and the full story is there, including whatever the tools printed. The log survives closing the terminal.',
  'help.logAt': 'On this machine the log is at {path}.',
  'help.logInTerminal': 'This server logs to its terminal only, so keep that window open.',
  'help.privacyTitle': 'What leaves your machine',
  'help.privacyBody':
    'The source URL, so the video can be fetched. Nothing else. Recognition, translation and speech all run locally, and a provider that would send audio elsewhere is never selected unless you allow it.',

  'about.title': 'About GermanDubI',
  'about.lede':
    'A local-first workstation for turning an English video into an editable, synchronized German dub.',
  'about.projectTitle': 'Project',
  'about.author': 'Author',
  'about.license': 'Licence',
  'about.licenseBody': 'GPL-3.0-or-later. The full text is in the LICENSE file.',
  'about.repository': 'Source code',
  'about.version': 'Version',
  'about.apiVersion': 'API',
  'about.revision': 'Revision',
  'about.languages': 'Language pair',
  'about.buildTitle': 'This build',
  'about.providersTitle': 'Providers in use',
  'about.providersLede':
    'What is actually installed on this machine, read live rather than listed by hand.',
  'about.providerLocal': 'local',
  'about.providerNetwork': 'network',
  'about.providerReady': 'ready',
  'about.providerMissing': 'not installed',
  'about.toolsTitle': 'Built with',
  'about.toolsLede':
    'Each of these keeps its own licence; none is redistributed as part of this project.',
  'about.rightsTitle': 'Your responsibility',
  'about.rightsBody':
    'This software does not circumvent access controls or DRM. You are responsible for holding the rights to process and redistribute any source you use, and for holding authorization for any voice you reproduce.',

  'project.breadcrumb': 'Breadcrumb',
  'project.loading': 'Loading project…',
  'project.missingId': 'The project identifier is missing.',
  'project.by': 'by {uploader}',
  'project.captionsAutomatic': 'Automatic English captions',
  'project.captionsManual': 'Manual English captions',
  'project.captionsNone': 'Speech recognition required',
  'project.previewTitle': 'German preview',
  'project.previewBody': 'The export includes German and original audio tracks.',
  'project.downloadExport': 'Download export',
  'project.artifacts': '{count} current artifacts with provenance',

  // Badge text, kept lower case because that is how a status chip reads here.
  'state.new': 'new',
  'state.probing': 'probing',
  'state.ready': 'ready',
  'state.processing': 'processing',
  'state.review': 'review',
  'state.complete': 'complete',
  'state.failed': 'failed',
  'state.cancelled': 'cancelled',

  'jobStatus.pending': 'waiting',
  'jobStatus.queued': 'queued',
  'jobStatus.running': 'running',
  'jobStatus.succeeded': 'done',
  'jobStatus.failed': 'failed',
  'jobStatus.cancel_requested': 'stopping',
  'jobStatus.cancelled': 'stopped',
  'jobStatus.skipped': 'skipped',

  // The stage names the processing screen lists. The server sends an English label too;
  // the stage identifier is what this maps, so the list reads in the chosen language.
  'stage.probe': 'Inspecting source',
  'stage.acquire': 'Downloading media',
  'stage.normalize': 'Extracting audio',
  'stage.transcribe': 'Getting English transcript',
  'stage.align': 'Aligning word timing',
  'stage.segment': 'Creating dubbing segments',
  'stage.separate': 'Separating voice and background',
  'stage.translate': 'Translating to German',
  'stage.prosody': 'Analysing narration',
  'stage.synthesize': 'Synthesizing German speech',
  'stage.fit': 'Fitting speech to timing',
  'stage.assemble': 'Assembling German narration',
  'stage.mix': 'Mixing audio',
  'stage.subtitle': 'Writing subtitles',
  'stage.qa': 'Running quality checks',
  'stage.export': 'Exporting video',

  'editor.title': 'Segment {number}',
  'editor.sourceLabel': 'English transcript',
  'editor.translationLabel': 'German translation',
  'editor.saveSource': 'Save English & regenerate',
  'editor.saveTranslation': 'Save German & regenerate',
  'editor.resynthesize': 'Regenerate speech',
  'editor.retranslate': 'Translate again',
  'editor.approve': 'Approve',
  'review.unreviewed': 'unreviewed',
  'review.needs_attention': 'needs attention',
  'review.approved': 'approved',

  'flag.duration_overrun': 'runs long',
  'flag.time_stretched': 'time-stretched',
  'flag.synthesis_failed': 'speech failed',
  'flag.low_transcription_confidence': 'uncertain transcript',

  'queue.waiting': 'Waiting for another project to finish',
  'queue.position': 'Position {position} of {total} in the queue',
  'queue.next': 'Next in the queue',

  'error.title': 'Something went wrong',
  // What the browser shows when the server did not anticipate a failure. The reference and
  // the log path are the two things that turn "it broke" into something a person can act on.
  'error.reference': 'Reference {reference}',
  'error.logAt': 'The full details are in the server log: {path}',
  'error.logInTerminal': 'The full details are in the terminal running the server.',
  // A heading per error code. The server also sends a specific sentence, which is shown
  // underneath as-is: it is the diagnostic a user quotes when asking for help, and
  // duplicating the backend's whole message catalogue here would drift within a release.
  'error.code.internal_error': 'Something went wrong',
  'error.code.unknown_error': 'The server could not be reached',
  'error.code.domain_error': 'That cannot be done right now',
  'error.code.invalid_state_transition': 'Not possible in this state',
  'error.code.not_found': 'Not found',
  'error.code.configuration_error': 'Something is not configured',
  'error.code.resource_error': 'A required resource is unavailable',
  'error.code.provider_unavailable': 'A required component is not installed',
  'error.code.cancelled': 'Stopped',
  'error.code.source_validation_error': 'That source cannot be used',
  'error.code.source_acquisition_error': 'The source could not be downloaded',
  'error.code.media_processing_error': 'Processing the media failed',
  'error.code.caption_error': 'The captions could not be used',
  'error.code.transcription_error': 'Speech recognition failed',
  'error.code.alignment_error': 'Word timing failed',
  'error.code.translation_error': 'Translation failed',
  'error.code.separation_error': 'Separating voice and background failed',
  'error.code.synthesis_error': 'German speech synthesis failed',
  'error.code.duration_fit_error': 'The German speech would not fit',
  'error.code.mix_error': 'Mixing the audio failed',
  'error.code.export_error': 'Writing the final video failed',
  'notFound.title': 'Page not found',
  'notFound.back': 'Back to projects',
} as const;

export type TranslationKey = keyof typeof en;
export type Catalogue = Record<TranslationKey, string>;
