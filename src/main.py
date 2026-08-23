from dotenv import load_dotenv
load_dotenv()
from Api.Routes.Client.basic_client_routes import basic_client_router
from Api.Routes.Auth.auth_routes import auth_router
from Api.ApiConfiguration.fast_api_config import create_lifespan
from fastapi import FastAPI
import uvicorn
import os
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI(lifespan=create_lifespan())
app.include_router(basic_client_router)
app.include_router(auth_router)

app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("MIDDLEWARE_SECRET_KEY"),
    same_site="lax",
    https_only=False, # Set to True in production
)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True,workers=1)






