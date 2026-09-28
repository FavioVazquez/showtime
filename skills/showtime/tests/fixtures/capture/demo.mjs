// Demo script used by tests/test_capture.py against tests/fixtures/capture/index.html (~5 s).
export const options = { size: '960x540', fps: 24 };

export default async function (demo) {
  await demo.goto('/');
  await demo.wait(0.5);
  await demo.chapter('Create a preview');
  await demo.scroll('#demo', { duration: 0.8 });
  await demo.type('#repo', 'acme/web', { cps: 16 });
  await demo.type('-x', { cps: 16 });          // no target: types into the focused field
  await demo.click('#go');
  await demo.waitFor('#result.show');
  await demo.press('Meta+K');
  await demo.wait(1.0);
}
