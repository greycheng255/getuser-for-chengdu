import psycopg2

conn = psycopg2.connect(
    host='122.51.51.177',
    port=15435,
    dbname='media_crawler_chengdu',
    user='media_crawler_chengdu',
    password='FjeAwcQbacemzxG5_chengdu'
)

cur = conn.cursor()

try:
    cur.execute('ALTER TABLE x_twitter_comment ADD COLUMN IF NOT EXISTS quotes_count VARCHAR(255) DEFAULT \'0\'')
    cur.execute('ALTER TABLE x_twitter_post ADD COLUMN IF NOT EXISTS hashtags TEXT DEFAULT \'\'')
    conn.commit()
    print('Database schema updated successfully')
except Exception as e:
    print(f'Error: {e}')
    conn.rollback()

conn.close()