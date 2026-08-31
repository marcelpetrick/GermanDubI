import { expect, test } from '@playwright/test';

test('voice picker', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Dark' }).click();
  await expect(page.getByLabel('German narrator')).toBeVisible();
  await page.screenshot({ path: 'shots/voice-dark.png' });
});
