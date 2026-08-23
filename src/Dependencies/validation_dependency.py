# src\Dependencies\validation_dependency.py
from Services.Services.validation_service import ValidationService

async def get_validation_service()->ValidationService:
    return await ValidationService.init_service()





