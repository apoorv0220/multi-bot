from fuzzywuzzy import fuzz
from typing import Dict, Optional, Tuple, List

# Expanded hardcoded responses for common queries
PERSONALIZED_RESPONSES = {
    # Greetings
    "hi": "Hi, I'm Allevia. I'm your migraine assistant. How can I assist you today?",
    "hello": "Hello! I'm here to help you with any migraine-related questions.",
    "hey": "Hey there! I'm Allevia. I'm your migraine assistant. What can I help you with?",
    "good morning": "Good morning! I'm here to help with your migraine questions.",
    "good afternoon": "Good afternoon! How can I assist you with migraine-related information?",
    "good evening": "Good evening! I'm here to help with your migraine queries.",
    "how are you": "I'm functioning well and ready to help with your migraine questions!",
    "how are you doing": "I'm doing great and ready to assist with your migraine queries!",
    "what's up": "I'm here to help with migraine-related information. What would you like to know?",
    "how's it going": "I'm doing well and ready to assist with your migraine queries!",
    "how have you been": "I'm functioning well and ready to help with your migraine questions!",
    "what's new": "I'm here to help with migraine-related information. What would you like to know?",
    "how's your day": "I'm having a good day and ready to help with your migraine questions!",
    "how's everything": "Everything is working well! How can I help with your migraine questions?",
    
    # Identity and Capabilities
    "who are you": "I'm a migraine-focused assistant here to support your health journey.",
    "what are you": "I'm an AI assistant specialized in providing migraine-related information and support.",
    "what can you do": "I can help answer questions about migraines using trusted sources, provide information about symptoms, treatments, and lifestyle management.",
    "how can you help": "I can provide information about migraines, their causes, treatments, and management strategies from reliable medical sources.",
    "what is your purpose": "My purpose is to provide accurate, helpful information about migraines and support your health journey.",
    "tell me about yourself": "I'm an AI assistant specialized in migraine information and support. I can help answer your questions about migraines, their causes, treatments, and management strategies.",
    "what do you know": "I'm knowledgeable about migraines, including their causes, symptoms, treatments, and management strategies. What would you like to know?",
    "what are your capabilities": "I can provide information about migraines, answer questions about symptoms and treatments, and help you find relevant resources.",
    
    # Gratitude
    "thank you": "You're welcome! I'm here anytime you need help.",
    "thanks": "Glad I could help. Ask me anything!",
    "appreciate it": "Happy to help! Feel free to ask more questions.",
    "that's helpful": "I'm glad that was helpful! Is there anything else you'd like to know?",
    "thank you so much": "You're very welcome! I'm here to help anytime.",
    "thanks a lot": "My pleasure! Feel free to ask more questions.",
    "i appreciate it": "Happy to help! What else would you like to know?",
    "that's great": "I'm glad I could help! Is there anything else you'd like to know about migraines?",
    
    # Farewell
    "bye": "Take care! Wishing you good health.",
    "goodbye": "Goodbye! Take care of yourself.",
    "see you": "See you later! Take care.",
    "farewell": "Farewell! Wishing you well.",
    "see you later": "See you later! Take care of yourself.",
    "talk to you later": "Looking forward to our next chat! Take care.",
    "have a good day": "Thank you! You have a great day too. Take care!",
    "take care": "You too! Take care of yourself.",
    
    # Common Questions
    "what's happening": "I'm here to help with migraine-related information. What would you like to know?",
    "what's going on": "I'm ready to assist with your migraine queries. What would you like to know?",
    "what's the matter": "I'm here to help with migraine-related information. What would you like to know?",
    "what's wrong": "I'm here to help with migraine-related information. What would you like to know?",
    "what's the problem": "I'm here to help with migraine-related information. What would you like to know?",
    
    # Clarification
    "what do you mean": "I'm here to provide information about migraines. Could you please rephrase your question?",
    "i don't understand": "I apologize for any confusion. Could you please ask your question about migraines in a different way?",
    "can you explain": "I'd be happy to explain. What specific aspect of migraines would you like to know more about?",
    "i'm confused": "Let me help clarify. What specific aspect of migraines would you like to know more about?",
    "i don't get it": "Let me explain differently. What would you like to know about migraines?",
    "can you clarify": "Of course! What specific aspect of migraines would you like me to clarify?",
    
    # Help
    "help": "I'm here to help! What would you like to know about migraines?",
    "i need help": "I'm ready to assist you. What migraine-related information are you looking for?",
    "can you help me": "Of course! I'm here to help with any migraine-related questions you have.",
    "i need assistance": "I'm here to help! What migraine-related information do you need?",
    "can you assist me": "I'd be happy to assist you. What would you like to know about migraines?",
    "i need support": "I'm here to support you. What migraine-related information would be helpful?",
    
    # Confirmation
    "yes": "Great! What would you like to know about migraines?",
    "no": "No problem. Is there something else you'd like to ask about migraines?",
    "maybe": "That's okay. Take your time. I'm here when you have questions about migraines.",
    "sure": "Great! What would you like to know about migraines?",
    "okay": "Perfect! What migraine-related information can I help you with?",
    "alright": "Great! What would you like to know about migraines?",
    
    # Emergency
    "emergency": "If you're experiencing a medical emergency, please call emergency services immediately. For non-emergency migraine information, I'm here to help.",
    "urgent": "For urgent medical concerns, please contact your healthcare provider or emergency services. For general migraine information, I'm here to assist.",
    "help me now": "If this is a medical emergency, please call emergency services immediately. For migraine information, I'm here to help.",
    "it's urgent": "For urgent medical concerns, please contact your healthcare provider or emergency services. For general migraine information, I'm here to assist.",
    
    # Technical
    "error": "I'm sorry you're experiencing an issue. Could you please rephrase your question about migraines?",
    "not working": "I'm here to help. Could you please rephrase your question about migraines?",
    "broken": "I'm functioning properly. How can I help you with migraine-related information?",
    "something's wrong": "I'm here to help. Could you please rephrase your question about migraines?",
    "it's not working": "I'm functioning properly. How can I help you with migraine-related information?",
    
    # Small Talk
    "nice to meet you": "Nice to meet you too! I'm here to help with your migraine questions.",
    "pleasure to meet you": "The pleasure is mine! How can I help with your migraine queries?",
    "how's your day going": "I'm having a good day and ready to help with your migraine questions!",
    "what's the weather like": "I'm focused on helping with migraine-related information. What would you like to know?",
    "how's your weekend": "I'm here to help with migraine-related information. What would you like to know?",
    
    # Politeness
    "please": "I'm here to help! What would you like to know about migraines?",
    "excuse me": "Yes, how can I help you with migraine-related information?",
    "pardon me": "No problem! How can I assist you with migraine-related questions?",
    "sorry": "No need to apologize! How can I help with your migraine questions?",
    "i apologize": "No need to apologize! What would you like to know about migraines?",
}

class FuzzyMatcher:
    def __init__(self, threshold: int = 80):
        """
        Initialize the fuzzy matcher with a similarity threshold.
        
        Args:
            threshold (int): Minimum similarity score (0-100) to consider a match
        """
        self.threshold = threshold
        # Combine all response dictionaries
        self.responses = {
            **GREETING_RESPONSES,
            **IDENTITY_RESPONSES,
            **POSITIVE_RESPONSES,
            **RANDOM_RESPONSES,
            **CLARIFICATION_RESPONSES,
            **HELP_RESPONSES,
            **SIMPLE_RESPONSES,
            **EMERGENCY_RESPONSES
        }
        self.greeting_patterns = [
            "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
            "how are you", "how are you doing", "what's up", "how's it going"
        ]

    def _get_word_combinations(self, words: List[str], max_length: int = 3) -> List[str]:
        """
        Generate combinations of consecutive words from the input.
        
        Args:
            words (List[str]): List of words to combine
            max_length (int): Maximum number of words to combine
            
        Returns:
            List[str]: List of word combinations
        """
        combinations = []
        for i in range(len(words)):
            for j in range(i + 1, min(i + max_length + 1, len(words) + 1)):
                combinations.append(" ".join(words[i:j]))
        return combinations

    def _contains_greeting(self, query: str) -> bool:
        """
        Check if the query contains any greeting patterns.
        
        Args:
            query (str): The user's query
            
        Returns:
            bool: True if query contains a greeting pattern
        """
        words = query.lower().split()
        combinations = self._get_word_combinations(words)
        
        for pattern in self.greeting_patterns:
            for combo in combinations:
                if fuzz.ratio(combo, pattern) >= self.threshold:
                    return True
        return False

    def find_best_match(self, query: str) -> Tuple[Optional[str], float]:
        """
        Find the best matching response for a given query.
        
        Args:
            query (str): The user's query
            
        Returns:
            Tuple[Optional[str], float]: (matched response, similarity score)
        """
        best_score = 0
        best_response = None
        
        # Clean and normalize the query
        query = query.lower().strip()
        words = query.split()
        
        # First, check for greeting patterns in combinations
        if self._contains_greeting(query):
            # If it contains a greeting, prioritize greeting responses
            for pattern in self.greeting_patterns:
                score = fuzz.ratio(query, pattern)
                if score > best_score:
                    best_score = score
                    best_response = self.responses.get(pattern)
        
        # If no greeting match found or score is low, check all patterns
        if best_score < self.threshold:
            for pattern, response in self.responses.items():
                # Calculate similarity score
                score = fuzz.ratio(query, pattern)
                
                # Update best match if score is higher
                if score > best_score:
                    best_score = score
                    best_response = response
        
        # Return response only if score meets threshold
        if best_score >= self.threshold:
            return best_response, best_score
        return None, best_score

    def get_response(self, query: str) -> Optional[str]:
        """
        Get a response for the query if a good match is found.
        
        Args:
            query (str): The user's query
            
        Returns:
            Optional[str]: The matched response or None if no good match
        """
        response, score = self.find_best_match(query)
        return response 