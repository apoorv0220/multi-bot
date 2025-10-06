import React, { useState, useEffect } from 'react';
import styled from 'styled-components';
import ChatWidget from './components/ChatWidget';

function App() {
  const [isOpen, setIsOpen] = useState(false);
  // const [apiUrl, setApiUrl] = useState(process.env.REACT_APP_API_URL || 'https://migraine.softdemonew.info/api');
  const [apiUrl, setApiUrl] = useState(process.env.REACT_APP_API_URL || 'http://localhost:8000');

  const closeChat = () => {
    setIsOpen(false);
  };

  // Listen for messages from parent window if embedded as widget
  useEffect(() => {
    const handleMessage = (event) => {
      // Accept messages from any origin when in widget mode
      const data = event.data;
      
      if (typeof data === 'object' && data.action === 'open-chat') {
        setIsOpen(true);
        if (data.apiUrl) {
          setApiUrl(data.apiUrl);
        }
      } else if (data === 'close-chat') {
        setIsOpen(false);
      } else if (data === 'toggle-chat') {
        setIsOpen(prev => !prev);
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  return (
    <AppContainer id="migraine-chatbot-widget" className={isOpen ? '' : 'closed-container'}>
      {isOpen && <ChatWidget onClose={closeChat} apiUrl={apiUrl} />}
      {/* <ChatButton onClick={toggleChat} isOpen={isOpen} /> */}
    </AppContainer>
  );
}

const AppContainer = styled.div`
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
`;

export default App; 