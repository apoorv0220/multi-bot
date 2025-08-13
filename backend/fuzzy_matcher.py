from fuzzywuzzy import fuzz
from typing import Dict, Optional, Tuple, List

# Expanded hardcoded responses for common queries
GREETING_RESPONSES = {
    "hi": "Hello! I'm your MRN Web Designs Assistant. How can I help you today with website design, development, SEO, or digital marketing?",
    "hello": "Hello! I'm your MRN Web Designs Assistant. How can I help you today with website design, development, SEO, or digital marketing?",
    "hey": "Hey there! I'm your MRN Web Designs Assistant. How can I help you today with website design, development, SEO, or digital marketing?",
    "good morning": "Good morning! How can MRN Web Designs help you with your digital presence today?",
    "good afternoon": "Good afternoon! What web design or digital marketing questions can I help you with?",
    "good evening": "Good evening! How can I assist you with your website or marketing needs tonight?",
    "how are you": "I'm functioning well and ready to help with your web design and digital marketing questions!",
    "hello how are you": "I'm functioning well and ready to help with your web design and digital marketing questions!",
    "how are you doing": "I'm doing great and ready to assist with your website and digital marketing queries!",
    "what's up": "I'm here to help with website design, development, SEO, and digital marketing information. What would you like to know?",
    "how's it going": "I'm doing well and ready to assist with your web design and digital marketing queries!",
    "how have you been": "I'm functioning well and ready to help with your website and marketing questions!",
    "what's new": "I'm here to help with website design, development, SEO, and digital marketing information. What would you like to know?",
    "how's your day": "I'm having a good day and ready to help with your web design and digital marketing questions!",
    "how's everything": "Everything is working well! How can I help with your website or marketing questions?",
}

IDENTITY_RESPONSES = {
    "who are you": "I'm a MRN Web Designs assistant here to help with your website design, development, and digital marketing needs.",
    "what are you": "I'm an AI assistant for MRN Web Designs, designed to help answer your questions about web design, development, SEO, and digital marketing.",
    "what can you do": "I can help answer questions about website design, development, maintenance, SEO, paid search, and social media marketing using our extensive expertise and custom solutions.",
    "how can you help": "I can provide information about our web design and digital marketing services, design advice, development guidance, and help you make the best choices for your business's digital presence.",
    "what is your purpose": "My purpose is to provide accurate, helpful information about website design, development, and digital marketing to support your business growth.",
    "tell me about yourself": "I'm an AI assistant specialized in web design and digital marketing. I can help answer your questions about our services, design options, and development guidance.",
    "what do you know": "I'm knowledgeable about website design, development, maintenance, SEO, paid search, social media marketing, and our extensive service range. What would you like to know?",
    "what are your capabilities": "I can provide information about web design and digital marketing, answer questions about development and SEO, and help you find the perfect digital solutions for your business.",
}

POSITIVE_RESPONSES = {
    "thank you": "You're welcome! Is there anything else you'd like to know about our web design or digital marketing services?",
    "thanks": "My pleasure! Let me know if you have any other questions about website development or marketing.",
    "thank you so much": "You're very welcome! Feel free to ask about any other web design or digital marketing needs.",
    "thanks a lot": "You're welcome! Is there anything else I can help you with regarding your website project?",
    "appreciate it": "I'm glad I could help! Any other questions about web design or digital marketing?",
    "that's helpful": "Great! Is there anything else you'd like to know about our services?",
    "perfect": "Wonderful! Let me know if you need any other information about web design or digital marketing.",
    "excellent": "I'm pleased to help! Any other questions about your website or marketing project?",
    "great": "Excellent! Is there anything else you'd like to know about our web design or digital marketing services?",
    "awesome": "I'm glad that was helpful! Any other questions about website development?",
    "that's great": "I'm glad I could help! Is there anything else you'd like to know about web design or digital marketing?",
}

RANDOM_RESPONSES = {
    "test": "I'm working perfectly! How can I help you with web design, development, SEO, or digital marketing?",
    "testing": "Test successful! What would you like to know about our services?",
    "check": "Everything looks good! How can I assist with your website or marketing needs?",
    "ok": "How can I help you with web design or digital marketing today?",
    "okay": "What web design or digital marketing questions can I answer for you?",
    "yes": "Great! What would you like to know about our web design and digital marketing services?",
    "no": "No problem! Is there something else about web design or digital marketing I can help with?",
    "sure": "Perfect! What web design or digital marketing information are you looking for?",
    "cool": "Awesome! How can I help with your website or marketing project?",
    "nice": "Thank you! What web design or digital marketing questions do you have?",
}

CLARIFICATION_RESPONSES = {
    "what": "Could you please be more specific about what aspect of web design or digital marketing you'd like to know about?",
    "how": "I'd be happy to help! Could you clarify what specific process or service you're asking about?",
    "when": "Could you provide more details about what timeline or scheduling information you need?",
    "where": "Are you asking about our service areas, office location, or something else? Please clarify.",
    "why": "I'd like to help explain! Could you be more specific about what you'd like to understand?",
    "which": "Could you provide more context about what options or services you're comparing?",
    "can you": "Absolutely! What specifically would you like me to help you with regarding web design or digital marketing?",
    "do you": "I'd be happy to answer! Could you be more specific about what you'd like to know?",
    "will you": "Of course! What would you like me to help you with regarding your website or marketing needs?",
    "should i": "I'd be glad to provide guidance! Could you give me more details about your specific situation?",
}

HELP_RESPONSES = {
    "help": "I'm here to help! I can answer questions about website design, development, maintenance, SEO, paid search, and social media marketing. What would you like to know?",
    "help me": "I'd be happy to help! What specific web design or digital marketing topic would you like assistance with?",
    "i need help": "I'm here to assist! What web design or digital marketing challenge can I help you with?",
    "can you help": "Absolutely! I can provide information about our website design, development, SEO, and digital marketing services. What do you need help with?",
    "i'm confused": "No worries! Web design and digital marketing can be complex. What specific aspect would you like me to clarify?",
    "i don't understand": "That's okay! I'm here to explain. What part of web design or digital marketing would you like me to break down for you?",
    "what should i do": "I'd be happy to provide guidance! Could you tell me more about your website or marketing goals?",
    "i'm lost": "Let me help guide you! What are you trying to accomplish with your website or digital marketing?",
    "i need advice": "I'm here to provide expert advice! What aspect of your web design or digital marketing strategy would you like guidance on?",
    "guide me": "I'd be happy to guide you! What's your main goal - a new website, improving SEO, or enhancing your digital marketing?",
}

SIMPLE_RESPONSES = {
    "price": "Our pricing varies based on your specific needs and project scope. Each website and marketing strategy is custom-designed. Would you like to discuss your project requirements?",
    "cost": "Costs depend on the complexity and scope of your project. We provide custom solutions rather than one-size-fits-all pricing. What type of project are you considering?",
    "expensive": "We focus on providing value through custom solutions that deliver results. Our pricing reflects the quality and effectiveness of our work. What's your project budget range?",
    "cheap": "We believe in providing excellent value. While we don't compete on price alone, we ensure every dollar spent delivers measurable results for your business.",
    "free": "We offer free consultations to discuss your web design and digital marketing needs. Would you like to schedule one?",
    "quote": "I'd be happy to help you get a custom quote! Could you tell me more about your project requirements and goals?",
    "estimate": "For an accurate estimate, we'd need to understand your specific needs. What type of website or marketing services are you looking for?",
    "contact": "You can contact MRN Web Designs through our website contact form, by phone, or email. How would you prefer to get in touch?",
    "location": "MRN Web Designs serves clients nationwide. Where is your business located?",
    "hours": "Our team is available during standard business hours, but we're flexible for client needs. When would be the best time to discuss your project?",
}

EMERGENCY_RESPONSES = {
    "urgent": "I understand this is urgent! For immediate assistance with your website or digital marketing emergency, please contact our support team directly.",
    "emergency": "For website emergencies or urgent digital marketing needs, our team is ready to help. What's the nature of your emergency?",
    "asap": "I see you need quick assistance! What urgent web design or digital marketing issue can we help resolve?",
    "immediately": "For immediate support with your website or marketing needs, let me connect you with our rapid response team.",
    "right now": "I understand you need immediate help! What urgent web design or digital marketing issue are you facing?",
    "crisis": "We're here to help during digital crises! What website or marketing emergency can we assist with?",
    "broken": "A broken website can be critical for business! Our emergency response team can help. What specific issue are you experiencing?",
    "down": "Website downtime is serious! Our technical team can help immediately. Can you describe what's happening with your site?",
    "hacked": "Website security breaches require immediate action! Please contact our security team right away for emergency assistance.",
    "crashed": "Website crashes need immediate attention! Our emergency response team is ready to help restore your site quickly.",
}

class FuzzyMatcher:
    def __init__(self, similarity_threshold: int = 85):
        self.similarity_threshold = similarity_threshold
        
        # Combine all response dictionaries
        self.response_db = {
            **GREETING_RESPONSES,
            **IDENTITY_RESPONSES,
            **POSITIVE_RESPONSES,
            **RANDOM_RESPONSES,
            **CLARIFICATION_RESPONSES,
            **HELP_RESPONSES,
            **SIMPLE_RESPONSES,
            **EMERGENCY_RESPONSES
        }
    
    def clean_query(self, query: str) -> str:
        """Clean and normalize the query string."""
        return query.lower().strip()
    
    def find_best_match(self, query: str) -> Optional[Tuple[str, int]]:
        """Find the best matching response for a query."""
        clean_query = self.clean_query(query)
        
        best_match = None
        best_score = 0
        
        for key, response in self.response_db.items():
            # Try exact match first
            if clean_query == key.lower():
                return response, 100
            
            # Try fuzzy matching
            score = fuzz.ratio(clean_query, key.lower())
            if score > best_score and score >= self.similarity_threshold:
                best_score = score
                best_match = response
        
        return (best_match, best_score) if best_match else None
    
    def get_response(self, query: str) -> Optional[Dict[str, any]]:
        """Get a response for the query if it matches any hardcoded responses."""
        match_result = self.find_best_match(query)
        
        if match_result:
            response, confidence = match_result
            return {
                "response": response,
                "confidence": confidence / 100.0,  # Convert to 0-1 scale
                "source": "fuzzy_match",
                "sources": []
            }
        
        return None
    
    def get_suggestions(self, query: str, limit: int = 5) -> List[str]:
        """Get suggested queries based on partial match."""
        clean_query = self.clean_query(query)
        suggestions = []
        
        for key in self.response_db.keys():
            if clean_query in key.lower() or key.lower() in clean_query:
                suggestions.append(key)
                if len(suggestions) >= limit:
                    break
        
        return suggestions

# For backward compatibility
def get_fuzzy_response(query: str) -> Optional[str]:
    """Get a fuzzy response for the query (backward compatibility)."""
    matcher = FuzzyMatcher()
    result = matcher.get_response(query)
    return result["response"] if result else None