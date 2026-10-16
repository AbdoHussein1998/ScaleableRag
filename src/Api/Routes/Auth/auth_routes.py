from fastapi import APIRouter, Depends, Request,Response

from Dependencies.auth_dependency import get_auth_service
from Services.Services.auth_service import AuthService
from src.Infrastructure.Authentication.Schema.models import TokenPayload
auth_router = APIRouter(prefix="/api/v1/auth",tags=["Auth", "Google"],)

@auth_router.get("/google/login",name="google_login",)
async def google_login(request: Request,auth_service: AuthService = Depends(get_auth_service),):

    return await auth_service.redirect_to_google(request)

@auth_router.get("/google/callback",name="google_callback",)
async def google_callback(request: Request,auth_service: AuthService = Depends(get_auth_service),):


    data= await auth_service.receiving_from_google(request) # Data of Google 
    await auth_service.save_to_database(data=data) 

    token_data= await auth_service.generate_tokens(data=data)
    
    return await auth_service.go_to_home_and_store_token(token_data=token_data)


@auth_router.post("/refresh")
async def refresh_tokens(request:Request,response:Response, auth_service:AuthService = Depends(get_auth_service),):
    refresh_tokens=auth_service.jwt_handler.get_refresh_token_from_request(request=request,)
    tokens_data=await auth_service.jwt_handler.re_freshing_all_tokens(refresh_tokens)
    auth_service.jwt_handler.set_auth_cookies(response=response,access_token=tokens_data["access_token"],refresh_token=tokens_data["refresh_token"],)
    
