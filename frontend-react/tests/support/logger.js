// Tiny timestamped logger shared by the step definitions and hooks, so a test
// run reads as a narrative of what the browser did — and failures are easy to
// locate in CI output.
const ts = () => new Date().toISOString();

export const log = {
  info: (msg) => console.log(`[${ts()}] INFO  ${msg}`),
  step: (msg) => console.log(`[${ts()}] STEP  ${msg}`),
  warn: (msg) => console.warn(`[${ts()}] WARN  ${msg}`),
  error: (msg) => console.error(`[${ts()}] ERROR ${msg}`)
};
