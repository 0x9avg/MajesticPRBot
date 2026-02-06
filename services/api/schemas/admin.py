from pydantic import BaseModel

class UserCreate(BaseModel):
    username: str
    nickname: str
    role: str
    discord_id: int
