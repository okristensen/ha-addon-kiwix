# Kiwix

## Getting started

1. Start the app and open **Kiwix** in the Home Assistant sidebar.
2. Use the catalog at the bottom of the page to search by language and category,
   then press **Download** on the content you want (for example *Wikipedia,
   Danish, no images*).
3. When the download finishes, the reader starts automatically. Press **Open
   Kiwix** to read inside Home Assistant, or use the direct link
   (`http://<home-assistant>:8080`) to open it in a separate browser tab.

## Who can do what

Everyone who can open the app can read. The management page, the catalog and the
download and delete actions are for Home Assistant administrators only; other users
are sent to the reader and do not see the **Manage content** button.

## Storage

Downloaded files live in `/share/kiwix` (available through the Samba share).
Partial downloads are kept as `.part` files and resumed if the app restarts.

## Dashboards

The library is published as `sensor.kiwix_library` (see the repository README for a
ready-made Markdown card).

## Updating content

Kiwix publishes new versions of its files regularly. Download the newer file from
the catalog and delete the old one from **Your library**.

## Configuration

There are no options. The direct link uses port 8080; change the host port on the
app's **Network** tab if it clashes with something else.
