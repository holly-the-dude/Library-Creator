// Kiwix's catalog links to /viewer#book. Open the archive directly so the map
// owns the whole page, with a single GPS adapter rather than a nested reader.
'use strict';
try {
  const target = location.hash.slice(1).split('/').map(part => encodeURIComponent(decodeURIComponent(part))).join('/');
  location.replace(target ? `/maps/content/${target}` : '/maps/');
} catch (_) { location.replace('/maps/'); }
