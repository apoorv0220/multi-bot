(function() {
  // Configuration - set this to your actual deployed URL in production
  const widgetUrl = window.MIGRAINE_CHATBOT_CONFIG?.baseUrl || 'http://localhost:3013';
  const apiUrl = window.MIGRAINE_CHATBOT_CONFIG?.apiUrl || 'http://localhost:8013';
  const primaryColor = window.MIGRAINE_CHATBOT_CONFIG?.primaryColor || '#5762d5';
  
  // Create iframe for the widget
  function createChatbotIframe() {
    const iframe = document.createElement('iframe');
    iframe.id = 'migraine-chatbot-iframe';
    iframe.src = widgetUrl;
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
  
  // Create toggle button
  function createToggleButton() {
    const button = document.createElement('button');
    button.id = 'migraine-chatbot-toggle';
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
    button.style.backgroundColor = primaryColor;
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
    const iframe = document.getElementById('migraine-chatbot-iframe');
    const button = document.getElementById('migraine-chatbot-toggle');
    
    if (iframe.style.display === 'none') {
      iframe.style.display = 'block';
      button.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <line x1="18" y1="6" x2="6" y2="18"></line>
          <line x1="6" y1="6" x2="18" y2="18"></line>
        </svg>
      `;
      // Send message to iframe to open chat
      iframe.contentWindow.postMessage({
        action: 'open-chat',
        apiUrl: apiUrl
      }, '*');
    } else {
      iframe.style.display = 'none';
      button.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
        </svg>
      `;
      // Send message to iframe to close chat
      iframe.contentWindow.postMessage('close-chat', '*');
    }
  }
  
  // Initialize widget
  function initWidget() {
    // Check if widget already exists
    if (document.getElementById('migraine-chatbot-iframe')) {
      return;
    }
    
    // Create and append iframe
    const iframe = createChatbotIframe();
    document.body.appendChild(iframe);
    
    // Create and append toggle button
    const button = createToggleButton();
    document.body.appendChild(button);
    
    // Add event listener to toggle button
    button.addEventListener('click', toggleChatbot);
  }
  
  // Wait for DOM to be fully loaded
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initWidget);
  } else {
    initWidget();
  }
})(); 