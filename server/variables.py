"""变量来源检查（契约 §3.2 第 8 条）：正式运行和流程试跑启动 k6 之前，确认每个 {{引用}} 都有来源。

按执行顺序检查：流程变量（每次迭代开始时按顺序求值）→ 初始化段 → 每次迭代的步骤。
来源：被测环境的变量、绑定的数据集的列、流程变量、前面步骤的提取；{{$名称}} 必须是认识的动态变量。
"""

import re
from typing import Any

# 和执行引擎（perf/core/interp.js 的 VAR_PATTERN）认出的引用要一致。JS 的 \s 和 Python 的不一样
# （Python 多 \x1c-\x1f、\x85，少 \ufeff），所以把 JS 的空白字符类显式写出来
_JS_WS = "\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
REF_RE = re.compile(r"\{\{[" + _JS_WS + r"]*(\$?[^{}()" + _JS_WS + r"]+(?:\([^{}()]*\))?)[" + _JS_WS + r"]*\}\}")

DYNAMIC = (
    "timestamp", "timestampMs", "isoTimestamp", "date", "uuid", "guid", "randomUUID",
    "randomInt", "randomString", "vu", "iteration", "runId",
)
_NO_ARGS = {"timestamp", "timestampMs", "isoTimestamp", "uuid", "guid", "randomUUID", "vu", "iteration", "runId"}
_DYNAMIC_RE = re.compile(r"^\$([A-Za-z]+)(?:\(([^{}()]*)\))?$")
_INT_RE = re.compile(r"^-?[0-9]+$")  # 和引擎一样只认 ASCII 数字，\d 会放过全角数字
_MAX_SAFE = 2**53 - 1  # JS 的 Number.isSafeInteger


def _safe_int(text: str) -> int | None:
    return int(text) if _INT_RE.match(text) and abs(int(text)) <= _MAX_SAFE else None


def dynamic_problem(ref: str) -> str | None:
    """动态变量的写法是否会被引擎认出来（参数规则和 perf/core/interp.js 的 DYNAMIC 一致）。
    返回 None 表示没问题；"unknown" 表示没有这个动态变量；其他是参数的问题。"""
    m = _DYNAMIC_RE.match(ref)
    if not m or m.group(1) not in DYNAMIC:
        return "unknown"
    name, raw = m.group(1), (m.group(2) or "").strip()
    args = [a.strip() for a in raw.split(",")] if raw else []
    if name == "date" or not args:
        return None
    if name in _NO_ARGS:
        return f"${name} 不接受参数"
    if name == "randomInt":
        low, high = (_safe_int(args[0]), _safe_int(args[1])) if len(args) == 2 else (None, None)
        if low is None or high is None or low > high:
            return "$randomInt 的参数是 (最小,最大)，两个整数且最小不大于最大"
        return None
    length = _safe_int(args[0]) if len(args) == 1 else None
    if length is None or not 1 <= length <= 256:
        return "$randomString 的参数是长度，1–256 之间的整数"
    return None


def refs(text: Any) -> list[str]:
    """文本里的引用名称（花括号里去掉两端空白的部分），按出现顺序。"""
    if not isinstance(text, str) or "{{" not in text:
        return []
    return [m.group(1) for m in REF_RE.finditer(text)]


def _merged_headers(env_headers: dict, api_headers: dict) -> dict:
    """和引擎一样合并请求头：名称不区分大小写，接口的覆盖环境的。"""
    out: dict[str, str] = {}
    index: dict[str, str] = {}
    for source in (env_headers or {}, api_headers or {}):
        for name, value in source.items():
            lower = name.lower()
            if lower in index:
                del out[index[lower]]
            index[lower] = name
            out[name] = value
    return out


def step_refs(api: dict, env_headers: dict) -> tuple[list[str], list[str]]:
    """一步里会被替换的位置上的引用，去重后按出现顺序，分两组返回：
    (接口自己的：path、接口的请求头、发送的请求体、期望文本；
     只来自被测环境公共请求头的：接口没有用同名请求头覆盖的那些)。"""
    body_type = api.get("bodyType") or "raw"
    own_headers = api.get("headers") or {}
    own_names = {name.lower() for name in own_headers}
    own_texts: list[Any] = [api.get("path")]
    env_texts: list[Any] = []
    for name, value in _merged_headers(env_headers, own_headers).items():
        # multipart 时引擎去掉合并后的 Content-Type，换成带 boundary 的；
        # x-www-form-urlencoded 时接口自己没写 Content-Type，引擎也会丢掉环境的
        if name.lower() == "content-type" and (
            body_type == "multipart" or (body_type == "form" and name.lower() not in own_names)
        ):
            continue
        (own_texts if name.lower() in own_names else env_texts).append(value)
    if body_type == "raw":
        own_texts.append(api.get("body"))
    else:
        for item in api.get("form") or []:
            own_texts.append(item.get("name"))
            if item.get("type") == "text":
                own_texts.append(item.get("value"))
    own_texts.append(api.get("expectBodyContains"))

    def collect(texts: list[Any], skip: list[str]) -> list[str]:
        out: list[str] = []
        for text in texts:
            for ref in refs(text):
                if ref not in out and ref not in skip:
                    out.append(ref)
        return out

    own = collect(own_texts, [])
    return own, collect(env_texts, own)


def _producer(outputs: list[list[str]], ref: str, start: int) -> int | None:
    """从下标 start 起第一个提取 ref 的步骤的下标。"""
    for index in range(start, len(outputs)):
        if ref in outputs[index]:
            return index
    return None


def source_problems(
    flow_name: str,
    env: dict,
    init_steps: list[tuple[dict, Any]],
    steps: list[tuple[dict, Any]],
    bindings: list[dict],
    variables: list[dict],
) -> list[str]:
    """一个流程里没有来源的引用，每个（位置, 名称）一条。env 是这次运行或试跑的被测环境。"""
    base = set((env.get("variables") or {}).keys())
    for binding in bindings:
        base.update(binding["dataset"]["columns"])
    flow_vars = [v["name"] for v in variables]
    init_out = [[ex["var"] for ex in api.get("extracts") or []] for api, _ in init_steps]
    main_out = [[ex["var"] for ex in api.get("extracts") or []] for api, _ in steps]
    init_names = [api["name"] for api, _ in init_steps]
    main_names = [api["name"] for api, _ in steps]
    reason = f"被测环境“{env['name']}”没有这个变量，数据集、流程变量和前面的步骤也不产出它"
    dynamic_list = "、".join(f"${name}" for name in DYNAMIC)
    problems: list[str] = []

    def check(where: str, ref: str, available: set[str], hint) -> None:
        if ref.startswith("$"):
            problem = dynamic_problem(ref)
            if problem == "unknown":
                problems.append(
                    f"业务流程“{flow_name}”{where}引用了 {{{{{ref}}}}}，但没有这个动态变量（支持：{dynamic_list}）"
                )
            elif problem:
                problems.append(f"业务流程“{flow_name}”{where}引用了 {{{{{ref}}}}}，但参数不对：{problem}")
            return
        if ref not in available:
            problems.append(f"业务流程“{flow_name}”{where}引用了 {{{{{ref}}}}}，但没有来源：{reason}{hint(ref)}")

    # 1) 流程变量：每次迭代开始时（取完数据集的行之后、初始化段之前）按顺序求值，只能用排在前面的
    for k, var in enumerate(variables):
        def var_hint(ref: str, k: int = k) -> str:
            if ref == flow_vars[k]:
                return "（流程变量不能引用它自己）"
            if ref in flow_vars[k + 1:]:
                return f"（流程变量 {ref} 定义在它后面，流程变量按顺序求值）"
            j = _producer(init_out, ref, 0)
            if j is not None:
                return f"（初始化第 {j + 1} 步「{init_names[j]}」会提取它，但流程变量在初始化段之前求值）"
            j = _producer(main_out, ref, 0)
            if j is not None:
                return f"（第 {j + 1} 步「{main_names[j]}」会提取它，但流程变量在每次迭代开始时求值，早于所有步骤）"
            return ""

        available = base | set(flow_vars[:k])
        for ref in refs(var["value"]):
            check(f"流程变量 {var['name']} ", ref, available, var_hint)

    env_headers = env.get("headers") or {}
    all_vars = base | set(flow_vars)
    # 公共请求头每一步都带。常见写法是 Authorization: Bearer {{token}}、token 由登录提取：
    # 登录这一步（以及它之前的步骤）发出的是未替换的原文，服务端不看，这是无害的。
    # 所以公共请求头里的引用只要求这个流程里某一处产出它，不要求排在这一步前面
    anywhere = all_vars | {v for out in init_out + main_out for v in out}
    header_refs: list[str] = []

    # 2) 初始化段：每个 VU 第一次迭代时在 steps 之前执行
    produced: set[str] = set()
    for i, (api, _) in enumerate(init_steps):
        def init_hint(ref: str, i: int = i) -> str:
            j = _producer(init_out, ref, i)
            if j == i:
                return "（这一步自己提取它，但一步自己的提取不能用在这一步的请求里）"
            if j is not None:
                return f"（初始化第 {j + 1} 步「{init_names[j]}」会提取它，但排在这一步之后）"
            j = _producer(main_out, ref, 0)
            if j is not None:
                return f"（第 {j + 1} 步「{main_names[j]}」会提取它，但初始化段在每次迭代的步骤之前执行）"
            return ""

        available = all_vars | produced
        own, inherited = step_refs(api, env_headers)
        for ref in own:
            check(f"初始化第 {i + 1} 步「{api['name']}」", ref, available, init_hint)
        header_refs.extend(ref for ref in inherited if ref not in header_refs)
        produced.update(init_out[i])

    # 3) 每次迭代的步骤：可以用初始化段的全部提取，和排在前面的步骤的提取
    all_vars |= produced
    produced = set()
    for i, (api, _) in enumerate(steps):
        def main_hint(ref: str, i: int = i) -> str:
            j = _producer(main_out, ref, i)
            if j == i:
                return "（这一步自己提取它，但一步自己的提取不能用在这一步的请求里）"
            if j is not None:
                return f"（第 {j + 1} 步「{main_names[j]}」会提取它，但排在这一步之后）"
            return ""

        available = all_vars | produced
        own, inherited = step_refs(api, env_headers)
        for ref in own:
            check(f"第 {i + 1} 步「{api['name']}」", ref, available, main_hint)
        header_refs.extend(ref for ref in inherited if ref not in header_refs)
        produced.update(main_out[i])

    # 公共请求头每一步都带，缺的只报一次
    where = f"使用的被测环境“{env['name']}”公共请求头"
    for ref in header_refs:
        if ref.startswith("$"):
            check(where, ref, anywhere, lambda _ref: "")
        elif ref not in anywhere:
            problems.append(
                f"业务流程“{flow_name}”{where}引用了 {{{{{ref}}}}}，但没有来源：被测环境没有这个变量，"
                "这个流程的数据集、流程变量和步骤也都不产出它"
            )
    return problems
