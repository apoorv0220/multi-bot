(function() {
  // Widget integration script
  const widgetUrl = window.MEDICALOPTICS_CHATBOT_CONFIG?.baseUrl || 'http://localhost:3033';
  const apiUrl = window.MEDICALOPTICS_CHATBOT_CONFIG?.apiUrl || 'http://localhost:8033';
  const primaryColor = window.MEDICALOPTICS_CHATBOT_CONFIG?.primaryColor || '#017764';
  
  // Create the iframe
  function createIframe() {
    const iframe = document.createElement('iframe');
    iframe.src = widgetUrl;
    iframe.id = 'medicaloptics-chatbot-iframe';
    iframe.style.cssText = `
      position: fixed;
      bottom: 100px;
      right: 20px;
      width: 400px;
      height: 500px;
      border: none;
      z-index: 999999;
      border-radius: 10px;
      box-shadow: 0 4px 20px rgba(0,0,0,0.3);
      display: none;
      background: white;
    `;
    
    // Handle messages from the iframe
    window.addEventListener('message', function(event) {
      if (event.origin !== widgetUrl) return;
      
      if (event.data.type === 'closeChat') {
        hideWidget();
      }
      if (event.data.type === 'resizeWidget') {
        iframe.style.height = event.data.height + 'px';
      }
    });
    
    document.body.appendChild(iframe);
    return iframe;
  }
  
  // Create the toggle button
  function createToggleButton() {
    const button = document.createElement('button');
    button.id = 'medicaloptics-chatbot-toggle';
    button.innerHTML = `
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    `;
    
    button.style.cssText = `
      position: fixed;
      bottom: 20px;
      right: 20px;
      width: 60px;
      height: 60px;
      border-radius: 50%;
      background-color: ${primaryColor};
      color: white;
      border: none;
      cursor: pointer;
      z-index: 999999;
      box-shadow: 0 4px 20px rgba(0,0,0,0.3);
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.3s ease;
    `;
    
    button.addEventListener('click', toggleWidget);
    document.body.appendChild(button);
    return button;
  }
  
  // Show widget
  function showWidget() {
    const iframe = document.getElementById('medicaloptics-chatbot-iframe');
    const button = document.getElementById('medicaloptics-chatbot-toggle');
    
    if (iframe) {
      iframe.style.display = 'block';
    }
    if (button) {
      button.innerHTML = `
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <line x1="18" y1="6" x2="6" y2="18" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          <line x1="6" y1="6" x2="18" y2="18" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      `;
    }
  }
  
  // Hide widget
  function hideWidget() {
    const iframe = document.getElementById('medicaloptics-chatbot-iframe');
    const button = document.getElementById('medicaloptics-chatbot-toggle');
    
    if (iframe) {
      iframe.style.display = 'none';
    }
    if (button) {
      button.innerHTML = `
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      `;
    }
  }
  
  // Toggle widget
  function toggleWidget() {
    const iframe = document.getElementById('medicaloptics-chatbot-iframe');
    if (iframe && iframe.style.display === 'block') {
      hideWidget();
    } else {
      showWidget();
    }
  }
  
  // Initialize the widget
  function initWidget() {
    // Prevent multiple widgets from being created
    if (document.getElementById('medicaloptics-chatbot-iframe')) {
      return;
    }

    createIframe();
    createToggleButton();
  }
  
  // Load the widget when the DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initWidget);
  } else {
    initWidget();
  }
})(); 