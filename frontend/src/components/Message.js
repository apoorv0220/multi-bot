import React from 'react';
import styled from 'styled-components';
import ReactMarkdown from 'react-markdown';

// Determine background color for trigger messages
const getTriggerBackgroundColor = (category) => {
  switch (category) {
    case 'emergency': return '#ffebee'; // Light red
    case 'suicide': return '#fff3e0'; // Light orange
    case 'doctor': return '#e8f5e9'; // Light green
    default: return 'var(--secondary-color)';
  }
};

// Determine border color for trigger messages
const getTriggerBorderColor = (category) => {
  switch (category) {
    case 'emergency': return '#d32f2f'; // Red
    case 'suicide': return '#f57c00'; // Orange
    case 'doctor': return '#4caf50'; // Green
    default: return 'transparent';
  }
};

const Message = ({ type, text, timestamp, sources = [], isError, source, isTrigger, triggerCategory, triggerButtons = [] }) => {
  // console.log("Message component received props:", { type, text, isTrigger, triggerCategory, sources, triggerButtons }); // Debug log removed
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
    sources.some(s => s.score >= 0.3); // Renamed 'source' to 's' to avoid conflict with prop 'source'

  return (
    <MessageContainer isError={isError} type={type} isTrigger={isTrigger} triggerCategory={triggerCategory}>
      <MessageContent 
        isError={isError} 
        type={type}
        isTrigger={isTrigger} // Pass to styled component
        triggerCategory={triggerCategory} // Pass to styled component
      >
        {isTrigger && <TriggerIcon category={triggerCategory}>⚠️</TriggerIcon>}
        <ReactMarkdown>{text}</ReactMarkdown>
        {type === 'bot' && !isError && source === 'vector_search' && hasHighConfidenceSource && (
          <ReadMoreButton 
            href={sources[0].url} 
            target="_blank" 
            rel="noopener noreferrer"
          >
            Read More
          </ReadMoreButton>
        )}
        {isTrigger && triggerButtons.length > 0 && (
            <TriggerButtonsContainer>
                {triggerButtons.map((button, idx) => (
                    <TriggerButton 
                        key={idx} 
                        buttonType={button.type}
                        onClick={(e) => {
                            e.preventDefault(); // Prevent default link behavior
                            if (button.action.startsWith('tel:')) {
                                window.location.href = button.action;
                            } else if (button.action.startsWith('http')) {
                                window.open(button.action, '_blank');
                            }
                            // No action for 'continue' for historical messages
                        }}
                    >
                        {button.text}
                    </TriggerButton>
                ))}
            </TriggerButtonsContainer>
        )}
      </MessageContent>
      <MessageTime type={type}>{formatTime(timestamp)}</MessageTime>
    </MessageContainer>
  );
};

const MessageContainer = styled.div`
  display: flex;
  flex-direction: column;
  align-items: ${props => props.type !== 'user' ? 'flex-start' : 'flex-end'};
  margin-bottom: 15px;
  max-width: 85%;
  align-self: ${props => props.type !== 'user' ? 'flex-start' : 'flex-end'};
`;

const MessageContent = styled.div`
  background-color: ${props => {
    // console.log("MessageContent styling evaluation:", { isTrigger: props.isTrigger, triggerCategory: props.triggerCategory }); // Debug log removed
    if (props.isError) return 'var(--error-color)';
    if (props.isTrigger) return getTriggerBackgroundColor(props.triggerCategory); // Corrected: use local function
    return props.type !== 'user' ? 'var(--secondary-color)' : 'var(--primary-color)';
  }};
  color: ${props => props.type !== 'user' ? 'var(--text-color)' : 'white'};
  padding: 12px 16px;
  border-radius: 18px;
  border-bottom-left-radius: ${props => props.type !== 'user' ? '4px' : '18px'};
  border-bottom-right-radius: ${props => props.type !== 'user' ? '18px' : '4px'};
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
  word-break: break-word;
  border: ${props => props.isTrigger ? `1px solid ${getTriggerBorderColor(props.triggerCategory)}` : 'none'}; // Corrected: use local function
  position: relative; // For trigger icon positioning
  
  p {
    margin: 0;
    line-height: 1.4;
  }
  
  a {
    color: ${props => props.type !== 'user' ? 'var(--primary-color)' : 'white'};
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

const TriggerIcon = styled.span`
  position: absolute;
  top: -8px; // Adjust as needed
  left: -8px; // Adjust as needed
  font-size: 1.2em;
  background-color: white;
  border-radius: 50%;
  padding: 2px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.2);
  z-index: 10; // Ensure it's above the message content
`;

const TriggerButtonsContainer = styled.div`
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
`;

const TriggerButton = styled.button`
  background-color: ${props => {
    switch (props.buttonType) {
      case 'emergency': return '#d32f2f';
      case 'support': return '#1976d2';
      case 'continue': return '#4caf50';
      default: return '#cccccc';
    }
  }};
  color: white;
  border: none;
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 0.85em;
  cursor: pointer;
  transition: background-color 0.2s ease;

  &:hover {
    opacity: 0.9;
  }
`;

export default Message; 