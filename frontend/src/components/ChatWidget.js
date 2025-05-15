import React, { useState, useRef, useEffect } from 'react';
import styled from 'styled-components';
import axios from 'axios';
import { FaTimes } from 'react-icons/fa';
import { BsSend } from 'react-icons/bs';
import Message from './Message';
import SourceCitation from './SourceCitation';

const ChatWidget = ({ onClose, apiUrl }) => {
  const [messages, setMessages] = useState([
    {
      type: 'bot',
      text: 'Hello! I\'m your Migraine Assistant. How can I help you today?',
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
      // Call API
      const response = await axios.post(`${apiUrl}/api/query`, {
        query: input,
        max_results: 3,
      });

      // Add bot response
      const botMessage = {
        type: 'bot',
        text: response.data.answer,
        timestamp: new Date(),
        sources: response.data.sources || [],
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
    <ChatContainer>
      <Header>
        <Title>Migraine AI Assistant</Title>
        <CloseButton onClick={onClose}>
          <FaTimes />
        </CloseButton>
      </Header>

      <MessageList>
        {messages.map((message, index) => (
          <div key={index}>
            <Message message={message} />
            {message.sources && message.sources.length > 0 && (
              <SourceList>
                {message.sources.map((source, idx) => (
                  <SourceCitation key={idx} source={source} />
                ))}
              </SourceList>
            )}
          </div>
        ))}
        {isLoading && (
          <LoadingIndicator>
            <div></div>
            <div></div>
            <div></div>
          </LoadingIndicator>
        )}
        <div ref={messageEndRef} />
      </MessageList>

      <InputForm onSubmit={handleSubmit}>
        <Input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type your question here..."
          disabled={isLoading}
          ref={inputRef}
        />
        <SendButton type="submit" disabled={isLoading || !input.trim()}>
          <BsSend />
        </SendButton>
      </InputForm>

      <Footer>
        <PoweredBy>Powered by Migraine.ie</PoweredBy>
      </Footer>
    </ChatContainer>
  );
};

// Styled Components
const ChatContainer = styled.div`
  width: 380px;
  height: 600px;
  background-color: white;
  border-radius: var(--border-radius);
  box-shadow: var(--shadow);
  display: flex;
  flex-direction: column;
  margin-bottom: 20px;
  overflow: hidden;
  
  @media (max-width: 480px) {
    width: 100vw;
    height: 100vh;
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    border-radius: 0;
    margin-bottom: 0;
  }
`;

const Header = styled.div`
  background-color: var(--primary-color);
  color: white;
  padding: 15px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
`;

const Title = styled.h2`
  margin: 0;
  font-size: 18px;
  font-weight: 500;
`;

const CloseButton = styled.button`
  background: none;
  border: none;
  color: white;
  font-size: 18px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  
  &:hover {
    opacity: 0.8;
  }
  
  &:focus {
    outline: none;
  }
`;

const MessageList = styled.div`
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
`;

const SourceList = styled.div`
  margin-top: 5px;
  margin-bottom: 15px;
  display: flex;
  flex-direction: column;
  gap: 5px;
`;

const InputForm = styled.form`
  display: flex;
  padding: 15px;
  border-top: 1px solid #eee;
`;

const Input = styled.input`
  flex: 1;
  padding: 12px 15px;
  border: 1px solid #ddd;
  border-radius: 20px;
  font-size: 14px;
  
  &:focus {
    outline: none;
    border-color: var(--primary-color);
  }
  
  &:disabled {
    background-color: #f9f9f9;
  }
`;

const SendButton = styled.button`
  background-color: var(--primary-color);
  color: white;
  border: none;
  border-radius: 50%;
  width: 40px;
  height: 40px;
  margin-left: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  
  &:hover:not(:disabled) {
    background-color: var(--primary-dark);
  }
  
  &:disabled {
    background-color: #ccc;
    cursor: not-allowed;
  }
  
  &:focus {
    outline: none;
  }
`;

const Footer = styled.div`
  padding: 10px;
  text-align: center;
  border-top: 1px solid #eee;
`;

const PoweredBy = styled.div`
  font-size: 12px;
  color: var(--light-text);
`;

const LoadingIndicator = styled.div`
  display: flex;
  justify-content: center;
  margin: 10px 0;
  
  div {
    width: 8px;
    height: 8px;
    margin: 0 5px;
    background-color: var(--primary-color);
    border-radius: 50%;
    animation: bounce 1.4s infinite ease-in-out both;

    &:nth-child(1) {
      animation-delay: -0.32s;
    }

    &:nth-child(2) {
      animation-delay: -0.16s;
    }
  }

  @keyframes bounce {
    0%, 80%, 100% {
      transform: scale(0);
    }
    40% {
      transform: scale(1);
    }
  }
`;

export default ChatWidget; 