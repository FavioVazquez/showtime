// A test that fails on purpose (the page says "Welcome back, Ada"), for `showtime repro`'s tests.
const { test, expect } = require('playwright/test');
const path = require('path');
const { pathToFileURL } = require('url');

test('signs in and greets the user', async ({ page }) => {
  await page.goto(pathToFileURL(path.join(__dirname, 'app', 'index.html')).href + '?session=s3ss10n-n0t-real#debug');
  await page.getByLabel('Email').fill('ada@example.test');
  await page.getByLabel('Password').fill('hunter2-not-real');
  await page.getByLabel('API token').fill('tok-0000-not-real');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Welcome, Ada!', { timeout: 1500 });
});
