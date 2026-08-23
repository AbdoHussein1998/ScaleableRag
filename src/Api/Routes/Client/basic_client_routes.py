from fastapi import APIRouter, Depends, UploadFile, File, Request,status
from fastapi.responses import JSONResponse
from Dependencies.welcome_dependency import get_welcome_service, WelcomeService
from Dependencies.validation_dependency import get_validation_service,ValidationService
from Celery.Tasks.welcome_task import welcome_task 
from fastapi import Request,Response

basic_client_router=APIRouter(prefix="/api/v1/client",tags=["Client"],)



@basic_client_router.post("/")
async def welcome_task_enqueue(request:Request,
                               valid_handler:ValidationService=Depends(get_validation_service)
                               ):
    """
    Enqueue the welcome task asynchronously via Celery.
    Returns the task_id for status polling.
    """
    ########## Verifing Access Tokens ########## 
    case= await valid_handler.verify_access_tokens(request=request,)


    if not case:
        res=JSONResponse(content={"detail": "Unauthorized"}, 
                            status_code=status.HTTP_401_UNAUTHORIZED)
        valid_handler.jwt.clear_auth_cookies(response=res)
        return res
    ########## RateLimiting Stage ##########



    
    ########## Main Task  ##########

    task = welcome_task.delay()  # send to broker, non-blocking
    
    return {
            "task_id": task.id,
            "status": "queued",
            "message": "Welcome task has been enqueued"
    }
   


