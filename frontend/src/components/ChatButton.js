import React from 'react';
import styled from 'styled-components';
import { FaComments, FaTimes } from 'react-icons/fa';

const ChatButton = ({ onClick, isOpen }) => {
  return (
    <Button onClick={onClick}>
      {isOpen ? <FaTimes /> : <FaComments />}
    </Button>
  );
};

const Button = styled.button`
  background-color: var(--primary-color);
  color: white;
  border: none;
  border-radius: 50%;
  width: 60px;
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: var(--shadow);
  transition: all 0.3s ease;
  font-size: 24px;
  
  &:hover {
    background-color: var(--primary-dark);
    transform: scale(1.05);
  }
  
  &:focus {
    outline: none;
  }
`;

export default ChatButton;
