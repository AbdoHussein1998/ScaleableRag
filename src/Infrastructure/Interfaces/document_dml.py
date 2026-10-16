



from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Optional


class DocumentInterfaceDML(ABC):

    @classmethod
    @abstractmethod
    async def init_class(self):
        pass

    # ==================== INSERT ====================

    @abstractmethod
    async def insert_one(self) -> Optional[Any]:
        pass
    @abstractmethod
    async def insert_many(self) -> Optional[List[Any]]:
       pass

    # ==================== READ ====================

    @abstractmethod
    async def get_one(self,) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    async def stream_many_docs(self,) -> AsyncGenerator[List[Dict[str, Any]], None]:
        pass

    @abstractmethod
    async def get_many(self,) -> List[Dict[str, Any]]:
       pass

    # ==================== UPDATE ====================

    @abstractmethod
    async def update_one(self,) -> bool:
        pass
    @abstractmethod
    async def update_many(self,) -> bool:
        pass


    # ==================== DELETE ====================
    @abstractmethod
    async def delete_one(self):
        pass
    @abstractmethod
    async def delete_many(self):
        pass
