import React from 'react';
import styled from 'styled-components';
import ReactMarkdown from 'react-markdown';

const Message = ({ message }) => {
  const { type, text, timestamp, isError } = message;
  const isBot = type === 'bot';
  
  // Format timestamp
  const formatTime = (date) => {
    return new Intl.DateTimeFormat('en-US', {
      hour: '2-digit',
      minute: '2-digit',
    }).format(date);
  };

  return (
    <MessageContainer isBot={isBot} isError={isError}>
      <MessageContent isBot={isBot}>
        <ReactMarkdown>{text}</ReactMarkdown>
      </MessageContent>
      <MessageTime>{formatTime(timestamp)}</MessageTime>
    </MessageContainer>
  );
};

const MessageContainer = styled.div`
  display: flex;
  flex-direction: column;
  align-items: ${props => props.isBot ? 'flex-start' : 'flex-end'};
  margin-bottom: 15px;
  max-width: 85%;
  align-self: ${props => props.isBot ? 'flex-start' : 'flex-end'};
`;

const MessageContent = styled.div`
  background-color: ${props => {
    if (props.isError) return 'var(--error-color)';
    return props.isBot ? 'var(--secondary-color)' : 'var(--primary-color)';
  }};
  color: ${props => props.isBot ? 'var(--text-color)' : 'white'};
  padding: 12px 16px;
  border-radius: 18px;
  border-bottom-left-radius: ${props => props.isBot ? '4px' : '18px'};
  border-bottom-right-radius: ${props => props.isBot ? '18px' : '4px'};
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
  word-break: break-word;
  
  p {
    margin: 0;
    line-height: 1.4;
  }
  
  a {
    color: ${props => props.isBot ? 'var(--primary-color)' : 'white'};
    text-decoration: underline;
  }
  
  ul, ol {
    margin-top: 8px;
    margin-bottom: 8px;
    padding-left: 20px;
  }
`;

const MessageTime = styled.span`
  font-size: 11px;
  color: var(--light-text);
  margin-top: 5px;
`;

export default Message; 