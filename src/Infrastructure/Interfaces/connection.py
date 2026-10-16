from abc import ABC, abstractmethod


class ConnectionManagerInterface(ABC):

    @classmethod
    @abstractmethod
    async def init_class(cls):
        pass

    @abstractmethod
    async def connect(self):
        pass
    @abstractmethod
    async def disconnect(self):
        pass
    @abstractmethod
    async def reconnect(self):
        pass
    @abstractmethod
    async def ensure_connected(self):
        pass
