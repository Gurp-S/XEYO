import base from '../playwright.config';
export default {...base, testDir: '.', testMatch: '*.browser.spec.ts', reporter: 'list'};
