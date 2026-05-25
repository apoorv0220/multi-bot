/**
 * Loads tenant branding from GET /api/public/config and updates example embed pages.
 * Requires window.CHATBOT_WIDGET_CONFIG.tenantPublicKey and apiUrl to be set first.
 */
(function () {
  function resolveApiBase(cfg) {
    const raw =
      cfg.apiUrl ||
      (window.RUNTIME_CONFIG && window.RUNTIME_CONFIG.API_BASE_URL) ||
      `${window.location.protocol}//${window.location.host}`;
    return String(raw).replace(/\/$/, "");
  }

  function brandLabel(data) {
    return (
      (data && (data.brand_name || data.header_title)) ||
      "Store"
    ).trim() || "Store";
  }

  async function applyExampleEmbedBranding(options) {
    const cfg = window.CHATBOT_WIDGET_CONFIG || {};
    const widgetKey = options && options.tenantPublicKey ? options.tenantPublicKey : cfg.tenantPublicKey;
    if (!widgetKey) {
      return null;
    }

    const apiUrl = resolveApiBase(options && options.apiUrl ? { apiUrl: options.apiUrl } : cfg);

    try {
      const response = await fetch(`${apiUrl}/api/public/config`, {
        headers: { "X-Widget-Key": widgetKey },
      });
      if (!response.ok) {
        return null;
      }
      const data = await response.json();
      const brand = brandLabel(data);
      const skipDom = Boolean(options && options.skipDomUpdates);

      if (!skipDom) {
        const titleText = options && options.titleText
          ? options.titleText.replace("{brand}", brand)
          : `${brand} Chatbot - Embed Example`;

        document.title = titleText;

        document.querySelectorAll("[data-embed-title]").forEach((node) => {
          node.textContent = titleText;
        });

        document.querySelectorAll("[data-embed-brand]").forEach((node) => {
          node.textContent = brand;
        });

        document.querySelectorAll("[data-embed-intro]").forEach((node) => {
          node.textContent = `This page demonstrates how to embed the ${brand} AI chatbot into any website.`;
        });

        if (data.primary_color) {
          document.documentElement.style.setProperty("--embed-primary", data.primary_color);
          document.querySelectorAll("[data-embed-primary]").forEach((node) => {
            node.style.color = data.primary_color;
          });
        }
      }

      return data;
    } catch (err) {
      console.warn("Could not load tenant branding for example page:", err);
      return null;
    }
  }

  window.applyExampleEmbedBranding = applyExampleEmbedBranding;
})();
