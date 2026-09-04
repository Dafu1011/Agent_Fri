from abc import ABC, abstractmethod

from ..schemas.media import MediaInfo


class BaseExtractor(ABC):
    platform: str

    @classmethod
    @abstractmethod
    def match(cls, url: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def extract(self, url: str) -> MediaInfo:
        raise NotImplementedError
