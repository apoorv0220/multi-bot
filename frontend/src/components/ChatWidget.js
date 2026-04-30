import React, { useState, useRef, useEffect } from 'react';
import styled from 'styled-components';
import { BsSend } from 'react-icons/bs';
import Message from './Message';
import { client } from '../api';

const FALLBACK_GREETING =
  "Hello! I'm your MRN Web Designs Assistant. How can I help you today with website design, development, SEO, or digital marketing?";
const FALLBACK_HEADER_TITLE = "MRN Web Designs Assistant";

const resolveInitialGreeting = () => FALLBACK_GREETING;
const createVisitorId = () => {
  if (window?.crypto?.randomUUID) return window.crypto.randomUUID();
  return `visitor-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
};

const createBotMessage = (text) => ({
  id: 1,
  type: "bot",
  text,
  timestamp: new Date(),
});

const ChatWidget = ({ mode = "admin" }) => {
  const [messages, setMessages] = useState([createBotMessage(resolveInitialGreeting())]);
  const [headerTitle, setHeaderTitle] = useState(FALLBACK_HEADER_TITLE);
  const [brandName, setBrandName] = useState("Nethues");
  const [avatarUrl, setAvatarUrl] = useState("");
  const [privacyPolicyUrl, setPrivacyPolicyUrl] = useState("");
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [apiUrl, setApiUrl] = useState(process.env.REACT_APP_API_URL || "");
  const [widgetKey, setWidgetKey] = useState(null);
  const [sessionStorageKey, setSessionStorageKey] = useState("chat_session_id");
  const [sessionId, setSessionId] = useState(localStorage.getItem("chat_session_id") || null);
  const [visitorId, setVisitorId] = useState(localStorage.getItem("chat_visitor_id") || null);
  const [publicConfigError, setPublicConfigError] = useState("");
  const [isProfileRequired, setIsProfileRequired] = useState(false);
  const [visitorName, setVisitorName] = useState("");
  const [visitorEmail, setVisitorEmail] = useState("");
  const [isSavingProfile, setIsSavingProfile] = useState(false);
  const [quotaBlocked, setQuotaBlocked] = useState(false);
  const [quotaMessage, setQuotaMessage] = useState("");
  const [idleRatingWaitSeconds, setIdleRatingWaitSeconds] = useState(120);
  const [showRatingPrompt, setShowRatingPrompt] = useState(false);
  const [selectedRating, setSelectedRating] = useState(0);
  const [ratingSubmitted, setRatingSubmitted] = useState(false);
  const [isSubmittingRating, setIsSubmittingRating] = useState(false);
  const messageEndRef = useRef(null);
  const inputRef = useRef(null);
  const idleTimerRef = useRef(null);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Focus input when widget opens
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    if (mode !== "public") return;
    const onMessage = (event) => {
      const data = event?.data;
      if (!data || typeof data !== "object") return;
      if (data.action !== "open-chat") return;
      if (data.apiUrl) setApiUrl(data.apiUrl);
      if (data.tenantPublicKey) setWidgetKey(data.tenantPublicKey);
      if (data.chatbotInitialText) {
        setMessages((prev) => (prev.length === 1 ? [createBotMessage(data.chatbotInitialText)] : prev));
      }
      if (data.chatbotHeaderTitle) {
        setHeaderTitle(data.chatbotHeaderTitle);
      }
      const keySuffix = data.tenantPublicKey || "default";
      const sessionKey = `chat_session_id_${keySuffix}`;
      const visitorKey = `chat_visitor_id_${keySuffix}`;
      const ratedSessionKey = `chat_session_rating_submitted_${keySuffix}`;
      let existingVisitorId = localStorage.getItem(visitorKey);
      if (!existingVisitorId) {
        existingVisitorId = createVisitorId();
        localStorage.setItem(visitorKey, existingVisitorId);
      }
      setSessionStorageKey(sessionKey);
      setSessionId(localStorage.getItem(sessionKey) || null);
      setVisitorId(existingVisitorId);
      const existingSession = localStorage.getItem(sessionKey) || null;
      if (existingSession && localStorage.getItem(`${ratedSessionKey}_${existingSession}`) === "true") {
        setRatingSubmitted(true);
      } else {
        setRatingSubmitted(false);
      }
      if (!data.tenantPublicKey) {
        setPublicConfigError("Widget is misconfigured: tenantPublicKey is required.");
      } else {
        setPublicConfigError("");
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [mode]);

  useEffect(() => {
    if (mode !== "public" || !widgetKey || !visitorId || !apiUrl) return;
    const checkProfile = async () => {
      try {
        const { data } = await client.get(`${apiUrl}/api/public/visitor-profile`, {
          headers: {
            "X-Widget-Key": widgetKey,
            "X-Visitor-Id": visitorId,
          },
        });
        setIsProfileRequired(!data?.profile_exists);
      } catch (err) {
        console.error("Error checking visitor profile:", err);
      }
    };
    checkProfile();
  }, [apiUrl, mode, visitorId, widgetKey]);

  useEffect(() => {
    if (mode !== "public" || !widgetKey || !apiUrl) return;
    const loadWidgetConfig = async () => {
      try {
        const { data } = await client.get(`${apiUrl}/api/public/config`, {
          headers: { "X-Widget-Key": widgetKey },
        });
        if (data?.header_title) {
          setHeaderTitle(data.header_title);
        }
        if (data?.welcome_message) {
          setMessages((prev) => (prev.length === 1 ? [createBotMessage(data.welcome_message)] : prev));
        }
        setBrandName(data?.brand_name || "Nethues");
        setAvatarUrl(data?.avatar_url || "");
        setPrivacyPolicyUrl(data?.privacy_policy_url || "");
        setIdleRatingWaitSeconds(Number(data?.idle_rating_wait_seconds || 120));
      } catch (err) {
        console.error("Error loading widget config:", err);
      }
    };
    loadWidgetConfig();
  }, [apiUrl, mode, widgetKey]);

  useEffect(() => {
    if (mode !== "public" || !widgetKey || !visitorId || !apiUrl || !sessionId) return;
    const checkExistingRating = async () => {
      try {
        const { data } = await client.get(`${apiUrl}/api/public/session-rating/${sessionId}`, {
          headers: {
            "X-Widget-Key": widgetKey,
            "X-Visitor-Id": visitorId,
          },
        });
        if (data?.submitted) {
          setRatingSubmitted(true);
          setSelectedRating(Number(data.rating || 0));
          setShowRatingPrompt(false);
        } else {
          setRatingSubmitted(false);
        }
      } catch (err) {
        console.error("Error checking session rating:", err);
      }
    };
    checkExistingRating();
  }, [apiUrl, mode, sessionId, visitorId, widgetKey]);

  useEffect(() => () => {
    if (idleTimerRef.current) {
      clearTimeout(idleTimerRef.current);
    }
  }, []);

  const resetIdleRatingTimer = () => {
    if (idleTimerRef.current) {
      clearTimeout(idleTimerRef.current);
    }
    if (mode !== "public" || !sessionId || ratingSubmitted || isProfileRequired || quotaBlocked) return;
    idleTimerRef.current = setTimeout(() => {
      setShowRatingPrompt(true);
    }, Math.max(Number(idleRatingWaitSeconds || 120), 5) * 1000);
  };

  const submitSessionRating = async (rating) => {
    if (!sessionId || ratingSubmitted) return;
    setIsSubmittingRating(true);
    try {
      await client.post(`${apiUrl}/api/public/session-rating`, {
        session_id: sessionId,
        rating,
      }, {
        headers: {
          "X-Widget-Key": widgetKey,
          "X-Visitor-Id": visitorId,
        },
      });
      setSelectedRating(rating);
      setRatingSubmitted(true);
      setShowRatingPrompt(false);
      const suffix = widgetKey || "default";
      localStorage.setItem(`chat_session_rating_submitted_${suffix}_${sessionId}`, "true");
    } catch (err) {
      if (err?.response?.status === 409) {
        setRatingSubmitted(true);
        setShowRatingPrompt(false);
        return;
      }
      setPublicConfigError(err?.response?.data?.detail || "Could not submit rating.");
    } finally {
      setIsSubmittingRating(false);
    }
  };

  const submitVisitorProfile = async () => {
    if (!visitorName.trim() || !visitorEmail.trim()) return;
    setIsSavingProfile(true);
    try {
      const { data } = await client.post(`${apiUrl}/api/public/visitor-profile`, {
        visitor_id: visitorId,
        name: visitorName.trim(),
        email: visitorEmail.trim(),
      }, {
        headers: {
          "X-Widget-Key": widgetKey,
        },
      });
      const resolvedVisitorId = data?.visitor_id;
      if (resolvedVisitorId && resolvedVisitorId !== visitorId) {
        const keySuffix = widgetKey || "default";
        const visitorKey = `chat_visitor_id_${keySuffix}`;
        localStorage.setItem(visitorKey, resolvedVisitorId);
        setVisitorId(resolvedVisitorId);
      }
      setIsProfileRequired(false);
    } catch (err) {
      console.error("Error saving visitor profile:", err);
      setPublicConfigError(err?.response?.data?.detail || "Could not save profile. Please try again.");
    } finally {
      setIsSavingProfile(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!input.trim()) return;
    if (mode === "public" && !widgetKey) {
      setPublicConfigError("Widget is misconfigured: tenantPublicKey is required.");
      return;
    }
    if (mode === "public" && quotaBlocked) {
      setPublicConfigError(quotaMessage || "Monthly message limit reached.");
      return;
    }
    if (mode === "public" && isProfileRequired) {
      setPublicConfigError("Please provide name and email first.");
      return;
    }

    // Add user message
    const userMessage = {
      type: 'user',
      text: input,
      timestamp: new Date(),
    };
    setMessages((prevMessages) => [...prevMessages, userMessage]);
    setInput('');
    setIsLoading(true);
    setShowRatingPrompt(false);
    resetIdleRatingTimer();

    try {
      const endpoint = mode === "public" ? "/api/public/chat" : "/api/chat";
      const requestUrl = mode === "public" ? `${apiUrl}${endpoint}` : endpoint;
      const response = await client.post(requestUrl, {
        message: input,
        session_id: sessionId,
        max_results: 3,
      }, {
        headers: mode === "public" ? { "X-Widget-Key": widgetKey, "X-Visitor-Id": visitorId } : undefined,
      });
      if (response.data.session_id) {
        const previousSessionId = sessionId;
        setSessionId(response.data.session_id);
        localStorage.setItem(sessionStorageKey, response.data.session_id);
        if (previousSessionId !== response.data.session_id) {
          setRatingSubmitted(false);
          setSelectedRating(0);
        }
      }

      // Add bot response with the new response format
      const botMessage = {
        type: 'bot',
        text: response.data.response,
        timestamp: new Date(),
        sources: response.data.sources || [],
        confidence: response.data.confidence,
        source: response.data.source,
        messageId: response.data.message_id,
      };
      setMessages((prevMessages) => [...prevMessages, botMessage]);
      if (mode === "public") {
        setQuotaBlocked(false);
      }
    } catch (err) {
      console.error('Error querying API:', err);
      if (mode === "public" && err?.response?.status === 429 && err?.response?.data?.detail === "tenant_message_quota_exceeded") {
        const limitMessage = err?.response?.headers?.["x-quota-message"] || "Monthly message limit reached. Please try again next month.";
        setQuotaBlocked(true);
        setQuotaMessage(limitMessage);
        setPublicConfigError(limitMessage);
        return;
      }
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
    <WidgetContainer className="mrnwebdesigns-chatbot-widget-container">
      <WidgetHeader className="mrnwebdesigns-chatbot-widget-header">
        <HeaderRow>
          {avatarUrl ? <HeaderAvatar src={avatarUrl} alt="brand avatar" /> : null}
          <WidgetTitle>{headerTitle}</WidgetTitle>
        </HeaderRow>
      </WidgetHeader>
      <PoweredBy>Powered by {brandName || "Nethues"}</PoweredBy>
      
      <MessageContainer className="mrnwebdesigns-chatbot-widget-message-container">
        {messages.map((message, index) => (
          <Message
            key={index}
            type={message.type}
            text={message.text}
            timestamp={message.timestamp}
            sources={message.sources}
            isError={message.isError}
            confidence={message.confidence}
            source={message.source}
            messageId={message.messageId}
            mode={mode}
            apiUrl={apiUrl}
            widgetKey={widgetKey}
          />
        ))}
        {isLoading && (
          <LoadingMessage>
            <LoadingDots>
              <span>.</span>
              <span>.</span>
              <span>.</span>
            </LoadingDots>
          </LoadingMessage>
        )}
        <div ref={messageEndRef} />
      </MessageContainer>

      <InputForm onSubmit={handleSubmit}>
        <Input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type your message..."
          disabled={isLoading || (mode === "public" && (isProfileRequired || quotaBlocked))}
        />
        <SendButton type="submit" disabled={isLoading || !input.trim() || (mode === "public" && (isProfileRequired || quotaBlocked))}>
          <BsSend />
        </SendButton>
      </InputForm>
      {mode === "public" && isProfileRequired && (
        <ProfileCaptureContainer>
          <ProfileTitle>Before we continue, please share your details:</ProfileTitle>
          <Input
            type="text"
            value={visitorName}
            onChange={(e) => setVisitorName(e.target.value)}
            placeholder="Your name"
            disabled={isSavingProfile}
          />
          <Input
            type="email"
            value={visitorEmail}
            onChange={(e) => setVisitorEmail(e.target.value)}
            placeholder="Your email"
            disabled={isSavingProfile}
          />
          <ProfileSaveButton
            type="button"
            disabled={isSavingProfile || !visitorName.trim() || !visitorEmail.trim()}
            onClick={submitVisitorProfile}
          >
            {isSavingProfile ? "Saving..." : "Continue to chat"}
          </ProfileSaveButton>
        </ProfileCaptureContainer>
      )}
      {mode === "public" && showRatingPrompt && !ratingSubmitted && sessionId && (
        <RatingContainer>
          <ProfileTitle>Please rate your overall experience:</ProfileTitle>
          <StarRow>
            {[1, 2, 3, 4, 5].map((star) => (
              <StarButton
                key={star}
                type="button"
                disabled={isSubmittingRating}
                onClick={() => submitSessionRating(star)}
              >
                {star}
              </StarButton>
            ))}
          </StarRow>
        </RatingContainer>
      )}
      {mode === "public" && ratingSubmitted && selectedRating > 0 && (
        <RatingSubmittedText>Thanks for rating: {selectedRating}/5</RatingSubmittedText>
      )}
      {privacyPolicyUrl && (
        <PrivacyPolicyLink href={privacyPolicyUrl} target="_blank" rel="noreferrer">
          Privacy Policy
        </PrivacyPolicyLink>
      )}
      {publicConfigError && <ConfigError>{publicConfigError}</ConfigError>}
    </WidgetContainer>
  );
};

// Styled components
const WidgetContainer = styled.div`
  display: flex;
  flex-direction: column;
  width: 380px;
  height: 600px;
  background: white;
  border-radius: 10px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
  overflow: hidden;
`;

const WidgetHeader = styled.div`
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 15px;
  background: #bf362e;
  color: white;
`;

const WidgetTitle = styled.h2`
  margin: 0;
  font-size: 1.2rem;
`;

const HeaderRow = styled.div`
  display: flex;
  align-items: center;
  gap: 8px;
`;

const HeaderAvatar = styled.img`
  width: 26px;
  height: 26px;
  border-radius: 999px;
  object-fit: cover;
  background: rgba(255, 255, 255, 0.2);
`;

const PoweredBy = styled.div`
  font-size: 0.75rem;
  color: #666;
  padding: 6px 15px 0;
`;

const MessageContainer = styled.div`
  flex: 1;
  overflow-y: auto;
  padding: 15px;
  display: flex;
  flex-direction: column;
  gap: 10px;
`;

const InputForm = styled.form`
  display: flex;
  padding: 15px;
  gap: 10px;
  border-top: 1px solid #eee;
`;

const Input = styled.input`
  flex: 1;
  padding: 10px;
  border: 1px solid #ddd;
  border-radius: 20px;
  outline: none;
  
  &:focus {
    border-color: #bf362e;
  }
`;

const SendButton = styled.button`
  background: #bf362e;
  color: white;
  border: none;
  border-radius: 50%;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  
  &:disabled {
    background: #ccc;
    cursor: not-allowed;
  }
  
  &:hover:not(:disabled) {
    background: #5a8f15;
  }
`;

const LoadingMessage = styled.div`
  display: flex;
  justify-content: center;
  padding: 10px;
  color: #666;
`;

const LoadingDots = styled.div`
  display: flex;
  gap: 2px;
  
  span {
    animation: loading 1.4s infinite;
    &:nth-child(2) { animation-delay: 0.2s; }
    &:nth-child(3) { animation-delay: 0.4s; }
  }
  
  @keyframes loading {
    0%, 80%, 100% { opacity: 0; }
    40% { opacity: 1; }
  }
`;

const ConfigError = styled.div`
  color: #c62828;
  font-size: 0.85rem;
  padding: 8px 12px 12px;
`;

const PrivacyPolicyLink = styled.a`
  color: #555;
  font-size: 0.75rem;
  padding: 0 15px 8px;
  text-decoration: underline;
`;

const ProfileCaptureContainer = styled.div`
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-top: 1px solid #eee;
  padding: 12px 15px;
`;

const ProfileTitle = styled.div`
  font-size: 0.85rem;
  color: #444;
`;

const ProfileSaveButton = styled.button`
  border: none;
  background: #bf362e;
  color: white;
  border-radius: 6px;
  padding: 8px 12px;
  cursor: pointer;

  &:disabled {
    background: #ccc;
    cursor: not-allowed;
  }
`;

const RatingContainer = styled.div`
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-top: 1px solid #eee;
  padding: 12px 15px;
`;

const StarRow = styled.div`
  display: flex;
  gap: 6px;
`;

const StarButton = styled.button`
  border: 1px solid #ddd;
  background: white;
  border-radius: 6px;
  padding: 6px 10px;
  cursor: pointer;
`;

const RatingSubmittedText = styled.div`
  color: #2e7d32;
  font-size: 0.8rem;
  padding: 0 15px 8px;
`;

export default ChatWidget; 