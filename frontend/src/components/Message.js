import React, { useMemo, useState } from 'react';
import styled from 'styled-components';
import ReactMarkdown from 'react-markdown';
import { client } from '../api';

const Message = ({
  type,
  text,
  timestamp,
  sources = [],
  isError,
  source,
  messageId,
  mode = "admin",
  apiUrl = "",
  widgetKey = "",
  userBubbleTextColor = "#ffffff",
  botBubbleTextColor = "#1a1a1a",
}) => {
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

  // If it's a trigger message, render TriggerMessageDisplay
  if (isTrigger) {
    return (
      <MessageContainer type={type} isTrigger={isTrigger} triggerCategory={triggerCategory}>
        <TriggerMessageDisplay
          title={botResponseTitle || (triggerCategory === 'emergency' ? '⚠️ Emergency Medical Alert' : triggerCategory === 'suicide' ? '⚠️ Crisis Support Available' : '📋 Medical Advice Recommended')}
          message={text}
          buttons={triggerButtons}
          category={triggerCategory}
          // onAcknowledge and onEnableChat are not passed here, as Message component is for display only
        />
        <MessageTime type={type}>{formatTime(timestamp)}</MessageTime>
      </MessageContainer>
    );
  }

  const feedbackStorageKey = useMemo(
    () => (messageId ? `feedback_${mode}_${widgetKey || "admin"}_${messageId}` : ""),
    [messageId, mode, widgetKey]
  );
  const [selectedVote, setSelectedVote] = useState(() => (feedbackStorageKey ? localStorage.getItem(feedbackStorageKey) : ""));

  const sendFeedback = async (vote) => {
    if (!messageId) return;
    try {
      const endpoint = mode === "public" ? `/api/public/messages/${messageId}/feedback` : `/api/messages/${messageId}/feedback`;
      const requestUrl = mode === "public" ? `${apiUrl}${endpoint}` : endpoint;
      await client.post(requestUrl, { vote }, {
        headers: mode === "public" ? { "X-Widget-Key": widgetKey } : undefined,
      });
      setSelectedVote(vote);
      if (feedbackStorageKey) {
        localStorage.setItem(feedbackStorageKey, vote);
      }
    } catch (err) {
      console.error("Feedback failed", err);
    }
  };

  return (
    <MessageContainer isError={isError} type={type}>
      <MessageContent
        isError={isError}
        type={type}
        className="mrnwebdesigns-chatbot-widget-message-content"
        $userText={userBubbleTextColor}
        $botText={botBubbleTextColor}
      >
        <ReactMarkdown>{text}</ReactMarkdown>
        {type === 'bot' && !isError && source === 'vector_search' && hasHighConfidenceSource && (
          <>
            <ReadMoreButton href={sources[0].url} target="_blank" rel="noopener noreferrer">Read More</ReadMoreButton>
            <FeedbackRow>
              <FeedbackButton selected={selectedVote === "up"} onClick={() => sendFeedback("up")} type="button">👍</FeedbackButton>
              <FeedbackButton selected={selectedVote === "down"} onClick={() => sendFeedback("down")} type="button">👎</FeedbackButton>
            </FeedbackRow>
          </>
        )}
        {/* Trigger buttons are now handled by TriggerMessageDisplay */}
      </MessageContent>
      <MessageTime type={type} className="mrnwebdesigns-chatbot-widget-message-time">{formatTime(timestamp)}</MessageTime>
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
  color: ${(props) => {
    if (props.isError) return '#fff';
    return props.type === 'user' ? props.$userText : props.$botText;
  }};
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
    color: ${(props) => {
      if (props.isError) return '#fff';
      if (props.type === 'user') return props.$userText;
      return 'var(--primary-color)';
    }};
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

const FeedbackRow = styled.div`
  margin-top: 8px;
  display: flex;
  gap: 6px;
`;

const FeedbackButton = styled.button`
  border: 1px solid ${props => (props.selected ? "var(--primary-color)" : "#ddd")};
  background: ${props => (props.selected ? "rgba(191, 54, 46, 0.12)" : "white")};
  border-radius: 6px;
  padding: 4px 8px;
  cursor: pointer;
`;

export default Message; 