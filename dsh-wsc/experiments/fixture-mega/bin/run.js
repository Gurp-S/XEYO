#!/usr/bin/env node
import { describeUser } from '../src/service.js';

const id = process.argv[2] ?? 'u1';
process.stdout.write(`${describeUser(id)}\n`);
