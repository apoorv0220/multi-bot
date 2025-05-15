import os
import sys
from dotenv import load_dotenv
import mysql.connector
import requests

# Load environment variables
load_dotenv()

def check_wordpress_db():
    """Check connection to WordPress database"""
    print("🔍 Testing WordPress Database Connection")
    print("=======================================")
    
    wp_db_host = os.getenv("WORDPRESS_DB_HOST", "localhost")
    wp_db_port = int(os.getenv("WORDPRESS_DB_PORT", 3306))
    wp_db_user = os.getenv("WORDPRESS_DB_USER", "root")
    wp_db_password = os.getenv("WORDPRESS_DB_PASSWORD", "")
    wp_db_name = os.getenv("WORDPRESS_DB_NAME", "migrainenew_mgrnnwdb")
    
    # Print connection details
    print(f"Connection details:")
    print(f"  Host: {wp_db_host}")
    print(f"  Port: {wp_db_port}")
    print(f"  User: {wp_db_user}")
    print(f"  Password: {'*' * len(wp_db_password) if wp_db_password else '(empty)'}")
    print(f"  Database: {wp_db_name}")
    
    try:
        # Attempt to connect to the database
        print("\nAttempting database connection...")
        connection = mysql.connector.connect(
            host=wp_db_host,
            port=wp_db_port,
            user=wp_db_user,
            password=wp_db_password,
            database=wp_db_name
        )
        
        if connection.is_connected():
            db_info = connection.get_server_info()
            print(f"✅ Connected to MySQL Server version {db_info}")
            
            # Get cursor
            cursor = connection.cursor()
            
            # Get WordPress posts
            print("\nFetching WordPress posts...")
            cursor.execute("SELECT COUNT(*) FROM wp_posts WHERE post_status = 'publish' AND post_type IN ('post', 'page')")
            post_count = cursor.fetchone()[0]
            print(f"  Found {post_count} published posts/pages")
            
            if post_count > 0:
                cursor.execute("SELECT ID, post_title, post_date FROM wp_posts WHERE post_status = 'publish' AND post_type IN ('post', 'page') LIMIT 5")
                posts = cursor.fetchall()
                print("\nSample posts:")
                for post in posts:
                    print(f"  - ID: {post[0]}, Title: {post[1]}, Date: {post[2]}")
            
            # Check if custom URLs table exists
            print("\nChecking for external URLs table...")
            url_table = os.getenv("WORDPRESS_URL_TABLE", "wp_custom_urls")
            cursor.execute(f"SHOW TABLES LIKE '{url_table}'")
            table_exists = cursor.fetchone() is not None
            
            if table_exists:
                print(f"✅ External URLs table '{url_table}' exists")
                cursor.execute(f"SELECT COUNT(*) FROM {url_table}")
                url_count = cursor.fetchone()[0]
                print(f"  Found {url_count} external URLs")
                
                if url_count > 0:
                    cursor.execute(f"SELECT id, url, title FROM {url_table} LIMIT 5")
                    urls = cursor.fetchall()
                    print("\nSample external URLs:")
                    for url in urls:
                        print(f"  - ID: {url[0]}, URL: {url[1]}, Title: {url[2]}")
            else:
                print(f"❌ External URLs table '{url_table}' does not exist")
            
            connection.close()
            print("\n✅ WordPress database check completed successfully")
            return True
            
    except mysql.connector.Error as e:
        print(f"\n❌ Error connecting to WordPress database: {e}")
        return False

def check_external_urls():
    """Test access to external URLs"""
    print("\n🔍 Testing External URL Access")
    print("===========================")
    
    test_urls = [
        "https://www.migrainetrust.org/",
        "https://americanmigrainefoundation.org/",
        "https://www.nhs.uk/conditions/migraine/"
    ]
    
    success_count = 0
    
    for url in test_urls:
        print(f"Testing access to: {url}")
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                print(f"  ✅ Successfully accessed {url}")
                success_count += 1
            else:
                print(f"  ⚠️ Received status code {response.status_code} from {url}")
        except Exception as e:
            print(f"  ❌ Error accessing {url}: {e}")
    
    print(f"\n{success_count}/{len(test_urls)} external URLs were successfully accessed")
    return success_count > 0

if __name__ == "__main__":
    wordpress_ok = check_wordpress_db()
    external_urls_ok = check_external_urls()
    
    print("\n📋 Connection Summary")
    print("===================")
    print(f"WordPress Database: {'✅ Connected' if wordpress_ok else '❌ Failed'}")
    print(f"External URLs: {'✅ Accessible' if external_urls_ok else '❌ Failed'}")
    
    if not wordpress_ok:
        print("\n⚠️ WordPress database connection failed. Please check your .env file and database credentials.")
        print("The embedder won't be able to fetch WordPress content.")
    
    if not external_urls_ok:
        print("\n⚠️ External URL access failed. Please check your internet connection.")
        print("The embedder won't be able to scrape external content.")
    
    if not wordpress_ok and not external_urls_ok:
        print("\n❌ All content sources are unavailable. Embeddings cannot be created.")
        sys.exit(1) 