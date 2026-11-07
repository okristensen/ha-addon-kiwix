# Changelog

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
