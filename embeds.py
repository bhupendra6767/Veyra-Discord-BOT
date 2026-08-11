import discord
from datetime import datetime, timezone
from typing import Optional

class VeyraEmbed(discord.Embed):
    """Base embed for Veyra to ensure consistent visual identity."""
    
    # Brand Colors
    SUCCESS_COLOR = 0x2ecc71
    ERROR_COLOR = 0xe74c3c
    WARNING_COLOR = 0xf1c40f
    INFO_COLOR = 0x3498db
    DEFAULT_COLOR = 0x2b2d31 # Discord dark theme matching

    def __init__(self, **kwargs):
        color = kwargs.pop("color", self.DEFAULT_COLOR)
        # Truncate strings to Discord limits if passed in constructor
        if "title" in kwargs and isinstance(kwargs["title"], str) and len(kwargs["title"]) > 256:
            kwargs["title"] = kwargs["title"][:253] + "..."
        if "description" in kwargs and isinstance(kwargs["description"], str) and len(kwargs["description"]) > 4096:
            kwargs["description"] = kwargs["description"][:4093] + "..."
        super().__init__(color=color, **kwargs)
        self.timestamp = datetime.now(timezone.utc)
        
    def add_field(self, *, name: str, value: str, inline: bool = True) -> 'VeyraEmbed':
        if isinstance(name, str) and len(name) > 256:
            name = name[:253] + "..."
        if isinstance(value, str) and len(value) > 1024:
            value = value[:1021] + "..."
        super().add_field(name=name, value=value, inline=inline)
        return self


    @classmethod
    def success(cls, title: str, description: str, **kwargs) -> 'VeyraEmbed':
        return cls(title=title, description=description, color=cls.SUCCESS_COLOR, **kwargs)
        
    @classmethod
    def error(cls, title: str, description: str, **kwargs) -> 'VeyraEmbed':
        return cls(title=title, description=description, color=cls.ERROR_COLOR, **kwargs)

    @classmethod
    def warning(cls, title: str, description: str, **kwargs) -> 'VeyraEmbed':
        return cls(title=title, description=description, color=cls.WARNING_COLOR, **kwargs)

    @classmethod
    def info(cls, title: str, description: str, **kwargs) -> 'VeyraEmbed':
        return cls(title=title, description=description, color=cls.INFO_COLOR, **kwargs)

    @classmethod
    def status(cls, title: str, description: str, **kwargs) -> 'VeyraEmbed':
        return cls(title=title, description=description, color=cls.DEFAULT_COLOR, **kwargs)

