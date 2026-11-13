# Microsoft, Google och kalendrar

## Microsoft 365

Registrera en webbapp i Microsoft Entra. Använd en specifik organisations-tenant;
appen är avsedd för en organisation. Ange tenant-ID, klient-ID och klienthemlighet
i serverns privata inställningar (`MICROSOFT_TENANT`, `MICROSOFT_CLIENT_ID`,
`MICROSOFT_CLIENT_SECRET`). Använd inte `common`, `organizations` eller `consumers`.

Registrera exakt returadress:

```text
https://er-domän.se/bokning/oauth/microsoft/callback/
```

Inloggning begär `openid email profile`. Kalenderanslutning begär dessutom
`offline_access`, `User.Read`, `Calendars.ReadWrite`, `Calendars.ReadWrite.Shared`
och `Place.Read.All`. Administratörssamtycke kan behövas enligt tenantens regler.
Det anslutna kontot måste ha behörighet att läsa och skriva i berörda resursbrevlådor.
Appen använder delegerad åtkomst, inte generell appbehörighet till alla brevlådor.

Under Integrationer kan administratören hämta skrivbara kalendrar eller Microsoft
Places-rum. Utrustningsbrevlådor som används för exempelvis bilar kan kopplas
manuellt på resursen: välj anslutning, ange resursens e-post och kalender-ID `default`.
Places rumlista är inte en generell lista över alla Exchange-utrustningsbrevlådor.
Kalenderposten skrivs direkt i den valda kalendern; detta är ingen mötesinbjudan
som väntar på Exchange-resursens automatiska acceptans.

## Google

Skapa OAuth-klient av typen webbapplikation i Google Cloud, aktivera Google
Calendar API och konfigurera samtyckessidan. Ange `GOOGLE_CLIENT_ID` och
`GOOGLE_CLIENT_SECRET` privat på servern. Lägg till exakt returadress:

```text
https://er-domän.se/bokning/oauth/google/callback/
```

Inloggning använder `openid email profile`. Kalenderkoppling begär även
`https://www.googleapis.com/auth/calendar`, offlineåtkomst och samtycke för att
kunna uppdatera utgångna token. En produktionsapp kan behöva Googles verifiering;
testlägets användarbegränsningar och tokenlivslängd styrs av Google.
Kontot behöver skrivrättigheter till resurskalendrarna.

Hämta skrivbara kalendrar i gränssnittet. En känd Workspace-resurskalender kan
anges manuellt med sitt kalender-ID. Google Admin SDK:s organisationsregister
över resurser används inte i denna version.

## Inloggningsregler

Befintliga konton kopplas genom att användaren först loggar in lokalt och väljer
Koppla Microsoft/Google under Mitt konto. Enbart en matchande e-postadress ger
inte åtkomst till ett befintligt konto, särskilt inte ett administratörskonto.

Nya SSO-konton skapas som vanliga användare endast om deras domän finns i
`SSO_ALLOWED_DOMAINS`. Standardvärdet är tomt och tillåter ingen automatisk
registrering. Microsoft använder en specifik tenant och verifierad tokenissuer;
Google kräver även verifierad e-post. Avstängda användare nekas åtkomst.

Kalenderkoppling är separat från inloggning. Endast administratörer kan ansluta
kalendrar och importera resurser. Återanslut samma leverantör och konto för att
förnya en befintlig anslutning utan att förlora resurskopplingarna.

## Bokning och tillgänglighet

Lokala bokningar och serviceblockeringar kontrolleras inom en databastransaktion.
För kopplade resurser kontrolleras externa upptagna kalenderhändelser, inklusive
återkommande instanser, innan en extern post skapas. Tidsmarginalen efter en
bokning läggs även till i den externa kalenderposten. Lediga eller borttagna
externa händelser blockerar inte. Kalenderfel stoppar bekräftelsen.

Veckovyn visar lokala bokningar och service. Tidsfiltrering på översikten gör
en extern tillgänglighetskontroll; resurskort utan vald tid lovar inte att den
externa kalendern är ledig. Externa möten kopieras inte till den lokala databasen.

Lokala och externa system har ingen gemensam atomär transaktion. En användare
kan hinna boka direkt i Outlook/Google mellan tillgänglighetskontroll och skrivning.
För garanterat enhetlig bokningspolicy bör bilbokningar göras i Bokning och
externa skrivbehörigheter begränsas. Serviceblockeringar gäller lokalt och måste
också läggas in externt om andra system får boka samma resurs. Automatisk
konfliktreparation, webhooks och spegling av externa ändringar ingår inte ännu.

Kalenderfilen som användaren laddar ned är en engångsexport. Den är ingen
automatisk prenumeration och uppdateras inte efter en avbokning.

## Primärkällor

- [Microsoft Graph: skapa kalenderhändelse](https://learn.microsoft.com/en-us/graph/api/calendar-post-events?view=graph-rest-1.0)
- [Microsoft Graph: Places-listor och behörigheter](https://learn.microsoft.com/en-us/graph/api/place-list?view=graph-rest-1.0)
- [Microsoft Graph: event och transactionId](https://learn.microsoft.com/en-us/graph/api/resources/event?view=graph-rest-1.0)
- [Google OAuth för webbservrar](https://developers.google.com/identity/protocols/oauth2/web-server)
- [Google Calendar: skapa händelser och egna ID:n](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert)
- [Authlib: webbklienter och ID-tokenvalidering](https://docs.authlib.org/en/latest/oauth2/client/web/)
