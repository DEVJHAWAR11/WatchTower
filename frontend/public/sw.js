/* Watchtower service worker: shows Web Push alerts and opens the right page when one is clicked. */

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { title: "Watchtower", body: event.data ? event.data.text() : "" };
  }
  const title = data.title || "Watchtower";
  const options = {
    body: data.body || "",
    tag: data.tag || undefined,
    renotify: Boolean(data.tag),
    icon: "/icon.svg",
    badge: "/icon.svg",
    data: { url: safeUrl(data.url), ...(data.data || {}) },
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

function safeUrl(url) {
  try {
    const u = new URL(url || "/alerts", self.location.origin);
    return u.origin === self.location.origin ? u.pathname + u.search : "/alerts";
  } catch {
    return "/alerts";
  }
}

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/alerts";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      for (const w of wins) {
        if (new URL(w.url).origin === self.location.origin && "focus" in w) {
          w.navigate(target);
          return w.focus();
        }
      }
      return self.clients.openWindow(target);
    }),
  );
});
