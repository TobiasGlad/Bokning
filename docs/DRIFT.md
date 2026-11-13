# Drift

## Aktuell leverans

Källkoden, databasmigrationen, testerna och installationsfilerna är färdiga.
Den lokala databasen är initierad separat. En publik HTTPS-adress och konfiguration
i webbservern krävs innan webbappen kan användas online eller installeras på telefon.
Microsoft/Google kräver dessutom egna appregistreringar. Ingen sådan anslutning
är aktiv bara för att källkoden är publicerad på GitHub.

## Inställningar

Appen läser processmiljö först och därefter `.secrets/settings.json`. Filen
skapas av `deploy/init_local.py`, har rättighet 0600 och ligger i en 0700-katalog.
`.env.example` är dokumentation, inte en automatisk dotenv-laddare.

Ange `PUBLIC_ORIGIN` till den faktiska HTTPS-adressens ursprung, utan `/bokning/`,
och lägg värdnamnet i `ALLOWED_HOSTS`. Behåll `DEBUG=false`,
`SECURE_COOKIES=true`. Sätt `SSL_REDIRECT=true` när HTTPS är konfigurerat.
`TRUST_PROXY_HTTPS=true` kräver att en betrodd proxy alltid skriver över
`X-Forwarded-Proto`. Sätt `HSTS_SECONDS` först när hela värden fungerar med HTTPS.
Subdomänomfattande HSTS och browser-preload är avsiktligt inte aktiverade;
Djangos rekommendationer W005/W021 är därför undertryckta. Sådana ändringar
berör hela domänen och kräver en separat kontroll av övriga projekt.

Appen stöder en installation och en organisation med flera användare. Den är
inte en plattform där oberoende organisationer delar samma databas.

## Server

```sh
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python -m gunicorn config.wsgi:application -c deploy/gunicorn.conf.py
```

Gunicorn lyssnar på `127.0.0.1:8010`. Anslut den befintliga HTTPS-servern till
`/bokning/` utan att ta bort prefixet. En exempelkonfiguration för Apache finns
i `deploy/apache-bokning.conf`. Anpassa konfigurationen till Plesk om Plesk
hanterar domänen. Behåll övriga projekt och deras webbserverregler.

Kopiera statiska filer till en separat webbserverläsbar katalog och anpassa
Alias. Gör inte `/root` allmänt läsbar. Bilder läses via den inloggningsskyddade
applikationen och får inte serveras direkt från uppladdningskatalogen.

`deploy/bokning.service` är en mall för den begärda sökvägen under `/root`.
Installera servicefilen i systemd och aktivera den först efter granskning av
den faktiska servermiljön. För en separat driftanvändare: flytta arbetskopia
och privat data till kataloger som driftanvändaren äger och anpassa sökvägarna.
Ingen systemd- eller webbserverkonfiguration installeras av Python-skripten.

Åtkomstloggar för `/bokning/` ska logga URL-sökväg utan frågesträng. OAuth-
returer innehåller tillfälliga auktoriseringskoder. Gunicorn-mallen använder
`%(U)s` för detta; konfigurera motsvarande i den yttre proxyn.

## Kalenderåterförsök

Administratören kan försöka synkronisera via webbgränssnittet. För automatisk
återhämtning kan en lokal schemaläggare köra varje minut:

```sh
cd /root/bokning
.venv/bin/python manage.py retry_calendar_sync
```

En väntande bokning är inte bekräftad och håller samtidigt tiden lokalt.
Avbokningen frigör tiden först när eventuell extern post har tagits bort.
Stabila externa händelse-ID:n (Google) och transactionId (Microsoft) används
vid återförsök. Okänt resultat från Microsoft kan behöva utredas av en administratör
om kalendertjänsten inte längre kan slutföra det ursprungliga försöket.

## Databas, backup och uppdateringar

SQLite används med IMMEDIATE-transaktioner, skrivarserialisering och 30 sekunders
lås-timeout. Kör installationen på en värd med lokal disk. Dela inte SQLite-filen
mellan flera servermaskiner eller på ett nätfilsystem. Ta en SQLite-konsistent
backup och skyddad kopia av `private/uploads` och `.secrets` före uppdateringar.
En databasbackup är separat från GitHub-rutinen.

Kör tester, `makemigrations --check --dry-run` och `check --deploy` inför driftsättning.
CI kör samma grundkontroller med en isolerad testdatabas. Vid lokal HTTP-utveckling
är HTTPS-redirect och HSTS avstängda som standard; aktivera dem i drift och kör:

```sh
SSL_REDIRECT=true HSTS_SECONDS=31536000 .venv/bin/python manage.py check --deploy --fail-level WARNING
```

Kontrollera efter HTTPS-publicering inloggning, uppladdning, två samtidiga bokningar,
extern kalenderkonflikt, avbokning och installation på både iPhone och Android.
Automatiska tester ersätter inte en riktig integrationstest med er tenant och dess behörigheter.
