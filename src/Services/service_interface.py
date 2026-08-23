#service_interface.py
from abc import ABC,abstractmethod
from typing import Optional
import loguru

  

class ServiceInterface(ABC):
    def __init__(
        self,
        logger: Optional[loguru._logger.Logger] = None,
    ) -> None:
        self.logger = logger or loguru.logger

    @classmethod
    @abstractmethod
    async def init_service(
        cls,
        *args,
        **kwargs,
    ):
        """
        Service-specific async factory initialization.
        """
        pass


    
  
   