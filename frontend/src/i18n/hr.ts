import type { Catalogue } from './en';

export const hr: Catalogue = {
  'app.tagline': 'Engleski video → njemačka sinkronizacija koju možeš urediti',
  'app.localBadge': 'Radi na ovom računalu',
  'app.skipToContent': 'Prijeđi na sadržaj',

  'nav.projects': 'Projekti',
  'nav.help': 'Kako radi',
  'nav.about': 'O programu',

  'theme.label': 'Prikaz',
  'theme.light': 'Svijetlo',
  'theme.dark': 'Tamno',
  'theme.system': 'Sustav',

  'language.label': 'Jezik sučelja',
  'language.note': 'Mijenja samo ovo sučelje. Sinkronizacija je uvijek s engleskog na njemački.',

  'home.title': 'Pretvori engleski video u njemačku sinkronizaciju',
  'home.subtitle': 'Zalijepi YouTube poveznicu. Svaki isječak ostaje uredljiv i nastavljiv.',
  'home.urlLabel': 'YouTube poveznica',
  'home.analyze': 'Analiziraj',
  'home.recent': 'Nedavni projekti',
  'home.loading': 'Učitavanje projekata…',
  'home.emptyTitle': 'Još nema projekata',
  'home.emptyBody': 'Zalijepi poveznicu na video iznad da započneš prvu sinkronizaciju.',
  'home.delete': 'Obriši',
  'home.confirmDelete': 'Obrisati „{title}“ i sve generirane datoteke?',
  'home.degraded': 'Ovo okruženje još ne može napraviti pravu sinkronizaciju.',
  'home.degradedHelp': 'Pokreni {command} da vidiš što nedostaje.',
  'home.newToThis': 'Prvi put ovdje? Pročitaj kako obrada teče.',

  'home.stop': 'Zaustavi',
  'home.stopHint':
    'Odmah zaustavlja ovu sinkronizaciju. Dovršeni koraci ostaju i možeš nastaviti kasnije.',
  'home.reset': 'Obriši sve',
  'home.resetHint':
    'Uklanja sve projekte i sve stvorene datoteke s ovog računala. To se ne može poništiti.',
  'home.confirmReset':
    'Obrisati svih {count} projekata i sve datoteke koje su stvorili? To se ne može poništiti.',
  'home.resetDone': 'Sve je obrisano.',
  'home.deleteHint': 'Obriši ovaj projekt i njegove datoteke.',
  'home.busy': 'u tijeku',

  'voice.label': 'Njemački pripovjedač',
  'voice.play': 'Poslušaj glas',
  'voice.loading': 'Učitavanje…',
  'voice.notDownloaded': 'preuzima se pri prvoj upotrebi',
  'voice.hint': 'Odaberi glas i poslušaj ga prije početka.',
  'voice.sampleFailed': 'Uzorak se nije mogao reproducirati. Glas se možda još preuzima.',

  'project.analyze': 'Analiziraj izvor',
  'project.analyzeHint': 'Čita naslov, trajanje i titlove izvora bez preuzimanja.',
  'project.start': 'Napravi njemačku sinkronizaciju',
  'project.startHint': 'Pokreće cijelu obradu. Možeš je zaustaviti kad god i nastaviti kasnije.',
  'project.cancel': 'Zaustavi obradu',
  'project.cancelHint':
    'Zaustavlja na sljedećoj sigurnoj točki i prekida alat koji trenutno radi. Dovršeni koraci ostaju.',
  'project.resume': 'Nastavi nedovršeno',
  'project.resumeHint': 'Nastavlja od zadnjeg dovršenog koraka.',
  'project.download': 'Preuzmi',
  'project.downloadHint': 'Sinkronizirani video, s izvornim zvukom kao drugom stazom.',

  'processing.title': 'Obrada',
  'processing.percentComplete': '{percent} % dovršeno',
  'processing.progressLabel': 'Napredak sinkronizacije',

  'segments.title': 'Pregled isječaka',
  'segments.subtitle':
    'Odaberi redak, ispravi jedno tekstualno polje i ponovno se radi samo ono što slijedi.',
  'segments.loading': 'Učitavanje isječaka…',
  'segments.total': 'ukupno {count}',
  'segments.approved': 'odobreno {count}',
  'segments.flagged': 'označeno {count}',
  'segments.failed': 'neuspjelo {count}',
  'segments.time': 'Vrijeme',
  'segments.english': 'Engleski',
  'segments.german': 'Njemački',
  'segments.fit': 'Uklapanje',
  'segments.notTranslated': 'Nije prevedeno',
  'segments.editLabel': 'Uredi isječak {number}',
  'segments.filterLabel': 'Prikaži',
  'segments.filterAll': 'Sve',
  'segments.filterFlagged': 'Označeno',
  'segments.filterUnapproved': 'Za pregled',
  'segments.filterFailed': 'Neuspjelo',
  'segments.noMatches': 'Nijedan isječak ne odgovara ovom filtru.',
  'segments.showingCount': 'Prikazano {shown} od {total}',

  'help.title': 'Kako GermanDubI radi',
  'help.lede':
    'Ti zalijepiš poveznicu, obrada odradi mehanički dio, a njemački ostaje pod tvojom kontrolom. Između koraka ništa se ne gubi: svaki međurezultat se sprema, pa promjena ponovno računa samo ono što o njoj ovisi.',
  'help.walkthroughTitle': 'Tijek rada od početka do kraja',
  'help.step1Title': 'Zalijepi poveznicu i pritisni Analiziraj',
  'help.step1Body':
    'Izvor se pregleda bez preuzimanja, pa naslov, trajanje i postojanje titlova vidiš za sekundu ili dvije.',
  'help.step2Title': 'Pritisni „Napravi njemačku sinkronizaciju“',
  'help.step2Body':
    'Obrada preuzima materijal, transkribira engleski, prevodi ga, izgovara njemački, prilagođava ga izvornom trajanju i miješa natrag ispod slike.',
  'help.step3Title': 'Gledaj kako teče ili se vrati kasnije',
  'help.step3Body':
    'Napredak se sprema usput. Zatvaranje kartice ili ponovno pokretanje računala ne gubi obradu; nastavlja se od zadnjeg dovršenog koraka.',
  'help.step4Title': 'Pregledaj i ispravi njemački',
  'help.step4Body':
    'Svaki isječak se može urediti. Ispraviš li prijevod, ponovno se izgovara samo taj isječak i ono što o njemu ovisi.',
  'help.step5Title': 'Odobri i izvezi',
  'help.step5Body':
    'Kad su svi isječci odobreni, projekt je gotov. Izvoz zadržava izvorni zvuk kao drugu stazu, uz njemačke i engleske titlove.',
  'help.stagesTitle': 'Šesnaest koraka',
  'help.stagesLede':
    'Obrada je graf ovisnosti, a ne jedna duga skripta. Upravo to omogućuje ponovno pokretanje pojedinog koraka nakon ispravka.',
  'help.stage.probe': 'Čita podatke o izvoru bez preuzimanja',
  'help.stage.acquire': 'Preuzima video i eventualne titlove',
  'help.stage.normalize': 'Izdvaja zvuk s ujednačenom frekvencijom',
  'help.stage.transcribe': 'Pretvara engleski govor u tekst',
  'help.stage.align': 'Svakoj riječi dodjeljuje položaj u vremenu',
  'help.stage.segment': 'Grupira tekst u isječke za sinkronizaciju',
  'help.stage.separate': 'Odvaja glas od pozadine, kad je dostupno',
  'help.stage.translate': 'Prevodi svaki isječak na njemački',
  'help.stage.prosody': 'Mjeri tempo i stanke pripovjedača',
  'help.stage.synthesize': 'Izgovara njemački lokalnim glasom',
  'help.stage.fit': 'Prilagođava trajanje raspoloživom razmaku',
  'help.stage.assemble': 'Slaže sve isječke na jednu stazu',
  'help.stage.mix': 'Miješa njemački preko izvornog zvuka',
  'help.stage.subtitle': 'Zapisuje njemačke i engleske titlove',
  'help.stage.qa': 'Provjerava rezultat na probleme s vremenom',
  'help.stage.export': 'Spaja sve u konačni video',
  'help.timingTitle': 'Koliko traje',
  'help.timingBody':
    'Na računalu bez grafičkog ubrzanja video od 40 minuta traje otprilike 8 minuta, oko petine svojeg trajanja. Prepoznavanje govora i sinteza uzimaju najviše; ostalo uglavnom premješta podatke.',
  'help.editTitle': 'Što možeš mijenjati',
  'help.editBody':
    'Njemački tekst bilo kojeg isječka. Sve nakon tvoje izmjene se preračunava, a sve prije ostaje netaknuto: ispravak imena pri kraju ne transkribira video ponovno.',
  'help.privacyTitle': 'Što napušta tvoje računalo',
  'help.privacyBody':
    'Poveznica na izvor, kako bi se video mogao dohvatiti. Ništa drugo. Prepoznavanje, prijevod i govor rade lokalno, a pružatelj koji bi slao zvuk drugamo nikad se ne bira bez tvojeg dopuštenja.',

  'about.title': 'O GermanDubI',
  'about.lede':
    'Radna okolina koja radi lokalno i pretvara engleski video u uredljivu, usklađenu njemačku verziju.',
  'about.projectTitle': 'Projekt',
  'about.author': 'Autor',
  'about.license': 'Licenca',
  'about.licenseBody': 'GPL-3.0-or-later. Cijeli tekst nalazi se u datoteci LICENSE.',
  'about.repository': 'Izvorni kod',
  'about.version': 'Verzija',
  'about.apiVersion': 'API',
  'about.revision': 'Revizija',
  'about.languages': 'Jezični par',
  'about.buildTitle': 'Ova verzija',
  'about.providersTitle': 'Korišteni pružatelji',
  'about.providersLede':
    'Ono što je stvarno instalirano na ovom računalu, očitano uživo umjesto ručno popisano.',
  'about.providerLocal': 'lokalno',
  'about.providerNetwork': 'mreža',
  'about.providerReady': 'spremno',
  'about.providerMissing': 'nije instalirano',
  'about.toolsTitle': 'Izgrađeno pomoću',
  'about.toolsLede':
    'Svaki od ovih alata zadržava vlastitu licencu; nijedan se ne distribuira kao dio ovog projekta.',
  'about.rightsTitle': 'Tvoja odgovornost',
  'about.rightsBody':
    'Ovaj program ne zaobilazi zaštitu pristupa ni DRM. Ti si odgovoran za prava na svaki izvor koji koristiš i za dopuštenje za svaki glas koji reproduciraš.',

  'error.title': 'Nešto je pošlo po zlu',
  'notFound.title': 'Stranica nije pronađena',
  'notFound.back': 'Natrag na projekte',
};
