import os
from fastapi import logging
import pymysql
from dotenv import load_dotenv

# Configure proper logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("embedder")

# Load environment variables
load_dotenv()

class WordPressFetcher:
    def __init__(self):
        self.host = os.getenv("WORDPRESS_DB_HOST")
        self.port = int(os.getenv("WORDPRESS_DB_PORT", 3306))
        self.user = os.getenv("WORDPRESS_DB_USER")
        self.password = os.getenv("WORDPRESS_DB_PASSWORD")
        self.database = os.getenv("WORDPRESS_DB_NAME")
        self.url_table = os.getenv("WORDPRESS_URL_TABLE")
        self.table_prefix = os.getenv("WORDPRESS_TABLE_PREFIX", "afn_")

    def get_connection(self):
        """Establish a connection to the WordPress database"""
        try:
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
            print(f"Error connecting to WordPress database: {e}")
            return None

    def get_all_posts(self):
        """Fetch all published posts and pages from WordPress"""
        connection = self.get_connection()
        if not connection:
            return []
        
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
                    CONCAT(%s, p.post_name) as url
                FROM 
                    {self.table_prefix}posts p
                WHERE 
                    p.post_status = 'publish' AND
                    p.post_type IN ('post', 'page') AND
                    p.post_content != ''
                ORDER BY 
                    p.post_date DESC
                """

                logger.info(f"Query: {query}")
                
                # Website URL with trailing slash
                site_url = self._get_site_url()

                logger.info(f"Site URL: {site_url}")
                
                cursor.execute(query, (site_url,))
                results = cursor.fetchall()
                
                # Process results to clean content
                for post in results:
                    # Basic HTML cleaning (you might want to improve this)
                    post['content'] = self._clean_html_content(post['content'])
                
                return results
        except Exception as e:
            print(f"Error fetching WordPress posts: {e}")
            return []
        finally:
            connection.close()
    
    def get_external_urls(self):
        """Fetch all external URLs from the custom URL table"""
        connection = self.get_connection()
        if not connection:
            return []
        
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
                
                # Add missing fields that the embedder expects
                processed_results = []
                for result in results:
                    processed_result = result.copy()
                    # Add default title and description based on URL
                    processed_result['title'] = f"External content from {result['url']}"
                    processed_result['description'] = f"External content fetched from {result['url']}"
                    processed_results.append(processed_result)
                
                return processed_results
        except Exception as e:
            print(f"Error fetching external URLs: {e}")
            return []
        finally:
            connection.close()
    
    def _get_site_url(self):
        """Get the WordPress site URL from options table"""
        connection = self.get_connection()
        if not connection:
            return "https://houseoftiles.ie/"
        
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
                    return "https://houseoftiles.ie/"
        except Exception as e:
            print(f"Error fetching site URL: {e}")
            return "https://houseoftiles.ie/"
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