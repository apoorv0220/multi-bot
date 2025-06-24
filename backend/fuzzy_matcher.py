from fuzzywuzzy import fuzz
from typing import Dict, Optional, Tuple, List

# Expanded hardcoded responses for common queries
GREETING_RESPONSES = {
    "hi": "Hi, I'm your Medical Optics Assistant. How can I help you with eye care, vision health, or optical services today?",
    "hello": "Hello! Welcome to Medical Optics. How can I assist you with your vision needs today?",
    "hey": "Hey there! I'm your Medical Optics assistant. What can I help you with?",
    "good morning": "Good morning! How can Medical Optics assist you with your vision health today?",
    "good afternoon": "Good afternoon! What eye care questions can I help you with?",
    "good evening": "Good evening! How can I assist you with your vision needs tonight?",
    "how are you": "I'm functioning well and ready to help with your eye care and vision health questions!",
    "how are you doing": "I'm doing great and ready to assist with your optical service queries!",
    "what's up": "I'm here to help with eye care, vision health, and optical service information. What would you like to know?",
    "how's it going": "I'm doing well and ready to assist with your eye care and vision health queries!",
    "how have you been": "I'm functioning well and ready to help with your optical service questions!",
    "what's new": "I'm here to help with eye care, vision health, and optical service information. What would you like to know?",
    "how's your day": "I'm having a good day and ready to help with your eye care and vision health questions!",
    "how's everything": "Everything is working well! How can I help with your optical service questions?",
}

IDENTITY_RESPONSES = {
    "who are you": "I'm a Medical Optics assistant here to help with your eye care, vision health, and optical service needs.",
    "what are you": "I'm an AI assistant for Medical Optics, designed to help answer your questions about eye care and vision health.",
    "what can you do": "I can help answer questions about eye care, vision health, treatments, and our optical services using our extensive product knowledge and design expertise.",
    "how can you help": "I can provide information about our eye care and vision health products, design advice, installation guidance, and help you make the best choices for your home or commercial project.",
    "what is your purpose": "My purpose is to provide accurate, helpful information about eye care, vision health, and optical services to support your design journey.",
    "tell me about yourself": "I'm an AI assistant specialized in eye care and vision health. I can help answer your questions about our products, design options, and installation guidance.",
    "what do you know": "I'm knowledgeable about eye care, vision health, treatments, and our extensive product range. What would you like to know?",
    "what are your capabilities": "I can provide information about eye care and vision health, answer questions about design and installation, and help you find the perfect solutions for your project.",
}

POSITIVE_RESPONSES = {
    "thank you": "You're welcome! Is there anything else you'd like to know about our eye care or vision health products?",
    "thanks": "My pleasure! Let me know if you have any other questions about optical services.",
    "thank you so much": "You're very welcome! Feel free to ask about any other eye care or vision health needs.",
    "thanks a lot": "You're welcome! Is there anything else I can help you with regarding your project?",
    "appreciate it": "I'm glad I could help! Any other questions about eye care or vision health?",
    "that's helpful": "Great! Is there anything else you'd like to know about our products?",
    "perfect": "Wonderful! Let me know if you need any other information about eye care or vision health.",
    "excellent": "I'm pleased to help! Any other questions about your optical service project?",
    "great": "Excellent! Is there anything else you'd like to know about our eye care or vision health products?",
    "awesome": "I'm glad that was helpful! Any other questions about home design?",
    "that's great": "I'm glad I could help! Is there anything else you'd like to know about eye care or vision health?",
}

RANDOM_RESPONSES = {
    "test": "I'm working perfectly! How can I help you with eye care, vision health, or optical services?",
    "testing": "Test successful! What would you like to know about our products?",
    "are you there": "Yes, I'm here! How can I assist with your eye care and vision health needs?",
    "are you working": "Yes, I'm working perfectly! What can I help you with today?",
    "can you hear me": "Yes, I can understand you! How can I help with your optical service project?",
    "hello world": "Hello! Welcome to Medical Optics. How can I assist you today?",
    "ping": "Pong! I'm here to help with your eye care and vision health questions.",
    "echo": "Echo received! How can I help with your optical service needs?",
    "what's happening": "I'm here to help with eye care, vision health, and optical service information. What would you like to know?",
    "what's going on": "I'm ready to assist with your eye care and vision health queries. What would you like to know?",
    "what's the matter": "I'm here to help with eye care, vision health, and optical service information. What would you like to know?",
    "what's wrong": "I'm here to help with eye care, vision health, and optical service information. What would you like to know?",
    "what's the problem": "I'm here to help with eye care, vision health, and optical service information. What would you like to know?",
}

CLARIFICATION_RESPONSES = {
    "what do you mean": "I'm here to provide information about eye care, vision health, and optical service. Could you please rephrase your question?",
    "i don't understand": "I apologize for any confusion. Could you please ask your question about eye care or vision health in a different way?",
    "can you explain": "I'd be happy to explain. What specific aspect of eye care, vision health, or optical service would you like to know more about?",
    "i'm confused": "Let me help clarify. What specific aspect of eye care, vision health, or optical service would you like to know more about?",
    "i don't get it": "Let me explain differently. What would you like to know about our eye care, vision health, or optical service services?",
    "can you clarify": "Of course! What specific aspect of eye care, vision health, or optical service would you like me to clarify?",
}

HELP_RESPONSES = {
    "help": "I'm here to help! I can answer questions about eye care, vision health, treatments, and our optical services. What would you like to know?",
    "i need help": "I'm here to help! Whether you have questions about eye exams, treatments, or our services, just ask!",
    "can you help me": "Of course! I'm here to help with all your eye care and vision health questions. What can I assist you with?",
    "i need assistance": "I'm here to help! What eye care or vision health information do you need?",
    "can you assist me": "I'd be happy to assist you. What would you like to know about our products or services?",
    "i need support": "I'm here to support you. What eye care or vision health information would be helpful?",
}

SIMPLE_RESPONSES = {
    "yes": "Great! What would you like to know about eye care, vision health, or optical services?",
    "no": "No problem. Is there something else you'd like to ask about our products or services?",
    "maybe": "That's okay. Take your time. I'm here when you have questions about eye care or vision health.",
    "sure": "Great! What would you like to know about our eye care, vision health, or optical services?",
    "okay": "Perfect! What eye care or vision health information can I help you with?",
    "alright": "Great! What would you like to know about our products?",
}

EMERGENCY_RESPONSES = {
    "emergency": "For urgent property issues, please contact appropriate emergency services. For eye care and vision health information, I'm here to help.",
    "urgent": "For urgent matters, please contact the appropriate services. For general eye care and vision health information, I'm here to assist.",
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