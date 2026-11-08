# Changelog

## 1.11.1

- Article buttons: back is now bottom left, the former "Forside" button is called "Hjem" (with a house icon) and sits in the middle, and the bookmark star stays on the right. The search results page uses the same "Hjem" button.

## 1.11.0

- Front page: no more choosing a language for search. "Alle" searches your own language first, and the English books are searched separately and shown below ("På engelsk"), both in the suggestions and on the search results page. The single books are still listed for searching just one.
- Articles have a round back button next to "Forside".

## 1.10.1

- Catalog search no longer has a language picker: results are shown in your own language first, with English results below them.

## 1.10.0

- Content updates: the add-on checks the Kiwix catalog every 12 hours (and on "Check now") for newer builds of the books you have downloaded. Books with a newer build show "Update available" and an "Update" button on the management page, and administrators see an update count on the front page.
- Optional "Update automatically": new builds are downloaded when there is room for them (the old file stays until the new one is complete), then the old file is deleted. Bookmarks and the hidden flag move to the new build.
- A Home Assistant notification is created when updates are found, and `sensor.kiwix_library` gets `updates` and `auto_update` attributes. The setting is stored in `.settings.json` in the library folder.

## 1.9.1

- The "Flere apps" card at the bottom of the front page now has the same card look and margins as the books, which fixes the sideways scrolling.

## 1.9.0

- Bookmarks: a star button at the bottom right of every article (next to "Forside") saves it to your bookmarks, and tapping it again removes it.
- The front page lists your bookmarks above the library, with a button to remove each one. Bookmarks are stored per Home Assistant user in `.bookmarks.json` in the library folder, so they follow you between devices.

## 1.8.1

- Front page: the search bar now sticks to the top when you scroll, and the big logo shrinks into a small one beside it.
- The footer now says "Indhold leveret af Kiwix" ("Content provided by Kiwix") instead of "Drevet af".

## 1.8.0

- Loading state for search suggestions: while suggestions are being fetched, the front page search shows a spinner and "Søger…" in the list, and the search bar in articles shows a spinner.

## 1.7.9

- The top of an article is no longer hidden under the search bar: the page makes room for the bar, whatever its height.

## 1.7.8

- Articles now run all the way down to the bottom edge of the screen on iPhone; the "Forside" button stays clear of the home indicator.

## 1.7.7

- The search bar at the top of articles now always stays visible, also when scrolling down.

## 1.7.6

- Fixes the app configuration, which was empty in 1.7.5 so that the update could not be installed.
- Articles in dark mode now have a dark page background behind the text, so no white strip shows at the bottom while scrolling fast.

## 1.7.5

- The app is now pinned to the screen on iPhone, so no strip of the dashboard shows at the bottom while scrolling.

## 1.7.4

- Steadier scrolling in the app on iPhone: the page no longer bounces or drags the dashboard behind it along, and articles no longer slide under the status bar.
- The empty white strip at the bottom of the app now has the same colour as the page.
- The "Forside" button on articles and search results is orange like the rest of the app, instead of blue.

## 1.7.3

- The app now uses orange (logo, buttons, chips and focus colour) to match its icon in the family apps, instead of blue.

## 1.7.2

- The app is now called "Opslag" everywhere it is shown (app name, sidebar panel, page titles and headings). The Kiwix catalog is still called Kiwix.

## 1.7.1

- Management page: the library buttons now wrap below the file name on narrow screens instead of running off the edge.

## 1.7.0

- Administrators can choose per book whether it is shown on the front page (button in the library list on
  the management page). Hidden books are left out for everyone else and from search; administrators see
  them in an extra "Hidden books" group below the others. This only hides the book from the list; it does
  not block direct links. The choice is stored in `.hidden.json` in the library folder.

## 1.6.2

- The network pill is gone from the front page. The dashboard card shows a small line under "Flere apps"
  instead (home network or internet, with the address Home Assistant sees).

## 1.6.1

- The network pill also shows the address Home Assistant sees for you, to tell a home address from your
  router's public one.

## 1.6.0

- The front page shows whether you reach Home Assistant from the home network or over the internet
  (green "Lokalt netværk" / orange "Via nettet"). It is based on the caller's address passed on by Home
  Assistant; when that says nothing (for example a loopback address), nothing is shown.

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
