import React, { useState, useRef, useEffect, useMemo } from 'react';
import styled from 'styled-components';
import axios from 'axios';
import { BsSend } from 'react-icons/bs';
import Message from './Message';
import ConsentMessage from './ConsentMessage';
import { useTriggerDetection } from './TriggerDetector';
// import TriggerMessageDisplay from './TriggerMessageDisplay'; // Removed as no longer needed

const ChatWidget = ({ onClose, apiUrl }) => {
  const initialBotGreeting = useMemo(() => ({
    type: 'bot',
    text: 'Hello, I\'m Allevia. I\'m your migraine assistant. How can I help you today?',
    timestamp: new Date(),
  }), []);

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [consentGiven, setConsentGiven] = useState(false);
  const [showConsent, setShowConsent] = useState(true);
  const [sessionId, setSessionId] = useState(sessionStorage.getItem('migraine-chatbot-session-id')); // Initialize directly from sessionStorage
  const [isHistoryLoading, setIsHistoryLoading] = useState(false); // New state for history loading
  const [chatDisabled, setChatDisabled] = useState(false); // Manage chatDisabled state here
  const messageEndRef = useRef(null);
  const inputRef = useRef(null);

  // Custom acknowledge and re-enable chat functions for TriggerMessageDisplay
  const acknowledgeTrigger = () => {
    // For doctor triggers, re-enable chat when acknowledged
    // This will be called from TriggerMessageDisplay within the Message component
    setChatDisabled(false); // This will only affect doctor triggers, as emergency/suicide chat is disabled.
  };

  const enableChat = () => {
    setChatDisabled(false);
  };

  // Function to save chat events to backend
  const saveHistory = async (eventData) => {
    try {
      // Ensure bot_response_source is structured correctly before sending
      if (eventData.bot_response_source && typeof eventData.bot_response_source === 'object') {
        // This object is already prepared by TriggerDetector.js
        // The backend expects this as a dict for JSON serialization
      }
      await axios.post(`${apiUrl}/api/save-history`, { ...eventData, session_id: sessionId });
    } catch (error) {
      console.error("Error saving chat event to backend:", error);
    }
  };

  // Initialize trigger detection
  const { checkTriggers } = useTriggerDetection(saveHistory);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Focus input when widget opens
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Check for existing consent in session storage and potentially create a session
  useEffect(() => {
    const sessionConsent = sessionStorage.getItem('migraine-chatbot-consent');
    if (sessionConsent === 'true') {
      setConsentGiven(true);
      setShowConsent(false);

      // If consent is given and greeting isn't already the first message, add it
      setMessages(prevMessages => {
        if (prevMessages.length === 0 || prevMessages[0].text !== initialBotGreeting.text) {
          return [initialBotGreeting, ...prevMessages];
        }
        return prevMessages;
      });

      // If consent is given but no session_id exists, create one via a dedicated endpoint
      const ensureSessionId = async () => {
        if (!sessionId) { // This condition will now correctly reflect sessionStorage
          try {
            const response = await axios.post(`${apiUrl}/api/start-session`, { session_id: null });
            if (response.data.session_id) {
              setSessionId(response.data.session_id);
              sessionStorage.setItem('migraine-chatbot-session-id', response.data.session_id);
              console.log("New session ID created and stored:", response.data.session_id);
            }
          } catch (error) {
            console.error("Error ensuring session ID on consent accept:", error);
          }
        }
      };
      ensureSessionId();
    }
  }, [consentGiven, sessionId, apiUrl, initialBotGreeting]); // Depend on consentGiven, sessionId, apiUrl, and initialBotGreeting

  // Load chat history if session_id exists and consent is given
  useEffect(() => {
    const loadChatHistory = async () => {
      // Only load history if session_id and consent are confirmed
      if (sessionId && consentGiven) {
        setIsHistoryLoading(true); // Start loading
        try {
          const response = await axios.get(`${apiUrl}/api/chat-history/${sessionId}`);
          const history = response.data.history.map(event => {
            // Reconstruct message objects from history events
            let sources_for_message = []; // Renamed to avoid confusion with event.bot_response_source
            let triggerButtons = [];
            let botResponseSourceType = 'unknown';
            let botResponseTitle = ''; // Initialize botResponseTitle

            // Parse bot_response_source from DB (which is a dict now)
            if (event.bot_response_source && typeof event.bot_response_source === 'object') {
                botResponseSourceType = event.bot_response_source.type;
                if (event.bot_response_source.type === 'vector_search') {
                    sources_for_message = event.bot_response_source.details?.sources || [];
                } else if (event.bot_response_source.type === 'trigger') {
                    triggerButtons = event.bot_response_source.buttons || [];
                    // Use bot_response_title if available, otherwise infer from category
                    botResponseTitle = event.bot_response_title || (event.event_type.replace('trigger_', '') === 'emergency' ? '⚠️ Emergency Medical Alert' : event.event_type.replace('trigger_', '') === 'suicide' ? '⚠️ Crisis Support Available' : '📋 Medical Advice Recommended');
                }
            }

            if (event.event_type === 'chat_message') {
                return [
                    { type: 'user', text: event.user_message_text, timestamp: new Date(event.event_timestamp) },
                    { 
                        type: 'bot', 
                        text: event.bot_response_text, 
                        timestamp: new Date(event.event_timestamp), 
                        sources: sources_for_message, // Pass extracted sources
                        confidence: event.bot_response_confidence, 
                        source: botResponseSourceType, // Pass source type
                        botResponseTitle: botResponseTitle, // Pass the title
                    }
                ];
            } else if (event.event_type.startsWith('trigger_')) {
                // For trigger events, we need to add both the user's message and the bot's trigger response
                return [
                    { 
                        type: 'user', 
                        text: event.user_message_text, 
                        timestamp: new Date(event.event_timestamp) 
                    },
                    {
                        type: 'bot',
                        text: event.bot_response_text,
                        timestamp: new Date(event.event_timestamp),
                        isTrigger: true,
                        triggerCategory: event.event_type.replace('trigger_', ''),
                        triggerButtons: triggerButtons, // Pass extracted trigger buttons
                        botResponseTitle: botResponseTitle, // Pass the title
                    }
                ];
            }
            return null; // Should not happen
          }).flat().filter(Boolean);
          
          // Filter out the initial bot greeting if history is loaded
          if (history.length > 0) {
            // Ensure the initial bot greeting is always the first message
            const filteredHistory = history.filter(msg => 
                !(msg.type === 'bot' && msg.text === initialBotGreeting.text)
            );
            setMessages([initialBotGreeting, ...filteredHistory]);

            // After loading history, check if chat should be disabled
            let shouldDisableChat = false;
            // Also check for active triggers from history to set the `activeTrigger` state
            
            for (const msg of filteredHistory) {
              if (msg.isTrigger) {
                if (msg.triggerCategory === 'emergency' || msg.triggerCategory === 'suicide') {
                  shouldDisableChat = true;
                  
                }
                
              }
            }
            setChatDisabled(shouldDisableChat);
            // The activeTrigger state is no longer used for rendering a separate banner
            // Instead, the Message component will render TriggerMessageDisplay if isTrigger is true

            console.log("Loaded chat history:", history); // Debug log

          } else {
            // If no history, ensure only the initial bot greeting is present
            setMessages([initialBotGreeting]);
          }

        } catch (error) {
          console.error("Error loading chat history:", error);
        } finally {
          setIsHistoryLoading(false); // End loading
        }
      }
    };
    loadChatHistory();
  }, [sessionId, consentGiven, apiUrl, initialBotGreeting]);

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

    // Add initial greeting after consent is accepted, if not already present
    setMessages(prevMessages => {
      if (prevMessages.length === 0 || prevMessages[0].text !== initialBotGreeting.text) {
        return [initialBotGreeting, ...prevMessages];
      }
      return prevMessages;
    });
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

    // Add user message to display immediately
    const userMessage = {
      type: 'user',
      text: input,
      timestamp: new Date(),
    };
    setMessages((prevMessages) => [...prevMessages, userMessage]);
    setInput(''); // Clear input immediately after adding user message

    // Check for trigger words before processing
    const trigger = await checkTriggers(userMessage.text); // Pass the text of the user message for trigger detection
    if (trigger) {
      // Disable chat based on trigger category
      if (trigger.category === 'emergency' || trigger.category === 'suicide') {
        setChatDisabled(true);
      }
      // Add bot trigger response message to the chat
      const botTriggerMessage = {
        type: 'bot',
        text: trigger.response.message,
        timestamp: new Date(),
        isTrigger: true,
        triggerCategory: trigger.category,
        triggerButtons: trigger.response.buttons,
        botResponseTitle: trigger.response.title,
      };
      setMessages((prevMessages) => [...prevMessages, botTriggerMessage]);

      // saveHistory is now called inside useTriggerDetection
      return; // Exit as trigger response is handled by renderTriggerResponse and saveHistory
    }

    setIsLoading(true);

    try {
      // Call API with the new chat endpoint, including sessionId
      const response = await axios.post(`${apiUrl}/api/chat`, {
        message: input,
        max_results: 3,
        session_id: sessionId, // Pass session_id to backend
      });

      // If a new session_id is returned, update state and sessionStorage
      if (response.data.session_id && response.data.session_id !== sessionId) {
        setSessionId(response.data.session_id);
        sessionStorage.setItem('migraine-chatbot-session-id', response.data.session_id);
        console.log("New session ID received and stored during chat:", response.data.session_id);
      }

      // Add bot response with the new response format
      const botMessage = {
        type: 'bot',
        text: response.data.response,
        timestamp: new Date(),
        sources: response.data.sources || [], // Use the 'sources' directly for 'Read More' in Message component
        confidence: response.data.confidence,
        source: response.data.source, // This is now a string like 'vector_search'
        sourceDetails: response.data.source_details, // Pass source_details for potential future use or debugging
      };
      setMessages((prevMessages) => [...prevMessages, botMessage]);

      // History is now saved directly by the backend in /api/chat endpoint

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
        {messages.map((message, index) => {
          console.log("Rendering Message component with props:", message); // Debug log
          return (
            <Message
              key={index}
              type={message.type}
              text={message.text}
              timestamp={message.timestamp}
              sources={message.sources}
              isError={message.isError}
              confidence={message.confidence}
              source={message.source}
              isTrigger={message.isTrigger} // Pass isTrigger prop
              triggerCategory={message.triggerCategory} // Pass triggerCategory prop
              triggerButtons={message.triggerButtons} // Pass triggerButtons prop
              botResponseTitle={message.botResponseTitle} // Pass the title prop
              onAcknowledge={message.isTrigger && message.triggerCategory === 'doctor' ? acknowledgeTrigger : null} // Pass acknowledge for doctor triggers
              onEnableChat={message.isTrigger && message.triggerCategory === 'doctor' ? enableChat : null} // Pass enableChat for doctor triggers
            />
          );
        })}
        
        {/* Show consent message after first bot message */}
        {showConsent && (
          <ConsentMessage
            onAccept={handleConsentAccept}
            onDecline={handleConsentDecline}
          />
        )}
        
        {/* Render active trigger banner dynamically */}
        {/* This is no longer needed as trigger messages are now handled by the Message component */}
        
        {/* Show loading indicator for history fetch */}
        {isHistoryLoading && (
          <LoadingMessage>
            <LoadingDots>
              <span>.</span>
              <span>.</span>
              <span>.</span>
            </LoadingDots>
            <p>Loading chat history...</p>
          </LoadingMessage>
        )}

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
  background: #bd1d73;
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
    border-color: #bd1d73;
  }
  
  &:disabled {
    background-color: #f5f5f5;
    color: #999;
    cursor: not-allowed;
  }
`;

const SendButton = styled.button`
  background: #bd1d73;
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