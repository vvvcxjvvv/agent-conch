"""9 大能力域的默认实现。

导入此包即触发所有域的 @registry.register 装饰器执行，
使所有默认实现注册到全局 registry。
"""
# 导入各域以触发注册（顺序无依赖，但按域编号导入便于阅读）
from conch.domains.information import *  # noqa: F401, F403
from conch.domains.tool import *  # noqa: F401, F403
from conch.domains.context import *  # noqa: F401, F403
from conch.domains.memory import *  # noqa: F401, F403
from conch.domains.orchestration import *  # noqa: F401, F403
from conch.domains.eval import *  # noqa: F401, F403
from conch.domains.observability import *  # noqa: F401, F403
from conch.domains.constraint import *  # noqa: F401, F403
from conch.domains.governance import *  # noqa: F401, F403
