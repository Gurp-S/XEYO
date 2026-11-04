const USERS = { u1: { id: 'u1', name: 'Ada' }, u2: { id: 'u2', name: 'Alan' } };

export function getUser(id) {
  const user = USERS[id];
  if (user === undefined) throw new Error(`no such user: ${id}`);
  return { ...user };
}

export function listUsers() {
  return Object.values(USERS).map((user) => ({ ...user }));
}
