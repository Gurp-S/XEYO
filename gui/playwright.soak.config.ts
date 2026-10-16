import {defineConfig, devices} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
const lab = JSON.parse(fs.readFileSync(process.env.XEYO_SOAK_LAB || '../.tmp/multiagent-soak-20261015/surfaces/surfaces.json', 'utf8'));
const port = Number(process.env.XEYO_SOAK_VITE_PORT || '5188');
export default defineConfig({
  testDir: './soak-e2e', workers: 1, retries: 0, timeout: 90000,
  outputDir: '../.tmp/multiagent-soak-20261015/browser-results',
  reporter: [['list'], ['json', {outputFile: '../.tmp/multiagent-soak-20261015/browser-report.json'}]],
  use: {baseURL: `http://127.0.0.1:${port}`, ...devices['Desktop Chrome'], trace: 'retain-on-failure', screenshot: 'only-on-failure'},
  webServer: {command: `node node_modules/vite/bin/vite.js --host 127.0.0.1 --port ${port} --strictPort`,
    env: {XEYO_PORT_FILE: path.resolve(lab.proxy_port_file)}, url: `http://127.0.0.1:${port}`, reuseExistingServer: false},
});
