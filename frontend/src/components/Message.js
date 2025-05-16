import React from 'react';
import styled from 'styled-components';
import ReactMarkdown from 'react-markdown';

const Message = ({ message }) => {
  const { type, text, timestamp, isError, sources } = message;
  const isBot = type === 'bot';
  
  // Format timestamp
  const formatTime = (date) => {
    return new Intl.DateTimeFormat('en-US', {
      hour: '2-digit',
      minute: '2-digit',
    }).format(date);
  };

  // Check if any sources have a score of at least 30%
  const hasHighConfidenceSource = sources && 
    sources.length > 0 && 
    sources.some(source => source.score >= 0.3);

  return (
    <MessageContainer isBot={isBot} isError={isError}>
      <MessageContent isBot={isBot} isError={isError}>
        <ReactMarkdown>{text}</ReactMarkdown>
        {isBot && hasHighConfidenceSource && (
          <ReadMoreButton 
            href={sources[0].url} 
            target="_blank" 
            rel="noopener noreferrer"
          >
            Read More
          </ReadMoreButton>
        )}
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

const ReadMoreButton = styled.a`
  display: inline-block;
  margin-top: 10px;
  padding: 5px 10px;
  background-color: var(--primary-color);
  color: white !important;
  border-radius: 4px;
  text-decoration: none;
  font-size: 12px;
  font-weight: 500;
  
  &:hover {
    background-color: var(--primary-dark);
    text-decoration: none !important;
  }
`;

const MessageTime = styled.span`
  font-size: 11px;
  color: var(--light-text);
  margin-top: 5px;
`;

export default Message; 