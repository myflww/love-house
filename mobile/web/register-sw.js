/* The APK serves its own private assets; service workers are for hosted PWA only. */
if (!window.LoveHouseNative && 'serviceWorker' in navigator && window.isSecureContext) {
  window.addEventListener('load', function () {
    navigator.serviceWorker.register('./sw.js', {scope: './'}).then(function (registration) {
      function ready() { document.documentElement.dataset.offlineReady = 'true'; }
      if (registration.active) ready();
      navigator.serviceWorker.ready.then(ready).catch(function () {});
    }).catch(function () {
      // Never claim offline readiness when install/cache failed.
      document.documentElement.dataset.offlineReady = 'false';
      window.dispatchEvent(new CustomEvent('lovehouse-offline-unavailable'));
    });
  });
}
