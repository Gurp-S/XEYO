const URL_RE = /url\(\s*(['"]?)([^'")]+)\1\s*\)/g;

export function urlSpecifiers(text) {
  const found = [];
  for (const match of text.matchAll(URL_RE)) found.push(match[2]);
  return found;
}

export function rewriteUrls(text, names) {
  return text.replace(URL_RE, (whole, _quote, target) => {
    const name = names.get(target);
    return name ? `url(${name})` : whole;
  });
}
