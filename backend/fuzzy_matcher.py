from fuzzywuzzy import fuzz
from typing import Dict, Optional, Tuple

# Expanded hardcoded responses for common queries
PERSONALIZED_RESPONSES = {
    # Greetings
    "hi": "Hi, I'm your Migraine Assistant. How can I assist you today?",
    "hello": "Hello! I'm here to help you with any migraine-related questions.",
    "hey": "Hey there! I'm your migraine assistant. What can I help you with?",
    "good morning": "Good morning! I'm here to help with your migraine questions.",
    "good afternoon": "Good afternoon! How can I assist you with migraine-related information?",
    "good evening": "Good evening! I'm here to help with your migraine queries.",
    
    # Identity and Capabilities
    "who are you": "I'm a migraine-focused assistant here to support your health journey.",
    "what are you": "I'm an AI assistant specialized in providing migraine-related information and support.",
    "what can you do": "I can help answer questions about migraines using trusted sources, provide information about symptoms, treatments, and lifestyle management.",
    "how can you help": "I can provide information about migraines, their causes, treatments, and management strategies from reliable medical sources.",
    "what is your purpose": "My purpose is to provide accurate, helpful information about migraines and support your health journey.",
    
    # Gratitude
    "thank you": "You're welcome! I'm here anytime you need help.",
    "thanks": "Glad I could help. Ask me anything!",
    "appreciate it": "Happy to help! Feel free to ask more questions.",
    "that's helpful": "I'm glad that was helpful! Is there anything else you'd like to know?",
    
    # Farewell
    "bye": "Take care! Wishing you good health.",
    "goodbye": "Goodbye! Take care of yourself.",
    "see you": "See you later! Take care.",
    "farewell": "Farewell! Wishing you well.",
    
    # Common Questions
    "how are you": "I'm functioning well and ready to help with your migraine questions!",
    "what's up": "I'm here to help with migraine-related information. What would you like to know?",
    "how's it going": "I'm doing well and ready to assist with your migraine queries!",
    
    # Clarification
    "what do you mean": "I'm here to provide information about migraines. Could you please rephrase your question?",
    "i don't understand": "I apologize for any confusion. Could you please ask your question about migraines in a different way?",
    "can you explain": "I'd be happy to explain. What specific aspect of migraines would you like to know more about?",
    
    # Help
    "help": "I'm here to help! What would you like to know about migraines?",
    "i need help": "I'm ready to assist you. What migraine-related information are you looking for?",
    "can you help me": "Of course! I'm here to help with any migraine-related questions you have.",
    
    # Confirmation
    "yes": "Great! What would you like to know about migraines?",
    "no": "No problem. Is there something else you'd like to ask about migraines?",
    "maybe": "That's okay. Take your time. I'm here when you have questions about migraines.",
    
    # Emergency
    "emergency": "If you're experiencing a medical emergency, please call emergency services immediately. For non-emergency migraine information, I'm here to help.",
    "urgent": "For urgent medical concerns, please contact your healthcare provider or emergency services. For general migraine information, I'm here to assist.",
    
    # Technical
    "error": "I'm sorry you're experiencing an issue. Could you please rephrase your question about migraines?",
    "not working": "I'm here to help. Could you please rephrase your question about migraines?",
    "broken": "I'm functioning properly. How can I help you with migraine-related information?",
}

class FuzzyMatcher:
    def __init__(self, threshold: int = 80):
        """
        Initialize the fuzzy matcher with a similarity threshold.
        
        Args:
            threshold (int): Minimum similarity score (0-100) to consider a match
        """
        self.threshold = threshold
        self.responses = PERSONALIZED_RESPONSES

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