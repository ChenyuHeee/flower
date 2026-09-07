# Kernkonzepte

flower bringt eine eigene Begriffsmenge mit: Run, Schritt, Session, Koordinator, Worker, Clarify, Goal Guard, Continuity, Handoff.
Diese Seite erklärt sie alle auf einmal, damit man auf den anderen Seiten nicht beim Lesen raten muss. In fünf Minuten durch.

Hier stehen nur die Konzepte, **keine API-Signaturen** — Signaturen gibt es in der [Python-API](../reference/api.md),
Ein-Satz-Definitionen samt Chinesisch-Englisch-Gegenüberstellung im [Glossar](../reference/glossary.md), Kommandozeilen-Schalter in der
[CLI-Referenz](../reference/cli.md).

## Welche Form ein Run hat {#形状}

Drei Ebenen, von groß nach klein:

| Begriff | Was es ist | Wo es festgehalten wird |
|---|---|---|
| [Run](../reference/glossary.md#运行) | Der komplette Ablauf einer `Runtime` von Anfang bis Ende. Auf dem Standardpfad ist ein Run genau ein Aufruf von `flower` | `runs/manifest.json` |
| [Schritt](../reference/glossary.md#步骤) step | Eine ausführbare Einheit innerhalb eines Runs: nimmt ein Kontext-Dictionary entgegen, lässt einen Agent laufen, schreibt das Ergebnis zurück ins Dictionary. Jede `==`-Trennlinie auf dem Bildschirm ist eine Schrittgrenze | dito, eine Zeile pro Schritt |
| [Session](../reference/glossary.md#会话) | Ein Kontextstrang auf Modellseite. Hat eine eigene `session_id`, lässt sich resumen und forken | `runs/sessions.db` |

Die Verschachtelung ist keine 1:1-Beziehung:

```text
Run ── dieser eine Aufruf von flower
 ├── Schritt Anforderungen klären ── Session A
 ├── Schritt Ziel setzen ─────────── Session B
 └── Schritt Arbeiten ───────────── Session C ──[Kontext fast voll]──> Session C'
      └── Arbeiten·Verdict#1 ─────── Session D
```

- **Ein Schritt kann mehrere Sessions verbrennen.** Wenn der Kontext fast voll ist, wird nicht komprimiert, sondern ein Handoff-Dokument geschrieben und eine neue Session übernimmt —
  das heißt [Handoff](../reference/glossary.md#换代) und passiert **innerhalb eines Runs**.
- **Ein neuer Run kann an alte Sessions anknüpfen.** Ein weiterer `flower`-Aufruf im selben Verzeichnis setzt jeden Schritt auf der Session vom letzten Mal fort —
  das heißt [Continuity](../reference/glossary.md#接续) und passiert **prozessübergreifend**. `runs/lineage.json`
  merkt sich dafür, „welcher Schrittname zu welcher `session_id` gehört".
- **Die Verdict-Runde ist immer eine neue Session.** Sie knüpft nicht an und geht nicht in die Lineage ein — wer beurteilt, „ob es fertig ist", darf nicht derselbe sein, der eben gearbeitet hat.

Eine der Reihe nach verkettete Gruppe von Schritten heißt [Workflow](../reference/glossary.md#流程).
`flower` ohne Argumente nutzt den mitgelieferten Drei-Schritt-Workflow: Anforderungen klären → Ziel setzen → Arbeiten.

## Arbeitsteilung: der Koordinator fasst nichts an {#分工}

**Das ist der Satz, auf dem das ganze Framework steht.**

Der [Koordinator](../reference/glossary.md#协调者) ist der Agent auf dem [Main Thread](../reference/glossary.md#主线程).
Er zerlegt Aufgaben, verteilt Arbeit, liest Berichte, trifft Entscheidungen — aber er **bekommt kein `Write` und kein `Edit`**,
und sein `Bash` reicht nur für [Ephemeral Commands](../reference/glossary.md#一次性命令) wie `ls` oder `git status`, um kurz nachzusehen
(kontrolliert per Hook, nicht per Prompt-Ermahnung; und diese Ergebnisse landen nicht in der persistierten Session-Aufzeichnung).
Seine Toolliste ist `Agent`, `TodoWrite`, `Read` plus dieses eingeschränkte `Bash`.

Die eigentliche Arbeit macht der [Worker](../reference/glossary.md#执行者) — ein über das `Agent`-Tool losgeschickter
[Subagent](../reference/glossary.md#subagent).

**Warum diese Aufteilung.** Ein Subagent hat **eine eigene Transcript-Spur**: wie viele Dateien er gelesen hat, wie oft er Tests laufen ließ,
wie viele Irrwege er ging — alles steht dort; der Main Thread bekommt nur den Abschlussbericht. Und der Main Thread ist der einzige Kontext, der den gesamten Run durchzieht,
also der, an dem am dringendsten gespart werden muss.

Gemessen ([HT001](../cases/ht001.md), ein Run über 10.4 Stunden):

| | Main Thread | Subagent | versenkter Anteil |
|---|---|---|---|
| Modellrunden | 70 | 3.0K | 97.7 % |
| Textzeichen | 200.1K | 3.6M | **94.8 %** |
| Tool-Aufrufe | 32 | 1,893 | —— |

Pro Beauftragung bleiben im Schnitt **82 Tool-Aufrufe für den Main Thread komplett unsichtbar**. Das ist die erste Ebene der Kontexteinsparung und zugleich die ergiebigste;
die vollständige Herleitung steht in [Kontextökonomie](../guide/context.md).

Zwei häufige Missverständnisse:

- **Der Koordinator ist kein klügerer Agent.** Er läuft standardmäßig auf derselben Modellklasse wie der Worker; gespart wird Kontext, nicht Modell.
- **Das Antwortformat ist erzwungen.** Die Antwort eines Workers besteht aus genau vier Abschnitten — Schlussfolgerung / Belege / Artefakte / Ungeprüftes, nicht länger als 30 Zeilen,
  und Dateiinhalte, Kommandoausgaben, Logs sowie Roh-Diffs sind verboten. Langes gehört nach `artifacts/` in der [Workbench](../reference/glossary.md#工作台),
  in der Antwort steht nur der Pfad.

flower hat insgesamt fünf Rollen, alle nach demselben Bauprinzip: ein eingespeister Regeltext + ein Toolset + ein Satz Hooks.

| Rolle | Aufgabe | Werkzeuge |
|---|---|---|
| [Koordinator](../reference/glossary.md#协调者) coordinator | zerlegen, beauftragen, entscheiden | `Agent` `TodoWrite` `Read` + eingeschränktes `Bash` |
| [Worker](../reference/glossary.md#执行者) | Code schreiben, Tests laufen lassen, recherchieren | `Read` `Write` `Edit` `Bash` `Glob` `Grep` `WebFetch` `WebSearch` |
| [Clarifier](../reference/glossary.md#确认者) clarify | stellt vor Arbeitsbeginn nur Fragen, bis alles klar ist | Frage-Tools + Nur-Lese-Tools, **keinerlei Schreib-Tools** |
| [Judge](../reference/glossary.md#判定者) | setzt das Ziel oder beurteilt, „ob diese Runde fertig ist" | Frage-Tools + `Read` `Glob` `Grep` (Kommandoausführung muss explizit freigeschaltet werden) |
| [Oracle](../reference/glossary.md#旁路顾问) | beantwortet mitten im Run „wo stehen wir gerade" | `Read` `Glob` `Grep`. **Seine Antworten gehen nicht in den Kontext dieses Runs** |

Parameter und Defaults der Factory-Funktionen stehen in der [Python-API](../reference/api.md#角色工厂).

## Long-Horizon geht an vier Stellen kaputt {#四个机制}

Ein [Long-Horizon](../reference/glossary.md#长程)-Run erstreckt sich über Stunden bis Tage, über mehrere Sessions, über Prozessneustarts hinweg.
Er zerfällt auf genau ein paar Arten, und jede hat ihren Mechanismus:

| Was du befürchtest | Mechanismus | Was er tut | Details |
|---|---|---|---|
| Es entsteht nicht das, was du wolltest | [Clarify](../reference/glossary.md#前置确认) | vor dem ersten Handgriff die Anforderungen ausfragen und als [Brief](../reference/glossary.md#需求确认书) einfrieren; jeder spätere Schritt liest ihn, statt neu zu raten | [Clarify](../guide/clarify.md) |
| Es sagt „fertig", ist es aber nicht | [Goal Guard](../reference/glossary.md#目标看守) | am Ende jeder Runde beurteilt ein unbeteiligter Judge unabhängig; nicht erreicht heißt zurück an die Arbeit | [Goal Guard](../guide/goal.md) |
| Nach Stunden Absturz, alles von vorn | [Continuity](../reference/glossary.md#接续) | ein erneuter Lauf im selben Verzeichnis knüpft automatisch am letzten Stand an — auch nach Prozess-Kill oder Maschinenneustart | [Continuity](../guide/continuity.md) |
| Voller Kontext wird zu einer Zusammenfassung zerdrückt | [Handoff](../reference/glossary.md#换代) | kurz vor dem Vollwerden schreibt die aktuelle Session ein für Menschen lesbares und editierbares [Handoff-Dokument](../reference/glossary.md#交接书), dann übernimmt eine neue Session | [Handoff](../guide/handoff.md) |

Zwei Punkte lohnen sich extra zu merken:

**Ein [Verdict](../reference/glossary.md#判定) hat drei Ausgänge, nicht zwei.** Erreicht, nicht erreicht, **in dieser Umgebung nicht verifizierbar**.
Die letzten beiden sind verschiedene Ergebnisse — „hier lässt es sich nicht prüfen" wird nie als bestanden gewertet, sondern hält an und fragt den Menschen.
Außerdem beurteilt der Judge das **Artefakt**, nicht den Quellcode: In [HT002](../cases/ht002.md) ist genau das einmal schiefgegangen —
nur der macOS-Zweig des Makefile wurde angesehen und durchgewinkt, ausgeliefert wurde tatsächlich ein Linux-ELF.

**Handoff ist kein [Compact](../reference/glossary.md#压缩).** Compact heißt, das Modell fasst den bisherigen Dialog im Verborgenen zu einer Zusammenfassung zusammen:
nicht lesbar, nicht änderbar, und was verloren ging, weißt du nicht. Das Handoff-Dokument ist strukturiert und liegt auf der Platte, du kannst es öffnen, eine Zeile ändern und weiterlaufen lassen.
flower schaltet den nativen Auto-Compact standardmäßig ab und setzt stattdessen auf Handoff.

Zwei weitere Ebenen stehen nicht in dieser Tabelle, laufen aber bei jedem Run mit:

- [Spill](../reference/glossary.md#落盘) — Tool-Ergebnisse über 4000 Zeichen werden nach `.flower/spill/` geschrieben,
  im Kontext bleibt nur eine Zeile mit dem Pfad. **Sofort geschnitten**, nicht erst zusammengefasst, wenn es voll ist.
- [Workbench](../reference/glossary.md#工作台) — die drei Verzeichnisse `scripts/`, `artifacts/` und `notes/` unter `.flower/`,
  dazu ein `INDEX.md`, das in den System-Prompt eingespeist wird, damit der Agent in jeder Runde weiß, was er zur Hand hat.
  In HT001 sammelten sich **61 Skripte an, die 331-mal ausgeführt wurden**, davon **92 %** mehr als einmal.

## Was flower nicht macht {#不做什么}

**Erstens: es liefert keine fertigen Workflows.** Das Framework kümmert sich nur um Mechanik: wie ein Schritt läuft, wie Kontext gespart wird, wie nach Verbindungsabbruch fortgesetzt wird,
wie parallele Änderungen am selben Repository sich nicht in die Quere kommen, wie angehalten wird, wenn ein Mensch gefragt werden muss. **Den Workflow schreibst du.**
Die drei Schritte beim nackten `flower`-Aufruf stammen aus
[`flower/workflow/starter.py`](https://github.com/ChenyuHeee/flower/blob/main/flower/workflow/starter.py)
und sind so generisch, dass sie keinerlei Domänenannahme enthalten — sie sind zum Loslegen da, nicht die Leistungsgrenze des Frameworks.
Für eigene siehe [Workflows entwerfen](../guide/workflow.md).

**Zweitens: es erbt keine Konfiguration des Hosts.** flower läuft mit `setting_sources=[]`: weder `~/.claude/` des Hosts
noch `.claude/` des Projekts werden gelesen. Genau das heißt [portabel](../reference/glossary.md#可移植) — auf einer anderen Maschine dasselbe Verhalten.
Domänenfähigkeiten kommen über [Plugins](../reference/glossary.md#plugin), die mit dem Repository mitreisen, nicht darüber, was auf dieser Maschine zufällig installiert ist.

**Drittens: Credentials musst du selbst mitbringen.** Das ist der Preis für Punkt zwei. flower sucht Credentials in fester Reihenfolge (Prozess-Umgebungsvariablen →
`$FLOWER_ENV` → `.env` im aktuellen Verzeichnis → `~/.config/flower/.env` → `.env` im Wurzelverzeichnis des Quell-Repos)
und leiht sich zuletzt als Rückfallebene die 9 Credential-Schlüssel aus dem `env`-Block von `~/.claude/settings.json` —
**geliehen wird ausschließlich die Information „wo finde ich das Token"**, alles andere in der settings.json beeinflusst das Agent-Verhalten nicht.
Die vollständige Reihenfolge und die Semantik jeder Variable stehen in der [Konfigurationsreferenz](../reference/config.md).

**Viertens: es ersetzt den System-Prompt nicht.** Domänenanweisungen werden **hinter** den nativen System-Prompt von Claude Code
[angehängt](../reference/glossary.md#叠加), nicht an dessen Stelle gesetzt. Spezialisierung geht daher nicht auf Kosten der allgemeinen Fähigkeiten.

---

Bis hierher sollten die Ausgaben aus [Schnellstart](quickstart.md) alle lesbar sein.
Wer wissen will, wie sich diese Mechanismen jeweils einstellen lassen und wann man sie besser nicht einsetzt, liest ab [Kontextökonomie](../guide/context.md) weiter;
wer nur Kommandos abschreiben will, geht zur [CLI-Referenz](../reference/cli.md).
