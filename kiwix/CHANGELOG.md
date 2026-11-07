# Changelog

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
