"""
URL validation and fallbacks for chatbot content and citations.
Prefers tenant `widget_website_url` when passed as `fallback_base`; avoids hardcoded third-party sites.
"""

import re
import requests
from urllib.parse import urlparse, urljoin
from typing import Optional
import logging

logger = logging.getLogger("url_utils")

def is_valid_url(url: str) -> bool:
    """
    Check if a URL is valid and properly formatted.
    
    Args:
        url (str): URL to validate
        
    Returns:
        bool: True if URL is valid, False otherwise
    """
    if not url or not isinstance(url, str):
        return False
    
    # Remove @ prefix if present
    clean_url = url.lstrip('@')
    
    try:
        parsed = urlparse(clean_url)
        
        # Must have scheme and netloc
        if not parsed.scheme or not parsed.netloc:
            return False
            
        # Check for field IDs or other invalid patterns in path
        invalid_patterns = [
            r'field_[a-f0-9]+',  # Field IDs like field_6846a4e998b80
            r'[a-f0-9]{13,}',    # Long hex strings
            r'_[0-9a-f]{8,}',    # Underscore followed by long hex
        ]
        
        for pattern in invalid_patterns:
            if re.search(pattern, parsed.path):
                return False
        
        # Check for invalid query parameters
        if parsed.query:
            # URLs with ?p= parameters are considered invalid (WordPress permalink issues)
            if re.search(r'\bp=\d+', parsed.query):
                return False
                
        return True
        
    except Exception as e:
        logger.warning(f"Error parsing URL {url}: {e}")
        return False

def get_base_url(url: str) -> str:
    """
    Extract the base URL from a given URL.
    
    Args:
        url (str): Full URL
        
    Returns:
        str: Base URL (protocol + domain)
    """
    if not url:
        return ""
    
    # Remove @ prefix if present
    clean_url = url.lstrip('@')
    
    try:
        parsed = urlparse(clean_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}/"
        return base_url
    except Exception as e:
        logger.warning(f"Error extracting base URL from {url}: {e}")
        return ""

def get_contact_url(url: str) -> str:
    """
    Extract the contact-us page URL from a given URL.
    
    Args:
        url (str): Full URL
        
    Returns:
        str: Contact-us page URL (protocol + domain + /contact-us/)
    """
    if not url:
        return ""
    
    # Remove @ prefix if present
    clean_url = url.lstrip('@')
    
    try:
        parsed = urlparse(clean_url)
        contact_url = f"{parsed.scheme}://{parsed.netloc}/contact-us/"
        return contact_url
    except Exception as e:
        logger.warning(f"Error extracting contact URL from {url}: {e}")
        return ""

async def check_url_accessibility(url: str, timeout: int = 5) -> bool:
    """
    Check if a URL is accessible (returns 200 status).
    
    Args:
        url (str): URL to check
        timeout (int): Request timeout in seconds
        
    Returns:
        bool: True if URL is accessible, False otherwise
    """
    if not is_valid_url(url):
        return False
    
    # Remove @ prefix if present
    clean_url = url.lstrip('@')
    
    try:
        response = requests.head(clean_url, timeout=timeout, allow_redirects=True)
        return response.status_code == 200
    except Exception as e:
        logger.debug(f"URL {clean_url} is not accessible: {e}")
        return False

def validate_and_fix_url(url: str, fallback_base: Optional[str] = None) -> str:
    """
    Validate a URL and return a fixed version or fallback.
    
    Args:
        url (str): Original URL to validate
        fallback_base (str, optional): Base URL to fall back to
        
    Returns:
        str: Valid URL or fallback contact-us page URL
    """
    if not url:
        return fallback_base or ""
    
    # Remove @ prefix if present
    clean_url = url.lstrip('@')
    
    # If URL is valid, return it
    if is_valid_url(clean_url):
        return clean_url
    
    logger.warning(f"Invalid URL detected: {url}")
    
    # Use contact-us page as primary fallback
    contact_url = get_contact_url(clean_url)
    if contact_url and is_valid_url(contact_url):
        logger.info(f"Using contact-us page fallback: {contact_url}")
        return contact_url
    
    # Try to extract base URL as secondary fallback
    base_url = get_base_url(clean_url)
    if base_url and is_valid_url(base_url):
        logger.info(f"Using base URL fallback: {base_url}")
        return base_url
    
    # Use provided fallback base (e.g. tenant widget_website_url)
    if fallback_base and is_valid_url(fallback_base):
        logger.info(f"Using provided fallback: {fallback_base}")
        return fallback_base

    logger.info("No valid URL or fallback_base; returning empty string")
    return ""

def clean_wordpress_url(site_url: str, post_name: str, post_id: int = None) -> str:
    """
    Create a clean WordPress URL from site URL and post name.
    Handles corrupted post names with field IDs and invalid permalinks.
    
    Args:
        site_url (str): WordPress site base URL
        post_name (str): WordPress post name/slug
        post_id (int, optional): Post ID for fallback
        
    Returns:
        str: Clean URL or contact-us page fallback
    """
    if not site_url or not post_name:
        return get_contact_url(site_url) if site_url else ""
    
    # Ensure site_url has trailing slash
    if not site_url.endswith('/'):
        site_url += '/'
    
    # Check if post_name contains field IDs or other invalid patterns
    invalid_patterns = [
        r'field_[a-f0-9]+',
        r'[a-f0-9]{13,}',
        r'_[0-9a-f]{8,}',
    ]
    
    for pattern in invalid_patterns:
        if re.search(pattern, post_name):
            logger.warning(f"Corrupted post_name detected: {post_name}")
            # Fall back to contact-us page instead of ?p= URLs
            return get_contact_url(site_url)
    
    # Construct normal URL
    try:
        # Clean the post name
        clean_name = post_name.strip('/')
        full_url = urljoin(site_url, clean_name)
        
        # Validate the constructed URL
        if is_valid_url(full_url):
            return full_url
        else:
            logger.warning(f"Constructed invalid URL: {full_url}")
            return get_contact_url(site_url)
            
    except Exception as e:
        logger.error(f"Error constructing URL for {post_name}: {e}")
        return get_contact_url(site_url)

def batch_validate_urls(urls: list, fallback_base: Optional[str] = None) -> list:
    """
    Validate a batch of URLs and fix invalid ones.
    
    Args:
        urls (list): List of URLs to validate
        fallback_base (str, optional): Base URL for fallbacks
        
    Returns:
        list: List of validated/fixed URLs
    """
    validated_urls = []
    
    for url in urls:
        if isinstance(url, dict) and 'url' in url:
            # Handle URL objects
            original_url = url['url']
            fixed_url = validate_and_fix_url(original_url, fallback_base)
            url['url'] = fixed_url
            validated_urls.append(url)
        elif isinstance(url, str):
            # Handle string URLs
            fixed_url = validate_and_fix_url(url, fallback_base)
            validated_urls.append(fixed_url)
        else:
            validated_urls.append(url)
    
    return validated_urls 