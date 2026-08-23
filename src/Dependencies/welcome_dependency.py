#src/Dependencies/welcome_dependency.py

from Services.Services.welcome_service import WelcomeService
import loguru


async def get_welcome_service()->WelcomeService:

    logger=loguru.logger
    return await WelcomeService.init_service(logger=logger)




