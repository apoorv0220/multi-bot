import React, { useState, useRef, useEffect } from 'react';
import styled from 'styled-components';
import { BsSend } from 'react-icons/bs';
import Message from './Message';
import { client } from '../api';

const ChatWidget = ({ mode = "admin" }) => {
  const [messages, setMessages] = useState([
    {
      id: 1,
      text: 'Hello! I\'m your MRN Web Designs Assistant. How can I help you today with website design, development, SEO, or digital marketing?',
      isBot: true,
      timestamp: new Date(),
    },
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [apiUrl, setApiUrl] = useState(process.env.REACT_APP_API_URL || "http://localhost:8043");
  const [widgetKey, setWidgetKey] = useState(null);
  const [sessionStorageKey, setSessionStorageKey] = useState("chat_session_id");
  const [sessionId, setSessionId] = useState(localStorage.getItem("chat_session_id") || null);
  const [publicConfigError, setPublicConfigError] = useState("");
  const messageEndRef = useRef(null);
  const inputRef = useRef(null);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Focus input when widget opens
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    if (mode !== "public") return;
    const onMessage = (event) => {
      const data = event?.data;
      if (!data || typeof data !== "object") return;
      if (data.action !== "open-chat") return;
      if (data.apiUrl) setApiUrl(data.apiUrl);
      if (data.tenantPublicKey) setWidgetKey(data.tenantPublicKey);
      const keySuffix = data.tenantPublicKey || "default";
      const storageKey = `chat_session_id_${keySuffix}`;
      setSessionStorageKey(storageKey);
      setSessionId(localStorage.getItem(storageKey) || null);
      if (!data.tenantPublicKey) {
        setPublicConfigError("Widget is misconfigured: tenantPublicKey is required.");
      } else {
        setPublicConfigError("");
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [mode]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim()) return;
    if (mode === "public" && !widgetKey) {
      setPublicConfigError("Widget is misconfigured: tenantPublicKey is required.");
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
      const endpoint = mode === "public" ? "/api/public/chat" : "/api/chat";
      const response = await client.post(`${apiUrl}${endpoint}`, {
        message: input,
        session_id: sessionId,
        max_results: 3,
      }, {
        headers: mode === "public" ? { "X-Widget-Key": widgetKey } : undefined,
      });
      if (response.data.session_id) {
        setSessionId(response.data.session_id);
        localStorage.setItem(sessionStorageKey, response.data.session_id);
      }

      // Add bot response with the new response format
      const botMessage = {
        type: 'bot',
        text: response.data.response,
        timestamp: new Date(),
        sources: response.data.sources || [],
        confidence: response.data.confidence,
        source: response.data.source,
        messageId: response.data.message_id,
      };
      setMessages((prevMessages) => [...prevMessages, botMessage]);
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
    <WidgetContainer className="mrnwebdesigns-chatbot-widget-container">
      <WidgetHeader className="mrnwebdesigns-chatbot-widget-header">
        <WidgetTitle>MRN Web Designs Assistant</WidgetTitle>
      </WidgetHeader>
      
      <MessageContainer className="mrnwebdesigns-chatbot-widget-message-container">
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
            messageId={message.messageId}
          />
        ))}
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
          placeholder="Type your message..."
          disabled={isLoading}
        />
        <SendButton type="submit" disabled={isLoading || !input.trim()}>
          <BsSend />
        </SendButton>
      </InputForm>
      {publicConfigError && <ConfigError>{publicConfigError}</ConfigError>}
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
  background: #bf362e;
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
    border-color: #bf362e;
  }
`;

const SendButton = styled.button`
  background: #bf362e;
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

const ConfigError = styled.div`
  color: #c62828;
  font-size: 0.85rem;
  padding: 8px 12px 12px;
`;

export default ChatWidget; 