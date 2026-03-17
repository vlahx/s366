from fastapi import Request, HTTPException
from starlette import status

async def login_required(request: Request):
    if not request.session.get("user_id"):
        # Pentru 401, de obicei vrem să-l trimitem la login direct, 
        # dar pentru acum lăsăm eroarea să fie prinsă de handler
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Trebuie să fii logat pentru a accesa această resursă."
        )
    return request.session.get("user_id")

async def superadmin_required(request: Request):
    await login_required(request)
    if request.session.get("role") != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acces interzis. Necesită privilegii de Superadmin."
        )
    return True

async def company_admin_required(request: Request):
    await login_required(request)
    role = request.session.get("role")
    company_id = request.session.get("company_id")

    if role == "superadmin":
        return True
    
    if role == "pending_admin":
        return True

    if role == "company_admin" and company_id:
        return True

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Acces neautorizat. Contactați administratorul pentru activare."
    )