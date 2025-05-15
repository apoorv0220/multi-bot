import React from 'react';
import styled from 'styled-components';

const SourceCitation = ({ source }) => {
  // Truncate content preview if needed
  const preview = source.content?.length > 100 
    ? `${source.content.substring(0, 100)}...` 
    : source.content;

  return (
    <CitationContainer>
      <SourceLink href={source.url} target="_blank" rel="noopener noreferrer">
        <SourceTitle>{source.source}</SourceTitle>
        <SourceScore>Confidence: {Math.round(source.score * 100)}%</SourceScore>
      </SourceLink>
      {preview && <SourcePreview>{preview}</SourcePreview>}
    </CitationContainer>
  );
};

const CitationContainer = styled.div`
  background-color: #f8f9fa;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 12px;
  border-left: 3px solid var(--primary-color);
`;

const SourceLink = styled.a`
  display: flex;
  justify-content: space-between;
  align-items: center;
  text-decoration: none;
  color: var(--text-color);
  
  &:hover {
    text-decoration: underline;
  }
`;

const SourceTitle = styled.div`
  font-weight: 500;
  color: var(--primary-color);
`;

const SourceScore = styled.div`
  color: var(--light-text);
  font-size: 11px;
`;

const SourcePreview = styled.div`
  margin-top: 5px;
  color: var(--light-text);
  font-style: italic;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
`;

export default SourceCitation; 