"""统一的错误响应（契约 §3）：{ "error": { "code", "message", "details" } }。"""

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("uvicorn.error")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: list[str] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or []


def bad_request(message: str, details: list[str] | None = None) -> ApiError:
    return ApiError(400, "VALIDATION_FAILED", message, details)


def not_found(message: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", message)


def conflict(message: str, details: list[str] | None = None) -> ApiError:
    return ApiError(409, "CONFLICT", message, details)


class BodyLimit:
    """请求体超过上限时返回 413，不读进内存：服务没有鉴权、监听 0.0.0.0，不能让一个请求把内存撑爆。

    有 Content-Length 的在读之前就拒绝；分块传输的边读边计数，超过时抛 HTTPException(413)：FastAPI 解析请求体时
    会把其他异常一律换成 400，只原样放过 HTTPException，再由下面的处理器转成统一格式。
    必须在 errors.install 之前注册（先注册的在里层），这样 413 也经过 CORS。"""

    def __init__(self, app, limit: int):
        self.app = app
        self.limit = limit

    def _error(self) -> ApiError:
        return ApiError(413, "PAYLOAD_TOO_LARGE", f"请求体超过 {self.limit // (1024 * 1024)} MiB 的上限")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        for name, value in scope.get("headers") or []:
            if name == b"content-length" and value.isdigit() and int(value) > self.limit:
                exc = self._error()
                await error_response(exc.status, exc.code, exc.message)(scope, receive, send)
                return
        received = 0

        async def limited():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    raise HTTPException(413, self._error().message)
            return message

        await self.app(scope, limited, send)


def error_response(status: int, code: str, message: str, details: list[str] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "details": details or []}},
    )


_LOC_PREFIX = {"body": "请求体", "query": "查询参数", "path": "路径参数", "header": "请求头"}
_PARAM_NAMES = {"item_id": "id", "run_id": "runId"}


def _translate(err: dict) -> str:
    """把 FastAPI / pydantic 的一条校验错误翻成中文。"""
    loc = list(err.get("loc") or [])
    where = _LOC_PREFIX.get(loc[0], str(loc[0])) if loc else "请求"
    field = ".".join(_PARAM_NAMES.get(str(p), str(p)) for p in loc[1:])
    kind = str(err.get("type", ""))
    if kind.startswith("json_invalid"):
        field = ""  # 这时 loc 里是出错的字符位置，对使用者没有意义
    if kind == "missing":
        reason = "缺少必填内容"
    elif kind.startswith("json_invalid"):
        reason = "不是合法的 JSON"
    elif kind.startswith("int"):
        reason = "必须是整数"
    elif kind.startswith("float"):
        reason = "必须是数字"
    elif kind.startswith("bool"):
        reason = "必须是 true 或 false"
    elif kind.startswith("string"):
        reason = "必须是字符串"
    elif kind.startswith(("dict", "model")):
        reason = "必须是 JSON 对象"
    else:
        reason = str(err.get("msg", "格式错误"))
    return f"{where} {field}：{reason}" if field else f"{where}：{reason}"


_STATUS_CODE = {404: "NOT_FOUND", 409: "CONFLICT", 413: "PAYLOAD_TOO_LARGE", 422: "PREFLIGHT_REJECTED"}
_STATUS_MESSAGE = {404: "资源不存在", 405: "不支持的请求方法"}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return error_response(exc.status, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        return error_response(400, "VALIDATION_FAILED", "请求参数格式错误", [_translate(e) for e in exc.errors()])

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        status = exc.status_code
        if status >= 500:
            code = "INTERNAL"
        else:
            code = _STATUS_CODE.get(status, "VALIDATION_FAILED")
        message = _STATUS_MESSAGE.get(status) or str(exc.detail or "请求失败")
        return error_response(status, code, message)

    # 兜底的 500。不用 exception_handler(Exception)：那个处理器挂在最外层的
    # ServerErrorMiddleware 上，在 CORS 中间件之外，跨域时浏览器读不到响应体。
    # 这个中间件必须先于 CORSMiddleware 注册（后注册的在更外层）。
    @app.middleware("http")
    async def _catch_all(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:  # noqa: BLE001
            log.exception("未处理的异常：%s %s", request.method, request.url.path)
            return error_response(500, "INTERNAL", f"服务器内部错误：{type(exc).__name__}: {exc}")
