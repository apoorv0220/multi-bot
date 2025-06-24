import React, { useState, useRef, useEffect } from 'react';
import styled from 'styled-components';
import axios from 'axios';
import { BsSend } from 'react-icons/bs';
import Message from './Message';

const ChatWidget = ({ apiUrl }) => {
  const [messages, setMessages] = useState([
    {
      id: 1,
      text: 'Hello! I\'m your Medical Optics Assistant. How can I help you with eye care, vision health, or optical services today?',
      isBot: true,
      timestamp: new Date(),
    },
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
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

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim()) return;

    // Add user message
    const userMessage = {
      type: 'user',
      text: input,
      timestamp: new Date(),
    };
    setMessages((prevMessages) => [...prevMessages, userMessage]);
    setInput('');
    setIsLoading(true);
    setError(null);

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
    } catch (err) {
      console.error('Error querying API:', err);
      setError('Sorry, I had trouble getting your answer. Please try again later.');
      
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
        <WidgetTitle>Medical Optics Assistant</WidgetTitle>
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
  background: #017764;
  color: white;
`;

const WidgetTitle = styled.h2`
  margin: 0;
  font-size: 1.2rem;
`;

const CloseButton = styled.button`
  background: none;
  border: none;
  color: white;
  cursor: pointer;
  font-size: 1.2rem;
  padding: 5px;
  
  &:hover {
    opacity: 0.8;
  }
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
    border-color: #017764;
  }
`;

const SendButton = styled.button`
  background: #017764;
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