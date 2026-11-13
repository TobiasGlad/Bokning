# Funktionsval

Användaren har valt direktbokning, utan obligatoriskt administratörsgodkännande.
För en bilpool är tillgänglighet, tydliga hämtningsinstruktioner och återlämning
viktigare än ett godkännandesteg för varje resa.

En genomgång av [Skeddas funktionslista](https://www.skedda.com/pricing) visar
bland annat tidsmarginaler, bokningshorisonter, bokningsvillkor och incheckning.
Microsofts och Googles dokumentation ligger till grund för integrationerna;
se källorna i KALENDRAR.md.

## Byggt i denna version

Direktbokning med konfliktskydd, marginal mellan resor, max bokningslängd,
bokningshorisont, egna resurser och kalenderkopplade resurser. Dessutom privata
bilbilder, registeruppgifter, nyckelinstruktioner, serviceblockeringar, återlämning
med mätarställning, felanmälningar, administrationslogg och CSV-export.

Mobilgränssnittet och PWA-installationen gör att samma app används på dator,
iPhone och Android. En separat App Store- eller Google Play-app ingår inte.

## Fortsatt utveckling

- E-postpåminnelser och sena återlämningar, efter konfiguration av utskickstjänst.
- Automatisk extern ändringssynk med webhooks och konfliktöversikt.
- Återkommande bokningsserier med konfliktkontroll för varje tillfälle.
- Bokningskvoter, kostnadsställen och mer detaljerad beläggningsstatistik.
- Foto vid återlämning och digital skadebesiktning.
- Apple/Nextcloud via CalDAV och återkallbara kalenderprenumerationer.

Dessa punkter är utvecklingsförslag. De visas inte som aktiva funktioner i appen.
