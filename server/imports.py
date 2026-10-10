"""接口导入（契约 §3.9）：OpenAPI 3.x / Swagger 2.0（JSON 或 YAML）、Postman Collection v2.0 / v2.1。

映射规则参照 Hoppscotch（MIT）的导入器 packages/hoppscotch-common/src/helpers/import-export/import/，
按本项目的接口模型改写：路径相对被测环境的 baseUrl，变量一律写成 {{name}}，没有"继承认证"和"禁用的行"，
认证一律展开成请求头或 query；不支持的内容不静默丢掉，逐条写进 notes 给页面显示，也写进接口备注。

只解析文档，不访问被测接口。按地址导入时由这里用 urllib 取一次文档：这是取文档，不是调试，不经 k6。
YAML 的别名可以让很小的文档展开成极大的结构，所以复制和遍历文档内容都走 _Budget 计数。
"""

import base64
import json
import re
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urljoin, urlsplit

import yaml
from fastapi import APIRouter, Body

from . import db, resources
from .errors import ApiError, bad_request
from .validators import METHODS, is_int, validate_api, validate_folder
from .variables import dynamic_problem, refs

MAX_BYTES = 10 * 1024 * 1024
MAX_APIS = 2000
FETCH_TIMEOUT_SEC = 15
MAX_NODES = 200_000
MAX_SCHEMA_DEPTH = 10

router = APIRouter(prefix="/api/imports", tags=["导入"])


class _Budget:
    def __init__(self) -> None:
        self.left = MAX_NODES

    def spend(self) -> None:
        self.left -= 1
        if self.left < 0:
            raise bad_request("文档太大或嵌套太深（可能是 YAML 别名展开），无法导入")


# ---------- 读取文档 ----------

class _HttpOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """urllib 默认也跟随到 ftp；只允许 http / https，其余的按 3xx 失败处理。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme not in ("http", "https"):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_HttpOnlyRedirect)


def _fetch(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise bad_request("地址必须是 http / https 地址")
    req = urllib.request.Request(url, headers={
        "Accept": "application/json, application/yaml, text/yaml, */*;q=0.8",
        "User-Agent": "perf-console-import",
    })
    try:
        with _opener.open(req, timeout=FETCH_TIMEOUT_SEC) as resp:
            raw = resp.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise bad_request(f"取文档失败：HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise bad_request(f"取文档失败：{reason}")
    if len(raw) > MAX_BYTES:
        raise bad_request(f"文档超过 {MAX_BYTES // (1024 * 1024)} MiB")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise bad_request("文档不是 UTF-8 编码")


def _load(text: str) -> Any:
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise bad_request(f"文档超过 {MAX_BYTES // (1024 * 1024)} MiB")
    text = text.lstrip("\ufeff")
    if not text.strip():
        raise bad_request("内容为空")
    try:
        return json.loads(text)
    except RecursionError:
        raise bad_request("文档嵌套太深")
    except ValueError:
        pass
    try:
        # YAML 1.1：200: 这样的键读成整数，on / yes 读成布尔；用到的地方都按字符串比较
        return yaml.safe_load(text)
    except RecursionError:
        raise bad_request("文档嵌套太深")
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f"（第 {mark.line + 1} 行）" if mark is not None else ""
        raise bad_request(f"不是合法的 JSON 或 YAML{where}")


def _detect(doc: Any) -> str:
    if not isinstance(doc, dict):
        if isinstance(doc, str) and doc.lstrip().lower().startswith("curl"):
            raise bad_request("这是 cURL 命令，请用“从 cURL 导入接口”")
        raise bad_request("无法识别的格式：支持 OpenAPI 3.x、Swagger 2.0、Postman Collection v2.0 / v2.1")
    if str(doc.get("openapi", "")).startswith("3."):
        return "openapi"
    if str(doc.get("swagger", "")) in ("2.0", "2"):
        return "swagger"
    info = doc.get("info")
    if isinstance(info, dict) and isinstance(doc.get("item"), list):
        return "postman"
    if doc.get("_postman_variable_scope") or (isinstance(doc.get("values"), list) and "item" not in doc):
        raise bad_request("这是 Postman 环境文件，不是集合（Collection）；环境变量请在被测环境里添加")
    if isinstance(doc.get("requests"), list) and "order" in doc:
        raise bad_request("这是 Postman Collection v1，请在 Postman 里重新导出为 v2.1 再导入")
    if isinstance(doc.get("log"), dict) and "entries" in doc["log"]:
        raise bad_request("HAR 文件暂不支持导入")
    if doc.get("_type") == "export" and "resources" in doc:
        raise bad_request("Insomnia 导出文件暂不支持导入，可以在 Insomnia 里导出为 OpenAPI 或 Postman 格式")
    raise bad_request("无法识别的格式：支持 OpenAPI 3.x、Swagger 2.0、Postman Collection v2.0 / v2.1")


# ---------- 通用 ----------

def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _var_name(name: str) -> str:
    """参数名做变量名：不合法的字符换成下划线（变量名规则见契约 §3.1「变量」）。"""
    out = re.sub(r"\W", "_", name.strip())
    return out or "value"


def _scalar(value: Any) -> str:
    """示例值写进请求头、query、表单时的文本形式。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def _set_header(headers: dict[str, str], name: str, value: str) -> None:
    """请求头名称不区分大小写，后写的覆盖先写的。"""
    for existing in list(headers):
        if existing.lower() == name.lower():
            del headers[existing]
    headers[name] = value


def _has_header(headers: dict[str, str], name: str) -> bool:
    return any(k.lower() == name.lower() for k in headers)


def _with_query(path: str, pairs: list[tuple[str, str]]) -> str:
    if not pairs:
        return path
    query = "&".join(f"{k}={v}" for k, v in pairs)
    return f"{path}{'&' if '?' in path else '?'}{query}"


def _basic(user: str, password: str, notes: list[str]) -> str:
    if "{{" in user or "{{" in password:
        notes.append("Basic 认证的用户名或密码是变量，导入后请把 Authorization 请求头改成 Basic + base64(用户名:密码)")
        return "Basic {{basicAuth}}"
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def _check_dynamic(api: dict, notes: list[str]) -> None:
    """列出引擎不认识的 {{$动态变量}}（例如 Postman 的 $randomEmail），导入后页面上也会标出来。"""
    texts = [api["path"], api["body"] or "", *api["headers"].values(), *(i["value"] for i in api["form"])]
    unknown = sorted({name for text in texts for name in refs(text) if name.startswith("$") and dynamic_problem(name)})
    if unknown:
        notes.append("引擎不认识的动态变量：" + "、".join(unknown))


class _Out:
    """解析结果：文件夹、接口草稿、跳过的条目。key 只在这次预览和提交之间有效。"""

    def __init__(self, fmt: str, label: str, title: str):
        self.fmt, self.label, self.title = fmt, label, title
        self.folders: list[dict] = []
        self.apis: list[dict] = []
        self.skipped: list[dict] = []
        self.warnings: list[str] = []
        self.base_urls: list[str] = []
        self.variables: list[dict] = []

    def folder(self, name: str, parent: str | None) -> str:
        key = f"f{len(self.folders)}"
        self.folders.append({"key": key, "name": (name.strip() or "未命名文件夹")[:100], "parentKey": parent})
        return key

    def api(self, folder: str | None, api: dict, notes: list[str], description: str) -> None:
        """notes 是没能原样导入的内容，和文档里的说明一起写进接口备注。"""
        if len(self.apis) >= MAX_APIS:
            raise bad_request(f"一次最多导入 {MAX_APIS} 个接口")
        _check_dynamic(api, notes)
        api["name"] = api["name"][:100]
        api["note"] = "\n".join(x for x in (description, *notes) if x)
        self.apis.append({"key": f"a{len(self.apis)}", "folderKey": folder, "api": api, "notes": notes})

    def base_url(self, url: str | None) -> None:
        if url and url not in self.base_urls:
            self.base_urls.append(url)


def _blank_api(name: str, method: str, path: str) -> dict:
    return {
        "name": name, "method": method, "path": path, "headers": {}, "bodyType": "raw", "body": None,
        "form": [], "expectStatus": 200, "expectBodyContains": None, "extracts": [], "note": "",
    }


def _split_origin(url: str) -> tuple[str | None, str]:
    """把 server 地址拆成 (协议 + 主机, 路径前缀)。前缀进接口路径，被测环境的 baseUrl 只要协议 + 主机。"""
    url = url.strip()
    m = re.match(r"^([A-Za-z][\w+.-]*://[^/?#]*)(.*)$", url)
    origin, rest = (m.group(1), m.group(2)) if m else (None, url)
    prefix = rest.split("?")[0].split("#")[0].rstrip("/")
    if prefix and not prefix.startswith("/"):
        prefix = "/" + prefix
    return origin, prefix


# ---------- OpenAPI 3.x / Swagger 2.0 ----------

_FORMAT_SAMPLES = {
    "date-time": "2026-01-01T00:00:00Z",
    "date": "2026-01-01",
    "time": "00:00:00",
    "uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "email": "user@example.com",
    "uri": "https://example.com",
    "url": "https://example.com",
    "hostname": "example.com",
    "ipv4": "127.0.0.1",
    "ipv6": "::1",
}
_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


class _Spec:
    def __init__(self, doc: dict, budget: _Budget):
        self.doc = doc
        self.budget = budget
        self.external: set[str] = set()

    def pointer(self, ref: str) -> Any:
        cur: Any = self.doc
        for part in ref[2:].split("/") if ref != "#" else []:
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
                cur = cur[int(part)]
            else:
                return None
        return cur

    def deref(self, node: Any) -> Any:
        """顺着 $ref 走到实际的对象；外部引用、断开的引用、成环的引用返回 None。"""
        seen: set[str] = set()
        while isinstance(node, dict) and isinstance(node.get("$ref"), str):
            ref = node["$ref"]
            if not ref.startswith("#"):
                self.external.add(ref)
                return None
            if ref in seen:
                return None
            seen.add(ref)
            node = self.pointer(ref)
        return node

    def copy(self, value: Any, depth: int = 0) -> Any:
        """示例值原样复制，但计入预算：YAML 别名会让同一个对象被引用很多次。"""
        self.budget.spend()
        if depth > 64:
            raise bad_request("文档嵌套太深")
        if isinstance(value, dict):
            return {str(k): self.copy(v, depth + 1) for k, v in value.items()}
        if isinstance(value, list):
            return [self.copy(v, depth + 1) for v in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)  # YAML 里的日期等

    def example(self, schema: Any, depth: int = 0, stack: frozenset[str] = frozenset()) -> Any:
        """按 schema 生成示例：example / default / const / enum 优先，否则按类型和 format 给占位值。"""
        self.budget.spend()
        if depth > MAX_SCHEMA_DEPTH or not isinstance(schema, dict):
            return None
        ref = schema.get("$ref")
        if isinstance(ref, str):
            if ref in stack:
                return None  # 递归的 schema 到这里为止
            return self.example(self.deref(schema), depth + 1, stack | {ref})
        for key in ("example", "default", "const"):
            if key in schema:
                return self.copy(schema[key])
        if isinstance(schema.get("examples"), list) and schema["examples"]:
            return self.copy(schema["examples"][0])
        if isinstance(schema.get("enum"), list) and schema["enum"]:
            return self.copy(schema["enum"][0])
        if isinstance(schema.get("allOf"), list):
            merged: Any = None
            for part in schema["allOf"]:
                value = self.example(part, depth + 1, stack)
                if isinstance(merged, dict) and isinstance(value, dict):
                    merged = {**merged, **value}
                elif value is not None:
                    merged = value
            if merged is not None:
                return merged
        for key in ("oneOf", "anyOf"):
            options = schema.get(key)
            if isinstance(options, list):
                for option in options:
                    if isinstance(option, dict) and option.get("type") != "null":
                        return self.example(option, depth + 1, stack)
        kind = schema.get("type")
        if isinstance(kind, list):
            kind = next((k for k in kind if k != "null"), None)
        if kind is None:
            kind = "object" if "properties" in schema else "array" if "items" in schema else None
        if kind == "object":
            out: dict[str, Any] = {}
            props = schema.get("properties")
            if isinstance(props, dict):
                for name, prop in props.items():
                    real = self.deref(prop) if isinstance(prop, dict) else None
                    if isinstance(real, dict) and real.get("readOnly"):
                        continue  # 只出现在响应里
                    out[str(name)] = self.example(prop, depth + 1, stack)
            return out
        if kind == "array":
            item = self.example(schema.get("items"), depth + 1, stack)
            return [] if item is None else [item]
        if kind == "string":
            fmt = schema.get("format")
            return _FORMAT_SAMPLES.get(fmt, "" if fmt in ("binary", "byte") else "string")
        if kind in ("integer", "number"):
            low = schema.get("minimum")
            return low if isinstance(low, (int, float)) and not isinstance(low, bool) else 0
        if kind == "boolean":
            return True
        return None

    def properties(self, schema: Any) -> list[tuple[str, dict]]:
        """表单类请求体的字段：展开 $ref 和 allOf，按出现顺序。"""
        out: dict[str, dict] = {}

        def walk(node: Any, depth: int) -> None:
            self.budget.spend()
            node = self.deref(node)
            if not isinstance(node, dict) or depth > MAX_SCHEMA_DEPTH:
                return
            for part in node.get("allOf") or []:
                walk(part, depth + 1)
            props = node.get("properties")
            if isinstance(props, dict):
                for name, prop in props.items():
                    real = self.deref(prop)
                    if isinstance(real, dict) and not real.get("readOnly"):
                        out[str(name)] = real

        walk(schema, 0)
        return list(out.items())


def _is_file_schema(schema: dict) -> bool:
    if schema.get("type") == "file" or schema.get("format") in ("binary", "base64"):
        return True
    if "contentMediaType" in schema or "contentEncoding" in schema:
        return True
    items = schema.get("items")
    return schema.get("type") == "array" and isinstance(items, dict) and _is_file_schema(items)


def _param_value(spec: _Spec, param: dict) -> Any:
    """参数的示例值；没有时返回 None。Swagger 2.0 的参数没有 schema，类型写在参数自身上。"""
    for key in ("example", "x-example", "default"):
        if key in param:
            return spec.copy(param[key])
    examples = param.get("examples")
    if isinstance(examples, dict):
        for item in examples.values():
            item = spec.deref(item)
            if isinstance(item, dict) and "value" in item:
                return spec.copy(item["value"])
    if isinstance(param.get("enum"), list) and param["enum"]:
        return spec.copy(param["enum"][0])
    items = param.get("items")  # Swagger 2.0 的数组参数：取元素的默认值或第一个枚举值
    if param.get("type") == "array" and isinstance(items, dict):
        if "default" in items:
            return spec.copy(items["default"])
        if isinstance(items.get("enum"), list) and items["enum"]:
            return spec.copy(items["enum"][0])
    schema = spec.deref(param.get("schema"))
    if isinstance(schema, dict):
        for key in ("example", "default", "const"):
            if key in schema:
                return spec.copy(schema[key])
        if isinstance(schema.get("examples"), list) and schema["examples"]:
            return spec.copy(schema["examples"][0])
        if isinstance(schema.get("enum"), list) and schema["enum"]:
            return spec.copy(schema["enum"][0])
    return None


def _servers(spec: _Spec, source_url: str | None, *levels: Any) -> tuple[str | None, str]:
    """取最内层定义的第一个 server（操作 > 路径 > 文档），{变量} 用默认值替换。
    相对地址相对文档所在的位置；没有 servers 等于 "/"（OpenAPI 3 规范），所以按地址导入时能得出服务地址。"""
    for servers in levels:
        if isinstance(servers, list) and servers and isinstance(servers[0], dict):
            server = servers[0]
            url = _text(server.get("url"))
            variables = server.get("variables") if isinstance(server.get("variables"), dict) else {}
            url = re.sub(
                r"\{([^{}]+)\}",
                lambda m: _scalar((variables.get(m.group(1)) or {}).get("default", m.group(0))),
                url,
            )
            return _split_origin(urljoin(source_url, url) if source_url else url)
    return _split_origin(urljoin(source_url, "/")) if source_url else (None, "")


def _swagger_base(doc: dict, source_url: str | None) -> tuple[str | None, str]:
    """Swagger 2.0 没写 host / schemes 时用提供文档的那台主机和协议（规范如此）。"""
    source = urlsplit(source_url) if source_url else None
    host = _text(doc.get("host")) or (source.netloc if source else "")
    default_scheme = source.scheme if source else "https"
    schemes = doc.get("schemes") if isinstance(doc.get("schemes"), list) and doc["schemes"] else [default_scheme]
    base_path = _text(doc.get("basePath")).rstrip("/")
    if base_path and not base_path.startswith("/"):
        base_path = "/" + base_path
    return (f"{schemes[0]}://{host}" if host else None), base_path


def _security(spec: _Spec, op: dict, swagger: bool, headers: dict, query: list, notes: list[str]) -> None:
    requirements = op.get("security", spec.doc.get("security"))
    if not isinstance(requirements, list) or not requirements:
        return
    first = requirements[0]
    if not isinstance(first, dict) or not first:
        return  # {} 表示可以不认证
    if len(requirements) > 1:
        notes.append("文档里有多种认证方式，只导入了第一种")
    if swagger:
        schemes = spec.doc.get("securityDefinitions")
    else:
        schemes = (spec.doc.get("components") or {}).get("securitySchemes")
    schemes = schemes if isinstance(schemes, dict) else {}
    for name in first:
        scheme = spec.deref(schemes.get(name))
        if not isinstance(scheme, dict):
            continue
        kind = scheme.get("type")
        http_scheme = str(scheme.get("scheme", "")).lower()
        if (kind == "http" and http_scheme == "bearer") or kind in ("oauth2", "openIdConnect"):
            _set_header(headers, "Authorization", "Bearer {{token}}")
            if kind != "http":
                notes.append(f"{'OAuth 2.0' if kind == 'oauth2' else 'OpenID Connect'} 认证按 Bearer {{{{token}}}} 导入，取 token 的接口需要自己建")
        elif (kind == "http" and http_scheme == "basic") or kind == "basic":
            _set_header(headers, "Authorization", "Basic {{basicAuth}}")
            notes.append("Basic 认证按变量 basicAuth 导入，它的值是 base64(用户名:密码)")
        elif kind == "apiKey":
            key = _text(scheme.get("name"))
            if not key:
                continue
            value = "{{" + _var_name(key) + "}}"
            where = scheme.get("in")
            if where == "header":
                _set_header(headers, key, value)
            elif where == "query":
                query.append((key, value))
            elif where == "cookie":
                _append_cookie(headers, key, value)
        else:
            notes.append(f"认证方式 {kind or name} 不支持，没有导入")


def _append_cookie(headers: dict, name: str, value: str) -> None:
    current = next((v for k, v in headers.items() if k.lower() == "cookie"), "")
    _set_header(headers, "Cookie", f"{current}; {name}={value}" if current else f"{name}={value}")


_JSON_TYPE = re.compile(r"^application/([\w.+-]*\+)?json\b|^\*/\*$", re.I)


def _pick_media(content: dict) -> str | None:
    types = [t for t in content if isinstance(t, str)]
    for test in (
        lambda t: _JSON_TYPE.match(t),
        lambda t: t.lower().startswith("application/x-www-form-urlencoded"),
        lambda t: t.lower().startswith("multipart/form-data"),
        lambda t: t.lower().startswith(("text/", "application/xml")),
    ):
        for t in types:
            if test(t):
                return t
    return types[0] if types else None


def _media_example(spec: _Spec, media: dict) -> Any:
    if "example" in media:
        return spec.copy(media["example"])
    examples = media.get("examples")
    if isinstance(examples, dict):
        for item in examples.values():
            item = spec.deref(item)
            if isinstance(item, dict) and "value" in item:
                return spec.copy(item["value"])
    return spec.example(media.get("schema"))


def _form_body(spec: _Spec, api: dict, schema: Any, multipart: bool, encoding: dict, notes: list[str]) -> None:
    files: list[str] = []
    for name, prop in spec.properties(schema):
        content_type = _text((encoding.get(name) or {}).get("contentType")) if isinstance(encoding, dict) else ""
        if multipart and (_is_file_schema(prop) or content_type.startswith(("image/", "application/octet-stream"))):
            api["form"].append({"name": name, "type": "file", "value": "", "fileId": None})
            files.append(name)
        else:
            value = spec.example(prop)
            api["form"].append({"name": name, "type": "text", "value": _scalar(value), "fileId": None})
    _finish_form(api, multipart, files, notes)


def _finish_form(api: dict, multipart: bool, files: list[str], notes: list[str]) -> None:
    """表单项的文件要在页面上选：有文件项时先按 raw（不发送表单）保存，选好文件再把请求体类型切回 form-data。"""
    if files:
        api["bodyType"] = "raw"
        notes.append(f"form-data 里有文件项 {'、'.join(files)}：选好文件后把请求体类型切回 form-data")
    else:
        api["bodyType"] = "multipart" if multipart else "form"


def _openapi_body(spec: _Spec, op: dict, api: dict, notes: list[str]) -> None:
    body = spec.deref(op.get("requestBody"))
    if not isinstance(body, dict) or not isinstance(body.get("content"), dict) or not body["content"]:
        return
    media_type = _pick_media(body["content"])
    media = spec.deref(body["content"].get(media_type)) if media_type else None
    if not isinstance(media, dict):
        media = {}
    lower = (media_type or "").lower()
    if lower.startswith("application/x-www-form-urlencoded") or lower.startswith("multipart/form-data"):
        _form_body(spec, api, media.get("schema"), lower.startswith("multipart"), media.get("encoding") or {}, notes)
        return
    value = _media_example(spec, media)
    if _JSON_TYPE.match(media_type or ""):
        api["body"] = json.dumps({} if value is None else value, ensure_ascii=False, indent=2, default=str)
        _set_header(api["headers"], "Content-Type", "application/json" if media_type == "*/*" else media_type)
    elif lower.startswith(("text/", "application/xml")):
        api["body"] = value if isinstance(value, str) else ("" if value is None else _scalar(value))
        _set_header(api["headers"], "Content-Type", media_type)
    else:
        notes.append(f"请求体类型 {media_type} 不支持，没有导入请求体")


def _swagger_body(spec: _Spec, op: dict, params: list[dict], api: dict, notes: list[str]) -> None:
    consumes = op.get("consumes") or spec.doc.get("consumes") or []
    consumes = [c for c in consumes if isinstance(c, str)]
    body_param = next((p for p in params if p.get("in") == "body"), None)
    form_params = [p for p in params if p.get("in") == "formData"]
    if body_param is not None:
        media_type = next((c for c in consumes if _JSON_TYPE.match(c)), consumes[0] if consumes else "application/json")
        value = spec.copy(body_param["x-example"]) if "x-example" in body_param else spec.example(body_param.get("schema"))
        if _JSON_TYPE.match(media_type):
            api["body"] = json.dumps({} if value is None else value, ensure_ascii=False, indent=2, default=str)
            _set_header(api["headers"], "Content-Type", "application/json" if media_type == "*/*" else media_type)
        else:
            api["body"] = value if isinstance(value, str) else _scalar(value)
            _set_header(api["headers"], "Content-Type", media_type)
    elif form_params:
        multipart = any(p.get("type") == "file" for p in form_params) or any(
            c.lower().startswith("multipart/form-data") for c in consumes
        )
        files: list[str] = []
        for p in form_params:
            name = _text(p.get("name"))
            if not name:
                continue
            if p.get("type") == "file":
                api["form"].append({"name": name, "type": "file", "value": "", "fileId": None})
                files.append(name)
            else:
                value = _param_value(spec, p)
                if value is None and p.get("required"):
                    value = "{{" + _var_name(name) + "}}"
                api["form"].append({"name": name, "type": "text", "value": _scalar(value), "fileId": None})
        _finish_form(api, multipart, files, notes)


def _expect_status(responses: Any) -> int:
    if not isinstance(responses, dict):
        return 200
    codes = sorted(int(str(k)) for k in responses if str(k).isdigit() and 200 <= int(str(k)) < 300)
    return codes[0] if codes else 200


def _parse_openapi(doc: dict, swagger: bool, source_url: str | None) -> _Out:
    spec = _Spec(doc, _Budget())
    info = doc.get("info") if isinstance(doc.get("info"), dict) else {}
    title = _text(info.get("title")) or ("Swagger" if swagger else "OpenAPI")
    label = "Swagger 2.0" if swagger else f"OpenAPI {doc.get('openapi')}"
    out = _Out("swagger" if swagger else "openapi", label, title)
    root = out.folder(title, None)
    paths = doc.get("paths") if isinstance(doc.get("paths"), dict) else {}
    ops: list[tuple[str, dict, str, dict]] = []
    for raw_path, item in paths.items():
        item = spec.deref(item)
        if isinstance(item, dict):
            ops += [(str(raw_path), item, m, item[m]) for m in _HTTP_METHODS if isinstance(item.get(m), dict)]

    def first_tag(op: dict) -> str:
        tags = op.get("tags")
        return _text(tags[0]) if isinstance(tags, list) and tags else ""

    # 一个标签一个文件夹，按文档 tags 里声明的顺序，没声明的按出现顺序排在后面
    declared = [_text(t.get("name")) for t in doc.get("tags") or [] if isinstance(t, dict)]
    used = list(dict.fromkeys(t for t in (first_tag(op) for *_, op in ops) if t))
    used.sort(key=lambda t: declared.index(t) if t in declared else len(declared))
    tag_folders = {t: out.folder(t, root) for t in used}

    doc_origin, doc_prefix = _swagger_base(doc, source_url) if swagger else _servers(spec, source_url, doc.get("servers"))
    out.base_url(doc_origin)
    for raw_path, item, method, op in ops:
        upper = method.upper()
        label_text = f"{upper} {raw_path}"
        if upper not in METHODS:
            out.skipped.append({"name": _text(op.get("summary")) or label_text, "reason": f"不支持 {upper} 方法"})
            continue
        notes: list[str] = []
        if swagger:
            origin, prefix = doc_origin, doc_prefix
        else:
            origin, prefix = _servers(spec, source_url, op.get("servers"), item.get("servers"), doc.get("servers"))
            out.base_url(origin)
        # 路径级参数被操作级的同名同位置参数覆盖
        merged: dict[tuple[str, str], dict] = {}
        for p in [*(item.get("parameters") or []), *(op.get("parameters") or [])]:
            p = spec.deref(p)
            if isinstance(p, dict) and _text(p.get("name")) and isinstance(p.get("in"), str):
                merged[(p["in"], _text(p["name"]))] = p
        params = list(merged.values())
        path = re.sub(r"\{([^{}/]+)\}", lambda m: "{{" + _var_name(m.group(1)) + "}}", str(raw_path))
        api = _blank_api(_text(op.get("summary")) or _text(op.get("operationId")) or label_text, upper, prefix + path)
        query: list[tuple[str, str]] = []
        optional: list[str] = []
        for p in params:
            where, name = p["in"], _text(p["name"])
            if where in ("path", "body", "formData"):
                continue
            value = _param_value(spec, p)
            if not p.get("required"):
                if where != "cookie":  # 可选的 Cookie 多半是会话（FastAPI 会给每个接口都列出来），不提示
                    optional.append(name)
                continue
            text = _scalar(value) if value is not None else "{{" + _var_name(name) + "}}"
            if where == "query":
                query.append((name, text))
            elif where == "header":
                _set_header(api["headers"], name, text)
            elif where == "cookie":
                _append_cookie(api["headers"], name, text)
        _security(spec, op, swagger, api["headers"], query, notes)
        api["path"] = _with_query(api["path"], query)
        if swagger:
            _swagger_body(spec, op, params, api, notes)
        else:
            _openapi_body(spec, op, api, notes)
        api["expectStatus"] = _expect_status(op.get("responses"))
        if optional:
            notes.append("可选参数没有导入：" + "、".join(optional))
        if op.get("deprecated"):
            notes.append("文档标记为已废弃")
        out.api(tag_folders.get(first_tag(op), root), api, notes, _text(op.get("description")))
    if spec.external:
        out.warnings.append("外部文件里的定义没有展开：" + "、".join(sorted(spec.external)[:5]))
    return out


# ---------- Postman Collection v2.0 / v2.1 ----------

_PM_LANGUAGE_TYPES = {
    "json": "application/json", "xml": "application/xml", "html": "text/html",
    "text": "text/plain", "javascript": "application/javascript",
}
# 由 HTTP 客户端生成，存进接口定义反而有害（和 cURL 导入一致）
_DROP_HEADERS = {"host", "content-length", "connection", "accept-encoding"}
_PM_URL = re.compile(r"^(?:([A-Za-z][\w+.-]*)://)?([^/?#]*)([^?#]*)(?:\?([^#]*))?")
_PM_PATH_VAR = re.compile(r"(?<=/):([A-Za-z_][\w-]*)")

# 测试脚本里"把响应里的值存成变量"的常见写法，转换成提取规则；脚本本身不导入（ADR-006 不支持脚本）
_ACCESS = r"((?:\s*\.\s*[A-Za-z_$][\w$]*|\s*\[\s*(?:\d+|'[\w-]+'|\"[\w-]+\")\s*\])+)"
_SET = r"""(?:\.set|\bset(?:Environment|Global)Variable)\(\s*(['"])(\w+)\1\s*,\s*"""
_SET_FROM_ALIAS = re.compile(_SET + r"([A-Za-z_$][\w$]*)" + _ACCESS + r"\s*\)")
_SET_FROM_JSON = re.compile(_SET + r"(?:pm\.response\.json\(\s*\)|JSON\.parse\(\s*responseBody\s*\))" + _ACCESS + r"\s*\)")
_SET_FROM_HEADER = re.compile(_SET + r"""pm\.response\.headers\.get\(\s*(['"])([\w-]+)\3\s*\)\s*\)""")
_JSON_ALIAS = re.compile(
    r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:pm\.response\.json\(\s*\)|JSON\.parse\(\s*responseBody\s*\))"
)


def _gjson_path(access: str) -> str:
    parts = re.findall(r"\.\s*([A-Za-z_$][\w$]*)|\[\s*(\d+)\s*\]|\[\s*['\"]([\w-]+)['\"]\s*\]", access)
    return ".".join(a or b or c for a, b, c in parts)


def _script_text(event: dict) -> str:
    script = event.get("script") if isinstance(event.get("script"), dict) else {}
    lines = script.get("exec")
    if isinstance(lines, list):
        return "\n".join(str(x) for x in lines)
    return lines if isinstance(lines, str) else ""


def _script_extracts(script: str) -> list[dict]:
    aliases = set(_JSON_ALIAS.findall(script))
    found: dict[str, dict] = {}
    for m in _SET_FROM_JSON.finditer(script):
        found[m.group(2)] = {"var": m.group(2), "from": "json", "expr": _gjson_path(m.group(3))}
    for m in _SET_FROM_ALIAS.finditer(script):
        if m.group(3) in aliases:
            found[m.group(2)] = {"var": m.group(2), "from": "json", "expr": _gjson_path(m.group(4))}
    for m in _SET_FROM_HEADER.finditer(script):
        found[m.group(2)] = {"var": m.group(2), "from": "header", "expr": m.group(4)}
    return [e for e in found.values() if e["expr"]]


def _pm_text(value: Any) -> str:
    """Postman 的 description 可以是字符串，也可以是 {content, type}。"""
    if isinstance(value, dict):
        value = value.get("content")
    return _text(value)


def _pm_rows(value: Any) -> tuple[list[tuple[str, str]], list[str]]:
    """[{key, value, disabled}] → (启用的行, 禁用的名称)。"""
    rows: list[tuple[str, str]] = []
    disabled: list[str] = []
    for row in value if isinstance(value, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get("key"), str) or not row["key"].strip():
            continue
        if row.get("disabled"):
            disabled.append(row["key"].strip())
        else:
            rows.append((row["key"].strip(), _scalar(row.get("value"))))
    return rows, disabled


def _pm_auth_params(auth: dict, kind: str) -> dict[str, str]:
    raw = auth.get(kind)
    if isinstance(raw, list):  # v2.1：[{key, value, type}]
        return {str(i.get("key")): _scalar(i.get("value")) for i in raw if isinstance(i, dict)}
    if isinstance(raw, dict):  # v2.0：{key: value}
        return {str(k): _scalar(v) for k, v in raw.items()}
    return {}


def _pm_auth(auth: Any, headers: dict, query: list, notes: list[str]) -> None:
    if not isinstance(auth, dict):
        return
    kind = auth.get("type")
    if kind in (None, "noauth"):
        return
    p = _pm_auth_params(auth, kind)
    if kind == "bearer":
        token = p.get("token", "").strip()
        if not token:
            token = "{{token}}"
            notes.append("Bearer token 为空，按变量 token 导入")
        _set_header(headers, "Authorization", f"Bearer {token}")
    elif kind == "basic":
        _set_header(headers, "Authorization", _basic(p.get("username", ""), p.get("password", ""), notes))
    elif kind == "apikey":
        key = p.get("key", "").strip()
        if key:
            if p.get("in") == "query":
                query.append((key, p.get("value", "")))
            else:
                _set_header(headers, key, p.get("value", ""))
    elif kind == "oauth2":
        token = p.get("accessToken", "").strip()
        if not token:
            token = "{{token}}"
            notes.append("OAuth 2.0 认证按 Bearer {{token}} 导入，取 token 的接口需要自己建")
        if p.get("addTokenTo") == "queryParams":
            query.append(("access_token", token))
        else:
            _set_header(headers, "Authorization", f"{p.get('headerPrefix') or 'Bearer'} {token}")
    else:
        notes.append(f"认证方式 {kind} 不支持，没有导入")


def _pm_url(url: Any, variables: dict[str, str], notes: list[str]) -> tuple[str | None, str, list[tuple[str, str]], list[str]]:
    """返回 (原地址的协议 + 主机, 路径, 启用的 query, 禁用的 query 名称)。"""
    structured = url if isinstance(url, dict) else None
    raw = url if isinstance(url, str) else _text(structured.get("raw")) if structured else ""
    if not raw and structured:
        host = structured.get("host")
        host = ".".join(str(h) for h in host) if isinstance(host, list) else _text(host)
        segs = structured.get("path")
        path = "/".join(str(s) if not isinstance(s, dict) else _text(s.get("value")) for s in segs) if isinstance(segs, list) else _text(segs)
        protocol = _text(structured.get("protocol"))
        raw = f"{protocol + '://' if protocol else ''}{host}/{path.lstrip('/')}"
    m = _PM_URL.match(raw.strip())
    scheme, host, path, raw_query = (m.group(1), m.group(2), m.group(3), m.group(4)) if m else (None, "", raw, None)
    if structured and isinstance(structured.get("query"), list):
        query, disabled = _pm_rows(structured["query"])
    else:
        query, disabled = [], []
        for part in (raw_query or "").split("&"):
            if part:
                k, _, v = part.partition("=")
                query.append((k, v))
    path_values = {}
    if structured:
        for row in structured.get("variable") or []:
            if isinstance(row, dict) and isinstance(row.get("key"), str):
                path_values[row["key"]] = _scalar(row.get("value"))
    path = _PM_PATH_VAR.sub(lambda v: path_values.get(v.group(1)) or "{{" + _var_name(v.group(1)) + "}}", path or "/")
    if not path.startswith("/"):
        path = "/" + path
    origin = None
    if host:
        whole = re.fullmatch(r"\{\{\s*([^{}]+?)\s*\}\}", host)
        if whole and scheme is None:
            origin = variables.get(whole.group(1)) or host
            if path == "/" and not query:
                notes.append(f"地址只有变量 {host}，路径按 / 导入")
        else:
            origin = f"{scheme or 'http'}://{host}"
    return origin, path, query, disabled


def _pm_body(body: Any, api: dict, notes: list[str]) -> None:
    if not isinstance(body, dict) or body.get("disabled"):
        return
    mode = body.get("mode")
    headers = api["headers"]
    if mode == "raw":
        api["body"] = _scalar(body.get("raw"))
        language = (((body.get("options") or {}).get("raw") or {}) if isinstance(body.get("options"), dict) else {}).get("language")
        if api["body"].strip() and not _has_header(headers, "Content-Type") and language in _PM_LANGUAGE_TYPES:
            headers["Content-Type"] = _PM_LANGUAGE_TYPES[language]
    elif mode in ("urlencoded", "formdata"):
        multipart = mode == "formdata"
        files: list[str] = []
        for row in body.get(mode) or []:
            if not isinstance(row, dict) or not _text(row.get("key")) or row.get("disabled"):
                continue
            name = _text(row["key"])
            if multipart and row.get("type") == "file":
                api["form"].append({"name": name, "type": "file", "value": "", "fileId": None})
                files.append(name)
            else:
                api["form"].append({"name": name, "type": "text", "value": _scalar(row.get("value")), "fileId": None})
        for name in [k for k in headers if k.lower() == "content-type"]:
            del headers[name]  # 引擎按请求体类型生成（multipart 要带 boundary）
        _finish_form(api, multipart, files, notes)
    elif mode == "graphql":
        gql = body.get("graphql") if isinstance(body.get("graphql"), dict) else {}
        variables: Any = gql.get("variables") or {}
        if isinstance(variables, str):
            try:
                variables = json.loads(variables) if variables.strip() else {}
            except ValueError:
                notes.append("GraphQL variables 不是合法的 JSON，没有导入")
                variables = {}
        api["body"] = json.dumps({"query": _scalar(gql.get("query")), "variables": variables}, ensure_ascii=False, indent=2)
        _set_header(headers, "Content-Type", "application/json")
    elif mode == "file":
        notes.append("请求体是二进制文件，不支持，没有导入请求体")


def _parse_postman(doc: dict) -> _Out:
    budget = _Budget()
    info = doc.get("info") if isinstance(doc.get("info"), dict) else {}
    schema = _text(info.get("schema"))
    version = "v2.1" if "v2.1" in schema else "v2.0" if "v2.0" in schema else "v2"
    title = _text(info.get("name")) or "Postman Collection"
    out = _Out("postman", f"Postman Collection {version}", title)
    variables: dict[str, str] = {}
    for row in doc.get("variable") or []:
        if isinstance(row, dict) and isinstance(row.get("key"), str) and row["key"].strip() and not row.get("disabled"):
            variables[row["key"].strip()] = _scalar(row.get("value"))
    out.variables = [{"name": k, "value": v} for k, v in variables.items()]
    scripted_groups: list[str] = []

    def walk(items: Any, folder: str, auth: Any, depth: int) -> None:
        if depth > 32:
            raise bad_request("文件夹嵌套太深")
        for item in items if isinstance(items, list) else []:
            budget.spend()
            if not isinstance(item, dict):
                continue
            name = _text(item.get("name"))
            if isinstance(item.get("item"), list):
                if any(_script_text(e).strip() for e in item.get("event") or [] if isinstance(e, dict)):
                    scripted_groups.append(name or "未命名文件夹")
                walk(item["item"], out.folder(name, folder), item.get("auth", auth), depth + 1)
                continue
            request = item.get("request")
            if isinstance(request, str):
                request = {"method": "GET", "url": request}
            if not isinstance(request, dict):
                continue
            method = (_text(request.get("method")) or "GET").upper()
            notes: list[str] = []
            origin, path, query, disabled_query = _pm_url(request.get("url"), variables, notes)
            label_text = name or f"{method} {path}"
            if method not in METHODS:
                out.skipped.append({"name": label_text, "reason": f"不支持 {method} 方法"})
                continue
            out.base_url(origin)
            api = _blank_api(label_text, method, path.split("?")[0])
            header_rows, disabled_headers = _pm_rows(request.get("header"))
            if isinstance(request.get("header"), str):
                for line in request["header"].splitlines():
                    k, sep, v = line.partition(":")
                    if sep and k.strip():
                        header_rows.append((k.strip(), v.strip()))
            for k, v in header_rows:
                if k.lower() not in _DROP_HEADERS:
                    _set_header(api["headers"], k, v)
            _pm_auth(request["auth"] if "auth" in request else auth, api["headers"], query, notes)
            api["path"] = _with_query(api["path"], query)
            _pm_body(request.get("body"), api, notes)
            codes = sorted(
                r["code"] for r in item.get("response") or []
                if isinstance(r, dict) and is_int(r.get("code")) and 200 <= r["code"] < 300
            )
            if codes:
                api["expectStatus"] = codes[0]
            for event in item.get("event") or []:
                if not isinstance(event, dict) or not _script_text(event).strip():
                    continue
                if event.get("listen") == "test":
                    extracts = _script_extracts(_script_text(event))
                    api["extracts"] = extracts
                    if extracts:
                        pairs = "、".join(f"{e['var']} ← {e['expr']}" for e in extracts)
                        notes.append(f"测试脚本里的赋值转成了提取：{pairs}；脚本本身没有导入")
                    else:
                        notes.append("测试脚本没有导入")
                else:
                    notes.append("前置脚本没有导入")
            if disabled_headers or disabled_query:
                notes.append("禁用的行没有导入：" + "、".join([*disabled_headers, *disabled_query]))
            out.api(folder, api, notes, _pm_text(request.get("description")))

    root = out.folder(title, None)
    if any(_script_text(e).strip() for e in doc.get("event") or [] if isinstance(e, dict)):
        scripted_groups.insert(0, title)
    walk(doc.get("item"), root, doc.get("auth"), 0)
    if scripted_groups:
        out.warnings.append("集合 / 文件夹上的脚本没有导入：" + "、".join(scripted_groups[:5]))
    return out


# ---------- 路由 ----------

def _source(payload: dict) -> tuple[str, str | None]:
    """返回 (文档内容, 文档地址)。"""
    url, text = payload.get("url"), payload.get("text")
    if isinstance(url, str) and url.strip():
        return _fetch(url.strip()), url.strip()
    if isinstance(text, str):
        return text, None
    raise bad_request("text（文档内容）和 url（文档地址）要给一个")


@router.post("/preview", summary="解析文档，不保存")
def preview_import(payload: Any = Body(...)):
    if not isinstance(payload, dict):
        raise bad_request("请求体必须是 JSON 对象")
    text, source_url = _source(payload)
    doc = _load(text)
    fmt = _detect(doc)
    out = _parse_postman(doc) if fmt == "postman" else _parse_openapi(doc, fmt == "swagger", source_url)
    with db.connect() as conn:
        existing: dict[tuple[str, str], dict] = {}
        for row in conn.execute("SELECT id, name, method, path FROM apis ORDER BY id"):
            existing.setdefault((row["method"], row["path"]), {"id": row["id"], "name": row["name"]})
        for item in out.apis:
            item["duplicateOf"] = existing.get((item["api"]["method"], item["api"]["path"]))
            try:
                validate_api({**item["api"], "folderId": None}, conn)
                item["problems"] = []
            except ApiError as e:
                item["problems"] = e.details or [e.message]
    used = {item["folderKey"] for item in out.apis}
    # 只留下装着接口的文件夹（和它们的上级）
    parents = {f["key"]: f["parentKey"] for f in out.folders}
    keep: set[str] = set()
    for key in used:
        while key is not None and key not in keep:
            keep.add(key)
            key = parents.get(key)
    return {
        "format": out.fmt,
        "formatLabel": out.label,
        "title": out.title,
        "baseUrls": out.base_urls,
        "variables": out.variables,
        "folders": [f for f in out.folders if f["key"] in keep],
        "apis": out.apis,
        "skipped": out.skipped,
        "warnings": out.warnings,
    }


@router.post("", status_code=201, summary="导入：新建文件夹和接口，全部成功或全部不做")
def import_apis(payload: Any = Body(...)):
    if not isinstance(payload, dict):
        raise bad_request("请求体必须是 JSON 对象")
    folders, apis = payload.get("folders", []), payload.get("apis")
    if not isinstance(folders, list) or not isinstance(apis, list):
        raise bad_request("folders 和 apis 必须是数组")
    if not apis:
        raise bad_request("没有要导入的接口")
    if len(apis) > MAX_APIS:
        raise bad_request(f"一次最多导入 {MAX_APIS} 个接口")
    errors: list[str] = []
    with db.connect() as conn:
        target = payload.get("folderId")
        if target is not None and (
            not is_int(target) or conn.execute("SELECT 1 FROM folders WHERE id = ?", (target,)).fetchone() is None
        ):
            raise bad_request(f"folderId 指向的文件夹 #{target} 不存在")
        ids: dict[str, int] = {}
        for i, f in enumerate(folders, 1):
            if not isinstance(f, dict) or not isinstance(f.get("key"), str):
                errors.append(f"folders 第 {i} 项必须是带 key 的对象")
                continue
            parent_key = f.get("parentKey")
            if parent_key is not None and parent_key not in ids:
                errors.append(f"文件夹「{f.get('name')}」的 parentKey 必须指向排在它前面的文件夹")
                continue
            try:
                data = validate_folder(
                    {"name": f.get("name"), "parentId": ids[parent_key] if parent_key is not None else target, "note": ""},
                    conn,
                )
            except ApiError as e:
                errors.extend(f"文件夹「{f.get('name')}」：{d}" for d in e.details or [e.message])
                continue
            ids[f["key"]] = resources.insert(conn, resources.FOLDERS, data)
        created: list[int] = []
        for i, item in enumerate(apis, 1):
            if not isinstance(item, dict):
                errors.append(f"apis 第 {i} 项必须是对象")
                continue
            folder_key = item.get("folderKey")
            if folder_key is not None and folder_key not in ids:
                errors.append(f"接口「{item.get('name')}」的 folderKey 指向的文件夹不存在")
                continue
            data = {k: v for k, v in item.items() if k not in ("folderKey", "id")}
            data["folderId"] = ids[folder_key] if folder_key is not None else target
            try:
                clean = validate_api(data, conn)
            except ApiError as e:
                errors.extend(f"接口「{item.get('name')}」：{d}" for d in e.details or [e.message])
                continue
            created.append(resources.insert(conn, resources.APIS, clean))
        if errors:
            raise bad_request("导入失败，没有导入任何内容", errors[:50])
    return {"folderIds": list(ids.values()), "apiIds": created}
