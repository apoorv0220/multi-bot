import os
import logging
import pymysql
from dotenv import load_dotenv
from url_utils import clean_wordpress_url, validate_and_fix_url

# Configure proper logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("wordpress_fetcher")

# Load environment variables
load_dotenv()

class WordPressFetcher:
    def __init__(self, source_config=None, fallback_site_url: str | None = None):
        source_config = source_config or {}
        self.fallback_site_url = (fallback_site_url or "").strip() or None
        self.host = source_config.get("host") or os.getenv("WORDPRESS_DB_HOST")
        self.port = int(source_config.get("port") or os.getenv("WORDPRESS_DB_PORT", 3306))
        self.user = source_config.get("user") or os.getenv("WORDPRESS_DB_USER")
        self.password = source_config.get("password") or os.getenv("WORDPRESS_DB_PASSWORD")
        self.database = source_config.get("database") or os.getenv("WORDPRESS_DB_NAME")
        self.url_table = source_config.get("url_table") or os.getenv("WORDPRESS_URL_TABLE")
        self.table_prefix = source_config.get("table_prefix") or os.getenv("WORDPRESS_TABLE_PREFIX", "afn_")
        self.last_connection_error = None

    def get_connection(self):
        """Establish a connection to the WordPress database"""
        try:
            self.last_connection_error = None
            connection = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor
            )
            return connection
        except Exception as e:
            self.last_connection_error = str(e)
            logger.error(f"Error connecting to WordPress database: {e}")
            return None

    def get_all_posts(self):
        """Fetch all published posts and pages from WordPress"""
        connection = self.get_connection()
        if not connection:
            detail = self.last_connection_error or "unknown connection error"
            raise ConnectionError(f"Failed to connect to WordPress database for posts fetch: {detail}")
        
        try:
            with connection.cursor() as cursor:
                # Query to get published posts and pages with their metadata
                query = f"""
                SELECT 
                    p.ID as id,
                    p.post_title as title,
                    p.post_content as content,
                    p.post_type as type,
                    p.post_date as date,
                    p.post_name as post_name
                FROM 
                    {self.table_prefix}posts p
                WHERE 
                    p.post_status = 'publish' AND
                    p.post_content != ''
                ORDER BY 
                    p.post_date DESC
                """

                logger.info(f"Query: {query}")
                
                cursor.execute(query)
                results = cursor.fetchall()
                
                # Get site URL for URL construction
                site_url = self._get_site_url()
                logger.info(f"Site URL: {site_url}")
                
                # Process results to clean content and construct valid URLs
                for post in results:
                    # Basic HTML cleaning
                    post['content'] = self._clean_html_content(post['content'])
                    
                    # Construct and validate URL using the new utility
                    post['url'] = clean_wordpress_url(
                        site_url, 
                        post['post_name'], 
                        post['id']
                    )
                    
                    # Log URL issues for debugging
                    if post['url'] == site_url:
                        logger.warning(f"Post {post['id']} '{post['title']}' using fallback URL due to invalid post_name: {post['post_name']}")
                
                return results
        except Exception as e:
            logger.error(f"Error fetching WordPress posts: {e}")
            return []
        finally:
            connection.close()
    
    def get_external_urls(self):
        """Fetch all external URLs from the custom URL table"""
        connection = self.get_connection()
        if not connection:
            detail = self.last_connection_error or "unknown connection error"
            raise ConnectionError(f"Failed to connect to WordPress database for external URLs fetch: {detail}")
        
        try:
            with connection.cursor() as cursor:
                # Query the custom URL table - only fetch existing columns
                query = f"""
                SELECT 
                    id,
                    url,
                    date
                FROM 
                    {self.url_table}
                """
                
                cursor.execute(query)
                results = cursor.fetchall()
                
                # Add missing fields that the embedder expects and validate URLs
                processed_results = []
                for result in results:
                    processed_result = result.copy()
                    
                    # Validate and fix the URL
                    original_url = result['url']
                    fixed_url = validate_and_fix_url(original_url, fallback_base=self.fallback_site_url)
                    
                    if fixed_url != original_url:
                        logger.warning(f"Fixed external URL: {original_url} -> {fixed_url}")
                    
                    processed_result['url'] = fixed_url
                    
                    # Add default title and description based on URL
                    processed_result['title'] = f"External content from {fixed_url}"
                    processed_result['description'] = f"External content fetched from {fixed_url}"
                    processed_results.append(processed_result)
                
                return processed_results
        except Exception as e:
            logger.error(f"Error fetching external URLs: {e}")
            return []
        finally:
            connection.close()
    
    def _get_site_url(self):
        """Get the WordPress site URL from options table"""
        connection = self.get_connection()
        if not connection:
            return "https://mrnwebdesigns.com/"
        
        try:
            with connection.cursor() as cursor:
                query = f"""
                SELECT 
                    option_value
                FROM 
                    {self.table_prefix}options
                WHERE 
                    option_name = 'siteurl'
                LIMIT 1
                """
                
                cursor.execute(query)
                result = cursor.fetchone()
                
                if result and 'option_value' in result:
                    site_url = result['option_value']
                    if not site_url.endswith('/'):
                        site_url += '/'
                    return site_url
                else:
                    return "https://mrnwebdesigns.com/"
        except Exception as e:
            logger.warning(f"Error fetching site URL: {e}")
            return "https://mrnwebdesigns.com/"
        finally:
            connection.close()
    
    def _clean_html_content(self, html_content):
        """Clean HTML content to extract plain text (basic version)"""
        # Very basic cleaning - you might want to use BeautifulSoup for better results
        import re
        
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', ' ', html_content)
        
        # Replace multiple spaces, newlines with single space
        text = re.sub(r'\s+', ' ', text)
        
        # Remove special characters
        text = re.sub(r'&[^;]+;', ' ', text)
        
        return text.strip()

# For testing
if __name__ == "__main__":
    wp_fetcher = WordPressFetcher()
    
    # Test fetching posts
    posts = wp_fetcher.get_all_posts()
    print(f"Found {len(posts)} WordPress posts")
    
    # Test fetching external URLs
    urls = wp_fetcher.get_external_urls()
    print(f"Found {len(urls)} external URLs") 