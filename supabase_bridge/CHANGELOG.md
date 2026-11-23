## 0.2.1

Sikkerhed (fra sikkerhedsreviewet uge 46):

- Basisbilledet er låst på digest, og `aiohttp` er låst på én version (3.14.5), så en ny build ikke stille henter noget andet.
- Kørsels-id: ved start laver broen et tilfældigt id og skriver det i kolonnen `koersel` på `bro_puls` ved hvert pulsslag og læser det tilbage. Afviger det, skriver en anden som broen: en persistent notifikation og en push ("Klar-bro: fremmed skriver"), højst én pr. 30 minutter. Mangler kolonnen, logges én advarsel, og tjekket er slået fra.
- Kanarie-kommando: en kommando, der ikke står på broens liste (fx `vagt_kanarie`), afvises som før og udløser en alarm ("Klar-bro: kanarie-kommando i køen"), højst én pr. 30 minutter. Kommandoen køres aldrig. Listen over tilladte kommandoer og farten er uændret.

## 0.2.0

- `images`: copies the picture of listed `image` entities (for example a vacuum map) to an images table.
- `seconds` on an entity pattern: limit how often a fast-changing entity is written.

## 0.1.0

- First version: publishes selected entity states, a heartbeat and selected service responses to Supabase, and runs allow-listed commands from a queue table.
