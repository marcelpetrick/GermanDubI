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

  'voice.label': 'German narrator',
  'voice.play': 'Hear this voice',
  'voice.loading': 'Loading…',
  'voice.notDownloaded': 'downloads on first use',
  'voice.hint': 'Pick a voice, then press play to hear it before you start.',
  'voice.sampleFailed': 'That sample could not be played. The voice may still be downloading.',

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

  'error.title': 'Something went wrong',
  'notFound.title': 'Page not found',
  'notFound.back': 'Back to projects',
} as const;

export type TranslationKey = keyof typeof en;
export type Catalogue = Record<TranslationKey, string>;
