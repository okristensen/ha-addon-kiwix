-- Example schema for the Supabase bridge (the one the author runs; table and column names are Danish).
-- The bridge needs these column names. Adapt the app names and the allowed commands to your own setup.
-- tilstande = states, puls = heartbeat, kommandoer = commands, adgang = access, enheder = bridge users.

-- Klar-bro: familie-apps uden fjernadgang til HA (se docs/klar-bro.md).
-- En lille HA-app (broen) holder én udgående forbindelse hertil: den skriver de tilstande, apps'ene viser,
-- og henter kommandoer fra en kø. Der er ingen vej ind i HA. Broen logger ind som sin egen Supabase-bruger
-- (ikke service-nøglen), så en kompromitteret HA kun kan røre disse tabeller.
-- Ude må apps'ene kun se – bortset fra seks støvsuger-kommandoer (besluttet af Ole 21/11 2026).

-- 1. Hvem er broen, og hvem må bruge hvilken app. Rækker lægges ind med SQL af ejeren, ikke fra appen.
create table public.bro_enheder (
  user_id  uuid primary key references auth.users on delete cascade,
  navn     text not null,
  oprettet timestamptz not null default now()
);
alter table public.bro_enheder enable row level security;
-- ingen politikker: kun service-rollen og SQL Editor

create table public.bro_adgang (
  user_id  uuid not null references auth.users on delete cascade,
  app      text not null check (app in ('stoevsuger', 'hvidevarer', 'energi')),
  oprettet timestamptz not null default now(),
  primary key (user_id, app)
);
alter table public.bro_adgang enable row level security;
create policy "bro_adgang: se egne" on public.bro_adgang
  for select to authenticated using (user_id = (select auth.uid()));

-- 2. Hjælpefunktioner til politikkerne (tabellerne ovenfor er lukkede, så opslaget sker som ejer).
create function public.bro_er_bro() returns boolean
  language sql stable security definer set search_path = ''
  as $$ select exists (select 1 from public.bro_enheder e where e.user_id = (select auth.uid())) $$;

create function public.bro_mine_apps() returns text[]
  language sql stable security definer set search_path = ''
  as $$ select coalesce(array_agg(a.app), '{}') from public.bro_adgang a where a.user_id = (select auth.uid()) $$;

revoke all on function public.bro_er_bro() from public, anon;
revoke all on function public.bro_mine_apps() from public, anon;
grant execute on function public.bro_er_bro() to authenticated;
grant execute on function public.bro_mine_apps() to authenticated;

-- 3. Tilstande: kopi af de HA-entiteter, apps'ene viser. Kun broen skriver.
create table public.bro_tilstande (
  entity_id text primary key check (length(entity_id) between 3 and 120),
  apps      text[] not null check (cardinality(apps) between 1 and 5),
  tilstand  jsonb not null check (pg_column_size(tilstand) < 20000),
  opdateret timestamptz not null default now()
);
alter table public.bro_tilstande enable row level security;
create policy "bro_tilstande: læs egne apps" on public.bro_tilstande
  for select to authenticated using (apps && public.bro_mine_apps() or public.bro_er_bro());
create policy "bro_tilstande: broen opretter" on public.bro_tilstande
  for insert to authenticated with check (public.bro_er_bro());
create policy "bro_tilstande: broen retter" on public.bro_tilstande
  for update to authenticated using (public.bro_er_bro()) with check (public.bro_er_bro());
create policy "bro_tilstande: broen sletter" on public.bro_tilstande
  for delete to authenticated using (public.bro_er_bro());

-- 4. Puls: én række, så apps'ene kan vise "Huset svarer ikke".
create table public.bro_puls (
  id      int primary key check (id = 1),
  sidst   timestamptz not null default now(),
  version text check (length(version) <= 40)
);
alter table public.bro_puls enable row level security;
create policy "bro_puls: læs med adgang" on public.bro_puls
  for select to authenticated using (cardinality(public.bro_mine_apps()) > 0 or public.bro_er_bro());
create policy "bro_puls: broen opretter" on public.bro_puls
  for insert to authenticated with check (public.bro_er_bro());
create policy "bro_puls: broen retter" on public.bro_puls
  for update to authenticated using (public.bro_er_bro()) with check (public.bro_er_bro());

-- 5. Kommandokø. Listen over tilladte kommandoer står her OG i broen; broen har det sidste ord.
create table public.bro_kommandoer (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null default auth.uid() references auth.users on delete cascade,
  app        text not null,
  kommando   text not null,
  argumenter jsonb not null default '{}'::jsonb,
  status     text not null default 'ny' check (status in ('ny', 'udfoert', 'afvist', 'udloebet')),
  svar       text check (length(svar) <= 300),
  oprettet   timestamptz not null default now(),
  udloeber   timestamptz not null default now() + interval '30 seconds',
  afgjort    timestamptz,
  constraint bro_kommandoer_tilladt check (
    app = 'stoevsuger' and kommando in ('start', 'pause', 'stop', 'dock', 'locate', 'clean_rooms')
  ),
  constraint bro_kommandoer_argumenter check (
    case when kommando = 'clean_rooms'
      then jsonb_typeof(argumenter -> 'rum') = 'array'
       and jsonb_array_length(argumenter -> 'rum') between 1 and 30
       and pg_column_size(argumenter) < 600
      else argumenter = '{}'::jsonb
    end
  ),
  constraint bro_kommandoer_levetid check (udloeber <= oprettet + interval '60 seconds')
);
create index bro_kommandoer_nye on public.bro_kommandoer (oprettet) where status = 'ny';
create index bro_kommandoer_bruger on public.bro_kommandoer (user_id, oprettet desc);
alter table public.bro_kommandoer enable row level security;

create policy "bro_kommandoer: læg i køen" on public.bro_kommandoer
  for insert to authenticated with check (
    user_id = (select auth.uid())
    and app = any (public.bro_mine_apps())
    and status = 'ny' and svar is null and afgjort is null
  );
create policy "bro_kommandoer: se egne, broen ser alle" on public.bro_kommandoer
  for select to authenticated using (user_id = (select auth.uid()) or public.bro_er_bro());
create policy "bro_kommandoer: broen afgør" on public.bro_kommandoer
  for update to authenticated using (public.bro_er_bro()) with check (public.bro_er_bro());

-- Broen må kun rette udfaldet, ikke hvad der blev bedt om.
revoke update on public.bro_kommandoer from authenticated, anon;
grant update (status, svar, afgjort) on public.bro_kommandoer to authenticated;

-- Loft og oprydning: højst 20 kommandoer pr. bruger pr. minut, tidspunkterne sættes af databasen,
-- og kommandoer ældre end 7 dage slettes.
create function public.bro_kommando_foer() returns trigger
  language plpgsql security definer set search_path = ''
  as $$
begin
  new.oprettet := now();
  new.udloeber := now() + interval '30 seconds';
  if (select count(*) from public.bro_kommandoer k
      where k.user_id = new.user_id and k.oprettet > now() - interval '1 minute') >= 20 then
    raise exception 'For mange kommandoer – vent et øjeblik' using errcode = 'P0001';
  end if;
  delete from public.bro_kommandoer k where k.oprettet < now() - interval '7 days';
  return new;
end $$;
revoke all on function public.bro_kommando_foer() from public, anon, authenticated;
create trigger bro_kommando_foer before insert on public.bro_kommandoer
  for each row execute function public.bro_kommando_foer();

-- Uden login er der ingen adgang overhovedet (heller ikke til at udløse triggeren).
revoke all on public.bro_enheder, public.bro_adgang, public.bro_tilstande, public.bro_puls, public.bro_kommandoer from anon;

-- 6. Realtime: broen lytter efter nye kommandoer, apps'ene efter udfald og tilstande. RLS gælder også dér.
alter publication supabase_realtime add table public.bro_kommandoer, public.bro_tilstande, public.bro_puls;

-- 7. Billeder (fra version 0.2.0): billedet bag image-entiteter, fx støvsugerens kort, som base64. Kun broen skriver.
create table public.bro_billeder (
  id        text primary key check (id like 'image.%' and length(id) <= 120),
  apps      text[] not null check (cardinality(apps) between 1 and 5),
  type      text not null check (type in ('image/png', 'image/jpeg', 'image/webp', 'image/gif')),
  data      text not null check (length(data) <= 600000),
  opdateret timestamptz not null default now()
);
alter table public.bro_billeder enable row level security;
create policy "bro_billeder: læs egne apps" on public.bro_billeder
  for select to authenticated using (apps && public.bro_mine_apps() or public.bro_er_bro());
create policy "bro_billeder: broen opretter" on public.bro_billeder
  for insert to authenticated with check (public.bro_er_bro());
create policy "bro_billeder: broen retter" on public.bro_billeder
  for update to authenticated using (public.bro_er_bro()) with check (public.bro_er_bro());
create policy "bro_billeder: broen sletter" on public.bro_billeder
  for delete to authenticated using (public.bro_er_bro());
revoke all on public.bro_billeder from anon;
