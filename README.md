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
- Danish and English interface, light and dark mode

## Installation

1. Click the badge above, or go to **Settings → Apps → App store → ⋮ →
   Repositories** and add `https://github.com/okristensen/ha-addon-kiwix`.
2. Install **Kiwix** and start it.
3. Open **Kiwix** in the sidebar, pick a ZIM file from the catalog and press
   **Download**.
4. Press **Open Kiwix** to read, or browse directly to `http://<home-assistant>:8080`.

Supported architectures: `aarch64`, `amd64`.

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
