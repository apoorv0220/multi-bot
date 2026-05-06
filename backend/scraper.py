import requests
import asyncio
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import time
from playwright.async_api import async_playwright
import os
import re

class WebScraper:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.google.com/",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        self.timeout = 15  # seconds
        
    async def scrape_url(self, url, title="", description=""):
        """Scrape content from a URL, trying multiple methods if needed"""
        print(f"Scraping URL: {url}")
        
        # Try simple requests first (faster)
        try:
            content = self._scrape_with_requests(url)
            if content and len(content) > 300:  # Ensure we got meaningful content
                return self._process_content(content, url, title, description)
        except Exception as e:
            print(f"Simple request scraping failed for {url}: {e}")
        
        # If requests fails or returns too little content, try with Playwright
        try:
            content = await self._scrape_with_playwright(url)
            if content:
                return self._process_content(content, url, title, description)
        except Exception as e:
            print(f"Playwright scraping failed for {url}: {e}")
        
        # If all scraping methods fail, return minimal info
        return {
            "url": url,
            "title": title or urlparse(url).netloc,
            "content": description or "Content unavailable",
            "source": urlparse(url).netloc,
            "source_type": "external"
        }
    
    def _scrape_with_requests(self, url):
        """Scrape URL using simple requests"""
        response = requests.get(url, headers=self.headers, timeout=self.timeout)
        response.raise_for_status()
        
        # Get main content
        soup = BeautifulSoup(response.text, 'html.parser')
        return soup.get_text()
    
    async def _scrape_with_playwright(self, url):
        """Scrape URL using Playwright (handles JavaScript rendering)"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=self.headers["User-Agent"]
            )
            
            page = await context.new_page()
            
            try:
                # Navigate to page with timeout
                await page.goto(url, timeout=self.timeout * 1000, wait_until="networkidle")
                
                # Wait for content to load
                await page.wait_for_load_state("domcontentloaded")
                
                # Wait a bit for any remaining JavaScript to execute
                await asyncio.sleep(2)
                
                # Get page content
                content = await page.content()
                
                # Parse with BeautifulSoup
                soup = BeautifulSoup(content, 'html.parser')
                
                # Try to get main content (different strategies)
                # 1. Look for article tags
                article = soup.find('article')
                if article:
                    return article.get_text()
                
                # 2. Look for main content div
                main = soup.find('main')
                if main:
                    return main.get_text()
                
                # 3. Fall back to body content
                body = soup.find('body')
                if body:
                    # Remove common elements that don't contain main content
                    for elem in body.select('nav, header, footer, aside, script, style'):
                        elem.extract()
                    return body.get_text()
                
                # 4. If all else fails, just get all text
                return soup.get_text()
            
            finally:
                await browser.close()
    
    def _process_content(self, content, url, title="", description=""):
        """Process and clean scraped content"""
        # Clean up whitespace
        content = re.sub(r'\s+', ' ', content).strip()
        
        # Extract a title if none provided
        if not title:
            # Try to extract from the URL
            parsed_url = urlparse(url)
            netloc = parsed_url.netloc
            path = parsed_url.path
            
            if path and path != '/':
                # Use the last part of the path as a title
                path_parts = path.rstrip('/').split('/')
                title = path_parts[-1].replace('-', ' ').replace('_', ' ').title()
            else:
                title = netloc
        
        # Get domain as source
        source = urlparse(url).netloc
        
        # Prepare result
        result = {
            "url": url,
            "title": title,
            "content": content,
            "source": source,
            "source_type": "external"
        }
        
        # Add description if provided
        if description:
            result["description"] = description
            
        return result

# Function to scrape multiple URLs concurrently
async def scrape_urls(urls):
    """Scrape multiple URLs concurrently"""
    scraper = WebScraper()
    tasks = []
    
    for url_data in urls:
        url = url_data.get('url')
        title = url_data.get('title', '')
        description = url_data.get('description', '')
        
        if url:
            tasks.append(scraper.scrape_url(url, title, description))
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Filter out any exceptions
    valid_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            print(f"Error scraping {urls[i].get('url')}: {result}")
        else:
            valid_results.append(result)
    
    return valid_results

# For testing
if __name__ == "__main__":
    async def test_scraper():
        scraper = WebScraper()
        url = "https://www.mrnwebdesigns.com"
        result = await scraper.scrape_url(url)
        print(f"Title: {result['title']}")
        print(f"Content length: {len(result['content'])} characters")
        print(f"Sample content: {result['content'][:200]}...")
        
    asyncio.run(test_scraper()) 