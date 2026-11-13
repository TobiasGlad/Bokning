# Arbetsregler för Bokning

Projektets lokala katalog är `/root/bokning`. Vid publicering online ska
applikationen ligga under `/bokning/`. Ta hänsyn till sökvägen för länkar,
statiska resurser och eventuell routing.

## Automatisk GitHub-uppdatering

Användaren har begärt samma leveransrutin som för Basen: uppdatera GitHub
automatiskt med färdiga ändringar som en del av varje avslutad arbetsuppgift,
utan att be om samma godkännande igen.

- Repository är `TobiasGlad/Bokning`, ordinarie gren är `main`.
- Använd den anslutna GitHub-tjänsten om lokal Git-autentisering saknas.
- Läs aktuell fjärrversion och bevara andras ändringar. Använd fast-forward
  eller en ref-uppdatering med förväntad tidigare SHA. Gör ingen force-push.
- Kör relevanta kontroller före publicering och granska exakt vilka filer
  och vilket innehåll som ska publiceras. Följ `.gitignore` även via API.
- Publicera aldrig databaser, personuppgifter, uppladdningar, säkerhetskopior,
  hemligheter, nycklar, sessionsuppgifter, loggar eller virtuella miljöer.
- Verifiera efter publicering rätt repository, gren och innehåll. Kontrollera
  GitHub Actions när relevant och skilj startade kontroller från godkända.
- Skapa ingen tom commit när allt redan är synkroniserat.
- Rapportera eventuella hinder och påstå aldrig att osynkroniserade ändringar
  finns på GitHub.
