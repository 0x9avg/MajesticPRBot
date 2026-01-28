
import asyncio
import os
import sys

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Database, Config

def format_table(headers, rows):
    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(str(val)))
            
    # Create separator
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    
    lines = [sep]
    
    # Header
    header_line = "|" + "|".join(f" {h:<{w}} " for h, w in zip(headers, widths)) + "|"
    lines.append(header_line)
    lines.append(sep)
    
    # Rows
    for row in rows:
        row_line = "|" + "|".join(f" {str(val):<{w}} " for val, w in zip(row, widths)) + "|"
        lines.append(row_line)
        
    lines.append(sep)
    return "\n".join(lines)

async def dump_schema():
    db = Database(
        db_host=Config.DB_HOST,
        db_user=Config.DB_USER,
        db_password=Config.DB_PASSWORD,
        db_name=Config.DB_NAME,
        logger=Config.setup_logging("FixEventsSchema")
    )
    
    output_file = "db_schema.txt"
    
    try:
        await db.start()
        async with db.pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # Get tables
                await cursor.execute("SHOW TABLES")
                tables = await cursor.fetchall()
                table_names = [list(t.values())[0] for t in tables]
                
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(f"DATABASE SCHEMA: {Config.DB_NAME}\n")
                    f.write("=" * 50 + "\n\n")
                    
                    for table in table_names:
                        f.write(f"TABLE: {table}\n")
                        
                        await cursor.execute(f"DESCRIBE {table}")
                        columns = await cursor.fetchall()
                        # columns is list of dicts or tuples depending on cursor? 
                        # aiomysql DictCursor returns dict.
                        # DESCRIBE returns: Field, Type, Null, Key, Default, Extra
                        
                        headers = ["Field", "Type", "Null", "Key", "Default", "Extra"]
                        rows = []
                        for col in columns:
                            # If dict
                            if isinstance(col, dict):
                                rows.append([
                                    col['Field'], 
                                    col['Type'], 
                                    col['Null'], 
                                    col['Key'], 
                                    col['Default'] if col['Default'] is not None else 'NULL', 
                                    col['Extra']
                                ])
                            else:
                                # Tuple
                                rows.append([str(c) for c in col])
                                
                        f.write(format_table(headers, rows))
                        f.write("\n\n")
                        
        print(f"Schema dumped to {os.path.abspath(output_file)}")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await db.close()

if __name__ == "__main__":
    asyncio.run(dump_schema())
