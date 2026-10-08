# Bundled Library map assets

This seed contains the working Library USB's Protomaps fonts and version 4 light
sprites, copied on 2026-10-07 without changing their contents. `SHA256SUMS` records
the vendored bytes and is checked during the image build. Runtime startup copies
missing files to `/storage/maps/basemaps-assets`, including these notices.
Existing files are preserved; startup does not refresh or replace them.

The seed provides Noto Sans Regular, Medium, and Italic glyph ranges
`0-255`, `256-511`, `512-767`, `768-1023`, `1024-1279`, `1280-1535`,
`7680-7935`, `8192-8447`, and `8448-8703`, plus the 1x and 2x light sprite
PNG/JSON files. This matches the working state-map installation; it is not a
complete worldwide font pack. Additional scripts/ranges can be placed beside
these files on the mounted drive and are preserved by startup.

Upstream project: https://github.com/protomaps/basemaps-assets

Licenses and provenance:

- `fonts/OFL.txt`: Noto font notice and SIL Open Font License 1.1.
- `sprites/TANGRAM-ICONS-LICENSE.txt`: Tangram icons MIT notice; Protomaps
  documents its sprites as derived from these icons.
- `sprites/LICENSE.md`: Protomaps BSD 3-Clause notice for upstream asset tooling.

The Noto and Protomaps notices were retrieved from upstream revision
`028c18f713baecad011301ff7a69acc39bcc2ae7`. The Tangram notice comes from
https://github.com/tangrams/icons/blob/master/LICENSE.md. The copied USB asset files
have no recorded upstream commit; their exact identity is the bundled checksum
manifest. Do not interpret the notice revision as their generation version.

When changing the seed, preserve license notices, verify compatibility with the
vendored `vendor/basemaps.js` style, and regenerate `SHA256SUMS` (excluding the
manifest itself). The manifest describes the image seed; customized destination
files can legitimately have different checksums.
