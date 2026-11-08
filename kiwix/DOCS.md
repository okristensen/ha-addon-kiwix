# Opslag

Opslag is an offline reference library: it downloads content from the Kiwix catalog
(Wikipedia, Wiktionary, books and more) and lets you read and search it from Home
Assistant, with no internet needed afterwards.

## Getting started

1. Start the app and open **Opslag** in the Home Assistant sidebar.
2. Use the catalog at the bottom of the page. Results are shown in your language
   first, with English below. Narrow them by category, then press **Download** on
   the content you want (for example *Wikipedia, Danish*).
3. When the download finishes, the reader starts automatically. Press **Open
   Opslag** to read inside Home Assistant, or use the direct link
   (`http://<home-assistant>:8080`) to open it in a separate browser tab.

## Reading

- The front page lists your books. The search box searches all of them: hits in
  your own language come first and English hits follow below. Pick one book in the
  row under the search box to search only that.
- In an article, the round arrow goes back, **Hjem** / **Home** returns to the
  front page, and the star saves the article as a bookmark. Bookmarks are listed on
  the front page and belong to your Home Assistant user.

## Who can do what

Everyone who can open the app can read and keep bookmarks. The management page,
the catalog and the download, update, hide and delete actions are for Home
Assistant administrators only. Other users are sent to the reader and do not see
the **Manage content** button.

## Updating content

Kiwix publishes new versions of its files regularly. Opslag checks the catalog
every 12 hours (and when you press **Check now**) for newer versions of the books
you have downloaded.

- A book with a newer version shows **Update available** with an **Update**
  button. Administrators also see the number of updates on the front page.
- **Update automatically** downloads new versions by itself when there is room
  for them: the old file is kept until the new one is complete, so both must fit
  with 1 GiB to spare.
- When the new version is in place, the old file is deleted, and your bookmarks and
  the hidden setting move to the new version.
- Home Assistant shows a notification when new versions are found. This setting is
  separate from Home Assistant's own automatic updates of the app itself.

## Storage

Downloaded files live in `/share/kiwix` (available through the Samba share).
Partial downloads are kept as `.part` files and resumed if the app restarts.
Settings, hidden books and bookmarks are small JSON files in the same folder.

## Dashboards

The library, downloads and available updates are published as
`sensor.kiwix_library`, and `kiwix-app-card.js` in the repository shows the whole
app on a dashboard (see the repository README for both).

## Configuration

There are no options. The direct link uses port 8080; change the host port on the
app's **Network** tab if it clashes with something else.
