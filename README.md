# Opslag – offline Wikipedia and more for Home Assistant

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fokristensen%2Fha-addon-kiwix)

**Opslag** (Danish for "look-up") turns your Home Assistant into a private,
offline reference library. It downloads Wikipedia, Wiktionary, Project Gutenberg
and other content from the [Kiwix](https://www.kiwix.org) catalog, serves it with
the official `kiwix-serve`, and wraps it in a clean, phone-friendly app that works
inside the Home Assistant app, in a browser, and on a dashboard – with no internet
needed once the content is downloaded.

> This is an unofficial community app. It is not affiliated with or endorsed by
> Kiwix or the Home Assistant project. The app's name in Home Assistant is
> "Opslag"; the repository keeps the name `ha-addon-kiwix`.

## What you get

**Reading**

- A front page with your library as cards, and one search box across everything
  you have downloaded, with suggestions as you type.
- Search results come in your own language first, with English results below.
  You never have to pick a language; pick a single book if you want to search
  only that one.
- Articles open full screen, with a back button, a button back to the front page
  and a bookmark star. Bookmarks are stored per Home Assistant user and follow you
  between devices.
- Light and dark mode, Danish and English interface (follows the browser language).

**Managing content (administrators)**

- Browse and search the official Kiwix catalog. Results are shown in your language
  first, then English, and can be narrowed by category.
- One-click, resumable downloads with progress, one at a time. A free-space check
  keeps 1 GiB free.
- **Updates:** the app checks the catalog every 12 hours for newer builds of the
  books you have, offers an **Update** button per book (or **Update all**), and
  can **update automatically**. The old file is deleted once the new one is
  complete, and bookmarks and the hidden setting move over to the new version.
- Hide a book from the front page, or delete it, from the library list.

**Home Assistant integration**

- Opens inside Home Assistant through ingress, so it works in the mobile app and
  through Home Assistant Cloud. The reader is also available directly on port 8080.
- Publishes `sensor.kiwix_library` (files, sizes, free space, downloads and
  available updates) and creates a notification when new versions are found.
- An optional dashboard card shows the whole app on a dashboard.

## Installation

1. Click the badge above, or go to **Settings → Apps → App store → ⋮ →
   Repositories** and add `https://github.com/okristensen/ha-addon-kiwix`.
2. Install **Opslag** and start it.
3. Open **Opslag** in the sidebar and pick a ZIM file from the catalog (for
   example *Wikipedia, Danish*, or a small one such as a Wiktionary to try it).
   Press **Download**.
4. When the download is done, press **Open Opslag** to read – or browse to
   `http://<home-assistant>:8080`.

Supported architectures: `aarch64`, `amd64`.

Check the size shown in the catalog before downloading: a full English Wikipedia
with images is well over 100 GB.

## Dashboard

### The whole app on a dashboard

`dashboard/kiwix-app-card.js` is a custom card that shows the full app (front page,
management and reader) on a dashboard, exactly as when it is opened from the sidebar.
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
It fills the screen, keeps clear of the status bar on phones, and avoids rubber-band
scrolling so it feels like a native app when added to the home screen.

### Library summary

The app publishes the library as `sensor.kiwix_library`: the state is the number of
ZIM files, and the attributes are `files` (`name`, `file`, `date`, `size_gb`),
`total_size_gb`, `free_space_gb`, `reader_running`, `downloads`, `updates` (books
with a newer version) and `auto_update`. A Markdown card can show it:

```yaml
type: markdown
title: Opslag
content: |-
  {% set e = 'sensor.kiwix_library' %}
  {% if states(e) in ['unknown', 'unavailable'] %}
  Opslag is not running.
  {% else %}
  {% for f in state_attr(e, 'files') -%}
  - **{{ f.name }}** · {{ f.date }} · {{ f.size_gb }} GB
  {% endfor -%}
  {% for d in state_attr(e, 'downloads') -%}
  - ⬇️ {{ d.file }} · {{ d.percent }} %
  {% endfor -%}
  {% for u in state_attr(e, 'updates') -%}
  - 🔄 Update available: {{ u.title or u.new_file }}
  {% endfor %}
  {{ state_attr(e, 'total_size_gb') }} GB in total · {{ state_attr(e, 'free_space_gb') }} GB free

  [Open Opslag](/hassio/ingress/<app slug>)
  {% endif %}
```

Replace `<app slug>` with the app's slug (shown in the address when you open the app
in Settings → Apps, e.g. `e074bf37_kiwix`). The sensor is re-published every minute,
so it comes back by itself after Home Assistant restarts.

## Notes

- ZIM files are stored in `/share/kiwix`, so they survive app updates and can be
  reached through the Samba share. Settings, hidden books and bookmarks are small
  JSON files in the same folder (`.settings.json`, `.hidden.json`, `.bookmarks.json`).
- Port 8080 is plain HTTP on your local network. Inside Home Assistant the reader
  is served through ingress, which also works remotely.
- Filenames follow the Kiwix convention (`name_YYYY-MM.zim`); the update check
  compares the date in the name with the catalog.
- Only administrators can download, update, hide or delete content. Everyone who
  can open the app can read and keep their own bookmarks.

## Development

The app is a single standard-library Python script (`kiwix/manager.py`) plus static
pages in `kiwix/web/`. Environment variables such as `KIWIX_LIBRARY_DIR`,
`KIWIX_CATALOG_URL` and `KIWIX_SERVE_BIN` allow running it outside Home
Assistant:

```sh
KIWIX_LIBRARY_DIR=/tmp/kiwix python3 kiwix/manager.py
```

Issues and pull requests are welcome.

## License

[MIT](LICENSE)
