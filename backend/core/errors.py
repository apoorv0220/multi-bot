from fastapi import Request
from fastapi.responses import JSONResponse


def error_payload(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


async def unhandled_exception_handler(request: Request, exc: Exception, include_detail: bool = False):
    message = str(exc) if include_detail else "Internal server error"
    return JSONResponse(status_code=500, content=error_payload("internal_error", message))
