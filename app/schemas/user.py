import re
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

# Shared properties
class UserBase(BaseModel):
    email: Optional[EmailStr] = None
    is_active: Optional[bool] = True

# Common passwords blocklist
_COMMON_PASSWORDS = {
    "password",
    "password123",
    "12345678",
    "123456789",
    "qwerty",
    "qwerty123",
    "admin",
    "admin123",
    "letmein",
    "welcome",
    "monkey",
    "dragon",
    "password1",
    "1234567890",
    "abc123",
}

# Properties to receive via API on creation
class UserCreate(UserBase):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError("Password must be at least 12 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]", v):
            raise ValueError("Password must contain at least one special character")
        if v.lower() in _COMMON_PASSWORDS:
            raise ValueError("Password is too common")
        # Block sequential patterns
        if re.search(r"(.)\1\1", v):  # 3 repeating chars
            raise ValueError("Password must not contain 3 repeating characters")
        return v

# Properties to receive via API on update
class UserUpdate(UserBase):
    password: Optional[str] = None

    @field_validator("password")
    @classmethod
    def validate_password_strength_update(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if len(v) < 12:
            raise ValueError("Password must be at least 12 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]", v):
            raise ValueError("Password must contain at least one special character")
        if v.lower() in _COMMON_PASSWORDS:
            raise ValueError("Password is too common")
        return v

# Properties to return via API
class UserOut(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr

# Properties stored in DB
class UserInDB(UserOut):
    hashed_password: str
