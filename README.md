# Bokning

Mobilanpassad bilpool och resursbokning byggd med Django. Installerbar webbapp
(PWA) med svensk administration. Alla appvägar, tillgångar och OAuth-returer
ligger under `/bokning/`.

- Lokal projektmapp: `/root/bokning`
- Sökväg vid framtida publicering online: `/bokning/`
- GitHub: https://github.com/TobiasGlad/Bokning
- Ordinarie gren: `main`

Färdiga ändringar kontrolleras och uppdateras automatiskt på GitHub enligt
[AGENTS.md](AGENTS.md). Publicering av källkod till GitHub är separat från
driftsättning av applikationen online.

## Funktioner

- Bilar, minibussar och egna resurser med privata bilder, registreringsnummer,
  drivmedel, platser, växellåda, räckvidd, mätarställning och nyckelinstruktioner.
- Direktbokning, tidsfilter, bokningshistorik, veckokalender, avbokning,
  återlämning, felanmälan, serviceblockeringar och CSV-rapport för administratörer.
- Skydd mot lokala dubbelbokningar, marginaler mellan bokningar, maximal
  bokningstid och bokningshorisont. Alla tider hanteras med Europe/Stockholm och UTC.
- Administratörer skapar användare och kan stänga av konton eller byta lösenord.
- Enhet väljs från en förvalslista vid bokning och visas i bokningsdetaljer,
  bokningslistor och CSV-rapporten. Administratören hanterar listan under
  Resurser & drift → Enheter. Enheter kan döljas för nya bokningar utan att
  äldre bokningar förlorar sin koppling. Valet är frivilligt och befintliga
  bokningar fungerar utan enhet. Inga organisationsspecifika enheter ingår i källkoden.
- Microsoft- och Google-inloggning med OpenID Connect via Authlib, state, nonce
  och PKCE. Befintliga konton länkas explicit efter inloggning, aldrig enbart via e-post.
- Separat OAuth-samtycke för kalenderkopplingar. Hämta och importera kalendrar,
  koppla Microsoft-resursbrevlådor manuellt och skapa externa kalenderposter.
- Krypterade kalendertoken, uppdatering av utgångna token och återförsök för väntande synk.
- Kalenderfil för Apple Kalender, Outlook och andra iCalendar-kompatibla system.
- PWA-manifest, appikoner och offlinesida. Inga personliga sidor eller bokningar
  sparas i service workerns cache. Bokning kräver alltid nätanslutning.

## Starta lokalt

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python deploy/init_local.py
.venv/bin/python manage.py migrate
.venv/bin/python manage.py create_local_admin
SECURE_COOKIES=false .venv/bin/python manage.py runserver 127.0.0.1:8010
```

Öppna `http://127.0.0.1:8010/bokning/`. Skapa ingen ny administratör om en redan
finns i den privata installationsdatabasen. Inga riktiga konton eller lösenord
ingår i repositoryt. Lokal HTTP används endast för utveckling på loopback.

```sh
.venv/bin/python manage.py test fleet
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
```

Vid första installationen skapar `deploy/init_local.py` privata nycklar i
`.secrets/settings.json`. Säkerhetskopiera nycklarna tillsammans med databasen
på ett skyddat ställe; krypterade kalendertoken kan inte läsas utan rätt nyckel.
GitHub innehåller varken databasen, administratörskontot, lösenordshashar,
uppladdningar eller privata nycklar.

Se [drift och installation](docs/DRIFT.md), [kalenderkopplingar](docs/KALENDRAR.md)
och [funktionsval och fortsättning](docs/FUNKTIONER.md).
