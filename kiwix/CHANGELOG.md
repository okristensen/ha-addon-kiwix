# Changelog

## 1.5.7

- The viewer no longer gets extra bottom padding for the Home button, which pushed the article under the
  bottom edge and made the page jump.

## 1.5.6

- Fixes the Home button being hidden whenever the reader sits in the dashboard iframe: only an article
  inside the viewer's own iframe goes without it.
- Only successful and error pages are decorated (not redirects or skin files), to keep the viewer loading.

## 1.5.5

- Kiwix cannot search books in different languages at once ("Two or more books in different languages").
  With mixed languages the front page now offers one "All · <language>" chip per language (your own
  language first) plus each book, instead of one "All" chip.

## 1.5.4

- Searching across all books works again ("No such book" fixed): books are addressed by their library id.
- The Home button now also appears on pages a browser had cached earlier (no more 304 answers for them).

## 1.5.3

- Search filter chips with the same title (for example two Wikipedias) now show the language too.

## 1.5.2

- The "Home" button (bottom left) is now on every reader page: the viewer, articles, search results and
  error pages. Only an article shown inside the viewer goes without, since the viewer carries it.

## 1.5.1

- Articles opened on their own (for example from search results) get a "Home" button at the bottom left.
  Inside the viewer it stays hidden, because the viewer has its own toolbar.

## 1.5.0

- Search result pages are styled like the front page (cards, chips, light/dark) and the "Home" link is
  now a bar at the bottom instead of a button on top of the text.

## 1.4.2

- Front page: search suggestions show the plain article title instead of Kiwix's highlight markup.

## 1.4.1

- Front page: fix "No such book" when searching. Books are now addressed by the name Kiwix uses in
  its own links instead of the catalog name.

## 1.4.0

- Managing content is for Home Assistant administrators only. The "Manage content" button on the
  front page is hidden for everyone else, and the management page, the catalog and the download,
  cancel and delete actions are refused for non-admins (who are sent to the reader instead).
  Administrators are read from Home Assistant with the app's own token.

## 1.3.2

- Downloads now continue by themselves after the app is restarted or updated. Unfinished downloads
  are remembered in `.downloads.json` in the library folder and resumed from the partial file.

## 1.3.1

- Front page: fix broken cover images (falls back to the size the catalog lists) and remove the
  extra space at the top.

## 1.3.0

- New front page for the reader: your library as large cards with cover, language, article
  count and size, one search box across all books with suggestions while typing, and a
  "Manage content" button. Works offline and follows light/dark mode and the browser language.
- Search result pages get a small "Home" link back to the front page; the old floating link on
  the reader home page is gone.

## 1.2.3

- Let non-admin Home Assistant users open the app (`panel_admin: false`), so it can be used
  as a family app. Everyone who can open it can also manage and delete content.

## 1.2.2

- Move the "Manage content" link closer to the bottom edge so it no longer covers the footer.

## 1.2.1

- The link back to the manager is now labelled "Manage content", sits at the bottom left and
  only appears on the reader's home page.

## 1.2.0

- Publish the library as `sensor.kiwix_library` (ZIM count; files, sizes, free space and
  active downloads as attributes) so it can be shown on dashboards and used in automations.

## 1.1.1

- Add a floating link on the reader pages that leads back to the library and catalog.

## 1.1.0

- The reader now opens inside Home Assistant (served through ingress), so it works in the
  mobile app and through Home Assistant Cloud. Port 8080 keeps working as a direct link.

## 1.0.2

- Accept download links on Kiwix's load-balanced download hosts (`lb.download.kiwix.org`).

## 1.0.1

- Fix downloads being rejected when the catalog lists `http://` download links.

## 1.0.0

- Initial release: catalog browser, resumable downloads and library management,
  served by `kiwix-serve` 3.8.2.
