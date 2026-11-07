# Kiwix for Home Assistant

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fokristensen%2Fha-addon-kiwix)

Read Wikipedia and other [Kiwix](https://www.kiwix.org) content offline, straight
from your Home Assistant. Pick what you want from the Kiwix catalog in a small
built-in web page, and the app downloads it and serves it on your local network.

> This is an unofficial community app. It is not affiliated with or endorsed by
> Kiwix or the Home Assistant project.

## Features

- Browse and search the official Kiwix catalog by language and category
- One-click, resumable downloads with progress; one download at a time
- Library view with sizes and free disk space; delete what you no longer need
- Serves everything with the official `kiwix-serve`, restarted automatically when
  the library changes
- Management page and reader both open inside Home Assistant (ingress), so they
  work in the mobile app and through Home Assistant Cloud; the reader is also
  available directly on port 8080
- A front page for the reader with your library as cards, one search across all
  books with suggestions, and a button to the management page
- Danish and English interface, light and dark mode

## Installation

1. Click the badge above, or go to **Settings → Apps → App store → ⋮ →
   Repositories** and add `https://github.com/okristensen/ha-addon-kiwix`.
2. Install **Kiwix** and start it.
3. Open **Kiwix** in the sidebar, pick a ZIM file from the catalog and press
   **Download**.
4. Press **Open Kiwix** to read, or browse directly to `http://<home-assistant>:8080`.

Supported architectures: `aarch64`, `amd64`.

## Dashboard

### The whole app on a dashboard

`dashboard/kiwix-app-card.js` is a custom card that shows the full app (library,
catalog and reader) on a dashboard, exactly as when it is opened from the sidebar.
Home Assistant only serves an app's page to browsers that hold an ingress session, so
a plain iframe fails with `401`; the card creates and renews that session itself.

1. Add `kiwix-app-card.js` as a dashboard resource of type **JavaScript module**
   (Settings → Dashboards → ⋮ → Resources, or copy it to `/config/www/` and use
   `/local/kiwix-app-card.js`).
2. Add a view of type **Panel** with this card:

   ```yaml
   type: custom:kiwix-app-card
   ```

The card finds the app by itself (or set `app: <slug>`), and needs an admin user.

### Library summary

The app publishes the library as `sensor.kiwix_library`: the state is the number of
ZIM files, and the attributes list the files (`name`, `file`, `date`, `size_gb`),
`total_size_gb`, `free_space_gb`, `reader_running` and running `downloads`. Add a
**Markdown** card to a dashboard to show it:

```yaml
type: markdown
title: Kiwix
content: |-
  {% set e = 'sensor.kiwix_library' %}
  {% if states(e) in ['unknown', 'unavailable'] %}
  Kiwix is not running.
  {% else %}
  {% for f in state_attr(e, 'files') -%}
  - **{{ f.name }}** · {{ f.date }} · {{ f.size_gb }} GB
  {% endfor -%}
  {% for d in state_attr(e, 'downloads') -%}
  - ⬇️ {{ d.file }} · {{ d.percent }} %
  {% endfor %}
  {{ state_attr(e, 'total_size_gb') }} GB in total · {{ state_attr(e, 'free_space_gb') }} GB free

  [Open Kiwix](/hassio/ingress/<app slug>)
  {% endif %}
```

Replace `<app slug>` with the app's slug (shown in the address when you open the app
in Settings → Apps, e.g. `e074bf37_kiwix`). The sensor is re-published every minute,
so it comes back by itself after Home Assistant restarts.

## Notes

- ZIM files are stored in `/share/kiwix`, so they survive app updates and can be
  reached through the Samba share. Check the size shown in the catalog before
  downloading: a full English Wikipedia with images is well over 100 GB.
- Port 8080 is plain HTTP on your local network. Inside Home Assistant the reader
  is served through ingress, which also works remotely.
- Filenames follow the Kiwix convention (`name_YYYY-MM.zim`). To update a ZIM,
  download the newer version and delete the old one.

## Development

The app is a single standard-library Python script (`kiwix/manager.py`) plus a
static page in `kiwix/web/`. Environment variables such as `KIWIX_LIBRARY_DIR`,
`KIWIX_CATALOG_URL` and `KIWIX_SERVE_BIN` allow running it outside Home
Assistant:

```sh
KIWIX_LIBRARY_DIR=/tmp/kiwix python3 kiwix/manager.py
```

## License

[MIT](LICENSE)
