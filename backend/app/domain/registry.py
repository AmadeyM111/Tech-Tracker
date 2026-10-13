"""Реестр моделей: импортирует все модули моделей, чтобы они попали в ``Base.metadata``.

Нужен Alembic (autogenerate, ``alembic check``). Каждая задача, добавляющая модели,
дописывает сюда импорт своего модуля.
"""

from app.domain.auth import models as auth_models  # noqa: F401
from app.domain.events import models as events_models  # noqa: F401
from app.domain.users import models as users_models  # noqa: F401
from app.domain.workspaces import models as workspaces_models  # noqa: F401
