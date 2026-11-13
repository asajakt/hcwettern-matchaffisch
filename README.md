# HC Wettern Matchaffisch

## 👉 Öppna sidan: https://asajakt.github.io/hcwettern-matchaffisch/

1. Välj **Lag** i den översta listan (t.ex. A-laget eller U12 - Team 14/15).
2. Välj **Match** i listan under. Där visas lagets kommande matcher med datum, tid och motståndare. Bocka i *Visa även spelade matcher* om du vill se äldre matcher.
3. Välj format: **Inlägg 1:1** eller **Story 9:16**.
4. Tryck på **Ladda ner** för att spara bilden, eller **Dela** för att skicka den direkt från mobilen.

Direktlänk till en viss match: `https://asajakt.github.io/hcwettern-matchaffisch/?match=<match-id>`. Länken kopieras när du trycker på **Dela** på en dator.

---

Webbsida där vem som helst i föreningen väljer lag och match och laddar ner en färdig matchaffisch (1:1 för inlägg eller 9:16 för story) med båda klubbarnas loggor.

## Hur det fungerar

- **Matcher** hämtas från föreningens kalender på svenskalag via iCal-flödet `https://cal.svenskalag.se/10862`.
- **Loggor** hämtas från klubbsidorna på stats.swehockey.se och sparas i `docs/logos/`.
- **Synk**: GitHub Actions (`.github/workflows/sync.yml`) kör `scripts/sync.py` varje natt. Om ett datum, en tid eller en arena har ändrats committas ny data och sidan uppdateras automatiskt.
- **Sidan** (`docs/index.html`) är statisk och publiceras med GitHub Pages från mappen `docs/`.

## Om en logga saknas eller blir fel

Lägg till en rad i `scripts/aliases.json`. Den kan peka på:
- klubbnamnet som det står på stats.swehockey.se: `"TAIF Löfstad": "Tranås"`
- en direkt bildadress: `"Klubb X": "https://…/logga.png"`
- `null` om klubben inte har någon logga, och då visas initialer i stället.

Ta sedan bort den felaktiga filen i `docs/logos/` och kör synken igen. Det gör du under Actions → Synka matcher → Run workflow.

## Köra lokalt

```
python scripts/sync.py
cd docs && python -m http.server
```
