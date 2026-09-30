# 用法：source scripts/env.sh
# 把项目自带的 Node 和 k6 放到 PATH 最前面。
_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$_root/.tools/node/bin:$_root/.tools/bin:$PATH"
unset _root
