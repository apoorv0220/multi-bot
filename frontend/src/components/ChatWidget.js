import React, { useState, useRef, useEffect } from 'react';
import styled from 'styled-components';
import axios from 'axios';
import { BsSend } from 'react-icons/bs';
import Message from './Message';
import ConsentMessage from './ConsentMessage';
import { useTriggerDetection } from './TriggerDetector';

const ChatWidget = ({ onClose, apiUrl }) => {
  const [messages, setMessages] = useState([
    {
      type: 'bot',
      text: 'Hello, I\'m Allevia. I\'m your migraine assistant. How can I help you today?',
      timestamp: new Date(),
    },
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [consentGiven, setConsentGiven] = useState(false);
  const [showConsent, setShowConsent] = useState(true);
  const messageEndRef = useRef(null);
  const inputRef = useRef(null);
  
  // PHP History API URL
  const PHP_HISTORY_API_URL = "https://migrainenew.newsoftdemo.info/wp-admin/admin-ajax.php?action=save_chat_history";

  // Function to save chat events to PHP backend
  const saveChatEventToPHP = async (eventData) => {
    try {
      const formBody = Object.keys(eventData).map(key =>
        encodeURIComponent(key) + '=' + encodeURIComponent(eventData[key])
      ).join('&');

      await fetch(PHP_HISTORY_API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: formBody,
      });
    } catch (error) {
      console.error("Error saving chat event to PHP backend:", error);
    }
  };

  // Initialize trigger detection
  const { checkTriggers, renderTriggerResponse, chatDisabled } = useTriggerDetection();

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Focus input when widget opens
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Check for existing consent in session storage
  useEffect(() => {
    const sessionConsent = sessionStorage.getItem('migraine-chatbot-consent');
    if (sessionConsent === 'true') {
      setConsentGiven(true);
      setShowConsent(false);
    }
  }, []);

  // Announce consent message to screen readers
  useEffect(() => {
    if (showConsent) {
      // Create a live region announcement for screen readers
      const announcement = document.createElement('div');
      announcement.setAttribute('aria-live', 'polite');
      announcement.setAttribute('aria-atomic', 'true');
      announcement.style.position = 'absolute';
      announcement.style.left = '-10000px';
      announcement.style.width = '1px';
      announcement.style.height = '1px';
      announcement.style.overflow = 'hidden';
      announcement.textContent = 'Important disclaimer dialog has appeared. Please review the terms and conditions before proceeding.';
      
      document.body.appendChild(announcement);
      
      // Clean up after announcement
      setTimeout(() => {
        document.body.removeChild(announcement);
      }, 1000);
    }
  }, [showConsent]);

  // Handle consent acceptance
  const handleConsentAccept = () => {
    setConsentGiven(true);
    setShowConsent(false);
    sessionStorage.setItem('migraine-chatbot-consent', 'true');
  };

  // Handle consent decline
  const handleConsentDecline = () => {
    // Clear any existing consent from session storage
    sessionStorage.removeItem('migraine-chatbot-consent');
    
    // Send message to parent window to close the entire widget
    if (window.parent && window.parent !== window) {
      // Use setTimeout to ensure the message is sent after any current operations
      setTimeout(() => {
        window.parent.postMessage('close-widget', '*');
      }, 100);
    }
    // Don't call onClose() here as it might interfere with the parent window handling
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim()) return;

    // Check if consent has been given
    if (!consentGiven) {
      return; // Don't process input until consent is given
    }

    // Check for trigger words before processing
    const trigger = await checkTriggers(input);
    if (trigger) {
      // Clear the input field when trigger is detected
      setInput('');
      
      // Save trigger event to PHP backend
      await saveChatEventToPHP({
        event_type: `trigger_${trigger.category}`,
        user_message_text: input,
        bot_response_text: trigger.response?.message || '', // Bot's predetermined response for trigger
        trigger_detection_method: trigger.method || 'unknown',
        trigger_confidence: trigger.confidence || 0,
        trigger_matched_phrase: trigger.triggerWord || 'unknown',
      });

      // Don't send the message to the AI model
      // The trigger response will be shown by renderTriggerResponse()
      return;
    }

    // Add user message
    const userMessage = {
      type: 'user',
      text: input,
      timestamp: new Date(),
    };
    setMessages((prevMessages) => [...prevMessages, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      // Call API with the new chat endpoint
      const response = await axios.post(`${apiUrl}/api/chat`, {
        message: input,
        max_results: 3,
      });

      // Add bot response with the new response format
      const botMessage = {
        type: 'bot',
        text: response.data.response,
        timestamp: new Date(),
        sources: response.data.sources || [],
        confidence: response.data.confidence,
        source: response.data.source,
      };
      setMessages((prevMessages) => [...prevMessages, botMessage]);

      // Save chat message to PHP backend
      await saveChatEventToPHP({
        event_type: 'chat_message',
        user_message_text: userMessage.text,
        bot_response_text: botMessage.text,
        bot_response_source: botMessage.source,
        bot_response_confidence: botMessage.confidence,
      });

    } catch (err) {
      console.error('Error querying API:', err);
      
      // Add error message
      const errorMessage = {
        type: 'bot',
        text: 'Sorry, I had trouble getting your answer. Please try again later.',
        timestamp: new Date(),
        isError: true,
      };
      setMessages((prevMessages) => [...prevMessages, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <WidgetContainer>
      <WidgetHeader>
        <WidgetTitle>Hello, I'm Allevia</WidgetTitle>
      </WidgetHeader>
      
      <MessageContainer>
        {messages.map((message, index) => (
          <Message
            key={index}
            type={message.type}
            text={message.text}
            timestamp={message.timestamp}
            sources={message.sources}
            isError={message.isError}
            confidence={message.confidence}
            source={message.source}
          />
        ))}
        
        {/* Show consent message after first bot message */}
        {showConsent && (
          <ConsentMessage
            onAccept={handleConsentAccept}
            onDecline={handleConsentDecline}
          />
        )}
        
        {/* Show trigger response if detected */}
        {renderTriggerResponse()}
        
        {isLoading && (
          <LoadingMessage>
            <LoadingDots>
              <span>.</span>
              <span>.</span>
              <span>.</span>
            </LoadingDots>
          </LoadingMessage>
        )}
        <div ref={messageEndRef} />
      </MessageContainer>

      <InputForm onSubmit={handleSubmit}>
        <Input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={
            !consentGiven ? "Please accept the disclaimer above to continue..." :
            chatDisabled ? "Chat disabled due to trigger detection. Use 'Re-enable Chat' button to continue..." :
            "Type your message..."
          }
          disabled={isLoading || !consentGiven || chatDisabled}
        />
        <SendButton type="submit" disabled={isLoading || !input.trim() || !consentGiven || chatDisabled}>
          <BsSend />
        </SendButton>
      </InputForm>
    </WidgetContainer>
  );
};

// Styled components
const WidgetContainer = styled.div`
  display: flex;
  flex-direction: column;
  width: 380px;
  height: 600px;
  background: white;
  border-radius: 10px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
  overflow: hidden;
`;

const WidgetHeader = styled.div`
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 15px;
  background: #72b519;
  color: white;
`;

const WidgetTitle = styled.h2`
  margin: 0;
  font-size: 1.2rem;
`;


const MessageContainer = styled.div`
  flex: 1;
  overflow-y: auto;
  padding: 15px;
  display: flex;
  flex-direction: column;
  gap: 10px;
`;

const InputForm = styled.form`
  display: flex;
  padding: 15px;
  gap: 10px;
  border-top: 1px solid #eee;
`;

const Input = styled.input`
  flex: 1;
  padding: 10px;
  border: 1px solid #ddd;
  border-radius: 20px;
  outline: none;
  
  &:focus {
    border-color: #72b519;
  }
  
  &:disabled {
    background-color: #f5f5f5;
    color: #999;
    cursor: not-allowed;
  }
`;

const SendButton = styled.button`
  background: #72b519;
  color: white;
  border: none;
  border-radius: 50%;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  
  &:disabled {
    background: #ccc;
    cursor: not-allowed;
  }
  
  &:hover:not(:disabled) {
    background: #5a8f15;
  }
`;

const LoadingMessage = styled.div`
  display: flex;
  justify-content: center;
  padding: 10px;
  color: #666;
`;

const LoadingDots = styled.div`
  display: flex;
  gap: 2px;
  
  span {
    animation: loading 1.4s infinite;
    &:nth-child(2) { animation-delay: 0.2s; }
    &:nth-child(3) { animation-delay: 0.4s; }
  }
  
  @keyframes loading {
    0%, 80%, 100% { opacity: 0; }
    40% { opacity: 1; }
  }
`;

export default ChatWidget; 