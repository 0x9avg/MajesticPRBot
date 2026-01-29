
import asyncio
import aiohttp
import sys

async def main():
    async with aiohttp.ClientSession() as session:
        # 1. Create event to join (or mock)
        # We need an event ID.
        # Let's list active events.
        print("Listing active events...")
        async with session.get("http://localhost:8000/api/events/active?guild_id=123") as resp:
             print(f"List events status: {resp.status}")
             try:
                 events = await resp.json()
                 print(f"Events: {events}")
             except:
                 print("Failed to parse events")
                 events = []
             
        event_id = events[0]['id'] if events else 1
        user_id = 123456789
        
        print(f"Trying to join event {event_id} with user {user_id}...")
        async with session.post(f"http://localhost:8000/api/events/{event_id}/join", json={"user_id": user_id}) as resp:
            print(f"Response Status: {resp.status}")
            text = await resp.text()
            print(f"Response Body: {text}")
            try:
                data = await resp.json()
                print(f"Parsed JSON type: {type(data)}")
                print(f"Parsed JSON: {data}")
            except:
                print("Could not parse JSON")

        print("Checking Guild Settings...")
        async with session.get("http://localhost:8000/api/guild") as resp:
             print(f"GET /guild Status: {resp.status}")
             text = await resp.text()
             print(f"GET /guild Body: {text}")
             try:
                 data = await resp.json()
                 print(f"GET /guild JSON type: {type(data)}")
             except: pass

        print("Checking Active Event...")
        async with session.get(f"http://localhost:8000/api/events/user/{user_id}/active") as resp:
             print(f"GET /active Status: {resp.status}")
             text = await resp.text()
             print(f"GET /active Body: {text}")
             try:
                 data = await resp.json()
                 print(f"GET /active JSON type: {type(data)}")
             except: pass

if __name__ == "__main__":
    asyncio.run(main())
