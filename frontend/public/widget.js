(function() {
  // Configuration - set this to your actual deployed URL in production
  const widgetUrl = window.MEDICALOPTICS_CHATBOT_CONFIG?.baseUrl || 'http://localhost:3023';
  const apiUrl = window.MEDICALOPTICS_CHATBOT_CONFIG?.apiUrl || 'http://localhost:8023';
  const primaryColor = window.MEDICALOPTICS_CHATBOT_CONFIG?.primaryColor || '#017764';
  
  // Create iframe for the widget
  function createChatbotIframe() {
    const iframe = document.createElement('iframe');
    iframe.id = 'medicaloptics-chatbot-iframe';
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
  
  // Create toggle button
  function createToggleButton() {
    const button = document.createElement('button');
    button.id = 'medicaloptics-chatbot-toggle';
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
    const iframe = document.getElementById('medicaloptics-chatbot-iframe');
    const button = document.getElementById('medicaloptics-chatbot-toggle');
    
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
      // Send message to iframe to open chat
      iframe.contentWindow.postMessage({
        action: 'open-chat',
        apiUrl: apiUrl
      }, '*');
    } else {
      closeChat();
    }
  }
  
  // Function to close the chat
  function closeChat() {
    const iframe = document.getElementById('medicaloptics-chatbot-iframe');
    const button = document.getElementById('medicaloptics-chatbot-toggle');
    
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
  
  // Initialize widget
  function initWidget() {
    // Check if widget already exists
    if (document.getElementById('medicaloptics-chatbot-iframe')) {
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
    document.addEventListener('DOMContentLoaded', initWidget);
  } else {
    initWidget();
  }
})(); 