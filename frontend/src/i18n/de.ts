import type { Catalogue } from './en';

export const de: Catalogue = {
  'app.tagline': 'Englisches Video → bearbeitbare deutsche Synchronfassung',
  'app.localBadge': 'Läuft auf diesem Rechner',
  'app.skipToContent': 'Zum Inhalt springen',

  'nav.projects': 'Projekte',
  'nav.help': 'So funktioniert es',
  'nav.about': 'Über',

  'theme.label': 'Darstellung',
  'theme.light': 'Hell',
  'theme.dark': 'Dunkel',
  'theme.system': 'System',

  'language.label': 'Sprache der Oberfläche',
  'language.note':
    'Ändert nur diese Oberfläche. Synchronisiert wird immer von Englisch nach Deutsch.',

  'home.title': 'Aus einem englischen Video eine deutsche Synchronfassung machen',
  'home.subtitle':
    'YouTube-Link einfügen. Jedes Segment bleibt bearbeitbar und der Lauf fortsetzbar.',
  'home.urlLabel': 'YouTube-Link',
  'home.analyze': 'Analysieren',
  'home.recent': 'Zuletzt bearbeitet',
  'home.loading': 'Projekte werden geladen…',
  'home.emptyTitle': 'Noch keine Projekte',
  'home.emptyBody': 'Füge oben einen Video-Link ein, um die erste Synchronfassung zu starten.',
  'home.delete': 'Löschen',
  'home.confirmDelete': '„{title}“ und alle erzeugten Dateien löschen?',
  'home.degraded': 'Diese Umgebung kann noch keine echte Synchronfassung erzeugen.',
  'home.degradedHelp': 'Führe {command} aus, um zu sehen, was fehlt.',
  'home.newToThis': 'Neu hier? Lies, wie die Verarbeitung abläuft.',

  'voice.label': 'Deutsche Erzählstimme',
  'voice.play': 'Stimme anhören',
  'voice.loading': 'Lädt…',
  'voice.notDownloaded': 'wird beim ersten Mal geladen',
  'voice.hint': 'Wähle eine Stimme und höre sie ab, bevor du startest.',
  'voice.sampleFailed':
    'Die Hörprobe konnte nicht abgespielt werden. Die Stimme wird vielleicht noch geladen.',

  'processing.title': 'Verarbeitung',
  'processing.percentComplete': '{percent} % abgeschlossen',
  'processing.progressLabel': 'Fortschritt der Synchronisation',

  'segments.title': 'Segmente prüfen',
  'segments.subtitle':
    'Zeile auswählen, ein Textfeld korrigieren, und nur das Nachfolgende wird neu erzeugt.',
  'segments.loading': 'Segmente werden geladen…',
  'segments.total': '{count} gesamt',
  'segments.approved': '{count} freigegeben',
  'segments.flagged': '{count} markiert',
  'segments.failed': '{count} fehlgeschlagen',
  'segments.time': 'Zeit',
  'segments.english': 'Englisch',
  'segments.german': 'Deutsch',
  'segments.fit': 'Passung',
  'segments.notTranslated': 'Nicht übersetzt',
  'segments.editLabel': 'Segment {number} bearbeiten',
  'segments.filterLabel': 'Anzeigen',
  'segments.filterAll': 'Alle',
  'segments.filterFlagged': 'Markiert',
  'segments.filterUnapproved': 'Zu prüfen',
  'segments.filterFailed': 'Fehlgeschlagen',
  'segments.noMatches': 'Keine Segmente passen zu diesem Filter.',
  'segments.showingCount': '{shown} von {total} werden angezeigt',

  'help.title': 'So funktioniert GermanDubI',
  'help.lede':
    'Du fügst einen Link ein, die Verarbeitung übernimmt die mechanische Arbeit, und das Deutsche bleibt in deiner Hand. Zwischen den Stufen geht nichts verloren: jedes Zwischenergebnis wird gespeichert, sodass eine Änderung nur das neu berechnet, was von ihr abhängt.',
  'help.walkthroughTitle': 'Der Ablauf von Anfang bis Ende',
  'help.step1Title': 'Link einfügen und auf Analysieren drücken',
  'help.step1Body':
    'Die Quelle wird geprüft, ohne sie herunterzuladen. Titel, Länge und vorhandene Untertitel siehst du in ein bis zwei Sekunden.',
  'help.step2Title': 'Auf „Deutsche Synchronfassung erstellen“ drücken',
  'help.step2Body':
    'Die Verarbeitung lädt das Material, transkribiert das Englische, übersetzt es, spricht das Deutsche ein, passt es an die ursprüngliche Zeitstruktur an und mischt es unter das Bild.',
  'help.step3Title': 'Zusehen oder später wiederkommen',
  'help.step3Body':
    'Der Fortschritt wird laufend gespeichert. Ein geschlossener Tab oder ein Neustart verliert keinen Lauf; er setzt bei der letzten fertigen Stufe fort.',
  'help.step4Title': 'Das Deutsche prüfen und korrigieren',
  'help.step4Body':
    'Jedes Segment ist bearbeitbar. Korrigierst du eine Übersetzung, wird nur dieses Segment neu gesprochen, zusammen mit allem, was davon abhängt.',
  'help.step5Title': 'Freigeben und exportieren',
  'help.step5Body':
    'Sind alle Segmente freigegeben, ist das Projekt fertig. Der Export behält die Originaltonspur als zweite Spur, dazu deutsche und englische Untertitel.',
  'help.stagesTitle': 'Die sechzehn Stufen',
  'help.stagesLede':
    'Ein Lauf ist ein Abhängigkeitsgraph, kein durchgehendes Skript. Genau das erlaubt es, nach einer Korrektur eine einzelne Stufe neu auszuführen.',
  'help.stage.probe': 'Liest die Angaben zur Quelle, ohne sie zu laden',
  'help.stage.acquire': 'Lädt das Video und vorhandene Untertitel',
  'help.stage.normalize': 'Extrahiert den Ton mit gleichbleibender Abtastrate',
  'help.stage.transcribe': 'Wandelt die englische Sprache in Text um',
  'help.stage.align': 'Gibt jedem Wort eine Position in der Zeit',
  'help.stage.segment': 'Fasst den Text zu Synchronsegmenten zusammen',
  'help.stage.separate': 'Trennt Stimme und Hintergrund, sofern verfügbar',
  'help.stage.translate': 'Übersetzt jedes Segment ins Deutsche',
  'help.stage.prosody': 'Misst Tempo und Pausen des Sprechers',
  'help.stage.synthesize': 'Spricht das Deutsche mit einer lokalen Stimme',
  'help.stage.fit': 'Passt das Timing an die verfügbare Lücke an',
  'help.stage.assemble': 'Setzt alle Segmente auf eine Tonspur',
  'help.stage.mix': 'Mischt das Deutsche über den Originalton',
  'help.stage.subtitle': 'Schreibt deutsche und englische Untertiteldateien',
  'help.stage.qa': 'Prüft das Ergebnis auf Timing-Probleme',
  'help.stage.export': 'Fügt alles zum fertigen Video zusammen',
  'help.timingTitle': 'Wie lange es dauert',
  'help.timingBody':
    'Auf einem reinen CPU-Rechner braucht ein 40-Minuten-Video etwa 8 Minuten, ungefähr ein Fünftel seiner Laufzeit. Spracherkennung und Sprachsynthese überwiegen; der Rest bewegt vor allem Daten.',
  'help.editTitle': 'Was du ändern kannst',
  'help.editBody':
    'Den deutschen Text jedes Segments. Alles nach deiner Änderung wird neu berechnet, alles davor bleibt unberührt: einen Namen am Ende zu korrigieren transkribiert nicht das ganze Video neu.',
  'help.privacyTitle': 'Was diesen Rechner verlässt',
  'help.privacyBody':
    'Der Link zur Quelle, damit das Video geladen werden kann. Sonst nichts. Erkennung, Übersetzung und Sprachsynthese laufen lokal, und ein Anbieter, der Audio nach außen geben würde, wird ohne deine Erlaubnis nie ausgewählt.',

  'about.title': 'Über GermanDubI',
  'about.lede':
    'Eine lokal arbeitende Umgebung, die ein englisches Video in eine bearbeitbare, synchrone deutsche Fassung verwandelt.',
  'about.projectTitle': 'Projekt',
  'about.author': 'Autor',
  'about.license': 'Lizenz',
  'about.licenseBody': 'GPL-3.0-or-later. Der vollständige Text steht in der Datei LICENSE.',
  'about.repository': 'Quelltext',
  'about.version': 'Version',
  'about.apiVersion': 'API',
  'about.revision': 'Revision',
  'about.languages': 'Sprachpaar',
  'about.buildTitle': 'Dieser Build',
  'about.providersTitle': 'Verwendete Anbieter',
  'about.providersLede':
    'Was auf diesem Rechner tatsächlich installiert ist – live ausgelesen statt von Hand gepflegt.',
  'about.providerLocal': 'lokal',
  'about.providerNetwork': 'Netzwerk',
  'about.providerReady': 'bereit',
  'about.providerMissing': 'nicht installiert',
  'about.toolsTitle': 'Gebaut mit',
  'about.toolsLede':
    'Jedes dieser Werkzeuge behält seine eigene Lizenz; keines wird als Teil dieses Projekts weitergegeben.',
  'about.rightsTitle': 'Deine Verantwortung',
  'about.rightsBody':
    'Diese Software umgeht keine Zugangsbeschränkungen und kein DRM. Du bist dafür verantwortlich, die Rechte an jeder verwendeten Quelle zu besitzen und die Erlaubnis für jede nachgebildete Stimme zu haben.',

  'error.title': 'Etwas ist schiefgelaufen',
  'notFound.title': 'Seite nicht gefunden',
  'notFound.back': 'Zurück zu den Projekten',
};
