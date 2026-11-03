export function slugify(input) {
  return String(input).toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '');
}

export function slugifyAll(list) {
  return list.map((item) => slugify(item));
}
