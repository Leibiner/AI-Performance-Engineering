"""种子数据：只在全新的库里写入一次。走和接口相同的校验，保证种子数据本身符合契约。"""

from . import db
from .resources import APIS, ENVIRONMENTS, FLOWS, PROFILES, TESTS, Resource, insert

# 执行引擎一方对百度实测过的请求头：这个 User-Agent 能让“期望包含 百度”通过；
# Accept-Encoding 让响应走 gzip，减少流量。
_BAIDU_HEADERS = {"User-Agent": "Mozilla/5.0 k6-mvp", "Accept-Encoding": "gzip"}


def seed() -> None:
    with db.connect() as conn:

        def add(res: Resource, payload: dict) -> int:
            return insert(conn, res, res.validate(payload, conn))

        add(ENVIRONMENTS, {
            "name": "百度（仅冒烟）",
            "baseUrl": "https://www.baidu.com",
            "headers": _BAIDU_HEADERS,
            "maxVus": 2, "maxRate": 2, "maxDurationSec": 60,
            "note": "第三方线上站点，只允许冒烟级别流量。不要调高这里的上限",
        })
        api_id = add(APIS, {
            "name": "百度首页", "method": "GET", "path": "/",
            "headers": {}, "body": None,
            "expectStatus": 200, "expectBodyContains": "百度",
            "extracts": [], "note": "",
        })
        flow_id = add(FLOWS, {
            "name": "访问首页", "note": "",
            "steps": [{"apiId": api_id, "thinkTimeMs": 500}],
        })
        add(PROFILES, {
            "name": "冒烟", "type": "smoke", "model": "closed",
            "config": {"vus": 1, "iterations": 10, "maxDurationSec": 30},
            "note": "1 个并发跑 10 次迭代，确认脚本和目标都正常",
        })
        add(PROFILES, {
            "name": "低速恒定到达率", "type": "average", "model": "open",
            "config": {"rate": 1, "durationSec": 20, "preAllocatedVus": 2},
            "note": "每秒 1 次迭代，持续 20 秒",
        })
        add(PROFILES, {
            "name": "压力示例（会被百度环境拒绝）", "type": "stress", "model": "open",
            "config": {"rate": 50, "durationSec": 120, "preAllocatedVus": 100},
            "note": "超过百度环境的上限，用来演示预检拒绝",
        })
        add(TESTS, {
            "name": "百度首页冒烟", "note": "",
            "flows": [{"flowId": flow_id, "weight": 1}],
            "slo": {"p95Ms": 2000, "p99Ms": None, "errorRate": 0.01, "checksRate": 0.99},
        })
