"""라우트 시그니처에서 반복되던 Depends 조합.

역할 별칭 하나가 여러 라우트에서 같은 `roles(...)` 객체를 공유하므로 FastAPI가
요청당 한 번만 평가한다. 동작은 라우트마다 `roles(...)`를 새로 만들던 때와 같다.
"""
from typing import Annotated

from fastapi import Depends, Header
from psycopg import Connection

from .db import database
from .security import current_user, current_visitor, festival_access, roles


Db = Annotated[Connection, Depends(database)]
User = Annotated[dict, Depends(current_user)]
Visitor = Annotated[dict, Depends(current_visitor)]
# 경로의 festival_id가 운영자 접근 범위인지 검사한다. 반환값은 대부분 쓰지 않는다.
Scope = Annotated[dict, Depends(festival_access)]

SuperAdmin = Annotated[dict, Depends(roles("SUPER_ADMIN"))]
Manager = Annotated[dict, Depends(roles("SUPER_ADMIN", "FESTIVAL_MANAGER"))]
Operator = Annotated[dict, Depends(roles("SUPER_ADMIN", "FESTIVAL_MANAGER", "FIELD_OPERATOR"))]
Reviewer = Annotated[dict, Depends(roles("SUPER_ADMIN", "REVIEWER"))]
ManagerOrReviewer = Annotated[dict, Depends(roles("SUPER_ADMIN", "FESTIVAL_MANAGER", "REVIEWER"))]
Merchant = Annotated[dict, Depends(roles("MERCHANT"))]

IfMatch = Annotated[str | None, Header(alias="If-Match")]
IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]
