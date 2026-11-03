"""All website routers, in the order they are mounted."""
from app.web import (routes_admin, routes_assistant, routes_auth, routes_phone, routes_practice, routes_public, routes_student,
                     routes_tools)

routers = [routes_auth.router, routes_phone.router, routes_public.router, routes_student.router, routes_practice.router,
           routes_tools.router, routes_assistant.router, routes_admin.router]
