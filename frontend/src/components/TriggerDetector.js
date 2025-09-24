import React, { useState } from 'react';
import styled from 'styled-components';


// Enhanced trigger word definitions with priority levels and keywords
const TRIGGER_WORDS = {
  emergency: {
    priority: 1,
    // Exact phrases for precise matching
    exactPhrases: [
      'stroke', 'slurred speech', 'garbled speech', 'unable to talk', 'face drop', 'facial droop',
      'problems with balance and coordination', 'a sudden and severe blinding headache',
      'difficulty understanding what other people are saying',
      'loss of vision in one eye or one half of both eyes', 'sudden onset dizziness or vertigo',
      'sudden loss of sensation on one side of the body',
      'i have a stroke', 'i think i have a stroke', 'i might have a stroke',
      'face is numb', 'face feels numb', 'face is drooping', 'face is dropping',
      'can\'t lift my arm', 'cannot lift my arm', 'unable to lift my arm',
      'speech is slurred', 'speech is garbled', 'can\'t speak clearly'
    ],
    // Keywords for smart matching (more specific to avoid false positives)
    keywords: [
      'stroke', 'face', 'numbness', 'one-sided', 'weakness', 'confusion',
      'slurred', 'garbled', 'unable', 'talk', 'speech', 'drop', 'droop',
      'balance', 'coordination', 'blinding', 'sudden', 'vision', 'eye', 
      'dizziness', 'vertigo', 'sensation', 'arm', 'leg', 'terrible', 'severe'
    ],
    // Common variations (very specific emergency phrases only)
    variations: [
      'can\'t lift arm', 'cannot lift arm', 'unable to lift arm',
      'face numbness', 'face feels numb', 'numb face',
      'dizzy suddenly', 'sudden dizziness', 'feel dizzy',
      'can\'t talk', 'cannot talk', 'unable to talk',
      'face drop', 'face droop', 'facial drop', 'facial droop',
      'balance problems', 'coordination problems', 'balance issues',
      'blinding headache', 'sudden severe blinding headache', 'terrible blinding headache',
      'vision loss', 'can\'t see', 'cannot see', 'unable to see',
      'confusion', 'confused', 'not understanding'
    ],
    response: {
      title: '⚠️ Emergency Medical Alert',
      message: `Unfortunately, many migraine symptoms are frequently the same as life threatening conditions, such as stroke. Never presume what you have is migraine. Always seek medical advice. If you are worried you might have stroke symptoms contact 112/999 immediately.

From the HSE: You can recognise a stroke and know what to do by using the word FAST:
• Face – your face may have dropped on one side, you may not be able to smile, or your mouth/eyelid may droop.
• Arms – you may not be able to lift both arms and keep them there because of weakness or numbness in 1 arm.
• Speech – your speech may be slurred or garbled, or you may not be able to talk at all.
• Time – it's time to dial 999 immediately if you have any of these signs or symptoms.`,
      buttons: [
        { text: 'Call 112', action: 'tel:112', type: 'emergency' },
        { text: 'Call 999', action: 'tel:999', type: 'emergency' },
        { text: 'HSE Stroke Info', action: '#', type: 'info' }
      ]
    }
  },
  suicide: {
    priority: 2,
    // Exact phrases for precise matching
    exactPhrases: [
      'suicide', 'kill me now', 'i want to die', 'i want to end it', 'i want to end it all'
    ],
    // Keywords for smart matching
    keywords: [
      'suicide', 'die', 'death', 'kill', 'ending', 'unbearable', 'alone',
      'take', 'anymore', 'thinking', 'about'
    ],
    // Common variations
    variations: [
      'can\'t take it anymore', 'cannot take it anymore', 'unable to take it anymore',
      'ending it all', 'ending it', 'thinking of ending', 'thinking about ending',
      'want to die', 'wanting to die', 'thinking of dying', 'thinking about dying',
      'kill myself', 'killing myself', 'end myself', 'ending myself',
      'i want to end it', 'i want to end it all', 'i want to end my life',
      'too much', 'overwhelming', 'can\'t handle it', 'cannot handle it'
    ],
    response: {
      title: '⚠️ Crisis Support Available',
      message: `If you are worried that you or a loved one is at risk from suicide please call 999/112 immediately. See Urgent help – HSE.ie

Samaritans – Pieta – Alone – Aware`,
      buttons: [
        { text: 'Call 112', action: 'tel:112', type: 'emergency' },
        { text: 'Call 999', action: 'tel:999', type: 'emergency' },
        { text: 'Samaritans', action: '#', type: 'support' },
        { text: 'Pieta', action: '#', type: 'support' },
        { text: 'ALONE', action: '#', type: 'support' },
        { text: 'HSE Urgent Help', action: '#', type: 'support' }
      ]
    }
  },
  doctor: {
    priority: 3,
    // Exact phrases for precise matching
    exactPhrases: [
      'paralysis', 'child', 'medications', 'diagnosis', 'treatment'
    ],
    // Keywords for smart matching
    keywords: [
      'paralysis', 'child', 'medications', 'diagnosis', 'treatment',
      'worsening', 'pain', 'symptoms', 'new', 'excruciating', 'severe',
      'do i have', 'do i', 'have', 'getting worse', 'worse'
    ],
    // Common variations
    variations: [
      'worsening pain', 'pain getting worse', 'pain is worse', 'worse pain',
      'my pain is worsening', 'my pain is getting worse', 'my pain is worse',
      'worsening symptoms', 'symptoms getting worse', 'symptoms are worse', 'worse symptoms',
      'my symptoms are worsening', 'my symptoms are getting worse', 'my symptoms are worse',
      'new symptoms', 'new pain', 'new problem', 'new issue',
      'excruciating pain', 'severe pain', 'terrible pain', 'awful pain',
      'do i have', 'do i', 'have i', 'am i', 'could i have'
    ],
    response: {
      title: '📋 Medical Advice Recommended',
      message: `Talk to your doctor immediately. For informational support email info@migraine.ie. Please note this is a limited informational support service which receives a high volume of queries and it may take some time to respond.

Please do not enter personal or medical identifiers in your messages.`,
      buttons: [
        { text: 'Continue', action: 'continue', type: 'continue' }
      ]
    }
  }
};

// Generate a unique session ID
// const generateSessionId = () => {
//   return 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
// };

// Get or create session ID
// const getSessionId = () => {
//   let sessionId = sessionStorage.getItem('migraine-chatbot-session-id');
//   if (!sessionId) {
//     sessionId = generateSessionId();
//     sessionStorage.setItem('migraine-chatbot-session-id', sessionId);
//   }
//   return sessionId;
// };

// Normalize text for matching (handle hyphens, spacing, case)
const normalizeText = (text) => {
  return text.toLowerCase()
    .replace(/[-\s]+/g, ' ')  // Replace hyphens and multiple spaces with single space
    .trim();
};


// Check for exact phrase matches
const checkExactPhrases = (text, phrases) => {
  const normalizedText = normalizeText(text);
  
  for (const phrase of phrases) {
    const normalizedPhrase = normalizeText(phrase);
    const regex = new RegExp(`\\b${normalizedPhrase.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i');
    if (regex.test(normalizedText)) {
      return { matched: true, phrase, confidence: 1.0 };
    }
  }
  
  return { matched: false, confidence: 0 };
};

// Check for variation matches with flexible word order
const checkVariations = (text, variations) => {
  const normalizedText = normalizeText(text);
  
  for (const variation of variations) {
    const normalizedVariation = normalizeText(variation);
    
    // First try exact match
    const exactRegex = new RegExp(`\\b${normalizedVariation.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i');
    if (exactRegex.test(normalizedText)) {
      return { matched: true, variation, confidence: 0.9 };
    }
    
    // Then try flexible word order for multi-word variations
    if (normalizedVariation.includes(' ')) {
      const words = normalizedVariation.split(/\s+/);
      if (words.length >= 2) {
        // Check if all words appear in the text (flexible order)
        const allWordsPresent = words.every(word => 
          normalizedText.includes(word)
        );
        
        if (allWordsPresent) {
          // Calculate proximity score
          const wordPositions = words.map(word => {
            const index = normalizedText.indexOf(word);
            return index !== -1 ? index : -1;
          }).filter(pos => pos !== -1);
          
          if (wordPositions.length === words.length) {
            // Calculate average distance between words
            let totalDistance = 0;
            for (let i = 0; i < wordPositions.length - 1; i++) {
              totalDistance += Math.abs(wordPositions[i + 1] - wordPositions[i]);
            }
            const averageDistance = totalDistance / (wordPositions.length - 1);
            
            // Higher confidence for closer words
            const proximityScore = Math.max(0, 1 - (averageDistance / normalizedText.length));
            const confidence = 0.7 + (proximityScore * 0.2); // 0.7 to 0.9 range
            
            return { matched: true, variation, confidence };
          }
        }
      }
    }
  }
  
  return { matched: false, confidence: 0 };
};

// Check for keyword combinations with flexible word order and proximity
const checkKeywordCombinations = (text, keywords) => {
  const normalizedText = normalizeText(text);
  const textWords = normalizedText.split(/\s+/);
  
  let matchedKeywords = [];
  let keywordPositions = [];
  
  // Find all keyword matches and their positions
  keywords.forEach(keyword => {
    const normalizedKeyword = normalizeText(keyword);
    
    // Check if keyword appears in text (exact word match or partial)
    textWords.forEach((word, index) => {
      if (word.includes(normalizedKeyword) || normalizedKeyword.includes(word)) {
        // Check if this keyword is already matched
        if (!matchedKeywords.includes(keyword)) {
          matchedKeywords.push(keyword);
          keywordPositions.push(index);
        }
      }
    });
  });
  
  // Special handling for headache-related emergency detection
  if (normalizedText.includes('headache')) {
    const emergencyModifiers = ['blinding', 'terrible', 'severe', 'sudden', 'worst'];
    const hasEmergencyModifier = emergencyModifiers.some(modifier => 
      normalizedText.includes(modifier)
    );
    
    if (hasEmergencyModifier) {
      // Add "headache" to the list of matched keywords
      if (!matchedKeywords.includes('headache')) {
          matchedKeywords.push('headache');
      }
      
      return {
        matched: true,
        keywords: matchedKeywords,
        confidence: 0.95 // High confidence for specific emergency headache
      };
    }
  }
  
  // If we have enough keywords, calculate proximity score
  if (matchedKeywords.length >= 2) {
    // Calculate average distance between keywords
    let totalDistance = 0;
    let distanceCount = 0;
    
    for (let i = 0; i < keywordPositions.length - 1; i++) {
      for (let j = i + 1; j < keywordPositions.length; j++) {
        const distance = Math.abs(keywordPositions[i] - keywordPositions[j]);
        totalDistance += distance;
        distanceCount++;
      }
    }
    
    const averageDistance = distanceCount > 0 ? totalDistance / distanceCount : 0;
    const maxDistance = textWords.length - 1;
    
    // Higher score for keywords closer together
    const proximityScore = Math.max(0, 1 - (averageDistance / maxDistance));
    
    // Calculate confidence based on keyword count and proximity
    const keywordRatio = matchedKeywords.length / keywords.length;
    const confidence = (keywordRatio * 0.6) + (proximityScore * 0.4);
    
    // Dynamic minimum keywords based on category
    const minKeywords = keywords.length > 20 ? 2 : 2; // Reduced threshold
    
    return {
      matched: matchedKeywords.length >= minKeywords && confidence >= 0.5,
      keywords: matchedKeywords,
      confidence: Math.min(confidence, 0.8)
    };
  }
  
  return {
    matched: false,
    keywords: matchedKeywords,
    confidence: 0
  };
};

// Blacklist of common false positive phrases
const FALSE_POSITIVE_PHRASES = [
  'i have been having a headache',
  'i have a headache',
  'my head hurts',
  'headache',
  'head pain',
  'migraine headache',
  'tension headache'
];

// List of words that permit a blacklisted phrase to be checked further
const PERMITTED_MODIFIERS = ['blinding', 'terrible', 'severe', 'sudden', 'worst'];

// Check if text contains false positive phrases
const isFalsePositive = (text) => {
  const normalizedText = normalizeText(text);
  
  // Check if any permitted modifier exists in the text
  const hasPermittedModifier = PERMITTED_MODIFIERS.some(modifier => 
    normalizedText.includes(modifier)
  );

  // If a permitted modifier is present, it's not a false positive, so we should check it.
  if (hasPermittedModifier) {
    return false;
  }

  // Otherwise, check against the blacklist.
  return FALSE_POSITIVE_PHRASES.some(phrase => 
    normalizedText.includes(normalizeText(phrase))
  );
};

// Smart trigger detection with multiple matching strategies
const detectTriggers = (text) => {
  const detectedTriggers = [];

  // Skip detection if it's a known false positive
  if (isFalsePositive(text)) {
    return null;
  }

  // Require minimum word count to prevent single word triggers
  const wordCount = normalizeText(text).split(/\s+/).length;
  if (wordCount < 2) {
    return null; // Skip single word inputs
  }

  // Check each trigger category with smart detection
  Object.entries(TRIGGER_WORDS).forEach(([category, config]) => {
    let bestMatch = null;
    let highestConfidence = 0;

    // Strategy 1: Check exact phrases (highest confidence)
    const exactMatch = checkExactPhrases(text, config.exactPhrases);
    if (exactMatch.matched && exactMatch.confidence > highestConfidence) {
      bestMatch = {
        category,
        priority: config.priority,
        triggerWord: exactMatch.phrase,
        response: config.response,
        confidence: exactMatch.confidence,
        method: 'exact'
      };
      highestConfidence = exactMatch.confidence;
      
    }

    // Strategy 2: Check variations (high confidence)
    const variationMatch = checkVariations(text, config.variations);
    if (variationMatch.matched && variationMatch.confidence > highestConfidence) {
      bestMatch = {
        category,
        priority: config.priority,
        triggerWord: variationMatch.variation,
        response: config.response,
        confidence: variationMatch.confidence,
        method: 'variation'
      };
      highestConfidence = variationMatch.confidence;
      
    }

    // Strategy 3: Check keyword combinations (medium confidence)
    const keywordMatch = checkKeywordCombinations(text, config.keywords);
    if (keywordMatch.matched && keywordMatch.confidence > highestConfidence) {
      bestMatch = {
        category,
        priority: config.priority,
        triggerWord: keywordMatch.keywords.join(', '),
        response: config.response,
        confidence: keywordMatch.confidence,
        method: 'keywords'
      };
      highestConfidence = keywordMatch.confidence;
      
    }

    // Add the best match for this category if confidence is high enough
    // Balanced threshold for better detection
    const minConfidence = category === 'emergency' ? 0.7 : 0.6;
    if (bestMatch && highestConfidence >= minConfidence) {
      detectedTriggers.push(bestMatch);
      
    } else if (bestMatch) {
      // Debug logging for rejected matches
    }
  });

  // Return the highest priority trigger (lowest number = highest priority)
  if (detectedTriggers.length > 0) {
    detectedTriggers.sort((a, b) => a.priority - b.priority);
    
    return detectedTriggers[0];
  }

  return null;
};


// Emergency Response Banner Component
const EmergencyBanner = ({ trigger, onAcknowledge, onEnableChat }) => {
  const [isVisible, setIsVisible] = useState(true);

  const handleAcknowledge = () => {
    setIsVisible(false);
    onAcknowledge();
  };

  const handleEnableChat = () => {
    setIsVisible(false);
    onEnableChat();
  };

  const handleButtonClick = (button) => {
    if (button.action === 'continue') {
      handleAcknowledge();
    } else if (button.action.startsWith('tel:')) {
      window.location.href = button.action;
    } else if (button.action.startsWith('http')) {
      window.open(button.action, '_blank');
    }
  };

  if (!isVisible) return null;

  return (
    <BannerContainer 
      role="alert" 
      aria-live="assertive"
      priority={trigger.category}
    >
      <BannerHeader>
        <span aria-hidden="true">⚠️</span>
        {trigger.response.title}
      </BannerHeader>
      
      <BannerContent>
        {trigger.response.message.split('\n').map((line, index) => (
          <BannerText key={index}>
            {line}
          </BannerText>
        ))}
      </BannerContent>
      
      <BannerButtons>
        {trigger.response.buttons.map((button, index) => (
          <BannerButton
            key={index}
            onClick={() => handleButtonClick(button)}
            buttonType={button.type}
            priority={trigger.category}
          >
            {button.text}
          </BannerButton>
        ))}
      </BannerButtons>
      
      {/* Only show acknowledge button for Doctor contact level */}
      {onEnableChat && (
        <ButtonRow>
          <ContinueButton onClick={handleAcknowledge}>
            Acknowledge
          </ContinueButton>
          <EnableChatButton onClick={handleEnableChat}>
            Re-enable Chat
          </EnableChatButton>
        </ButtonRow>
      )}
    </BannerContainer>
  );
};

// Doctor Contact Note Component
const DoctorNote = ({ onAcknowledge, onEnableChat }) => {
  const [isVisible, setIsVisible] = useState(true);

  const handleAcknowledge = () => {
    setIsVisible(false);
    onAcknowledge();
  };

  const handleEnableChat = () => {
    setIsVisible(false);
    onEnableChat();
  };

  if (!isVisible) return null;

  return (
    <NoteContainer role="note" aria-live="polite">
      <NoteHeader>
        <span aria-hidden="true">📋</span>
        Medical Advice Recommended
      </NoteHeader>
      
      <NoteContent>
        Talk to your doctor immediately. For informational support email info@migraine.ie. 
        Please note this is a limited informational support service which receives a high volume of queries and it may take some time to respond.
      </NoteContent>
      
      <NoteWarning>
        Please do not enter personal or medical identifiers in your messages.
      </NoteWarning>
      
      <NoteButtonRow>
        <NoteButton onClick={handleAcknowledge}>
          Acknowledge
        </NoteButton>
        <NoteButton onClick={handleEnableChat}>
          Re-enable Chat
        </NoteButton>
      </NoteButtonRow>
    </NoteContainer>
  );
};

// Main Trigger Detector Hook
export const useTriggerDetection = (saveHistory) => {
  const [activeTrigger, setActiveTrigger] = useState(null);
  const [isBlocked, setIsBlocked] = useState(false);
  const [chatDisabled, setChatDisabled] = useState(false);

  const checkTriggers = async (text) => {
    const trigger = detectTriggers(text);
    
    if (trigger) {
      setActiveTrigger(trigger);
      setIsBlocked(true);
      setChatDisabled(true); // Disable chat after trigger
      
      // Log trigger event to the backend
      if (saveHistory) {
        await saveHistory({
          event_type: `trigger_${trigger.category}`,
          user_message_text: text,
          bot_response_text: trigger.response?.message || '',
          trigger_detection_method: trigger.method || 'unknown',
          trigger_confidence: trigger.confidence || 0,
          trigger_matched_phrase: trigger.triggerWord || 'unknown',
        });
      }
      
      return trigger; // Return the full trigger object
    }
    
    return null; // Return null if no trigger detected
  };

  const acknowledgeTrigger = () => {
    setActiveTrigger(null);
    setIsBlocked(false);
    // Keep chat disabled after acknowledging trigger
    // User needs to manually re-enable if they want to continue
  };

  const enableChat = () => {
    setChatDisabled(false);
    setActiveTrigger(null);
    setIsBlocked(false);
  };

  const renderTriggerResponse = () => {
    if (!activeTrigger) return null;

    if (activeTrigger.category === 'doctor') {
      return <DoctorNote onAcknowledge={acknowledgeTrigger} onEnableChat={enableChat} />;
    } else {
      // Emergency and Suicide triggers don't allow re-enabling chat
      return (
        <EmergencyBanner 
          trigger={activeTrigger} 
          onAcknowledge={acknowledgeTrigger}
          onEnableChat={null} // No re-enable for emergency/suicide
        />
      );
    }
  };

  return {
    checkTriggers,
    acknowledgeTrigger,
    enableChat,
    renderTriggerResponse,
    isBlocked,
    chatDisabled,
    activeTrigger
  };
};

// Styled Components
const BannerContainer = styled.div`
  background: ${props => 
    props.priority === 'emergency' 
      ? 'linear-gradient(135deg, #ffebee 0%, #ffcdd2 100%)'
      : 'linear-gradient(135deg, #fff3e0 0%, #ffe0b2 100%)'
  };
  border: 2px solid ${props => 
    props.priority === 'emergency' ? '#d32f2f' : '#f57c00'
  };
  border-radius: 12px;
  padding: 20px;
  margin: 15px 0;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
  max-width: 100%;
`;

const BannerHeader = styled.h3`
  color: ${props => props.priority === 'emergency' ? '#c62828' : '#e65100'};
  margin: 0 0 15px 0;
  font-size: 1.1rem;
  font-weight: 600;
  text-align: center;
`;

const BannerContent = styled.div`
  margin-bottom: 20px;
`;

const BannerText = styled.p`
  color: #8b4513;
  font-size: 0.9rem;
  line-height: 1.5;
  margin: 0 0 8px 0;
  
  &:last-child {
    margin-bottom: 0;
  }
`;

const BannerButtons = styled.div`
  display: flex;
  gap: 10px;
  justify-content: center;
  flex-wrap: wrap;
  margin-bottom: 15px;
`;

const BannerButton = styled.button`
  background: ${props => 
    props.buttonType === 'emergency' ? '#d32f2f' : 
    props.buttonType === 'support' ? '#1976d2' : '#4caf50'
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
    background: ${props => 
      props.buttonType === 'emergency' ? '#b71c1c' : 
      props.buttonType === 'support' ? '#1565c0' : '#388e3c'
    };
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
`;

const ContinueButton = styled.button`
  background: #72b519;
  color: white;
  border: none;
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  font-size: 0.95rem;
  flex: 1;
  
  &:hover {
    background: #5a8f15;
    transform: translateY(-1px);
  }
  
  &:focus {
    outline: 3px solid #3498db;
    outline-offset: 2px;
  }
  
  /* When it's the only button, take full width */
  &:only-child {
    flex: none;
    width: 100%;
  }
`;

const EnableChatButton = styled.button`
    background: #3498db;
    color: white;
    border: none;
    padding: 12px 24px;
    border-radius: 8px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
    font-size: 0.95rem;
    flex: 1;
    
    &:hover {
      background: #2980b9;
      transform: translateY(-1px);
    }
    
    &:focus {
      outline: 3px solid #72b519;
      outline-offset: 2px;
    }
  `;
  
  const NoteContainer = styled.div`
    background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%);
    border: 2px solid #4caf50;
    border-radius: 8px;
    padding: 15px;
    margin: 10px 0;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  `;
  
  const NoteHeader = styled.h4`
    color: #2e7d32;
    margin: 0 0 10px 0;
    font-size: 1rem;
    font-weight: 600;
  `;
  
  const NoteContent = styled.p`
    color: #388e3c;
    font-size: 0.9rem;
    line-height: 1.4;
    margin: 0 0 8px 0;
  `;
  
  const NoteWarning = styled.p`
    color: #d32f2f;
    font-size: 0.85rem;
    font-weight: 600;
    margin: 0 0 10px 0;
  `;
  
  const NoteButtonRow = styled.div`
    display: flex;
    gap: 8px;
    margin-top: 10px;
  `;
  
  const NoteButton = styled.button`
    background: #72b519;
    color: white;
    border: none;
    padding: 8px 16px;
    border-radius: 6px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s ease;
    font-size: 0.9rem;
    flex: 1;
    
    &:hover {
      background: #5a8f15;
    }
    
    &:focus {
      outline: 3px solid #3498db;
      outline-offset: 2px;
    }
    
    &:nth-child(2) {
      background: #3498db;
      
      &:hover {
        background: #2980b9;
      }
    }
  `;
  
  const TriggerDetector = { useTriggerDetection, detectTriggers };
  export default TriggerDetector;