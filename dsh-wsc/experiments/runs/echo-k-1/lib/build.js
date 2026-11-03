// Public entry point. Callers (bin/build.js, tests) import build/parseArgs from
// here; planning and writing live in planner.js, the argument contract in cli.js.
// One facade means the CLI and the tests cannot drift apart.
export * from './planner.js';
export { parseArgs, USAGE, formatReport, positiveInt } from './cli.js';
