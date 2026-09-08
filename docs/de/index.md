# flower

<div class="fl-hero" markdown>

<p class="fl-hero__tagline">Ein portables Long-Horizon-Agent-Framework auf Basis des Claude Agent SDK.</p>

<p class="fl-hero__sub">Ohne die Fähigkeiten von Claude Code zu opfern, wird es zu einem spezialisierten Agent, den du mitnehmen kannst, dessen Interaktion du anpassen kannst und der tagelang läuft.
Der Agent im Main Thread trifft nur Entscheidungen; die eigentliche Arbeit geht an Subagents.
Anforderungen werden erst geklärt, dann wird gearbeitet; ob etwas fertig ist, entscheidet eine andere Rolle.
Auf einer anderen Maschine verhält es sich identisch — es liest keine Einstellungen des Host-Systems, die Credentials bringt es selbst mit.</p>

[Schnellstart](getting-started/quickstart.md){ .md-button .md-button--primary }
[GitHub](https://github.com/ChenyuHeee/flower){ .md-button }

</div>

<div class="fl-stats">
<div class="fl-stat"><b>$171.62</b><span>Kosten eines Runs</span></div>
<div class="fl-stat"><b>10.4 Stunden</b><span>am Stück, Netzabbruch unterwegs selbst überbrückt</span></div>
<div class="fl-stat"><b>185.9K</b><span>Kontext-Spitze im Main Thread, durchgehend ohne Compact</span></div>
<div class="fl-stat"><b>94.8 %</b><span>der Textzeichen landen in Subagents</span></div>
</div>

Die vier Zahlen stammen aus [HT001](cases/ht001.md) — dem Run, in dem ein Agent unter flower von Null eine Terminal-IDE geschrieben hat.

## Installieren {#装}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

Sucht automatisch `uv` / `pipx` / `pip` und installiert den Befehl `flower`. Es braucht nur Python ≥ 3.10, kein Node,
und auch keine Claude Code CLI. Nach der Installation `cd` in ein beliebiges Projektverzeichnis und `flower` eintippen: Beim ersten Mal fragt es nach API-Key
oder Gateway-Adresse, einmal konfiguriert liegt das in `~/.config/flower/.env` und gilt überall; wenn auf der Maschine bereits Claude Code installiert und eingerichtet ist,
borgt es sich dieses Token direkt, ganz ohne Nachfrage. Vollständige Schritte und Fehlersuche siehe [Installation](getting-started/install.md).

## Es fängt vier Arten von Fehlschlägen für dich ab {#四类失败}

<div class="fl-grid" markdown>

<div class="fl-card" markdown>
### [Clarify](guide/clarify.md) {#前置确认}

Angst, dass am Ende nicht das herauskommt, was du wolltest — vor dem Loslegen gibt es eine Rolle, die nur fragt und nichts anfasst, so lange, bis alles klar ist, und friert die Anforderung in einem Dokument ein,
das jeder folgende Schritt zum Start liest.
</div>

<div class="fl-card" markdown>
### [Goal Guard](guide/goal.md) {#目标看守}

Angst, dass es "fertig" sagt, obwohl es nicht fertig ist — nach jeder Arbeitsrunde urteilt eine andere Rolle unabhängig: erreicht, dann weiter; nicht erreicht, dann zurück;
lässt sich das in dieser Umgebung nicht verifizieren, hält es an und fragt einen Menschen.
</div>

<div class="fl-card" markdown>
### [Continuity](guide/continuity.md) {#接续}

Angst, dass nach Stunden alles abstürzt und du von vorn anfängst — tippe im selben Verzeichnis noch einmal `flower` und du bist wieder beim letzten Stand, auch wenn der Prozess gekillt wurde
oder die Maschine neu gestartet ist; du musst dir keine ID merken.
</div>

<div class="fl-card" markdown>
### [Handoff](guide/handoff.md) {#换代}

Angst, dass der volle Kontext zu einer Zusammenfassung zusammengepresst wird — die aktuelle Session schreibt selbst ein Handoff-Dokument, das Menschen lesen und ändern können, eine neue Session übernimmt,
ganz ohne Compact.
</div>

</div>

## Warum es "long-horizon" ist {#长程}

Der [Coordinator](reference/glossary.md#协调者) im Main Thread enthält nur Entscheidungen und bekommt weder `Write` noch `Edit` —
Code schreiben, Tests laufen lassen, Recherche geht alles an [Subagents](reference/glossary.md#subagent),
und das Trial-and-Error der Subagents landet in **einem anderen** Transcript, der Main Thread bekommt nur einen Bericht von höchstens 30 Zeilen.
Im 10.4-stündigen Run von HT001 **landeten 94.8 % der Textzeichen in Subagents**,
von 1.893 handanlegenden Tool-Aufrufen kamen nur 32 dem Coordinator zu Gesicht.
Deshalb wuchs der Main Thread erst nach 70 Runden auf 185.9K und es kam durchgehend zu keinem Compact — wie diese Schicht gebaut ist und was die anderen drei sind,
steht unter [Kontextökonomie](guide/context.md).

## Wirklich gelaufen {#真的跑过}

- **[HT001](cases/ht001.md)** — eine Terminal-IDE von Null geschrieben. $171.62 / 10.4 Stunden /
  Main-Thread-Kontext auf 185.9K gewachsen, 12.212 Zeilen Produktcode abgeliefert, unterwegs einmal Netzabbruch, danach selbst weitergelaufen.
- **[HT002](cases/ht002.md)** — es auf macOS installiert und zum Laufen gebracht. $38.24 / rund 1 Stunde, erstmals mit Goal Guard;
  das Programm lief tatsächlich, und das Verdict lautete **nicht erreicht**, also kam die Frage an den Menschen hoch.

Beide Seiten schreiben auch, was nicht haltbar ist: In HT001 hat der Agent bei der eigenen Abnahme einen Punkt falsch beurteilt,
in HT002 wurde aus `git clone && make && ./cppide` eine Stunde. Jede Zahl lässt sich in `runs/manifest.json`
und `sessions.db` nachrechnen — das sind Rohaufzeichnungen, keine Werbung.

## Wo anfangen zu lesen {#从哪读起}

- **Sofort loslegen** — [Schnellstart](getting-started/quickstart.md): erst für ein paar Cent die Credentials verifizieren,
  dann ohne eine Zeile Code einen dreistufigen Workflow durchlaufen.
- **Erst die Konzepte verstehen** — [Kernkonzepte](getting-started/concepts.md): Run, Step, Session, die fünf Rollen,
  in fünf Minuten einmal komplett erklärt.
- **In eigenen Code einbinden** — [Python API](reference/api.md): `Runtime`, `Step`, die fünf Rollen-Factories,
  Signaturen und Defaults von 62 öffentlichen Symbolen.
