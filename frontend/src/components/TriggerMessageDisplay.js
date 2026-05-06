import React from 'react';
import styled from 'styled-components';

const getCategoryColors = (category) => {
  switch (category) {
    case 'emergency':
      return {
        background: 'linear-gradient(135deg, #ffebee 0%, #ffcdd2 100%)',
        border: '#d32f2f',
        header: '#c62828',
        text: '#8b4513',
      };
    case 'suicide':
      return {
        background: 'linear-gradient(135deg, #fff3e0 0%, #ffe0b2 100%)',
        border: '#f57c00',
        header: '#e65100',
        text: '#8b4513',
      };
    case 'doctor':
      return {
        background: 'linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%)',
        border: '#4caf50',
        header: '#2e7d32',
        text: '#388e3c',
      };
    default:
      return {
        background: 'white',
        border: '#ccc',
        header: '#333',
        text: '#666',
      };
  }
};

const TriggerMessageDisplay = ({ title, message, buttons, category, onAcknowledge, onEnableChat }) => {
  const colors = getCategoryColors(category);

  const handleButtonClick = (button) => {
    if (button.action === 'continue') {
      onAcknowledge && onAcknowledge();
    } else if (button.action.startsWith('tel:')) {
      window.location.href = button.action;
    } else if (button.action.startsWith('http')) {
      window.open(button.action, '_blank');
    }
  };

  // Split message into paragraphs by double newline, handle single newlines within paragraphs
  const messageParagraphs = message.split('\n\n').map(para => para.split('\n').join('<br />'));

  return (
    <Container role="alert" aria-live="assertive" category={category} colors={colors}>
      <Header colors={colors}>
        <span aria-hidden="true">⚠️</span> {title}
      </Header>
      
      <Content>
        {messageParagraphs.map((para, index) => (
          <Text key={index} colors={colors} dangerouslySetInnerHTML={{ __html: para }} />
        ))}
      </Content>
      
      {buttons && buttons.length > 0 && (
        <ButtonsContainer>
          {buttons.map((button, index) => (
            <Button
              key={index}
              buttonType={button.type}
              onClick={() => handleButtonClick(button)}
              category={category}
            >
              {button.text}
            </Button>
          ))}
        </ButtonsContainer>
      )}

      {/* Only show acknowledge/re-enable for doctor triggers */}
      {(onAcknowledge || onEnableChat) && category === 'doctor' && (
        <ButtonRow>
          {onAcknowledge && (
            <ActionButtons onClick={onAcknowledge} isPrimary={true}>
              Acknowledge
            </ActionButtons>
          )}
          {onEnableChat && (
            <ActionButtons onClick={onEnableChat} isPrimary={false}>
              Re-enable Chat
            </ActionButtons>
          )}
        </ButtonRow>
      )}
      {/* Emergency and suicide triggers show only emergency/support buttons - no continue options */}
    </Container>
  );
};

// Styled Components
const Container = styled.div`
  background: ${props => props.colors.background};
  border: 2px solid ${props => props.colors.border};
  border-radius: 12px;
  padding: 20px;
  margin: 15px 0;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  max-width: 100%;
`;

const Header = styled.h3`
  color: ${props => props.colors.header};
  margin: 0 0 15px 0;
  font-size: 1.1rem;
  font-weight: 600;
  text-align: center;
`;

const Content = styled.div`
  margin-bottom: 20px;
`;

const Text = styled.p`
  color: ${props => props.colors.text};
  font-size: 0.9rem;
  line-height: 1.5;
  margin: 0 0 8px 0;
  
  &:last-child {
    margin-bottom: 0;
  }
`;

const ButtonsContainer = styled.div`
  display: flex;
  gap: 10px;
  justify-content: center;
  flex-wrap: wrap;
  margin-bottom: 15px;
`;

const Button = styled.button`
  background: ${props => 
    props.buttonType === 'emergency' ? '#d32f2f' : 
    props.buttonType === 'support' ? '#1976d2' : 
    props.buttonType === 'info' ? '#9e9e9e' : '#4caf50'
  };
  color: white;
  border: none;
  padding: 10px 16px;
  border-radius: 6px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  font-size: 0.9rem;
  
  &:hover {
    opacity: 0.9;
    transform: translateY(-1px);
  }
  
  &:focus {
    outline: 3px solid #3498db;
    outline-offset: 2px;
  }
`;

const ButtonRow = styled.div`
  display: flex;
  gap: 10px;
  margin-top: 15px;
  justify-content: center;
`;

const ActionButtons = styled.button`
  background: ${props => props.isPrimary ? '#72b519' : '#3498db'};
  color: white;
  border: none;
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  font-size: 0.95rem;
  flex: 1;
  max-width: 200px; /* Limit width for these specific action buttons */
  
  &:hover {
    background: ${props => props.isPrimary ? '#5a8f15' : '#2980b9'};
    transform: translateY(-1px);
  }
  
  &:focus {
    outline: 3px solid #3498db;
    outline-offset: 2px;
  }
`;

export default TriggerMessageDisplay;
