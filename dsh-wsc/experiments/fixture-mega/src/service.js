import { getUser } from './api.js';

export function describeUser(id) {
  const user = getUser(id);
  return `${user.id}:${user.name}`;
}
