import os
import pymysql
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def check_url_table():
    """Check the schema of the URL table"""
    try:
        # Get connection details from environment variables
        host = os.getenv("WORDPRESS_DB_HOST")
        port = int(os.getenv("WORDPRESS_DB_PORT", 3306))
        user = os.getenv("WORDPRESS_DB_USER")
        password = os.getenv("WORDPRESS_DB_PASSWORD")
        database = os.getenv("WORDPRESS_DB_NAME")
        url_table = os.getenv("WORDPRESS_URL_TABLE", "wp_custom_urls")
        
        # Connect to the database
        connection = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database
        )
        
        # Create a cursor
        cursor = connection.cursor()
        
        # Describe the table to get column information
        print(f"Checking schema for table: {url_table}")
        cursor.execute(f"DESCRIBE {url_table}")
        columns = cursor.fetchall()
        
        print("\nURL Table Columns:")
        for column in columns:
            print(f"  - {column[0]}: {column[1]}")
        
        # Get sample data
        print("\nSample data from URL table:")
        cursor.execute(f"SELECT * FROM {url_table} LIMIT 3")
        rows = cursor.fetchall()
        
        for row in rows:
            print(f"\nRow data:")
            for i, column in enumerate(cursor.description):
                print(f"  {column[0]}: {row[i]}")
        
        # Close the connection
        connection.close()
        
    except Exception as e:
        print(f"Error checking URL table: {e}")

if __name__ == "__main__":
    check_url_table() 