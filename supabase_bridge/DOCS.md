# Klar-bro (Supabase bridge)

Lets a web app show and control a few things in Home Assistant **without any
remote access to Home Assistant**. The bridge only makes outbound connections:

- it copies the state of the entities you list into a Supabase table,
- it writes a heartbeat, so your app can show "the house is offline",
- it runs commands that signed-in users put in a queue table, but only the
  commands on its own allow-list, with typed and range-checked arguments.

Your app talks to Supabase; the bridge talks to Supabase; nothing talks to
Home Assistant from outside. You can keep Nabu Casa remote access and every
port closed.

## What the bridge will and will not do

- It runs **only** the commands in the `commands` option. A row in the queue
  that names anything else is marked `afvist` (rejected). The database can
  have its own checks, but the list in this app has the last word.
- Arguments are whole numbers or lists of whole numbers, each with a range you
  set. Free text never reaches a service call.
- A command older than its `udloeber` (expires) time is never run.
- It never publishes the attributes `access_token`, `entity_picture`,
  `entity_picture_local`, `token` or `stream_source`.
- It signs in as an ordinary Supabase user and depends on row level security.
  Do **not** give it the service-role key.

## Setup

1. **Database.** Run `schema.example.sql` (in this folder) in your Supabase
   project, after adapting app names and allowed commands. It creates the
   tables, the row level security rules and the realtime publication.
2. **Bridge user.** In Supabase → Authentication → Users, add a user for the
   bridge (email + a long random password). Then register it:
   `insert into bro_enheder (user_id, navn) select id, 'bridge' from auth.users where email = '<the bridge email>';`
3. **Access for people.** For each person and app:
   `insert into bro_adgang (user_id, app) select id, '<app>' from auth.users where email = '<their email>';`
4. **Configure the app** (Configuration tab), then start it and read the log:
   it lists every allowed command at start.

## Configuration

```yaml
supabase_url: https://<project>.supabase.co
supabase_anon_key: <the publishable/anon key>
email: <the bridge user's email>
password: <the bridge user's password>
entities:
  - pattern: vacuum.robot          # exact id or a glob such as sensor.robot_*
    apps: [vacuum]                 # which apps may read it
  - pattern: sensor.*_power
    apps: [energy]
    seconds: 15                    # optional: at most one write per entity every 15 s (default 2)
images:                            # optional: copy the picture of image entities
  - entity_id: image.robot_map     # exact id, no wildcards
    apps: [vacuum]
    seconds: 60                    # optional: at most one copy per minute (default 60, minimum 10)
commands:
  - app: vacuum
    command: start
    service: vacuum.start
    entity_id: vacuum.robot
  - app: vacuum
    command: clean_rooms
    service: vacuum.send_command
    entity_id: vacuum.robot
    data: '{"command":"app_segment_clean","params":[{"segments":"$rooms","repeat":"$times"}]}'
    args: '{"rooms":{"type":"int_list","max_items":30,"min":0,"max":100000},"times":{"type":"int","min":1,"max":3,"default":1}}'
responses:
  - id: bridge.robot_rooms         # published like an entity
    apps: [vacuum]
    service: roborock.get_maps     # a service that returns a response
    entity_id: vacuum.robot
    interval_minutes: 60
max_commands_per_minute: 30
log_level: info
```

- `data` is the service data as a JSON string. A string value `"$name"` is
  replaced by the validated argument `name`.
- `args` declares each argument: `{"type":"int","min":…,"max":…,"default":…}`
  or `{"type":"int_list","max_items":…,"min":…,"max":…}`. An argument that is
  not declared is rejected.
- A pattern must name a domain (`sensor.robot_*`, not `*`).
- `seconds` on an entity pattern is the shortest time between two writes of
  the same entity. Use it for values that change every second (power
  meters); the latest value is always the one written. When several
  patterns match, the largest value wins.
- `images` copies the picture behind an `image` entity to the images table
  as base64, whenever the entity's state (its timestamp) has changed. The
  entity's own state is published too. Pictures over 400 kB, and anything
  that is not PNG, JPEG, WebP or GIF, are skipped. The signed picture URL
  (`entity_picture`) is never published.
- Optional `states_table`, `commands_table`, `heartbeat_table`,
  `images_table` override the table names (`bro_tilstande`,
  `bro_kommandoer`, `bro_puls`, `bro_billeder`).

## How fast is it

The bridge listens on Supabase Realtime and picks up a new command in well
under a second. If Realtime is unavailable it polls every 3 seconds, so
commands still arrive. State changes are written within about a second, at
most once every 2 seconds per entity.

## Turning it off

Stop the app. No command is run while it is stopped, the heartbeat goes
stale, and queued commands expire by themselves.
