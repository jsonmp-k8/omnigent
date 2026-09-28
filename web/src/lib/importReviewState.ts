// Which hosts' harness imports this device has already reviewed, so the
// import modal opens on its own only the first time a host shows up.

const KEY_PREFIX = "omnigent:imports-reviewed:";

export function importsReviewed(hostId: string): boolean {
  if (typeof window === "undefined") return true;
  try {
    return window.localStorage.getItem(KEY_PREFIX + hostId) !== null;
  } catch {
    // Without storage, don't nag on every load.
    return true;
  }
}

export function markImportsReviewed(hostId: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(KEY_PREFIX + hostId, new Date().toISOString());
  } catch {
    // localStorage quota or access errors shouldn't break the app.
  }
}
