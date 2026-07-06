from dataclasses import dataclass


@dataclass(frozen=True)
class DemoPrincipal:
    user_id: str
    role: str


def get_demo_principal(role: str = "admin") -> DemoPrincipal:
    return DemoPrincipal(user_id="demo_admin", role=role)
