import React, { useEffect, useRef } from 'react';
import styled from 'styled-components';

const ConsentMessage = ({ onAccept, onDecline }) => {
  const acceptButtonRef = useRef(null);
  const declineButtonRef = useRef(null);
  const containerRef = useRef(null);

  // Focus management and keyboard navigation
  useEffect(() => {
    // Focus the accept button when component mounts
    if (acceptButtonRef.current) {
      acceptButtonRef.current.focus();
    }

    // Handle keyboard navigation
    const handleKeyDown = (event) => {
      switch (event.key) {
        case 'Tab':
          // Allow normal tab navigation between buttons
          break;
        case 'Enter':
        case ' ':
          // Prevent default to avoid page scrolling
          event.preventDefault();
          if (document.activeElement === acceptButtonRef.current) {
            onAccept();
          } else if (document.activeElement === declineButtonRef.current) {
            onDecline();
          }
          break;
        case 'Escape':
          // Allow escape to decline
          event.preventDefault();
          onDecline();
          break;
        case 'ArrowLeft':
        case 'ArrowRight':
          // Allow arrow key navigation between buttons
          event.preventDefault();
          if (document.activeElement === acceptButtonRef.current) {
            declineButtonRef.current?.focus();
          } else if (document.activeElement === declineButtonRef.current) {
            acceptButtonRef.current?.focus();
          }
          break;
        default:
          break;
      }
    };

    // Add event listener
    const container = containerRef.current;
    if (container) {
      container.addEventListener('keydown', handleKeyDown);
    }

    // Cleanup
    return () => {
      if (container) {
        container.removeEventListener('keydown', handleKeyDown);
      }
    };
  }, [onAccept, onDecline]);

  return (
    <ConsentContainer 
      ref={containerRef}
      role="dialog" 
      aria-labelledby="consent-header" 
      aria-describedby="consent-content"
      tabIndex="-1"
    >
      <ConsentHeader id="consent-header">
        <span aria-hidden="true">⚠️</span> Important Disclaimer
      </ConsentHeader>
      <ConsentContent id="consent-content">
        <ConsentText>
          This is an Artificial Intelligence (AI) tool. It is for informational and educational purposes only. It is not a medical device, and it cannot provide medical advice or diagnosis.
        </ConsentText>
        
        <ConsentText>
          Unfortunately, many migraine symptoms are frequently the same as life threatening conditions, such as stroke. Never presume what you have is migraine. Always seek medical advice. If you are worried you might have stroke symptoms contact 112/999 immediately.
        </ConsentText>
        
        <ConsentText>
          For medical advice or diagnosis, you must see a Health Care Professional such as your GP. In case of emergencies call 112 or 999 or attend your nearest Emergency Department.
        </ConsentText>
        
        <ConsentText>
          The content this chatbot generates may not be accurate. Please note, any data submitted by you to the service is processed by the AI system/model owners and not by Migraine Ireland. Therefore, please do not submit any personal or medical information, such as your name, health problems, doctor's name, etc.
        </ConsentText>
        
        <ConsentText>
          It uses ChatGPT which is a large language content generation system built on an underlying Open AI model. It is designed for content creation and is being used by Migraine Ireland to assist you with using our site only. If you understand this and are happy to accept it, please click yes.
        </ConsentText>
      </ConsentContent>
      
      <ConsentButtons role="group" aria-label="Consent options">
        <AcceptButton 
          ref={acceptButtonRef}
          onClick={onAccept}
          aria-label="Accept the disclaimer and continue using the chatbot"
          title="Accept the disclaimer and continue using the chatbot"
        >
          Yes (Agree)
        </AcceptButton>
        <DeclineButton 
          ref={declineButtonRef}
          onClick={onDecline}
          aria-label="Decline the disclaimer and close the chatbot"
          title="Decline the disclaimer and close the chatbot"
        >
          No (Decline)
        </DeclineButton>
      </ConsentButtons>
    </ConsentContainer>
  );
};

const ConsentContainer = styled.div`
  background: linear-gradient(135deg, #fff3cd 0%, #ffeaa7 100%);
  border: 2px solid #f39c12;
  border-radius: 12px;
  padding: 20px;
  margin: 15px 0;
  box-shadow: 0 4px 12px rgba(243, 156, 18, 0.2);
  max-width: 100%;
`;

const ConsentHeader = styled.h3`
  color: #d68910;
  margin: 0 0 15px 0;
  font-size: 1.1rem;
  font-weight: 600;
  text-align: center;
`;

const ConsentContent = styled.div`
  margin-bottom: 20px;
`;

const ConsentText = styled.p`
  color: #8b4513;
  font-size: 0.9rem;
  line-height: 1.5;
  margin: 0 0 12px 0;
  
  &:last-child {
    margin-bottom: 0;
  }
`;

const ConsentButtons = styled.div`
  display: flex;
  gap: 12px;
  justify-content: center;
  flex-wrap: wrap;
`;

const AcceptButton = styled.button`
  background: #27ae60;
  color: white;
  border: none;
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  font-size: 0.95rem;
  
  &:hover {
    background: #229954;
    transform: translateY(-1px);
  }
  
  &:active {
    transform: translateY(0);
  }
  
  &:focus {
    outline: 3px solid #3498db;
    outline-offset: 2px;
    background: #229954;
  }
  
  &:focus:not(:focus-visible) {
    outline: none;
  }
`;

const DeclineButton = styled.button`
  background: #e74c3c;
  color: white;
  border: none;
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  font-size: 0.95rem;
  
  &:hover {
    background: #c0392b;
    transform: translateY(-1px);
  }
  
  &:active {
    transform: translateY(0);
  }
  
  &:focus {
    outline: 3px solid #3498db;
    outline-offset: 2px;
    background: #c0392b;
  }
  
  &:focus:not(:focus-visible) {
    outline: none;
  }
`;

export default ConsentMessage;
