# 用法：source scripts/env.sh
# 把项目自带的 Node 和 k6 放到 PATH 最前面。
_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$_root/.tools/node/bin:$_root/.tools/bin:$PATH"
unset _root
# k6 v2.3.0 遇到不认识的 import 时默认会联网向 Grafana 的构建服务请求下载扩展；关掉，未知 import 直接报错
export K6_AUTO_EXTENSION_RESOLUTION=false
