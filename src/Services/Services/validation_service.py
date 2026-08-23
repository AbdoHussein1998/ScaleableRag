# src\Services\Services\validation_service.py
from Authentication.Providers.jwt_services_provider import JWTHandler
import loguru
from typing import Optional,Bool
from fastapi import Request,Response
from fastapi.responses import FileResponse


class ValidationService:
    def __init__(self,logger:Optional[loguru.Logger]=None):
        self.jwt:JWTHandler=None
        self.logger=loguru.logger or logger
    @classmethod
    async def init_service(cls,logger:Optional[loguru.Logger]=None):
        logger=logger or loguru.logger
        instacne=cls(logger)
        instacne.jwt=await JWTHandler.init_class(logger=logger)
        return instacne


    
    async def verify_access_tokens(self,request:Request,)->Bool:
        access_tokens=self.jwt.get_access_token_from_request(request=request)
        payload=await self.jwt.verify_access_token(token=access_tokens)
        if payload:
            return True
        return False
