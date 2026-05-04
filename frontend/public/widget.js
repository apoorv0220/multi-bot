(function() {
  const runtimeConfig = window.RUNTIME_CONFIG || {};
  // Prefer neutral name; legacy key kept for backward compatibility with older embeds.
  const cfg = window.CHATBOT_WIDGET_CONFIG || window.MRNWEBDESIGNS_CHATBOT_CONFIG || {};
  // Configuration - set this to your actual deployed URL in production
  const widgetUrl =
    cfg.baseUrl ||
    runtimeConfig.WIDGET_BASE_URL ||
    `${window.location.protocol}//${window.location.host}`;
  const apiUrl =
    cfg.apiUrl ||
    runtimeConfig.API_BASE_URL ||
    `${window.location.protocol}//${window.location.host}`;
  // Optional embed override for the launcher bubble only. Chat panel colors come from
  // tenant branding (GET /api/public/config → primary_color) when we fetch below.
  const embedPrimaryColorOverride = cfg.primaryColor || null;
  const tenantPublicKey = cfg.tenantPublicKey || null;
  const chatbotInitialText = cfg.chatbotInitialText || null;
  const chatbotHeaderTitle = cfg.chatbotHeaderTitle || null;

  function postOpenChatConfig(iframe) {
    if (!iframe || !iframe.contentWindow) return;
    iframe.contentWindow.postMessage({
      action: 'open-chat',
      apiUrl: apiUrl,
      tenantPublicKey: tenantPublicKey,
      chatbotInitialText: chatbotInitialText,
      chatbotHeaderTitle: chatbotHeaderTitle
    }, '*');
  }
  
  // Create iframe for the widget
  function createChatbotIframe() {
    const iframe = document.createElement('iframe');
    iframe.id = 'mrnwebdesigns-chatbot-iframe';
    iframe.src = widgetUrl.replace(/\/$/, '') + '/embed';
    iframe.style.position = 'fixed';
    iframe.style.bottom = '90px';
    iframe.style.right = '20px';
    iframe.style.width = '380px';
    iframe.style.height = '600px';
    iframe.style.border = 'none';
    iframe.style.borderRadius = '12px';
    iframe.style.boxShadow = '0 4px 25px rgba(0, 0, 0, 0.1)';
    iframe.style.zIndex = '999998';
    iframe.style.display = 'none';
    iframe.style.opacity = '0';
    iframe.style.transition = 'opacity 0.3s ease';
    iframe.setAttribute('allowtransparency', 'true');
    
    // Add responsiveness for mobile
    const mediaQuery = window.matchMedia('(max-width: 480px)');
    if (mediaQuery.matches) {
      iframe.style.width = '100%';
      iframe.style.height = '100%';
      iframe.style.bottom = '0';
      iframe.style.right = '0';
      iframe.style.borderRadius = '0';
    }
    
    return iframe;
  }
  
  // Create toggle button (launcher color: DB primary_color when fetched, else embed override, else default)
  function createToggleButton(launcherColor) {
    const button = document.createElement('button');
    button.id = 'mrnwebdesigns-chatbot-toggle';
    button.innerHTML = `
      <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
      </svg>
    `;
    button.style.position = 'fixed';
    button.style.bottom = '20px';
    button.style.right = '20px';
    button.style.width = '60px';
    button.style.height = '60px';
    button.style.borderRadius = '50%';
    button.style.backgroundColor = launcherColor || '#bf362e';
    button.style.color = 'white';
    button.style.border = 'none';
    button.style.boxShadow = '0 4px 25px rgba(0, 0, 0, 0.1)';
    button.style.cursor = 'pointer';
    button.style.zIndex = '999999';
    button.style.display = 'flex';
    button.style.alignItems = 'center';
    button.style.justifyContent = 'center';
    button.style.transition = 'all 0.3s ease';
    
    return button;
  }
  
  // Toggle chatbot visibility
  function toggleChatbot() {
    const iframe = document.getElementById('mrnwebdesigns-chatbot-iframe');
    const button = document.getElementById('mrnwebdesigns-chatbot-toggle');
    
    if (iframe.style.display === 'none') {
      // Show iframe with transition
      iframe.style.display = 'block';
      // Use setTimeout to allow the display change to take effect before changing opacity
      setTimeout(() => {
        iframe.style.opacity = '1';
      }, 10);
      
      button.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="18" y1="6" x2="6" y2="18"></line>
          <line x1="6" y1="6" x2="18" y2="18"></line>
        </svg>
      `;
      // Send message to iframe to open chat.
      // Retry shortly to handle slower iframe bootstrap on production.
      postOpenChatConfig(iframe);
      setTimeout(() => postOpenChatConfig(iframe), 250);
    } else {
      closeChat();
    }
  }
  
  // Function to close the chat
  function closeChat() {
    const iframe = document.getElementById('mrnwebdesigns-chatbot-iframe');
    const button = document.getElementById('mrnwebdesigns-chatbot-toggle');
    
    // Hide with transition
    iframe.style.opacity = '0';
    
    // Reset button icon
    button.innerHTML = `
      <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
      </svg>
    `;
    
    // Send message to iframe to close chat
    iframe.contentWindow.postMessage('close-chat', '*');
    
    // Wait for transition to complete before hiding the element
    setTimeout(() => {
      iframe.style.display = 'none';
      
      // Clean up any potential shadows or remnants
      const shadows = document.querySelectorAll('.chatbot-shadow-element');
      shadows.forEach(el => {
        document.body.removeChild(el);
      });
    }, 300); // Match the transition duration
  }
  
  async function resolveLauncherPrimaryColor() {
    let color = embedPrimaryColorOverride || '#bf362e';
    if (!tenantPublicKey || !apiUrl) return color;
    try {
      const base = String(apiUrl).replace(/\/$/, '');
      const res = await fetch(`${base}/api/public/config`, {
        headers: { 'X-Widget-Key': tenantPublicKey },
      });
      if (!res.ok) return color;
      const data = await res.json();
      if (data && typeof data.primary_color === 'string' && data.primary_color.trim()) {
        color = data.primary_color.trim();
      }
    } catch (e) {
      // keep fallback
    }
    return color;
  }

  // Initialize widget
  async function initWidget() {
    // Check if widget already exists
    if (document.getElementById('mrnwebdesigns-chatbot-iframe')) {
      return;
    }

    const launcherColor = await resolveLauncherPrimaryColor();
    
    // Create and append iframe
    const iframe = createChatbotIframe();
    iframe.addEventListener('load', function() {
      // Ensure config reaches iframe even if first open click happens
      // before the embedded app has attached its message listener.
      postOpenChatConfig(iframe);
    });
    document.body.appendChild(iframe);
    
    // Create and append toggle button
    const button = createToggleButton(launcherColor);
    document.body.appendChild(button);
    
    // Add event listener to toggle button
    button.addEventListener('click', toggleChatbot);
    
    // Listen for messages from the iframe
    window.addEventListener('message', function(event) {
      // Accept messages from the chatbot iframe
      if (event.data === 'close-widget') {
        closeChat();
      }
    });
  }
  
  // Wait for DOM to be fully loaded
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() { initWidget(); });
  } else {
    initWidget();
  }
})(); 