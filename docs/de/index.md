# flower

<div class="fl-hero" markdown>

<p class="fl-hero__tagline">Ein portables Framework für long-horizon Agents auf Basis des Claude Agent SDK.</p>

<p class="fl-hero__sub">Ohne die Fähigkeiten von Claude Code zu opfern, wird daraus ein spezialisierter Agent, den man mitnehmen kann, dessen Interaktion sich anpassen lässt und der tagelang läuft.
Der Agent im main thread trifft nur Entscheidungen, die eigentliche Arbeit geht komplett an Subagents; die Anforderungen werden erst geklärt, dann wird angefangen, und ob etwas fertig ist oder nicht, entscheidet eine andere Rolle.
Auf einer anderen Maschine verhält es sich identisch — es liest keine Einstellungen des Hostsystems, die Zugangsdaten bringt es selbst mit.</p>

[Schnellstart](getting-started/quickstart.md){ .md-button .md-button--primary }
[GitHub](https://github.com/ChenyuHeee/flower){ .md-button }

</div>

<div class="fl-stats">
<div class="fl-stat"><b>$171.62</b><span>Kosten eines Runs</span></div>
<div class="fl-stat"><b>10.4 Stunden</b><span>durchgehend gelaufen, Netzausfall unterwegs selbst überbrückt</span></div>
<div class="fl-stat"><b>185.9K</b><span>Spitze des Kontexts im main thread, kein einziger Compact</span></div>
<div class="fl-stat"><b>94.8%</b><span>der Textzeichen entfallen auf Subagents</span></div>
</div>

Die vier Zahlen stammen aus [HT001](cases/ht001.md) — dem Run, in dem ein Agent unter flower von null an eine Terminal-IDE geschrieben hat.

## Ein Befehl zur Installation, ohne Node {#装}

```bash
curl -fsSL https://chenyuheee.github.io/flower/install.sh | sh
```

Das Skript sucht sich automatisch `uv` / `pipx` / `pip` und installiert den Befehl `flower`; nötig ist nur Python ≥ 3.10,
auch die Claude Code CLI muss nicht installiert sein. Danach in ein beliebiges Projektverzeichnis `cd`en und `flower` eintippen: Beim ersten Mal wird nach einem API-Key
oder einer Gateway-Adresse gefragt, einmal konfiguriert landet das in `~/.config/flower/.env` und gilt überall; wenn auf der Maschine bereits Claude Code installiert und eingerichtet ist,
borgt es sich direkt jenes Token und fragt gar nicht erst. Vollständige Schritte und Fehlerbehebung siehe [Installation](getting-started/install.md).

## Es fängt vier Klassen von Fehlschlägen für dich ab {#四类失败}

<div class="fl-grid" markdown>

<div class="fl-card" markdown>
### [Clarify](guide/clarify.md) {#前置确认}

Die Sorge, dass am Ende nicht das herauskommt, was gewollt war — bevor angefangen wird, fragt eine Rolle, die nur fragt und selbst nichts anfasst, so lange nach, bis alles klar ist, und friert die Anforderungen in einem Dokument ein;
jeder weitere Schritt startet mit dessen Lektüre.
</div>

<div class="fl-card" markdown>
### [Goal guard](guide/goal.md) {#目标看守}

Die Sorge, dass es „fertig" sagt und in Wahrheit nicht fertig ist — am Ende jeder Arbeitsrunde urteilt eine andere Rolle unabhängig ein Mal: erreicht, dann weiter; nicht erreicht, dann zurück;
lässt es sich in dieser Umgebung nicht verifizieren, wird angehalten und beim Menschen nachgefragt.
</div>

<div class="fl-card" markdown>
### [Continuity](guide/continuity.md) {#接续}

Die Sorge, nach Stunden Laufzeit abzustürzen und von vorn anfangen zu müssen — im selben Verzeichnis noch einmal `flower` eintippen und der letzte Stand wird fortgesetzt, auch wenn der Prozess ge-killt
oder die Maschine neu gestartet wurde, ohne dass du dir irgendeine id merken musst.
</div>

<div class="fl-card" markdown>
### [Handoff](guide/handoff.md) {#换代}

Die Sorge, dass ein voller Kontext zu einer Zusammenfassung zusammengedrückt wird — die aktuelle Session schreibt selbst ein handoff document, das ein Mensch lesen und ändern kann, eine neue Session übernimmt,
ohne Compact.
</div>

</div>

## Wodurch es „long-horizon" ist {#长程}

Der [Koordinator](reference/glossary.md#协调者) im main thread trägt nur Entscheidungen und bekommt weder `Write` noch `Edit` —
Code schreiben, Tests laufen lassen, Recherche, all das geht an [Subagents](reference/glossary.md#subagent),
und das Probieren und Irren der Subagents landet in einem **anderen** Transcript, der main thread bekommt nur einen Bericht von höchstens 30 Zeilen.
In jenem 10.4 Stunden langen Run von HT001 entfielen **94.8% der Textzeichen auf Subagents**,
von 1,893 ausführenden Tool-Aufrufen kamen nur 32 dem Koordinator zu Gesicht.
Deshalb wuchs der main thread über 70 Runden erst auf 185.9K und es kam im gesamten Lauf zu keinem Compact — wie diese Schicht gebaut ist und was die anderen drei Schichten sind,
steht in [Kontext-Ökonomie](guide/context.md).

## Die Rohaufzeichnungen zweier echter Langläufe {#真的跑过}

- **[HT001](cases/ht001.md)** — eine Terminal-IDE von null an. $171.62 / 10.4 Stunden /
  Kontext im main thread bis auf 185.9K gewachsen, abgeliefert wurden 12,212 Zeilen Produktcode, unterwegs riss einmal das Netz ab, danach lief es von selbst zu Ende.
- **[HT002](cases/ht002.md)** — es unter macOS installieren und zum Laufen bringen. $38.24 / rund 1 Stunde, erstmals mit goal guard;
  das Programm lief tatsächlich, und das Verdikt lautete trotzdem **nicht erreicht**, mit Rückfrage an den Menschen.

Beide Seiten benennen auch, was nicht hält: In HT001 hat der Agent bei der eigenen Abnahme einen Punkt falsch beurteilt,
in HT002 wurden aus `git clone && make && ./cppide` eine ganze Stunde. Jede Zahl lässt sich in `runs/manifest.json`
und `sessions.db` nachrechnen — das ist ein Protokoll, keine Werbung.

## Wo anfangen {#从哪读起}

- **Sofort loslaufen** — [Schnellstart](getting-started/quickstart.md): mit drei Befehlen läuft es,
  danach lernst du, das zu lesen, was über den Bildschirm scrollt.
- **Erst die Konzepte verstehen** — [Kernkonzepte](getting-started/concepts.md): Run, Step, Session, die fünf Rollen,
  in fünf Minuten einmal komplett.
- **In eigenen Code einbinden** — [Python API](reference/api.md): `Runtime`, `Step`, die fünf Rollen-Factories,
  Signaturen und Defaults von 62 öffentlichen Symbolen.
